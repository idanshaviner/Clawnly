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
        groups.append({"activity": room["activity"], "part": room["part"], "time": "10am-12pm",
                       "members": members, "alternates": [ids[3]], "why": "shared interests",
                       "proposals": {pid: "Hi, " + room["activity"] + " tomorrow?" for pid in members}})
        if len(groups) == 2:
            break
    return {"thoughts": "Two strong rooms today.", "groups": groups}


def says(answer, counter=""):
    return lambda system, content: json.dumps({"answer": answer, "counter": counter, "say": "noted"})


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
            return json.dumps({"answer": "yes", "say": "in"})
        if any(("personal agent of " + names[m] + ".") in system for m in plan["groups"][0]["members"]):
            return json.dumps({"answer": "no", "say": "busy"})
        return json.dumps({"answer": "yes", "say": "in"})

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
        return json.dumps({"answer": "yes", "say": "in"})

    def resolve(system, content):
        return json.dumps({"thoughts": "swap in the alternate", "groups": [
            {"id": "g1", "keep": True, "time": "11am-1pm", "ask": [
                {"id": g1["alternates"][0], "message": "a spot opened"},
                {"id": outsider, "message": "join?"},
                {"id": g2["members"][0], "message": "switch groups?"},
            ]},
            {"id": "g2", "keep": True, "ask": []},
        ]})

    client = fake(plan, agent=agent, resolve=resolve)
    data = run(matchmaker.run_day(DAY, 5, people, client))
    group = data["groups"][0]
    assert group["time"] == "11am-1pm"
    assert g1["alternates"][0] in group["final"]
    assert outsider not in group["final"]
    assert g2["members"][0] not in group["final"]
    checks = [e["text"] for e in data["log"] if e["kind"] == "check"]
    assert any("isn't in g1 or its alternates" in c for c in checks)
    assert any("already said yes to g2" in c for c in checks)
    # 6 round-one asks + the one valid round-two ask
    assert client.kinds().count("mm_agent") == 7


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
        return json.dumps({"answer": "yes", "say": "in"})

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
