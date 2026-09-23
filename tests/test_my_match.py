"""Tests for my_match.py -- the mutual yes/no gate for hub invitations."""

import db
import my_match
from conftest import make_joined_resident, reset_db


def reset():
    reset_db()


def make_neighborhood(threshold=3):
    return db.get_or_create_neighborhood("ten-trails", "Ten Trails", threshold)


def make_resident(nb, email, name):
    return make_joined_resident(nb, email, name)


def make_match(nb, residents):
    # an invitation as batch.py stores it: name-blinded pitch per member
    member_ids = ["r" + str(r["id"]) for r in residents]
    pitches = {}
    for member_id in member_ids:
        pitches[member_id] = "You both want a steady weekly table. " + member_id
    run_id = db.create_run(nb["id"])
    details = {"conversation_id": 1,
               "invite": {"activity": "a short hike", "when": "Saturday morning", "where": "Ten Trails trailhead"},
               "pitches": pitches}
    match_id = db.create_invitation(run_id, 0, member_ids, "Alex and Bao both want a steady table", 9, details)
    db.create_pending_acceptances(match_id, [r["id"] for r in residents])
    return match_id


# ----- get_state: no match yet ------------------------------------------------

def test_not_yet_batched_before_the_neighborhood_triggers():
    reset()
    nb = make_neighborhood()
    resident = make_resident(nb, "a@example.com", "Alex")
    state = my_match.get_state(resident)
    assert state["state"] == "not_yet_batched"


def test_no_match_once_batched_but_never_grouped():
    reset()
    nb = make_neighborhood()
    resident = make_resident(nb, "a@example.com", "Alex")
    db.try_trigger_batch(nb["id"])
    state = my_match.get_state(resident)
    assert state["state"] == "no_match"


# ----- get_state: pending -----------------------------------------------------

def test_pending_shows_only_the_callers_own_pitch():
    reset()
    nb = make_neighborhood()
    alex = make_resident(nb, "a@example.com", "Alex")
    bao = make_resident(nb, "b@example.com", "Bao")
    cleo = make_resident(nb, "c@example.com", "Cleo")
    make_match(nb, [alex, bao, cleo])

    state = my_match.get_state(alex)
    assert state["state"] == "pending"
    assert state["group_size"] == 3
    assert state["reason"] == "You both want a steady weekly table. r" + str(alex["id"])
    assert "other_first_names" not in state
    # the hub's headline names people, so it stays hidden until everyone says yes
    assert "Bao" not in str(state)


# ----- respond: accept / decline / waiting / sealed --------------------------

def test_accept_alone_moves_to_waiting_not_sealed():
    reset()
    nb = make_neighborhood()
    alex = make_resident(nb, "a@example.com", "Alex")
    bao = make_resident(nb, "b@example.com", "Bao")
    match_id = make_match(nb, [alex, bao])

    state, error = my_match.respond(alex, match_id, "accept")
    assert error is None
    assert state["state"] == "waiting"
    assert state["group_size"] == 2
    # bao (still pending) can't see alex's acceptance leaking any names either.
    bao_state = my_match.get_state(bao)
    assert bao_state["state"] == "pending"


def test_everyone_accepting_seals_the_match_with_full_reveal():
    reset()
    nb = make_neighborhood()
    alex = make_resident(nb, "a@example.com", "Alex")
    bao = make_resident(nb, "b@example.com", "Bao Lin")
    match_id = make_match(nb, [alex, bao])

    my_match.respond(alex, match_id, "accept")
    state, error = my_match.respond(bao, match_id, "accept")
    assert error is None
    assert state["state"] == "sealed"
    assert state["other_first_names"] == ["Alex"]   # first name only
    assert state["meetup"] == {"activity": "a short hike", "when": "Saturday morning", "where": "Ten Trails trailhead"}
    assert state["reason"] == "Alex and Bao both want a steady table"
    assert state["pitch"].endswith("r" + str(bao["id"]))

    # alex's own view is sealed too, revealing Bao's first name (not "Bao Lin").
    alex_state = my_match.get_state(alex)
    assert alex_state["state"] == "sealed"
    assert alex_state["other_first_names"] == ["Bao"]

    assert db.get_match(match_id)["sealed_at"] is not None


def test_decline_dissolves_the_match_for_everyone():
    reset()
    nb = make_neighborhood()
    alex = make_resident(nb, "a@example.com", "Alex")
    bao = make_resident(nb, "b@example.com", "Bao")
    cleo = make_resident(nb, "c@example.com", "Cleo")
    match_id = make_match(nb, [alex, bao, cleo])

    my_match.respond(alex, match_id, "accept")
    state, error = my_match.respond(bao, match_id, "decline")
    assert error is None
    assert state["state"] == "dissolved"

    # alex (who already accepted) and cleo (who never responded) both see it dissolved too.
    assert my_match.get_state(alex)["state"] == "dissolved"
    assert my_match.get_state(cleo)["state"] == "dissolved"
    assert db.get_match(match_id)["dissolved_at"] is not None


def test_declined_members_are_released_back_into_the_eligible_pool():
    reset()
    nb = make_neighborhood()
    alex = make_resident(nb, "a@example.com", "Alex")
    bao = make_resident(nb, "b@example.com", "Bao")
    match_id = make_match(nb, [alex, bao])
    assert db.list_eligible_residents(nb["id"]) == []

    my_match.respond(alex, match_id, "decline")
    eligible_ids = {r["id"] for r in db.list_eligible_residents(nb["id"])}
    assert eligible_ids == {alex["id"], bao["id"]}


# ----- respond: IDOR safety ---------------------------------------------------

def test_respond_rejects_a_resident_who_is_not_a_member_of_the_match():
    reset()
    nb = make_neighborhood()
    alex = make_resident(nb, "a@example.com", "Alex")
    bao = make_resident(nb, "b@example.com", "Bao")
    outsider = make_resident(nb, "z@example.com", "Zoe")
    match_id = make_match(nb, [alex, bao])

    state, error = my_match.respond(outsider, match_id, "accept")
    assert state is None
    assert error is not None
    assert db.get_acceptance(match_id, outsider["id"]) is None


def test_respond_only_ever_touches_the_callers_own_row():
    reset()
    nb = make_neighborhood()
    alex = make_resident(nb, "a@example.com", "Alex")
    bao = make_resident(nb, "b@example.com", "Bao")
    match_id = make_match(nb, [alex, bao])

    my_match.respond(alex, match_id, "accept")
    # bao's row is untouched by alex's response.
    assert db.get_acceptance(match_id, bao["id"])["status"] == "pending"
    assert db.get_acceptance(match_id, alex["id"])["status"] == "accepted"


def test_respond_rejects_an_invalid_response_value():
    reset()
    nb = make_neighborhood()
    alex = make_resident(nb, "a@example.com", "Alex")
    bao = make_resident(nb, "b@example.com", "Bao")
    match_id = make_match(nb, [alex, bao])

    state, error = my_match.respond(alex, match_id, "maybe")
    assert state is None
    assert error is not None
    assert db.get_acceptance(match_id, alex["id"])["status"] == "pending"


def test_respond_on_an_already_dissolved_match_is_rejected():
    reset()
    nb = make_neighborhood()
    alex = make_resident(nb, "a@example.com", "Alex")
    bao = make_resident(nb, "b@example.com", "Bao")
    match_id = make_match(nb, [alex, bao])
    my_match.respond(alex, match_id, "decline")

    state, error = my_match.respond(bao, match_id, "accept")
    assert state is None
    assert error is not None
    assert db.get_acceptance(match_id, bao["id"])["status"] == "pending"


def test_respond_a_second_time_does_not_flip_the_first_answer():
    reset()
    nb = make_neighborhood()
    alex = make_resident(nb, "a@example.com", "Alex")
    bao = make_resident(nb, "b@example.com", "Bao")
    match_id = make_match(nb, [alex, bao])

    my_match.respond(alex, match_id, "accept")
    my_match.respond(alex, match_id, "decline")   # too late -- already accepted
    assert db.get_acceptance(match_id, alex["id"])["status"] == "accepted"
    assert db.get_match(match_id)["dissolved_at"] is None


# ----- logs ----------------------------------------------------------------------

def test_every_answer_and_the_reveal_are_logged():
    reset()
    nb = make_neighborhood()
    alex = make_resident(nb, "a@example.com", "Alex")
    bao = make_resident(nb, "b@example.com", "Bao")
    match_id = make_match(nb, [alex, bao])
    my_match.respond(alex, match_id, "accept")
    my_match.respond(bao, match_id, "accept")
    texts = [e["text"] for e in db.list_neighborhood_events(nb["id"])]
    assert texts == [
        "Alex said YES to invitation #" + str(match_id) + ".",
        "Bao said YES to invitation #" + str(match_id) + ".",
        "Invitation #" + str(match_id) + " sealed: everyone said yes. First names and the meetup are revealed.",
    ]
    # the events belong to the round that made the invitation
    run_id = db.get_match(match_id)["run_id"]
    assert len(db.list_events(run_id)) == 3


def test_a_no_and_the_dissolve_are_logged_and_a_repeat_answer_is_not():
    reset()
    nb = make_neighborhood()
    alex = make_resident(nb, "a@example.com", "Alex")
    bao = make_resident(nb, "b@example.com", "Bao")
    match_id = make_match(nb, [alex, bao])
    my_match.respond(alex, match_id, "decline")
    my_match.respond(alex, match_id, "accept")        # too late, changes nothing, logs nothing
    texts = [e["text"] for e in db.list_neighborhood_events(nb["id"])]
    assert texts == [
        "Alex said NO to invitation #" + str(match_id) + ".",
        "Invitation #" + str(match_id) + " dissolved. Nobody's name was revealed; everyone in it is back in the pool.",
    ]
