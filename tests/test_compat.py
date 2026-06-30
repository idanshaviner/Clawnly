"""Tests for the pairwise compatibility map (compat.py) -- pure code, no API."""

from compat import compatibility_matrix, pair_score, _hobby_lookup
from users import USERS


def by_id(uid):
    for u in USERS:
        if u["id"] == uid:
            return u
    raise KeyError(uid)


def test_no_shared_window_scores_zero():
    lookup = _hobby_lookup()
    # Aisha (weekend daytime only) + Marcus (weekday evenings only) can never meet.
    assert pair_score(by_id("u07"), by_id("u04"), lookup) == 0


def test_a_compatible_pair_scores_high():
    lookup = _hobby_lookup()
    # Maya + Omar: share two windows and overlapping interests.
    assert pair_score(by_id("u01"), by_id("u10"), lookup) >= 2


def test_score_is_bounded_0_to_4():
    lookup = _hobby_lookup()
    i = 0
    while i < len(USERS):
        j = 0
        while j < len(USERS):
            if i != j:
                s = pair_score(USERS[i], USERS[j], lookup)
                assert 0 <= s <= 4
            j += 1
        i += 1


def test_matrix_shape_and_diagonal():
    m = compatibility_matrix(USERS)
    assert len(m["names"]) == 12 and len(m["ids"]) == 12
    assert len(m["matrix"]) == 12
    i = 0
    while i < 12:
        assert len(m["matrix"][i]) == 12
        assert m["matrix"][i][i] is None       # no self-compatibility
        i += 1


def test_matrix_is_symmetric():
    m = compatibility_matrix(USERS)
    i = 0
    while i < 12:
        j = 0
        while j < 12:
            assert m["matrix"][i][j] == m["matrix"][j][i]
            j += 1
        i += 1
