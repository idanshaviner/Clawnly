"""Offline demo: see the whole pipeline run with ZERO API calls (no cost).

This swaps in a scripted client that fakes Claude's replies, so you can watch
the full interview -> match -> popup flow and its exact output format for free.
The AI *content* here is scripted (clearly a stand-in); the real logic,
constraints, and flow are the same code main.py uses. Run: python demo.py
"""

import asyncio
import json

from main import run_pipeline
from users import USERS


def _body(obj):
    # the full JSON the model would return (assistant-prefill is no longer used).
    return json.dumps(obj)


def _user_by_name(name):
    i = 0
    while i < len(USERS):
        if USERS[i]["name"] == name:
            return USERS[i]
        i += 1
    return None


def _parse_name(system):
    # the Claw system prompt starts with: "You ARE <name>."
    marker = "You ARE "
    start = system.find(marker)
    if start == -1:
        return None
    start = start + len(marker)
    end = system.find(".", start)
    return system[start:end]


class _Resp:
    def __init__(self, text):
        self.content = [type("Block", (), {"type": "text", "text": text})()]


class _Messages:
    def __init__(self, outer):
        self.outer = outer

    async def create(self, **kwargs):
        messages = kwargs.get("messages", [])
        system = kwargs.get("system", "")
        low = system.lower()
        # route by system marker (no assistant-prefill anymore).
        if "embody this character" not in low:
            if kwargs.get("model") == self.outer.match_model:
                return _Resp(self.outer.match_body)
            if "facilitator" in low:
                return _Resp(self.outer.negotiation_body)
            return _Resp(self.outer.popup_body)
        # otherwise a Claw persona interview.
        name = _parse_name(system)
        question = messages[-1]["content"]
        # a batched interview asks both questions; return two "===" separated answers.
        if "Separate your two answers" in question:
            a1 = self.outer.interview_answer(name, "what are you looking for socially")
            a2 = self.outer.interview_answer(name, "availability and energy")
            return _Resp(a1 + "\n===\n" + a2)
        return _Resp(self.outer.interview_answer(name, question))


class DemoClient:
    """Scripted stand-in for AsyncAnthropic -- no network, no cost."""

    def __init__(self):
        import config
        self.match_model = config.MODEL_MATCH
        self.match_body = _body({
            "group": ["u01", "u04", "u10"],
            "reason": ("Maya, Marcus and Omar all keep weekday evenings free, lean introverted, "
                       "and share a calm intellectual streak (reading, chess, writing) that "
                       "complements rather than competes."),
            "scores": {"personality": 3, "availability": 4, "interests": 4, "size_fit": 5},
            "why_not": [
                {"id": "u08", "reason": "Ethan wants a 6-8 person group -- too big for this 3-person meetup."},
                {"id": "u07", "reason": "Aisha is only free weekend daytimes, so she shares no window with this weekday-evening group."},
            ],
        })
        self.negotiation_body = _body({
            "common_ground": [
                "all three keep weekday evenings free",
                "a shared calm, intellectual streak -- chess, reading, writing",
            ],
            "activity": "a relaxed weeknight chess night over coffee",
            "rationale": "It suits their introverted energy and lands in their one shared free window.",
            "reactions": [
                {"name": "Maya", "reaction": "Honestly perfect -- a quiet evening sounds lovely."},
                {"name": "Marcus", "reaction": "Chess after the gym? Count me in."},
                {"name": "Omar", "reaction": "I'm always up for a good match and a real conversation."},
            ],
        })
        self.popup_body = _body({
            "event_name": "Weeknight Chess & Coffee",
            "activity": "casual chess over coffee",
            "location": "Compass Coffee, Navy Yard",
            "time": "Wednesday evening",
            "matched_users": ["placeholder"],
            "reason": "You three all unwind on weekday evenings and bond over a slow game and good conversation.",
        })
        self.messages = _Messages(self)

    def interview_answer(self, name, question):
        # craft a scripted-but-personalized answer from the user's own profile.
        user = _user_by_name(name)
        if user is None:
            return "(scripted demo answer)"
        hobbies = ", ".join(user["hobbies"])
        availability = ", ".join(user["availability"])
        if "availability" in question:
            return ("I'm usually free {}. As someone who's {}, I bring {} energy to a group."
                    .format(availability, user["personality"], user["personality"]))
        return ("Right now I'd love to meet people around {}. I'm pretty {}, so something "
                "low-key suits me.".format(hobbies, user["personality"]))


if __name__ == "__main__":
    print("### OFFLINE DEMO -- scripted AI replies, ZERO API calls, no cost ###")
    asyncio.run(run_pipeline(USERS, client=DemoClient()))
