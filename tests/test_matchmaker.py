"""Run Clawnly on the server (matchmaker.py): the hub plans a day of activity
groups by talking to each person's agent one to one. Offline, via FakeClient."""

import datetime
import json

import catalog
import config
import db
import demand
import matchmaker
import population
from conftest import FakeClient, reset_db, run

DAY = datetime.date(2026, 9, 27)
# a time inside each day part, and a later one still inside it
INSIDE = {"morning": "10am-12pm", "afternoon": "1-3pm", "evening": "6-8pm"}
LATER = {"morning": "10:30am-12pm", "afternoon": "1:30-3:30pm", "evening": "6:30-8:30pm"}


def town():
    return population.generate(200, seed=7, start=DAY)


def rooms_for(people):
    return demand.break_room(people, catalog.ACTIVITIES, DAY)


def two_group_plan(rooms):
    # the first two break rooms, three people each, one alternate each
    groups = []
    used = set()
    for room in rooms:
        ids = [c["id"] for c in room["candidates"] if c["id"] not in used]
        if len(ids) < 4:
            continue
        members = ids[:3]
        used.update(ids[:4])
        groups.append({"activity": room["activity"], "part": room["part"], "time": INSIDE[room["part"]],
                       "members": members, "alternates": [ids[3]], "why": "shared interests",
                       "proposals": {pid: "Hi, " + room["activity"] + " tomorrow?" for pid in members}})
        if len(groups) == 2:
            break
    return {"thoughts": "Two strong rooms today.", "groups": groups}


def says(answer, counter=""):
    return lambda system, content: json.dumps({"answer": answer, "reason": "loves it", "counter": counter, "say": "noted"})


def keep_all(system, content):
    return json.dumps({"thoughts": "Both groups hold.", "groups": [{"id": "g1", "keep": True, "ask": []},
                                                                  {"id": "g2", "keep": True, "ask": []}]})


def welcome(system, content):
    return json.dumps({"headline": "See you there", "messages": {}})


def fake(plan, agent=None, resolve=keep_all, message=welcome):
    if agent is None:
        agent = says("yes")
    return FakeClient(matchmaker={"mm_plan": lambda s, c: json.dumps(plan), "mm_agent": agent,
                                  "mm_resolve": resolve, "mm_message": message})


def test_a_day_runs_hub_and_spoke_and_locks_groups():
    reset_db()
    people = town()
    plan = two_group_plan(rooms_for(people))
    client = fake(plan)
    seen = []
    data = run(matchmaker.run_day(DAY, 5, people, client, on_progress=lambda d: seen.append(d["status"])))

    assert data["status"] == "done"
    assert [g["status"] for g in data["groups"]] == ["locked", "locked"]
    assert len(data["groups"][0]["final"]) == 3
    assert data["groups"][0]["magic"]["headline"] == "See you there"
    # every conversation is hub <-> one agent: 6 asks, 6 replies, never agent to agent
    thread = data["groups"][0]["thread"] + data["groups"][1]["thread"]
    assert len([m for m in thread if m["from"] == "hub"]) == 6
    assert len([m for m in thread if m["from"] == "agent"]) == 6
    assert client.kinds().count("mm_agent") == 6
    assert client.kinds()[0] == "mm_plan"
    assert "mm_resolve" in client.kinds()
    assert client.kinds().count("mm_message") == 2
    # live progress was reported along the way, ending done
    assert len(seen) > 4
    assert seen[-1] == "done"
    assert data["breakRoom"]["slots"] == len(rooms_for(people))


def test_every_call_is_kept_verbatim_in_the_run_and_the_db():
    reset_db()
    people = town()
    client = fake(two_group_plan(rooms_for(people)))
    data = run(matchmaker.run_day(DAY, 5, people, client))
    assert len(data["calls"]) == len(client.calls)
    assert data["calls"][0]["kind"] == "orchestrator plan"
    assert "BREAK ROOMS" in data["calls"][0]["prompt"]
    assert data["calls"][0]["reply"] is not None
    purposes = [r["purpose"] for r in db._get_conn().execute("SELECT purpose FROM ai_calls").fetchall()]
    assert "matchmaker_plan" in purposes
    assert "matchmaker_agent" in purposes
    assert "matchmaker_resolve" in purposes
    assert "matchmaker_message" in purposes


def test_models_opus_for_the_hub_and_sonnet_for_agents_no_temperature():
    reset_db()
    people = town()
    client = fake(two_group_plan(rooms_for(people)))
    run(matchmaker.run_day(DAY, 5, people, client))
    for kind, kwargs in client.calls:
        assert "temperature" not in kwargs
        assert kwargs["output_config"]["effort"]
        if kind in ("mm_plan", "mm_resolve"):
            assert kwargs["model"] == config.MODEL_PREMIUM
        else:
            assert kwargs["model"] == config.MODEL_REASONING


def test_agents_never_see_other_people():
    reset_db()
    people = town()
    plan = two_group_plan(rooms_for(people))
    client = fake(plan)
    run(matchmaker.run_day(DAY, 5, people, client))
    names = {p["id"]: p["name"] for p in people}
    for kind, kwargs in client.calls:
        if kind != "mm_agent":
            continue
        text = kwargs["system"] + kwargs["messages"][0]["content"]
        me = [pid for pid in names if ("personal agent of " + names[pid] + ".") in kwargs["system"]]
        assert len(me) == 1
        for group in plan["groups"]:
            for pid in group["members"]:
                if pid != me[0]:
                    assert pid not in text


def test_code_rejects_people_outside_the_room_and_double_booking():
    people = town()
    rooms = rooms_for(people)
    index = {p["id"]: p for p in people}
    first = rooms[0]
    inside = [c["id"] for c in first["candidates"]]
    outside = [p["id"] for p in people if p["id"] not in inside][0]
    # another room that shares someone with the first
    other = None
    shared = None
    for r in rooms[1:]:
        both = [c["id"] for c in r["candidates"] if c["id"] in inside[:2]]
        rest = [c["id"] for c in r["candidates"] if c["id"] not in inside]
        if both and rest:
            other, shared = r, both[0]
            break
    assert other is not None
    raw = {"groups": [
        {"activity": first["activity"], "part": first["part"], "members": inside[:2] + [outside]},
        {"activity": "moon-walk", "part": "morning", "members": inside[:3]},
        {"activity": other["activity"], "part": other["part"], "members": [shared, rest[0]]},
    ]}
    groups, rejected = matchmaker.check_plan(raw, rooms, 10, index)
    assert len(groups) == 1
    assert [m["id"] for m in groups[0]["members"]] == inside[:2]
    assert any("isn't in the" in r for r in rejected)
    assert any("no such break room" in r for r in rejected)
    assert any("already in another group" in r for r in rejected)
    assert any("fewer than 2" in r for r in rejected)


def test_no_upper_size_limit_but_max_groups_is_respected():
    people = town()
    rooms = rooms_for(people)
    index = {p["id"]: p for p in people}
    big = [c["id"] for c in rooms[0]["candidates"]][:9]
    raw = {"groups": [{"activity": rooms[0]["activity"], "part": rooms[0]["part"], "members": big}]}
    groups, rejected = matchmaker.check_plan(raw, rooms, 10, index)
    assert len(groups[0]["members"]) == 9
    groups, rejected = matchmaker.check_plan(two_group_plan(rooms), rooms, 1, index)
    assert len(groups) == 1


def test_a_group_with_one_yes_is_dropped_by_code():
    reset_db()
    people = town()
    plan = two_group_plan(rooms_for(people))
    lone = plan["groups"][0]["members"][0]
    names = {p["id"]: p["name"] for p in people}

    def agent(system, content):
        if ("personal agent of " + names[lone] + ".") in system:
            return json.dumps({"answer": "yes", "reason": "loves it", "say": "in"})
        if any(("personal agent of " + names[m] + ".") in system for m in plan["groups"][0]["members"]):
            return json.dumps({"answer": "no", "say": "busy"})
        return json.dumps({"answer": "yes", "reason": "loves it", "say": "in"})

    data = run(matchmaker.run_day(DAY, 5, people, fake(plan, agent=agent)))
    assert data["groups"][0]["status"] == "dropped"
    assert data["groups"][0]["dropReason"] == "only 1 yes"
    assert data["groups"][1]["status"] == "locked"
    assert any(e["kind"] == "check" and e["text"].startswith("Dropped g1") for e in data["log"])


def test_round_two_only_asks_members_or_alternates_and_never_a_yes_elsewhere():
    reset_db()
    people = town()
    rooms = rooms_for(people)
    plan = two_group_plan(rooms)
    g1 = plan["groups"][0]
    g2 = plan["groups"][1]
    # someone in both break rooms: a g2 member who is also g1's second alternate
    room1 = [r for r in rooms if r["activity"] == g1["activity"] and r["part"] == g1["part"]][0]
    room2 = [r for r in rooms if r["activity"] == g2["activity"] and r["part"] == g2["part"]][0]
    in1 = {c["id"] for c in room1["candidates"]}
    used = set(g1["members"] + g1["alternates"] + g2["members"] + g2["alternates"])
    both = [c["id"] for c in room2["candidates"] if c["id"] in in1 and c["id"] not in used][0]
    g2["members"][0] = both
    g2["proposals"][both] = "join?"
    g1["alternates"].append(both)
    names = {p["id"]: p["name"] for p in people}
    outsider = [p["id"] for p in people if p["id"] not in g1["members"] + g1["alternates"] + g2["members"] + g2["alternates"]][0]
    no_one = g1["members"][0]

    def agent(system, content):
        if ("personal agent of " + names[no_one] + ".") in system:
            return json.dumps({"answer": "no", "say": "can't"})
        return json.dumps({"answer": "yes", "reason": "loves it", "say": "in"})

    def resolve(system, content):
        return json.dumps({"thoughts": "swap in the alternate", "groups": [
            {"id": "g1", "keep": True, "time": LATER[g1["part"]], "ask": [
                {"id": g1["alternates"][0], "message": "a spot opened"},
                {"id": outsider, "message": "join?"},
                {"id": g2["members"][0], "message": "switch groups?"},
            ]},
            {"id": "g2", "keep": True, "ask": []},
        ]})

    client = fake(plan, agent=agent, resolve=resolve)
    data = run(matchmaker.run_day(DAY, 5, people, client))
    group = data["groups"][0]
    assert group["time"] == LATER[g1["part"]]
    assert g1["alternates"][0] in group["final"]
    assert outsider not in group["final"]
    assert g2["members"][0] not in group["final"]
    checks = [e["text"] for e in data["log"] if e["kind"] == "check"]
    assert any("isn't in g1 or its alternates" in c for c in checks)
    assert any("already said yes to g2" in c for c in checks)
    # 6 round-one asks + the one valid round-two ask + the 2 yeses code re-asks because the time moved
    assert client.kinds().count("mm_agent") == 9
    assert len([c for c in checks if c.startswith("Asking ") and "before it moved" in c]) == 2


def test_a_counter_is_recorded_and_a_failed_agent_counts_as_no():
    reset_db()
    people = town()
    plan = two_group_plan(rooms_for(people))
    names = {p["id"]: p["name"] for p in people}
    broken = plan["groups"][1]["members"][0]
    countering = plan["groups"][0]["members"][1]

    def agent(system, content):
        if ("personal agent of " + names[broken] + ".") in system:
            raise RuntimeError("overloaded")
        if ("personal agent of " + names[countering] + ".") in system:
            return json.dumps({"answer": "counter", "counter": "after 11", "say": "later works"})
        return json.dumps({"answer": "yes", "reason": "loves it", "say": "in"})

    data = run(matchmaker.run_day(DAY, 5, people, fake(plan, agent=agent)))
    member = [m for m in data["groups"][0]["members"] if m["id"] == countering][0]
    assert member["state"] == "counter"
    assert member["counter"] == "after 11"
    failed = [m for m in data["groups"][1]["members"] if m["id"] == broken][0]
    assert failed["state"] == "no"
    assert data["metrics"]["calls"]["agent reply"]["failed"] == 1
    assert data["status"] == "done"


def test_a_failed_plan_stops_the_run_and_says_why():
    reset_db()
    people = town()

    def boom(system, content):
        raise RuntimeError("api down")

    client = FakeClient(matchmaker={"mm_plan": boom})
    data = run(matchmaker.run_day(DAY, 5, people, client))
    assert data["status"] == "failed"
    assert "api down" in data["log"][-1]["text"]
    assert data["calls"][0]["error"] == "api down"
    assert data["finished"] is not None


def test_only_one_run_at_a_time_and_a_stale_one_is_released():
    reset_db()
    first = db.claim_matchmaker_run("2026-09-27", "admin@example.com", 600)
    assert first is not None
    assert db.claim_matchmaker_run("2026-09-27", "admin@example.com", 600) is None
    # a run that hasn't saved progress for longer than the window is dead (the app restarted)
    db._get_conn().execute("UPDATE matchmaker_runs SET updated_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (first,))
    second = db.claim_matchmaker_run("2026-09-27", "admin@example.com", 600)
    assert second is not None
    assert db.get_matchmaker_run(first)["status"] == "failed"
    db.save_matchmaker_run(second, {"status": "done", "groups": []})
    latest = db.latest_matchmaker_run()
    assert latest["id"] == second
    assert latest["status"] == "done"


# ----- Idan's changes: agents can say no, real event times, a smaller plan ---------

def test_parse_hours_reads_the_times_plans_use():
    assert matchmaker.parse_hours("10:30am-12pm") == (10.5, 12.0)
    assert matchmaker.parse_hours("12-5pm") == (12.0, 17.0)
    assert matchmaker.parse_hours("5:20pm-8:30pm") == (17 + 20 / 60, 20.5)
    assert matchmaker.parse_hours("morning") is None


def test_the_agent_sees_the_full_profile_and_the_whole_week():
    person = town()[0]
    system = matchmaker._agent_system(person)
    for word in person["dislikes"] + person["avoid"]:
        assert word.replace("_", " ") in system
    assert "Budget:" in system
    for day in person["calendar"]:
        assert matchmaker.day_label(datetime.date.fromisoformat(day)) in system
    assert "Saying no is normal" in system


def test_code_flags_what_argues_against_a_plan():
    person = dict(town()[0], avoid=["early_mornings", "late_nights"], budget="free",
                  likes=[{"tag": "fishing", "weight": 1}], dislikes=[])
    day = datetime.date.fromisoformat(sorted(person["calendar"])[0])
    person["calendar"] = {day.isoformat(): ["morning"]}
    early = matchmaker.plan_checks(person, catalog.get("sawyer-fishing"), "morning", "7:30am-9am", day)
    assert any("starts before 9am" in c for c in early)
    assert any("only up for it" in c for c in early)
    later = matchmaker.plan_checks(person, catalog.get("sawyer-fishing"), "morning", "9:30am-11am", day)
    assert not any("before 9am" in c for c in later)
    busy = matchmaker.plan_checks(person, catalog.get("golf"), "afternoon", "1pm-3pm", day)
    assert any("busy that afternoon" in c for c in busy)
    assert any("budget" in c for c in busy)
    assert any("never said they like" in c for c in busy)


def test_agents_get_what_code_found_with_the_proposal():
    reset_db()
    people = town()
    plan = two_group_plan(rooms_for(people))
    client = fake(plan)
    run(matchmaker.run_day(DAY, 5, people, client))
    payloads = [kwargs["messages"][0]["content"] for kind, kwargs in client.calls if kind == "mm_agent"]
    assert all("What code found in" in p for p in payloads)


def test_events_keep_their_real_time_whatever_the_plan_says():
    people = town()
    index = {p["id"]: p for p in people}
    rooms = rooms_for(people)
    room = [r for r in rooms if r["activity"] == "seahawks"][0]
    real = catalog.get("seahawks")["fixed"][room["part"]]
    ids = [c["id"] for c in room["candidates"]][:3]
    raw = {"groups": [{"activity": "seahawks", "part": room["part"], "time": "11am-1pm", "members": ids}]}
    groups, rejected = matchmaker.check_plan(raw, rooms, 5, index)
    assert groups[0]["time"] == real
    assert groups[0]["fixed"] is True
    assert groups[0]["plannedTime"] == "11am-1pm"


def test_the_matchmaker_cannot_move_an_event_in_round_two():
    reset_db()
    people = town()
    rooms = rooms_for(people)
    room = [r for r in rooms if r["activity"] == "seahawks"][0]
    ids = [c["id"] for c in room["candidates"]]
    plan = {"thoughts": "game day", "groups": [{"activity": "seahawks", "part": room["part"], "time": "whenever",
                                                 "members": ids[:3], "alternates": [], "proposals": {}}]}

    def resolve(system, content):
        return json.dumps({"thoughts": "move it", "groups": [{"id": "g1", "keep": True, "time": "9am-10am", "ask": []}]})

    data = run(matchmaker.run_day(DAY, 5, people, fake(plan, resolve=resolve)))
    real = catalog.get("seahawks")["fixed"][room["part"]]
    assert data["groups"][0]["time"] == real
    checks = [e["text"] for e in data["log"] if e["kind"] == "check"]
    assert any("to the event's real time" in c for c in checks)
    assert any("can't move it to 9am-10am" in c for c in checks)


def test_the_plan_lists_each_person_once_and_stays_small():
    people = town()
    index = {p["id"]: p for p in people}
    rooms = rooms_for(people)
    payload = matchmaker._plan_payload(rooms, index)
    profiled = [line.split()[0] for line in payload.split("PEOPLE:")[1].splitlines() if line.strip()]
    assert len(profiled) == len(set(profiled))
    # every room that can form a group still names everyone in it, so nobody is left out of the plan
    for room in rooms:
        if len(matchmaker.split_room(room, index)[0]) < 2:
            continue
        for c in room["candidates"]:
            assert c["id"] in payload
    # under half of what it was before the trim (65,000 characters for this day). It grew from
    # 25,000 when each keen person's liked tags and everyone's avoids were added: without them the
    # hub called five beer fans "trivia-keen" (simulation_results/runs/run_20261029_023732_pilot)
    assert len(matchmaker._plan_system(DAY, 10) + payload) < 32000


def test_the_plan_shows_why_each_keen_person_is_in_the_room_and_what_they_avoid():
    people = town()
    index = {p["id"]: p for p in people}
    rooms = rooms_for(people)
    payload = matchmaker._plan_payload(rooms, index)
    room = rooms[0]
    first = room["candidates"][0]
    activity = catalog.get(room["activity"])
    liked = [like["tag"].replace("_", " ") for like in index[first["id"]]["likes"] if like["tag"] in activity["tags"]]
    assert first["id"] + ":" + str(first["score"]) + " [" + ", ".join(liked) + "]" in payload
    avoider = next(p for p in people if p["avoid"] and p["id"] + " " in payload.split("PEOPLE:")[1])
    line = [l for l in payload.split("PEOPLE:")[1].splitlines() if l.strip().startswith(avoider["id"] + " ")][0]
    assert "avoids " + avoider["avoid"][0].replace("_", " ") in line


def test_round_two_never_re_asks_a_yes_to_an_unchanged_time():
    reset_db()
    people = town()
    plan = two_group_plan(rooms_for(people))
    g1 = plan["groups"][0]

    def resolve(system, content):
        return json.dumps({"thoughts": "Confirm everyone.", "groups": [
            {"id": "g1", "keep": True, "ask": [{"id": pid, "message": "Confirmed!"} for pid in g1["members"]]},
            {"id": "g2", "keep": True, "ask": []}]})

    client = fake(plan, resolve=resolve)
    data = run(matchmaker.run_day(DAY, 5, people, client))
    # 6 round-one asks and no confirmations: each yes stands, and the confirmation comes after the lock
    assert client.kinds().count("mm_agent") == 6
    skipped = [e["text"] for e in data["log"] if e["text"].startswith("Skipped asking")]
    assert len(skipped) == 3
    assert data["groups"][0]["status"] == "locked"


def test_a_moved_time_still_re_asks_the_yeses():
    reset_db()
    people = town()
    plan = two_group_plan(rooms_for(people))
    g1 = plan["groups"][0]

    def resolve(system, content):
        return json.dumps({"thoughts": "Later.", "groups": [
            {"id": "g1", "keep": True, "time": LATER[g1["part"]], "ask": [{"id": pid, "message": "A bit later?"} for pid in g1["members"]]},
            {"id": "g2", "keep": True, "ask": []}]})

    client = fake(plan, resolve=resolve)
    run(matchmaker.run_day(DAY, 5, people, client))
    assert client.kinds().count("mm_agent") == 9


def test_the_message_writer_gets_what_the_group_really_shares():
    people = town()
    index = {p["id"]: p for p in people}
    pair = [p for p in people if any(l["tag"] == "hiking" for l in p["likes"])][:2]
    group = {"activity": "gorge", "time": "9am-12pm", "final": [pair[0]["id"], pair[1]["id"]]}
    payload = matchmaker._message_payload(group, DAY, index)
    assert "WHAT THEY SHARE" in payload
    first = [p["name"].split(" ")[0] for p in pair]
    assert "hiking: " + first[0] + ", " + first[1] in payload
    assert "WHAT THEY SHARE lists them both" in matchmaker._message_system()


def test_a_time_outside_the_day_part_is_refused_in_the_plan_and_in_round_two():
    reset_db()
    people = town()
    plan = two_group_plan(rooms_for(people))
    g1 = plan["groups"][0]
    outside = {"morning": "7-9pm", "afternoon": "8-10am", "evening": "8-10am"}[g1["part"]]
    g1["time"] = outside

    def resolve(system, content):
        return json.dumps({"thoughts": "Move it.", "groups": [{"id": "g1", "keep": True, "time": outside, "ask": []},
                                                            {"id": "g2", "keep": True, "ask": []}]})

    client = fake(plan, resolve=resolve)
    data = run(matchmaker.run_day(DAY, 5, people, client))
    group = data["groups"][0]
    # calendars are checked per day part: the plan's time gives way to the part's hours, and stays there
    assert group["time"] == matchmaker.PART_HOURS[g1["part"]]
    checks = [e["text"] for e in data["log"] if e["kind"] == "check"]
    assert any(c.startswith("Set g1 to its " + g1["part"]) for c in checks)
    assert any(c.startswith("Kept g1 at") and "outside the " + g1["part"] in c for c in checks)
    assert client.kinds().count("mm_agent") == 6


def test_a_moved_time_the_hub_forgets_to_re_ask_is_re_asked_by_code():
    reset_db()
    people = town()
    plan = two_group_plan(rooms_for(people))
    g1 = plan["groups"][0]

    def resolve(system, content):
        return json.dumps({"thoughts": "Later.", "groups": [{"id": "g1", "keep": True, "time": LATER[g1["part"]], "ask": []},
                                                            {"id": "g2", "keep": True, "ask": []}]})

    client = fake(plan, resolve=resolve)
    data = run(matchmaker.run_day(DAY, 5, people, client))
    assert client.kinds().count("mm_agent") == 9
    second = [m for m in data["groups"][0]["thread"] if m["from"] == "hub" and m["round"] == 2]
    assert len(second) == 3
    assert "has moved to " + LATER[g1["part"]] in second[0]["text"]


def test_the_agent_holds_what_the_person_avoids_as_a_limit():
    person = town()[0]
    assert "is a limit they set, not a preference to trade off" in matchmaker._agent_system(person)


# ----- the team's fixes after the 200 live groups -------------------------------------

def strong_ids(room, index):
    return [c["id"] for c in matchmaker.split_room(room, index)[0]]


def evening_room(people, index):
    # an evening room with a movable time, no late-night trait, and three people who really want it
    for room in rooms_for(people):
        activity = catalog.get(room["activity"])
        if room["part"] != "evening" or matchmaker.fixed_time(activity, "evening") is not None:
            continue
        if "late_nights" in activity["traits"] or len(strong_ids(room, index)) < 3:
            continue
        return room
    return None


def test_code_refuses_a_yes_that_runs_into_what_the_person_avoids():
    # Nikhil's case: his agent said yes to hockey until 9:30pm although he avoids late nights
    reset_db()
    people = town()
    index = {p["id"]: p for p in people}
    room = evening_room(people, index)
    ids = strong_ids(room, index)[:3]
    index[ids[0]]["avoid"] = ["late_nights"]
    plan = {"thoughts": "One late game.", "groups": [{"activity": room["activity"], "part": "evening", "time": "7-9:30pm",
                                                      "members": ids, "alternates": [], "proposals": {}}]}
    data = run(matchmaker.run_day(DAY, 5, people, fake(plan)))
    group = data["groups"][0]
    late = [m for m in group["members"] if m["id"] == ids[0]][0]
    assert late["state"] == "no"
    assert "avoids late nights" in late["refused"]
    assert group["status"] == "locked" and ids[0] not in group["final"] and len(group["final"]) == 2
    first = index[ids[0]]["name"].split(" ")[0]
    assert any(e["kind"] == "check" and e["text"].startswith("Refused " + first + "'s yes to g1: It runs to 9pm or later")
               for e in data["log"])
    # the agent's own words stay on record next to code's decision
    agent = [m for m in group["thread"] if m["from"] == "agent" and m["by"] == ids[0]][0]
    assert agent["answer"] == "yes"
    assert any(m["from"] == "system" and m["text"].startswith("Code turned " + first + "'s yes into a no") for m in group["thread"])


def test_a_yes_without_a_reason_from_the_profile_counts_as_no():
    reset_db()
    people = town()
    plan = two_group_plan(rooms_for(people))
    vague = plan["groups"][0]["members"][0]
    names = {p["id"]: p["name"] for p in people}

    def agent(system, content):
        if ("personal agent of " + names[vague] + ".") in system:
            return json.dumps({"answer": "yes", "reason": "  ", "say": "sure, why not"})
        return json.dumps({"answer": "yes", "reason": "loves it", "say": "in"})

    client = fake(plan, agent=agent)
    data = run(matchmaker.run_day(DAY, 5, people, client))
    assert vague not in data["groups"][0]["final"]
    assert any("gave no reason from" in e["text"] for e in data["log"] if e["kind"] == "check")
    # the matchmaker sees why, so it can call an alternate
    resolve = [kwargs["messages"][0]["content"] for kind, kwargs in client.calls if kind == "mm_resolve"][0]
    assert vague + " " + names[vague] + ": no (code refused their agent's yes: the agent gave no reason" in resolve


def test_the_matchmaker_sees_when_code_refused_a_yes():
    group = {"id": "g1", "activity": "gorge", "part": "morning", "time": "9am-12pm", "alternates": [],
             "members": [{"id": "e001", "state": "no", "counter": "", "refused": "the agent gave no reason from Ann's profile."}]}
    payload = matchmaker._resolve_payload([group], {"e001": {"name": "Ann B."}})
    assert "e001 Ann B.: no (code refused their agent's yes: the agent gave no reason" in payload


def test_the_agent_needs_a_strong_reason_to_say_yes():
    system = matchmaker._agent_system(town()[0])
    assert "only with a strong reason from the profile" in system
    assert "Being only up for it (a mild interest) is not a strong reason" in system
    assert '"reason": "for a yes: the strong reason, from the profile"' in system
    assert "A mild interest is a fair reason to pass" not in system


def test_only_people_with_a_strong_interest_can_be_members():
    # Donna and Valeria were only "up for" it, and their agents said yes anyway
    people = town()
    index = {p["id"]: p for p in people}
    rooms = rooms_for(people)
    room = [r for r in rooms if len(strong_ids(r, index)) >= 2 and matchmaker.split_room(r, index)[1]][0]
    strong = strong_ids(room, index)[:2]
    mild = matchmaker.split_room(room, index)[1][0]["id"]
    assert matchmaker.keenness(index[mild], catalog.get(room["activity"])) == 1
    raw = {"groups": [{"activity": room["activity"], "part": room["part"], "members": strong + [mild], "alternates": []}]}
    groups, rejected = matchmaker.check_plan(raw, rooms, 5, index)
    assert [m["id"] for m in groups[0]["members"]] == strong
    assert groups[0]["alternates"] == [mild]
    assert any(index[mild]["name"] + " is only up for" in r and "an alternate, not a member" in r for r in rejected)
    # two mild people alone can't make a group
    others = [c["id"] for c in matchmaker.split_room(room, index)[1]]
    if len(others) >= 2:
        groups, rejected = matchmaker.check_plan({"groups": [{"activity": room["activity"], "part": room["part"],
                                                               "members": others[:2]}]}, rooms, 5, index)
        assert groups == [] and any("fewer than 2 valid people" in r for r in rejected)


def test_the_plan_lists_mild_people_as_alternates_only():
    people = town()
    index = {p["id"]: p for p in people}
    rooms = rooms_for(people)
    payload = matchmaker._plan_payload(rooms, index)
    assert "Members need a strong interest" in matchmaker._plan_system(DAY, 10)
    room = [r for r in rooms if len(strong_ids(r, index)) >= 2 and matchmaker.split_room(r, index)[1]][0]
    activity = catalog.get(room["activity"])
    block = payload.split("[" + activity["id"] + " | " + room["part"] + "]")[1].split("\n[")[0]
    mild = [c["id"] for c in matchmaker.split_room(room, index)[1]]
    assert "  mild, alternates only: " + " ".join(mild) in block
    keenest = [line for line in block.splitlines() if line.startswith("  keenest: ")][0]
    assert not any(pid + ":" in keenest for pid in mild)
    # a room without two people who really want it can't form a group, so the plan doesn't show it
    weak = [r for r in rooms if len(strong_ids(r, index)) < 2]
    for r in weak:
        assert "[" + r["activity"] + " | " + r["part"] + "]" not in payload


def test_people_with_fewer_plans_this_week_come_first():
    # Wei T. was placed 22 times across the runs while 60 neighbors were never placed
    people = town()
    index = {p["id"]: p for p in people}
    rooms = rooms_for(people)
    room = [r for r in rooms if len(strong_ids(r, index)) > matchmaker.PROFILES_PER_ROOM][0]
    busy = strong_ids(room, index)[0]
    plans = {busy: 2}
    matchmaker._fewest_plans_first(rooms, plans)
    assert strong_ids(room, index)[-1] == busy
    payload = matchmaker._plan_payload(rooms, index, plans)
    activity = catalog.get(room["activity"])
    block = payload.split("[" + activity["id"] + " | " + room["part"] + "]")[1].split("\n[")[0]
    keenest = [line for line in block.splitlines() if line.startswith("  keenest: ")][0]
    assert busy + ":" not in keenest
    assert "Favor people with fewer plans this week" in matchmaker._plan_system(DAY, 10)


def test_a_day_says_who_already_has_a_plan_and_shows_it_to_the_matchmaker():
    reset_db()
    people = town()
    index = {p["id"]: p for p in people}
    rooms = rooms_for(people)
    # someone from a small room stays listed whatever the order; in a big one a plan moves them out of view
    small = [r for r in rooms if 2 <= len(strong_ids(r, index)) <= matchmaker.PROFILES_PER_ROOM][0]
    top = strong_ids(small, index)[0]
    client = fake(two_group_plan(rooms))
    data = run(matchmaker.run_day(DAY, 5, people, client, plans={top: 1, "nobody": 3}))
    assert any(e["text"].startswith("Neighbors who already have a plan this week: 1.") for e in data["log"])
    plan_payload = [kwargs["messages"][0]["content"] for kind, kwargs in client.calls if kind == "mm_plan"][0]
    line = [l for l in plan_payload.split("PEOPLE:")[1].splitlines() if l.strip().startswith(top + " ")]
    assert len(line) == 1 and line[0].endswith("; plans this week: 1")
    assert plan_payload.count("plans this week:") == 1
    assert data["breakRoom"]["usable"] <= data["breakRoom"]["slots"]
