"""The popup generator: turns a matched group into a concrete meetup card.

Given the matched users and the matcher's reason, it produces one specific Seattle
meetup -- venue, day/time, activity -- with a personal one-line reason that is
consistent with the matcher's reasoning and the group's stated availability
(SPEC F4).
"""

import config
from llm_io import join_text, extract_json


def _popup_system_prompt():
    lines = [
        "You plan 2-3 real-world meetup OPTIONS for a small group, so they can pick.",
        "Use the people's hobbies, neighborhoods, and availability. Base the location on the",
        "group's OWN stated neighborhoods below -- never assume any specific city or region.",
        "Give the options some variety (different vibes or venues), and put the best one first.",
        "",
        "Rules for EVERY option:",
        "- Pick a SPECIFIC, real-sounding venue or park near the group's own stated",
        "  neighborhoods (not a generic 'a cafe', and not a made-up place in a city they",
        "  never mentioned).",
        "- The day and time must fit the group's shared availability windows.",
        "- The reason must be ONE sentence, personal and specific to these people,",
        "  and consistent with the matcher's reason below (do not contradict it).",
        "",
        "Return ONLY a JSON object, exactly:",
        "{",
        '  "options": [',
        '    {"event_name": "...", "activity": "...", "location": "specific Seattle venue or park",',
        '     "time": "day of week + time of day", "reason": "one specific, personal sentence"}',
        "  ]",
        "}",
        "Include 2 or 3 options. Respond with the JSON object ONLY -- no code fences, nothing else.",
    ]
    return "\n".join(lines)


def _fallback_option(match_reason):
    return {"event_name": "Meetup", "activity": "casual hangout", "location": "a spot near the group",
            "time": "this weekend", "reason": match_reason}


def _shared_windows(matched_users):
    # the availability windows EVERY member shares (intersection).
    if len(matched_users) == 0:
        return []
    common = set(matched_users[0]["availability"])
    i = 1
    while i < len(matched_users):
        common = common & set(matched_users[i]["availability"])
        i += 1
    return list(common)


def _popup_payload(matched_users, match_reason, suggested_activity):
    parts = ["The matcher grouped these people. Matcher's reason: " + match_reason]
    if suggested_activity is not None and len(suggested_activity) > 0:
        parts.append("The group already agreed on this activity -- build the meetup around it: "
                     + suggested_activity)
    shared = _shared_windows(matched_users)
    if len(shared) > 0:
        parts.append("The group is ONLY free during these windows: " + ", ".join(shared)
                     + ". The day + time of the meetup MUST fall in one of them.")
    parts.append("")
    parts.append("Group:")
    i = 0
    while i < len(matched_users):
        u = matched_users[i]
        hobbies = ", ".join(u["hobbies"])
        availability = ", ".join(u["availability"])
        line = "- {} ({}): hobbies {}; free {}".format(u["name"], u["location"], hobbies, availability)
        parts.append(line)
        i += 1
    return "\n".join(parts)


def _names(matched_users):
    names = []
    i = 0
    while i < len(matched_users):
        names.append(matched_users[i]["name"])
        i += 1
    return names


async def generate_popup(matched_users, match_reason, suggested_activity=None, client=None):
    # client is injectable for tests (SPEC section 9); defaults to the real one.
    # suggested_activity (from the negotiation phase) anchors the meetup if given.
    if client is None:
        client = config.get_client()

    message = await client.messages.create(
        model=config.MODEL_POPUP,
        max_tokens=800,
        temperature=config.TEMP_POPUP,
        system=_popup_system_prompt(),
        messages=[
            {"role": "user", "content": _popup_payload(matched_users, match_reason, suggested_activity)},
        ],
    )
    parsed = extract_json(join_text(message))

    # normalize to a list of 2-3 options; fall back safely on a bad reply.
    options = None
    if parsed is not None and isinstance(parsed.get("options"), list) and len(parsed["options"]) > 0:
        options = parsed["options"][:3]
    if options is None:
        options = [_fallback_option(match_reason)]

    first = options[0]
    # keep the first option flattened at the top level for back-compat, plus the
    # full options list and the real attendee names.
    return {
        "options": options,
        "matched_users": _names(matched_users),
        "event_name": first.get("event_name", ""),
        "activity": first.get("activity", ""),
        "location": first.get("location", ""),
        "time": first.get("time", ""),
        "reason": first.get("reason", ""),
    }
