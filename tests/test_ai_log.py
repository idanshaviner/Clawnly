"""Tests for ai_log.py -- every Claude call logged verbatim."""

from types import SimpleNamespace

import pytest

import ai_log
import db
from conftest import FakeClient, json_body, reset_db, run


def test_every_call_is_logged_with_prompt_reply_and_purpose():
    reset_db()
    fake = FakeClient(card_queue=[json_body({"essence": "e"})])
    client = ai_log.LoggedClient(fake, run_id=7, neighborhood_id=3, resident_id=11)
    run(client.messages.create(model="m-1", max_tokens=10,
                               system="Turn it into the profile card their Clawnly agent will carry.",
                               messages=[{"role": "user", "content": "the pasted text"}]))
    calls = db.list_ai_calls(7)
    assert len(calls) == 1
    call = calls[0]
    assert call["purpose"] == "card"
    assert call["model"] == "m-1"
    assert "profile card" in call["system"]
    assert call["messages"] == [{"role": "user", "content": "the pasted text"}]
    assert call["reply"] == json_body({"essence": "e"})
    assert (call["neighborhood_id"], call["resident_id"], call["error"]) == (3, 11, None)
    assert call["ms"] >= 0
    assert client.counter == {"total": 1, "by_model": {"m-1": 1}}


def test_a_failed_call_is_logged_and_still_raised():
    reset_db()
    fake = FakeClient(fail_names=["Noa"])
    client = ai_log.LoggedClient(fake, run_id=8)
    with pytest.raises(RuntimeError):
        run(client.messages.create(model="m", system="You are the Clawnly agent of Noa. agent-to-agent conversation",
                                   messages=[{"role": "user", "content": "hi"}]))
    call = db.list_ai_calls(8)[0]
    assert call["purpose"] == "agent_turn"
    assert call["reply"] is None
    assert "simulated API failure" in call["error"]


def test_token_usage_is_recorded_when_the_reply_carries_it():
    reset_db()

    class Messages:
        async def create(self, **kwargs):
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")],
                                   usage=SimpleNamespace(input_tokens=120, output_tokens=40))

    client = ai_log.LoggedClient(SimpleNamespace(messages=Messages()), run_id=9)
    run(client.messages.create(model="m", system="Decide which agents talk next.", messages=[]))
    call = db.list_ai_calls(9)[0]
    assert (call["purpose"], call["input_tokens"], call["output_tokens"]) == ("pairing", 120, 40)


def test_purpose_of_knows_every_prompt_kind():
    assert ai_log.purpose_of("... should be invited to meet ...") == "verdict"
    assert ai_log.purpose_of("something else") == "other"
    assert ai_log.purpose_of(None) == "other"
