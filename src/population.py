"""100 emulated people: the neighbors the orchestrator plans for in simulation.

No AI calls -- a seeded generator, so the same seed always gives the same
people and a simulation can be re-run exactly. Every person is fictional.

A person is what they'd tell their own bot:
  likes     -- activity tags (catalog.TAGS) with a weight 1-3 (3 = love it)
  dislikes  -- activity tags they never want to do
  avoid     -- things they avoid (catalog.TRAITS: crowds, early mornings, ...)
  budget, travel -- free/low/any, walk/bike/car
  calendar  -- the next 7 days: date -> the day parts they're free
  brief     -- the same thing in plain words, as they'd say it to their bot
"""

import datetime
import random

import catalog


FIRST_NAMES = [
    "Aaliyah", "Aarav", "Abebe", "Adaeze", "Aiden", "Aisha", "Alejandro", "Amara", "Amir", "Ana",
    "Andre", "Anika", "Ari", "Ayesha", "Bea", "Ben", "Bilal", "Bo", "Camila", "Carlos",
    "Chen", "Chloe", "Dana", "Daniel", "Dara", "Deja", "Devon", "Diego", "Elif", "Eli",
    "Emeka", "Emma", "Esi", "Ethan", "Fatima", "Felix", "Gabriel", "Grace", "Hana", "Hiro",
    "Ibrahim", "Imani", "Inés", "Isaac", "Ivy", "Jae", "Jamal", "Jasmine", "Javier", "Jin",
    "Jordan", "Kai", "Kavya", "Keisha", "Kenji", "Kofi", "Lara", "Layla", "Leo", "Lina",
    "Luca", "Luis", "Mahmoud", "Maya", "Mei", "Miguel", "Mina", "Nadia", "Naomi", "Nia",
    "Nikhil", "Noah", "Nora", "Omar", "Oren", "Owen", "Paloma", "Priya", "Quinn", "Rafael",
    "Rania", "Ravi", "Rosa", "Ruth", "Sam", "Sana", "Santiago", "Sara", "Selin", "Shira",
    "Sofia", "Tariq", "Tess", "Theo", "Tomas", "Uma", "Valentina", "Wei", "Yara", "Zoe",
]

# when each kind of life is usually free: weekday parts, weekend parts
ARCHETYPES = {
    "student": {"weekday": ["afternoon", "evening"], "weekend": ["morning", "afternoon", "evening"]},
    "office": {"weekday": ["evening"], "weekend": ["morning", "afternoon", "evening"]},
    "shift worker": {"weekday": ["morning", "afternoon"], "weekend": ["evening"]},
    "parent": {"weekday": ["evening"], "weekend": ["morning", "afternoon"]},
    "remote worker": {"weekday": ["morning", "evening"], "weekend": ["morning", "afternoon"]},
}
ARCHETYPE_NAMES = ["student", "student", "office", "office", "shift worker", "parent", "remote worker"]

BUDGETS = ["free", "low", "any"]
TRAVEL = ["walk", "bike", "bike", "car"]

LOVE = {3: "love", 2: "really like", 1: "am up for"}


def _pick(rng, items, count):
    # `count` distinct items, in random order
    pool = list(items)
    rng.shuffle(pool)
    return pool[:count]


def _calendar(rng, archetype, start, days):
    # free day parts for each of the next `days` days, with some of them taken
    pattern = ARCHETYPES[archetype]
    out = {}
    d = 0
    while d < days:
        day = start + datetime.timedelta(days=d)
        usual = pattern["weekday"]
        if day.weekday() >= 5:
            usual = pattern["weekend"]
        free = []
        i = 0
        while i < len(usual):
            # life happens: roughly a third of usual free time is taken
            if rng.random() > 0.35:
                free.append(usual[i])
            i += 1
        out[day.isoformat()] = free
        d += 1
    return out


def _words(tag):
    return tag.replace("_", " ")


def _brief(p):
    # what they'd tell their bot, in plain words
    loves = []
    i = 0
    while i < len(p["likes"]):
        like = p["likes"][i]
        loves.append("I " + LOVE[like["weight"]] + " " + _words(like["tag"]))
        i += 1
    parts = [p["name"] + " here. " + "; ".join(loves) + "."]
    if len(p["dislikes"]) > 0:
        nos = []
        j = 0
        while j < len(p["dislikes"]):
            nos.append(_words(p["dislikes"][j]))
            j += 1
        parts.append("Not into " + ", ".join(nos) + ".")
    if len(p["avoid"]) > 0:
        avoid = []
        k = 0
        while k < len(p["avoid"]):
            avoid.append(_words(p["avoid"][k]))
            k += 1
        parts.append("I avoid " + ", ".join(avoid) + ".")
    parts.append("I'm a " + p["archetype"] + " in " + p["neighborhood"] + ", I get around by " + p["travel"] +
                 ", and my budget is " + p["budget"] + ".")
    return " ".join(parts)


def generate(count=100, seed=7, start=None, days=7):
    # the same seed always gives the same neighborhood
    rng = random.Random(seed)
    if start is None:
        start = datetime.date.today()
    names = list(FIRST_NAMES)
    rng.shuffle(names)
    people = []
    n = 0
    while n < count:
        name = names[n % len(names)]
        if n >= len(names):
            name = name + " " + str(n // len(names) + 1)
        archetype = ARCHETYPE_NAMES[rng.randrange(len(ARCHETYPE_NAMES))]
        like_tags = _pick(rng, catalog.TAGS, rng.randint(3, 6))
        likes = []
        i = 0
        while i < len(like_tags):
            likes.append({"tag": like_tags[i], "weight": rng.choice([1, 2, 2, 3, 3])})
            i += 1
        others = []
        j = 0
        while j < len(catalog.TAGS):
            if catalog.TAGS[j] not in like_tags:
                others.append(catalog.TAGS[j])
            j += 1
        person = {
            "id": "e" + str(n + 1).zfill(3),
            "name": name,
            "age": rng.randint(18, 45),
            "neighborhood": catalog.NEIGHBORHOODS[rng.choice([0, 0, 0, 1, 1, 2, 3])],
            "archetype": archetype,
            "likes": likes,
            "dislikes": _pick(rng, others, rng.randint(1, 3)),
            "avoid": _pick(rng, catalog.TRAITS, rng.randint(0, 2)),
            "budget": rng.choice(BUDGETS),
            "travel": rng.choice(TRAVEL),
            "calendar": _calendar(rng, archetype, start, days),
            "emulated": True,
        }
        person["brief"] = _brief(person)
        people.append(person)
        n += 1
    return people
