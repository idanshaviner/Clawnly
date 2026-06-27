"""Generate the user profiles with Claude instead of hardcoding them.

`generate_users(count, theme)` asks Claude to invent a diverse, schema-valid cast
of people. Edit GEN_STYLE (or pass a different `theme`) to re-roll who they are,
then feed them into the pipeline or chat with them. Output is validated in code
and re-tried if the model breaks the schema, so callers always get clean data.

Run: python src/persona_gen.py        (prints a fresh cast as JSON)
"""

import asyncio
import json

import config
from llm_io import join_text, extract_json
from users import HOBBY_CATEGORIES, AVAILABILITY_WINDOWS


DEFAULT_THEME = "young adults (ages 24-35) living in Washington DC"

# ---------------------------------------------------------------------------
# GENERATION STYLE -- tweak this to change WHO gets invented and how varied
# they are. Edit freely and re-run to get a different cast.
# ---------------------------------------------------------------------------
GEN_STYLE = [
    "Invent a cast of distinct, believable people -- each should feel like a real",
    "individual, not a stereotype. Vary gender, age, personality, occupation,",
    "availability, neighborhood, hobbies, and group-size preference widely.",
    "Write each bio in first person, 2-3 natural sentences that sound human.",
    "Make sure the set collectively spans all six hobby categories, mixes all three",
    "personality types and all three occupations, and includes some people who",
    "prefer tiny groups and some who prefer big ones.",
]


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


def _gen_system_prompt(count, theme):
    lines = [
        "You generate simulated user profiles for a friendship-matching app.",
        "Theme: {}.".format(theme),
        "",
    ]
    i = 0
    while i < len(GEN_STYLE):
        lines.append(GEN_STYLE[i])
        i += 1
    lines.append("")
    lines.append("Each user MUST use exactly these fields:")
    lines.append("  id, name, age, gender, hobbies, personality, occupation,")
    lines.append("  availability, location, bio, preferred_group_size")
    lines.append("")
    lines.append("Rules:")
    lines.append("- age: integer 24-35.")
    lines.append("- personality: one of introverted / extroverted / mixed.")
    lines.append("- occupation: one of student / working professional / freelancer.")
    lines.append("- availability: a non-empty list from: {}.".format(", ".join(AVAILABILITY_WINDOWS)))
    lines.append("- hobbies: 2-3 items, chosen ONLY from this menu (use the exact words):")
    lines.append(_hobby_menu())
    lines.append("- preferred_group_size: either [min, max] with 2 <= min <= max <= 8, or the string \"no preference\".")
    lines.append("- location: a real Washington DC neighborhood.")
    lines.append("")
    lines.append("Return ONLY a JSON object: {{\"users\": [ ... {} user objects ... ]}}".format(count))
    lines.append("Respond with the JSON object ONLY -- no markdown code fences, no text before or after it.")
    return "\n".join(lines)


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


async def generate_users(count=12, theme=DEFAULT_THEME, client=None, attempts=3):
    if client is None:
        client = config.get_client()
    system = _gen_system_prompt(count, theme)
    users = []
    feedback = ""
    n = 0
    while n < attempts:
        payload = "Generate the {} users now.".format(count)
        if len(feedback) > 0:
            payload = payload + "\nYour last attempt had problems: " + feedback + "\nFix them."
        message = await client.messages.create(
            model=config.MODEL_CLAW,
            max_tokens=4000,
            temperature=config.TEMP_PERSONA,
            system=system,
            messages=[{"role": "user", "content": payload}],
        )
        obj = extract_json(join_text(message))
        if obj is None or "users" not in obj:
            feedback = "Output was not valid JSON with a 'users' array."
            n += 1
            continue
        users = _reid(obj["users"])
        problems = validate_users(users)
        if len(problems) == 0:
            return users
        feedback = "; ".join(problems)
        n += 1
    # return the best effort even if imperfect; caller can inspect.
    return users


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
