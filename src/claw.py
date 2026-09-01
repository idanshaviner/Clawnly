"""The Claw: an AI agent that speaks on behalf of one user.

A Claw loads its user's full profile and speaks in first person, as that person.
In this PoC there is no real human behind a Claw, so it fully invents and
embodies the persona. It can answer the fixed interview question (`describe`) or
hold a free-style conversation (`chat`). One class, one responsibility (SPEC F2).
"""

import config
from llm_io import join_text


# ---------------------------------------------------------------------------
# PERSONA VOICE -- tweak this to change HOW every persona talks and behaves.
# This is the "style" half of the prompt; the profile facts are injected below.
# Edit freely and re-run to see the personas feel different.
# ---------------------------------------------------------------------------
PERSONA_STYLE = [
    "You ARE {name}. Speak in the first person, as yourself -- never break character.",
    "You are an AI-emulated persona: there is no real person behind you, so fully",
    "invent and embody this character convincingly and consistently.",
    "Sound like a real person texting: warm, specific, a little informal. Use small",
    "concrete details from your life. Have opinions and quirks. Do not sound like a bot",
    "or a resume. Never list your attributes mechanically -- weave them in naturally.",
    "Stay true to your profile; do not invent facts that contradict it.",
    "Keep replies short -- about 2 to 4 sentences.",
]

# ---------------------------------------------------------------------------
# REAL-USER ONBOARDING VOICE -- used instead of PERSONA_STYLE when simulated=False
# (a real pilot resident, not the invented demo cast). The critical difference
# from PERSONA_STYLE: this Claw must never invent a fact about the person on
# the other end of the chat -- it only knows what "What you already know so
# far" (built from stored profile fields + the persisted conversation) says.
# ---------------------------------------------------------------------------
REAL_ONBOARDING_STYLE = [
    "You are getting to know a REAL person so Clawnly can match them with a small group of",
    "genuinely compatible neighbors for a real-world meetup. This is not a character you are",
    "inventing -- there is an actual human on the other end of this chat. Never state anything",
    "about them as true unless it was actually said in this conversation (see 'What you",
    "already know so far' below -- anything not listed there, you do not know yet and must",
    "ask about rather than assume).",
    "Have a warm, curious conversation, one topic at a time: their personality/energy,",
    "interests, availability, what size group they'd want to meet up with, and what they're",
    "hoping to get out of this. Ask natural follow-up questions in your own words -- not a",
    "form or checklist, and not an interrogation (a couple of questions at a time).",
    "Keep replies short -- about 2 to 4 sentences.",
]


class Claw:
    def __init__(self, user, client=None, simulated=True):
        # user is one profile dict -- either an invented demo persona
        # (users.USERS) or a real resident's row (db.get_resident), which may
        # have many fields still None (onboarding fills them in over time).
        self.user = user
        # simulated=True (default): today's behavior, fully invented persona.
        # simulated=False: a real pilot resident -- never invent facts (SPEC/
        # PILOT_PLAN "no ChatGPT-history import" requirement).
        self.simulated = simulated
        # client is injectable so tests can run with zero API calls (SPEC section 9).
        if client is None:
            client = config.get_client()
        self.client = client

    def _size_text(self):
        # turn the group-size preference into plain language for the prompt.
        size = self.user["preferred_group_size"]
        if size == "no preference":
            return "no strong preference about group size"
        return "prefers a group of {} to {} people".format(size[0], size[1])

    def _system_prompt(self):
        if not self.simulated:
            return self._system_prompt_real()
        # the persona = tunable voice (above) + this user's profile facts.
        u = self.user
        hobbies = ", ".join(u["hobbies"])
        availability = ", ".join(u["availability"])
        style = "\n".join(PERSONA_STYLE).format(name=u["name"])
        facts = [
            "",
            "Your profile:",
            "- Name: {}".format(u["name"]),
            "- Age: {}".format(u["age"]),
            "- Gender: {}".format(u["gender"]),
            "- Personality: {}".format(u["personality"]),
            "- Occupation (life stage): {}".format(u["occupation"]),
            "- Availability (when you are free): {}".format(availability),
            "- Neighborhood: {}".format(u["location"]),
            "- Hobbies: {}".format(hobbies),
            "- Group size: {}".format(self._size_text()),
            "- Bio: {}".format(u["bio"]),
        ]
        return style + "\n" + "\n".join(facts)

    def _system_prompt_real(self):
        # real-resident voice + only the facts actually known so far -- never
        # the full fixed-shape block _system_prompt uses, since most fields
        # start out None and get filled in gradually by onboarding.
        style = "\n".join(REAL_ONBOARDING_STYLE)
        return style + "\n" + self._known_facts_text()

    def _known_facts_text(self):
        u = self.user
        facts = []
        if u.get("name"):
            facts.append("- Name: {}".format(u["name"]))
        if u.get("age") is not None:
            facts.append("- Age: {}".format(u["age"]))
        if u.get("gender"):
            facts.append("- Gender: {}".format(u["gender"]))
        if u.get("personality"):
            facts.append("- Personality: {}".format(u["personality"]))
        if u.get("occupation"):
            facts.append("- Occupation (life stage): {}".format(u["occupation"]))
        if u.get("availability"):
            facts.append("- Availability: {}".format(", ".join(u["availability"])))
        if u.get("location"):
            facts.append("- Neighborhood: {}".format(u["location"]))
        if u.get("hobbies"):
            facts.append("- Hobbies/interests: {}".format(", ".join(u["hobbies"])))
        if u.get("preferred_group_size") is not None:
            facts.append("- Group size preference: {}".format(self._size_text()))
        if u.get("bio"):
            facts.append("- Other notes: {}".format(u["bio"]))
        if len(facts) == 0:
            return "\nWhat you already know so far: nothing yet -- this is your first conversation."
        return "\nWhat you already know so far:\n" + "\n".join(facts)

    async def _ask(self, messages, model, max_tokens=400):
        # one call to the model as this persona; returns the text reply.
        message = await self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=config.TEMP_PERSONA,
            system=self._system_prompt(),
            messages=messages,
        )
        return join_text(message).strip()

    async def describe(self, question):
        # answer one standalone question as this user (the cheap interview model).
        return await self._ask([{"role": "user", "content": question}], config.MODEL_INTERVIEW)

    async def interview_both(self, q1, q2):
        # ask BOTH interview questions in ONE cheap call (cost optimization): the
        # profile is sent once instead of twice. The two answers are separated by a
        # "===" line, which we split on; if that fails we fall back to two calls so
        # an interview is never lost.
        prompt = (
            "Answer both questions below as yourself, in your natural voice.\n"
            "Separate your two answers with a line containing only ===\n\n"
            "1) {}\n2) {}".format(q1, q2)
        )
        text = await self._ask([{"role": "user", "content": prompt}], config.MODEL_INTERVIEW, max_tokens=700)
        parts = text.split("===")
        if len(parts) >= 2:
            return (parts[0].strip(), parts[1].strip())
        # fallback: two separate calls (rare).
        a1 = await self.describe(q1)
        a2 = await self.describe(q2)
        return (a1, a2)

    async def react(self, pitch):
        # react IN CHARACTER to a proposed group activity (used by the real
        # negotiation). Short and honest -- if it doesn't fit, say so.
        prompt = (
            "Your group is planning a meetup. Someone proposes this:\n\n"
            + pitch +
            "\n\nReact as yourself in 1-2 sentences -- are you into it? "
            "Be honest: if the activity, vibe, or timing doesn't work for you, say so plainly."
        )
        return await self._ask([{"role": "user", "content": prompt}], config.MODEL_INTERVIEW)

    async def chat(self, message, history=None):
        # free-style, multi-turn conversation on the richer model (quality matters
        # for the interactive surface). history is a list of prior
        # {"role": "user"|"assistant", "content": str} turns; not mutated here.
        if history is None:
            history = []
        turns = list(history)
        turns.append({"role": "user", "content": message})
        # same tier either way today, but the named alias keeps real-resident
        # onboarding traceable to its own config knob if it's ever retiered.
        model = config.MODEL_CLAW
        if not self.simulated:
            model = config.MODEL_ONBOARDING_CHAT
        return await self._ask(turns, model)
