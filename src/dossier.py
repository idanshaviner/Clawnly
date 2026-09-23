"""Bring your agent: turn what a person's own AI knows about them into the
dossier their Clawnly Claw carries.

A person copies IMPORT_PROMPT into the AI that already knows them (ChatGPT,
Claude, Muse, Instinct, ...) and pastes the answer back. That pasted text IS
the dossier -- the only thing their Claw ever knows about them (agent_talk.py).
build_card() makes a short structured card from it, used by the hub to decide
who should talk (orchestrator.py). Nothing here invents: anything the text
doesn't say goes in "unknowns", and the card also scores whether the text
reads like the real person or their public, social-media self.
"""

import config
from llm_io import join_text, extract_json


SOURCES = ["ChatGPT", "Claude", "Muse", "Instinct", "Other"]

# shorter than this can't represent a person -- ask for the full answer instead
MIN_DOSSIER_CHARS = 400
MAX_DOSSIER_CHARS = 8000

# each paragraph is one line so the copied prompt reads cleanly in any chat box
IMPORT_PROMPT = "\n".join([
    "I'm joining Clawnly. An AI agent will represent me in private conversations with other people's "
    "agents, to find me a few genuinely close friends. I only step in at the end to say yes or no to "
    "meeting someone.",
    "",
    "From what you actually know about me from our conversations (not how I'd present myself on social "
    "media or LinkedIn), write an honest portrait of me. Include the unflattering parts: a match made "
    "with a polished version of me fails in real life. If you don't know something, write \"unknown\" "
    "instead of guessing.",
    "",
    "Cover, in plain prose:",
    "1. What I care about most, and what I won't compromise on.",
    "2. The chapter of life I'm in right now: what's hard, what's changing.",
    "3. How I actually am with friends: what I give, what I need, how I handle conflict or being let down.",
    "4. What drains me socially and what fills me up.",
    "5. My sense of humor (an example if you have one).",
    "6. The kind of friendship I'm missing.",
    "7. Who would be a bad fit for me.",
    "8. When I'm usually free, and roughly which neighborhood or city I'm in.",
    "",
    "Write it in the second person (\"You...\"), 250-450 words. Leave out last names, employer names, "
    "addresses, health or financial details, and other people's names.",
])

TEXT_FIELDS = ["essence", "chapter", "gives", "needs", "energy", "humor", "missing", "free", "area"]
LIST_FIELDS = ["values", "not_a_fit", "unknowns"]


def _card_system_prompt():
    # "profile card their Clawnly agent will carry" doubles as the marker
    # tests/conftest.py's FakeClient routes this call kind on.
    lines = [
        "Someone joining Clawnly (a friendship service where AI agents talk to each other on people's",
        "behalf) pasted what their own AI assistant wrote about them.",
        "Turn it into the profile card their Clawnly agent will carry.",
        "Use ONLY what the text says. Anything it doesn't cover goes in \"unknowns\" -- never guess.",
        "Keep their real voice and keep the unflattering parts; do not polish.",
        "Also judge whether this reads like the REAL person (struggles, needs, specifics) or a public,",
        "social-media version (achievements, buzzwords, no vulnerability).",
        "",
        "Return ONLY this JSON object, no text around it:",
        '{"essence": "one sentence: who they really are", "chapter": "the chapter of life they\'re in",',
        ' "values": ["3-5 short items"], "gives": "what they give friends", "needs": "what they need from friends",',
        ' "energy": "what drains vs fills them", "humor": "their humor", "missing": "the friendship they\'re missing",',
        ' "not_a_fit": ["who would be a bad fit"], "free": "when they\'re free", "area": "neighborhood/city or unknown",',
        ' "unknowns": ["important things the text doesn\'t say"],',
        ' "real_vs_public": {"score": 1-5, "note": "one sentence; 5 = clearly the real person"}}',
    ]
    return "\n".join(lines)


def check_text(text):
    # returns an error message for the person, or None when the text is usable.
    if not isinstance(text, str) or len(text.strip()) < MIN_DOSSIER_CHARS:
        return "That's too short to represent you. Paste your AI's full answer (a few paragraphs)."
    return None


def clean_card(raw):
    # keep only well-formed fields; a missing field reads as "unknown", never
    # as something made up.
    if not isinstance(raw, dict):
        raw = {}
    card = {}
    i = 0
    while i < len(TEXT_FIELDS):
        key = TEXT_FIELDS[i]
        value = raw.get(key)
        if isinstance(value, str) and len(value.strip()) > 0:
            card[key] = value.strip()
        else:
            card[key] = "unknown"
        i += 1
    i = 0
    while i < len(LIST_FIELDS):
        key = LIST_FIELDS[i]
        items = []
        value = raw.get(key)
        if isinstance(value, list):
            j = 0
            while j < len(value):
                if isinstance(value[j], str) and len(value[j].strip()) > 0:
                    items.append(value[j].strip())
                j += 1
        card[key] = items
        i += 1
    card["real_vs_public"] = None
    rvp = raw.get("real_vs_public")
    if isinstance(rvp, dict):
        score = rvp.get("score")
        if isinstance(score, int) and not isinstance(score, bool) and 1 <= score <= 5:
            card["real_vs_public"] = {"score": score, "note": str(rvp.get("note", ""))}
    return card


async def build_card(source, text, client=None):
    # raises ValueError for unusable text (the caller shows the message).
    problem = check_text(text)
    if problem is not None:
        raise ValueError(problem)
    if client is None:
        client = config.get_client()
    message = await client.messages.create(
        model=config.MODEL_DOSSIER,
        max_tokens=900,
        system=_card_system_prompt(),
        messages=[{"role": "user", "content": "Their AI (" + source + ") wrote:\n\n" + text.strip()[:MAX_DOSSIER_CHARS]}],
    )
    return clean_card(extract_json(join_text(message)))


def card_text(card):
    # the card as plain lines, for the hub's pairing prompt.
    if card is None:
        return "(no card yet)"
    lines = [
        "Essence: " + card["essence"],
        "Chapter of life: " + card["chapter"],
        "Values: " + _list_text(card["values"]),
        "Gives to friends: " + card["gives"],
        "Needs from friends: " + card["needs"],
        "Social energy: " + card["energy"],
        "Humor: " + card["humor"],
        "Friendship they're missing: " + card["missing"],
        "Bad fit: " + _list_text(card["not_a_fit"]),
        "Free: " + card["free"],
        "Area: " + card["area"],
        "Unknowns: " + _list_text(card["unknowns"]),
    ]
    return "\n".join(lines)


def _list_text(items):
    if len(items) == 0:
        return "unknown"
    return "; ".join(items)
