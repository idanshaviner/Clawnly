"""Tests for match_eval.py -- the offline evaluation of code-proposed activity groups."""

import datetime

import catalog
import match_eval
import population

SATURDAY = datetime.date(2026, 10, 31)


def town():
    return population.generate(200, seed=7, start=datetime.date(2026, 10, 28))


def test_hard_violations_reads_every_rule():
    p = {"calendar": {SATURDAY.isoformat(): ["evening"]}, "budget": "free", "dislikes": ["craft_beer"],
         "avoid": ["loud_places"]}
    found = match_eval.hard_violations(p, catalog.get("kraken"), SATURDAY, "evening")
    assert "over budget" in found and "dislikes craft_beer" in found and "avoids loud_places" in found
    assert "busy" in match_eval.hard_violations(p, catalog.get("kraken"), SATURDAY, "afternoon")


def test_a_day_of_records_explains_each_group_and_breaks_no_rule():
    records, summary, unplaced = match_eval.day_records(town(), SATURDAY, "t")
    assert len(records) == summary["groups"] > 0
    placed = sum(r["size"] for r in records)
    assert placed == summary["placed"] == 200 - len(unplaced)
    for r in records:
        assert r["explanation_recorded"].startswith(r["activity_name"])
        assert 2 <= r["size"] <= 5
        assert all(m["hard_violations"] == [] for m in r["members"])
        assert r["review_status"] in ("rule-clean", "needs human review")


def test_cohesion_is_the_mean_pairwise_overlap_of_likes():
    a = {"likes": [{"tag": "hiking", "weight": 3}, {"tag": "coffee", "weight": 1}]}
    b = {"likes": [{"tag": "hiking", "weight": 2}]}
    assert match_eval.group_cohesion([a, b]) == 0.5
    assert match_eval.group_cohesion([a]) == 0.0


def test_groups_do_not_depend_on_input_order():
    assert match_eval.order_stability(trials=1)["day_runs_that_differed"] == 0


def test_the_live_matchmakers_code_check_lets_no_bad_plan_through():
    assert match_eval.fuzz_check_plan(trials=40)["rule_break_count"] == 0
