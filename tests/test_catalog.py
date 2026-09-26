"""Tests for catalog.py -- the neighborhood activity menu."""

import catalog


def test_every_activity_is_well_formed():
    ids = set()
    for a in catalog.ACTIVITIES:
        assert a["id"] not in ids
        ids.add(a["id"])
        assert a["neighborhood"] in catalog.NEIGHBORHOODS
        assert set(a["tags"]) <= set(catalog.TAGS) and len(a["tags"]) > 0
        assert set(a["traits"]) <= set(catalog.TRAITS)
        assert set(a["parts"]) <= set(catalog.DAY_PARTS) and len(a["parts"]) > 0
        assert set(a["days"]) <= set(range(7)) and len(a["days"]) > 0
        assert "min_size" not in a and "max_size" not in a   # one size rule for every activity
        assert a["cost"] in ("free", "low", "mid")


def test_every_neighborhood_has_things_to_do():
    for n in catalog.NEIGHBORHOODS:
        assert any(a["neighborhood"] == n for a in catalog.ACTIVITIES)


def test_reachable_by_travel_mode():
    assert catalog.reachable("College Park", "College Park", "walk")
    assert not catalog.reachable("College Park", "Hyattsville", "walk")
    assert catalog.reachable("College Park", "Hyattsville", "bike")
    assert not catalog.reachable("College Park", "Columbia Heights", "bike")
    assert catalog.reachable("College Park", "Columbia Heights", "car")


def test_groups_are_small_on_purpose():
    assert (catalog.GROUP_MIN, catalog.GROUP_MAX) == (3, 5)


def test_get():
    assert catalog.get("hy-kayak")["name"].startswith("Kayaking")
    assert catalog.get("nope") is None
