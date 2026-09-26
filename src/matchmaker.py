"""Run Clawnly on the server: the matchmaker plans a day of small activity groups.

Hub and spoke, never agent to agent. For one day in the neighborhood:

  1. break rooms (code, demand.break_room): one per activity and time of day,
     holding every neighbor who is free, keen, can afford it and doesn't avoid it.
  2. plan (Opus): the matchmaker picks groups from the break rooms, with
     alternates and a personal proposal to each person's agent. Code keeps only
     people who are in that break room and never books anyone twice.
  3. round 1 (Sonnet, one call per agent): the matchmaker asks each agent one
     to one; the agent answers yes / no / counter from its person's brief and
     calendar only.
  4. resolve (Opus): accept counters by moving the time, call alternates. Code
     only lets it ask the group's own members or alternates, never someone who
     already said yes elsewhere, and never one person for two groups.
  5. round 2 (Sonnet): only the people the matchmaker re-asks.
  6. lock (code): a group goes ahead once at least 2 people said yes.
  7. the message (Sonnet): the one message each person receives.

The run is one plain dict -- the same shape the Run Clawnly page renders -- with
every hub<->agent message, every step in `log`, and every Claude call verbatim
in `calls` (also in db.ai_calls through ai_log.LoggedClient). on_progress(run)
is called after each step so the page can follow along live.
"""

import asyncio
import datetime
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
# the keenest people in a break room shown with their full profile; the rest by name
PROFILES_PER_ROOM = 15


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

def _person_line(p, score):
    likes = []
    i = 0
    while i < len(p["likes"]):
        likes.append(_words(p["likes"][i]["tag"]) + " " + str(p["likes"][i]["weight"]))
        i += 1
    kids = ""
    if p["kids_at_home"]:
        kids = ", kids at home"
    return ("  " + p["id"] + " " + p["name"] + " (" + str(p["age"]) + ", " + p["archetype"] + kids + ", " + p["area"] +
            "; keenness " + str(score) + "; likes " + ", ".join(likes) + ")")


def _plan_system(day, max_groups):
    return "\n".join([
        "You are the Clawnly matchmaker: the orchestrator for " + catalog.NEIGHBORHOOD + ". Task: plan the day's activity groups for " + day_label(day) + ".",
        "Each neighbor has told their own agent what they like, what they don't, and when they're free. You talk to each person's agent one to one. Agents never talk to each other. The goal is not friendship matching: it is a good small group doing something real together, so neighbors get to know each other.",
        "",
        "The break rooms were built by code: one per activity and time of day that can run that day, holding every neighbor who is free then, interested, can afford it and doesn't avoid anything about it (keenness = how much they'd want to, higher is better).",
        "",
        "Plan up to " + str(max_groups) + " groups:",
        "- Size each group to fit the activity and the people. You decide: two neighbors having a beer over the game is a group, and so is a bigger hike. Small groups are often where people actually meet each other.",
        "- Each person in at most one group. Use only people in that break room.",
        "- Prefer groups whose members share more than the activity (overlapping likes, similar stage of life), so they'd enjoy each other.",
        "- Spread plans across many people rather than stacking the keenest into one group.",
        "- Pick a specific time inside the day part (morning " + PART_HOURS["morning"] + ", afternoon " + PART_HOURS["afternoon"] + ", evening " + PART_HOURS["evening"] + ").",
        "- Name up to 2 alternates per group from the same break room, in case someone declines.",
        "- Write a short, personal proposal to each member's agent: what, when, where, how many others, and why it fits this person. Don't name the other people yet.",
        "",
        "Reply with only this JSON object:",
        '{"thoughts": "your reasoning about the day, 3-6 sentences", "groups": [{"activity": "activity id", "part": "morning|afternoon|evening", "time": "e.g. 10:30am-12pm", "members": ["person id"], "alternates": ["person id"], "why": "one sentence: why this group", "proposals": {"person id": "the message to that person\'s agent"}}]}',
    ])


def _plan_payload(rooms, people):
    lines = ["BREAK ROOMS:"]
    i = 0
    while i < len(rooms):
        room = rooms[i]
        a = catalog.get(room["activity"])
        lines.append("")
        lines.append("[" + a["id"] + " | " + room["part"] + "] " + a["name"] + " at " + a["where"] + " (cost " + a["cost"] + ", " +
                     str(len(room["candidates"])) + " in the room)")
        rest = []
        j = 0
        while j < len(room["candidates"]):
            c = room["candidates"][j]
            if j < PROFILES_PER_ROOM:
                lines.append(_person_line(people[c["id"]], c["score"]))
            else:
                rest.append(c["id"] + " " + _first(people[c["id"]]) + " (" + str(c["score"]) + ")")
            j += 1
        if len(rest) > 0:
            lines.append("  also in the room: " + ", ".join(rest))
        i += 1
    return "\n".join(lines)


def _agent_system(person):
    first = _first(person)
    return "\n".join([
        "You are the personal agent of " + person["name"] + ". You know " + first + " only from what they told you and their calendar. You speak for " + first + " to the Clawnly matchmaker. You never talk to other people's agents.",
        "",
        "What " + first + " told you: " + person["brief"],
        "",
        "Decide for " + first + ': "yes" if it fits, "no" if it clearly doesn\'t, or "counter" with one concrete change that would make it a yes (a different time within a day part they\'re free, for example). Be realistic: people are busy and choosy, so not everything they like is a yes.',
        'Reply with only this JSON object: {"answer": "yes" or "no" or "counter", "counter": "the change, if any", "say": "one or two sentences to the matchmaker, as ' + first + "'s agent\"}",
    ])


def _agent_payload(person, group, day, message):
    a = catalog.get(group["activity"])
    free = person["calendar"].get(day.isoformat(), [])
    free_text = "nothing"
    if len(free) > 0:
        free_text = ", ".join(free)
    return "\n".join([
        _first(person) + " is free on " + day_label(day) + ": " + free_text + ".",
        "The matchmaker proposes: " + a["name"] + " at " + a["where"] + ", " + day_label(day) + ", " + group["time"] + " (" + group["part"] +
        "), cost " + a["cost"] + ", a small group of neighbors.",
        "The matchmaker's message: " + message,
    ])


def _resolve_system(day):
    return "\n".join([
        "You are the Clawnly matchmaker for " + catalog.NEIGHBORHOOD + ", " + day_label(day) + ". Task: finish the day's plan after each person's agent answered you privately.",
        "For each group: keep it if at least 2 people can do it. Accept a counter by moving the time if that still works for the ones who said yes (then re-ask them with the new time). Replace people who said no with alternates (ask them). Drop a group that can't reach 2.",
        "Never add anyone who is already in another group. Only ask the group's own members or its alternates.",
        "",
        "Reply with only this JSON object:",
        '{"thoughts": "your reasoning, 2-5 sentences", "groups": [{"id": "group id", "keep": true or false, "time": "final time", "ask": [{"id": "person id", "message": "what you say to their agent now"}]}]}',
    ])


def _resolve_payload(groups, people):
    lines = ["GROUPS:"]
    i = 0
    while i < len(groups):
        g = groups[i]
        a = catalog.get(g["activity"])
        lines.append("")
        lines.append(g["id"] + ": " + a["name"] + ", " + g["time"] + " (" + g["part"] + ")")
        j = 0
        while j < len(g["members"]):
            m = g["members"][j]
            said = m["state"]
            if m["counter"]:
                said = said + " (" + m["counter"] + ")"
            lines.append("  " + m["id"] + " " + people[m["id"]]["name"] + ": " + said)
            j += 1
        alts = []
        k = 0
        while k < len(g["alternates"]):
            alts.append(g["alternates"][k] + " " + people[g["alternates"][k]]["name"])
            k += 1
        if len(alts) > 0:
            lines.append("  alternates: " + ", ".join(alts))
        i += 1
    return "\n".join(lines)


def _message_system():
    return "\n".join([
        "You are the Clawnly matchmaker for " + catalog.NEIGHBORHOOD + ". Task: write the message each person receives now that their small group is confirmed (every person's agent said yes).",
        "This is the moment people find out who they're meeting, so make it feel specific and real, never salesy.",
        "For each person: 2-3 sentences. Say what, when and where, name the others by first name, and give one concrete reason from their profiles why they'll get along (a shared interest or stage of life). Only use what's in the profiles.",
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
    return "\n".join(lines)


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
            if _in_room(room, aid) and aid not in taken and aid not in members:
                alternates.append(aid)
        proposals = r.get("proposals")
        if not isinstance(proposals, dict):
            proposals = {}
        group = {"id": "g" + str(len(groups) + 1), "activity": room["activity"], "part": room["part"],
                 "time": str(r.get("time") or PART_HOURS[room["part"]]), "why": str(r.get("why") or ""),
                 "members": [], "alternates": alternates, "thread": [], "status": "negotiating", "magic": None}
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
        if isinstance(r, dict):
            answer = str(r.get("answer") or "no").lower()
            counter = str(r.get("counter") or "")
            say = str(r.get("say") or "")
        if answer != "yes" and answer != "counter":
            answer = "no"
        member["state"] = answer
        member["counter"] = counter
        group["thread"].append({"t": _now(), "from": "agent", "by": person_id, "round": round_no,
                                "answer": answer, "counter": counter, "text": say})
        run.log("agent", "reply", _first(person) + "'s agent to the matchmaker: " + answer.upper() +
                " (" + catalog.get(group["activity"])["name"] + ")", group["id"])
        run.progress()


async def _ask_all(run, people, jobs):
    # jobs: [(group, person id, message, round)]; a few at a time
    gate = asyncio.Semaphore(AGENT_CONCURRENCY)
    await asyncio.gather(*[_ask_agent(run, people, j[0], j[1], j[2], j[3], gate) for j in jobs])


async def run_day(day, max_groups=10, people_list=None, client=None, on_progress=None):
    # plans `day` for the neighborhood and returns the run dict
    if people_list is None:
        people_list = demand_people(day)
    people = _index(people_list)
    if client is None:
        client = config.get_client()
    run = _Run(day, max_groups, ai_log.LoggedClient(client), on_progress)
    data = run.data
    try:
        # 1. break rooms, in code
        rooms = demand.break_room(people_list, catalog.ACTIVITIES, day)
        rooms.sort(key=_room_strength, reverse=True)
        in_any = {}
        i = 0
        while i < len(rooms):
            j = 0
            while j < len(rooms[i]["candidates"]):
                in_any[rooms[i]["candidates"][j]["id"]] = True
                j += 1
            i += 1
        data["breakRoom"] = {"slots": len(rooms), "people": len(in_any)}
        run.log("code", "check", "Built " + str(len(rooms)) + " break rooms for " + day_label(day) + " (one per activity and time of day); " +
                str(len(in_any)) + " of " + str(len(people_list)) + " neighbors are in at least one.")
        run.progress()

        # 2. the plan
        raw = await run.ask("orchestrator plan", config.MODEL_PREMIUM, _plan_system(day, max_groups),
                            _plan_payload(rooms, people), 16000, config.HUB_EFFORT)
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

        # 4. resolve counters and declines
        res = await run.ask("orchestrator resolve", config.MODEL_PREMIUM, _resolve_system(day),
                            _resolve_payload(groups, people), 16000, config.HUB_EFFORT)
        thoughts = ""
        if isinstance(res, dict):
            thoughts = str(res.get("thoughts") or "")
        data["resolve"] = {"thoughts": thoughts}
        run.log("hub", "thought", "Matchmaker after round 1: " + thoughts)
        jobs = _resolve_jobs(run, res, groups, people)
        run.progress()
        # 5. round 2
        if len(jobs) > 0:
            await _ask_all(run, people, jobs)

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


def _resolve_jobs(run, res, groups, people):
    # the matchmaker's round-2 asks, kept only where they follow the rules
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
        if dec.get("time") and str(dec["time"]) != group["time"]:
            group["time"] = str(dec["time"])
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
            if _member(group, pid) is None and pid not in group["alternates"]:
                run.log("code", "check", "Rejected: the matchmaker tried to ask " + who + ", who isn't in " + group["id"] + " or its alternates.")
                continue
            if pid in placed and placed[pid] != group["id"]:
                run.log("code", "check", "Rejected: " + who + " already said yes to " + placed[pid] + ".")
                continue
            # one person is only ever asked for one group in a round
            if pid in claimed and claimed[pid] != group["id"]:
                run.log("code", "check", "Rejected: " + who + " is already being asked for " + claimed[pid] + ".")
                continue
            claimed[pid] = group["id"]
            jobs.append((group, pid, str(ask.get("message") or ""), 2))
    return jobs


def demand_people(day):
    # the emulated neighborhood, with calendars starting on the planned day
    return population.generate(200, seed=7, start=day)
