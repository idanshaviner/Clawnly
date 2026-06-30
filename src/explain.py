"""Let the Master Claw explain its own decisions.

Given a finished run (the dict from run_pipeline), this answers free-form
questions about WHY the Master Claw matched these people, left others out, and
landed on the activity -- grounded only in what actually happened.
"""

import config
from llm_io import join_text


def _name_of(interviews, uid):
    record = interviews.get(uid)
    if record is not None and "profile" in record:
        return record["profile"]["name"]
    return uid


def context_summary(run_result):
    # a readable record of every group I formed this run.
    interviews = run_result.get("interviews", {})
    groups = run_result.get("groups", [])
    parts = []

    if len(groups) == 0:
        parts.append("I did not form any group -- no set of people satisfied all the hard constraints.")
    else:
        gi = 0
        while gi < len(groups):
            entry = groups[gi]
            match = entry.get("match", {})
            ids = match.get("group", [])
            names = []
            j = 0
            while j < len(ids):
                names.append(_name_of(interviews, ids[j]))
                j += 1
            parts.append("GROUP " + str(gi + 1) + ": " + ", ".join(names) + ".")
            parts.append("  Why: " + match.get("reason", ""))
            plan = entry.get("negotiation")
            if plan is not None:
                parts.append("  Plan: '" + plan.get("activity", "") + "' (agreed=" + str(plan.get("agreed")) + ").")
            gi += 1

    unmatched = run_result.get("unmatched", [])
    if len(unmatched) > 0:
        names = []
        j = 0
        while j < len(unmatched):
            names.append(_name_of(interviews, unmatched[j]))
            j += 1
        parts.append("Left over (no good group): " + ", ".join(names) + ".")

    return "\n".join(parts)


def _system_prompt(run_result):
    lines = [
        "You ARE the Master Claw, the matchmaker who just ran this matching.",
        "Answer the user's questions about WHY you made your choices, in the first person,",
        "honestly and grounded ONLY in the record below. Do not invent decisions you did not make.",
        "If the record doesn't cover something, say so. Keep answers short and direct.",
        "",
        "Your record of what you decided this run:",
        context_summary(run_result),
    ]
    return "\n".join(lines)


async def explain_decision(question, run_result, history=None, client=None):
    # client is injectable for tests; defaults to the real one.
    if client is None:
        client = config.get_client()
    if history is None:
        history = []
    turns = list(history)
    turns.append({"role": "user", "content": question})
    message = await client.messages.create(
        model=config.MODEL_CLAW,
        max_tokens=500,
        temperature=config.TEMP_POPUP,
        system=_system_prompt(run_result),
        messages=turns,
    )
    return join_text(message).strip()
