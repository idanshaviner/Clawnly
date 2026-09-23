"""Admin dashboard: neighborhood progress, resident status, recent hub
rounds with usage, each round's full behind-the-scenes record -- every hub
thought and decision, every agent message, every code check, every
agent-to-agent conversation with its verdict, and every Claude call verbatim --
and each neighborhood's activity feed (signups, answers, admin actions). Read-only; the one write action
(running a round now) is batch.force_trigger_batch, called from app.py.

Gated entirely by auth.is_admin(email) via app.py's _require_admin -- the
same plain email-allowlist pattern login already uses.
"""

import db


def neighborhood_progress(neighborhood):
    complete = len(db.list_complete_residents(neighborhood["id"]))
    total = len(db.list_residents(neighborhood["id"]))
    return {
        "id": neighborhood["id"], "slug": neighborhood["slug"], "name": neighborhood["name"],
        "batch_threshold": neighborhood["batch_threshold"], "complete_count": complete,
        "resident_count": total, "batch_triggered_at": neighborhood["batch_triggered_at"],
    }


def list_neighborhood_progress():
    neighborhoods = db.list_neighborhoods()
    out = []
    i = 0
    while i < len(neighborhoods):
        out.append(neighborhood_progress(neighborhoods[i]))
        i += 1
    return out


def _resident_status(resident):
    # a plain rollup of state spread across residents, match_acceptances and
    # matches.sealed_at/dissolved_at -- nothing new is tracked to compute this.
    if resident["profile_complete_at"] is None:
        return "joining"
    acceptance = db.latest_match_acceptance(resident["id"])
    if acceptance is None:
        return "in_pool"
    match = db.get_match(acceptance["match_id"])
    if match is None:
        return "in_pool"
    if match["dissolved_at"] is not None:
        return "dissolved"
    if match["sealed_at"] is not None:
        return "sealed"
    if acceptance["status"] == "pending":
        return "match_pending"
    return "match_waiting"


def resident_summaries(neighborhood_id):
    residents = db.list_residents(neighborhood_id)
    out = []
    i = 0
    while i < len(residents):
        r = residents[i]
        out.append({
            "id": r["id"], "email": r["email"], "name": r["name"],
            "consent_agreed_at": r["consent_agreed_at"],
            "profile_complete_at": r["profile_complete_at"],
            "source": r["dossier_source"], "status": _resident_status(r),
        })
        i += 1
    return out


def recent_run_summaries(neighborhood_id, limit=5):
    # conversation / invitation / failure counts + the API-call tally per round
    return db.list_runs_for_neighborhood(neighborhood_id, limit=limit)


def run_detail(run_id):
    # everything that happened in one round, in order, with resident names
    run = db.get_run(run_id)
    if run is None:
        return None
    conversations = db.list_agent_conversations(run_id)
    names = {}
    i = 0
    while i < len(conversations):
        conversation = conversations[i]
        names[conversation["a"]] = _name_for(conversation["a"])
        names[conversation["b"]] = _name_for(conversation["b"])
        i += 1
    return {"run": run, "names": names, "conversations": conversations, "events": db.list_events(run_id),
            "ai_calls": db.list_ai_calls(run_id)}


def neighborhood_activity(neighborhood_id):
    # the neighborhood's whole story as one feed (signups, rounds, answers,
    # admin actions), plus the Claude calls made outside rounds (signup cards)
    return {"events": db.list_neighborhood_events(neighborhood_id),
            "signup_ai_calls": db.list_signup_ai_calls(neighborhood_id)}


def _name_for(person_id):
    # "r17" -> that resident's first name; anything else (e.g. sample people) as is
    if isinstance(person_id, str) and person_id.startswith("r") and person_id[1:].isdigit():
        resident = db.get_resident(int(person_id[1:]))
        if resident is not None and resident["name"]:
            return resident["name"]
    return person_id
