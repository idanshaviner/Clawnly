"""200 emulated adults of Black Diamond, WA: the neighbors the orchestrator plans for.

No AI calls -- a seeded generator, so the same seed always gives the same town
and a simulation can be re-run exactly. Every person is fictional, but the mix
follows the city's census profile (ACS 2024 5-year): median age about 38, 65+
about 10% of all residents (about 14% of adults), 39% of households with kids,
a high median household income (about $141k), and names drawn in the city's
proportions (about 67% White, 18% Asian, 8% Hispanic, 7% other). Ethnicity is
only reflected in names; it is never stored or used for matching.

Only adults have agents, so everyone here is 18+.

A person is what they'd tell their own bot:
  likes     -- activity tags (catalog.TAGS) with a weight 1-3 (3 = love it)
  dislikes  -- activity tags they never want to do
  avoid     -- things they avoid (catalog.TRAITS: crowds, early mornings, ...)
  budget    -- free / low / any
  age, area, archetype, kids_at_home -- who they are and the shape of their week
  calendar  -- the next 7 days: date -> the day parts they're free
  brief     -- the same thing in plain words, as they'd say it to their bot
"""

import datetime
import random

import catalog


# names in the city's proportions; each pool is (share, first names, last names)
NAME_POOLS = [
    (0.67, ["Emma", "Olivia", "Ava", "Sophia", "Grace", "Hannah", "Claire", "Megan", "Katie", "Lauren", "Jessica",
            "Sarah", "Amy", "Rachel", "Heather", "Karen", "Linda", "Susan", "Donna", "Carol", "Ruth", "Janet",
            "Liam", "Noah", "Jack", "Owen", "Wyatt", "Caleb", "Tyler", "Ryan", "Kyle", "Josh", "Matt", "Chris",
            "Brian", "Kevin", "Scott", "Greg", "Mark", "Steve", "Dave", "Jim", "Bill", "Tom", "Gary", "Ron",
            "Nora", "Ellie", "Molly", "Jenna", "Cody", "Dylan", "Ethan", "Logan", "Hunter", "Brooke", "Paige"],
     ["Anderson", "Miller", "Johnson", "Olsen", "Larson", "Peterson", "Nelson", "Carlson", "Walsh", "Murphy",
      "Brooks", "Hayes", "Price", "Reed", "Ward", "Foster", "Hughes", "Bennett", "Coleman", "Russell"]),
    (0.176, ["Wei", "Mei", "Jin", "Hana", "Kenji", "Yuki", "Min-jun", "Ji-woo", "Seo-yeon", "Priya", "Arjun",
             "Ananya", "Rohan", "Kavya", "Nikhil", "Linh", "Minh", "Thao", "Maria", "Jose", "Angelica", "Paolo"],
     ["Chen", "Wang", "Li", "Kim", "Park", "Lee", "Nguyen", "Tran", "Patel", "Shah", "Reddy", "Tanaka",
      "Sato", "Santos", "Reyes", "Cruz"]),
    (0.079, ["Sofia", "Camila", "Valeria", "Lucia", "Isabel", "Diego", "Mateo", "Santiago", "Luis", "Carlos",
             "Javier", "Elena", "Rosa", "Andres", "Gabriel"],
     ["Garcia", "Martinez", "Lopez", "Hernandez", "Gonzalez", "Rodriguez", "Ramirez", "Flores", "Torres", "Rivera"]),
    (0.075, ["Jordan", "Taylor", "Morgan", "Imani", "Malik", "Aaliyah", "Andre", "Keisha", "Leilani", "Kai",
             "Amara", "Tariq", "Nia", "Sam", "Quinn"],
     ["Washington", "Jackson", "Robinson", "Kealoha", "Mahoe", "Okafor", "Mensah", "Hassan", "Ali", "Brown"]),
]

# adult ages in bands with their shares: median about 38, 65+ about 14% of adults
AGE_BANDS = [((18, 24), 0.09), ((25, 34), 0.21), ((35, 44), 0.22), ((45, 54), 0.18), ((55, 64), 0.16), ((65, 85), 0.14)]

# when each kind of week is usually free: weekday parts, weekend parts
ARCHETYPES = {
    "student": {"weekday": ["afternoon", "evening"], "weekend": ["morning", "afternoon", "evening"]},
    "commuter": {"weekday": ["evening"], "weekend": ["morning", "afternoon", "evening"]},
    "shift worker": {"weekday": ["morning", "afternoon"], "weekend": ["evening"]},
    "parent at home": {"weekday": ["morning", "afternoon"], "weekend": ["morning", "afternoon"]},
    "remote worker": {"weekday": ["morning", "evening"], "weekend": ["morning", "afternoon"]},
    "retiree": {"weekday": ["morning", "afternoon"], "weekend": ["morning", "afternoon"]},
}

# interests that lean one way by stage of life; the rest are drawn from everything
LEANS = {
    "student": ["bmx", "mountain_biking", "basketball", "watch_sports", "trivia", "board_games", "tubing", "swimming"],
    "commuter": ["craft_beer", "watch_sports", "golf", "hiking", "running", "dining", "live_music", "pickleball"],
    "shift worker": ["fishing", "craft_beer", "hiking", "watch_sports", "cards", "mountain_biking", "coffee"],
    "parent at home": ["picnics", "swimming", "baseball", "farmers_market", "coffee", "dog_walks", "cooking", "baking"],
    "remote worker": ["coffee", "hiking", "kayaking", "yoga", "photography", "book_club", "craft_beer", "running"],
    "retiree": ["history", "golf", "birding", "cards", "gardening", "volunteering", "fishing", "crafts", "book_club"],
}
KID_LEANS = ["picnics", "swimming", "baseball", "farmers_market", "baking"]

# a high-income town: few people need everything free
BUDGETS = [("free", 0.15), ("low", 0.40), ("any", 0.45)]

LOVE = {3: "love", 2: "really like", 1: "am up for"}


def _weighted(rng, pairs):
    # pairs: [(value, share)]; the shares needn't sum exactly to 1
    total = 0.0
    i = 0
    while i < len(pairs):
        total += pairs[i][1]
        i += 1
    roll = rng.random() * total
    i = 0
    while i < len(pairs):
        roll -= pairs[i][1]
        if roll <= 0:
            return pairs[i][0]
        i += 1
    return pairs[len(pairs) - 1][0]


def _pick(rng, items, how_many):
    # `how_many` distinct items, in random order
    pool = list(items)
    rng.shuffle(pool)
    return pool[:how_many]


def _archetype(rng, age):
    # the shape of someone's week, from their age
    if age >= 65:
        return _weighted(rng, [("retiree", 0.85), ("remote worker", 0.10), ("commuter", 0.05)])
    if age <= 22:
        return _weighted(rng, [("student", 0.65), ("shift worker", 0.35)])
    if age <= 24:
        return _weighted(rng, [("student", 0.30), ("shift worker", 0.35), ("commuter", 0.35)])
    if age >= 58:
        return _weighted(rng, [("commuter", 0.45), ("remote worker", 0.20), ("retiree", 0.25), ("shift worker", 0.10)])
    return _weighted(rng, [("commuter", 0.45), ("remote worker", 0.22), ("shift worker", 0.18), ("parent at home", 0.15)])


def _kids_at_home(rng, age, archetype):
    # about 39% of Black Diamond households have kids, concentrated in the late 20s to 50s
    if archetype == "parent at home":
        return True
    if 27 <= age <= 54:
        return rng.random() < 0.55
    return False


def _calendar(rng, archetype, kids, start, days):
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
            # life happens: about a third of usual free time is taken, more with kids
            taken = 0.35
            if kids:
                taken = 0.5
            if rng.random() > taken:
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
    home = "I'm " + str(p["age"]) + ", a " + p["archetype"] + " in " + p["area"]
    if p["kids_at_home"]:
        home = home + ", with kids at home"
    parts.append(home + ", and my budget is " + p["budget"] + ".")
    return " ".join(parts)


def _name(rng, used):
    # a first name and last initial, drawn in the city's proportions, never repeated
    pools = []
    i = 0
    while i < len(NAME_POOLS):
        pools.append((i, NAME_POOLS[i][0]))
        i += 1
    tries = 0
    while True:
        pool = NAME_POOLS[_weighted(rng, pools)]
        name = rng.choice(pool[1]) + " " + rng.choice(pool[2])[0] + "."
        tries += 1
        if name not in used or tries > 50:
            if name in used:
                name = name + " " + str(len(used))
            used[name] = True
            return name


def generate(count=200, seed=7, start=None, days=7):
    # the same seed always gives the same town
    rng = random.Random(seed)
    if start is None:
        start = datetime.date.today()
    used = {}
    people = []
    n = 0
    while n < count:
        band = _weighted(rng, AGE_BANDS)
        age = rng.randint(band[0], band[1])
        archetype = _archetype(rng, age)
        kids = _kids_at_home(rng, age, archetype)
        # about half their interests come from their stage of life, the rest from anywhere
        how_many = rng.randint(3, 6)
        leans = list(LEANS[archetype])
        if kids:
            leans = leans + KID_LEANS
        like_tags = _pick(rng, leans, how_many // 2 + 1)
        extra = _pick(rng, catalog.TAGS, how_many)
        e = 0
        while e < len(extra) and len(like_tags) < how_many:
            if extra[e] not in like_tags:
                like_tags.append(extra[e])
            e += 1
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
            "name": _name(rng, used),
            "age": age,
            "neighborhood": catalog.NEIGHBORHOOD,
            "area": catalog.AREAS[rng.randrange(len(catalog.AREAS))],
            "archetype": archetype,
            "kids_at_home": kids,
            "likes": likes,
            "dislikes": _pick(rng, others, rng.randint(1, 3)),
            "avoid": _pick(rng, catalog.TRAITS, rng.randint(0, 2)),
            "budget": _weighted(rng, BUDGETS),
            "calendar": _calendar(rng, archetype, kids, start, days),
            "emulated": True,
        }
        person["brief"] = _brief(person)
        people.append(person)
        n += 1
    return people
