"""The single review file must contain its evidence and preserve exported notes."""

import json
import re
from pathlib import Path

import readable_review as review


ROOT = Path(__file__).resolve().parent.parent / "simulation_results"


def test_all_matches_have_embedded_people_and_referenced_calls():
    data = review.collect(ROOT)
    assert len(data["matches"]) >= 200
    assert 0 < data["distinct"] <= len(data["matches"])
    i = 0
    while i < len(data["matches"]):
        match = data["matches"][i]
        run = data["runs"][match["run"]]
        j = 0
        while j < len(match["group"]["members"]):
            pid = match["group"]["members"][j]["id"]
            assert run["people"][pid]["agent_system_prompt"]
            assert pid in run["after"]
            j += 1
        j = 0
        while j < len(match["raw_calls"]):
            assert str(match["raw_calls"][j]) in run["calls"]
            j += 1
        assert match["conversation"] == sorted(match["conversation"], key=lambda event: event["seq"])
        i += 1


def test_note_text_cannot_close_the_embedded_script():
    value = {"text": "</script><script>alert('test')</script>"}
    text = review.script_json(value)
    assert "</script>" not in text
    assert json.loads(text) == value


def test_rebuilding_preserves_notes_in_a_saved_review_file(tmp_path):
    path = tmp_path / "review.html"
    review.build(ROOT, path)
    text = path.read_text()
    state = {"notes": {"example": {"verdict": "Unsure", "text": "Discuss timing", "updated": 1}}, "cursor": 4}
    text = re.sub(r'(<script id="review-state" type="application/json">).*?(</script>)',
                  lambda match: match[1] + review.script_json(state) + match[2], text, flags=re.S)
    path.write_text(text)
    review.build(ROOT, path)
    saved = re.search(r'<script id="review-state" type="application/json">(.*?)</script>', path.read_text(), re.S)
    assert json.loads(saved[1]) == state
