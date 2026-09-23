"""Batch trigger: runs the hub (orchestrator.run_round) for a neighborhood
and turns its invitations into the mutual yes/no gate (my_match.py).

The FIRST round starts when joins cross the neighborhood's threshold: app.py
calls schedule_check() right after a successful bring-your-agent confirm.
After that, nightly.py runs a round every night, and the admin dashboard can
run one any time (force_trigger_batch).

Rules enforced here in code, on top of the hub's own gate:
  - one invitation per person per round -- the strongest (highest depth)
    wins, any other is held back and logged.
  - invitations are blind until both say yes: the other person's name is
    removed from each pitch before it's stored (_blind).
"""

import asyncio
import re

import config
import db
import orchestrator


# fire-and-forget tasks must be referenced, or Python may garbage-collect them mid-run
_RUNNING = set()


def resident_to_person(resident):
    # "r" + resident id, the shape orchestrator/agent_talk expect. Only
    # residents with a dossier and card ever reach here (db.list_complete_residents).
    name = resident.get("name")
    if not name:
        name = "Neighbor"
    source = resident.get("dossier_source")
    if not source:
        source = "Other"
    return {"id": "r" + str(resident["id"]), "name": name, "source": source,
            "dossier": resident["dossier_text"], "card": resident["card"]}


def _blind(text, other_name):
    # the pitch someone reads before both have said yes must not name the other person
    text = str(text or "")
    if not other_name:
        return text
    return re.sub(r"\b" + re.escape(other_name) + r"\b", "your match", text, flags=re.IGNORECASE)


def pick_invitations(invitations):
    # strongest first; a person already holding an invitation this round is skipped.
    # returns (kept, held_back).
    ordered = list(invitations)
    ordered.sort(key=lambda conversation: conversation["verdict"]["depth"], reverse=True)
    taken = {}
    kept = []
    held_back = []
    i = 0
    while i < len(ordered):
        conversation = ordered[i]
        if conversation["a"] in taken or conversation["b"] in taken:
            held_back.append(conversation)
        else:
            taken[conversation["a"]] = True
            taken[conversation["b"]] = True
            kept.append(conversation)
        i += 1
    return kept, held_back


def _resident_id(person_id):
    return int(person_id[1:])


async def run_neighborhood_round(neighborhood_id, people, client):
    # one hub round for these people, then one invitation (yes/no gate) per kept pair.
    # (the round itself logs every event and every Claude call, and records usage.)
    result = await orchestrator.run_round(people, client=client, neighborhood_id=neighborhood_id)
    run_id = result["run_id"]

    names = {}
    i = 0
    while i < len(people):
        names[people[i]["id"]] = people[i]["name"]
        i += 1

    kept, held_back = pick_invitations(result["invitations"])
    i = 0
    while i < len(held_back):
        conversation = held_back[i]
        db.log_event(run_id, "code", "check", "Held back the invitation for " + names[conversation["a"]] + " + "
                     + names[conversation["b"]] + ": one of them already has a stronger invitation this round.",
                     str(conversation["id"]), neighborhood_id)
        i += 1

    i = 0
    while i < len(kept):
        conversation = kept[i]
        a = conversation["a"]
        b = conversation["b"]
        verdict = conversation["verdict"]
        invite = verdict["invite"]
        details = {
            "conversation_id": conversation["id"],
            "invite": {"activity": str(invite.get("activity", "")), "when": str(invite.get("when", "")),
                       "where": str(invite.get("where", ""))},
            "pitches": {a: _blind(invite.get("to_a"), names[b]), b: _blind(invite.get("to_b"), names[a])},
        }
        match_id = db.create_invitation(run_id, [a, b], verdict["headline"], verdict["depth"], details)
        db.create_pending_acceptances(match_id, [_resident_id(a), _resident_id(b)])
        db.log_event(run_id, "system", "system", "Invitation #" + str(match_id) + " sent to " + names[a] + " and "
                     + names[b] + ". Nothing is revealed until both say yes.", str(conversation["id"]), neighborhood_id)
        i += 1
    return run_id


def people_for(neighborhood_id):
    # everyone who has brought their agent and isn't holding a live invitation
    eligible = db.list_eligible_residents(neighborhood_id)
    people = []
    i = 0
    while i < len(eligible):
        people.append(resident_to_person(eligible[i]))
        i += 1
    return people


async def check_and_trigger_batch(neighborhood_id, client=None):
    # called right after a resident joins. Cheap early-outs (unknown
    # neighborhood, below threshold) never touch the one-shot CAS.
    neighborhood = db.get_neighborhood(neighborhood_id)
    if neighborhood is None:
        return
    people = people_for(neighborhood_id)
    if len(people) < neighborhood["batch_threshold"]:
        return
    if not db.try_trigger_batch(neighborhood_id):
        return   # another near-simultaneous join already triggered this round
    db.log_event(None, "system", "system", "Threshold reached: " + str(len(people)) + " of "
                 + str(neighborhood["batch_threshold"]) + " neighbors have an agent. Running the first round.",
                 None, neighborhood_id)
    try:
        if client is None:
            client = config.get_client()
        await run_neighborhood_round(neighborhood_id, people, client)
    except Exception as error:
        # the CAS already fired, so an operator re-runs it from the admin
        # dashboard; never surface this through an unrelated resident's request --
        # but always leave it in the log (the round's own events show how far it got).
        db.log_event(None, "system", "system", "The automatic round failed: " + str(error)
                     + ". Run it again from the admin dashboard.", None, neighborhood_id)
        print("[batch] neighborhood {} round failed: {}".format(neighborhood_id, error))


def schedule_check(neighborhood_id):
    # fire-and-forget from a request handler: the resident's "you're in" must
    # not wait on (or fail because of) a whole round of agent conversations.
    task = asyncio.get_running_loop().create_task(check_and_trigger_batch(neighborhood_id))
    _RUNNING.add(task)
    task.add_done_callback(_RUNNING.discard)
    return task


async def force_trigger_batch(neighborhood_id, client=None, by=None):
    # the admin dashboard's "run a round now": ignores batch_threshold, and runs
    # inside the admin's request, so a failure is reported back as an error.
    # `by` is the admin's email, for the log.
    neighborhood = db.get_neighborhood(neighborhood_id)
    if neighborhood is None:
        return None, "No such neighborhood."
    people = people_for(neighborhood_id)
    if len(people) < 2:
        return None, "Not enough residents with an agent to pair anyone (need at least 2)."
    if client is None:
        client = config.get_client()
    db.mark_batch_triggered(neighborhood_id)
    who = "An admin"
    if by:
        who = "Admin " + by
    db.log_event(None, "human", "human", who + " ran a round now with " + str(len(people)) + " neighbors.",
                 None, neighborhood_id)
    run_id = await run_neighborhood_round(neighborhood_id, people, client)
    return run_id, None
