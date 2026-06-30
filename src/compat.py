"""Pairwise compatibility across the cast -- code only, no API calls.

A quick, deterministic read of who would click with whom, for the compatibility
map in the app. Score scale: 0 = can never meet (no shared free time);
1 = can meet but little in common; up to 4 = strong fit.
"""

from users import HOBBY_CATEGORIES


def _hobby_lookup():
    lookup = {}
    cats = list(HOBBY_CATEGORIES.keys())
    i = 0
    while i < len(cats):
        hobbies = HOBBY_CATEGORIES[cats[i]]
        j = 0
        while j < len(hobbies):
            lookup[hobbies[j]] = cats[i]
            j += 1
        i += 1
    return lookup


def _categories(user, lookup):
    cats = set()
    hobbies = user["hobbies"]
    i = 0
    while i < len(hobbies):
        if hobbies[i] in lookup:
            cats.add(lookup[hobbies[i]])
        i += 1
    return cats


def _personality_fit(a, b):
    # mixed gels with anyone; introvert + extrovert complement each other.
    if a == "mixed" or b == "mixed":
        return True
    return a != b


def pair_score(a, b, lookup):
    common = set(a["availability"]) & set(b["availability"])
    if len(common) == 0:
        return 0                       # no shared time -> they can never meet
    score = 1
    if len(_categories(a, lookup) & _categories(b, lookup)) > 0:
        score += 1                     # share an interest area
    if _personality_fit(a["personality"], b["personality"]):
        score += 1                     # complementary energy
    if len(common) >= 2:
        score += 1                     # lots of overlapping free time
    if score > 4:
        score = 4
    return score


def compatibility_matrix(users):
    # a names + ids + NxN matrix; diagonal is None (self).
    lookup = _hobby_lookup()
    names = []
    ids = []
    i = 0
    while i < len(users):
        names.append(users[i]["name"])
        ids.append(users[i]["id"])
        i += 1

    matrix = []
    i = 0
    while i < len(users):
        row = []
        j = 0
        while j < len(users):
            if i == j:
                row.append(None)
            else:
                row.append(pair_score(users[i], users[j], lookup))
            j += 1
        matrix.append(row)
        i += 1
    return {"ids": ids, "names": names, "matrix": matrix}
