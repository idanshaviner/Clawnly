"""Tests for the free-style chat helpers and conversational Claw."""

from conftest import FakeClient, run
import chat
from claw import Claw
from users import USERS


def test_roster_lists_all_personas():
    text = chat.roster()
    i = 0
    while i < len(USERS):
        assert USERS[i]["name"] in text
        i += 1


def test_find_persona_by_number():
    assert chat.find_persona("1")["name"] == USERS[0]["name"]
    assert chat.find_persona("12")["name"] == USERS[11]["name"]


def test_find_persona_by_name_case_insensitive():
    assert chat.find_persona("maya")["id"] == "u01"
    assert chat.find_persona("MARCUS")["id"] == "u04"


def test_find_persona_invalid_returns_none():
    assert chat.find_persona("99") is None
    assert chat.find_persona("nobody") is None


def test_claw_chat_includes_history():
    fake = FakeClient(interview_text="sure, sounds good")
    claw = Claw(USERS[0], client=fake)
    history = [
        {"role": "user", "content": "hey Maya"},
        {"role": "assistant", "content": "hi there!"},
    ]
    reply = run(claw.chat("want to grab coffee?", history))
    assert reply == "sure, sounds good"
    # the call should carry the prior turns plus the new message.
    _, kwargs = fake.calls[0]
    sent = kwargs["messages"]
    assert len(sent) == 3
    assert sent[-1]["content"] == "want to grab coffee?"


def test_claw_chat_does_not_mutate_history():
    fake = FakeClient(interview_text="ok")
    claw = Claw(USERS[0], client=fake)
    history = []
    run(claw.chat("hello", history))
    assert history == []        # caller's history is left untouched
