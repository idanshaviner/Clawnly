"""Tests for the seed users and the closed vocabularies (SPEC 4)."""

import json

from users import USERS, HOBBY_CATEGORIES, AVAILABILITY_WINDOWS


def hobby_to_category():
    lookup = {}
    for category, hobbies in HOBBY_CATEGORIES.items():
        for hobby in hobbies:
            lookup[hobby] = category
    return lookup


def test_exactly_twelve_unique_ids():
    assert len(USERS) == 12
    ids = [u["id"] for u in USERS]
    assert len(set(ids)) == 12


def test_required_fields_present():
    fields = ["id", "name", "age", "gender", "hobbies", "personality",
              "occupation", "availability", "location", "bio", "preferred_group_size"]
    for u in USERS:
        for field in fields:
            assert field in u, f"{u.get('id')} missing {field}"


def test_ages_in_target_segment():
    for u in USERS:
        assert 24 <= u["age"] <= 35


def test_gender_is_a_mix():
    genders = set(u["gender"] for u in USERS)
    assert len(genders) >= 2


def test_personality_covers_all_three():
    kinds = set(u["personality"] for u in USERS)
    assert kinds == {"introverted", "extroverted", "mixed"}


def test_occupation_covers_all_three():
    kinds = set(u["occupation"] for u in USERS)
    assert kinds == {"student", "working professional", "freelancer"}


def test_hobbies_map_and_cover_six_categories():
    lookup = hobby_to_category()
    covered = set()
    for u in USERS:
        for hobby in u["hobbies"]:
            assert hobby in lookup, f"unmapped hobby: {hobby}"
            covered.add(lookup[hobby])
    assert covered == set(HOBBY_CATEGORIES.keys())
    assert len(covered) == 6


def test_availability_windows_valid():
    for u in USERS:
        assert len(u["availability"]) >= 1
        for window in u["availability"]:
            assert window in AVAILABILITY_WINDOWS


def test_availability_has_real_variety():
    # at least one pair shares a window, and at least one pair shares none,
    # so availability matching is genuinely exercised.
    shared_found = False
    disjoint_found = False
    for a in range(len(USERS)):
        for b in range(a + 1, len(USERS)):
            common = set(USERS[a]["availability"]) & set(USERS[b]["availability"])
            if len(common) > 0:
                shared_found = True
            else:
                disjoint_found = True
    assert shared_found and disjoint_found


def test_group_size_valid_and_varied():
    saw_range = False
    saw_no_pref = False
    saw_min_above_five = False
    for u in USERS:
        size = u["preferred_group_size"]
        if size == "no preference":
            saw_no_pref = True
            continue
        assert isinstance(size, list) and len(size) == 2
        low, high = size
        assert 2 <= low <= high <= 8
        saw_range = True
        if low > 5:
            saw_min_above_five = True
    assert saw_range and saw_no_pref
    # the C1 showcase: a user the matcher must correctly exclude via why_not
    assert saw_min_above_five


def test_bios_are_natural_strings():
    for u in USERS:
        assert isinstance(u["bio"], str)
        assert len(u["bio"]) > 30


def test_users_are_json_serializable():
    # F1: printable as formatted JSON.
    dumped = json.dumps(USERS, indent=2)
    assert json.loads(dumped) == USERS
