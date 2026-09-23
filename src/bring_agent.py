"""Bring your agent: how a resident joins.

After login + consent, a resident copies dossier.IMPORT_PROMPT into the AI
that already knows them (ChatGPT, Claude, Muse, Instinct, ...) and pastes its
answer back. Two steps:
  preview -- validate the text, build the card the hub will read
             (dossier.build_card), and store both as a draft on the resident.
  confirm -- join with exactly the stored draft (never a card the browser
             sends back), marking the profile complete.

The pasted text becomes the dossier: the only thing the resident's Claw ever
knows about them (agent_talk.py). Both steps are logged to the neighborhood's
activity feed, and the card-building call itself to db.ai_calls (ai_log).
App.py's routes stay thin wrappers, same shape as my_match.py.
"""

import ai_log
import config
import db
import dossier


# each preview is a paid AI call; a handful is plenty to tweak and retry
MAX_PREVIEWS = 5
MAX_NAME_CHARS = 30


def status(resident):
    return {
        "joined": resident["profile_complete_at"] is not None,
        "name": resident.get("name"),
        "source": resident.get("dossier_source"),
        "card": resident.get("card"),
        "previews_left": _previews_left(resident),
        "import_prompt": dossier.IMPORT_PROMPT,
        "sources": dossier.SOURCES,
        "min_chars": dossier.MIN_DOSSIER_CHARS,
    }


def _previews_left(resident):
    left = MAX_PREVIEWS - resident.get("dossier_previews", 0)
    if left < 0:
        left = 0
    return left


def _clean_name(name):
    # first name only -- it's what other residents see after a mutual yes.
    if not isinstance(name, str):
        return None
    parts = name.strip().split()
    if len(parts) == 0:
        return None
    first = parts[0][:MAX_NAME_CHARS]
    return first


async def preview(resident, name, source, text, client=None):
    # returns (status dict, None) on success, or (None, a message for the person).
    if resident["profile_complete_at"] is not None:
        return None, "Your agent is already in. Nothing to change here."
    if _previews_left(resident) == 0:
        return None, "You've used all your previews. Join with your last card, or contact us to reset."
    first = _clean_name(name)
    if first is None:
        return None, "Add your first name."
    if source not in dossier.SOURCES:
        return None, "Pick which AI wrote this."
    problem = dossier.check_text(text)
    if problem is not None:
        return None, problem
    text = text.strip()[:dossier.MAX_DOSSIER_CHARS]
    # take the preview slot before the paid call, atomically -- parallel
    # requests can't slip past the cap
    if not db.claim_preview(resident["id"], MAX_PREVIEWS):
        return None, "You've used all your previews. Join with your last card, or contact us to reset."
    if client is None:
        client = config.get_client()
    logged = ai_log.LoggedClient(client, neighborhood_id=resident["neighborhood_id"], resident_id=resident["id"])
    card = await dossier.build_card(source, text, logged)
    updated = db.save_dossier_draft(resident["id"], first, source, text, card)
    db.log_event(None, "human", "human", first + " built their agent's card from " + source + _score_note(card) + ".",
                 None, resident["neighborhood_id"])
    return status(updated), None


def _score_note(card):
    score = card.get("real_vs_public")
    if score is None:
        return ""
    return " (real-you score " + str(score["score"]) + "/5)"


def confirm(resident):
    if resident["profile_complete_at"] is not None:
        return status(resident), None
    if resident.get("card") is None or not resident.get("dossier_text"):
        return None, "Build your agent's card first."
    # the hub check is scheduled by app.py's route, so this stays request-free and testable
    updated = db.mark_profile_complete(resident["id"])
    neighborhood = db.get_neighborhood(resident["neighborhood_id"])
    joined = len(db.list_complete_residents(resident["neighborhood_id"]))
    text = updated["name"] + " joined with their agent from " + updated["dossier_source"] + "."
    if neighborhood is not None:
        text = text + " " + str(joined) + " of " + str(neighborhood["batch_threshold"]) + " needed for the first round."
    db.log_event(None, "human", "human", text, None, resident["neighborhood_id"])
    return status(updated), None
