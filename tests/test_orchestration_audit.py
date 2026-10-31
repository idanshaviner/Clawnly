"""The simulation audit (orchestration_audit.py): rule checks over a run's logs,
and the independent AI audit whose findings must cite events it was shown.
Offline: the runs and the auditor are FakeClient replies, not Claude's."""

import datetime
import json
import os
import re

import catalog
import demand
import matchmaker
import orchestration_audit as audit
import orchestration_sim as sim
from conftest import FakeClient, reset_db, run

DAY = "2026-10-31"
INSIDE = {"morning": "10:30am-12pm", "afternoon": "2-4pm", "evening": "6-8pm"}
OUTSIDE = {"morning": "7-9pm", "afternoon": "7-9pm", "evening": "8-10am"}


def rooms(people):
    return demand.break_room(people, catalog.ACTIVITIES, datetime.date.fromisoformat(DAY))


def plan(people, groups=2, size=3, time_for=None):
    out = []
    used = set()
    index = {p["id"]: p for p in people}
    for room in rooms(people):
        # people who can take a seat: a strong interest in what the activity is mainly about
        ids = [c["id"] for c in matchmaker.split_room(room, index)[0] if c["id"] not in used]
        if len(ids) < size + 1:
            continue
        used.update(ids[:size + 1])
        time = INSIDE[room["part"]]
        if time_for is not None:
            time = time_for(room, ids)
        out.append({"activity": room["activity"], "part": room["part"], "time": time, "members": ids[:size],
                    "alternates": [ids[size]], "why": "they share it",
                    "proposals": {pid: "A small group, want in?" for pid in ids[:size]}})
        if len(out) == groups:
            break
    return {"thoughts": "A small day.", "groups": out}


def yes(system, content):
    return json.dumps({"answer": "yes", "reason": "loves it", "counter": "", "say": "in"})


def keep(system, content):
    return json.dumps({"thoughts": "Keep them.", "groups": [{"id": "g1", "keep": True, "ask": []},
                                                            {"id": "g2", "keep": True, "ask": []}]})


def messages(system, content):
    ids = sim._GROUP_LINE.findall(content)
    return json.dumps({"headline": "See you there", "messages": {pid: "See you there." for pid in ids}})


def client_for(the_plan, agent=yes, resolve=keep, message=messages, auditor=None):
    replies = {"mm_plan": lambda s, c: json.dumps(the_plan), "mm_agent": agent, "mm_resolve": resolve,
               "mm_message": message}
    if auditor is not None:
        replies.update(auditor)
    return FakeClient(matchmaker=replies)


def simulate(tmp_path, people, client, name="run_audit"):
    out = str(tmp_path / name)
    run(sim.simulate(people, [DAY], 3, client, out, stage="test"))
    return out


def cohort():
    return sim.cohort(sim.town(), datetime.date.fromisoformat(DAY), 12)


def checks(result):
    return [f["check"] for f in result["mechanical"]]


def test_a_greeting_is_not_another_members_name_when_two_people_share_it(tmp_path):
    reset_db()
    people = cohort()
    out = simulate(tmp_path, people, client_for(plan(people)))
    loaded = audit.load(out)
    group = loaded["groups"][0]
    first = group["members"][0]["id"]
    second = group["members"][1]["id"]
    loaded["by_id"][first]["name"] = "Nora B."
    loaded["by_id"][second]["name"] = "Nora P."
    group["members"][0]["first_proposal"] = "Nora, want to join a walk?"
    group["members"][1]["first_proposal"] = "Nora, want to join a walk?"
    found = audit.mechanical(loaded)
    names = []
    i = 0
    while i < len(found):
        if found[i]["check"] == "proposal names another person":
            names.append(found[i])
        i += 1
    assert names == []
    group["members"][0]["first_proposal"] = "Nora, join the walk with Nora P.?"
    found = audit.mechanical(loaded)
    named = False
    i = 0
    while i < len(found):
        if found[i]["check"] == "proposal names another person":
            named = True
        i += 1
    assert named


def test_a_clean_run_has_no_rule_findings_and_true_numbers(tmp_path):
    reset_db()
    people = cohort()
    out = simulate(tmp_path, people, client_for(plan(people)))
    result = audit.audit(out)
    serious = [f for f in result["mechanical"] if f["severity"] in ["critical", "high"]]
    assert serious == []
    numbers = result["metrics"]
    assert numbers["groups_proposed"] == 2
    assert numbers["groups_locked"] == 2
    assert numbers["invitations_sent"] == 6
    assert numbers["answers"] == {"yes": 6, "no": 0, "counter": 0}
    assert numbers["acceptance_rate"] == 1.0
    assert numbers["hard_constraint_violations"] == 0
    assert "did NOT come from Claude" in numbers["replies_from"]
    assert numbers["simulation_cost_usd"] == "unknown: 10 replies reported no usage"
    for name in ["audit_mechanical.json", "metrics.json", "audit_report.md"]:
        assert os.path.exists(os.path.join(out, name))


def test_a_time_moved_without_asking_again_is_caught(tmp_path):
    # the product now refuses this (matchmaker.inside_part, and code re-asks after a move), so the
    # checker is shown a run doctored to have it, as a run from before the guards would
    reset_db()
    people = cohort()
    the_plan = plan(people)
    out = simulate(tmp_path, people, client_for(the_plan))
    loaded = audit.load(out)
    audit._add_first_proposals(loaded)
    group = loaded["groups"][0]
    group["time_final"] = OUTSIDE[group["part"]]
    group["evidence"]["time_change_seqs"] = [group["evidence"]["status_seq"]]
    found = audit.mechanical(loaded)
    unagreed = [f for f in found if f["check"] == "locked at a time they never agreed to"]
    assert len(unagreed) == 3
    assert all(f["severity"] == "high" and f["groups"] == [DAY + "/g1"] for f in unagreed)
    assert "time outside its day part" in [f["check"] for f in found]


def test_the_product_now_refuses_a_move_outside_the_day_part(tmp_path):
    reset_db()
    people = cohort()
    the_plan = plan(people)
    moved = OUTSIDE[the_plan["groups"][0]["part"]]

    def resolve(system, content):
        return json.dumps({"thoughts": "Move g1.", "groups": [{"id": "g1", "keep": True, "time": moved, "ask": []},
                                                              {"id": "g2", "keep": True, "ask": []}]})

    out = simulate(tmp_path, people, client_for(the_plan, resolve=resolve))
    result = audit.audit(out)
    assert [f for f in result["mechanical"] if f["severity"] in ["critical", "high"]] == []
    assert result["metrics"]["hard_constraint_violations"] == 0


def test_an_agent_saying_yes_to_a_conflict_it_was_shown_is_flagged(tmp_path):
    reset_db()
    people = sim.town()
    target = None
    for room in rooms(people):
        if room["part"] != "morning" or catalog.get(room["activity"]).get("fixed"):
            continue
        avoiders = [c["id"] for c in room["candidates"] if "early_mornings" in
                    next(p for p in people if p["id"] == c["id"])["avoid"]]
        others = [c["id"] for c in room["candidates"] if c["id"] not in avoiders]
        if avoiders and others:
            target = (room, avoiders[0], others[0])
            break
    assert target is not None
    room, early, other = target
    the_plan = {"thoughts": "One.", "groups": [{"activity": room["activity"], "part": "morning", "time": "8-9:30am",
                                                "members": [early, other], "alternates": [], "why": "x",
                                                "proposals": {}}]}

    def resolve(system, content):
        return json.dumps({"thoughts": "Keep.", "groups": [{"id": "g1", "keep": True, "ask": []}]})

    out = simulate(tmp_path, people, client_for(the_plan, resolve=resolve))
    result = audit.audit(out)
    flagged = [f for f in result["mechanical"] if f["check"] == "agent accepted a conflict it was shown"]
    assert [f["agents"] for f in flagged] == [[early]]
    assert "early" in flagged[0]["what"]
    assert result["metrics"]["agents_accepting_a_conflict_they_were_shown"] == 1


def test_an_unreadable_agent_reply_is_an_orchestration_failure(tmp_path):
    reset_db()
    people = cohort()
    out = simulate(tmp_path, people, client_for(plan(people), agent=lambda s, c: "Sure, sounds fun!"))
    result = audit.audit(out)
    unreadable = [f for f in result["mechanical"] if f["check"] == "reply wasn't JSON"]
    assert len(unreadable) == 6
    assert "silently" in unreadable[0]["why"]
    assert result["metrics"]["groups_locked"] == 0
    assert result["metrics"]["orchestration_failures"] == 6


def test_a_message_naming_someone_who_said_no_is_flagged(tmp_path):
    reset_db()
    people = cohort()
    the_plan = plan(people, groups=1, size=3)
    decliner = the_plan["groups"][0]["members"][2]
    first = next(p for p in people if p["id"] == decliner)["name"].split(" ")[0]
    by_name = {p["name"]: p["id"] for p in people}

    def agent(system, content):
        name = system.split("\n")[0][len("You are the personal agent of "):].split(". You know")[0]
        if by_name[name] == decliner:
            return json.dumps({"answer": "no", "counter": "", "say": "pass"})
        return yes(system, content)

    def message(system, content):
        ids = sim._GROUP_LINE.findall(content)
        return json.dumps({"headline": "On", "messages": {pid: "You'll meet " + first + " there." for pid in ids}})

    def resolve(system, content):
        return json.dumps({"thoughts": "Keep.", "groups": [{"id": "g1", "keep": True, "ask": []}]})

    out = simulate(tmp_path, people, client_for(the_plan, agent=agent, resolve=resolve, message=message))
    result = audit.audit(out)
    named = [f for f in result["mechanical"] if f["check"] == "message names someone who isn't coming"]
    assert len(named) == 2
    assert all(decliner in f["agents"] for f in named)


def test_the_rule_checks_catch_a_double_booking_they_are_given(tmp_path):
    # code prevents this in the product; the checker must still see it if it ever happens
    reset_db()
    people = cohort()
    out = simulate(tmp_path, people, client_for(plan(people)))
    loaded = audit.load(out)
    audit._add_first_proposals(loaded)
    loaded["groups"][1]["final_members"].append(loaded["groups"][0]["final_members"][0])
    found = [f for f in audit.mechanical(loaded) if f["check"] == "double booking"]
    assert len(found) == 1
    assert found[0]["severity"] == "critical"


def first_seq(packet):
    return int(re.search(r"^\[(\d+)\]", packet, re.MULTILINE).group(1))


def test_ai_findings_must_cite_events_the_auditor_was_shown(tmp_path):
    reset_db()
    people = cohort()

    def audit_group(system, content):
        seq = first_seq(content)
        return json.dumps({"verdict": "acceptable", "summary": "Fine.", "compatibility": "Shared interest.",
                           "agents": [{"id": "e001", "consistent": False, "note": "contradicted itself"}],
                           "matchmaker": "Reasonable.", "conversation": "Clear.",
                           "findings": [
                               {"severity": "medium", "kind": "quality issue", "agents": [], "what": "real",
                                "why": "w", "expected": "e", "fix": "f", "evidence": [seq]},
                               {"severity": "high", "kind": "quality issue", "agents": [], "what": "made up",
                                "why": "w", "expected": "e", "fix": "f", "evidence": [999999]}]})

    def audit_day(system, content):
        return json.dumps({"verdict": "good", "summary": "A fair day.", "findings": []})

    client = client_for(plan(people), auditor={"audit_group": audit_group, "audit_day": audit_day})
    out = simulate(tmp_path, people, client)
    result = audit.audit(out, client, use_ai=True)
    ai = result["ai"]
    assert ai["groups_audited"] == 2
    assert ai["days_audited"] == 1
    assert [f["what"] for f in ai["kept"]] == ["real", "real"]
    assert [f["what"] for f in ai["unsupported"]] == ["made up", "made up"]
    assert ai["unsupported"][0]["unsupported_refs"] == [999999]
    assert result["metrics"]["ai_audit_coverage"] == "2 of 2 groups, 1 of 1 days"
    assert result["metrics"]["ai_inconsistent_agents"] == 2
    # the auditor's calls are kept verbatim, like the run's
    calls = [json.loads(line) for line in open(os.path.join(out, "audit_calls.jsonl"))]
    purposes = [c["purpose"] for c in calls if c["type"] == "model_call"]
    assert purposes == ["audit_day", "audit_group", "audit_group"]
    assert calls[0]["request"]["model"] == audit.AUDITOR
    report = open(os.path.join(out, "audit_report.md")).read()
    assert "Findings dropped: no valid evidence cited (2)" in report


def test_the_group_packet_holds_profiles_the_room_and_numbered_messages(tmp_path):
    reset_db()
    people = cohort()
    out = simulate(tmp_path, people, client_for(plan(people)))
    loaded = audit.load(out)
    audit._add_first_proposals(loaded)
    packet, valid = audit.group_packet(loaded, loaded["groups"][0], [])
    assert "PEOPLE ASKED, OR NAMED AS ALTERNATES" in packet
    assert "OTHERS IN THE SAME BREAK ROOM" in packet
    assert "HUB -> " in packet
    assert "'s agent -> HUB: YES" in packet
    assert len(valid) >= 7
    for seq in valid:
        assert "[" + str(seq) + "]" in packet


def test_sampling_keeps_every_flagged_or_dropped_group(tmp_path):
    reset_db()
    people = cohort()
    out = simulate(tmp_path, people, client_for(plan(people)))
    loaded = audit.load(out)
    loaded["groups"][1]["status"] = "dropped"
    picked, how = audit._sample(loaded, [], 1)
    assert [g["id"] for g in picked] == ["g2"]
    assert "seed" in how
    picked, how = audit._sample(loaded, [], None)
    assert len(picked) == 2
    assert how == "every group"


def test_the_day_packet_carries_full_profiles_and_day_findings_get_full_ids(tmp_path):
    reset_db()
    people = cohort()
    out = simulate(tmp_path, people, client_for(plan(people)))
    loaded = audit.load(out)
    packet, valid = audit.day_packet(loaded, DAY)
    assert "FULL PROFILES OF EVERYONE ASKED TODAY" in packet
    assert "Avoids:" in packet or "Not into:" in packet
    seq = next(iter(valid))
    kept, _ = audit._validate({"findings": [{"severity": "low", "kind": "quality issue", "groups": ["g1"],
                                             "what": "x", "evidence": [seq]}]}, valid, "day", [], DAY)
    assert kept[0]["groups"] == [DAY + "/g1"]


def test_naming_a_decliner_is_flagged(tmp_path):
    # the product now skips re-asking an unchanged yes, so the hub names the decliner while moving the time
    reset_db()
    people = cohort()
    the_plan = plan(people, groups=1, size=3)
    members = the_plan["groups"][0]["members"]
    decliner = members[2]
    first = next(p for p in people if p["id"] == decliner)["name"].split(" ")[0]
    by_name = {p["name"]: p["id"] for p in people}
    later = {"morning": "11am-12pm", "afternoon": "3-4pm", "evening": "7-8pm"}[the_plan["groups"][0]["part"]]

    def agent(system, content):
        name = system.split("\n")[0][len("You are the personal agent of "):].split(". You know")[0]
        if by_name[name] == decliner:
            return json.dumps({"answer": "no", "counter": "", "say": "pass"})
        return yes(system, content)

    def resolve(system, content):
        return json.dumps({"thoughts": "Move it.", "groups": [{"id": "g1", "keep": True, "time": later, "ask": [
            {"id": members[0], "message": first + " can't make it, so it's a bit later now: ok?"},
            {"id": members[1], "message": "It's a bit later now: ok?"}]}]})

    out = simulate(tmp_path, people, client_for(the_plan, agent=agent, resolve=resolve))
    result = audit.audit(out)
    named = [f for f in result["mechanical"] if f["check"] == "hub told others who declined"]
    assert len(named) == 1
    assert named[0]["agents"] == [members[0], decliner]
    assert "re-asked a yes about an unchanged plan" not in checks(result)


def test_re_asking_an_unchanged_yes_is_flagged_in_a_log_that_has_it():
    # runs from before the product skipped these (the pilot) must still be counted
    def event(seq, kind, **fields):
        base = {"seq": seq, "type": kind, "day": DAY, "group": "g1", "person": "e001"}
        base.update(fields)
        return base

    events = [
        event(1, "hub_to_agent", round=1, text="Hike?"),
        event(2, "model_call", purpose="matchmaker_agent", round=1, group_time_at_ask="9-11am"),
        event(3, "agent_to_hub", round=1, answer="yes", text="in"),
        event(4, "hub_to_agent", round=2, text="Confirmed!"),
        event(5, "model_call", purpose="matchmaker_agent", round=2, group_time_at_ask="9-11am"),
        event(6, "agent_to_hub", round=2, answer="yes", text="in"),
    ]
    found = audit._check_round_two(events, {"e001": {"name": "Ann B."}})
    assert [f["check"] for f in found] == ["re-asked a yes about an unchanged plan"]
    assert found[0]["evidence"] == [4]


def test_compare_puts_two_runs_side_by_side_from_the_logs_alone(tmp_path):
    reset_db()
    people = cohort()
    before = simulate(tmp_path, people, client_for(plan(people)), name="run_before")
    after = simulate(tmp_path, people, client_for(plan(people, groups=1)), name="run_after")
    table = audit.compare(before, after)
    assert "| groups locked / proposed | 2 / 2 | 1 / 1 |" in table
    assert "| agent calls | 6 | 3 |" in table
    share = audit.side_interest_share(audit.load(before))
    assert 0 <= share <= 1


def test_compare_can_look_at_one_day_of_a_longer_run(tmp_path):
    reset_db()
    people = cohort()
    out = str(tmp_path / "run_two_days")
    run(sim.simulate(people, [DAY, "2026-11-01"], 3, client_for(plan(people)), out, stage="test"))
    whole = audit.numbers_for(out)
    one = audit.numbers_for(out, DAY)
    assert one["days"] == DAY
    assert one["agent calls"] < whole["agent calls"]


def test_a_probe_replays_an_agent_call_with_the_old_and_the_current_prompt(tmp_path):
    reset_db()
    people = cohort()
    out = simulate(tmp_path, people, client_for(plan(people)))
    loaded = audit.load(out)
    call = next(e for e in loaded["events"] if e["type"] == "model_call" and e["purpose"] == "matchmaker_agent")
    seen = []

    def agent(system, content):
        seen.append(system)
        return json.dumps({"answer": "no", "counter": "", "say": "limit"})

    result = run(audit.probe(loaded, [call["seq"]], 2, client_for(plan(people), agent=agent), None))
    assert [r["prompt"] for r in result["rows"]] == ["as run", "as run", "current code", "current code"]
    assert all(r["answer"] == "no" for r in result["rows"])
    # the same proposal both times; only the system prompt differs
    assert seen[0] == call["request"]["system"]
    assert seen[2] == audit.matchmaker._agent_system(loaded["by_id"][call["person"]])
    assert "| " + str(call["seq"]) + " " + call["person"] + " | current code | {\"no\": 2} |" in audit.probe_table(result["rows"])

    # a yes with no reason is shown as what the current code makes of it
    rows = [{"seq": 5, "person": "e001", "prompt": "current code", "answer": "yes", "reason": "", "said": "ok"},
            {"seq": 5, "person": "e001", "prompt": "current code", "answer": "yes", "reason": "loves hiking", "said": "in"},
            {"seq": 5, "person": "e001", "prompt": "as run", "answer": "yes", "said": "in"}]
    table = audit.probe_table(rows)
    assert '| 5 e001 | current code | {"yes without a reason (counts as no)": 1, "yes": 1} |' in table
    assert '| 5 e001 | as run | {"yes": 1} |' in table


def test_rerunning_the_rule_checks_keeps_the_ai_audit_already_done(tmp_path):
    reset_db()
    people = cohort()

    def audit_group(system, content):
        return json.dumps({"verdict": "good", "summary": "Fine.", "agents": [], "findings": []})

    def audit_day(system, content):
        return json.dumps({"verdict": "good", "summary": "Fine.", "findings": []})

    client = client_for(plan(people), auditor={"audit_group": audit_group, "audit_day": audit_day})
    out = simulate(tmp_path, people, client)
    audit.audit(out, client, use_ai=True)
    again = audit.audit(out)
    assert again["metrics"]["ai_audit_coverage"] == "2 of 2 groups, 1 of 1 days"
    assert "Independent AI audit" in open(os.path.join(out, "audit_report.md")).read()


def test_a_paid_audit_or_probe_needs_room_under_the_total_cap(tmp_path, monkeypatch, capsys):
    import orchestration_sim
    path = str(tmp_path / "ledger.json")
    orchestration_sim.ledger_settle(orchestration_sim.ledger_reserve("earlier", "run_x", 10.0, path), 10.0, path)
    monkeypatch.setattr(audit.config, "resolve_api_key", lambda: "sk-test-not-real")
    seen = []

    def budget(ceiling, total_cap):
        seen.append(total_cap)
        return min(ceiling, total_cap - orchestration_sim.ledger_spent(path))

    monkeypatch.setattr(orchestration_sim, "budget_for", budget)
    assert audit.main(["orchestration_audit.py", str(tmp_path), "--ai"]) == 1
    assert "$10.0 total cap is used up" in capsys.readouterr().out
    assert audit.main(["orchestration_audit.py", "probe", str(tmp_path), "1,2", "3", "--total-cap", "10"]) == 1
    assert "total cap is used up" in capsys.readouterr().out
    # a higher total only comes from the command line
    assert seen == [orchestration_sim.TOTAL_CAP, 10.0]
    assert audit._total_cap(["x", "--sample", "4", "--total-cap", "18.41"]) == 18.41


def test_re_asking_a_round_two_yes_in_round_three_is_flagged_too():
    # a replacement who said yes in round 2 is settled just like a round-1 yes
    def event(seq, kind, **fields):
        base = {"seq": seq, "type": kind, "day": DAY, "group": "g1", "person": "e001"}
        base.update(fields)
        return base

    events = [
        event(1, "hub_to_agent", round=2, text="A spot opened: want in?"),
        event(2, "model_call", purpose="matchmaker_agent", round=2, group_time_at_ask="9-11am"),
        event(3, "agent_to_hub", round=2, answer="yes", text="in"),
        event(4, "hub_to_agent", round=3, text="Confirmed!"),
        event(5, "model_call", purpose="matchmaker_agent", round=3, group_time_at_ask="9-11am"),
        event(6, "agent_to_hub", round=3, answer="yes", text="in"),
    ]
    found = audit._check_round_two(events, {"e001": {"name": "Ann B."}})
    assert [f["check"] for f in found] == ["re-asked a yes about an unchanged plan"]
    assert found[0]["evidence"] == [4]
