"""The one-file text dump of a run (run_dump.py): everything a person or an AI chat needs, in
order, each line traceable by event number. Offline, on FakeClient runs."""

import json
import os

import orchestration_audit as audit
import run_dump
from conftest import reset_db
from test_orchestration_audit import client_for, cohort, plan, simulate

SECTIONS = ["\n1. PEOPLE: each", "\n2. CONVERSATIONS: every", "\n3. GROUPS: each", "\n4. TIMELINE: every",
            "\n5. WHAT OUR CHECKS FOUND"]


def events_of(out):
    with open(os.path.join(out, "full_simulation.jsonl")) as f:
        return [json.loads(line) for line in f.read().splitlines() if line.strip()]


def test_a_run_writes_its_dump_with_every_section_in_order(tmp_path):
    reset_db()
    people = cohort()
    out = simulate(tmp_path, people, client_for(plan(people)))
    path = os.path.join(out, "run_dump.txt")
    assert os.path.exists(path)
    text = open(path).read()
    positions = [text.index(s) for s in SECTIONS]
    assert positions == sorted(positions)
    assert "did NOT come from Claude" in text.split(SECTIONS[0])[0]
    assert "HOW TO USE THIS FILE" in text


def test_every_message_between_hub_and_agents_is_printed_in_full(tmp_path):
    reset_db()
    people = cohort()
    out = simulate(tmp_path, people, client_for(plan(people)))
    text = run_dump.dump(out)
    conversations = text.split(SECTIONS[1])[1].split(SECTIONS[2])[0]
    events = events_of(out)
    messages = [e for e in events if e["type"] in ("hub_to_agent", "agent_to_hub")]
    assert len(messages) == 12
    for e in messages:
        assert "[#" + str(e["seq"]) + "]" in conversations
        assert '"' + e["text"] + '"' in conversations
    # what code showed each agent sits under the hub's message
    assert conversations.count("code showed the agent") == 6


def test_each_person_has_their_prompt_before_and_their_answers_after(tmp_path):
    reset_db()
    people = cohort()
    out = simulate(tmp_path, people, client_for(plan(people)))
    text = run_dump.dump(out)
    section = text.split(SECTIONS[0])[1].split(SECTIONS[1])[0]
    initial = json.load(open(os.path.join(out, "agents_initial.json")))
    # the shared wording once, in full; each person's own part under them
    assert section.count("Check the plan against everything above") == 1
    for person in initial:
        assert person["id"] + " | " + person["name"] in section
        assert run_dump._told_block(person["agent_system_prompt"]).split("\n")[0] in section
    assert section.count("AFTER: profile unchanged (checked against the start)") == len(initial)
    asked = {e["person"] for e in events_of(out) if e["type"] == "agent_to_hub"}
    assert section.count("Never asked in this run") == len(initial) - len(asked)


def test_a_prompt_with_different_wording_is_printed_in_full(tmp_path):
    reset_db()
    people = cohort()
    out = simulate(tmp_path, people, client_for(plan(people)))
    path = os.path.join(out, "agents_initial.json")
    initial = json.load(open(path))
    initial[3]["agent_system_prompt"] = initial[3]["agent_system_prompt"].replace("Saying no is normal", "Say yes often")
    open(path, "w").write(json.dumps(initial))
    text = run_dump.dump(out)
    assert "this prompt's wording differs from the one above" in text
    assert "Say yes often" in text


def test_the_timeline_has_every_event_and_groups_show_their_logic(tmp_path):
    reset_db()
    people = cohort()
    out = simulate(tmp_path, people, client_for(plan(people)))
    text = run_dump.dump(out)
    timeline = text.split(SECTIONS[3])[1].split(SECTIONS[4])[0]
    for e in events_of(out):
        assert "[#" + str(e["seq"]) + "]" in timeline
    groups = text.split(SECTIONS[2])[1].split(SECTIONS[3])[0]
    assert groups.count(" | LOCKED") == 2
    assert "The hub's reason" in groups
    assert "Likes the final members share" in groups


def test_the_checks_come_last_and_appear_once_audited(tmp_path):
    reset_db()
    people = cohort()
    out = simulate(tmp_path, people, client_for(plan(people)))
    assert "hasn't been audited yet" in open(os.path.join(out, "run_dump.txt")).read()
    audit.audit(out)
    text = open(os.path.join(out, "run_dump.txt")).read()
    assert "RULE CHECKS IN CODE (reproducible)" in text.split(SECTIONS[4])[1]


def test_several_runs_go_into_one_file_behind_an_index(tmp_path):
    reset_db()
    people = cohort()
    first = simulate(tmp_path, people, client_for(plan(people)), name="run_one")
    second = simulate(tmp_path, people, client_for(plan(people, groups=1)), name="run_two")
    path = run_dump.write_all(str(tmp_path / "ALL.txt"), [first, second])
    text = open(path).read()
    assert text.startswith("CLAWNLY ORCHESTRATION RUNS: 2 runs in one file")
    assert "END OF run_one" in text
    assert "END OF run_two" in text
