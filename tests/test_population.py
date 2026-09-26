"""Tests for population.py -- 200 emulated Black Diamond adults."""

import datetime

import catalog
import population

START = datetime.date(2026, 9, 27)


def town():
    return population.generate(200, seed=7, start=START)


def test_two_hundred_distinct_people_with_everything_a_bot_needs():
    people = town()
    assert len(people) == 200
    assert len({p["id"] for p in people}) == 200
    assert len({p["name"] for p in people}) == 200
    for p in people:
        assert p["emulated"] is True and p["age"] >= 18
        assert p["neighborhood"] == catalog.NEIGHBORHOOD and p["area"] in catalog.AREAS
        assert p["archetype"] in population.ARCHETYPES
        assert 3 <= len(p["likes"]) <= 6
        tags = [like["tag"] for like in p["likes"]]
        assert set(tags) <= set(catalog.TAGS) and not (set(tags) & set(p["dislikes"]))
        assert set(p["avoid"]) <= set(catalog.TRAITS)
        assert len(p["calendar"]) == 7 and START.isoformat() in p["calendar"]
        for parts in p["calendar"].values():
            assert set(parts) <= set(catalog.DAY_PARTS)
        assert p["name"] in p["brief"] and p["area"] in p["brief"]


def test_the_mix_follows_the_census_profile():
    people = town()
    ages = sorted(p["age"] for p in people)
    median = ages[len(ages) // 2]
    over_65 = sum(1 for a in ages if a >= 65) / len(ages)
    kids = sum(1 for p in people if p["kids_at_home"]) / len(people)
    assert 34 <= median <= 46            # adults only; the city's all-ages median is 38
    assert 0.08 <= over_65 <= 0.22       # about 14% of adults
    assert 0.25 <= kids <= 0.50          # 39% of households have kids
    assert {"student", "retiree", "commuter", "remote worker"} <= {p["archetype"] for p in people}
    assert "ethnicity" not in people[0] and "race" not in people[0]


def test_the_same_seed_gives_the_same_town():
    assert town() == town()
    assert town() != population.generate(200, seed=8, start=START)


def test_weekend_calendars_follow_the_archetype():
    saturday = (START + datetime.timedelta(days=6)).isoformat()   # 2026-10-03
    for p in town():
        usual = population.ARCHETYPES[p["archetype"]]["weekend"]
        assert set(p["calendar"][saturday]) <= set(usual)
