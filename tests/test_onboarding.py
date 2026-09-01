"""Tests for onboarding.py -- the real-resident onboarding chat + completeness
tracking (PILOT_PLAN.md stage 3)."""

import config
import db
import onboarding
from conftest import FakeClient, json_body, run
from users import USERS


def reset():
    db.reset_all(USERS)


def make_resident():
    nb = db.get_or_create_neighborhood("ballard", "Ballard", 100)
    return db.get_or_create_resident(nb["id"], "a@example.com", "magic_link")


def extraction_body(slots=None, fields=None):
    return json_body({"slots": slots or {}, "fields": fields or {}})


NO_SLOTS = {name: False for name in onboarding.SLOT_NAMES}
ALL_SLOTS = {name: True for name in onboarding.SLOT_NAMES}


# ----- take_turn: persistence -------------------------------------------------

def test_take_turn_persists_both_sides_of_the_exchange():
    reset()
    resident = make_resident()
    fake = FakeClient(onboarding_text="Hey! What are you into?",
                       extraction_queue=[extraction_body(NO_SLOTS)])
    result = run(onboarding.take_turn(resident, "hi there", client=fake))
    assert result["reply"] == "Hey! What are you into?"
    saved = db.get_onboarding_messages(resident["id"])
    assert saved == [
        {"role": "user", "content": "hi there"},
        {"role": "assistant", "content": "Hey! What are you into?"},
    ]


def test_take_turn_passes_full_prior_history_to_the_chat_call():
    reset()
    resident = make_resident()
    db.save_onboarding_message(resident["id"], "user", "earlier message")
    db.save_onboarding_message(resident["id"], "assistant", "earlier reply")
    fake = FakeClient(onboarding_text="got it",
                       extraction_queue=[extraction_body(NO_SLOTS)])
    run(onboarding.take_turn(resident, "second message", client=fake))
    kind, kwargs = fake.calls[0]
    assert kind == "onboarding_chat"
    sent = kwargs["messages"]
    assert len(sent) == 3    # 2 prior turns + the new message
    assert sent[-1]["content"] == "second message"


# ----- take_turn: extraction updates the profile -------------------------------

def test_take_turn_updates_profile_from_extracted_fields():
    reset()
    resident = make_resident()
    fields = {"name": "Sam", "age": 29, "hobbies": ["hiking", "pottery"],
              "availability": ["weekend_daytime"], "preferred_group_size": [2, 4]}
    fake = FakeClient(onboarding_text="reply",
                       extraction_queue=[extraction_body(NO_SLOTS, fields)])
    run(onboarding.take_turn(resident, "I'm Sam, I love hiking and pottery", client=fake))
    updated = db.get_resident(resident["id"])
    assert updated["name"] == "Sam"
    assert updated["age"] == 29
    assert updated["hobbies"] == ["hiking", "pottery"]
    assert updated["availability"] == ["weekend_daytime"]
    assert updated["preferred_group_size"] == [2, 4]
    assert updated["slots_status"] == NO_SLOTS


def test_invalid_extracted_hobbies_and_availability_are_dropped():
    reset()
    resident = make_resident()
    fields = {"hobbies": ["hiking", "made-up-hobby"], "availability": ["weekend_daytime", "midnight"]}
    fake = FakeClient(onboarding_text="reply",
                       extraction_queue=[extraction_body(NO_SLOTS, fields)])
    run(onboarding.take_turn(resident, "message", client=fake))
    updated = db.get_resident(resident["id"])
    assert updated["hobbies"] == ["hiking"]              # made-up-hobby dropped
    assert updated["availability"] == ["weekend_daytime"]  # midnight dropped


def test_entirely_invalid_hobbies_leaves_the_field_untouched():
    reset()
    resident = make_resident()
    fake = FakeClient(onboarding_text="reply",
                       extraction_queue=[extraction_body(NO_SLOTS, {"hobbies": ["not-a-real-hobby"]})])
    run(onboarding.take_turn(resident, "message", client=fake))
    updated = db.get_resident(resident["id"])
    assert updated["hobbies"] is None


def test_invalid_group_size_is_dropped():
    reset()
    resident = make_resident()
    fake = FakeClient(onboarding_text="reply",
                       extraction_queue=[extraction_body(NO_SLOTS, {"preferred_group_size": [9, 12]})])
    run(onboarding.take_turn(resident, "message", client=fake))
    updated = db.get_resident(resident["id"])
    assert updated["preferred_group_size"] is None


# ----- take_turn: completeness ---------------------------------------------

def test_take_turn_not_complete_with_partial_slots():
    reset()
    resident = make_resident()
    slots = dict(ALL_SLOTS)
    slots["seeking"] = False
    fake = FakeClient(onboarding_text="reply", extraction_queue=[extraction_body(slots)])
    result = run(onboarding.take_turn(resident, "message", client=fake))
    assert result["complete"] is False
    assert db.get_resident(resident["id"])["profile_complete_at"] is None


def test_take_turn_marks_complete_when_all_five_slots_are_filled():
    reset()
    resident = make_resident()
    fake = FakeClient(onboarding_text="reply", extraction_queue=[extraction_body(ALL_SLOTS)])
    result = run(onboarding.take_turn(resident, "message", client=fake))
    assert result["complete"] is True
    assert db.get_resident(resident["id"])["profile_complete_at"] is not None


def test_take_turn_force_completes_at_the_turn_cap():
    reset()
    resident = make_resident()
    n = 0
    while n < onboarding.MAX_ONBOARDING_TURNS - 1:
        db.save_onboarding_message(resident["id"], "user", "turn " + str(n))
        db.save_onboarding_message(resident["id"], "assistant", "reply " + str(n))
        n += 1
    # this is the 20th user turn -- still no slots filled, but the cap forces completion.
    fake = FakeClient(onboarding_text="ok",
                       extraction_queue=[extraction_body(NO_SLOTS)])
    result = run(onboarding.take_turn(resident, "final message", client=fake))
    assert result["complete"] is True
    assert db.get_resident(resident["id"])["profile_complete_at"] is not None


def test_take_turn_uses_the_cheap_completeness_model():
    reset()
    resident = make_resident()
    fake = FakeClient(onboarding_text="reply", extraction_queue=[extraction_body(NO_SLOTS)])
    run(onboarding.take_turn(resident, "message", client=fake))
    kind, kwargs = fake.calls[1]
    assert kind == "onboarding_extract"
    assert kwargs["model"] == config.MODEL_ONBOARDING_COMPLETENESS


def test_extraction_failure_does_not_lose_the_already_persisted_reply(capsys):
    reset()
    resident = make_resident()

    class FlakyMessages:
        def __init__(self, chat_reply):
            self.chat_reply = chat_reply
            self.calls = 0

        async def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return type("R", (), {"content": [type("B", (), {"type": "text", "text": self.chat_reply})()]})()
            raise RuntimeError("simulated extraction outage")

    class FlakyClient:
        def __init__(self, chat_reply):
            self.messages = FlakyMessages(chat_reply)

    fake = FlakyClient("hi there!")
    result = run(onboarding.take_turn(resident, "hello", client=fake))
    # the reply still comes back -- a bookkeeping hiccup is not surfaced as a turn failure.
    assert result["reply"] == "hi there!"
    assert result["complete"] is False
    # both sides of the exchange are still persisted even though extraction failed.
    assert db.get_onboarding_messages(resident["id"]) == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there!"},
    ]
    assert "extraction call failed" in capsys.readouterr().out


def test_default_client_falls_back_to_config_get_client(monkeypatch):
    reset()
    resident = make_resident()
    fake = FakeClient(onboarding_text="reply", extraction_queue=[extraction_body(NO_SLOTS)])
    monkeypatch.setattr(config, "get_client", lambda: fake)
    result = run(onboarding.take_turn(resident, "message"))
    assert result["reply"] == "reply"
