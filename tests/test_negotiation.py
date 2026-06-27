"""Tests for the negotiation phase (parent agent brokers a joint plan)."""

import config
from conftest import FakeClient, json_body, run
from negotiation import negotiate
from users import USERS


def group(ids):
    by_id = {u["id"]: u for u in USERS}
    return [by_id[i] for i in ids]


def interviews_for(ids):
    by_id = {u["id"]: u for u in USERS}
    out = {}
    for i in ids:
        out[i] = {"profile": by_id[i], "q1": "wants low-key meetups", "q2": "free weekday evenings"}
    return out


def plan_obj():
    return {
        "common_ground": ["all free weekday evenings", "shared love of chess"],
        "activity": "a relaxed chess night over coffee",
        "rationale": "Fits their introverted energy and shared free time.",
        "reactions": [{"name": "Maya", "reaction": "love it"}],
    }


def test_negotiate_returns_plan():
    fake = FakeClient(negotiation_queue=[json_body(plan_obj())])
    out = run(negotiate(group(["u01", "u04", "u10"]), interviews_for(["u01", "u04", "u10"]), client=fake))
    assert out["activity"] == "a relaxed chess night over coffee"
    assert len(out["common_ground"]) == 2


def test_negotiate_uses_persona_model_and_is_routed():
    fake = FakeClient(negotiation_queue=[json_body(plan_obj())])
    run(negotiate(group(["u01", "u04"]), interviews_for(["u01", "u04"]), client=fake))
    kind, kwargs = fake.calls[0]
    assert kind == "negotiation"
    assert kwargs["model"] == config.MODEL_CLAW


def test_negotiate_payload_includes_profiles_and_answers():
    fake = FakeClient(negotiation_queue=[json_body(plan_obj())])
    run(negotiate(group(["u01", "u04"]), interviews_for(["u01", "u04"]), client=fake))
    _, kwargs = fake.calls[0]
    payload = kwargs["messages"][0]["content"]
    assert "Maya" in payload and "Marcus" in payload
    assert "chess" in payload                 # a real hobby from the profile
    assert "wants low-key meetups" in payload  # the interview answer


def test_negotiate_falls_back_on_bad_json():
    fake = FakeClient(negotiation_queue=["not valid json"])
    out = run(negotiate(group(["u01", "u04"]), interviews_for(["u01", "u04"]), client=fake))
    assert out["activity"] == ""
    assert out["common_ground"] == []
