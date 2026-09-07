"""Free, offline simulation of a real Ten Trails onboarding + matching cycle.

Companion to demo.py, but for the REAL neighborhood-pilot code path
(onboarding.py -> batch.py -> my_match.py) instead of the original demo
pipeline. Every function called here is the exact, unmodified production
code a real resident's browser session would hit -- the only thing scripted
is the AI's replies (PilotDemoClient below), via the same client-injection
points main.py/demo.py already use (SPEC section 9). Zero API calls, zero
cost, so this can be re-run any time to sanity-check the pilot flow's
plumbing before ever spending real money (see dryrun.py for the real-AI,
real-cost version of this same idea).

Each persona covers personality/interests/availability/group-size/seeking in
one scripted message, so the whole cycle -- onboarding, threshold batch
trigger, matching, negotiation, and the mutual-accept reveal gate (including
a decline/dissolve) -- fits in one readable run. A real conversation takes
several back-and-forth turns; dryrun.py's "chat" mode exercises that part.

Run: python src/pilot_demo.py   (writes to an ISOLATED db, never clawnly.db)
"""

import asyncio
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_DB_PATH = os.path.join(os.path.dirname(_HERE), "clawnly_pilot_demo.db")
os.environ.setdefault("CLAWNLY_DB_PATH", _DB_PATH)

import batch
import db
import my_match
import onboarding


def _body(obj):
    return json.dumps(obj)


PERSONAS = [
    {
        "name": "Sam Rivera", "age": 29, "gender": "woman", "personality": "mixed",
        "occupation": "working professional", "hobbies": ["hiking", "trail running"],
        "availability": ["weekend_daytime", "weekend_evening"],
        "location": "Ten Trails - The Ridge",
        "bio": "Loves getting out on the actual ten trails after work.",
        "preferred_group_size": "no preference",
        "opening": ("Hi! I'm Sam, 29, working in marketing. I'm somewhere between introverted and "
                    "extroverted depending on the day. I love hiking and trail running, especially "
                    "right here in the neighborhood. Usually free weekend mornings and evenings. "
                    "I'd love to meet 3 or 4 other neighbors into the outdoors -- no huge group."),
    },
    {
        "name": "Priya Nair", "age": 31, "gender": "woman", "personality": "extroverted",
        "occupation": "working professional", "hobbies": ["hiking", "board games"],
        "availability": ["weekend_daytime"],
        "location": "Ten Trails - Foothills",
        "bio": "New to the neighborhood and eager to make friends who like being active.",
        "preferred_group_size": [3, 5],
        "opening": ("Hey there! Priya, 31, just moved into Foothills. Definitely extroverted -- love "
                    "meeting new people. Hiking is my thing, plus a good board game night. Weekend "
                    "days are when I'm free. I'd like a group of 3 to 5 -- an actual little crew."),
    },
    {
        "name": "Marcus Chen", "age": 34, "gender": "man", "personality": "mixed",
        "occupation": "freelancer", "hobbies": ["trail running", "photography"],
        "availability": ["weekend_daytime", "weekday_evening"],
        "location": "Ten Trails - The Ridge",
        "bio": "Freelance designer who works odd hours and wants a consistent group.",
        "preferred_group_size": "no preference",
        "opening": ("Hi, I'm Marcus, 34, freelance graphic designer -- flexible schedule, but I keep "
                    "weekend days and weekday evenings open for people. A mix of introvert and "
                    "extrovert. Trail running and photography are my two big things. No strong "
                    "opinion on group size, just want people who'll actually show up."),
    },
    {
        "name": "Grace Kim", "age": 38, "gender": "woman", "personality": "extroverted",
        "occupation": "working professional", "hobbies": ["gardening", "hiking"],
        "availability": ["weekend_daytime"],
        "location": "Ten Trails - The Ridge",
        "bio": "In the neighborhood a year, knows a few people but wants a real group.",
        "preferred_group_size": "no preference",
        "opening": ("Hi! Grace, 38, in Ten Trails about a year now, work in healthcare admin. "
                    "Definitely extroverted. Gardening and hiking are my main hobbies. Free weekend "
                    "daytimes. Open to any group size, just want people I actually click with."),
    },
    {
        "name": "Dana Whitfield", "age": 27, "gender": "nonbinary", "personality": "introverted",
        "occupation": "working professional", "hobbies": ["board games", "reading"],
        "availability": ["weekday_evening"],
        "location": "Ten Trails - Foothills",
        "bio": "Works from home and wants low-key weeknight company.",
        "preferred_group_size": [2, 4],
        "opening": ("Hey, I'm Dana, 27, they/them. Work from home in software, pretty introverted, "
                    "so looking for something small and low-key. Really into board games and "
                    "reading. Weekday evenings work best -- weekends I like to recharge alone. "
                    "Would love a group of 2 to 4, tops."),
    },
    {
        "name": "Omar Haddad", "age": 33, "gender": "man", "personality": "introverted",
        "occupation": "student", "hobbies": ["chess", "reading"],
        "availability": ["weekday_evening"],
        "location": "Ten Trails - Foothills",
        "bio": "Back in school part-time, misses having a regular social routine.",
        "preferred_group_size": "no preference",
        "opening": ("Hi, Omar, 33. Back in school part time, so my days are a mix, but weekday "
                    "evenings are solid. On the introverted side. Chess and reading are what I do "
                    "with my free time. No real preference on group size."),
    },
    {
        "name": "Lena Brooks", "age": 26, "gender": "woman", "personality": "introverted",
        "occupation": "working professional", "hobbies": ["reading", "board games"],
        "availability": ["weekday_evening"],
        "location": "Ten Trails - Foothills",
        "bio": "Recently moved from out of state and doesn't know anyone yet.",
        "preferred_group_size": "no preference",
        "opening": ("Hi! I'm Lena, 26, just moved here from out of state for work and don't know "
                    "anyone yet. Pretty introverted -- reading and board games are basically my "
                    "whole personality right now. Weekday evenings are best. Open to any size "
                    "group, I just want to actually meet people."),
    },
]


def _persona_by_name(name):
    i = 0
    while i < len(PERSONAS):
        if PERSONAS[i]["name"] == name:
            return PERSONAS[i]
        i += 1
    return None


def _parse_name(system):
    # a simulated=True Claw's system prompt starts "You ARE <name>." -- same
    # trick demo.py uses.
    marker = "You ARE "
    start = system.find(marker)
    if start == -1:
        return None
    start = start + len(marker)
    end = system.find(".", start)
    return system[start:end]


def _extraction_body(persona):
    slots = {"personality_energy": True, "interests": True, "availability": True,
              "group_size": True, "seeking": True}
    fields = {
        "name": persona["name"], "age": persona["age"], "gender": persona["gender"],
        "personality": persona["personality"], "occupation": persona["occupation"],
        "bio": persona["bio"], "location": persona["location"],
        "hobbies": persona["hobbies"], "availability": persona["availability"],
        "preferred_group_size": persona["preferred_group_size"],
    }
    return _body({"slots": slots, "fields": fields})


class _Resp:
    def __init__(self, text):
        self.content = [type("Block", (), {"type": "text", "text": text})()]


class _Messages:
    def __init__(self, outer):
        self.outer = outer

    async def create(self, **kwargs):
        outer = self.outer
        messages = kwargs.get("messages", [])
        system = kwargs.get("system", "")
        low = system.lower()
        content = messages[-1]["content"]

        if "actual human on the other end" in low:
            # the resident's own Claw replying during onboarding -- cosmetic
            # here, since every persona completes their profile in one turn.
            return _Resp("Thanks for sharing all that -- sounds like a great fit "
                          "for the neighborhood. I've got what I need for now!")
        if "personality_energy" in low:
            return _Resp(outer.extraction_queue.pop(0))
        if "form one meetup" in low:
            return _Resp(outer.match_queue.pop(0))
        if "joint activity" in low:
            return _Resp(outer.propose_queue.pop(0))
        if "on board" in low:
            return _Resp(outer.assess_queue.pop(0))
        if "embody this character" in low:
            name = _parse_name(system)
            persona = _persona_by_name(name)
            if "Separate your two answers" in content:
                hobbies = ", ".join(persona["hobbies"])
                availability = ", ".join(persona["availability"])
                a1 = "I'd love to meet people around {}.".format(hobbies)
                a2 = "I'm usually free {}, and I bring {} energy to a group.".format(
                    availability, persona["personality"])
                return _Resp(a1 + "\n===\n" + a2)
            if "React as yourself" in content:
                return _Resp("That works for me -- I'm in!")
            return _Resp("Sounds good to me.")
        return _Resp(outer.popup_queue.pop(0))


class PilotDemoClient:
    """Scripted stand-in for AsyncAnthropic, tuned to the pilot's own prompts."""

    def __init__(self, group_a_ids, group_b_ids):
        self.extraction_queue = []
        i = 0
        while i < len(PERSONAS):
            self.extraction_queue.append(_extraction_body(PERSONAS[i]))
            i += 1

        self.match_queue = [
            _body({
                "group": group_a_ids,
                "reason": ("Sam, Priya, Marcus and Grace all share weekend daytime availability and "
                           "a genuine hiking anchor (Sam & Marcus also trail run); Priya's group-size "
                           "range of 3-5 fits a group of four."),
                "scores": {"personality": 4, "availability": 5, "interests": 5, "size_fit": 4},
                "why_not": [
                    {"id": group_b_ids[0],
                     "reason": "Dana's schedule is weekday-evening only -- no overlap with this group's shared weekend window."},
                ],
            }),
            _body({
                "group": group_b_ids,
                "reason": ("Dana, Omar and Lena all keep weekday evenings free and share a calm, "
                           "low-key anchor in board games and reading -- Dana's 2-4 range fits a "
                           "group of three."),
                "scores": {"personality": 4, "availability": 4, "interests": 4, "size_fit": 4},
                "why_not": [],
            }),
        ]
        self.propose_queue = [
            _body({"activity": "a group hike on the neighborhood trails, then coffee",
                   "pitch": "You're all early risers who love the outdoors -- let's hit the trails together, then grab coffee after."}),
            _body({"activity": "a casual board game night",
                   "pitch": "You all keep weeknights free and love a good low-key game -- let's get a board game night going."}),
        ]
        self.assess_queue = [
            _body({"members": [{"name": "Sam Rivera", "on_board": True, "note": ""},
                                {"name": "Priya Nair", "on_board": True, "note": ""},
                                {"name": "Marcus Chen", "on_board": True, "note": ""},
                                {"name": "Grace Kim", "on_board": True, "note": ""}],
                   "agreed": True, "concern": ""}),
            _body({"members": [{"name": "Dana Whitfield", "on_board": True, "note": ""},
                                {"name": "Omar Haddad", "on_board": True, "note": ""},
                                {"name": "Lena Brooks", "on_board": True, "note": ""}],
                   "agreed": True, "concern": ""}),
        ]
        self.popup_queue = [
            _body({"options": [
                {"event_name": "Ten Trails Trailhead Hike & Coffee",
                 "activity": "a group hike followed by coffee",
                 "location": "the Ten Trails trailhead off Lawson St, Black Diamond",
                 "time": "Saturday morning around 9am",
                 "reason": "A trailhead hike puts Sam and Marcus's trail running and Priya and Grace's hiking front and center, right on your own trails."},
            ]}),
            _body({"options": [
                {"event_name": "Board Games & Books Night",
                 "activity": "a casual board game night",
                 "location": "the Ten Trails community clubhouse",
                 "time": "Wednesday evening around 7pm",
                 "reason": "A low-key clubhouse game night matches the calm, weeknight energy all three of you asked for."},
            ]}),
        ]
        self.messages = _Messages(self)


def _rule(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


async def _onboard(resident, persona, client):
    result = await onboarding.take_turn(resident, persona["opening"], client=client)
    print("  {} -> profile complete: {}".format(persona["name"], result["complete"]))


def _print_state(label, resident_row):
    state = my_match.get_state(resident_row)
    print("\n{} ({}):".format(label, state["state"]))
    if state["state"] == "pending":
        print("  reason: {}".format(state["reason"]))
        print("  group_size: {} (no names yet -- the mutual-accept gate)".format(state["group_size"]))
    elif state["state"] == "sealed":
        print("  reason: {}".format(state["reason"]))
        print("  other members revealed: {}".format(", ".join(state["other_first_names"])))
        meetup = state["meetup"]
        if meetup is not None:
            print("  meetup: {} -- {} @ {}".format(
                meetup.get("event_name"), meetup.get("time"), meetup.get("location")))
    return state


async def main():
    print("### PILOT DEMO -- scripted AI replies, ZERO API calls, no cost ###")
    print("Using database: " + db.DB_PATH)
    if db.DB_PATH == os.path.join(os.path.dirname(_HERE), "clawnly.db"):
        print("REFUSING to run against the real clawnly.db.")
        return
    db.init_db()

    neighborhood = db.get_or_create_neighborhood("ten-trails-demo", "Ten Trails", len(PERSONAS))
    print("Neighborhood: ten-trails-demo (threshold={})".format(neighborhood["batch_threshold"]))

    _rule("Onboarding {} residents (one scripted message each)".format(len(PERSONAS)))
    residents_by_name = {}
    i = 0
    while i < len(PERSONAS):
        persona = PERSONAS[i]
        email = "demo-{}@example.com".format(i)
        resident = db.get_or_create_resident(neighborhood["id"], email, "magic_link")
        db.record_consent(resident["id"])
        residents_by_name[persona["name"]] = resident
        i += 1

    group_a_names = ["Sam Rivera", "Priya Nair", "Marcus Chen", "Grace Kim"]
    group_b_names = ["Dana Whitfield", "Omar Haddad", "Lena Brooks"]
    group_a_ids = []
    i = 0
    while i < len(group_a_names):
        group_a_ids.append("r" + str(residents_by_name[group_a_names[i]]["id"]))
        i += 1
    group_b_ids = []
    i = 0
    while i < len(group_b_names):
        group_b_ids.append("r" + str(residents_by_name[group_b_names[i]]["id"]))
        i += 1

    client = PilotDemoClient(group_a_ids, group_b_ids)

    i = 0
    while i < len(PERSONAS):
        persona = PERSONAS[i]
        await _onboard(residents_by_name[persona["name"]], persona, client)
        i += 1

    _rule("Triggering the batch run (interview -> match -> negotiate -> venue)")
    run_id, error = await batch.force_trigger_batch(neighborhood["id"], client=client)
    if error is not None:
        print("Batch did not run: " + error)
        return
    print("Batch run id: " + str(run_id))

    _rule("Group A -- the mutual-accept reveal gate")
    sam = db.get_resident(residents_by_name["Sam Rivera"]["id"])
    _print_state("Sam, before anyone responds", sam)
    j = 0
    while j < len(group_a_names) - 1:
        name = group_a_names[j]
        resident_row = db.get_resident(residents_by_name[name]["id"])
        state = my_match.get_state(resident_row)
        my_match.respond(resident_row, state["match_id"], "accept")
        j += 1
    grace = db.get_resident(residents_by_name["Grace Kim"]["id"])
    state = my_match.get_state(grace)
    my_match.respond(grace, state["match_id"], "accept")   # the accept that seals it
    sam = db.get_resident(residents_by_name["Sam Rivera"]["id"])
    _print_state("Sam, after the whole group has accepted", sam)

    _rule("Group B -- a decline dissolves the match for everyone")
    dana = db.get_resident(residents_by_name["Dana Whitfield"]["id"])
    state = my_match.get_state(dana)
    my_match.respond(dana, state["match_id"], "accept")
    dana = db.get_resident(residents_by_name["Dana Whitfield"]["id"])
    _print_state("Dana, after accepting (waiting on the others)", dana)

    omar = db.get_resident(residents_by_name["Omar Haddad"]["id"])
    state = my_match.get_state(omar)
    my_match.respond(omar, state["match_id"], "decline")

    dana = db.get_resident(residents_by_name["Dana Whitfield"]["id"])
    lena = db.get_resident(residents_by_name["Lena Brooks"]["id"])
    _print_state("Dana, after Omar declined", dana)
    _print_state("Lena, after Omar declined (never even responded)", lena)

    eligible = db.list_eligible_residents(neighborhood["id"])
    eligible_names = []
    k = 0
    while k < len(eligible):
        eligible_names.append(eligible[k]["name"])
        k += 1
    _rule("Released back into the pool for the next batch")
    print("Eligible again: " + ", ".join(eligible_names))


if __name__ == "__main__":
    asyncio.run(main())
