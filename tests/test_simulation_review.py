"""Review exports must keep evidence traceable and never discard human notes."""

import csv
import json
import shutil
from pathlib import Path

import simulation_review as review


SOURCE = Path(__file__).resolve().parent.parent / "simulation_results" / "run_20261029_023316_smoke"


def test_saved_run_has_consistent_profiles_and_traceable_replies():
    rows, checked = review.inspect_run(SOURCE)
    assert len(rows) == checked["locked"] == 3
    assert checked["errors"] == []
    assert checked["calls"] == 13
    assert checked["answers"] == 8
    conversation = rows[0]["conversation_verbatim"]
    assert "HUB -> e124" in conversation and "e104 Susan L. -> HUB" in conversation
    assert conversation.index("[#20]") < conversation.index("[#22]")
    assert conversation.index("[#28]") < conversation.index("[#38]")


def test_tampering_with_a_reply_is_reported(tmp_path):
    folder = tmp_path / SOURCE.name
    shutil.copytree(SOURCE, folder)
    path = folder / "groups_generated.json"
    groups = review.read(path)
    groups[0]["members"][0]["answers"][0]["said"] = "invented explanation"
    path.write_text(json.dumps(groups), encoding="utf-8")
    rows, checked = review.inspect_run(folder)
    assert "reply differs from log: 2026-10-31/g1" in checked["errors"]


def test_rebuilding_keeps_human_verdicts_and_notes(tmp_path):
    shutil.copytree(SOURCE, tmp_path / SOURCE.name)
    review.build(tmp_path)
    path = tmp_path / "review_notes.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    rows[0]["human_verdict"] = "Unsure"
    rows[0]["human_notes"] = "Ask whether photography is enough."
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=review.FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    result = review.build(tmp_path)
    assert result["completed_groups"] == 3
    assert result["additional_groups_needed"] == 197
    assert result["human_verdicts_in_csv"] == 1
    with path.open(encoding="utf-8-sig", newline="") as stream:
        saved = list(csv.DictReader(stream))
    assert saved[0]["human_notes"] == rows[0]["human_notes"]
