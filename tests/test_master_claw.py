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


def weak_match_obj(group=None):
    # a valid group, but only "workable" scores (average 3.0, under the 3.5 bar).
    obj = valid_match_obj(group)
    obj["scores"] = {"personality": 3, "availability": 3, "interests": 3, "size_fit": 3}
    return obj


def test_find_matches_declines_a_weak_but_valid_group():
    # passes every hard constraint, but the connection is only lukewarm -> not shipped.
    weak = json_body(weak_match_obj())
    fake = FakeClient(match_queue=[weak, weak, weak])
    mc = MasterClaw(USERS, client=fake)
    out = run(mc.find_matches(run(mc.interview_claws())))
    assert out["group"] == []
    assert "strong" in out["reason"].lower()


def test_find_matches_upgrades_from_weak_to_strong():
    # a weak first pick is sent back; a strong one on retry ships.
    fake = FakeClient(match_queue=[json_body(weak_match_obj()), json_body(valid_match_obj())])
    mc = MasterClaw(USERS, client=fake)
    out = run(mc.find_matches(run(mc.interview_claws())))
    assert out["group"] == ["u01", "u04", "u10"]
    assert len([k for k in fake.kinds() if k == "match"]) == 2


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


# ----- computed compatibility hints (grounded matching signal) --------------

def test_shared_items_finds_overlap_in_order_no_dupes():
    from master_claw import _shared_items
    assert _shared_items(["a", "b", "c"], ["c", "a"]) == ["a", "c"]
    assert _shared_items(["a", "a", "b"], ["a"]) == ["a"]   # no duplicate entries
    assert _shared_items(["a"], ["b"]) == []


def test_compatibility_hints_lists_exact_shared_hobbies():
    mc = MasterClaw(USERS, client=FakeClient())
    # Marcus (u04) and Omar (u10) both list chess and podcasts.
    hints = mc._compatibility_hints(["u04", "u10"])
    assert "Marcus & Omar" in hints
    assert "chess" in hints and "podcasts" in hints


def test_compatibility_hints_only_flags_strong_availability_overlap():
    mc = MasterClaw(USERS, client=FakeClient())
    # Maya (u01) and Sofia (u05) share 2 windows -> flagged as strong.
    hints = mc._compatibility_hints(["u01", "u05"])
    assert "Maya & Sofia" in hints and "2 shared windows" in hints
    # Maya (u01) and Daniel (u02) share only 1 window -> not flagged (noise).
    hints_one = mc._compatibility_hints(["u01", "u02"])
    assert "Maya & Daniel" not in hints_one


def test_compatibility_hints_empty_when_no_overlap_in_pool():
    mc = MasterClaw(USERS, client=FakeClient())
    # a lone candidate has no pairs to compute at all.
    assert mc._compatibility_hints(["u01"]) == ""


def test_compatibility_hints_are_sent_in_the_match_payload():
    fake = FakeClient(match_queue=[json_body(valid_match_obj())])
    mc = MasterClaw(USERS, client=fake)
    run(mc.find_matches(run(mc.interview_claws())))
    payload = [kw for kind, kw in fake.calls if kind == "match"][0]["messages"][0]["content"]
    assert "COMPUTED COMPATIBILITY SIGNALS" in payload
    assert "Marcus & Omar" in payload   # a real shared-hobby pair among the 12


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


def test_find_matches_repairs_missing_scores():
    # empty scores must not silently bypass the quality gate -- it should be
    # treated as a malformed reply and repaired, same as a hard-constraint miss.
    broken = valid_match_obj()
    broken["scores"] = {}
    fake = FakeClient(match_queue=[json_body(broken), json_body(valid_match_obj())])
    mc = MasterClaw(USERS, client=fake)
    out = run(mc.find_matches(run(mc.interview_claws())))
    assert out["group"] == ["u01", "u04", "u10"]
    assert len([k for k in fake.kinds() if k == "match"]) == 2


def test_find_matches_repairs_out_of_range_score():
    broken = valid_match_obj()
    broken["scores"] = {"personality": 9, "availability": 4, "interests": 4, "size_fit": 5}
    fake = FakeClient(match_queue=[json_body(broken), json_body(valid_match_obj())])
    mc = MasterClaw(USERS, client=fake)
    out = run(mc.find_matches(run(mc.interview_claws())))
    assert out["group"] == ["u01", "u04", "u10"]
    assert len([k for k in fake.kinds() if k == "match"]) == 2


def test_find_matches_repairs_invented_why_not_id():
    # a why_not entry citing someone who doesn't exist is an invented entity
    # (SPEC 6c) and must be repaired, not shipped.
    broken = valid_match_obj()
    broken["why_not"] = [{"id": "u99", "reason": "made up"}]
    fake = FakeClient(match_queue=[json_body(broken), json_body(valid_match_obj())])
    mc = MasterClaw(USERS, client=fake)
    out = run(mc.find_matches(run(mc.interview_claws())))
    assert out["group"] == ["u01", "u04", "u10"]
    assert len([k for k in fake.kinds() if k == "match"]) == 2


def test_find_matches_repairs_invented_why_not_id_on_empty_group():
    broken = {"group": [], "reason": "no viable group", "scores": {},
              "why_not": [{"id": "u99", "reason": "made up"}]}
    fine = {"group": [], "reason": "no viable group", "scores": {}, "why_not": []}
    fake = FakeClient(match_queue=[json_body(broken), json_body(fine)])
    mc = MasterClaw(USERS, client=fake)
    out = run(mc.find_matches(run(mc.interview_claws())))
    assert out["group"] == []
    assert len([k for k in fake.kinds() if k == "match"]) == 2


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


def test_score_validator_passes_clean_scores():
    scores = {"personality": 3, "availability": 4, "interests": 4, "size_fit": 5}
    assert make_mc()._validate_scores(scores) == []


def test_score_validator_flags_missing_dimension():
    scores = {"personality": 3, "availability": 4, "interests": 4}   # size_fit missing
    problems = make_mc()._validate_scores(scores)
    assert any("size_fit" in p for p in problems)


def test_score_validator_flags_non_integer_and_out_of_range():
    scores = {"personality": "high", "availability": 4, "interests": 4, "size_fit": 9}
    problems = make_mc()._validate_scores(scores)
    assert any("personality" in p for p in problems)
    assert any("size_fit" in p for p in problems)


def test_score_validator_flags_non_dict():
    assert make_mc()._validate_scores([]) != []


def test_why_not_validator_passes_known_ids():
    why_not = [{"id": "u08", "reason": "too big"}]
    assert make_mc()._validate_why_not(why_not) == []


def test_why_not_validator_flags_unknown_id():
    why_not = [{"id": "u99", "reason": "made up"}]
    problems = make_mc()._validate_why_not(why_not)
    assert any("u99" in p for p in problems)


# ----- json extraction helper -----------------------------------------------

def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_with_surrounding_noise():
    assert extract_json('noise before {"a": 1} noise after') == {"a": 1}


def test_extract_json_invalid_returns_none():
    assert extract_json("no json here") is None
