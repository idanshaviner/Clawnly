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
        content = messages[-1]["content"]
        # route by system marker (no assistant-prefill anymore).
        if "embody this character" not in low:
            # match routes by model OR its unique prompt marker.
            if kwargs.get("model") == self.outer.match_model or "form one meetup" in low:
                # serve successive groups (multi mode forms more than one).
                bodies = self.outer.match_bodies
                idx = self.outer.match_index
                if idx >= len(bodies):
                    idx = len(bodies) - 1
                self.outer.match_index = idx + 1
                return _Resp(bodies[idx])
            if "joint activity" in low:
                return _Resp(self.outer.propose_body)
            if "on board" in low:
                return _Resp(self.outer.assess_body)
            return _Resp(self.outer.popup_body)
        # otherwise a Claw persona call (interview, reaction, or free-style chat).
        name = _parse_name(system)
        if "Separate your two answers" in content:
            a1 = self.outer.interview_answer(name, "what are you looking for socially")
            a2 = self.outer.interview_answer(name, "availability and energy")
            return _Resp(a1 + "\n===\n" + a2)
        if "React as yourself" in content:
            return _Resp(self.outer.reaction_for(name))
        # a free-style chat message -> a reply that reflects edited traits (parsed
        # from the system prompt) and varies with the question.
        return _Resp(self.outer.chat_reply(system, content))


class DemoClient:
    """Scripted stand-in for AsyncAnthropic -- no network, no cost."""

    def __init__(self):
        import config
        self.match_model = config.MODEL_MATCH
        # a scripted partition: group 1, then group 2, then "no more" -- so single
        # mode shows the chess trio and multi mode shows two groups + leftovers.
        self.match_index = 0
        self.match_bodies = [
            _body({
                "group": ["u01", "u04", "u10"],
                "reason": ("Maya, Marcus and Omar all keep weekday evenings free, lean introverted, "
                           "and share a calm intellectual streak (reading, chess, writing)."),
                "scores": {"personality": 3, "availability": 4, "interests": 4, "size_fit": 5},
                "why_not": [
                    {"id": "u08", "reason": "Ethan wants a 6-8 person group -- too big for this meetup."},
                ],
            }),
            _body({
                "group": ["u03", "u09", "u11"],
                "reason": ("Priya, Nina and Grace all have free daytimes and a creative, "
                           "community-minded streak -- a complementary, easygoing trio."),
                "scores": {"personality": 4, "availability": 4, "interests": 4, "size_fit": 4},
                "why_not": [],
            }),
            _body({"group": [], "reason": "No further compatible group among the remaining people.",
                   "scores": {}, "why_not": []}),
        ]
        self.propose_body = _body({
            "activity": "a relaxed weeknight chess night over coffee",
            "pitch": "How about a low-key chess night over coffee on a weekday evening? It fits all our schedules and our quieter vibe.",
        })
        self.assess_body = _body({"agreed": True, "concern": ""})
        self.popup_body = _body({
            "options": [
                {"event_name": "Weeknight Chess & Coffee", "activity": "casual chess over coffee",
                 "location": "Compass Coffee, Navy Yard", "time": "Wednesday evening",
                 "reason": "You all unwind on weekday evenings and bond over a slow game and good talk."},
                {"event_name": "Quiet Reading Hour", "activity": "a books-and-coffee hang",
                 "location": "Politics and Prose, Connecticut Ave", "time": "Tuesday evening",
                 "reason": "A calm weeknight over books suits this introverted, bookish trio."},
            ],
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

    def reaction_for(self, name):
        # a scripted in-character reaction to the proposed plan.
        reactions = {
            "Maya": "Honestly that sounds perfect -- a calm evening is exactly my speed.",
            "Marcus": "Chess after the gym? Yeah, I'm in.",
            "Omar": "Works for me -- a good game and real conversation beats a loud bar.",
        }
        if name in reactions:
            return reactions[name]
        return "Sounds good to me, I'm in."

    def chat_reply(self, system, message):
        # a scripted chat reply that reflects EDITED traits (parsed from the live
        # system prompt) and varies with the message. Live mode is the real thing.
        personality = _parse_field(system, "- Personality:")
        hobbies = _parse_field(system, "- Hobbies:")
        first_hobby = "a few things I love"
        if len(hobbies) > 0:
            first_hobby = hobbies.split(",")[0].strip()
        leans = {
            "introverted": "I'd honestly keep it low-key and small",
            "extroverted": "I'm always up for something lively",
            "mixed": "it kind of depends on my mood",
        }
        lean = leans.get(personality, "I'm pretty easygoing about it")
        snippet = message.strip()
        if len(snippet) > 60:
            snippet = snippet[:60] + "..."
        return ('(demo) You said: "{}" -- as a {} person, {}. I\'m really into {} lately. '
                "What about you?").format(snippet, personality, lean, first_hobby)


def _parse_field(system, prefix):
    # pull a "- Field: value" line out of the persona system prompt.
    lines = system.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith(prefix):
            return line[len(prefix):].strip()
        i += 1
    return ""


if __name__ == "__main__":
    print("### OFFLINE DEMO -- scripted AI replies, ZERO API calls, no cost ###")
    asyncio.run(run_pipeline(USERS, client=DemoClient()))
