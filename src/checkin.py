"""The next-morning check-in (journey step 12): after a revealed meetup, each
person privately answers "did you meet?" and "would you meet again?".

The window opens 12 hours after the meetup's start time, which the hub gives as
`starts_at` and code validates (clean_starts_at). When there is no usable start
time it opens 48 hours after both people said yes. Answers are stored once per
person (first answer wins) and never shown to the other person: the only thing
anyone learns is a mutual yes ("would meet again" from everyone who met), which
is logged so the admin can count it. Nobody is told who said no.

Pure DB/clock logic, no AI calls -- app.py's routes are thin wrappers around
state_for/answer.
"""

import datetime
import zoneinfo

import config
import db

OPENS_AFTER_START_HOURS = 12
OPENS_AFTER_SEAL_HOURS = 48
MAX_DAYS_AHEAD = 14


def _zone():
    return zoneinfo.ZoneInfo(config.NIGHTLY_TIMEZONE)


def _now():
    return datetime.datetime.now(_zone())


def today_text():
    # for the hub's prompt, e.g. "Tuesday 2026-11-24"
    now = _now()
    return now.strftime("%A") + " " + now.date().isoformat()


def _first_name(resident):
    name = resident.get("name")
    if name is None or len(name.strip()) == 0:
        return "A neighbor"
    return name.strip().split(" ")[0]


def clean_starts_at(raw, now=None):
    # the hub's start time -> (ISO time in the neighborhood's zone, None), or (None, a line for
    # the log). Code checks it because a model can write a time in the past or a year out.
    fallback = "the check-in opens 48 hours after both say yes"
    if now is None:
        now = _now()
    if not isinstance(raw, str) or len(raw.strip()) == 0:
        return None, "The hub gave no start time (starts_at): " + fallback + "."
    try:
        when = datetime.datetime.fromisoformat(raw.strip())
    except ValueError:
        return None, "The hub's start time \"" + raw.strip()[:60] + "\" is not a date and time: " + fallback + "."
    if when.tzinfo is None:
        when = when.replace(tzinfo=_zone())
    when = when.astimezone(_zone())
    if when <= now:
        return None, "The hub's start time " + when.isoformat() + " is in the past: " + fallback + "."
    if when > now + datetime.timedelta(days=MAX_DAYS_AHEAD):
        return None, ("The hub's start time " + when.isoformat() + " is more than " + str(MAX_DAYS_AHEAD)
                      + " days away: " + fallback + ".")
    return when.isoformat(), None


def _parse(text):
    if not isinstance(text, str):
        return None
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError:
        return None


def opens_at(match):
    # when the check-in may be answered: 12 hours after the start time, else 48 hours after the
    # seal, else None (no start time and never sealed). Callers check the match is live first.
    invite = match["details"].get("invite")
    if isinstance(invite, dict):
        start = _parse(invite.get("starts_at"))
        if start is not None and start.tzinfo is not None:
            return start + datetime.timedelta(hours=OPENS_AFTER_START_HOURS)
    sealed = _parse(match["sealed_at"])
    if sealed is None:
        return None
    return sealed + datetime.timedelta(hours=OPENS_AFTER_SEAL_HOURS)


def is_mutual(match):
    # everyone invited answered, everyone met, everyone would meet again
    checkins = db.list_checkins(match["id"])
    if len(checkins) == 0 or len(checkins) < len(match["member_ids"]):
        return False
    i = 0
    while i < len(checkins):
        if not checkins[i]["met"] or checkins[i]["would_meet_again"] is not True:
            return False
        i += 1
    return True


def mutual_count(neighborhood_id):
    # for the admin tile: how many meetups ended with everyone wanting another
    ids = db.list_sealed_match_ids(neighborhood_id)
    count = 0
    i = 0
    while i < len(ids):
        match = db.get_match(ids[i])
        if match is not None and is_mutual(match):
            count += 1
        i += 1
    return count


def _mine(match_id, resident_id):
    checkins = db.list_checkins(match_id)
    i = 0
    while i < len(checkins):
        if checkins[i]["resident_id"] == resident_id:
            return checkins[i]
        i += 1
    return None


def _live_match(match):
    return match is not None and match["sealed_at"] is not None and match["dissolved_at"] is None


def _state_for_match(resident, match):
    mine = _mine(match["id"], resident["id"])
    if mine is not None:
        # only the caller's own answers, plus the mutual yes -- never the other person's answer
        return {"state": "done", "match_id": match["id"], "met": mine["met"],
                "would_meet_again": mine["would_meet_again"], "mutual": is_mutual(match)}
    opens = opens_at(match)
    if opens is None or _now() < opens:
        return {"state": "not_yet", "match_id": match["id"]}
    return {"state": "ask", "match_id": match["id"]}


def state_for(resident):
    # resolves from the CALLER's own latest match, never a client-supplied id
    row = db.latest_match_acceptance(resident["id"])
    if row is None:
        return {"state": "none"}
    match = db.get_match(row["match_id"])
    if not _live_match(match):
        return {"state": "none"}
    return _state_for_match(resident, match)


def answer(resident, match_id, met, would_meet_again):
    # (state, None) or (None, a message). Membership is checked against the caller's own session.
    if not isinstance(met, bool):
        return None, "met must be true or false."
    if met and not isinstance(would_meet_again, bool):
        return None, "would_meet_again must be true or false."
    if not met:
        would_meet_again = None
    if db.get_acceptance(match_id, resident["id"]) is None:
        return None, "You're not a member of that match."
    match = db.get_match(match_id)
    if not _live_match(match):
        return None, "This invitation hasn't been revealed yet."
    opens = opens_at(match)
    if opens is None or _now() < opens:
        return None, "The check-in isn't open yet. We'll ask after your meetup."

    stored = db.save_checkin(match_id, resident["id"], met, would_meet_again)
    if stored:
        text = _first_name(resident) + " checked in on invitation #" + str(match_id) + ": did not meet."
        if met and would_meet_again:
            text = _first_name(resident) + " checked in on invitation #" + str(match_id) + ": met, would meet again."
        elif met:
            text = _first_name(resident) + " checked in on invitation #" + str(match_id) + ": met, would not meet again."
        db.log_event(match["run_id"], "human", "human", text, None, resident["neighborhood_id"])
        _log_if_everyone_answered(match, resident["neighborhood_id"])
    return _state_for_match(resident, match), None


def _log_if_everyone_answered(match, neighborhood_id):
    if len(db.list_checkins(match["id"])) < len(match["member_ids"]):
        return
    if is_mutual(match):
        text = ("Everyone on invitation #" + str(match["id"])
                + " would meet again: offer a second meetup.")
    else:
        text = "Everyone answered the check-in on invitation #" + str(match["id"]) + ": no second meetup."
    db.log_event(match["run_id"], "system", "system", text, None, neighborhood_id)
