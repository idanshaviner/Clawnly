"""Negotiation phase: the parent agent works out a joint plan for the group.

After the Master Claw picks a compatible group, this facilitates the group
converging on real common ground and ONE joint activity everyone buys into --
plus a short in-character reaction from each person. Grounded in their real
profiles and interview answers; no fabricated interests. Feeds the popup.
"""

import config
from llm_io import join_text, extract_json


def _negotiation_system_prompt():
    lines = [
        "You are the Master Claw acting as a FACILITATOR for a small group that has",
        "just been matched. Your job: find what they genuinely have in common (or",
        "complement each other on) and broker ONE joint activity they'd all enjoy.",
        "",
        "Rules:",
        "- Ground everything in their REAL hobbies, availability, and answers below.",
        "  Do not invent shared interests that aren't there.",
        "- Find common ground that is specific (a shared hobby, a compatible vibe, a",
        "  complementary mix), not generic ('they all like fun').",
        "- Propose ONE activity that fits everyone's interests AND their shared free time.",
        "- Give each person a short, in-character reaction (1 sentence) to the plan.",
        "",
        "Return ONLY a JSON object, exactly:",
        "{",
        '  "common_ground": ["specific shared/complementary threads, grounded in their profiles"],',
        '  "activity": "one specific joint activity they would all enjoy",',
        '  "rationale": "one or two sentences on why it works for all of them",',
        '  "reactions": [{"name": "Maya", "reaction": "short in-character reaction"}]',
        "}",
        "Respond with the JSON object ONLY -- no markdown code fences, no text before or after it.",
    ]
    return "\n".join(lines)


def _payload(group_users, interviews):
    parts = ["The matched group to broker a plan for:\n"]
    i = 0
    while i < len(group_users):
        u = group_users[i]
        record = interviews.get(u["id"], {})
        q1 = record.get("q1", "")
        q2 = record.get("q2", "")
        block = [
            "{} ({}, {}):".format(u["name"], u["personality"], u["location"]),
            "  hobbies: {}".format(", ".join(u["hobbies"])),
            "  free: {}".format(", ".join(u["availability"])),
            "  wants socially: {}".format(q1),
            "  energy/availability: {}".format(q2),
            "",
        ]
        parts.append("\n".join(block))
        i += 1
    return "\n".join(parts)


async def negotiate(group_users, interviews, client=None):
    # client is injectable for tests (zero API calls); defaults to the real one.
    if client is None:
        client = config.get_client()
    message = await client.messages.create(
        model=config.MODEL_CLAW,
        max_tokens=1200,
        temperature=config.TEMP_POPUP,
        system=_negotiation_system_prompt(),
        messages=[{"role": "user", "content": _payload(group_users, interviews)}],
    )
    result = extract_json(join_text(message))

    # safe fallback so the pipeline never crashes on a bad reply.
    if result is None:
        result = {"common_ground": [], "activity": "", "rationale": "", "reactions": []}
    return result
