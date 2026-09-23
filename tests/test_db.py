"""Tests for db.py: the SQLite persistence layer.

Pure storage tests -- save/load round trips for the plain dicts the rest of
the app produces.
"""

import db
from conftest import make_joined_resident


def reset():
    db.init_db()
    db.reset_all()


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
    assert first["profile_complete_at"] is None
    assert first["dossier_text"] is None and first["card"] is None
    assert first["dossier_previews"] == 0
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


# ----- bring your agent: dossier drafts ---------------------------------------

def test_save_dossier_draft_keeps_the_latest_text_and_card():
    reset()
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 10)
    resident = db.get_or_create_resident(nb["id"], "a@example.com", "google")
    db.save_dossier_draft(resident["id"], "Noa", "ChatGPT", "the text", {"essence": "e"})
    saved = db.save_dossier_draft(resident["id"], "Noa", "Claude", "better text", {"essence": "e2"})
    assert saved["dossier_source"] == "Claude"
    assert saved["dossier_text"] == "better text"
    assert saved["card"] == {"essence": "e2"}


def test_claim_preview_is_capped_atomically_and_stops_after_joining():
    reset()
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 10)
    resident = db.get_or_create_resident(nb["id"], "a@example.com", "google")
    assert [db.claim_preview(resident["id"], 2) for _ in range(3)] == [True, True, False]
    assert db.get_resident(resident["id"])["dossier_previews"] == 2
    other = make_joined_resident(nb, "b@example.com", "Bao")
    assert db.claim_preview(other["id"], 5) is False


def test_invite_codes_are_secret_and_required():
    reset()
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 10)
    code = nb["invite_code"]
    assert code and code != "ballard" and len(code) >= 12
    assert db.neighborhood_for_invite("ballard", code)["id"] == nb["id"]
    assert db.neighborhood_for_invite("ballard", "wrong") is None
    assert db.neighborhood_for_invite("ballard", "") is None
    assert db.neighborhood_for_invite("ballard", None) is None
    assert db.neighborhood_for_invite("nowhere", code) is None
    # a legacy neighborhood whose "code" was its own public slug is never joinable as-is...
    conn = db._get_conn()
    conn.execute("UPDATE neighborhoods SET invite_code = slug WHERE id = ?", (nb["id"],))
    conn.commit()
    assert db.neighborhood_for_invite("ballard", "ballard") is None
    # ...until it is given a real secret code
    fixed = db.ensure_invite_code(nb["id"])
    assert fixed["invite_code"] != "ballard"
    assert db.neighborhood_for_invite("ballard", fixed["invite_code"])["id"] == nb["id"]


def test_count_recent_magic_links_counts_per_email():
    reset()
    db.create_magic_link_token("h1", "a@example.com", None, 900)
    db.create_magic_link_token("h2", "a@example.com", None, 900)
    db.create_magic_link_token("h3", "b@example.com", None, 900)
    assert db.count_recent_magic_links("a@example.com", 900) == 2
    assert db.count_recent_magic_links("c@example.com", 900) == 0


def test_dossier_draft_is_locked_once_joined():
    reset()
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 10)
    resident = make_joined_resident(nb, "a@example.com", "Noa")
    db.save_dossier_draft(resident["id"], "Evil", "Other", "overwrite", {"essence": "x"})
    after = db.get_resident(resident["id"])
    assert after["name"] == "Noa"
    assert after["card"]["essence"] == "Noa is real"


# ----- invitations + the mutual yes/no gate -----------------------------------

def _invitation(nb, residents):
    run_id = db.create_run(nb["id"])
    member_ids = ["r" + str(r["id"]) for r in residents]
    details = {"conversation_id": 1, "invite": {"activity": "dinner", "when": "Sun", "where": "here"},
               "pitches": {member_ids[0]: "pitch one"}}
    match_id = db.create_invitation(run_id, member_ids, "a headline", 9, details)
    db.create_pending_acceptances(match_id, [r["id"] for r in residents])
    return run_id, match_id


def test_create_invitation_round_trips_details():
    reset()
    nb = db.get_or_create_neighborhood("ten-trails", "Ten Trails", 3)
    r1 = make_joined_resident(nb, "a@example.com", "Noa")
    r2 = make_joined_resident(nb, "b@example.com", "Marcus")
    _, match_id = _invitation(nb, [r1, r2])
    match = db.get_match(match_id)
    assert match["member_ids"] == ["r" + str(r1["id"]), "r" + str(r2["id"])]
    assert match["headline"] == "a headline"
    assert match["depth"] == 9
    assert match["details"]["invite"]["activity"] == "dinner"
    assert {a["status"] for a in db.list_match_acceptances(match_id)} == {"pending"}


def test_respond_to_acceptance_first_response_wins():
    reset()
    nb = db.get_or_create_neighborhood("ten-trails", "Ten Trails", 3)
    r1 = make_joined_resident(nb, "a@example.com", "Noa")
    _, match_id = _invitation(nb, [r1])
    assert db.respond_to_acceptance(match_id, r1["id"], "accepted") is True
    assert db.respond_to_acceptance(match_id, r1["id"], "declined") is False
    assert db.get_acceptance(match_id, r1["id"])["status"] == "accepted"


def test_mark_match_sealed_and_dissolved_are_idempotent():
    reset()
    nb = db.get_or_create_neighborhood("ten-trails", "Ten Trails", 3)
    _, match_id = _invitation(nb, [make_joined_resident(nb, "a@example.com", "Noa")])
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
    r1 = make_joined_resident(nb, "a@example.com", "Noa")
    _, first = _invitation(nb, [r1])
    _, second = _invitation(nb, [r1])
    assert db.latest_match_acceptance(r1["id"])["match_id"] == second
    assert first != second


def test_eligible_needs_a_joined_agent_with_a_dossier():
    reset()
    nb = db.get_or_create_neighborhood("ten-trails", "Ten Trails", 3)
    make_joined_resident(nb, "a@example.com", "Noa")
    # complete from the old onboarding chat, but no dossier: never eligible
    legacy = db.get_or_create_resident(nb["id"], "old@example.com", "google")
    db.mark_profile_complete(legacy["id"])
    eligible = db.list_eligible_residents(nb["id"])
    assert [r["name"] for r in eligible] == ["Noa"]


def test_eligible_excludes_live_invitations_and_includes_dissolved_ones():
    reset()
    nb = db.get_or_create_neighborhood("ten-trails", "Ten Trails", 3)
    r1 = make_joined_resident(nb, "a@example.com", "Noa")
    r2 = make_joined_resident(nb, "b@example.com", "Marcus")
    assert len(db.list_eligible_residents(nb["id"])) == 2
    _, match_id = _invitation(nb, [r1, r2])
    assert db.list_eligible_residents(nb["id"]) == []
    db.mark_match_dissolved(match_id)
    assert len(db.list_eligible_residents(nb["id"])) == 2


# ----- runs, events, agent conversations ----------------------------------------

def test_events_are_logged_in_order_per_run():
    reset()
    run_a = db.create_run()
    run_b = db.create_run()
    db.log_event(run_a, "hub", "thought", "first", None)
    db.log_event(run_b, "code", "check", "other run", None)
    db.log_event(run_a, "agent", "message", "second", "7")
    events = db.list_events(run_a)
    assert [(e["actor"], e["text"], e["ref"]) for e in events] == [("hub", "first", None), ("agent", "second", "7")]


def test_agent_conversation_turns_and_verdict_round_trip():
    reset()
    run_id = db.create_run()
    cid = db.save_agent_conversation(run_id, "r1", "r2", "why", [])
    db.set_agent_turns(cid, [{"by": "r1", "text": "hi"}])
    db.set_agent_verdict(cid, {"depth": 9, "invited": True}, True)
    saved = db.list_agent_conversations(run_id)[0]
    assert saved["turns"] == [{"by": "r1", "text": "hi"}]
    assert saved["verdict"]["depth"] == 9 and saved["invited"] is True
    assert len(db.list_agent_conversations()) == 1


def test_run_summaries_count_conversations_invitations_and_failures():
    reset()
    nb = db.get_or_create_neighborhood("ten-trails", "Ten Trails", 3)
    r1 = make_joined_resident(nb, "a@example.com", "Noa")
    r2 = make_joined_resident(nb, "b@example.com", "Marcus")
    run_id, _ = _invitation(nb, [r1, r2])
    done = db.save_agent_conversation(run_id, "r1", "r2", "", [])
    db.set_agent_verdict(done, {"depth": 9}, True)
    db.save_agent_conversation(run_id, "r1", "r3", "", [])     # never judged = failed
    db.set_run_usage(run_id, {"total": 14, "by_model": {}})
    summary = db.list_runs_for_neighborhood(nb["id"])[0]
    assert summary["conversation_count"] == 2
    assert summary["invitation_count"] == 1
    assert summary["failed_count"] == 1
    assert summary["usage"]["total"] == 14
    assert db.get_run(run_id)["usage"]["total"] == 14
    assert db.get_run(999999) is None


# ----- full reset ------------------------------------------------------------

def test_reset_all_wipes_everything():
    reset()
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 100)
    make_joined_resident(nb, "a@example.com", "Noa")
    run_id = db.create_run(nb["id"])
    db.log_event(run_id, "hub", "thought", "x")
    db.save_agent_conversation(run_id, "r1", "r2", "", [])
    db.create_session("tok-1", "a@example.com", "resident", 1, nb["id"], 3600)
    db.create_magic_link_token("hash-1", "a@example.com", nb["id"], 900)
    db.create_oauth_state("state-hash", nb["id"], 900)

    db.reset_all()

    assert db.get_neighborhood_by_slug("ballard") is None
    assert db.get_session("tok-1") is None
    assert db.list_events(run_id) == []
    assert db.list_agent_conversations() == []


# ----- ai_calls + neighborhood activity ---------------------------------------------------

def test_ai_calls_split_into_rounds_and_signups():
    reset()
    db.log_ai_call(1, 9, None, "pairing", "m", "s", [], "r", 1, 2, 3, None)
    db.log_ai_call(None, 9, 4, "card", "m", "s", [{"role": "user", "content": "x"}], "r", None, None, 3, None)
    db.log_ai_call(None, 8, 5, "card", "m", "s", [], None, None, None, 3, "boom")
    assert [c["purpose"] for c in db.list_ai_calls(1)] == ["pairing"]
    signup = db.list_signup_ai_calls(9)
    assert len(signup) == 1 and signup[0]["resident_id"] == 4
    assert signup[0]["messages"] == [{"role": "user", "content": "x"}]
    assert db.list_signup_ai_calls(8)[0]["error"] == "boom"


def test_neighborhood_events_keep_the_most_recent_in_order():
    reset()
    i = 0
    while i < 5:
        db.log_event(None, "system", "system", "e" + str(i), None, 3)
        i += 1
    db.log_event(None, "system", "system", "elsewhere", None, 4)
    assert [e["text"] for e in db.list_neighborhood_events(3, limit=3)] == ["e2", "e3", "e4"]
