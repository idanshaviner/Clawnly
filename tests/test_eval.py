"""Tests for the evaluation harness (SPEC 13 / PRD 6a)."""

import random

from conftest import FakeClient, json_body, run
import eval as evalmod


# ----- pure helpers ---------------------------------------------------------

def test_make_pools_has_at_least_ten_and_includes_impossible():
    pools = evalmod.make_pools()
    assert len(pools) >= 10
    kinds = [p["kind"] for p in pools]
    assert "impossible" in kinds
    assert kinds.count("impossible") >= 2


def test_impossible_pool_has_no_shared_window():
    pools = evalmod.make_pools()
    impossible = [p for p in pools if p["kind"] == "impossible"]
    for pool in impossible:
        windows = [set(u["availability"]) for u in pool["users"]]
        common = set.intersection(*windows)
        assert len(common) == 0          # genuinely impossible to share a time


def test_synthetic_interviews_shape():
    pools = evalmod.make_pools()
    users = pools[0]["users"]
    interviews = evalmod.synthetic_interviews(users)
    assert set(interviews.keys()) == set(u["id"] for u in users)
    sample = interviews[users[0]["id"]]
    assert "profile" in sample and sample["q1"] and sample["q2"]


def test_random_group_size_and_uniqueness():
    pools = evalmod.make_pools()
    users = pools[0]["users"]
    rng = random.Random(1)
    g = evalmod.random_group(users, 4, rng)
    assert len(g) == 4
    assert len(set(g)) == 4


# ----- evaluate + aggregate -------------------------------------------------

def controlled_pools():
    by_id = {u["id"]: u for u in __import__("users").USERS}
    normal = {"id": "p_norm", "kind": "normal",
              "users": [by_id["u01"], by_id["u04"], by_id["u10"]]}
    impossible = evalmod._impossible_pool("p_imp", [3, 5])
    return [normal, impossible]


def test_evaluate_records_match_and_refusal():
    valid = json_body({
        "group": ["u01", "u04", "u10"],
        "reason": "share weekday evenings",
        "scores": {"personality": 3, "availability": 4, "interests": 4, "size_fit": 5},
        "why_not": [],
    })
    refusal = json_body({"group": [], "reason": "no shared time", "scores": {}, "why_not": []})
    fake = FakeClient(match_queue=[valid, refusal])

    records = run(evalmod.evaluate(controlled_pools(), fake))
    assert len(records) == 2

    normal = records[0]
    assert normal["matched"] == ["u01", "u04", "u10"]
    assert normal["violations"] == []          # matcher group is clean
    assert normal["refused"] is False

    impossible = records[1]
    assert impossible["refused"] is True        # correctly declined


def test_aggregate_pass_bars():
    valid = json_body({
        "group": ["u01", "u04", "u10"],
        "reason": "r",
        "scores": {"personality": 3, "availability": 4, "interests": 4, "size_fit": 5},
        "why_not": [],
    })
    refusal = json_body({"group": [], "reason": "no shared time", "scores": {}, "why_not": []})
    fake = FakeClient(match_queue=[valid, refusal])

    records = run(evalmod.evaluate(controlled_pools(), fake))
    report = evalmod.aggregate(records)

    assert report["pools"] == 2
    assert report["impossible_pools"] == 1
    assert report["matcher_hard_violations"] == 0
    assert report["pass_zero_violations"] is True
    assert report["refusal_rate"] == 1.0
    assert report["pass_full_refusal"] is True


def test_is_solvable_true_for_seed_false_for_impossible():
    from users import USERS
    assert evalmod.is_solvable(USERS) is True
    imp = evalmod._impossible_pool("x", [3, 5])["users"]
    assert evalmod.is_solvable(imp) is False


def test_evaluate_records_solvability():
    scores = {"personality": 4, "availability": 4, "interests": 4, "size_fit": 4}
    valid = json_body({"group": ["u01", "u04", "u10"], "reason": "r", "scores": scores, "why_not": []})
    refusal = json_body({"group": [], "reason": "no", "scores": {}, "why_not": []})
    fake = FakeClient(match_queue=[valid, refusal])
    records = run(evalmod.evaluate(controlled_pools(), fake))
    assert records[0]["solvable"] is True          # the workable trio
    assert records[1]["solvable"] is False         # the impossible pool


def test_feedback_does_not_flag_a_correct_refusal():
    # refused on an UNSOLVABLE pool -> GOOD, not a false CONCERN (the A6 fix).
    recs = [{"kind": "normal", "matched": [], "size": 0, "reason": "r", "scores": {}, "why_not": [],
             "violations": [], "baseline_violations": [], "refused": True, "solvable": False}]
    joined = " ".join(evalmod.feedback(recs))
    assert "Correctly refused" in joined
    assert "CONCERN" not in joined


def test_feedback_flags_a_real_over_refusal():
    # refused on a SOLVABLE pool -> genuine CONCERN.
    recs = [{"kind": "normal", "matched": [], "size": 0, "reason": "r", "scores": {}, "why_not": [],
             "violations": [], "baseline_violations": [], "refused": True, "solvable": True}]
    assert any("CONCERN" in n for n in evalmod.feedback(recs))


def test_blind_review_hides_matcher_but_keeps_key():
    records = [{
        "pool_id": "p1",
        "matched": ["u01", "u04", "u10"],
        "baseline": ["u02", "u05", "u06"],
    }]
    review = evalmod.build_blind_review(records)
    assert len(review) == 1
    item = review[0]
    assert "option_A" in item and "option_B" in item
    assert "matcher" in item["answer_key"]
    pair = [item["option_A"], item["option_B"]]
    assert ["u01", "u04", "u10"] in pair        # matcher group is present, just hidden
