"""Agent-to-agent conversation: two Claws talk privately, each one
representing one real person.

A Claw is not an invented persona. It is the person's representative, and
it knows ONLY that person's dossier -- the text their own AI wrote about them
(dossier.py). About the other person it knows only what the other Claw says. It speaks ABOUT its person ("Noa tends to..."),
never AS them, and when the dossier doesn't cover something it must say "I
don't know, ask them in person" instead of inventing.

The conversation is short and fixed-length (TURNS messages, alternating,
the last two are each side's honest read of the fit). Every message is passed
to record() as it happens, so the behind-the-scenes log sees all of it.
"""

import config
from llm_io import join_text


TURNS = 6
MAX_DOSSIER_IN_PROMPT = 5000


def transcript_text(turns, names_by_id):
    lines = []
    i = 0
    while i < len(turns):
        turn = turns[i]
        lines.append(names_by_id[turn["by"]] + "'s agent: " + turn["text"])
        i += 1
    return "\n\n".join(lines)


def _turn_system(me, other, index):
    # "agent-to-agent conversation" doubles as the marker tests/conftest.py's
    # FakeClient routes this call kind on.
    name = me["name"]
    lines = [
        "You are the Clawnly agent of " + name + ". You are in a private, agent-to-agent conversation with",
        "the agent of " + other["name"] + ". Neither human is present; they only see a yes/no invitation",
        "later, if the hub decides they should meet.",
        "Your job: find out honestly whether " + name + " and " + other["name"] + " could become genuinely close",
        "friends, and represent " + name + " truthfully.",
        "",
        "Everything you know about " + name + " is the dossier below, written by the AI " + name,
        "already uses (" + me["source"] + "). You know nothing else about them, and you know nothing about",
        other["name"] + " except what their agent tells you.",
        "",
        "Rules:",
        "- Speak as " + name + "'s agent, about them in the third person (\"" + name + " tends to...\").",
        "  Never pretend to be " + name + ".",
        "- Only say what the dossier supports. If asked something it doesn't cover, say plainly that you",
        "  don't know and that it's something to ask " + name + " in person. Never invent.",
        "- Represent the real person, including struggles, needs and quirks. A match built on a",
        "  polished version fails in real life.",
        "- Skip small talk and hobby lists. Ask about what actually predicts deep friendship: values, the",
        "  chapter of life they're in, what they need from friends and what they give, how they handle",
        "  conflict or being let down, humor, rhythm, what they're missing, when and where they're free.",
        "- Respond specifically to what the other agent just said and connect it to " + name + ": a real",
        "  similarity, a real complement, or an honest mismatch. Don't flatter.",
        "- 2-4 sentences, plain prose, no lists or headers. No last names, employers or addresses.",
    ]
    if index == 0:
        lines.append("- You speak first: introduce who " + name + " really is in one sentence, then ask one sharp question.")
    elif index >= TURNS - 2:
        lines.append("- This is your LAST message. Answer anything still open, then give your honest read of the fit")
        lines.append("  from " + name + "'s side, including any doubt. Don't ask a question.")
    else:
        lines.append("- End with ONE sharp question for the other agent.")
    lines.append("")
    lines.append("DOSSIER -- " + name + ":")
    lines.append(me["dossier"][:MAX_DOSSIER_IN_PROMPT])
    return "\n".join(lines)


async def agent_turn(me, other, turns, index, client):
    names = {me["id"]: me["name"], other["id"]: other["name"]}
    so_far = "(nothing yet -- you speak first)"
    if len(turns) > 0:
        so_far = transcript_text(turns, names)
    message = await client.messages.create(
        model=config.MODEL_AGENT_TURN,
        max_tokens=400,
        system=_turn_system(me, other, index),
        messages=[{"role": "user", "content": "Conversation so far:\n\n" + so_far + "\n\nWrite only your next message."}],
    )
    return join_text(message).strip()


async def converse(a, b, client=None, record=None, ref=None):
    # a and b are people: {"id", "name", "source", "dossier"}. Returns the turns
    # [{"by": id, "text": str}, ...]. record(actor, kind, text, ref) is called
    # for every message as it happens.
    if client is None:
        client = config.get_client()
    turns = []
    index = 0
    while index < TURNS:
        me = a
        other = b
        if index % 2 == 1:
            me = b
            other = a
        text = await agent_turn(me, other, turns, index, client)
        turns.append({"by": me["id"], "text": text})
        if record is not None:
            record("agent", "message", me["name"] + "'s agent: " + text, ref)
        index += 1
    return turns
