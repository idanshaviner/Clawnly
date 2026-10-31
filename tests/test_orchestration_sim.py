"""The orchestration simulation harness (orchestration_sim.py): it runs the real
matchmaker.run_day, records every event, and writes a run folder that rebuilds
the day. Offline, through FakeClient: these replies are not Claude's, and the
manifest must say so."""

import datetime
import json
import os
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

import catalog
import demand
import matchmaker
import orchestration_sim as sim
from conftest import FakeClient, reset_db, run

DAY = "2026-10-31"


def people_for(size=12):
    return sim.cohort(sim.town(), datetime.date.fromisoformat(DAY), size)


INSIDE = {"morning": "10:30am-12pm", "afternoon": "1-3pm", "evening": "6-8pm"}


def plan_from_rooms(people, day=DAY, groups=2, size=3):
    rooms = demand.break_room(people, catalog.ACTIVITIES, datetime.date.fromisoformat(day))
    used = set()
    out = []
    index = {p["id"]: p for p in people}
    for room in rooms:
        # people who can take a seat: a strong interest in what the activity is mainly about
        ids = [c["id"] for c in matchmaker.split_room(room, index)[0] if c["id"] not in used]
        if len(ids) < size + 1:
            continue
        used.update(ids[:size + 1])
        out.append({"activity": room["activity"], "part": room["part"], "time": INSIDE[room["part"]], "members": ids[:size],
                    "alternates": [ids[size]], "why": "they share it",
                    "proposals": {pid: "Want to join " + room["activity"] + "?" for pid in ids[:size]}})
        if len(out) == groups:
            break
    return {"thoughts": "A small day.", "groups": out}


def agent_says(answer, counter=""):
    return lambda system, content: json.dumps({"answer": answer, "reason": "loves it", "counter": counter, "say": "noted"})


def keep(system, content):
    return json.dumps({"thoughts": "Keep them.", "groups": [{"id": "g1", "keep": True, "ask": []},
                                                            {"id": "g2", "keep": True, "ask": []}]})


def message_for_final(system, content):
    ids = sim._GROUP_LINE.findall(content)
    return json.dumps({"headline": "See you there", "messages": {pid: "See you there." for pid in ids}})


def fake(plan, agent=None, resolve=keep, message=message_for_final):
    if agent is None:
        agent = agent_says("yes")
    return FakeClient(matchmaker={"mm_plan": lambda s, c: json.dumps(plan), "mm_agent": agent,
                                  "mm_resolve": resolve, "mm_message": message})


def simulate(tmp_path, people, client, days=None, ceiling=None, name="run_test"):
    out = str(tmp_path / name)
    manifest = run(sim.simulate(people, days or [DAY], 3, client, out, ceiling=ceiling, stage="test"))
    return out, manifest


def read_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f.read().splitlines() if line.strip()]


def read_json(path):
    with open(path) as f:
        return json.loads(f.read())


def test_a_simulated_day_writes_every_file_and_says_where_replies_came_from(tmp_path):
    reset_db()
    people = people_for()
    out, manifest = simulate(tmp_path, people, fake(plan_from_rooms(people)))
    for name in ["run_manifest.json", "full_simulation.jsonl", "full_transcript.txt", "agents_initial.json",
                 "agents_final.json", "groups_generated.json", "cost_report.json", "days/" + DAY + ".json"]:
        assert os.path.exists(os.path.join(out, name)), name
    # a fake client never passes for Claude
    assert "did NOT come from Claude" in manifest["replies_from"]
    assert "did NOT come from Claude" in open(os.path.join(out, "full_transcript.txt")).read()
    assert manifest["days_run"][0]["status"] == "done"
    assert manifest["groups_locked"] == 2
    # no usage in the fake's replies: the cost is unknown, never a reassuring zero
    assert manifest["calls_without_usage"] == 10


def test_three_separate_records_agree_on_every_call(tmp_path):
    reset_db()
    people = people_for()
    client = fake(plan_from_rooms(people))
    out, manifest = simulate(tmp_path, people, client)
    check = manifest["days_run"][0]["log_check"]
    assert check["complete"] is True
    assert check["run_calls"] == check["harness_calls"] == check["db_ai_calls"] == len(client.calls)


def test_events_are_one_numbered_timeline(tmp_path):
    reset_db()
    people = people_for()
    out, _ = simulate(tmp_path, people, fake(plan_from_rooms(people)))
    events = read_jsonl(os.path.join(out, "full_simulation.jsonl"))
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert [e["t"] for e in events] == sorted(e["t"] for e in events)
    assert events[0]["type"] == "run_start"
    assert events[-1]["type"] == "run_end"
    # each hub message comes before the agent's call, which comes before its reply
    for reply in [e for e in events if e["type"] == "agent_to_hub"]:
        ask = [e for e in events if e["type"] == "hub_to_agent" and e["person"] == reply["person"]
               and e["group"] == reply["group"] and e["round"] == reply["round"]][0]
        call = [e for e in events if e["type"] == "model_call" and e["person"] == reply["person"]
                and e["group"] == reply["group"] and e["round"] == reply["round"]][0]
        assert ask["seq"] < call["seq"] < reply["seq"]


def test_every_agent_call_is_tied_to_its_person_group_and_round(tmp_path):
    reset_db()
    people = people_for()
    plan = plan_from_rooms(people)
    out, _ = simulate(tmp_path, people, fake(plan))
    events = read_jsonl(os.path.join(out, "full_simulation.jsonl"))
    times = {"g" + str(i + 1): g["time"] for i, g in enumerate(plan["groups"])}
    calls = [e for e in events if e["type"] == "model_call" and e["purpose"] == "matchmaker_agent"]
    assert len(calls) == 6
    for call in calls:
        assert call["person"] is not None
        assert call["group"] in ["g1", "g2"]
        assert call["round"] == 1
        assert call["group_time_at_ask"] == times[call["group"]]
        # the exact request is kept, system prompt and all
        assert call["request"]["system"].startswith("You are the personal agent of ")
        assert call["response"]["parsed_json"] is True
    messages = [e for e in events if e["type"] == "model_call" and e["purpose"] == "matchmaker_message"]
    assert sorted(m["group"] for m in messages) == ["g1", "g2"]


def test_a_name_ending_in_a_period_still_links_to_the_person():
    people = people_for()
    rec = sim.Recorder("x", people, None, False)
    person = people[0]
    assert person["name"].endswith(".")
    rec.data = {"groups": [{"id": "g1", "time": "9-11am", "thread": [{"t": "1", "from": "hub", "to": person["id"], "round": 1}]}]}
    system = "You are the personal agent of " + person["name"] + ". You know someone only from their profile"
    link = rec.link(system, "")
    assert link["person"] == person["id"]
    assert link["group"] == "g1"
    assert link["group_time"] == "9-11am"


def test_groups_point_at_the_events_that_decided_them(tmp_path):
    reset_db()
    people = people_for()
    out, _ = simulate(tmp_path, people, fake(plan_from_rooms(people)))
    events = {e["seq"]: e for e in read_jsonl(os.path.join(out, "full_simulation.jsonl"))}
    groups = read_json(os.path.join(out, "groups_generated.json"))
    assert len(groups) == 2
    for group in groups:
        assert group["status"] == "locked"
        assert events[group["evidence"]["plan_call_seq"]]["purpose"] == "matchmaker_plan"
        assert events[group["evidence"]["resolve_call_seq"]]["purpose"] == "matchmaker_resolve"
        assert events[group["evidence"]["status_seq"]]["after"] == "locked"
        assert events[group["evidence"]["message_call_seq"]]["purpose"] == "matchmaker_message"
        for member in group["members"]:
            answer = member["answers"][0]
            assert events[answer["reply_seq"]]["type"] == "agent_to_hub"
            assert events[answer["ask_seq"]]["type"] == "hub_to_agent"
            assert events[answer["call_seq"]]["type"] == "model_call"


def test_state_changes_record_before_and_after(tmp_path):
    reset_db()
    people = people_for()
    plan = plan_from_rooms(people)
    first = plan["groups"][0]["members"][0]

    def agent(system, content):
        if people_by_name[system.split("\n")[0][len("You are the personal agent of "):].split(". You know")[0]] == first:
            return json.dumps({"answer": "no", "counter": "", "say": "not keen"})
        return json.dumps({"answer": "yes", "reason": "loves it", "counter": "", "say": "in"})

    people_by_name = {p["name"]: p["id"] for p in people}
    out, _ = simulate(tmp_path, people, fake(plan, agent=agent))
    events = read_jsonl(os.path.join(out, "full_simulation.jsonl"))
    changes = [e for e in events if e["type"] == "member_state" and e["person"] == first]
    assert changes[0]["before"] == "asked"
    assert changes[0]["after"] == "no"
    statuses = [e for e in events if e["type"] == "group_status"]
    assert all(s["before"] == "negotiating" and s["after"] == "locked" for s in statuses)


def test_profiles_are_proven_unchanged_and_memory_is_stated(tmp_path):
    reset_db()
    people = people_for()
    out, _ = simulate(tmp_path, people, fake(plan_from_rooms(people)))
    initial = read_json(os.path.join(out, "agents_initial.json"))
    final = read_json(os.path.join(out, "agents_final.json"))
    assert len(initial) == len(final) == len(people)
    assert initial[0]["agent_system_prompt"].startswith("You are the personal agent of ")
    assert all(row["profile_changed"] is False for row in final)
    assert "none" in final[0]["memory"]
    answered = [row for row in final if len(row["answers"]) > 0]
    assert len(answered) == 6
    assert all(len(row["placed_in"]) == 1 for row in answered)


def test_a_call_that_could_cross_the_ceiling_is_never_made(tmp_path):
    reset_db()
    people = people_for()
    client = fake(plan_from_rooms(people))
    out, manifest = simulate(tmp_path, people, client, days=[DAY, "2026-11-01"], ceiling=0.05)
    # the plan's worst case (16000 Opus output tokens) is over $0.05: nothing goes out
    assert client.calls == []
    assert manifest["stopped_by_ceiling"] is True
    assert "cut short by the spending ceiling" in manifest["days_run"][0]["status"]
    assert manifest["days_run"][1]["status"] == "skipped (ceiling)"
    events = read_jsonl(os.path.join(out, "full_simulation.jsonl"))
    assert len([e for e in events if e["type"] == "budget_stop"]) == 1
    assert manifest["days_run"][0]["log_check"]["complete"] is True


def test_the_reservation_counts_calls_in_flight():
    rec = sim.Recorder("x", people_for(), 1.0, False)
    first = rec.reserve("claude-sonnet-5", 3000, 4000)
    assert round(first, 4) == round(1000 * 2 / 1e6 + 4000 * 10 / 1e6, 4)
    rec.release(first, 0.01)
    assert rec.spent == 0.01
    assert rec.in_flight == 0
    with pytest.raises(sim.BudgetStop):
        rec.reserve("claude-opus-5-5", 3000, 60000)
    # once stopped, it stays stopped
    with pytest.raises(sim.BudgetStop):
        rec.reserve("claude-sonnet-5", 10, 10)


def usage_reply(text, model, tokens_in=1000, tokens_out=500):
    return SimpleNamespace(id="msg_test", model=model, stop_reason="end_turn",
                           content=[SimpleNamespace(type="thinking", thinking="a summary"),
                                    SimpleNamespace(type="text", text=text)],
                           usage=SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out,
                                                 cache_creation_input_tokens=0, cache_read_input_tokens=0))


class UsageFake:
    """Replies with usage, like the real API, and can fail the first call."""

    def __init__(self, inner, fail_first=False):
        self.inner = inner
        self.fail_first = fail_first
        self.sent = []
        self.messages = self

    async def create(self, **kwargs):
        self.sent.append(kwargs)
        if self.fail_first:
            self.fail_first = False
            raise anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
        reply = await self.inner.messages.create(**kwargs)
        return usage_reply(reply.content[0].text, kwargs["model"])


def test_cost_comes_from_reported_usage_and_thinking_summaries_are_kept(tmp_path, monkeypatch):
    reset_db()
    monkeypatch.setattr(sim, "RETRY_WAIT", [0, 0])
    people = people_for()
    client = UsageFake(fake(plan_from_rooms(people)), fail_first=True)
    out = str(tmp_path / "run_usage")
    manifest = run(sim.simulate(people, [DAY], 3, client, out, ceiling=5.0, stage="test", thinking_summaries=True))
    costs = read_json(os.path.join(out, "cost_report.json"))
    # plan and resolve on Opus, 6 agents and 2 messages on Sonnet; 1000 in / 500 out each
    opus = 2 * (1000 * 4 + 500 * 20) / 1e6
    sonnet = 8 * (1000 * 2 + 500 * 10) / 1e6
    assert costs["calls"] == 10
    assert abs(costs["total_usd"] - (opus + sonnet)) < 1e-9
    assert abs(manifest["spent_usd"] - (opus + sonnet)) < 1e-9
    assert costs["by_model"]["claude-opus-5-5"]["calls"] == 2
    # the failed first try was retried and logged, not hidden
    events = read_jsonl(os.path.join(out, "full_simulation.jsonl"))
    retries = [e for e in events if e["type"] == "model_retry"]
    assert len(retries) == 1
    assert "APIConnectionError" in retries[0]["error"]
    plan_call = [e for e in events if e["type"] == "model_call" and e["purpose"] == "matchmaker_plan"][0]
    assert plan_call["attempts"] == 2
    # the harness asks for readable thinking and says so
    assert client.sent[0]["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert plan_call["request"]["added_by_harness"] == ["thinking.display=summarized"]
    assert plan_call["response"]["content"][0] == {"type": "thinking", "thinking": "a summary"}
    assert manifest["harness_request_changes"] != []


def test_keys_never_reach_a_results_file():
    assert sim.scrub("failed with sk-ant-api03-abcDEF_123-xyz in it") == "failed with [REDACTED] in it"


def test_a_cohort_is_drawn_from_the_town_and_shares_break_rooms():
    town = sim.town()
    group = sim.cohort(town, datetime.date.fromisoformat(DAY), 8)
    assert len(group) == 8
    ids = {p["id"] for p in town}
    assert all(p["id"] in ids for p in group)
    rooms = demand.break_room(group, catalog.ACTIVITIES, datetime.date.fromisoformat(DAY))
    assert max(len(r["candidates"]) for r in rooms) >= 3
    assert sim.cohort(town, datetime.date.fromisoformat(DAY), 500) == town


def test_the_estimate_prices_every_stage_without_a_client():
    town = sim.town()
    est = sim.estimate(town, ["2026-10-28"], 10)
    assert est["calls"] > 10
    assert 0 < est["usd_low"] < est["usd_high"] < est["usd_worst_case"]
    assert est["days"][0]["plan_input_tokens"] > 1000


def test_run_refuses_without_a_key(monkeypatch, capsys):
    monkeypatch.setattr(sim.config, "resolve_api_key", lambda: None)
    assert sim.main(["orchestration_sim.py", "run", "smoke"]) == 1
    assert "Nothing was run" in capsys.readouterr().out


def test_the_total_cap_holds_across_runs_and_counts_unsettled_runs_in_full(tmp_path):
    path = str(tmp_path / "ledger.json")
    assert sim.budget_for(4.0, 10.0, path) == 4.0
    first = sim.ledger_reserve("simulation smoke", "run_a", 1.5, path)
    # not settled yet (a crash would leave it so): the whole ceiling counts
    assert sim.ledger_spent(path) == 1.5
    sim.ledger_settle(first, 0.42, path)
    assert sim.ledger_spent(path) == 0.42
    second = sim.ledger_reserve("audit", "run_a", 8.0, path)
    sim.ledger_settle(second, 9.0, path)
    # what's left of the cap, never the stage's own ceiling, is the most a run may get
    assert sim.budget_for(4.0, 10.0, path) == round(10.0 - 9.42, 6)
    sim.ledger_settle(second, "unknown: 3 replies reported no usage", path)
    assert sim.ledger_spent(path) == 8.42


def test_run_refuses_when_the_total_cap_is_used_up(tmp_path, monkeypatch, capsys):
    path = str(tmp_path / "ledger.json")
    sim.ledger_settle(sim.ledger_reserve("earlier", "run_x", 10.0, path), 10.0, path)
    monkeypatch.setattr(sim, "LEDGER", path)
    monkeypatch.setattr(sim.config, "resolve_api_key", lambda: "sk-test-not-real")
    monkeypatch.setattr(sim, "budget_for", lambda ceiling, total_cap: total_cap - sim.ledger_spent(path))
    assert sim.main(["orchestration_sim.py", "run", "smoke"]) == 1
    assert "total cap is used up" in capsys.readouterr().out
    # a higher cap has to be given on the command line; the retest is refused without one too
    assert sim.main(["orchestration_sim.py", "run", "retest"]) == 1
    assert "$10.0 total cap is used up" in capsys.readouterr().out


def test_plans_carry_over_from_day_to_day_so_the_matchmaker_can_favor_fewer(tmp_path):
    reset_db()
    people = people_for()
    days = [DAY, "2026-11-01"]
    plans = [plan_from_rooms(people, day=d) for d in days]
    asked = []

    def plan_for_the_day(system, content):
        asked.append(content)
        return json.dumps(plans[len(asked) - 1])

    client = FakeClient(matchmaker={"mm_plan": plan_for_the_day, "mm_agent": agent_says("yes"),
                                    "mm_resolve": keep, "mm_message": message_for_final})
    out, manifest = simulate(tmp_path, people, client, days=days)
    starts = [e for e in read_jsonl(os.path.join(out, "full_simulation.jsonl")) if e["type"] == "day_start"]
    assert starts[0]["plans_before"] == {}
    first_day = [pid for g in plans[0]["groups"] for pid in g["members"]]
    assert starts[1]["plans_before"] == {pid: 1 for pid in first_day}
    assert str(len(first_day)) + " of them already have a plan this week" in starts[1]["text"]
    # the second day's plan shows the matchmaker who already has one
    assert "plans this week:" not in asked[0]
    assert "plans this week: 1" in asked[1]


def test_the_retest_town_is_the_same_neighbors_busier_and_pickier():
    stage = sim.STAGES["retest"]
    assert stage["busier"] and stage["pickier"] and stage["people"] == sim.TOWN_SIZE
    # consecutive days, so plans carry over
    first = datetime.date.fromisoformat(stage["days"][0])
    assert stage["days"] == [(first + datetime.timedelta(days=i)).isoformat() for i in range(len(stage["days"]))]
    plain = sim.town()
    harder = sim.town_for(stage)
    assert [p["name"] for p in harder] == [p["name"] for p in plain]
    assert sim.town_for(sim.STAGES["town"]) == plain
