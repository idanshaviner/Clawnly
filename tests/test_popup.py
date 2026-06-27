"""Tests for the popup generator (SPEC F4)."""

import config
from conftest import FakeClient, json_body, run
from popup import generate_popup
from users import USERS


def group(ids):
    by_id = {u["id"]: u for u in USERS}
    return [by_id[i] for i in ids]


def sample_popup():
    return {
        "event_name": "Weekday Wind-Down",
        "activity": "board games and drinks",
        "location": "Board Room DC, Dupont Circle",
        "time": "Wednesday evening",
        "matched_users": ["WILL_BE_OVERWRITTEN"],
        "reason": "You three all unwind on weekday evenings and love a good strategy game.",
    }


def test_generate_popup_returns_required_keys():
    fake = FakeClient(popup_queue=[json_body(sample_popup())])
    out = run(generate_popup(group(["u01", "u04", "u10"]), "they share weekday evenings", client=fake))
    for key in ["event_name", "activity", "location", "time", "matched_users", "reason"]:
        assert key in out


def test_matched_users_anchored_to_real_names():
    fake = FakeClient(popup_queue=[json_body(sample_popup())])
    out = run(generate_popup(group(["u01", "u04", "u10"]), "reason", client=fake))
    assert out["matched_users"] == ["Maya", "Marcus", "Omar"]


def test_popup_uses_config_model_and_temperature():
    fake = FakeClient(popup_queue=[json_body(sample_popup())])
    run(generate_popup(group(["u01", "u04"]), "reason", client=fake))
    kind, kwargs = fake.calls[0]
    assert kind == "popup"
    assert kwargs["model"] == config.MODEL_POPUP
    assert kwargs["temperature"] == config.TEMP_POPUP


def test_match_reason_passed_into_prompt():
    fake = FakeClient(popup_queue=[json_body(sample_popup())])
    run(generate_popup(group(["u01", "u04"]), "a very specific matcher reason", client=fake))
    _, kwargs = fake.calls[0]
    assert "a very specific matcher reason" in kwargs["messages"][0]["content"]


def test_popup_falls_back_on_bad_json():
    fake = FakeClient(popup_queue=["not valid json"])
    out = run(generate_popup(group(["u01", "u04"]), "fallback reason", client=fake))
    assert out["reason"] == "fallback reason"
    assert out["matched_users"] == ["Maya", "Marcus"]
