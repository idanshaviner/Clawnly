"""Generate the user profiles with Claude instead of hardcoding them.

`generate_users(count, theme)` invents a diverse, schema-valid cast of people.
For speed, every person is invented by its OWN call, all fired concurrently, so
a 12-person cast takes about as long as inventing one person -- not twelve times
as long. Each slot is nudged toward a different personality / occupation /
group-size / hobby lean so the set still spans the whole space. Output is
validated in code (and each slot re-tried if the model breaks the schema), so
callers always get clean data.

Run: python src/persona_gen.py        (prints a fresh cast as JSON)
"""

import asyncio
import json
import random

import config
from llm_io import join_text, extract_json
from users import HOBBY_CATEGORIES, AVAILABILITY_WINDOWS


DEFAULT_THEME = "young adults (ages 24-35) living in Washington DC"


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
        "stereotype. Give them a fresh name and a real Washington DC neighborhood.",
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
        "- age: integer 24-35.",
        "- personality: one of introverted / extroverted / mixed.",
        "- occupation: one of student / working professional / freelancer.",
        "- availability: a non-empty list from: {}.".format(", ".join(AVAILABILITY_WINDOWS)),
        "- hobbies: 2-3 items, chosen ONLY from this menu (use the exact words):",
        _hobby_menu(),
        "- preferred_group_size: either [min, max] with 2 <= min <= max <= 8, or the string \"no preference\".",
        "- location: a real Washington DC neighborhood.",
        "",
        "Return ONLY a JSON object for the single person (the fields above).",
        "Respond with the JSON object ONLY -- no markdown code fences, no text before or after it.",
    ]
    return "\n".join(lines)


def _slot_specs(count):
    # give each slot a distinct lean so the cast spans personalities, occupations,
    # group-size preferences, and all six hobby areas.
    personalities = ["introverted", "extroverted", "mixed"]
    occupations = ["student", "working professional", "freelancer"]
    sizes = ["prefers a small, intimate group (2-3)",
             "prefers a big, lively group (5-8)",
             "has no strong group-size preference"]
    cats = list(HOBBY_CATEGORIES.keys())
    specs = []
    i = 0
    while i < count:
        specs.append({
            "personality": personalities[i % len(personalities)],
            "occupation": occupations[(i + i // 3) % len(occupations)],
            "size": sizes[(i + i // 2) % len(sizes)],
            "focus": cats[i % len(cats)],
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


async def _generate_one(client, theme, spec, seed, attempts=3):
    # invent a single valid person, retrying just this slot if the schema breaks.
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


async def generate_users(count=12, theme=DEFAULT_THEME, client=None, attempts=3):
    if client is None:
        client = config.get_client()
    specs = _slot_specs(count)
    # one random seed so a re-roll feels like a different batch.
    seed = random.randint(1000, 9999)
    # invent every person concurrently -- one call each (gather fan-out only, D6).
    tasks = [_generate_one(client, theme, specs[i], seed, attempts) for i in range(count)]
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
        if not isinstance(age, int) or age < 24 or age > 35:
            problems.append("{} age {} not an int in 24-35".format(tag, age))
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
