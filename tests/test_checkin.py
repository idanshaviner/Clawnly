"""Tests for checkin.py -- the next-morning check-in (journey step 12)."""

import datetime
import zoneinfo

import admin
import checkin
import db
import my_match
from conftest import make_joined_resident, reset_db

PACIFIC = zoneinfo.ZoneInfo("America/Los_Angeles")
NOW = datetime.datetime(2026, 12, 5, 9, 0, tzinfo=PACIFIC)
# the meetup is Sunday 8am, so the check-in opens Sunday 8pm
STARTS_AT = "2026-12-06T08:00:00-08:00"
OPENS = datetime.datetime(2026, 12, 6, 20, 0, tzinfo=PACIFIC)


def reset():
    reset_db()


def make_neighborhood():
    return db.get_or_create_neighborhood("ten-trails", "Ten Trails", 3)


def make_sealed(nb, residents, starts_at=STARTS_AT):
    # an invitation everyone has said yes to, as batch.py + my_match.py leave it
    member_ids = ["r" + str(r["id"]) for r in residents]
    pitches = {}
    for member_id in member_ids:
        pitches[member_id] = "You both want a steady weekly table."
    run_id = db.create_run(nb["id"])
    details = {"conversation_id": 1, "pitches": pitches,
               "invite": {"activity": "a short hike", "when": "Sunday 8am", "where": "The Commons",
                          "starts_at": starts_at}}
    match_id = db.create_invitation(run_id, member_ids, "Alex and Bao want a steady table", 9, details)
    db.create_pending_acceptances(match_id, [r["id"] for r in residents])
    i = 0
    while i < len(residents):
        my_match.respond(residents[i], match_id, "accept")
        i += 1
    return match_id


def two_people():
    nb = make_neighborhood()
    alex = make_joined_resident(nb, "a@example.com", "Alex")
    bao = make_joined_resident(nb, "b@example.com", "Bao")
    return nb, alex, bao


def clock(monkeypatch, when):
    monkeypatch.setattr(checkin, "_now", lambda: when)


def texts_for(nb):
    return [e["text"] for e in db.list_neighborhood_events(nb["id"])]


# ----- clean_starts_at: the hub's start time ------------------------------------

def test_a_good_start_time_is_kept_in_the_neighborhoods_zone():
    kept, note = checkin.clean_starts_at("2026-12-06T08:15", now=NOW)
    assert note is None
    assert kept == "2026-12-06T08:15:00-08:00"


def test_a_start_time_with_an_offset_is_converted_to_the_local_zone():
    kept, note = checkin.clean_starts_at("2026-12-06T16:00:00+00:00", now=NOW)
    assert note is None and kept == "2026-12-06T08:00:00-08:00"


def test_a_missing_or_unreadable_start_time_is_dropped_with_a_log_line():
    raws = [None, "", "   ", 5, "Sunday morning", "2026-13-45T99:00"]
    i = 0
    while i < len(raws):
        kept, note = checkin.clean_starts_at(raws[i], now=NOW)
        assert kept is None
        assert "check-in opens 48 hours after both say yes" in note
        i += 1


def test_a_start_time_in_the_past_or_too_far_away_is_dropped():
    kept, note = checkin.clean_starts_at("2026-12-05T08:00", now=NOW)
    assert kept is None and "in the past" in note
    kept, note = checkin.clean_starts_at("2026-12-19T09:01", now=NOW)
    assert kept is None and "more than 14 days away" in note
    kept, note = checkin.clean_starts_at("2026-12-19T08:59", now=NOW)
    assert note is None and kept is not None


# ----- when the window opens ----------------------------------------------------

def test_the_window_opens_12_hours_after_the_start_time():
    reset()
    nb, alex, bao = two_people()
    match = db.get_match(make_sealed(nb, [alex, bao]))
    assert checkin.opens_at(match) == OPENS


def test_without_a_start_time_the_window_opens_48_hours_after_the_seal():
    reset()
    nb, alex, bao = two_people()
    match = db.get_match(make_sealed(nb, [alex, bao], starts_at=None))
    sealed = datetime.datetime.fromisoformat(match["sealed_at"])
    assert checkin.opens_at(match) == sealed + datetime.timedelta(hours=48)


def test_an_unsealed_invitation_with_no_start_time_has_no_window():
    # (opens_at only does the clock; checkin._live_match is what refuses an unsealed invitation)
    reset()
    nb, alex, bao = two_people()
    run_id = db.create_run(nb["id"])
    match_id = db.create_invitation(run_id, ["r1", "r2"], "h", 9, {"invite": {}})
    assert checkin.opens_at(db.get_match(match_id)) is None


# ----- state_for ------------------------------------------------------------------

def test_no_state_before_any_match_or_for_a_dissolved_one():
    reset()
    nb, alex, bao = two_people()
    assert checkin.state_for(alex) == {"state": "none"}
    run_id = db.create_run(nb["id"])
    match_id = db.create_invitation(run_id, ["r" + str(alex["id"]), "r" + str(bao["id"])], "h", 9, {"invite": {}})
    db.create_pending_acceptances(match_id, [alex["id"], bao["id"]])
    my_match.respond(alex, match_id, "accept")
    assert checkin.state_for(alex) == {"state": "none"}
    my_match.respond(bao, match_id, "decline")
    assert checkin.state_for(alex) == {"state": "none"}


def test_the_check_in_is_closed_until_the_window_opens_then_asks(monkeypatch):
    reset()
    nb, alex, bao = two_people()
    match_id = make_sealed(nb, [alex, bao])
    clock(monkeypatch, OPENS - datetime.timedelta(minutes=1))
    assert checkin.state_for(alex) == {"state": "not_yet", "match_id": match_id}
    clock(monkeypatch, OPENS)
    assert checkin.state_for(alex) == {"state": "ask", "match_id": match_id}


# ----- answer ---------------------------------------------------------------------

def test_an_answer_before_the_window_opens_is_refused_and_stored_nowhere(monkeypatch):
    reset()
    nb, alex, bao = two_people()
    match_id = make_sealed(nb, [alex, bao])
    clock(monkeypatch, OPENS - datetime.timedelta(hours=1))
    state, error = checkin.answer(alex, match_id, True, True)
    assert state is None and "isn't open yet" in error
    assert db.list_checkins(match_id) == []


def test_an_answer_is_stored_logged_and_the_first_answer_wins(monkeypatch):
    reset()
    nb, alex, bao = two_people()
    match_id = make_sealed(nb, [alex, bao])
    clock(monkeypatch, OPENS)
    state, error = checkin.answer(alex, match_id, True, True)
    assert error is None
    assert state["state"] == "done" and state["met"] is True and state["would_meet_again"] is True
    # a second, different answer does not change the first or log again
    state, error = checkin.answer(alex, match_id, False, None)
    assert error is None and state["met"] is True and state["would_meet_again"] is True
    checkins = db.list_checkins(match_id)
    assert len(checkins) == 1 and checkins[0]["resident_id"] == alex["id"]
    lines = [t for t in texts_for(nb) if "checked in" in t]
    assert lines == ["Alex checked in on invitation #" + str(match_id) + ": met, would meet again."]


def test_not_meeting_stores_no_second_answer_and_is_logged(monkeypatch):
    reset()
    nb, alex, bao = two_people()
    match_id = make_sealed(nb, [alex, bao])
    clock(monkeypatch, OPENS)
    state, error = checkin.answer(alex, match_id, False, True)
    assert error is None and state["met"] is False and state["would_meet_again"] is None
    assert db.list_checkins(match_id)[0]["would_meet_again"] is None
    assert "Alex checked in on invitation #" + str(match_id) + ": did not meet." in texts_for(nb)


def test_answers_must_be_plain_true_or_false(monkeypatch):
    reset()
    nb, alex, bao = two_people()
    match_id = make_sealed(nb, [alex, bao])
    clock(monkeypatch, OPENS)
    assert checkin.answer(alex, match_id, "yes", True)[0] is None
    assert checkin.answer(alex, match_id, 1, True)[0] is None
    assert checkin.answer(alex, match_id, True, None)[0] is None
    assert checkin.answer(alex, match_id, True, "yes")[0] is None
    assert db.list_checkins(match_id) == []


def test_only_a_member_of_a_revealed_invitation_can_check_in(monkeypatch):
    reset()
    nb, alex, bao = two_people()
    cam = make_joined_resident(nb, "c@example.com", "Cam")
    match_id = make_sealed(nb, [alex, bao])
    clock(monkeypatch, OPENS)
    state, error = checkin.answer(cam, match_id, True, True)
    assert state is None and "not a member" in error
    assert db.list_checkins(match_id) == []
    # an invitation nobody has sealed yet
    run_id = db.create_run(nb["id"])
    pending_id = db.create_invitation(run_id, ["r" + str(alex["id"]), "r" + str(cam["id"])], "h", 9, {"invite": {}})
    db.create_pending_acceptances(pending_id, [alex["id"], cam["id"]])
    state, error = checkin.answer(alex, pending_id, True, True)
    assert state is None and "hasn't been revealed" in error


# ----- the other person's answers stay private --------------------------------------

def test_the_other_persons_answer_is_never_in_my_state(monkeypatch):
    reset()
    nb, alex, bao = two_people()
    match_id = make_sealed(nb, [alex, bao])
    clock(monkeypatch, OPENS)
    before = checkin.state_for(alex)
    checkin.answer(bao, match_id, True, False)
    # Bao said no: Alex sees exactly what he saw before Bao answered at all
    assert checkin.state_for(alex) == before
    state, error = checkin.answer(alex, match_id, True, True)
    assert error is None
    # now both answered, Alex still cannot tell Bao's answer from "not mutual"
    assert state == {"state": "done", "match_id": match_id, "met": True, "would_meet_again": True, "mutual": False}
    assert checkin.state_for(bao)["mutual"] is False


def test_a_mutual_yes_is_shown_to_both_logged_and_counted(monkeypatch):
    reset()
    nb, alex, bao = two_people()
    match_id = make_sealed(nb, [alex, bao])
    clock(monkeypatch, OPENS)
    state, error = checkin.answer(alex, match_id, True, True)
    assert state["mutual"] is False
    assert checkin.mutual_count(nb["id"]) == 0
    state, error = checkin.answer(bao, match_id, True, True)
    assert state["mutual"] is True
    assert checkin.state_for(alex)["mutual"] is True
    lines = texts_for(nb)
    assert "Everyone on invitation #" + str(match_id) + " would meet again: offer a second meetup." in lines
    assert checkin.mutual_count(nb["id"]) == 1
    progress = admin.neighborhood_progress(db.get_neighborhood(nb["id"]))
    assert progress["would_meet_again_count"] == 1


def test_a_no_from_anyone_means_no_second_meetup_and_is_logged_once(monkeypatch):
    reset()
    nb, alex, bao = two_people()
    match_id = make_sealed(nb, [alex, bao])
    clock(monkeypatch, OPENS)
    checkin.answer(alex, match_id, True, True)
    checkin.answer(bao, match_id, False, None)
    checkin.answer(bao, match_id, False, None)
    lines = texts_for(nb)
    assert lines.count("Everyone answered the check-in on invitation #" + str(match_id) + ": no second meetup.") == 1
    assert not any("offer a second meetup" in t for t in lines)
    assert checkin.mutual_count(nb["id"]) == 0
    assert checkin.state_for(alex)["mutual"] is False
