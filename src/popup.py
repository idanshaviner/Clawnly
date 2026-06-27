"""The popup generator: turns a matched group into a concrete meetup card.

Given the matched users and the matcher's reason, it produces one specific DC
meetup -- venue, day/time, activity -- with a personal one-line reason that is
consistent with the matcher's reasoning and the group's stated availability
(SPEC F4).
"""

import config
from llm_io import join_text, extract_json


def _popup_system_prompt():
    lines = [
        "You plan a single real-world meetup for a small group in Washington DC.",
        "Use the people's hobbies, neighborhoods, and availability to pick something they'd all enjoy.",
        "",
        "Rules:",
        "- Pick a SPECIFIC, real-sounding DC venue or park (not a generic 'a cafe').",
        "- The day and time must fit the group's shared availability windows.",
        "- The reason must be ONE sentence, personal and specific to these people,",
        "  and consistent with the matcher's reason below (do not contradict it).",
        "",
        "Return ONLY a JSON object, exactly:",
        "{",
        '  "event_name": "...",',
        '  "activity": "...",',
        '  "location": "specific DC venue or park",',
        '  "time": "day of week + time of day",',
        '  "matched_users": ["Name", "Name"],',
        '  "reason": "one specific, personal sentence"',
        "}",
        "Respond with the JSON object ONLY -- no markdown code fences, no text before or after it.",
    ]
    return "\n".join(lines)


def _popup_payload(matched_users, match_reason, suggested_activity):
    parts = ["The matcher grouped these people. Matcher's reason: " + match_reason]
    if suggested_activity is not None and len(suggested_activity) > 0:
        parts.append("The group already agreed on this activity -- build the meetup around it: "
                     + suggested_activity)
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
    popup = extract_json(join_text(message))

    # safe fallback so the pipeline never crashes on a bad reply.
    if popup is None:
        popup = {
            "event_name": "Meetup",
            "activity": "casual hangout",
            "location": "a spot in DC",
            "time": "this weekend",
            "matched_users": _names(matched_users),
            "reason": match_reason,
        }

    # always anchor the attendee list to the real matched names.
    popup["matched_users"] = _names(matched_users)
    return popup
