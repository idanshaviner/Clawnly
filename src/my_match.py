"""The mutual yes/no gate for hub invitations (batch.py stores each one as a
matches row + one match_acceptances row per invited resident).

Before anyone knows who the other person is, a resident sees only the pitch
the hub wrote to them (name-blinded by batch.py) and answers yes or no. Once
everyone invited says yes, the invitation is "sealed": first names, the hub's
headline and the proposed meetup are revealed. A "no" dissolves it for
everyone, and db.list_eligible_residents puts them back in the pool.

Pure DB/routing logic, no AI calls -- app.py's routes are thin wrappers
around get_state/respond.
"""

import db


def _resident_id_from_member(member_id):
    # batch.py always stores invited members as "r" + resident id (e.g. "r17").
    return int(member_id[1:])


def _member_resident_ids(match):
    ids = []
    raw = match["member_ids"]
    i = 0
    while i < len(raw):
        ids.append(_resident_id_from_member(raw[i]))
        i += 1
    return ids


def _first_name(resident):
    name = resident.get("name")
    if name is None or len(name.strip()) == 0:
        return "A neighbor"
    return name.strip().split(" ")[0]


def _all_accepted(acceptances):
    if len(acceptances) == 0:
        return False
    i = 0
    while i < len(acceptances):
        if acceptances[i]["status"] != "accepted":
            return False
        i += 1
    return True


def _seal_if_ready(match_id, acceptances):
    if _all_accepted(acceptances):
        db.mark_match_sealed(match_id)
        return True
    return False


def _pitch_for(resident, match):
    pitches = match["details"].get("pitches", {})
    return pitches.get("r" + str(resident["id"]), "")


def _sealed_payload(resident, match):
    names = []
    ids = _member_resident_ids(match)
    i = 0
    while i < len(ids):
        rid = ids[i]
        if rid != resident["id"]:
            member = db.get_resident(rid)
            if member is not None:
                names.append(_first_name(member))
        i += 1
    return {
        "state": "sealed", "match_id": match["id"], "reason": match["reason"],
        "pitch": _pitch_for(resident, match), "other_first_names": names,
        "meetup": match["details"].get("invite"),
    }


def get_state(resident):
    # resolves purely from the CALLER's own most recent match_acceptances row
    # -- never a client-supplied match id, same IDOR-safe pattern as
    # _require_consented_resident in app.py.
    row = db.latest_match_acceptance(resident["id"])
    if row is None:
        neighborhood = db.get_neighborhood(resident["neighborhood_id"])
        if neighborhood is not None and neighborhood["batch_triggered_at"] is not None:
            return {"state": "no_match"}
        return {"state": "not_yet_batched"}

    match = db.get_match(row["match_id"])
    if match is None:
        return {"state": "no_match"}

    if match["dissolved_at"] is not None:
        return {"state": "dissolved"}

    if row["status"] == "pending":
        # the pitch only -- the hub's headline names both people, so it waits for the seal
        acceptances = db.list_match_acceptances(match["id"])
        return {"state": "pending", "match_id": match["id"], "reason": _pitch_for(resident, match),
                "group_size": len(acceptances)}

    acceptances = db.list_match_acceptances(match["id"])
    sealed = match["sealed_at"] is not None or _seal_if_ready(match["id"], acceptances)
    if not sealed:
        return {"state": "waiting", "match_id": match["id"], "group_size": len(acceptances)}

    return _sealed_payload(resident, match)


def respond(resident, match_id, response):
    # updates only the CALLER's own row -- match_id names which match, but
    # db.get_acceptance/respond_to_acceptance are always scoped to
    # resident["id"] from the session, never a resident id from the request.
    if response not in ("accept", "decline"):
        return None, "response must be 'accept' or 'decline'"

    acceptance = db.get_acceptance(match_id, resident["id"])
    if acceptance is None:
        return None, "You're not a member of that match."

    match = db.get_match(match_id)
    if match is None or match["dissolved_at"] is not None:
        return None, "This match is no longer active."

    status = "accepted"
    if response == "decline":
        status = "declined"
    # first response wins (same idempotency guard as record_consent) -- if
    # this call didn't actually change anything (the resident already
    # answered), don't act on `response` as though it just happened.
    changed = db.respond_to_acceptance(match_id, resident["id"], status)

    if changed and status == "declined":
        db.mark_match_dissolved(match_id)
    elif changed:
        acceptances = db.list_match_acceptances(match_id)
        _seal_if_ready(match_id, acceptances)

    return get_state(resident), None
