"""Tests for the Master Claw: interviews, matching, validation (SPEC 3/6/6b)."""

import config
from conftest import FakeClient, json_body, run
from llm_io import extract_json
from master_claw import MasterClaw
from users import USERS


def valid_match_obj(group=None):
    if group is None:
        group = ["u01", "u04", "u10"]
    return {
        "group": group,
        "reason": "Maya, Marcus and Omar are all free weekday evenings and share a calm, intellectual streak.",
        "scores": {"personality": 3, "availability": 4, "interests": 4, "size_fit": 5},
        "why_not": [{"id": "u08", "reason": "Ethan wants a group of 6-8, too big for this meetup."}],
    }


# ----- interviews -----------------------------------------------------------

def test_interviews_keyed_by_id_for_all_users():
    mc = MasterClaw(USERS, client=FakeClient())
    interviews = run(mc.interview_claws())
    assert set(interviews.keys()) == set(u["id"] for u in USERS)
    assert interviews["u01"]["q1"] == "canned interview answer"
    assert interviews["u01"]["q2"] == "canned interview answer"


def test_interview_error_isolation():
    mc = MasterClaw(USERS, client=FakeClient(fail_names=["Aisha"]))
    interviews = run(mc.interview_claws())
    assert "error" in interviews["u07"]            # Aisha failed
    assert "error" not in interviews["u01"]         # others fine
    assert "u07" not in mc._candidate_ids(interviews)
    assert len(interviews) == 12                    # run still completes


def test_interviews_batched_one_call_per_claw():
    fake = FakeClient()
    mc = MasterClaw(USERS, client=fake)
    run(mc.interview_claws())
    interview_calls = [k for k in fake.kinds() if k == "interview"]
    assert len(interview_calls) == 12               # batched: one call per user, not two


# ----- matching: happy path, repair, refusal, fallback ----------------------

def test_find_matches_accepts_valid_group():
    fake = FakeClient(match_queue=[json_body(valid_match_obj())])
    mc = MasterClaw(USERS, client=fake)
    out = run(mc.find_matches(run(mc.interview_claws())))
    assert out["group"] == ["u01", "u04", "u10"]
    assert out["scores"]["size_fit"] == 5


def test_find_matches_repairs_constraint_violation():
    bad = json_body(valid_match_obj(group=["u07", "u04"]))   # H2 fail + under 3
    good = json_body(valid_match_obj())
    fake = FakeClient(match_queue=[bad, good])
    mc = MasterClaw(USERS, client=fake)
    out = run(mc.find_matches(run(mc.interview_claws())))
    assert out["group"] == ["u01", "u04", "u10"]
    match_calls = [k for k in fake.kinds() if k == "match"]
    assert len(match_calls) == 2                     # retried once


def test_find_matches_retries_on_invalid_json():
    fake = FakeClient(match_queue=["this is not json at all", json_body(valid_match_obj())])
    mc = MasterClaw(USERS, client=fake)
    out = run(mc.find_matches(run(mc.interview_claws())))
    assert out["group"] == ["u01", "u04", "u10"]


def test_find_matches_accepts_empty_group():
    empty = json_body({"group": [], "reason": "no shared time across viable sets", "scores": {}, "why_not": []})
    fake = FakeClient(match_queue=[empty])
    mc = MasterClaw(USERS, client=fake)
    out = run(mc.find_matches(run(mc.interview_claws())))
    assert out["group"] == []


def test_find_matches_falls_back_when_never_valid():
    bad = json_body(valid_match_obj(group=["u07", "u04"]))   # always violates
    fake = FakeClient(match_queue=[bad, bad, bad, bad, bad])
    mc = MasterClaw(USERS, client=fake)
    out = run(mc.find_matches(run(mc.interview_claws())))
    assert out["group"] == []                        # never ships a bad group
    assert "satisf" in out["reason"].lower()


def test_match_call_uses_strong_model():
    fake = FakeClient(match_queue=[json_body(valid_match_obj())])
    mc = MasterClaw(USERS, client=fake)
    run(mc.find_matches(run(mc.interview_claws())))
    match_kwargs = [kw for kind, kw in fake.calls if kind == "match"][0]
    assert match_kwargs["model"] == config.MODEL_MATCH
    # Opus 4.8 rejects `temperature`; the match call must not send it.
    assert "temperature" not in match_kwargs


def test_find_all_matches_partitions_pool_no_overlap():
    a = json_body(valid_match_obj(["u01", "u04", "u10"]))
    b = json_body(valid_match_obj(["u03", "u09", "u11"]))
    refuse = json_body({"group": [], "reason": "no more viable groups", "scores": {}, "why_not": []})
    fake = FakeClient(match_queue=[a, b, refuse])
    mc = MasterClaw(USERS, client=fake)
    out = run(mc.find_all_matches(run(mc.interview_claws())))
    assert len(out["groups"]) == 2
    assert out["groups"][0]["group"] == ["u01", "u04", "u10"]
    assert out["groups"][1]["group"] == ["u03", "u09", "u11"]
    g1 = set(out["groups"][0]["group"])
    g2 = set(out["groups"][1]["group"])
    assert g1.isdisjoint(g2)                       # non-overlapping
    assert len(out["unmatched"]) == 6              # the rest are left over


def test_past_feedback_is_injected_into_match_prompt():
    fb = [{"members": ["Ethan", "Sofia"], "rating": "down", "note": "too loud for them"}]
    fake = FakeClient(match_queue=[json_body(valid_match_obj())])
    mc = MasterClaw(USERS, client=fake, feedback=fb)
    run(mc.find_matches(run(mc.interview_claws())))
    payload = [kw for kind, kw in fake.calls if kind == "match"][0]["messages"][0]["content"]
    assert "PAST FEEDBACK" in payload
    assert "too loud for them" in payload and "Ethan" in payload
    assert "[BAD]" in payload                         # a thumbs-down is marked BAD


def test_find_all_matches_stops_when_no_group():
    refuse = json_body({"group": [], "reason": "none", "scores": {}, "why_not": []})
    fake = FakeClient(match_queue=[refuse])
    mc = MasterClaw(USERS, client=fake)
    out = run(mc.find_all_matches(run(mc.interview_claws())))
    assert out["groups"] == []
    assert len(out["unmatched"]) == 12             # nobody matched


def test_why_not_capped_at_three():
    obj = valid_match_obj()
    obj["why_not"] = [{"id": "u0" + str(i), "reason": "r"} for i in range(2, 8)]
    fake = FakeClient(match_queue=[json_body(obj)])
    mc = MasterClaw(USERS, client=fake)
    out = run(mc.find_matches(run(mc.interview_claws())))
    assert len(out["why_not"]) <= 3


# ----- hard-constraint validator (SPEC 6b) ----------------------------------

def make_mc():
    return MasterClaw(USERS, client=FakeClient())


def test_validator_passes_clean_group():
    assert make_mc()._validate_group(["u01", "u04", "u10"]) == []


def test_validator_h2_no_shared_window():
    problems = make_mc()._validate_group(["u07", "u04"])
    assert any("availability" in p for p in problems)


def test_validator_h1_size_range_excluded():
    problems = make_mc()._validate_group(["u01", "u04", "u08"])   # Ethan [6,8]
    assert any("Ethan" in p for p in problems)


def test_validator_h3_duplicate():
    problems = make_mc()._validate_group(["u01", "u01", "u10"])
    assert any("duplicate" in p for p in problems)


def test_validator_h3_unknown_id():
    problems = make_mc()._validate_group(["u01", "u99", "u10"])
    assert any("unknown" in p for p in problems)


def test_validator_size_over_five():
    problems = make_mc()._validate_group(["u01", "u02", "u03", "u05", "u06", "u12"])
    assert any("larger than" in p for p in problems)


# ----- json extraction helper -----------------------------------------------

def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_with_surrounding_noise():
    assert extract_json('noise before {"a": 1} noise after') == {"a": 1}


def test_extract_json_invalid_returns_none():
    assert extract_json("no json here") is None
