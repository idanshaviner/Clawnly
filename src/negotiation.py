"""Real multi-agent negotiation between the Master Claw and the group.

This is the genuine version (not a single summarizing call). Each round:
  1. the Master Claw PROPOSES a joint activity (and a short pitch),
  2. every real Claw REACTS in character to the pitch,
  3. the Master Claw ASSESSES the reactions -- on board, or revise?
It loops until the group agrees or `max_rounds` is hit, and returns the full
transcript so you can watch (or replay) the whole exchange.
"""

import asyncio

import config
from llm_io import join_text, extract_json


def _planner_prompt():
    lines = [
        "You are the Master Claw, facilitating a small matched group toward ONE joint activity",
        "that EVERY member is genuinely enthusiastic about. Ground the plan in their real hobbies,",
        "availability, and what they said they want -- do not invent interests they don't have.",
        "",
        "Find genuine COMMON GROUND. A good plan is one nobody has to be talked into -- not one that",
        "thrills some members while another just tolerates it. If their specific hobbies don't all",
        "overlap, don't force one person's hobby on the others; fall back to a simple shared setting",
        "(a relaxed dinner, coffee, a walk, a low-key game everyone can enjoy) where the real point is",
        "the conversation they all said they want. Match the group's shared energy (calm vs lively).",
        "",
        "Return ONLY a JSON object, no markdown fences, nothing before or after:",
        '{ "activity": "one specific joint activity", "pitch": "1-2 warm sentences pitching it to the group" }',
    ]
    return "\n".join(lines)


def _assess_prompt():
    lines = [
        "You are the Master Claw. You proposed a plan and the group reacted. Decide whether the",
        "group is genuinely ON BOARD, or whether real hesitation/conflict means you should revise.",
        "Be honest -- polite-but-unconvinced is NOT on board.",
        "",
        "Return ONLY a JSON object, no markdown fences, nothing before or after:",
        '{ "agreed": true, "concern": "if not agreed, the specific thing to fix next round" }',
    ]
    return "\n".join(lines)


def _group_payload(claws, interviews):
    parts = ["The matched group:\n"]
    i = 0
    while i < len(claws):
        u = claws[i].user
        record = interviews.get(u["id"], {})
        block = [
            "{} ({}): hobbies {}; free {}".format(
                u["name"], u["personality"], ", ".join(u["hobbies"]), ", ".join(u["availability"])),
            "  wants: {}".format(record.get("q1", "")),
            "",
        ]
        parts.append("\n".join(block))
        i += 1
    return "\n".join(parts)


def _reactions_text(reactions):
    parts = []
    i = 0
    while i < len(reactions):
        parts.append("- {}: {}".format(reactions[i]["name"], reactions[i]["text"]))
        i += 1
    return "\n".join(parts)


async def _master_call(client, system, payload):
    # a Master-Claw reasoning call (Sonnet). JSON only, parsed in code.
    message = await client.messages.create(
        model=config.MODEL_CLAW,
        max_tokens=600,
        temperature=config.TEMP_POPUP,
        system=system,
        messages=[{"role": "user", "content": payload}],
    )
    return extract_json(join_text(message))


async def _propose(client, claws, interviews, feedback):
    payload = _group_payload(claws, interviews)
    if len(feedback) > 0:
        payload = payload + "\nLast plan didn't land. The specific concern was: " + feedback \
            + "\nKeep whatever the group already liked and change ONLY what's needed to win over the" \
            + " person who hesitated. Do NOT swing to a totally different activity that now loses" \
            + " someone else -- aim for the shared middle ground everyone can be happy with."
    result = await _master_call(client, _planner_prompt(), payload)
    if result is None:
        result = {"activity": "a casual hangout", "pitch": "Let's just grab a coffee and see how it goes."}
    return result


async def _assess(client, activity, reactions):
    payload = "Proposed plan: " + activity + "\n\nThe group's reactions:\n" + _reactions_text(reactions)
    result = await _master_call(client, _assess_prompt(), payload)
    if result is None:
        # one retry with a firmer nudge before giving up.
        result = await _master_call(client, _assess_prompt(),
                                    payload + "\n\nReturn ONLY the JSON object, nothing else.")
    if result is None:
        result = {"agreed": True, "concern": ""}   # last resort: end gracefully, don't loop
    return result


async def negotiate(claws, interviews, client=None, max_rounds=3, on_event=None):
    # client is injectable for tests (zero API calls); defaults to the real one.
    # on_event(entry), if given, is called for each transcript entry as it happens
    # (so the UI can stream the negotiation live).
    if client is None:
        client = config.get_client()

    transcript = []

    def record(entry):
        transcript.append(entry)
        if on_event is not None:
            on_event(entry)

    proposal = await _propose(client, claws, interviews, "")
    activity = proposal.get("activity", "")
    pitch = proposal.get("pitch", activity)
    record({"type": "propose", "round": 1, "activity": activity, "pitch": pitch})

    round_no = 1
    agreed = False
    concern = ""
    while round_no <= max_rounds:
        # every real Claw reacts to the pitch, concurrently (gather fan-out, D6).
        tasks = [claws[i].react(pitch) for i in range(len(claws))]
        texts = await asyncio.gather(*tasks)

        reactions = []
        i = 0
        while i < len(claws):
            name = claws[i].user["name"]
            reactions.append({"name": name, "text": texts[i]})
            record({"type": "reaction", "round": round_no, "name": name, "text": texts[i]})
            i += 1

        verdict = await _assess(client, activity, reactions)
        agreed = verdict.get("agreed", True)
        concern = verdict.get("concern", "")
        record({"type": "assess", "round": round_no, "agreed": agreed, "concern": concern})

        if agreed:
            break
        if round_no == max_rounds:
            break

        # revise: propose again, addressing the concern.
        proposal = await _propose(client, claws, interviews, concern)
        activity = proposal.get("activity", "")
        pitch = proposal.get("pitch", activity)
        round_no += 1
        record({"type": "propose", "round": round_no, "activity": activity, "pitch": pitch})

    return {
        "activity": activity,          # alias kept so the popup can build around it
        "final_activity": activity,
        "agreed": agreed,
        "concern": concern,            # the unresolved sticking point when not agreed
        "rounds": round_no,
        "transcript": transcript,
    }
