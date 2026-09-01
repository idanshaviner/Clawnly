"""Tests for batch.py -- the headcount-threshold batch trigger + resident ->
profile-dict mapping (PILOT_PLAN.md stage 4)."""

import json

import batch
import db
from conftest import FakeClient, json_body, run
from users import USERS


def reset():
    db.reset_all(USERS)


def make_neighborhood(threshold=3):
    return db.get_or_create_neighborhood("ten-trails", "Ten Trails", threshold)


def make_complete_resident(nb, email, name, availability=None, hobbies=None):
    resident = db.get_or_create_resident(nb["id"], email, "magic_link")
    fields = {
        "name": name, "age": 29, "gender": "nonbinary", "personality": "mixed",
        "occupation": "working professional",
        "hobbies": hobbies or ["hiking", "board games"],
        "availability": availability or ["weekend_daytime"],
        "location": "Ten Trails", "bio": name + " is getting to know the neighborhood.",
        "preferred_group_size": "no preference",
    }
    db.update_resident_profile(resident["id"], fields)
    return db.mark_profile_complete(resident["id"])


def match_obj(group):
    return {
        "group": group,
        "reason": "Shared weekend availability and an outdoorsy streak.",
        "scores": {"personality": 4, "availability": 4, "interests": 4, "size_fit": 4},
        "why_not": [],
    }


def pipeline_fake(group_ids):
    g1 = json_body(match_obj(group_ids))
    refuse = json_body({"group": [], "reason": "no more viable groups", "scores": {}, "why_not": []})
    popup = json_body({"options": [
        {"event_name": "Trailhead Meetup", "activity": "a short hike", "location": "Ten Trails trailhead",
         "time": "Saturday morning", "reason": "Everyone's free and into the outdoors."},
    ]})
    return FakeClient(
        match_queue=[g1, refuse],
        propose_queue=[json_body({"activity": "a short hike", "pitch": "Hike Saturday?"})],
        assess_queue=[json_body({"agreed": True, "concern": ""})],
        popup_queue=[popup],
    )


# ----- resident_to_profile: defaults for whatever onboarding never caught ----

def test_resident_to_profile_uses_real_values_when_present():
    reset()
    nb = make_neighborhood()
    resident = make_complete_resident(nb, "a@example.com", "Sam")
    profile = batch.resident_to_profile(resident, nb)
    assert profile["id"] == "r" + str(resident["id"])
    assert profile["name"] == "Sam"
    assert profile["hobbies"] == ["hiking", "board games"]
    assert profile["availability"] == ["weekend_daytime"]
    assert profile["preferred_group_size"] == "no preference"


def test_resident_to_profile_fills_in_sane_defaults_for_missing_fields():
    reset()
    nb = make_neighborhood()
    # only the five gating slots' worth of fields set -- the rest (name, age,
    # gender, occupation, location, bio) never came up in conversation.
    resident = db.get_or_create_resident(nb["id"], "b@example.com", "google")
    db.update_resident_profile(resident["id"], {
        "personality": "introverted", "hobbies": ["chess"],
        "availability": ["weekday_evening"], "preferred_group_size": [2, 3],
    })
    resident = db.mark_profile_complete(resident["id"])
    profile = batch.resident_to_profile(resident, nb)
    # every field run_pipeline/Claw needs is present and individually valid --
    # nothing crashes on a plain dict index.
    required = ["id", "name", "age", "gender", "hobbies", "personality",
                "occupation", "availability", "location", "bio", "preferred_group_size"]
    for field in required:
        assert field in profile
        assert profile[field] not in (None, "")
    assert isinstance(profile["age"], int)
    assert profile["gender"] == "unspecified"
    assert profile["occupation"] in ("student", "working professional", "freelancer")
    assert profile["location"] == nb["name"]


def test_resident_to_profile_drops_invalid_stored_values_to_defaults():
    reset()
    nb = make_neighborhood()
    resident = db.get_or_create_resident(nb["id"], "c@example.com", "google")
    # simulate a corrupted/impossible stored profile (should never normally
    # happen -- onboarding.py already validates -- but resident_to_profile
    # must not trust it blindly either).
    db.update_resident_profile(resident["id"], {
        "personality": "moody", "occupation": "wizard",
        "preferred_group_size": [9, 12],
    })
    resident = db.mark_profile_complete(resident["id"])
    profile = batch.resident_to_profile(resident, nb)
    assert profile["personality"] == "mixed"
    assert profile["occupation"] == "working professional"
    assert profile["preferred_group_size"] == "no preference"


# ----- check_and_trigger_batch: threshold gating -----------------------------

def test_below_threshold_does_not_trigger():
    reset()
    nb = make_neighborhood(threshold=3)
    make_complete_resident(nb, "a@example.com", "A")
    make_complete_resident(nb, "b@example.com", "B")
    fake = FakeClient()
    run(batch.check_and_trigger_batch(nb["id"], client=fake))
    assert db.get_neighborhood(nb["id"])["batch_triggered_at"] is None
    assert fake.calls == []


def test_unknown_neighborhood_is_a_no_op():
    reset()
    fake = FakeClient()
    run(batch.check_and_trigger_batch(999999, client=fake))
    assert fake.calls == []


# ----- check_and_trigger_batch: trigger + full persistence -------------------

def test_at_threshold_triggers_runs_and_persists():
    reset()
    nb = make_neighborhood(threshold=3)
    r1 = make_complete_resident(nb, "a@example.com", "A", availability=["weekend_daytime"])
    r2 = make_complete_resident(nb, "b@example.com", "B", availability=["weekend_daytime"])
    r3 = make_complete_resident(nb, "c@example.com", "C", availability=["weekend_daytime"])
    group_ids = ["r" + str(r1["id"]), "r" + str(r2["id"]), "r" + str(r3["id"])]
    fake = pipeline_fake(group_ids)

    run(batch.check_and_trigger_batch(nb["id"], client=fake))

    neighborhood = db.get_neighborhood(nb["id"])
    assert neighborhood["batch_triggered_at"] is not None

    # persisted exactly like app.py's admin-console runs, but neighborhood-tagged.
    conn = db._get_conn()
    run_row = conn.execute(
        "SELECT * FROM runs WHERE neighborhood_id = ? ORDER BY id DESC LIMIT 1", (nb["id"],)
    ).fetchone()
    assert run_row is not None
    assert run_row["mode"] == "live"

    result = db.load_run_result(run_row["id"])
    assert len(result["groups"]) == 1
    g = result["groups"][0]
    assert g["match"]["group"] == group_ids
    assert g["negotiation"]["agreed"] is True
    assert g["popup"]["event_name"] == "Trailhead Meetup"


def test_compare_and_swap_prevents_double_trigger():
    reset()
    nb = make_neighborhood(threshold=3)
    r1 = make_complete_resident(nb, "a@example.com", "A", availability=["weekend_daytime"])
    r2 = make_complete_resident(nb, "b@example.com", "B", availability=["weekend_daytime"])
    r3 = make_complete_resident(nb, "c@example.com", "C", availability=["weekend_daytime"])
    group_ids = ["r" + str(r1["id"]), "r" + str(r2["id"]), "r" + str(r3["id"])]

    fake1 = pipeline_fake(group_ids)
    run(batch.check_and_trigger_batch(nb["id"], client=fake1))
    assert len(fake1.calls) > 0   # first call actually ran the pipeline

    # a second near-simultaneous "completion" re-checks the same neighborhood --
    # batch_triggered_at is already set, so this must be a pure no-op.
    fake2 = FakeClient()
    run(batch.check_and_trigger_batch(nb["id"], client=fake2))
    assert fake2.calls == []

    conn = db._get_conn()
    count = conn.execute(
        "SELECT COUNT(*) FROM runs WHERE neighborhood_id = ?", (nb["id"],)
    ).fetchone()[0]
    assert count == 1   # only one run persisted, not two


def test_try_trigger_batch_cas_directly():
    reset()
    nb = make_neighborhood(threshold=3)
    first = db.try_trigger_batch(nb["id"])
    second = db.try_trigger_batch(nb["id"])
    assert first is True
    assert second is False


def test_every_interview_failing_still_completes_with_no_groups():
    # master_claw.py isolates per-Claw interview errors (SPEC), so a totally
    # broken client (e.g. the invalid-key situation flagged in ROADMAP.md)
    # doesn't raise here -- it just leaves everyone uninterviewed, so no
    # candidate ever reaches the match stage. The run still completes and
    # persists (0 groups, everyone unmatched), which matters operationally:
    # this is what actually happens on this dev machine's expired key today.
    reset()
    nb = make_neighborhood(threshold=3)
    make_complete_resident(nb, "a@example.com", "A")
    make_complete_resident(nb, "b@example.com", "B")
    make_complete_resident(nb, "c@example.com", "C")

    class BrokenMessages:
        async def create(self, **kwargs):
            raise RuntimeError("simulated API outage")

    class BrokenClient:
        def __init__(self):
            self.messages = BrokenMessages()

    run(batch.check_and_trigger_batch(nb["id"], client=BrokenClient()))
    neighborhood = db.get_neighborhood(nb["id"])
    assert neighborhood["batch_triggered_at"] is not None
    conn = db._get_conn()
    run_row = conn.execute(
        "SELECT * FROM runs WHERE neighborhood_id = ? ORDER BY id DESC LIMIT 1", (nb["id"],)
    ).fetchone()
    assert run_row is not None
    result = db.load_run_result(run_row["id"])
    assert result["groups"] == []
    # a failed interview never becomes a match "candidate" in the first place
    # (master_claw.py's per-Claw error isolation), so it doesn't show up in
    # "unmatched" either -- every one of the 3 interviews recorded its error.
    assert result["unmatched"] == []
    interview_ids = list(result["interviews"].keys())
    assert len(interview_ids) == 3
    for uid in interview_ids:
        assert "error" in result["interviews"][uid]


def test_pipeline_exception_does_not_raise_out_of_the_background_task():
    reset()
    nb = make_neighborhood(threshold=3)
    make_complete_resident(nb, "a@example.com", "A")
    make_complete_resident(nb, "b@example.com", "B")
    make_complete_resident(nb, "c@example.com", "C")

    # interviews succeed (default canned reply) but the match call has
    # nothing queued -> IndexError, a genuine exception out of run_pipeline.
    fake = FakeClient(match_queue=[])

    # must not raise -- a background fire-and-forget task's exception should
    # never propagate up through take_turn's response to the resident.
    run(batch.check_and_trigger_batch(nb["id"], client=fake))
    neighborhood = db.get_neighborhood(nb["id"])
    assert neighborhood["batch_triggered_at"] is not None   # CAS already spent
    conn = db._get_conn()
    count = conn.execute(
        "SELECT COUNT(*) FROM runs WHERE neighborhood_id = ?", (nb["id"],)
    ).fetchone()[0]
    assert count == 0   # nothing half-persisted


# ----- force_trigger_batch: admin manual override (stage 6) ------------------

def test_force_trigger_requires_at_least_two_eligible_residents():
    reset()
    nb = make_neighborhood(threshold=100)   # would never auto-trigger
    make_complete_resident(nb, "a@example.com", "A")
    fake = FakeClient()
    run_id, error = run(batch.force_trigger_batch(nb["id"], client=fake))
    assert run_id is None
    assert "at least 2" in error
    assert fake.calls == []


def test_force_trigger_unknown_neighborhood():
    reset()
    run_id, error = run(batch.force_trigger_batch(999999, client=FakeClient()))
    assert run_id is None
    assert error == "No such neighborhood."


def test_force_trigger_bypasses_the_threshold():
    reset()
    nb = make_neighborhood(threshold=100)   # nowhere close to met
    r1 = make_complete_resident(nb, "a@example.com", "A", availability=["weekend_daytime"])
    r2 = make_complete_resident(nb, "b@example.com", "B", availability=["weekend_daytime"])
    r3 = make_complete_resident(nb, "c@example.com", "C", availability=["weekend_daytime"])
    group_ids = ["r" + str(r1["id"]), "r" + str(r2["id"]), "r" + str(r3["id"])]
    fake = pipeline_fake(group_ids)

    run_id, error = run(batch.force_trigger_batch(nb["id"], client=fake))
    assert error is None
    assert run_id is not None
    assert db.get_neighborhood(nb["id"])["batch_triggered_at"] is not None
    result = db.load_run_result(run_id)
    assert result["groups"][0]["match"]["group"] == group_ids


def test_force_trigger_records_usage():
    reset()
    nb = make_neighborhood(threshold=100)
    r1 = make_complete_resident(nb, "a@example.com", "A", availability=["weekend_daytime"])
    r2 = make_complete_resident(nb, "b@example.com", "B", availability=["weekend_daytime"])
    r3 = make_complete_resident(nb, "c@example.com", "C", availability=["weekend_daytime"])
    group_ids = ["r" + str(r1["id"]), "r" + str(r2["id"]), "r" + str(r3["id"])]
    fake = pipeline_fake(group_ids)

    run_id, error = run(batch.force_trigger_batch(nb["id"], client=fake))
    assert error is None
    conn = db._get_conn()
    row = conn.execute("SELECT usage FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert row["usage"] is not None
    import json as jsonlib
    usage_data = jsonlib.loads(row["usage"])
    assert usage_data["total"] > 0


def test_force_trigger_can_fire_again_after_an_earlier_trigger():
    reset()
    nb = make_neighborhood(threshold=2)
    r1 = make_complete_resident(nb, "a@example.com", "A", availability=["weekend_daytime"])
    r2 = make_complete_resident(nb, "b@example.com", "B", availability=["weekend_daytime"])
    group_ids = ["r" + str(r1["id"]), "r" + str(r2["id"])]

    # the automatic threshold trigger fires once, dissolving isn't simulated here --
    # just confirm force_trigger_batch doesn't get blocked by an already-set
    # batch_triggered_at the way the automatic CAS would.
    db.try_trigger_batch(nb["id"])
    assert db.get_neighborhood(nb["id"])["batch_triggered_at"] is not None

    fake = pipeline_fake(group_ids)
    run_id, error = run(batch.force_trigger_batch(nb["id"], client=fake))
    assert error is None
    assert run_id is not None


def test_default_client_falls_back_to_config_get_client(monkeypatch):
    reset()
    nb = make_neighborhood(threshold=3)
    r1 = make_complete_resident(nb, "a@example.com", "A", availability=["weekend_daytime"])
    r2 = make_complete_resident(nb, "b@example.com", "B", availability=["weekend_daytime"])
    r3 = make_complete_resident(nb, "c@example.com", "C", availability=["weekend_daytime"])
    group_ids = ["r" + str(r1["id"]), "r" + str(r2["id"]), "r" + str(r3["id"])]
    fake = pipeline_fake(group_ids)
    import config
    monkeypatch.setattr(config, "get_client", lambda: fake)
    run(batch.check_and_trigger_batch(nb["id"]))
    assert len(fake.calls) > 0
