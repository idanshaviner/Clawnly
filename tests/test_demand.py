"""Tests for demand.py -- the break room: common ground found in code."""

import datetime

import catalog
import demand
import population

SUNDAY = datetime.date(2026, 9, 27)


def person(**over):
    p = {"id": "x1", "name": "X", "neighborhood": "Black Diamond, WA", "budget": "any",
         "likes": [{"tag": "kayaking", "weight": 3}], "dislikes": [], "avoid": [],
         "calendar": {SUNDAY.isoformat(): ["morning", "afternoon"]}}
    p.update(over)
    return p


def test_fit_scores_a_keen_free_person():
    kayak = catalog.get("sawyer-paddle")
    score, why_not = demand.fit(person(), kayak, SUNDAY, "afternoon")
    assert why_not is None and score == 3   # loves kayaking


def test_fit_says_why_not():
    kayak = catalog.get("sawyer-paddle")
    assert demand.fit(person(calendar={}), kayak, SUNDAY, "afternoon")[1] == "busy"
    assert demand.fit(person(budget="free"), kayak, SUNDAY, "afternoon")[1] == "over budget"
    assert demand.fit(person(dislikes=["kayaking"]), kayak, SUNDAY, "afternoon")[1] == "dislikes kayaking"
    assert demand.fit(person(avoid=["early_mornings"]), kayak, SUNDAY, "morning")[1] == "avoids early_mornings"
    assert demand.fit(person(), kayak, datetime.date(2027, 1, 10), "afternoon")[1] == "out of season"
    assert demand.fit(person(likes=[{"tag": "chess", "weight": 3}]), kayak, SUNDAY, "afternoon")[1] == "not interested"
    assert demand.fit(person(), kayak, SUNDAY, "evening")[1] == "not running then"


def test_groups_respect_sizes_and_nobody_is_booked_twice():
    people = population.generate(200, seed=7, start=SUNDAY)
    result = demand.propose_groups(people, catalog.ACTIVITIES, SUNDAY)
    assert len(result["groups"]) > 0
    seen = set()
    for g in result["groups"]:
        activity = catalog.get(g["activity"])
        assert 2 <= len(g["members"]) <= 5
        for m in g["members"]:
            assert m["id"] not in seen
            seen.add(m["id"])
            p = next(x for x in people if x["id"] == m["id"])
            assert demand.fit(p, activity, SUNDAY, g["part"])[1] is None
    assert len(seen) + len(result["unplaced"]) == 200


def test_the_break_room_is_deterministic():
    people = population.generate(200, seed=7, start=SUNDAY)
    assert demand.propose_groups(people, catalog.ACTIVITIES, SUNDAY) == demand.propose_groups(people, catalog.ACTIVITIES, SUNDAY)


def test_one_person_is_not_a_group_but_two_are():
    kayak = catalog.get("sawyer-paddle")
    one = [person(id="a")]
    result = demand.propose_groups(one, [kayak], SUNDAY)
    assert result["groups"] == [] and result["slots_that_could_run"] == 0
    two = one + [person(id="b")]
    assert len(demand.propose_groups(two, [kayak], SUNDAY)["groups"]) == 1


def test_a_crowd_is_split_into_small_groups_across_the_day():
    kayak = catalog.get("sawyer-paddle")
    eight = [person(id="p" + str(i)) for i in range(8)]   # all free morning and afternoon
    groups = demand.propose_groups(eight, [kayak], SUNDAY)["groups"]
    assert [len(g["members"]) for g in groups] == [5, 3]
    assert {g["part"] for g in groups} == {"morning", "afternoon"}
