"""End-to-end pipeline tests with a fully mocked client (SPEC F5)."""

from conftest import FakeClient, json_body, run
from main import run_pipeline
from users import USERS


def match_obj(group=None):
    if group is None:
        group = ["u01", "u04", "u10"]
    return {
        "group": group,
        "reason": "All free weekday evenings with a shared calm, intellectual streak.",
        "scores": {"personality": 3, "availability": 4, "interests": 4, "size_fit": 5},
        "why_not": [{"id": "u08", "reason": "wants 6-8 people"}],
    }


def negotiation_obj():
    return {
        "common_ground": ["all keep weekday evenings free", "shared love of chess and quiet focus"],
        "activity": "a low-key chess night over coffee",
        "rationale": "It fits their introverted energy and their one shared free window.",
        "reactions": [
            {"name": "Maya", "reaction": "Honestly perfect, I'd love a calm evening."},
            {"name": "Marcus", "reaction": "Chess after work? I'm in."},
        ],
    }


def popup_obj():
    return {
        "event_name": "Weekday Wind-Down",
        "activity": "chess and coffee",
        "location": "Compass Coffee, Navy Yard",
        "time": "Wednesday evening",
        "matched_users": ["placeholder"],
        "reason": "A quiet weekday evening over chess suits all three of you perfectly.",
    }


def full_fake():
    return FakeClient(
        match_queue=[json_body(match_obj())],
        negotiation_queue=[json_body(negotiation_obj())],
        popup_queue=[json_body(popup_obj())],
    )


def test_full_pipeline_runs_end_to_end(capsys):
    fake = full_fake()
    result = run(run_pipeline(USERS, client=fake))

    assert result["matches"]["group"] == ["u01", "u04", "u10"]
    assert result["negotiation"]["activity"] == "a low-key chess night over coffee"
    assert result["popup"]["matched_users"] == ["Maya", "Marcus", "Omar"]

    out = capsys.readouterr().out
    assert "STEP 1 - INTERVIEWS" in out
    assert "STEP 2 - MATCH + REASONING" in out
    assert "STEP 3 - NEGOTIATION" in out
    assert "STEP 4 - MEETUP POPUP" in out
    assert "a low-key chess night over coffee" in out      # negotiated activity shown
    assert "Weekday Wind-Down" in out


def test_negotiated_activity_flows_into_popup():
    fake = full_fake()
    run(run_pipeline(USERS, client=fake))
    popup_kwargs = [kw for kind, kw in fake.calls if kind == "popup"][0]
    payload = popup_kwargs["messages"][0]["content"]
    assert "a low-key chess night over coffee" in payload    # popup built around it


def test_pipeline_skips_popup_on_empty_group(capsys):
    empty = json_body({"group": [], "reason": "no shared time across viable sets", "scores": {}, "why_not": []})
    fake = FakeClient(match_queue=[empty])
    result = run(run_pipeline(USERS, client=fake))

    assert result["matches"]["group"] == []
    assert result["popup"] is None

    out = capsys.readouterr().out
    assert "No viable group" in out
    assert "MEETUP POPUP" not in out                        # popup skipped
    kinds = [k for k, _ in fake.calls]
    assert "popup" not in kinds and "negotiation" not in kinds   # both skipped


def test_pipeline_uses_single_injected_client():
    fake = full_fake()
    run(run_pipeline(USERS, client=fake))
    kinds = [k for k, _ in fake.calls]
    assert "interview" in kinds and "match" in kinds
    assert "negotiation" in kinds and "popup" in kinds
