"""Tests for catalog.py -- the neighborhood's things to do."""

import catalog


def test_thirty_to_forty_well_formed_activities_in_one_neighborhood():
    assert 30 <= len(catalog.ACTIVITIES) <= 40
    ids = set()
    for a in catalog.ACTIVITIES:
        assert a["id"] not in ids
        ids.add(a["id"])
        assert a["neighborhood"] == catalog.NEIGHBORHOOD
        assert set(a["tags"]) <= set(catalog.TAGS) and len(a["tags"]) > 0
        assert set(a["traits"]) <= set(catalog.TRAITS)
        assert set(a["parts"]) <= set(catalog.DAY_PARTS) and len(a["parts"]) > 0
        assert set(a["days"]) <= set(range(7)) and len(a["days"]) > 0
        assert a["cost"] in ("free", "low", "mid")
        assert set(a["months"]) <= set(range(1, 13)) and len(a["months"]) > 0


def test_every_interest_has_something_to_do():
    used = set()
    for a in catalog.ACTIVITIES:
        used |= set(a["tags"])
    assert used == set(catalog.TAGS)


def test_groups_are_two_to_five():
    assert (catalog.GROUP_MIN, catalog.GROUP_MAX) == (2, 5)


def test_get():
    assert catalog.get("seahawks")["where"] == "The Vault Taphouse & Beer Garden"
    assert catalog.get("nope") is None
