"""The one-file match review (match_book.py): every locked group as a readable card, built
from saved runs with no API calls. Offline, on FakeClient runs."""

import json
import os

import match_book
from conftest import reset_db
from test_orchestration_audit import DAY, client_for, cohort, plan, simulate


def write_failed_run(root, name):
    folder = root / name
    folder.mkdir()
    (folder / "run_manifest.json").write_text(json.dumps({"stage": "review", "days_run": [{"day": DAY, "status": "failed"}]}))
    (folder / "groups_generated.json").write_text("[]")
    (folder / "full_simulation.jsonl").write_text(json.dumps({"type": "system", "text": "Run stopped: Connection error.",
                                                              "seq": 1, "day": DAY}) + "\n")


def test_every_locked_group_gets_a_card_and_failed_runs_are_set_aside(tmp_path):
    reset_db()
    people = cohort()
    simulate(tmp_path, people, client_for(plan(people)), name="run_a_pilot")
    simulate(tmp_path, people, client_for(plan(people, groups=1)), name="run_b_pilot")
    write_failed_run(tmp_path, "run_c_review")
    (tmp_path / "run_d_review").mkdir()
    text = match_book.build(str(tmp_path))
    assert text.startswith("# Clawnly match review: 3 groups made by the AI matchmaker")
    assert text.count("\n#### ") == 3
    assert "#### 3. " in text
    # the at-a-glance table: its header, then one row per group
    glance = text.split("## All groups at a glance")[1].split("## Every group")[0]
    assert glance.count("\n| ") == 1 + 3
    assert "1 run, failed: Run stopped: Connection error.: `run_c_review`" in text
    assert "1 run, interrupted before it finished (no manifest): `run_d_review`" in text


def test_a_card_shows_the_people_the_reason_and_every_answer_verbatim(tmp_path):
    reset_db()
    people = cohort()
    out = simulate(tmp_path, people, client_for(plan(people)), name="run_a_pilot")
    text = match_book.build(str(tmp_path))
    card = text.split("#### 1. ")[1].split("#### 2. ")[0]
    groups = json.load(open(os.path.join(out, "groups_generated.json")))
    assert "> " + groups[0]["why_hub_chose_it"] in card
    for member in groups[0]["members"]:
        person = next(p for p in people if p["id"] == member["id"])
        assert "| " + person["name"] + " (" + person["id"] + ") |" in card
        for answer in member["answers"]:
            assert answer["said"] in card
    assert "**How it ended:**" in card
    assert "**Your verdict:**" in card


def test_side_interests_and_repeats_are_flagged_as_facts(tmp_path):
    reset_db()
    people = cohort()
    simulate(tmp_path, people, client_for(plan(people)), name="run_a_pilot")
    simulate(tmp_path, people, client_for(plan(people)), name="run_b_pilot")
    text = match_book.build(str(tmp_path))
    # the same plan twice: each group meets again in the other run
    first = text.split("#### 1. ")[1].split("#### 2. ")[0]
    assert "The same activity and people also met in #3." in first
    assert "Things to look at" in first


def test_write_puts_the_file_in_the_results_folder(tmp_path):
    reset_db()
    people = cohort()
    simulate(tmp_path, people, client_for(plan(people)), name="run_a_pilot")
    path = match_book.write(str(tmp_path))
    assert path == os.path.join(str(tmp_path), "CLAWNLY_MATCH_REVIEW.md")
    assert os.path.exists(path)
