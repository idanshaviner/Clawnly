"""Generate the user profiles with Claude instead of hardcoding them.

`generate_users(count, theme)` invents a diverse, schema-valid cast of people.
For speed, every person is invented by its OWN call, all fired concurrently, so
a 12-person cast takes about as long as inventing one person -- not twelve times
as long. Callers can pass `count` (default 12, max 100) and a `theme` string.
Each slot is nudged toward a different personality / occupation /
group-size / hobby lean so the set still spans the whole space. Output is
validated in code (and each slot re-tried if the model breaks the schema), so
callers always get clean data.

`build_demo_cast(count, theme)` is the offline counterpart: a schema-valid
cast with no API calls, used by the demo console so a 100-person Black Diamond
run is playable without Anthropic.

Run: python src/persona_gen.py        (prints a fresh cast as JSON)
"""

import asyncio
import json
import random

import config
from llm_io import join_text, extract_json
from users import HOBBY_CATEGORIES, AVAILABILITY_WINDOWS


DEFAULT_THEME = (
    "neighbors in Black Diamond, Washington (ages 24-40, platonic friendship "
    "/ activity partners -- not dating)"
)
DEFAULT_COUNT = 12
MAX_GEN_COUNT = 100
MIN_AGE = 24
MAX_AGE = 40

# how many person-generation calls may be in flight at once. Fanning out a small
# cast at once is fast but can trip API rate limits on lower tiers; a modest cap
# keeps a 100-person roll moving without bursting unbounded.
GEN_CONCURRENCY = 8


def _hobby_menu():
    lines = []
    cats = list(HOBBY_CATEGORIES.keys())
    i = 0
    while i < len(cats):
        lines.append("  {}: {}".format(cats[i], ", ".join(HOBBY_CATEGORIES[cats[i]])))
        i += 1
    return "\n".join(lines)


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


def _gen_one_system_prompt(theme, spec):
    # invent ONE believable person, leaning the way this slot asks so the whole
    # cast spans the space. The phrase "generate simulated user" stays so the
    # test fake can route the call.
    lines = [
        "You generate simulated user profiles for a friendship-matching app.",
        "Theme: {}.".format(theme),
        "",
        "Invent exactly ONE distinct, believable person -- a real individual, not a",
        "stereotype. Give them a fresh name and a real neighborhood consistent with the theme above.",
        "Write the bio in first person, 2-3 natural sentences that sound human.",
        "",
        "Lean this person the following way (stay believable, don't force it):",
        "- personality: {}".format(spec["personality"]),
        "- occupation: {}".format(spec["occupation"]),
        "- group size: {}".format(spec["size"]),
        "- center their hobbies on the '{}' area of life".format(spec["focus"]),
        "",
        "The person MUST use exactly these fields:",
        "  id, name, age, gender, hobbies, personality, occupation,",
        "  availability, location, bio, preferred_group_size",
        "",
        "Rules:",
        "- age: integer {}-{}.".format(MIN_AGE, MAX_AGE),
        "- personality: one of introverted / extroverted / mixed.",
        "- occupation: one of student / working professional / freelancer.",
        "- availability: a non-empty list from: {}.".format(", ".join(AVAILABILITY_WINDOWS)),
        "- hobbies: 4-6 items, chosen ONLY from this menu (use the exact words). Pick a genuinely",
        "  varied mix -- don't just take the first few that fit the lean above:",
        _hobby_menu(),
        "- preferred_group_size: either [min, max] with 2 <= min <= max <= 8, or the string \"no preference\".",
        "- location: a real neighborhood consistent with the theme above (not necessarily Seattle --",
        "  follow whatever place the theme names).",
        "",
        "Return ONLY a JSON object for the single person (the fields above).",
        "Respond with the JSON object ONLY -- no markdown code fences, no text before or after it.",
    ]
    return "\n".join(lines)


def _cycled_shuffle(options, count):
    # repeat 'options' enough times to reach count, re-shuffling each full
    # cycle independently -- guarantees every option appears roughly equally
    # often (so the cast still spans the whole space) while the ORDER (who
    # gets which lean) is genuinely random on every call, not a fixed pattern.
    out = []
    while len(out) < count:
        cycle = list(options)
        random.shuffle(cycle)
        out.extend(cycle)
    return out[:count]


def _slot_specs(count):
    # give each slot a distinct, randomized lean so the cast spans personalities,
    # occupations, group-size preferences, and all six hobby areas -- but which
    # slot gets which lean is reshuffled every call, so re-rolling the cast
    # produces a genuinely different mix of people each time, not the same
    # index-0-is-always-introverted pattern.
    personalities = ["introverted", "extroverted", "mixed"]
    occupations = ["student", "working professional", "freelancer"]
    sizes = ["prefers a small, intimate group (2-3)",
             "prefers a big, lively group (5-8)",
             "has no strong group-size preference"]
    cats = list(HOBBY_CATEGORIES.keys())
    p_leans = _cycled_shuffle(personalities, count)
    o_leans = _cycled_shuffle(occupations, count)
    s_leans = _cycled_shuffle(sizes, count)
    c_leans = _cycled_shuffle(cats, count)
    specs = []
    i = 0
    while i < count:
        specs.append({
            "personality": p_leans[i],
            "occupation": o_leans[i],
            "size": s_leans[i],
            "focus": c_leans[i],
        })
        i += 1
    return specs


def _coerce_one(obj):
    # accept a bare person object, or a {"user": {...}} / {"users": [...]} wrapper.
    if not isinstance(obj, dict):
        return None
    if "name" in obj and "hobbies" in obj:
        return obj
    inner = obj.get("user")
    if isinstance(inner, dict):
        return inner
    users = obj.get("users")
    if isinstance(users, list) and len(users) > 0 and isinstance(users[0], dict):
        return users[0]
    return None


async def _generate_one(client, theme, spec, seed, sem, attempts=3):
    # invent a single valid person, retrying just this slot if the schema breaks.
    # `sem` bounds how many of these run at once (rate-limit safety).
    async with sem:
        return await _generate_one_inner(client, theme, spec, seed, attempts)


async def _generate_one_inner(client, theme, spec, seed, attempts):
    system = _gen_one_system_prompt(theme, spec)
    feedback = ""
    n = 0
    while n < attempts:
        payload = ("Invent ONE brand-new person now (random batch #{}). Make them feel "
                   "distinct from any typical person.").format(seed)
        if len(feedback) > 0:
            payload = payload + "\nYour last attempt had problems: " + feedback + "\nFix them."
        try:
            message = await client.messages.create(
                model=config.MODEL_CLAW,
                max_tokens=700,
                temperature=config.TEMP_PERSONA,
                system=system,
                messages=[{"role": "user", "content": payload}],
            )
        except Exception:
            return None
        person = _coerce_one(extract_json(join_text(message)))
        if person is not None:
            # validate the single person (a temp id satisfies the id checks).
            problems = validate_users([dict(person, id="u01")])
            if len(problems) == 0:
                return person
            feedback = "; ".join(problems)
        else:
            feedback = "Output was not a valid JSON person object."
        n += 1
    return None


def clamp_count(count):
    # keep generation bounded: default 12, never above 100, never below 1.
    if count is None:
        return DEFAULT_COUNT
    try:
        n = int(count)
    except (TypeError, ValueError):
        return DEFAULT_COUNT
    if n < 1:
        return 1
    if n > MAX_GEN_COUNT:
        return MAX_GEN_COUNT
    return n


def clamp_theme(theme):
    if theme is None:
        return DEFAULT_THEME
    if not isinstance(theme, str):
        return DEFAULT_THEME
    stripped = theme.strip()
    if len(stripped) == 0:
        return DEFAULT_THEME
    return stripped


async def generate_users(count=12, theme=DEFAULT_THEME, client=None, attempts=3):
    count = clamp_count(count)
    theme = clamp_theme(theme)
    if client is None:
        client = config.get_client()
    specs = _slot_specs(count)
    # one random seed so a re-roll feels like a different batch.
    seed = random.randint(1000, 9999)
    # invent every person concurrently, but at most GEN_CONCURRENCY at a time so a
    # re-roll stays fast without bursting past API rate limits (gather fan-out, D6).
    sem = asyncio.Semaphore(GEN_CONCURRENCY)
    tasks = [_generate_one(client, theme, specs[i], seed, sem, attempts) for i in range(count)]
    people = await asyncio.gather(*tasks)
    # keep the ones that came back valid, in slot order, with clean sequential ids.
    users = []
    i = 0
    while i < len(people):
        if people[i] is not None:
            users.append(people[i])
        i += 1
    return _reid(users)


def validate_users(users):
    # check generated profiles against the schema + vocabularies (SPEC section 4).
    problems = []
    lookup = _hobby_lookup()
    valid_personality = ["introverted", "extroverted", "mixed"]
    valid_occupation = ["student", "working professional", "freelancer"]
    required = ["id", "name", "age", "gender", "hobbies", "personality",
                "occupation", "availability", "location", "bio", "preferred_group_size"]

    i = 0
    while i < len(users):
        u = users[i]
        tag = "user[{}]".format(i)

        j = 0
        while j < len(required):
            if required[j] not in u:
                problems.append("{} missing field {}".format(tag, required[j]))
            j += 1
        if len(problems) > 0 and required[0] not in u:
            i += 1
            continue

        age = u.get("age")
        if not isinstance(age, int) or age < MIN_AGE or age > MAX_AGE:
            problems.append("{} age {} not an int in {}-{}".format(tag, age, MIN_AGE, MAX_AGE))
        if u.get("personality") not in valid_personality:
            problems.append("{} bad personality {}".format(tag, u.get("personality")))
        if u.get("occupation") not in valid_occupation:
            problems.append("{} bad occupation {}".format(tag, u.get("occupation")))

        hobbies = u.get("hobbies", [])
        if len(hobbies) < 2:
            problems.append("{} needs at least 2 hobbies".format(tag))
        k = 0
        while k < len(hobbies):
            if hobbies[k] not in lookup:
                problems.append("{} unknown hobby '{}'".format(tag, hobbies[k]))
            k += 1

        availability = u.get("availability", [])
        if len(availability) < 1:
            problems.append("{} needs at least 1 availability window".format(tag))
        k = 0
        while k < len(availability):
            if availability[k] not in AVAILABILITY_WINDOWS:
                problems.append("{} bad availability '{}'".format(tag, availability[k]))
            k += 1

        size = u.get("preferred_group_size")
        if size != "no preference":
            ok = isinstance(size, list) and len(size) == 2
            if not ok:
                problems.append("{} bad preferred_group_size {}".format(tag, size))
            else:
                low = size[0]
                high = size[1]
                if not (2 <= low <= high <= 8):
                    problems.append("{} size range {} outside 2-8".format(tag, size))
        i += 1

    ids = []
    i = 0
    while i < len(users):
        ids.append(users[i].get("id"))
        i += 1
    if len(set(ids)) != len(ids):
        problems.append("ids are not unique")

    return problems


def _reid(users):
    # overwrite ids sequentially so uniqueness is guaranteed regardless of model.
    out = []
    i = 0
    while i < len(users):
        u = dict(users[i])
        u["id"] = "u{:02d}".format(i + 1)
        out.append(u)
        i += 1
    return out


def _nudge_system_prompt():
    lines = [
        "You revise a person's profile based on a short instruction (e.g. 'make her more",
        "adventurous'). Keep them a believable, consistent individual -- change only what the",
        "instruction implies, and keep the bio in first person.",
        "",
        "Use the SAME vocabulary:",
        "- personality: introverted / extroverted / mixed",
        "- occupation: student / working professional / freelancer",
        "- availability: any of {}".format(", ".join(AVAILABILITY_WINDOWS)),
        "- hobbies: only from this menu (exact words):",
        _hobby_menu(),
        "- preferred_group_size: [min, max] with 2 <= min <= max <= 8, or \"no preference\"",
        "",
        "Return ONLY a JSON object with the fields that CHANGE (omit unchanged ones), e.g.",
        '{ "personality": "extroverted", "bio": "..." }. No fences, nothing else.',
    ]
    return "\n".join(lines)


async def nudge_user(user, instruction, client=None):
    # AI rewrites editable traits from a plain-English instruction; returns just
    # the changed fields (the caller validates + applies them).
    if client is None:
        client = config.get_client()
    editable = {
        "name": user["name"], "age": user["age"], "gender": user["gender"],
        "hobbies": user["hobbies"], "personality": user["personality"],
        "occupation": user["occupation"], "availability": user["availability"],
        "location": user["location"], "bio": user["bio"],
        "preferred_group_size": user["preferred_group_size"],
    }
    payload = ("Current profile:\n" + json.dumps(editable)
               + "\n\nInstruction: " + instruction + "\nReturn only the changed fields as JSON.")
    message = await client.messages.create(
        model=config.MODEL_CLAW,
        max_tokens=600,
        temperature=config.TEMP_PERSONA,
        system=_nudge_system_prompt(),
        messages=[{"role": "user", "content": payload}],
    )
    changes = extract_json(join_text(message))
    if changes is None:
        return {}
    return changes



# first names / last names / Black Diamond-area neighborhoods used only by the
# offline demo cast -- Live generation invents its own via the model.
_DEMO_FIRST = [
    "Ava", "Ben", "Cora", "Drew", "Elena", "Felix", "Gia", "Hugo", "Iris", "Jules",
    "Kai", "Lena", "Milo", "Nora", "Owen", "Priya", "Quinn", "Rosa", "Sam", "Tia",
    "Uri", "Vera", "Wes", "Xena", "Yves", "Zara", "Amir", "Bea", "Chris", "Dana",
    "Eli", "Faye", "Gabe", "Hana", "Ian", "Jade", "Kira", "Leo", "Maya", "Nate",
    "Omar", "Pia", "Reed", "Sage", "Tess", "Uma", "Vince", "Willa", "Yara", "Zoe",
]
_DEMO_LAST = [
    "Park", "Nguyen", "Shah", "Ortiz", "Kim", "Patel", "Brooks", "Chen", "Ali",
    "Diaz", "Singh", "Walsh", "Okoye", "Berg", "Sato", "Ibrahim", "Cole", "Reed",
]
_DEMO_PLACES = [
    "Ten Trails, Black Diamond",
    "Lawson Hills, Black Diamond",
    "Downtown Black Diamond",
    "Lake Sawyer, Black Diamond",
    "Morgan Creek, Black Diamond",
    "Black Diamond Ridge",
    "Palmer Coking, Black Diamond",
    "The Villages, Black Diamond",
    "Maple Valley edge near Black Diamond",
    "Enumclaw plateau near Black Diamond",
]
_DEMO_GENDERS = ["female", "male", "nonbinary"]


def _all_hobbies():
    out = []
    cats = list(HOBBY_CATEGORIES.keys())
    i = 0
    while i < len(cats):
        items = HOBBY_CATEGORIES[cats[i]]
        j = 0
        while j < len(items):
            out.append(items[j])
            j += 1
        i += 1
    return out


def _demo_hobbies(focus, seed_i):
    # 4-6 hobbies, starting from the slot's focus category so the cast still spans.
    lookup_cats = list(HOBBY_CATEGORIES.keys())
    focused = list(HOBBY_CATEGORIES.get(focus, HOBBY_CATEGORIES[lookup_cats[0]]))
    pool = _all_hobbies()
    n = 4 + (seed_i % 3)
    picked = []
    # take two from the focus category first.
    k = 0
    while k < len(focused) and len(picked) < 2:
        item = focused[(seed_i + k) % len(focused)]
        if item not in picked:
            picked.append(item)
        k += 1
    k = 0
    while k < len(pool) and len(picked) < n:
        item = pool[(seed_i * 3 + k) % len(pool)]
        if item not in picked:
            picked.append(item)
        k += 1
    return picked


def _demo_availability(seed_i):
    # 1-3 windows, rotated so the pool still has overlap AND disjoint pairs.
    n = 1 + (seed_i % 3)
    out = []
    k = 0
    while k < n:
        out.append(AVAILABILITY_WINDOWS[(seed_i + k) % len(AVAILABILITY_WINDOWS)])
        k += 1
    return out


def _demo_size(size_lean):
    if "small" in size_lean:
        return [2, 3]
    if "big" in size_lean:
        return [5, 8]
    return "no preference"


def build_demo_cast(count=12, theme=DEFAULT_THEME):
    # schema-valid people with no API calls, so Demo mode can run a 100-person
    # Black Diamond simulation end-to-end. Theme only flavors location/bio.
    count = clamp_count(count)
    theme = clamp_theme(theme)
    specs = _slot_specs(count)
    users = []
    i = 0
    while i < count:
        spec = specs[i]
        first = _DEMO_FIRST[i % len(_DEMO_FIRST)]
        last = _DEMO_LAST[(i // len(_DEMO_FIRST) + i) % len(_DEMO_LAST)]
        # suffix when the name pool wraps so 100 people stay distinct.
        cycle = i // (len(_DEMO_FIRST) * len(_DEMO_LAST))
        name = first + " " + last
        if cycle > 0:
            name = name + " " + str(cycle + 1)
        age = MIN_AGE + ((i * 3) % (MAX_AGE - MIN_AGE + 1))
        gender = _DEMO_GENDERS[i % len(_DEMO_GENDERS)]
        place = _DEMO_PLACES[i % len(_DEMO_PLACES)]
        hobbies = _demo_hobbies(spec["focus"], i)
        bio = (
            "I live around {} and I'm looking for platonic friends / activity "
            "partners -- not dating. Theme of this cast: {}. I usually fill my "
            "time with {}."
        ).format(place, theme, ", ".join(hobbies[:2]))
        users.append({
            "name": name,
            "age": age,
            "gender": gender,
            "hobbies": hobbies,
            "personality": spec["personality"],
            "occupation": spec["occupation"],
            "availability": _demo_availability(i),
            "location": place,
            "bio": bio,
            "preferred_group_size": _demo_size(spec["size"]),
        })
        i += 1
    return _reid(users)


async def main(client=None):
    users = await generate_users(client=client)
    print(json.dumps(users, indent=2))
    problems = validate_users(users)
    if len(problems) == 0:
        print("\n# valid: {} users pass the schema".format(len(users)))
    else:
        print("\n# warning: {} problems remain: {}".format(len(problems), problems))
    return users


if __name__ == "__main__":
    asyncio.run(main())
