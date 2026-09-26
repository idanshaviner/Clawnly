"""Tests for population.py -- the 100 emulated neighbors."""

import datetime

import catalog
import population

START = datetime.date(2026, 9, 27)


def test_hundred_distinct_people_with_everything_a_bot_needs():
    people = population.generate(100, seed=7, start=START)
    assert len(people) == 100
    assert len({p["id"] for p in people}) == 100
    assert len({p["name"] for p in people}) == 100
    for p in people:
        assert p["emulated"] is True
        assert p["neighborhood"] == catalog.NEIGHBORHOOD
        assert 3 <= len(p["likes"]) <= 6
        tags = [like["tag"] for like in p["likes"]]
        assert set(tags) <= set(catalog.TAGS) and not (set(tags) & set(p["dislikes"]))
        assert set(p["avoid"]) <= set(catalog.TRAITS)
        assert len(p["calendar"]) == 7 and START.isoformat() in p["calendar"]
        for parts in p["calendar"].values():
            assert set(parts) <= set(catalog.DAY_PARTS)
        assert p["name"] in p["brief"] and p["neighborhood"] in p["brief"]


def test_the_same_seed_gives_the_same_people():
    a = population.generate(100, seed=7, start=START)
    b = population.generate(100, seed=7, start=START)
    c = population.generate(100, seed=8, start=START)
    assert a == b
    assert a != c


def test_weekend_calendars_follow_the_archetype():
    people = population.generate(100, seed=7, start=START)
    saturday = (START + datetime.timedelta(days=6)).isoformat()   # 2026-10-03
    for p in people:
        usual = population.ARCHETYPES[p["archetype"]]["weekend"]
        assert set(p["calendar"][saturday]) <= set(usual)


def test_more_than_the_name_list_still_gives_unique_names():
    people = population.generate(120, seed=1, start=START)
    assert len({p["name"] for p in people}) == 120
