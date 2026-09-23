"""Tests for admin.py -- the admin dashboard's read-only aggregation:
neighborhood progress, resident status, hub rounds, and each round's full
behind-the-scenes record."""

import admin
import db
from conftest import make_joined_resident, reset_db


def make_neighborhood(threshold=3):
    return db.get_or_create_neighborhood("ten-trails", "Ten Trails", threshold)


def invite(nb, residents):
    run_id = db.create_run(nb["id"])
    member_ids = ["r" + str(r["id"]) for r in residents]
    match_id = db.create_invitation(run_id, member_ids, "headline", 9,
                                    {"conversation_id": 1, "invite": {}, "pitches": {}})
    db.create_pending_acceptances(match_id, [r["id"] for r in residents])
    return run_id, match_id


# ----- neighborhood progress -------------------------------------------------

def test_neighborhood_progress_counts_joined_agents_and_everyone_registered():
    reset_db()
    nb = make_neighborhood(threshold=3)
    make_joined_resident(nb, "a@example.com", "Alex")
    db.get_or_create_resident(nb["id"], "b@example.com", "google")   # registered, no agent yet

    progress = admin.neighborhood_progress(db.get_neighborhood(nb["id"]))
    assert progress["complete_count"] == 1
    assert progress["resident_count"] == 2
    assert progress["batch_threshold"] == 3
    assert progress["batch_triggered_at"] is None


def test_list_neighborhood_progress_covers_every_neighborhood():
    reset_db()
    make_neighborhood()
    db.get_or_create_neighborhood("fremont", "Fremont", 50)
    assert {r["slug"] for r in admin.list_neighborhood_progress()} == {"ten-trails", "fremont"}


# ----- resident status rollup ----------------------------------------------------

def test_resident_status_joining_then_in_pool():
    reset_db()
    nb = make_neighborhood()
    db.get_or_create_resident(nb["id"], "a@example.com", "google")
    assert admin.resident_summaries(nb["id"])[0]["status"] == "joining"

    reset_db()
    nb = make_neighborhood()
    make_joined_resident(nb, "a@example.com", "Alex", source="Muse")
    summary = admin.resident_summaries(nb["id"])[0]
    assert summary["status"] == "in_pool"
    assert summary["source"] == "Muse"


def test_resident_status_follows_the_invitation():
    reset_db()
    nb = make_neighborhood()
    a = make_joined_resident(nb, "a@example.com", "Alex")
    b = make_joined_resident(nb, "b@example.com", "Bao")
    _, match_id = invite(nb, [a, b])

    def statuses():
        return {s["id"]: s["status"] for s in admin.resident_summaries(nb["id"])}

    assert statuses()[a["id"]] == "match_pending"
    db.respond_to_acceptance(match_id, a["id"], "accepted")
    assert statuses()[a["id"]] == "match_waiting"
    db.respond_to_acceptance(match_id, b["id"], "accepted")
    db.mark_match_sealed(match_id)
    assert statuses() == {a["id"]: "sealed", b["id"]: "sealed"}


def test_resident_status_dissolved():
    reset_db()
    nb = make_neighborhood()
    a = make_joined_resident(nb, "a@example.com", "Alex")
    _, match_id = invite(nb, [a])
    db.mark_match_dissolved(match_id)
    assert admin.resident_summaries(nb["id"])[0]["status"] == "dissolved"


# ----- hub rounds -----------------------------------------------------------------

def test_recent_run_summaries_respects_limit_and_ordering():
    reset_db()
    nb = make_neighborhood()
    ids = []
    n = 0
    while n < 3:
        ids.append(db.create_run(nb["id"]))
        n += 1
    runs = admin.recent_run_summaries(nb["id"], limit=2)
    assert [r["id"] for r in runs] == [ids[2], ids[1]]   # newest first


def test_run_detail_has_every_event_and_conversation_with_names():
    reset_db()
    nb = make_neighborhood()
    a = make_joined_resident(nb, "a@example.com", "Alex")
    b = make_joined_resident(nb, "b@example.com", "Bao")
    run_id = db.create_run(nb["id"])
    ra = "r" + str(a["id"])
    rb = "r" + str(b["id"])
    cid = db.save_agent_conversation(run_id, ra, rb, "both want a table", [{"by": ra, "text": "hi"}])
    db.set_agent_verdict(cid, {"depth": 9, "invited": True, "headline": "h", "thoughts": "t", "gate": []}, True)
    db.log_event(run_id, "hub", "thought", "the hub's reasoning")
    db.log_event(run_id, "agent", "message", "Alex's agent: hi", str(cid))

    detail = admin.run_detail(run_id)
    assert detail["run"]["id"] == run_id
    assert detail["names"] == {ra: "Alex", rb: "Bao"}
    assert detail["conversations"][0]["turns"] == [{"by": ra, "text": "hi"}]
    assert [e["text"] for e in detail["events"]] == ["the hub's reasoning", "Alex's agent: hi"]
    assert admin.run_detail(999999) is None


# ----- logs visible to the admin ----------------------------------------------------

def test_neighborhood_activity_and_run_detail_expose_every_log():
    reset_db()
    nb = make_neighborhood()
    run_id = db.create_run(nb["id"])
    db.log_event(None, "human", "human", "Alex joined.", None, nb["id"])
    db.log_event(run_id, "hub", "thought", "reasoning", None, nb["id"])
    db.log_ai_call(run_id, nb["id"], None, "verdict", "claude-opus-5-5", "sys", [{"role": "user", "content": "t"}],
                   "reply", 10, 5, 42, None)
    db.log_ai_call(None, nb["id"], 1, "card", "claude-sonnet-4-6", "sys", [], "card reply", None, None, 7, None)

    activity = admin.neighborhood_activity(nb["id"])
    assert [e["text"] for e in activity["events"]] == ["Alex joined.", "reasoning"]
    assert [c["purpose"] for c in activity["signup_ai_calls"]] == ["card"]

    detail = admin.run_detail(run_id)
    assert [c["purpose"] for c in detail["ai_calls"]] == ["verdict"]
    assert detail["ai_calls"][0]["reply"] == "reply"
