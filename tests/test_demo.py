"""Tests for the offline DemoClient (scripted AI, zero API calls)."""

from conftest import run
from demo import DemoClient, _is_seed_cast, _parse_match_candidates, _dynamic_match_body
from main import run_pipeline
import json
import persona_gen


def test_seed_cast_marker_requires_maya_and_marcus():
    seed = "id: u01 | name: Maya | age: 27\nid: u04 | name: Marcus | age: 31"
    assert _is_seed_cast(seed) is True
    generated = "id: u01 | name: Ava Park | age: 24\nid: u04 | name: Drew Shah | age: 30"
    assert _is_seed_cast(generated) is False


def test_dynamic_match_picks_three_from_remaining_payload():
    payload = (
        "id: u01 | name: Ava Park | age: 24 | gender: female\n"
        "availability: weekday_evening, weekend_daytime\n"
        "preferred_group_size: no preference\n"
        "\n"
        "id: u02 | name: Ben Nguyen | age: 27 | gender: male\n"
        "availability: weekday_evening\n"
        "preferred_group_size: [2, 3]\n"
        "\n"
        "id: u03 | name: Cora Shah | age: 30 | gender: female\n"
        "availability: weekday_evening, weekend_evening\n"
        "preferred_group_size: no preference\n"
        "\n"
        "id: u04 | name: Drew Ortiz | age: 33 | gender: male\n"
        "availability: weekend_daytime\n"
        "preferred_group_size: [5, 8]\n"
    )
    people = _parse_match_candidates(payload)
    assert len(people) == 4
    body = json.loads(_dynamic_match_body(payload))
    assert len(body["group"]) == 3
    assert "u04" not in body["group"]   # size 5-8 cannot sit in a group of 3
    assert body["why_not"][0]["id"] == "u04"


def test_demo_pipeline_partitions_a_24_person_cast():
    people = persona_gen.build_demo_cast(count=24, theme="Black Diamond neighbors")
    result = run(run_pipeline(people, client=DemoClient(), verbose=False))
    assert len(result["interviews"]) == 24
    assert len(result["groups"]) >= 2
    assert "unmatched" in result
    # every matched id was actually in the generated cast
    ids = set(u["id"] for u in people)
    gi = 0
    while gi < len(result["groups"]):
        group = result["groups"][gi]["match"]["group"]
        assert len(group) >= 3
        mi = 0
        while mi < len(group):
            assert group[mi] in ids
            mi += 1
        gi += 1
