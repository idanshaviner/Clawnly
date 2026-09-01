"""Tests for db.py: the SQLite persistence layer (Milestone 1).

Pure storage tests -- no matching/negotiation logic involved, just save/load
round trips for the plain dicts the rest of the app already produces.
"""

import db
from users import USERS


def reset():
    db.reset_all(USERS)


# ----- users -------------------------------------------------------------

def test_replace_and_list_users_round_trips_every_field():
    reset()
    users = db.list_users()
    assert len(users) == 12
    maya = users[0]
    assert maya["id"] == "u01"
    assert maya["hobbies"] == USERS[0]["hobbies"]
    assert maya["availability"] == USERS[0]["availability"]
    assert maya["preferred_group_size"] == USERS[0]["preferred_group_size"]


def test_list_users_preserves_order():
    reset()
    ids = [u["id"] for u in db.list_users()]
    assert ids == [u["id"] for u in USERS]


def test_get_user_unknown_returns_none():
    reset()
    assert db.get_user("nope") is None


def test_update_user_persists_only_editable_fields():
    reset()
    out = db.update_user("u01", {"personality": "extroverted", "id": "u99", "hobbies": ["chess"]})
    assert out["personality"] == "extroverted"
    assert out["hobbies"] == ["chess"]
    assert out["id"] == "u01"                      # id is not editable, ignored
    stored = db.get_user("u01")
    assert stored["personality"] == "extroverted"
    assert stored["hobbies"] == ["chess"]


def test_update_user_no_preference_string_round_trips():
    reset()
    db.update_user("u01", {"preferred_group_size": "no preference"})
    assert db.get_user("u01")["preferred_group_size"] == "no preference"


def test_update_unknown_user_returns_none():
    reset()
    assert db.update_user("nope", {"bio": "x"}) is None


def test_seed_default_users_if_empty_is_a_noop_when_not_empty():
    reset()
    db.update_user("u01", {"personality": "extroverted"})
    db.seed_default_users_if_empty(USERS)          # table isn't empty -> no reseed
    assert db.get_user("u01")["personality"] == "extroverted"


# ----- runs + interview cache ---------------------------------------------

def _sample_interviews():
    users = db.list_users()
    return {users[0]["id"]: {"profile": users[0], "q1": "a", "q2": "b"}}


def test_find_cached_interviews_misses_when_no_run_yet():
    reset()
    assert db.find_cached_interviews("sig-1", "demo") is None


def test_find_cached_interviews_hits_after_a_saved_run():
    reset()
    run_id = db.create_run("demo", "sig-1")
    db.save_interviews(run_id, _sample_interviews())
    cached = db.find_cached_interviews("sig-1", "demo")
    assert cached is not None
    assert cached["u01"]["q1"] == "a"


def test_find_cached_interviews_is_scoped_to_mode_and_signature():
    reset()
    run_id = db.create_run("demo", "sig-1")
    db.save_interviews(run_id, _sample_interviews())
    assert db.find_cached_interviews("sig-1", "live") is None       # different mode
    assert db.find_cached_interviews("sig-2", "demo") is None       # different cast


def test_find_cached_interviews_reflects_error_records():
    reset()
    run_id = db.create_run("demo", "sig-1")
    db.save_interviews(run_id, {"u01": {"profile": db.get_user("u01"), "q1": None, "q2": None, "error": "boom"}})
    cached = db.find_cached_interviews("sig-1", "demo")
    assert cached["u01"]["error"] == "boom"


# ----- matches / negotiations / meetups / run reconstruction --------------

def _sample_match():
    return {"group": ["u01", "u04", "u10"], "reason": "grounded reason",
            "scores": {"personality": 4, "availability": 4, "interests": 4, "size_fit": 4},
            "why_not": [{"id": "u08", "reason": "too big a group"}]}


def _sample_negotiation():
    return {"activity": "coffee", "agreed": True, "concern": "", "rounds": 1,
            "transcript": [{"type": "propose", "round": 1, "activity": "coffee", "pitch": "hi"}]}


def _sample_popup():
    return {"options": [{"event_name": "Coffee", "activity": "coffee", "location": "cafe",
                         "time": "Saturday", "reason": "grounded"}],
            "matched_users": ["Maya", "Marcus", "Omar"], "event_name": "Coffee",
            "activity": "coffee", "location": "cafe", "time": "Saturday", "reason": "grounded"}


def test_load_run_result_reconstructs_the_full_shape():
    reset()
    run_id = db.create_run("demo", "sig-1")
    db.save_interviews(run_id, _sample_interviews())
    match_id = db.save_match(run_id, 0, _sample_match())
    db.save_negotiation(match_id, _sample_negotiation())
    db.save_meetup(match_id, _sample_popup())
    db.finish_run(run_id, ["u12"])

    result = db.load_run_result(run_id)
    assert result["interviews"]["u01"]["q1"] == "a"
    assert result["unmatched"] == ["u12"]
    assert len(result["groups"]) == 1
    group = result["groups"][0]
    assert group["match"]["group"] == ["u01", "u04", "u10"]
    assert group["match"]["why_not"][0]["id"] == "u08"
    assert group["negotiation"]["agreed"] is True
    assert group["negotiation"]["transcript"][0]["type"] == "propose"
    assert group["popup"]["event_name"] == "Coffee"


def test_load_run_result_handles_a_group_with_no_agreement_yet():
    # negotiation exists but the group never agreed -> no meetup was generated.
    reset()
    run_id = db.create_run("demo", "sig-1")
    match_id = db.save_match(run_id, 0, _sample_match())
    db.save_negotiation(match_id, {"activity": "coffee", "agreed": False, "concern": "Maya isn't sold",
                                    "rounds": 4, "transcript": []})
    db.finish_run(run_id, [])
    result = db.load_run_result(run_id)
    assert result["groups"][0]["negotiation"]["agreed"] is False
    assert result["groups"][0]["popup"] is None


def test_load_run_result_unknown_run_returns_none():
    reset()
    assert db.load_run_result(999999) is None


def test_latest_run_id_for_signature_is_scoped_and_picks_the_newest():
    reset()
    assert db.latest_run_id_for_signature("sig-1") is None
    first = db.create_run("demo", "sig-1")
    second = db.create_run("demo", "sig-1")
    db.create_run("demo", "sig-2")               # a different cast, should not match
    assert db.latest_run_id_for_signature("sig-1") == second
    assert first != second


# ----- feedback ------------------------------------------------------------

def test_feedback_add_list_clear_round_trip():
    reset()
    assert db.list_feedback() == []
    db.add_feedback({"members": ["Maya", "Marcus"], "rating": "up", "note": "great"})
    fb = db.list_feedback()
    assert len(fb) == 1
    assert fb[0]["rating"] == "up" and fb[0]["note"] == "great"
    db.clear_feedback()
    assert db.list_feedback() == []


# ----- real-user pilot: neighborhoods ---------------------------------------

def test_get_or_create_neighborhood_is_idempotent_and_snapshots_threshold():
    reset()
    first = db.get_or_create_neighborhood("ballard", "Ballard", 100)
    second = db.get_or_create_neighborhood("ballard", "Ballard", 50)   # different threshold arg
    assert first["id"] == second["id"]
    assert second["batch_threshold"] == 100     # unchanged -- the FIRST create wins


def test_get_neighborhood_by_slug_and_id():
    reset()
    created = db.get_or_create_neighborhood("fremont", "Fremont", 100)
    assert db.get_neighborhood_by_slug("fremont")["id"] == created["id"]
    assert db.get_neighborhood(created["id"])["slug"] == "fremont"
    assert db.get_neighborhood_by_slug("nope") is None
    assert db.get_neighborhood(999999) is None


# ----- real-user pilot: residents -------------------------------------------

def test_get_or_create_resident_starts_blank_and_is_idempotent():
    reset()
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 100)
    first = db.get_or_create_resident(nb["id"], "a@example.com", "google")
    assert first["hobbies"] is None
    assert first["profile_complete_at"] is None
    assert first["slots_status"] == {}
    second = db.get_or_create_resident(nb["id"], "a@example.com", "magic_link")
    assert first["id"] == second["id"]
    assert second["auth_method"] == "google"      # unchanged -- first login wins


def test_residents_are_scoped_per_neighborhood():
    reset()
    a = db.get_or_create_neighborhood("ballard", "Ballard", 100)
    b = db.get_or_create_neighborhood("fremont", "Fremont", 100)
    ra = db.get_or_create_resident(a["id"], "same@example.com", "google")
    rb = db.get_or_create_resident(b["id"], "same@example.com", "google")
    assert ra["id"] != rb["id"]                   # independent profiles per neighborhood


def test_get_resident_unknown_returns_none():
    reset()
    assert db.get_resident(999999) is None


def test_record_consent_sets_the_timestamp_once():
    reset()
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 100)
    resident = db.get_or_create_resident(nb["id"], "a@example.com", "google")
    assert resident["consent_agreed_at"] is None

    first = db.record_consent(resident["id"])
    assert first["consent_agreed_at"] is not None

    second = db.record_consent(resident["id"])
    assert second["consent_agreed_at"] == first["consent_agreed_at"]   # first agreement wins


# ----- real-user pilot: sessions --------------------------------------------

def test_session_round_trip_and_delete():
    reset()
    db.create_session("tok-1", "a@example.com", "resident", 5, 1, 3600)
    session = db.get_session("tok-1")
    assert session["email"] == "a@example.com"
    assert session["role"] == "resident"
    assert session["resident_id"] == 5
    assert session["neighborhood_id"] == 1
    db.delete_session("tok-1")
    assert db.get_session("tok-1") is None


def test_expired_session_is_rejected_and_pruned():
    reset()
    db.create_session("tok-old", "a@example.com", "resident", 5, 1, -10)   # already expired
    assert db.get_session("tok-old") is None


def test_unknown_session_returns_none():
    reset()
    assert db.get_session("nope") is None


# ----- real-user pilot: magic link tokens -----------------------------------

def test_magic_link_token_is_single_use():
    reset()
    db.create_magic_link_token("hash-1", "a@example.com", 1, 900)
    first = db.consume_magic_link_token("hash-1")
    assert first["email"] == "a@example.com"
    assert first["neighborhood_id"] == 1
    second = db.consume_magic_link_token("hash-1")     # already used
    assert second is None


def test_expired_magic_link_token_is_rejected():
    reset()
    db.create_magic_link_token("hash-2", "a@example.com", 1, -10)   # already expired
    assert db.consume_magic_link_token("hash-2") is None


def test_unknown_magic_link_token_returns_none():
    reset()
    assert db.consume_magic_link_token("nope") is None


# ----- real-user pilot: OAuth state ------------------------------------------

def test_oauth_state_is_single_use():
    reset()
    db.create_oauth_state("state-hash", 7, 900)
    first = db.consume_oauth_state("state-hash")
    assert first["neighborhood_id"] == 7
    assert db.consume_oauth_state("state-hash") is None


def test_expired_oauth_state_is_rejected():
    reset()
    db.create_oauth_state("state-hash-2", 7, -10)
    assert db.consume_oauth_state("state-hash-2") is None


# ----- real-user pilot: match acceptances (mutual reveal gate) --------------

def test_persist_run_result_creates_pending_acceptances_for_resident_members():
    reset()
    nb = db.get_or_create_neighborhood("ten-trails", "Ten Trails", 3)
    r1 = db.get_or_create_resident(nb["id"], "a@example.com", "google")
    r2 = db.get_or_create_resident(nb["id"], "b@example.com", "google")
    result = {
        "interviews": {},
        "groups": [{"match": {"group": ["r" + str(r1["id"]), "r" + str(r2["id"])],
                              "reason": "grounded reason", "scores": {}, "why_not": []},
                    "negotiation": None, "popup": None}],
        "unmatched": [],
    }
    run_id = db.persist_run_result("live", "sig", result, neighborhood_id=nb["id"])
    conn = db._get_conn()
    row = conn.execute("SELECT id FROM matches WHERE run_id = ?", (run_id,)).fetchone()
    match_id = row["id"]

    acceptances = db.list_match_acceptances(match_id)
    assert len(acceptances) == 2
    assert {a["resident_id"] for a in acceptances} == {r1["id"], r2["id"]}
    assert all(a["status"] == "pending" for a in acceptances)


def test_persist_run_result_does_not_create_acceptances_for_demo_cast_ids():
    reset()
    result = {
        "interviews": {},
        "groups": [{"match": {"group": ["u01", "u04", "u10"], "reason": "x", "scores": {}, "why_not": []},
                    "negotiation": None, "popup": None}],
        "unmatched": [],
    }
    run_id = db.persist_run_result("demo", "sig", result)
    conn = db._get_conn()
    row = conn.execute("SELECT id FROM matches WHERE run_id = ?", (run_id,)).fetchone()
    assert db.list_match_acceptances(row["id"]) == []


def test_respond_to_acceptance_first_response_wins():
    reset()
    nb = db.get_or_create_neighborhood("ten-trails", "Ten Trails", 3)
    r1 = db.get_or_create_resident(nb["id"], "a@example.com", "google")
    match_id = db.save_match(db.create_run("live", "sig", nb["id"]), 0, _sample_match())
    db.create_pending_acceptances(match_id, [r1["id"]])

    changed = db.respond_to_acceptance(match_id, r1["id"], "accepted")
    assert changed is True
    assert db.get_acceptance(match_id, r1["id"])["status"] == "accepted"

    # a second response can't flip an already-recorded one.
    changed_again = db.respond_to_acceptance(match_id, r1["id"], "declined")
    assert changed_again is False
    assert db.get_acceptance(match_id, r1["id"])["status"] == "accepted"


def test_mark_match_sealed_and_dissolved_are_idempotent():
    reset()
    match_id = db.save_match(db.create_run("live", "sig"), 0, _sample_match())
    db.mark_match_sealed(match_id)
    first = db.get_match(match_id)["sealed_at"]
    db.mark_match_sealed(match_id)
    assert db.get_match(match_id)["sealed_at"] == first

    db.mark_match_dissolved(match_id)
    first_dissolved = db.get_match(match_id)["dissolved_at"]
    db.mark_match_dissolved(match_id)
    assert db.get_match(match_id)["dissolved_at"] == first_dissolved


def test_latest_match_acceptance_picks_the_most_recent():
    reset()
    nb = db.get_or_create_neighborhood("ten-trails", "Ten Trails", 3)
    r1 = db.get_or_create_resident(nb["id"], "a@example.com", "google")
    run_id = db.create_run("live", "sig", nb["id"])
    match1 = db.save_match(run_id, 0, _sample_match())
    match2 = db.save_match(run_id, 1, _sample_match())
    db.create_pending_acceptances(match1, [r1["id"]])
    db.create_pending_acceptances(match2, [r1["id"]])
    latest = db.latest_match_acceptance(r1["id"])
    assert latest["match_id"] == match2


def test_get_negotiation_and_get_meetup_single_match_lookup():
    reset()
    match_id = db.save_match(db.create_run("live", "sig"), 0, _sample_match())
    assert db.get_negotiation(match_id) is None
    assert db.get_meetup(match_id) is None
    db.save_negotiation(match_id, _sample_negotiation())
    db.save_meetup(match_id, _sample_popup())
    negotiation = db.get_negotiation(match_id)
    meetup = db.get_meetup(match_id)
    assert negotiation["activity"] == "coffee"
    assert negotiation["agreed"] is True
    assert meetup["event_name"] == "Coffee"


def test_list_eligible_residents_excludes_members_of_a_live_match():
    reset()
    nb = db.get_or_create_neighborhood("ten-trails", "Ten Trails", 3)
    r1 = db.mark_profile_complete(db.get_or_create_resident(nb["id"], "a@example.com", "google")["id"])
    r2 = db.mark_profile_complete(db.get_or_create_resident(nb["id"], "b@example.com", "google")["id"])
    assert len(db.list_eligible_residents(nb["id"])) == 2

    match_id = db.save_match(db.create_run("live", "sig", nb["id"]), 0, _sample_match())
    db.create_pending_acceptances(match_id, [r1["id"], r2["id"]])
    eligible = db.list_eligible_residents(nb["id"])
    assert eligible == []


def test_list_eligible_residents_includes_members_of_a_dissolved_match():
    reset()
    nb = db.get_or_create_neighborhood("ten-trails", "Ten Trails", 3)
    r1 = db.mark_profile_complete(db.get_or_create_resident(nb["id"], "a@example.com", "google")["id"])
    match_id = db.save_match(db.create_run("live", "sig", nb["id"]), 0, _sample_match())
    db.create_pending_acceptances(match_id, [r1["id"]])
    assert db.list_eligible_residents(nb["id"]) == []

    db.mark_match_dissolved(match_id)
    eligible = db.list_eligible_residents(nb["id"])
    assert len(eligible) == 1
    assert eligible[0]["id"] == r1["id"]


# ----- full reset ------------------------------------------------------------

def test_reset_all_wipes_history_and_reseeds_users():
    reset()
    run_id = db.create_run("demo", "sig-1")
    db.save_match(run_id, 0, _sample_match())
    db.add_feedback({"members": ["Maya"], "rating": "down", "note": "n"})
    db.update_user("u01", {"personality": "extroverted"})
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 100)
    db.get_or_create_resident(nb["id"], "a@example.com", "google")
    db.create_session("tok-1", "a@example.com", "resident", 1, nb["id"], 3600)
    db.create_magic_link_token("hash-1", "a@example.com", nb["id"], 900)
    db.create_oauth_state("state-hash", nb["id"], 900)

    db.reset_all(USERS)

    assert db.list_feedback() == []
    assert db.latest_run_id_for_signature("sig-1") is None
    assert db.get_user("u01")["personality"] == "introverted"
    assert len(db.list_users()) == 12
    assert db.get_neighborhood_by_slug("ballard") is None
    assert db.get_session("tok-1") is None
