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
                return _Resp(self.outer.propose_for(content))
            if "on board" in low:
                return _Resp(self.outer.assess_for(content))
            return _Resp(self.outer.popup_for(content))
        # otherwise a Claw persona call (interview, reaction, or free-style chat).
        name = _parse_name(system)
        if "Separate your two answers" in content:
            a1 = self.outer.interview_answer(name, "what are you looking for socially")
            a2 = self.outer.interview_answer(name, "availability and energy")
            return _Resp(a1 + "\n===\n" + a2)
        if "React as yourself" in content:
            return _Resp(self.outer.reaction_for(name, content))
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
        self.messages = _Messages(self)

    # ----- negotiation: a scripted, content-driven multi-round exchange --------
    # Group 1 (Maya/Marcus/Omar) genuinely disagrees, so the demo shows a real
    # arc: chess (Maya's out) -> writing (Omar's out) -> a dinner everyone loves.
    # Other groups get an easy plan they all like on the first try.

    def propose_for(self, payload):
        low = payload.lower()
        # only Maya's group runs the scripted back-and-forth; others agree fast.
        if "maya" not in low:
            return _body({
                "activity": "a relaxed weekend hangout -- coffee and an easy walk by the water",
                "pitch": "You all like getting outside and keeping it easy, so let's grab coffee and take a walk somewhere pretty and just catch up.",
            })
        marker = "specific concern was:"
        idx = low.find(marker)
        if idx == -1:
            # round 1: propose chess (Maya won't be into it).
            return _body({
                "activity": "a weeknight chess night over coffee",
                "pitch": "You all keep weekday evenings free and lean low-key -- grab a chess board, find a quiet corner, and let a game or two give the evening some shape.",
            })
        concern = low[idx + len(marker):]
        if "writing" in concern or "story" in concern:
            # round 3: the compromise everyone actually wants.
            return _body({
                "activity": "a relaxed dinner and long conversation in Fremont",
                "pitch": "Let's keep it simple -- a low-key dinner where the whole point is the conversation. No games, no pressure, just good food and real talk.",
            })
        # round 2: the concern was about chess -> try a creative writing night.
        return _body({
            "activity": "a small creative writing and storytelling night",
            "pitch": "A couple of you lean creative, so let's do a writing night -- each bring a short piece or a prompt and riff on them together, low pressure and lots of room to talk.",
        })

    def assess_for(self, payload):
        # judge each member from their reaction line; agreed only if all are in.
        markers = ["not into", "not sure", "outside my lane", "stresses me", "not really", "not my thing"]
        members = []
        concern = ""
        lines = payload.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith("- ") and ":" in line:
                rest = line[2:]
                sep = rest.find(":")
                name = rest[:sep].strip()
                text = rest[sep + 1:].strip()
                low_text = text.lower()
                on = True
                j = 0
                while j < len(markers):
                    if markers[j] in low_text:
                        on = False
                    j += 1
                members.append({"name": name, "on_board": on, "note": ("" if on else "has reservations")})
                if not on and len(concern) == 0:
                    concern = name + " isn't sold: " + text
            i += 1
        agreed = True
        k = 0
        while k < len(members):
            if not members[k]["on_board"]:
                agreed = False
            k += 1
        return _body({"members": members, "agreed": agreed, "concern": concern})

    def popup_for(self, payload):
        low = payload.lower()
        if "dinner" in low or "conversation" in low:
            options = [
                {"event_name": "Fremont Dinner & Long Talk", "activity": "a relaxed dinner with unhurried conversation",
                 "location": "The Whale Wins, Fremont", "time": "Wednesday evening around 7pm",
                 "reason": "A calm Fremont dinner is exactly the low-key, deep-conversation hang all three of you wanted."},
                {"event_name": "Quiet Coffee & Catch-up", "activity": "coffee and conversation in a calm cafe",
                 "location": "Miir Cafe, Ballard", "time": "Tuesday evening around 7pm",
                 "reason": "A quiet Ballard cafe gives you the unhurried, small-group talk you each asked for."},
            ]
        else:
            options = [
                {"event_name": "Green Lake Walk & Coffee", "activity": "an easy loop around the lake, then coffee",
                 "location": "Green Lake Park loop, then Diva Espresso", "time": "Saturday morning around 10am",
                 "reason": "An easy weekend loop and coffee suits your relaxed, get-outside vibe perfectly."},
                {"event_name": "Discovery Park Ramble", "activity": "a scenic walk with plenty of time to chat",
                 "location": "Discovery Park, Magnolia", "time": "Sunday morning around 10am",
                 "reason": "A pretty, low-key trail is an easy way for the three of you to actually catch up."},
            ]
        return _body({"options": options})

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

    def reaction_for(self, name, pitch):
        # a scripted in-character reaction that depends on WHAT was proposed, so the
        # demo shows genuine disagreement that resolves over several rounds.
        low = pitch.lower()
        if "chess" in low:
            if name == "Maya":
                return ("Honestly, I'm not into chess -- it kind of stresses me out. "
                        "Could we do something lower-key where we just talk?")
            picks = {"Marcus": "Chess after the gym? Yeah, I'm in.",
                     "Omar": "Works for me -- a good game and real conversation beats a loud bar."}
            return picks.get(name, "Sounds good to me, I'm in.")
        if "writing" in low or "story" in low:
            if name == "Omar":
                return ("I'm not sure about this one -- writing's a bit outside my lane. "
                        "Could we do something with more back-and-forth, like a good talk over dinner?")
            picks = {"Maya": "Oh I love this -- writing together feels way less performative. I'm in.",
                     "Marcus": "Honestly yeah, I've been craving that kind of creative company."}
            return picks.get(name, "Sounds good to me, I'm in.")
        # the compromise (dinner / conversation / walk) -- everyone is happy.
        picks = {"Maya": "Yes! A relaxed dinner where we can actually talk is exactly my speed.",
                 "Marcus": "That works for me -- good food and real conversation, I'm in.",
                 "Omar": "Perfect, that's the kind of hang I actually enjoy. I'm in."}
        return picks.get(name, "Yeah, I'm into this -- count me in.")

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
