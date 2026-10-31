"""Run Clawnly on the server: the matchmaker plans a day of small activity groups.

Hub and spoke, never agent to agent. For one day in the neighborhood:

  1. break rooms (code, demand.break_room): one per activity and time of day,
     holding every neighbor who is free, keen, can afford it and doesn't avoid it.
  2. plan (Opus): the matchmaker picks groups from the break rooms, with
     alternates and a personal proposal to each person's agent. Rooms list the
     people with fewer plans this week first. Code keeps only people who are in
     that break room and never books anyone twice; a seat (member or alternate)
     needs a strong interest in what the activity is mainly about, its first tag,
     so someone there only for a side interest or a mild one gets no seat.
  3. round 1 (Sonnet, one call per agent): the matchmaker asks each agent one
     to one; the agent checks the plan against its person's full profile (likes,
     dislikes, what they avoid, budget, the week's calendar) plus what code found
     in it (plan_checks), and answers yes / no / counter. Code takes a yes only
     with a reason from the profile and nothing in it that rules the plan out.
  4. resolve (Opus): accept counters by moving the time, replace a no. For each
     group with a no, code also lists up to POOL_PER_GROUP free people from its
     break room (a strong interest in the main activity, not asked today, nothing
     in the profile against it, fewest plans first), and the matchmaker picks who fits. Code only lets
     it ask the group's own members, alternates or that free list, never someone
     who already said yes elsewhere, and never one person for two groups.
  5. round 2 (Sonnet): only the people the matchmaker re-asks. If one of them
     says no, steps 4 and 5 run once more (round 3), while there's anyone left.
  6. lock (code): a group goes ahead once at least 2 people said yes.
  7. the message (Sonnet): the one message each person receives.

The run is one plain dict -- the same shape the Run Clawnly page renders -- with
every hub<->agent message, every step in `log`, and every Claude call verbatim
in `calls` (also in db.ai_calls through ai_log.LoggedClient). on_progress(run)
is called after each step so the page can follow along live.
"""

import asyncio
import datetime
import re
import time

import ai_log
import catalog
import config
import demand
import population
from llm_io import extract_json, join_text


PART_HOURS = {"morning": "8am-12pm", "afternoon": "12-5pm", "evening": "5-10pm"}
WEEKDAY = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# how many agents are asked at once
AGENT_CONCURRENCY = 4
# the keenest people in a break room, listed with keenness and a profile line (once each,
# in PEOPLE); the rest of the room by id only. Keeps what Opus reads, and pays for, small.
PROFILES_PER_ROOM = 8
# a seat needs a strong interest (really likes or loves) in what the activity is mainly about, its
# first tag. In 200 live groups agents said yes to a mild interest 4 times in 6, and in the Sunday
# 1 Nov browser run the Green River Gorge hike went to three people who were there for the fishing
STRONG = 2
# a group with a no also sees this many free, keen people from its break room besides its
# alternates: in the retest, 5 of 6 no's went unfilled, each after both alternates said no too
POOL_PER_GROUP = 4
# round 1 asks the plan; rounds 2 and 3 replace whoever said no
LAST_ROUND = 3


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def day_label(day):
    return WEEKDAY[day.weekday()] + " " + str(day.day) + " " + day.strftime("%b")


def _first(person):
    return person["name"].split(" ")[0]


def _words(tag):
    return str(tag).replace("_", " ")


def _index(items):
    out = {}
    i = 0
    while i < len(items):
        out[items[i]["id"]] = items[i]
        i += 1
    return out


# ----- prompts: each system prompt carries one marker phrase (ai_log.PURPOSES) -----

def _person_line(p, plans=0):
    # one compact line per person; the plan lists each person once, however many rooms they're in
    likes = []
    i = 0
    while i < len(p["likes"]):
        likes.append(_words(p["likes"][i]["tag"]) + " " + str(p["likes"][i]["weight"]))
        i += 1
    kids = ""
    if p["kids_at_home"]:
        kids = ", kids"
    avoid = ""
    if len(p["avoid"]) > 0:
        words = []
        i = 0
        while i < len(p["avoid"]):
            words.append(_words(p["avoid"][i]))
            i += 1
        # the hub can't see the profile otherwise, and a fixed late event can still reach a late-night avoider
        avoid = "; avoids " + ", ".join(words)
    already = ""
    if plans > 0:
        already = "; plans this week: " + str(plans)
    return "  " + p["id"] + " " + p["name"] + ", " + str(p["age"]) + ", " + p["archetype"] + kids + ", " + p["area"] + ": " + ", ".join(likes) + avoid + already


def _liked_here(person, activity):
    # which of this activity's tags the person likes: what their keenness is made of
    out = []
    i = 0
    while i < len(activity["tags"]):
        j = 0
        while j < len(person["likes"]):
            if person["likes"][j]["tag"] == activity["tags"][i]:
                out.append(_words(activity["tags"][i]))
            j += 1
        i += 1
    return ", ".join(out)


def _plan_system(day, max_groups):
    return "\n".join([
        "You are the Clawnly matchmaker: the orchestrator for " + catalog.NEIGHBORHOOD + ". Task: plan the day's activity groups for " + day_label(day) + ".",
        "Each neighbor has told their own agent what they like, what they don't, and when they're free. You talk to each person's agent one to one. Agents never talk to each other. The goal is not friendship matching: it is a good small group doing something real together, so neighbors get to know each other.",
        "",
        "The break rooms were built by code: one per activity and time of day that can run that day, holding every neighbor who is free then, interested, can afford it and doesn't avoid anything about it. Each room lists only the people who can take a seat: they really like or love what the activity is mainly about (marked main), fewest plans this week first, as id:keenness [which of the activity's tags they like] (higher is better), then the rest of them by id. PEOPLE has one line per listed person, once each, with what they avoid and any plans they already have this week.",
        "",
        "Plan up to " + str(max_groups) + " groups:",
        "- Size each group to fit the activity and the people. You decide: two neighbors having a beer over the game is a group, and so is a bigger hike. Small groups are often where people actually meet each other.",
        "- Each person in at most one group. Use only people in that break room.",
        "- Members and alternates come only from the people listed. Someone in the room only for a side interest (the beer at a trivia night, the fishing on a hike) or a mild one gets no seat.",
        "- Prefer groups whose members share more than the activity (overlapping likes, similar stage of life), so they'd enjoy each other.",
        "- Favor people with fewer plans this week: when two people fit, the place goes to the one with fewer. Spread plans across many people rather than stacking the keenest into one group.",
        "- Pick a specific time inside the day part (morning " + PART_HOURS["morning"] + ", afternoon " + PART_HOURS["afternoon"] + ", evening " + PART_HOURS["evening"] + "). A room marked FIXED is a real event (a game, a concert): use exactly that time.",
        "- Name up to 2 alternates per group from the same break room, in case someone declines.",
        "- Write a short, personal proposal to each member's agent: what, when, where, how many others, and why it fits this person. Don't name the other people yet.",
        "- In the why and the proposals, describe only interests people actually have: someone in a trivia room for the craft beer isn't a trivia fan. Check what a person avoids against a FIXED time.",
        "",
        "Reply with only this JSON object:",
        '{"thoughts": "your reasoning about the day, 3-6 sentences", "groups": [{"activity": "activity id", "part": "morning|afternoon|evening", "time": "e.g. 10:30am-12pm", "members": ["person id"], "alternates": ["person id"], "why": "one sentence: why this group", "proposals": {"person id": "the message to that person\'s agent"}}]}',
    ])


def split_room(room, people):
    # (seats, rest): the room's candidates who can be members or alternates, and the ones who are
    # there only for a side interest or a mild one
    activity = catalog.get(room["activity"])
    seats = []
    rest = []
    i = 0
    while i < len(room["candidates"]):
        c = room["candidates"][i]
        if main_keenness(people[c["id"]], activity) >= STRONG:
            seats.append(c)
        else:
            rest.append(c)
        i += 1
    return seats, rest


def _fewest_plans_first(rooms, plans):
    # within each room, people with fewer plans this week come first; keenness still orders the rest
    i = 0
    while i < len(rooms):
        rooms[i]["candidates"].sort(key=lambda c: plans.get(c["id"], 0))
        i += 1


def _plan_payload(rooms, people, plans=None):
    if plans is None:
        plans = {}
    lines = ["BREAK ROOMS:"]
    listed = []
    seen = {}
    i = 0
    while i < len(rooms):
        room = rooms[i]
        i += 1
        strong, others = split_room(room, people)
        # no group can form without two members who really want it
        if len(strong) < 2:
            continue
        a = catalog.get(room["activity"])
        tags = [_words(a["tags"][0]) + " (main)"]
        t = 1
        while t < len(a["tags"]):
            tags.append(_words(a["tags"][t]))
            t += 1
        header = "[" + a["id"] + " | " + room["part"] + "] " + a["name"] + " at " + a["where"] + ", cost " + a["cost"] + ", about: " + ", ".join(tags)
        fixed = fixed_time(a, room["part"])
        if fixed is not None:
            header = header + ", FIXED " + fixed
        lines.append("")
        lines.append(header + " (" + str(len(room["candidates"])) + " in the room)")
        top = []
        rest = []
        j = 0
        while j < len(strong):
            c = strong[j]
            if j < PROFILES_PER_ROOM:
                top.append(c["id"] + ":" + str(c["score"]) + " [" + _liked_here(people[c["id"]], a) + "]")
                if c["id"] not in seen:
                    seen[c["id"]] = True
                    listed.append(c["id"])
            else:
                rest.append(c["id"])
            j += 1
        lines.append("  keenest: " + "; ".join(top))
        if len(rest) > 0:
            lines.append("  also: " + " ".join(rest))
    lines.append("")
    lines.append("PEOPLE:")
    k = 0
    while k < len(listed):
        lines.append(_person_line(people[listed[k]], plans.get(listed[k], 0)))
        k += 1
    return "\n".join(lines)


# ----- what an agent checks before answering (Idan: "so they can actually say no") -----

LEVELS = [[3, "Loves"], [2, "Really likes"], [1, "Is up for"]]
BUDGET_WORDS = {"free": "free things only", "low": "free or low-cost things", "any": "any cost"}
_CLOCK = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.IGNORECASE)


def fixed_time(activity, part):
    # the real time of a game, concert or event in that day part, or None when the time is free to pick
    times = activity.get("fixed") or {}
    return times.get(part)


def _to_hours(match, half):
    hour = int(match[0])
    if half == "pm" and hour < 12:
        hour += 12
    if half == "am" and hour == 12:
        hour = 0
    minutes = 0
    if match[1]:
        minutes = int(match[1])
    return hour + minutes / 60.0


def parse_hours(text):
    # "10:30am-12pm" -> (10.5, 12.0); None when there's no start and end to read
    found = _CLOCK.findall(str(text or ""))
    if len(found) < 2:
        return None
    end_half = found[-1][2].lower()
    start_half = found[0][2].lower()
    if start_half == "":
        start_half = end_half
    start = _to_hours(found[0], start_half)
    end = _to_hours(found[-1], end_half)
    # "11pm-12am" ends after midnight, not at hour 0: otherwise it reads as inside the evening
    if end <= start:
        end += 24
    return start, end


def inside_part(time_text, part):
    # calendars and break rooms are checked per day part, so a time outside it was never checked;
    # a time code can't read is left alone (the simulation audit flags it)
    hours = parse_hours(time_text)
    if hours is None:
        return True
    bounds = parse_hours(PART_HOURS[part])
    return hours[0] >= bounds[0] and hours[1] <= bounds[1]


def agent_profile(person):
    # everything the person told their agent, in plain words: the agent checks a plan against all of it
    first = _first(person)
    kids = ""
    if person["kids_at_home"]:
        kids = ", with kids at home"
    lines = [first + " is " + str(person["age"]) + ", a " + person["archetype"] + " in " + person["area"] + kids + "."]
    l = 0
    while l < len(LEVELS):
        tags = []
        i = 0
        while i < len(person["likes"]):
            if person["likes"][i]["weight"] == LEVELS[l][0]:
                tags.append(_words(person["likes"][i]["tag"]))
            i += 1
        if len(tags) > 0:
            lines.append(LEVELS[l][1] + ": " + ", ".join(tags) + ".")
        l += 1
    dislikes = []
    i = 0
    while i < len(person["dislikes"]):
        dislikes.append(_words(person["dislikes"][i]))
        i += 1
    if len(dislikes) > 0:
        lines.append("Not into: " + ", ".join(dislikes) + ".")
    avoid = []
    i = 0
    while i < len(person["avoid"]):
        avoid.append(_words(person["avoid"][i]))
        i += 1
    if len(avoid) > 0:
        lines.append("Avoids: " + ", ".join(avoid) + ".")
    lines.append("Budget: " + BUDGET_WORDS[person["budget"]] + ".")
    days = sorted(person["calendar"].keys())
    week = []
    d = 0
    while d < len(days):
        free = person["calendar"][days[d]]
        free_text = "busy"
        if len(free) > 0:
            free_text = "free " + ", ".join(free)
        week.append(day_label(datetime.date.fromisoformat(days[d])) + ": " + free_text)
        d += 1
    lines.append("This week: " + "; ".join(week) + ".")
    return "\n".join(lines)


def keenness(person, activity):
    # their strongest like among the activity's tags: 3 loves, 2 really likes, 1 only up for it, 0 none
    keen = 0
    i = 0
    while i < len(person["likes"]):
        if person["likes"][i]["tag"] in activity["tags"] and person["likes"][i]["weight"] > keen:
            keen = person["likes"][i]["weight"]
        i += 1
    return keen


def main_keenness(person, activity):
    # how much they like what the activity is mainly about, its first tag: only this earns a seat
    keen = 0
    i = 0
    while i < len(person["likes"]):
        if person["likes"][i]["tag"] == activity["tags"][0]:
            keen = person["likes"][i]["weight"]
        i += 1
    return keen


def no_seat(person, activity):
    # why someone in the break room can't be a member or an alternate, or "" when they can
    main = _words(activity["tags"][0])
    keen = main_keenness(person, activity)
    if keen >= STRONG:
        return ""
    if keen == 1:
        return person["name"] + " is only up for " + main
    return person["name"] + " is in the room for the " + _liked_here(person, activity) + ", not the " + main


def conflicts(person, activity, part, time_text, day):
    # what in the profile rules this plan out: code refuses a yes that runs into any of it
    first = _first(person)
    out = []
    if part not in person["calendar"].get(day.isoformat(), []):
        out.append(first + " is busy that " + part + ".")
    hours = parse_hours(time_text)
    if hours is not None and "early_mornings" in person["avoid"] and hours[0] < 9:
        out.append("It starts before 9am, and " + first + " avoids early mornings.")
    if hours is not None and "late_nights" in person["avoid"] and hours[1] >= 21:
        out.append("It runs to 9pm or later, and " + first + " avoids late nights.")
    i = 0
    while i < len(activity["traits"]):
        # an early start is judged on the real start time above, when there is one
        covered = activity["traits"][i] == "early_mornings" and hours is not None
        if activity["traits"][i] in person["avoid"] and not covered:
            out.append("It involves " + _words(activity["traits"][i]) + ", which " + first + " avoids.")
        i += 1
    i = 0
    while i < len(activity["tags"]):
        if activity["tags"][i] in person["dislikes"]:
            out.append("It's " + _words(activity["tags"][i]) + ", which " + first + " is not into.")
        i += 1
    if activity["cost"] not in demand.BUDGET_OK[person["budget"]]:
        out.append("It costs more than " + first + "'s budget (" + BUDGET_WORDS[person["budget"]] + ").")
    return out


def plan_checks(person, activity, part, time_text, day):
    # what code can see in the profile that argues against this plan; the agent weighs it
    first = _first(person)
    out = conflicts(person, activity, part, time_text, day)
    keen = keenness(person, activity)
    if keen == 0:
        out.append(first + " never said they like this.")
    if keen == 1:
        out.append("Interest is mild: " + first + " is only up for it.")
    return out


def _agent_system(person):
    first = _first(person)
    return "\n".join([
        "You are the personal agent of " + person["name"] + ". You know " + first + " only from their profile and calendar below. You speak for " + first + " to the Clawnly matchmaker. You never talk to other people's agents.",
        "",
        "WHAT " + first.upper() + " TOLD YOU:",
        agent_profile(person),
        "",
        "Check the plan against everything above before you answer: the time against their calendar and what they avoid, the activity against their likes and dislikes, the cost against their budget. Code has listed what it found; weigh it, and look for anything it missed.",
        "What " + first + " avoids is a limit they set, not a preference to trade off: if the plan runs into it, say no (or counter, if the time can move), however much they'd enjoy the rest.",
        '- "yes" only with a strong reason from the profile: something ' + first + ' loves or really likes that this plan gives them. Put that reason in "reason"; a yes without one counts as a no.',
        '- "no" if something clearly conflicts and no small change fixes it, or if there is no strong reason. Being only up for it (a mild interest) is not a strong reason. Saying no is normal and helps the matchmaker.',
        '- "counter" with one concrete change that would make it a yes (for example a later start inside a day part they\'re free). A fixed-time event can\'t move, so don\'t counter its time.',
        'Reply with only this JSON object: {"answer": "yes" or "no" or "counter", "reason": "for a yes: the strong reason, from the profile", "counter": "the change, if any", "say": "one or two sentences to the matchmaker, as ' + first + "'s agent\"}",
    ])


def _agent_payload(person, group, day, message):
    a = catalog.get(group["activity"])
    when = group["time"] + " (" + group["part"] + ")"
    if group.get("fixed"):
        when = when + ", a fixed-time event"
    checks = plan_checks(person, a, group["part"], group["time"], day)
    found = "  nothing in the profile conflicts with it"
    if len(checks) > 0:
        found = "  - " + "\n  - ".join(checks)
    return "\n".join([
        "The matchmaker proposes: " + a["name"] + " at " + a["where"] + ", " + day_label(day) + ", " + when + ", cost " + a["cost"] + ", a small group of neighbors.",
        "The matchmaker's message: " + message,
        "",
        "What code found in " + _first(person) + "'s profile:",
        found,
    ])


def _resolve_system(day):
    return "\n".join([
        "You are the Clawnly matchmaker for " + catalog.NEIGHBORHOOD + ", " + day_label(day) + ". Task: finish the day's plan after each person's agent answered you privately.",
        "For each group: keep it if at least 2 people can do it. Accept a counter by moving the time if that still works for the ones who said yes (then re-ask them with the new time). Replace people who said no (ask them): an alternate, or someone from the group's free list. Drop a group that can't reach 2.",
        "The free list is people from the group's break room who are free, have a strong interest in the main activity and haven't been asked today, fewest plans this week first. Pick whoever fits the people who said yes best (shared likes, similar stage of life); when two fit, pick the one with fewer plans.",
        "Never add anyone who is already in another group. Only ask the group's own members, its alternates or its free list.",
        "Only ask people whose answer you still need: an alternate replacing a no, someone whose counter you're answering, or someone who said yes to a time you've now changed. Don't send confirmations: everyone gets one after the lock. Never tell anyone who declined.",
        "",
        "Reply with only this JSON object:",
        '{"thoughts": "your reasoning, 2-5 sentences", "groups": [{"id": "group id", "keep": true or false, "time": "final time", "ask": [{"id": "person id", "message": "what you say to their agent now"}]}]}',
    ])


def _resolve_payload(groups, people, plans=None):
    if plans is None:
        plans = {}
    lines = ["GROUPS:"]
    i = 0
    while i < len(groups):
        g = groups[i]
        a = catalog.get(g["activity"])
        lines.append("")
        when = g["time"] + " (" + g["part"] + ")"
        if g.get("fixed"):
            when = when + ", FIXED: a real event, the time can't move"
        lines.append(g["id"] + ": " + a["name"] + ", " + when)
        j = 0
        while j < len(g["members"]):
            m = g["members"][j]
            said = m["state"]
            if m["counter"]:
                said = said + " (" + m["counter"] + ")"
            if m.get("refused"):
                said = said + " (code refused their agent's yes: " + m["refused"] + ")"
            lines.append("  " + m["id"] + " " + people[m["id"]]["name"] + ": " + said)
            j += 1
        alts = []
        k = 0
        while k < len(g["alternates"]):
            alts.append(g["alternates"][k] + " " + people[g["alternates"][k]]["name"])
            k += 1
        if len(alts) > 0:
            lines.append("  alternates: " + ", ".join(alts))
        pool = g.get("pool", [])
        if len(pool) > 0:
            lines.append("  free list:")
            k = 0
            while k < len(pool):
                lines.append("  " + _person_line(people[pool[k]], plans.get(pool[k], 0)))
                k += 1
        i += 1
    return "\n".join(lines)


def _fill_pools(groups, rooms, people, day):
    # each group with a no or a counter gets its free list: keen people in its break room
    # who haven't been asked today and whose profile has nothing against it, fewest plans first
    asked = {}
    g = 0
    while g < len(groups):
        m = 0
        while m < len(groups[g]["members"]):
            asked[groups[g]["members"][m]["id"]] = True
            m += 1
        g += 1
    g = 0
    while g < len(groups):
        group = groups[g]
        g += 1
        group["pool"] = []
        if group["status"] == "dropped" or not _has_open_answer(group):
            continue
        room = _room_for(rooms, group["activity"], group["part"])
        if room is None:
            continue
        activity = catalog.get(group["activity"])
        c = 0
        while c < len(room["candidates"]) and len(group["pool"]) < POOL_PER_GROUP:
            pid = room["candidates"][c]["id"]
            c += 1
            if pid in asked or pid in group["alternates"]:
                continue
            # a replacement takes a seat, so the same bar as members and alternates
            if main_keenness(people[pid], activity) < STRONG:
                continue
            if len(conflicts(people[pid], activity, group["part"], group["time"], day)) > 0:
                continue
            group["pool"].append(pid)


def _log_pools(run, groups, people):
    g = 0
    while g < len(groups):
        group = groups[g]
        g += 1
        if len(group["pool"]) == 0:
            continue
        names = []
        k = 0
        while k < len(group["pool"]):
            names.append(people[group["pool"][k]]["name"])
            k += 1
        run.log("code", "check", "Free list for " + group["id"] + " (" + catalog.get(group["activity"])["name"] +
                "), free, keen, not asked today, fewest plans first: " + ", ".join(names), group["id"])


def _has_open_answer(group):
    i = 0
    while i < len(group["members"]):
        if group["members"][i]["state"] in ("no", "counter"):
            return True
        i += 1
    return False


def _needs_another_round(groups, round_no):
    # someone asked in round_no said no or countered, and the group still has someone to ask
    g = 0
    while g < len(groups):
        group = groups[g]
        g += 1
        if group["status"] == "dropped":
            continue
        open_now = False
        t = 0
        while t < len(group["thread"]):
            entry = group["thread"][t]
            t += 1
            if entry["from"] == "agent" and entry["round"] == round_no:
                member = _member(group, entry["by"])
                if member is not None and member["state"] in ("no", "counter"):
                    open_now = True
        if not open_now:
            continue
        if len(group["pool"]) > 0:
            return True
        a = 0
        while a < len(group["alternates"]):
            if _member(group, group["alternates"][a]) is None:
                return True
            a += 1
    return False


def _message_system():
    return "\n".join([
        "You are the Clawnly matchmaker for " + catalog.NEIGHBORHOOD + ". Task: write the message each person receives now that their small group is confirmed (every person's agent said yes).",
        "This is the moment people find out who they're meeting, so make it feel specific and real, never salesy.",
        "For each person: 2-3 sentences. Say what, when and where, name the others by first name, and give one concrete reason from their profiles why they'll get along (a shared interest or stage of life). Only use what's in the profiles.",
        "Say two people share an interest only if WHAT THEY SHARE lists them both under it; people often like different things about the same activity.",
        "",
        'Reply with only this JSON object: {"headline": "one line for the whole group", "messages": {"person id": "the message"}}',
    ])


def _message_payload(group, day, people):
    a = catalog.get(group["activity"])
    lines = ["Activity: " + a["name"] + " at " + a["where"] + ", " + day_label(day) + ", " + group["time"] + ".", "", "THE GROUP:"]
    i = 0
    while i < len(group["final"]):
        lines.append("  " + group["final"][i] + " " + people[group["final"][i]]["brief"])
        i += 1
    lines.append("")
    lines.append("WHAT THEY SHARE (worked out by code from their likes):")
    shared = _shared_likes(group["final"], people)
    if len(shared) == 0:
        lines.append("  no like in common: give a reason from stage of life or the activity itself")
    i = 0
    while i < len(shared):
        lines.append("  " + shared[i])
        i += 1
    return "\n".join(lines)


def _shared_likes(ids, people):
    # every like held by at least two of these people, with who holds it, in tag order
    holders = {}
    order = []
    i = 0
    while i < len(ids):
        person = people[ids[i]]
        j = 0
        while j < len(person["likes"]):
            tag = person["likes"][j]["tag"]
            if tag not in holders:
                holders[tag] = []
                order.append(tag)
            if _first(person) not in holders[tag]:
                holders[tag].append(_first(person))
            j += 1
        i += 1
    out = []
    k = 0
    while k < len(order):
        if len(holders[order[k]]) >= 2:
            out.append(_words(order[k]) + ": " + ", ".join(holders[order[k]]))
        k += 1
    return out


# ----- the run --------------------------------------------------------------------

class _Run:
    """One day's run: the dict the page renders, plus the helpers that fill it."""

    def __init__(self, day, max_groups, client, on_progress):
        self.day = day
        self.client = client
        self.on_progress = on_progress
        self.data = {"day": day.isoformat(), "started": _now(), "finished": None, "maxGroups": str(max_groups),
                     "plan": None, "resolve": None, "groups": [], "log": [], "calls": [], "metrics": {"calls": {}},
                     "breakRoom": None, "status": "running"}

    def log(self, actor, kind, text, group_id=None):
        self.data["log"].append({"t": _now(), "actor": actor, "kind": kind, "text": text, "group": group_id})

    def progress(self):
        if self.on_progress is not None:
            self.on_progress(self.data)

    async def ask(self, kind, model, system, payload, max_tokens, effort):
        # one Claude call, kept word for word in the run (and in db.ai_calls by LoggedClient)
        started = time.monotonic()
        reply = None
        error = None
        ok = False
        try:
            message = await self.client.messages.create(
                model=model, max_tokens=max_tokens, system=system,
                output_config={"effort": effort},
                messages=[{"role": "user", "content": payload}],
            )
            reply = join_text(message)
            ok = True
            return extract_json(reply)
        except Exception as e:
            error = str(e)
            raise
        finally:
            ms = int((time.monotonic() - started) * 1000)
            calls = self.data["metrics"]["calls"]
            if kind not in calls:
                calls[kind] = {"n": 0, "ms": 0, "failed": 0}
            calls[kind]["n"] += 1
            calls[kind]["ms"] += ms
            if not ok:
                calls[kind]["failed"] += 1
            self.data["calls"].append({"t": _now(), "kind": kind, "tier": model, "ms": ms,
                                       "prompt": system + "\n\n" + payload, "reply": reply, "error": error})


def _in_room(room, person_id):
    i = 0
    while i < len(room["candidates"]):
        if room["candidates"][i]["id"] == person_id:
            return True
        i += 1
    return False


def _room_for(rooms, activity_id, part):
    i = 0
    while i < len(rooms):
        if rooms[i]["activity"] == activity_id and rooms[i]["part"] == part:
            return rooms[i]
        i += 1
    return None


def check_plan(raw, rooms, max_groups, people):
    # the matchmaker's plan, kept only where it follows the rules: (groups, rejected reasons)
    groups = []
    rejected = []
    taken = {}
    listed = []
    if isinstance(raw, dict) and isinstance(raw.get("groups"), list):
        listed = raw["groups"]
    i = 0
    while i < len(listed) and len(groups) < max_groups:
        r = listed[i]
        i += 1
        if not isinstance(r, dict):
            continue
        room = _room_for(rooms, str(r.get("activity", "")), str(r.get("part", "")))
        if room is None:
            rejected.append(str(r.get("activity")) + " " + str(r.get("part")) + ": no such break room that day")
            continue
        activity = catalog.get(room["activity"])
        members = []
        ids = r.get("members")
        if not isinstance(ids, list):
            ids = []
        j = 0
        while j < len(ids):
            pid = str(ids[j])
            j += 1
            if not _in_room(room, pid):
                who = pid
                if pid in people:
                    who = people[pid]["name"]
                rejected.append(who + " isn't in the " + activity["name"] + " break room")
                continue
            if pid in taken or pid in members:
                rejected.append(people[pid]["name"] + " was already in another group")
                continue
            why = no_seat(people[pid], activity)
            if why:
                rejected.append(why + ": no seat in " + activity["name"])
                continue
            members.append(pid)
        if len(members) < 2:
            rejected.append(activity["name"] + ": fewer than 2 valid people")
            continue
        alternates = []
        alts = r.get("alternates")
        if not isinstance(alts, list):
            alts = []
        k = 0
        while k < len(alts) and len(alternates) < 2:
            aid = str(alts[k])
            k += 1
            if not _in_room(room, aid) or aid in taken or aid in members or aid in alternates:
                continue
            # an alternate who steps in takes a seat, so the same bar applies
            why = no_seat(people[aid], activity)
            if why:
                rejected.append(why + ": not an alternate for " + activity["name"])
                continue
            alternates.append(aid)
        proposals = r.get("proposals")
        if not isinstance(proposals, dict):
            proposals = {}
        group = {"id": "g" + str(len(groups) + 1), "activity": room["activity"], "part": room["part"],
                 "time": str(r.get("time") or PART_HOURS[room["part"]]), "why": str(r.get("why") or ""),
                 "members": [], "alternates": alternates, "thread": [], "status": "negotiating", "magic": None}
        # a game or concert happens when it happens, whatever time the plan wrote
        fixed = fixed_time(activity, room["part"])
        if fixed is not None:
            group["fixed"] = True
            if group["time"] != fixed:
                group["plannedTime"] = group["time"]
                group["time"] = fixed
        elif not inside_part(group["time"], room["part"]):
            group["plannedTime"] = group["time"]
            group["time"] = PART_HOURS[room["part"]]
        m = 0
        while m < len(members):
            taken[members[m]] = group["id"]
            group["members"].append({"id": members[m], "state": "asked", "counter": "", "proposal": str(proposals.get(members[m]) or "")})
            m += 1
        groups.append(group)
    return groups, rejected


def _member(group, person_id):
    i = 0
    while i < len(group["members"]):
        if group["members"][i]["id"] == person_id:
            return group["members"][i]
        i += 1
    return None


def _yes(group):
    out = []
    i = 0
    while i < len(group["members"]):
        if group["members"][i]["state"] == "yes":
            out.append(group["members"][i]["id"])
        i += 1
    return out


async def _ask_agent(run, people, group, person_id, message, round_no, gate):
    async with gate:
        person = people[person_id]
        group["thread"].append({"t": _now(), "from": "hub", "to": person_id, "round": round_no, "text": message})
        member = _member(group, person_id)
        if member is None:
            member = {"id": person_id, "state": "asked", "counter": "", "proposal": message}
            group["members"].append(member)
        member["state"] = "asked"
        member["refused"] = ""
        try:
            r = await run.ask("agent reply", config.MODEL_REASONING, _agent_system(person),
                              _agent_payload(person, group, run.day, message), 4000, config.REASONING_EFFORT)
        except Exception as error:
            member["state"] = "no"
            group["thread"].append({"t": _now(), "from": "system", "round": round_no,
                                    "text": _first(person) + "'s agent didn't answer (" + str(error)[:80] + ")."})
            run.progress()
            return
        answer = "no"
        counter = ""
        say = ""
        reason = ""
        if isinstance(r, dict):
            answer = str(r.get("answer") or "no").lower()
            counter = str(r.get("counter") or "")
            say = str(r.get("say") or "")
            reason = str(r.get("reason") or "").strip()
        if answer != "yes" and answer != "counter":
            answer = "no"
        member["state"] = answer
        member["counter"] = counter
        group["thread"].append({"t": _now(), "from": "agent", "by": person_id, "round": round_no,
                                "answer": answer, "reason": reason, "counter": counter, "text": say})
        run.log("agent", "reply", _first(person) + "'s agent to the matchmaker: " + answer.upper() +
                " (" + catalog.get(group["activity"])["name"] + ")", group["id"])
        # the agent's yes is a claim; code takes it only if nothing in the profile rules the plan out
        if answer == "yes":
            refused = refusal(person, group, run.day, reason)
            if refused:
                member["state"] = "no"
                member["refused"] = refused
                group["thread"].append({"t": _now(), "from": "system", "round": round_no,
                                        "text": "Code turned " + _first(person) + "'s yes into a no: " + refused})
                run.log("code", "check", "Refused " + _first(person) + "'s yes to " + group["id"] + ": " + refused, group["id"])
        run.progress()


def refusal(person, group, day, reason):
    # why code won't take this yes, or "" when it stands
    found = conflicts(person, catalog.get(group["activity"]), group["part"], group["time"], day)
    if len(found) > 0:
        return found[0]
    if reason == "":
        return "the agent gave no reason from " + _first(person) + "'s profile."
    return ""


async def _ask_all(run, people, jobs):
    # jobs: [(group, person id, message, round)]; a few at a time
    gate = asyncio.Semaphore(AGENT_CONCURRENCY)
    await asyncio.gather(*[_ask_agent(run, people, j[0], j[1], j[2], j[3], gate) for j in jobs])


async def run_day(day, max_groups=10, people_list=None, client=None, on_progress=None, plans=None):
    # plans `day` for the neighborhood and returns the run dict. plans: {person id: how many plans
    # they already have this week}, so the matchmaker favors the people with fewer
    if people_list is None:
        people_list = demand_people(day)
    if plans is None:
        plans = {}
    people = _index(people_list)
    if client is None:
        client = config.get_client()
    run = _Run(day, max_groups, ai_log.LoggedClient(client), on_progress)
    data = run.data
    try:
        # 1. break rooms, in code
        rooms = demand.break_room(people_list, catalog.ACTIVITIES, day)
        rooms.sort(key=_room_strength, reverse=True)
        _fewest_plans_first(rooms, plans)
        in_any = {}
        usable = 0
        i = 0
        while i < len(rooms):
            j = 0
            while j < len(rooms[i]["candidates"]):
                in_any[rooms[i]["candidates"][j]["id"]] = True
                j += 1
            strong, others = split_room(rooms[i], people)
            if len(strong) >= 2:
                usable += 1
            i += 1
        data["breakRoom"] = {"slots": len(rooms), "people": len(in_any), "usable": usable}
        run.log("code", "check", "Built " + str(len(rooms)) + " break rooms for " + day_label(day) + " (one per activity and time of day); " +
                str(len(in_any)) + " of " + str(len(people_list)) + " neighbors are in at least one. " + str(usable) +
                " have at least 2 people with a strong interest in the main activity; only those can form a group.")
        already = 0
        ids = list(plans.keys())
        i = 0
        while i < len(ids):
            if ids[i] in people and plans[ids[i]] > 0:
                already += 1
            i += 1
        if already > 0:
            run.log("code", "check", "Neighbors who already have a plan this week: " + str(already) +
                    ". Each break room lists them after people with fewer.")
        run.progress()

        # 2. the plan
        raw = await run.ask("orchestrator plan", config.MODEL_PREMIUM, _plan_system(day, max_groups),
                            _plan_payload(rooms, people, plans), 16000, config.HUB_EFFORT)
        thoughts = ""
        if isinstance(raw, dict):
            thoughts = str(raw.get("thoughts") or "")
        data["plan"] = {"thoughts": thoughts}
        run.log("hub", "thought", "Matchmaker's plan: " + thoughts)
        groups, rejected = check_plan(raw, rooms, max_groups, people)
        r = 0
        while r < len(rejected):
            run.log("code", "check", "Rejected from the plan: " + rejected[r])
            r += 1
        data["groups"] = groups
        g = 0
        while g < len(groups):
            if groups[g].get("plannedTime") and groups[g].get("fixed"):
                run.log("code", "check", "Set " + groups[g]["id"] + " to the event's real time, " + groups[g]["time"] +
                        " (the plan said " + groups[g]["plannedTime"] + ").", groups[g]["id"])
            elif groups[g].get("plannedTime"):
                run.log("code", "check", "Set " + groups[g]["id"] + " to its " + groups[g]["part"] + ", " + groups[g]["time"] +
                        ": the plan's " + groups[g]["plannedTime"] + " is outside it, when nobody's calendar was checked.",
                        groups[g]["id"])
            run.log("hub", "decision", "Proposed " + groups[g]["id"] + ": " + catalog.get(groups[g]["activity"])["name"] + ", " +
                    groups[g]["time"] + ", " + str(len(groups[g]["members"])) + " people. " + groups[g]["why"], groups[g]["id"])
            g += 1
        run.progress()

        # 3. round 1: the matchmaker asks each agent, one to one
        jobs = []
        g = 0
        while g < len(groups):
            m = 0
            while m < len(groups[g]["members"]):
                member = groups[g]["members"][m]
                message = member["proposal"]
                if not message:
                    a = catalog.get(groups[g]["activity"])
                    message = a["name"] + ", " + day_label(day) + " " + groups[g]["time"] + " at " + a["where"] + ", with a few neighbors. In?"
                jobs.append((groups[g], member["id"], message, 1))
                m += 1
            g += 1
        await _ask_all(run, people, jobs)

        # 4-5. resolve counters and declines, then ask; again if a replacement said no
        data["resolve"] = {"thoughts": "", "rounds": []}
        round_no = 2
        while round_no <= LAST_ROUND:
            _fill_pools(groups, rooms, people, day)
            if round_no > 2 and not _needs_another_round(groups, round_no - 1):
                break
            _log_pools(run, groups, people)
            res = await run.ask("orchestrator resolve", config.MODEL_PREMIUM, _resolve_system(day),
                                _resolve_payload(groups, people, plans), 16000, config.HUB_EFFORT)
            thoughts = ""
            if isinstance(res, dict):
                thoughts = str(res.get("thoughts") or "")
            if round_no == 2:
                data["resolve"]["thoughts"] = thoughts
            data["resolve"]["rounds"].append({"round": round_no, "thoughts": thoughts})
            run.log("hub", "thought", "Matchmaker after round " + str(round_no - 1) + ": " + thoughts)
            jobs = _resolve_jobs(run, res, groups, people, round_no)
            run.progress()
            if len(jobs) == 0:
                break
            await _ask_all(run, people, jobs)
            round_no += 1

        # 6. lock, in code only
        g = 0
        while g < len(groups):
            group = groups[g]
            g += 1
            if group["status"] == "dropped":
                continue
            yes = _yes(group)
            if len(yes) >= 2:
                group["status"] = "locked"
                group["final"] = yes
                run.log("code", "check", "Locked " + group["id"] + ": " + catalog.get(group["activity"])["name"] + ", " + group["time"] +
                        ", " + str(len(yes)) + " people said yes.", group["id"])
            else:
                group["status"] = "dropped"
                group["dropReason"] = "only " + str(len(yes)) + " yes"
                run.log("code", "check", "Dropped " + group["id"] + ": only " + str(len(yes)) + " yes.", group["id"])
        run.progress()

        # 7. the message each person receives
        g = 0
        while g < len(groups):
            group = groups[g]
            g += 1
            if group["status"] != "locked":
                continue
            try:
                out = await run.ask("final message", config.MODEL_REASONING, _message_system(),
                                    _message_payload(group, day, people), 6000, config.REASONING_EFFORT)
            except Exception:
                continue
            headline = ""
            messages = {}
            if isinstance(out, dict):
                headline = str(out.get("headline") or "")
                if isinstance(out.get("messages"), dict):
                    messages = out["messages"]
            group["magic"] = {"headline": headline, "messages": messages}
            run.log("hub", "decision", "Sent " + group["id"] + "'s plan to " + str(len(group["final"])) + " people: " + headline, group["id"])
            run.progress()
        data["status"] = "done"
    except Exception as error:
        data["status"] = "failed"
        run.log("system", "system", "Run stopped: " + str(error)[:200])
    data["finished"] = _now()
    run.progress()
    return data


def _room_strength(room):
    total = 0
    i = 0
    while i < len(room["candidates"]):
        total += room["candidates"][i]["score"]
        i += 1
    return total


def _resolve_jobs(run, res, groups, people, round_no=2):
    # the matchmaker's asks for round_no, kept only where they follow the rules
    placed = {}
    g = 0
    while g < len(groups):
        yes = _yes(groups[g])
        y = 0
        while y < len(yes):
            placed[yes[y]] = groups[g]["id"]
            y += 1
        g += 1
    by_id = {}
    g = 0
    while g < len(groups):
        by_id[groups[g]["id"]] = groups[g]
        g += 1
    claimed = {}
    jobs = []
    decisions = []
    if isinstance(res, dict) and isinstance(res.get("groups"), list):
        decisions = res["groups"]
    d = 0
    while d < len(decisions):
        dec = decisions[d]
        d += 1
        if not isinstance(dec, dict) or dec.get("id") not in by_id:
            continue
        group = by_id[dec["id"]]
        name = catalog.get(group["activity"])["name"]
        if dec.get("keep") is False:
            group["status"] = "dropped"
            group["dropReason"] = "the matchmaker dropped it"
            run.log("hub", "decision", "Dropped " + group["id"] + " (" + name + ").", group["id"])
            continue
        moved = False
        if dec.get("time") and str(dec["time"]) != group["time"]:
            if group.get("fixed"):
                run.log("code", "check", "Kept " + group["id"] + " at " + group["time"] + ": " + name +
                        " is a real event, so the matchmaker can't move it to " + str(dec["time"]) + ".", group["id"])
            elif not inside_part(str(dec["time"]), group["part"]):
                run.log("code", "check", "Kept " + group["id"] + " at " + group["time"] + ": " + str(dec["time"]) +
                        " is outside the " + group["part"] + " (" + PART_HOURS[group["part"]] +
                        "), when nobody's calendar was checked.", group["id"])
            else:
                group["time"] = str(dec["time"])
                moved = True
                run.log("hub", "decision", group["id"] + " moves to " + group["time"] + ".", group["id"])
        asks = dec.get("ask")
        if not isinstance(asks, list):
            asks = []
        a = 0
        while a < len(asks):
            ask = asks[a]
            a += 1
            if not isinstance(ask, dict):
                continue
            pid = str(ask.get("id") or "")
            who = pid
            if pid in people:
                who = people[pid]["name"]
            if _member(group, pid) is None and pid not in group["alternates"] and pid not in group.get("pool", []):
                run.log("code", "check", "Rejected: the matchmaker tried to ask " + who + ", who isn't in " + group["id"] +
                        ", its alternates or its free list.")
                continue
            if pid in placed and placed[pid] != group["id"]:
                run.log("code", "check", "Rejected: " + who + " already said yes to " + placed[pid] + ".")
                continue
            # a yes to the same time is settled: asking again can only repeat it or undo it
            member = _member(group, pid)
            if member is not None and member["state"] == "yes" and not moved:
                run.log("code", "check", "Skipped asking " + who + " again: they already said yes to " + group["id"] +
                        " at this time, and everyone gets a confirmation after the lock.", group["id"])
                continue
            # one person is only ever asked for one group in a round
            if pid in claimed and claimed[pid] != group["id"]:
                run.log("code", "check", "Rejected: " + who + " is already being asked for " + claimed[pid] + ".")
                continue
            claimed[pid] = group["id"]
            jobs.append((group, pid, str(ask.get("message") or ""), round_no))
        # a yes to the old time isn't a yes to the new one: anyone the hub didn't re-ask, code does
        if moved:
            m = 0
            while m < len(group["members"]):
                member = group["members"][m]
                m += 1
                if member["state"] == "yes" and claimed.get(member["id"]) != group["id"]:
                    claimed[member["id"]] = group["id"]
                    run.log("code", "check", "Asking " + people[member["id"]]["name"] + " again: they said yes to " +
                            group["id"] + " before it moved to " + group["time"] + ".", group["id"])
                    jobs.append((group, member["id"], name + " has moved to " + group["time"] + ", " +
                                 day_label(run.day) + ". Does the new time still work?", round_no))
    return jobs


def demand_people(day):
    # the emulated neighborhood, with calendars starting on the planned day
    return population.generate(200, seed=7, start=day)
