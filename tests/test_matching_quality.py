"""Matching-quality tests + tests for the good/bad feedback report.

These exercise the matcher across many realistic scenarios and assert it does
the RIGHT thing -- a failing test here is concrete feedback that the matching
went wrong.
"""

from conftest import FakeClient, json_body, run
from master_claw import MasterClaw
from users import USERS
import eval as evalmod


def mc():
    return MasterClaw(USERS, client=FakeClient())


def match_obj(group, why_not=None):
    return {
        "group": group,
        "reason": "grounded reason",
        "scores": {"personality": 4, "availability": 4, "interests": 4, "size_fit": 4},
        "why_not": why_not or [],
    }


# ---------------------------------------------------------------------------
# The validator's judgment should match human expectations
# ---------------------------------------------------------------------------

def test_a_genuinely_compatible_trio_is_accepted():
    # Maya, Marcus, Omar: all free weekday_evening, sizes all admit 3.
    assert mc()._validate_group(["u01", "u04", "u10"]) == []


def test_oversized_preference_is_rejected_in_a_small_group():
    # Ethan wants [6,8]; he can't be hard-satisfied in a group of 3.
    problems = mc()._validate_group(["u01", "u04", "u08"])
    assert any("Ethan" in p for p in problems)


def test_no_shared_time_is_rejected():
    # Aisha (weekends only) + Marcus (weekday evenings only) can never meet.
    problems = mc()._validate_group(["u07", "u04"])
    assert any("availability" in p for p in problems)


def test_group_larger_than_five_is_rejected():
    problems = mc()._validate_group(["u01", "u02", "u03", "u05", "u06", "u12"])
    assert any("larger than" in p for p in problems)


def test_a_pair_is_rejected_when_no_one_forces_a_small_group():
    # default target is 3-5; a size-2 group needs a member whose max < 3.
    problems = mc()._validate_group(["u01", "u10"])
    assert any("under 3" in p for p in problems)


def test_duplicate_member_is_rejected():
    assert any("duplicate" in p for p in mc()._validate_group(["u01", "u01", "u10"]))


def test_unknown_member_is_rejected():
    assert any("unknown" in p for p in mc()._validate_group(["u01", "u99", "u10"]))


def test_no_preference_member_imposes_no_size_limit():
    # Grace (u11) is "no preference"; a clean trio with her stays valid if times overlap.
    # Grace: weekday_daytime/weekend_evening. Pair with two who share one of those.
    # u06 James: weekday_daytime/weekend_evening; u03 Priya: weekday_daytime/weekend_daytime.
    # All three share weekday_daytime -> valid, and "no preference" adds no size problem.
    problems = mc()._validate_group(["u11", "u06", "u03"])
    assert problems == []


# ---------------------------------------------------------------------------
# The matcher must never SHIP a rule-breaking group
# ---------------------------------------------------------------------------

def interviews(ids=None):
    by_id = {u["id"]: u for u in USERS}
    if ids is None:
        ids = [u["id"] for u in USERS]
    out = {}
    for i in ids:
        out[i] = {"profile": by_id[i], "q1": "x", "q2": "y"}
    return out


def test_matcher_repairs_a_size_violation():
    bad = json_body(match_obj(["u01", "u04", "u08"]))     # Ethan too-big-pref
    good = json_body(match_obj(["u01", "u04", "u10"]))
    m = MasterClaw(USERS, client=FakeClient(match_queue=[bad, good]))
    out = run(m.find_matches(interviews()))
    assert m._validate_group(out["group"]) == []          # whatever ships is clean


def test_matcher_repairs_an_availability_violation():
    bad = json_body(match_obj(["u07", "u04"]))            # no shared window
    good = json_body(match_obj(["u01", "u04", "u10"]))
    m = MasterClaw(USERS, client=FakeClient(match_queue=[bad, good]))
    out = run(m.find_matches(interviews()))
    assert m._validate_group(out["group"]) == []


def test_matcher_refuses_rather_than_shipping_a_bad_group():
    bad = json_body(match_obj(["u07", "u04"]))
    m = MasterClaw(USERS, client=FakeClient(match_queue=[bad, bad, bad, bad]))
    out = run(m.find_matches(interviews()))
    assert out["group"] == []                             # gave up safely


def test_matcher_caps_why_not_so_output_stays_legible():
    obj = match_obj(["u01", "u04", "u10"], why_not=[{"id": "u0" + str(i), "reason": "r"} for i in range(2, 9)])
    m = MasterClaw(USERS, client=FakeClient(match_queue=[json_body(obj)]))
    out = run(m.find_matches(interviews()))
    assert len(out["why_not"]) <= 3


# ---------------------------------------------------------------------------
# The good/bad feedback report classifies correctly
# ---------------------------------------------------------------------------

def record(kind="normal", matched=None, violations=None, baseline_violations=None, refused=False, why_not=None):
    matched = matched if matched is not None else ["u01", "u04", "u10"]
    return {
        "pool_id": "p", "kind": kind, "matched": (matched if not refused else []),
        "size": (0 if refused else len(matched)), "reason": "r", "scores": {},
        "why_not": why_not or [], "violations": violations or [],
        "baseline": ["u02", "u05", "u06"], "baseline_violations": baseline_violations or [],
        "refused": refused,
        # impossible pools have no valid group; normal pools do.
        "solvable": kind != "impossible",
    }


def test_feedback_praises_clean_and_correct_runs():
    recs = [
        record(),
        record(kind="impossible", refused=True),
    ]
    notes = " ".join(evalmod.feedback(recs))
    assert "[GOOD] Never broke a hard rule" in notes
    assert "Correctly refused" in notes


def test_feedback_flags_a_hard_violation():
    recs = [record(violations=["someone's size range excludes a group of 3"])]
    notes = " ".join(evalmod.feedback(recs))
    assert "[BAD] Broke hard rules" in notes


def test_feedback_flags_forcing_an_impossible_pool():
    recs = [record(kind="impossible", refused=False)]   # should have refused, didn't
    notes = " ".join(evalmod.feedback(recs))
    assert "[BAD] Forced a group" in notes


def test_feedback_flags_over_refusal_on_solvable_pools():
    recs = [record(kind="normal", refused=True)]        # refused a solvable pool
    notes = " ".join(evalmod.feedback(recs))
    assert "[CONCERN] Refused on" in notes


def test_feedback_credits_beating_the_random_baseline():
    recs = [record(baseline_violations=["random group shares no time"])]
    notes = " ".join(evalmod.feedback(recs))
    assert "random grouping broke rules" in notes
