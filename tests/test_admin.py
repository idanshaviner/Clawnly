"""Tests for admin.py -- the admin dashboard's read-only aggregation
(PILOT_PLAN.md's admin surface, stage 6)."""

import admin
import db
from users import USERS


def reset():
    db.reset_all(USERS)


def make_neighborhood(threshold=3):
    return db.get_or_create_neighborhood("ten-trails", "Ten Trails", threshold)


def make_resident(nb, email, name=None):
    resident = db.get_or_create_resident(nb["id"], email, "google")
    if name is not None:
        db.update_resident_profile(resident["id"], {"name": name})
    return resident


# ----- neighborhood_progress / list_neighborhood_progress ---------------------

def test_neighborhood_progress_counts_complete_and_total():
    reset()
    nb = make_neighborhood(threshold=3)
    a = make_resident(nb, "a@example.com")
    make_resident(nb, "b@example.com")
    db.mark_profile_complete(a["id"])

    progress = admin.neighborhood_progress(db.get_neighborhood(nb["id"]))
    assert progress["complete_count"] == 1
    assert progress["resident_count"] == 2
    assert progress["batch_threshold"] == 3
    assert progress["batch_triggered_at"] is None


def test_list_neighborhood_progress_covers_every_neighborhood():
    reset()
    make_neighborhood(threshold=3)
    db.get_or_create_neighborhood("fremont", "Fremont", 50)
    rows = admin.list_neighborhood_progress()
    slugs = {r["slug"] for r in rows}
    assert slugs == {"ten-trails", "fremont"}


# ----- resident_summaries: status rollup --------------------------------------

def test_resident_status_onboarding_when_not_complete():
    reset()
    nb = make_neighborhood()
    make_resident(nb, "a@example.com")
    summaries = admin.resident_summaries(nb["id"])
    assert summaries[0]["status"] == "onboarding"


def test_resident_status_complete_unmatched():
    reset()
    nb = make_neighborhood()
    a = make_resident(nb, "a@example.com")
    db.mark_profile_complete(a["id"])
    summaries = admin.resident_summaries(nb["id"])
    assert summaries[0]["status"] == "complete_unmatched"


def test_resident_status_match_pending_then_sealed():
    reset()
    nb = make_neighborhood()
    a = db.mark_profile_complete(make_resident(nb, "a@example.com", "Alex")["id"])
    b = db.mark_profile_complete(make_resident(nb, "b@example.com", "Bao")["id"])
    match_id = db.save_match(db.create_run("live", "sig", nb["id"]), 0, {
        "group": ["r" + str(a["id"]), "r" + str(b["id"])], "reason": "x", "scores": {}, "why_not": [],
    })
    db.create_pending_acceptances(match_id, [a["id"], b["id"]])

    summaries = {s["id"]: s["status"] for s in admin.resident_summaries(nb["id"])}
    assert summaries[a["id"]] == "match_pending"

    db.respond_to_acceptance(match_id, a["id"], "accepted")
    summaries = {s["id"]: s["status"] for s in admin.resident_summaries(nb["id"])}
    assert summaries[a["id"]] == "match_waiting"

    db.respond_to_acceptance(match_id, b["id"], "accepted")
    db.mark_match_sealed(match_id)
    summaries = {s["id"]: s["status"] for s in admin.resident_summaries(nb["id"])}
    assert summaries[a["id"]] == "sealed"
    assert summaries[b["id"]] == "sealed"


def test_resident_status_dissolved():
    reset()
    nb = make_neighborhood()
    a = db.mark_profile_complete(make_resident(nb, "a@example.com")["id"])
    match_id = db.save_match(db.create_run("live", "sig", nb["id"]), 0, {
        "group": ["r" + str(a["id"])], "reason": "x", "scores": {}, "why_not": [],
    })
    db.create_pending_acceptances(match_id, [a["id"]])
    db.mark_match_dissolved(match_id)
    summaries = admin.resident_summaries(nb["id"])
    assert summaries[0]["status"] == "dissolved"


# ----- recent_run_summaries: usage + interview errors --------------------------

def test_recent_run_summaries_includes_usage_and_errors():
    reset()
    nb = make_neighborhood()
    run_id = db.create_run("live", "sig", nb["id"])
    db.save_interviews(run_id, {
        "r1": {"profile": {"name": "A"}, "q1": "x", "q2": "y"},
        "r2": {"profile": {"name": "B"}, "q1": None, "q2": None, "error": "boom"},
    })
    db.save_match(run_id, 0, {"group": ["r1"], "reason": "x", "scores": {}, "why_not": []})
    db.finish_run(run_id, [])
    db.set_run_usage(run_id, {"total": 7, "by_model": {"claude-haiku-4-5": 5, "claude-opus-4-8": 2}})

    runs = admin.recent_run_summaries(nb["id"])
    assert len(runs) == 1
    run = runs[0]
    assert run["group_count"] == 1
    assert run["usage"]["total"] == 7
    assert len(run["interview_errors"]) == 1
    assert run["interview_errors"][0]["id"] == "r2"


def test_recent_run_summaries_respects_limit_and_ordering():
    reset()
    nb = make_neighborhood()
    ids = []
    n = 0
    while n < 3:
        run_id = db.create_run("live", "sig-" + str(n), nb["id"])
        db.finish_run(run_id, [])
        ids.append(run_id)
        n += 1
    runs = admin.recent_run_summaries(nb["id"], limit=2)
    assert len(runs) == 2
    assert runs[0]["id"] == ids[-1]   # newest first
