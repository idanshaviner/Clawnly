"""Tests for the Claw persona agent (SPEC F2)."""

import config
from claw import Claw
from conftest import FakeClient, run
from users import USERS


def find(uid):
    for u in USERS:
        if u["id"] == uid:
            return u
    raise KeyError(uid)


def test_describe_returns_text():
    claw = Claw(find("u01"), client=FakeClient(interview_text="hello from Maya"))
    out = run(claw.describe("what are you after socially?"))
    assert out == "hello from Maya"


def test_describe_uses_cheap_interview_model():
    fake = FakeClient()
    claw = Claw(find("u01"), client=fake)
    run(claw.describe("q"))
    kind, kwargs = fake.calls[0]
    assert kind == "interview"
    assert kwargs["model"] == config.MODEL_INTERVIEW      # Haiku, the cheap model
    assert kwargs["temperature"] == config.TEMP_PERSONA


def test_interview_both_single_call_two_answers():
    fake = FakeClient(interview_text="my answer")
    claw = Claw(find("u01"), client=fake)
    q1, q2 = run(claw.interview_both("what are you after?", "when are you free?"))
    assert q1 == "my answer" and q2 == "my answer"
    interview_calls = [k for k in fake.kinds() if k == "interview"]
    assert len(interview_calls) == 1                       # both answers, ONE call
    assert fake.calls[0][1]["model"] == config.MODEL_INTERVIEW


def test_interview_both_falls_back_when_no_separator():
    # if the model omits the "===" separator, fall back to two separate calls.
    from types import SimpleNamespace

    class Msgs:
        def __init__(self):
            self.n = 0

        async def create(self, **kwargs):
            self.n += 1
            content = kwargs["messages"][-1]["content"]
            if "Separate your two answers" in content:
                text = "one blob, no separator"     # forces the fallback
            else:
                text = "fallback ans"
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])

    class Client:
        def __init__(self):
            self.messages = Msgs()

    client = Client()
    claw = Claw(find("u01"), client=client)
    q1, q2 = run(claw.interview_both("q1", "q2"))
    assert q1 == "fallback ans" and q2 == "fallback ans"
    assert client.messages.n == 3                    # 1 batched (failed) + 2 fallback


def test_chat_uses_richer_model():
    fake = FakeClient(interview_text="hey")
    claw = Claw(find("u01"), client=fake)
    run(claw.chat("hi"))
    assert fake.calls[0][1]["model"] == config.MODEL_CLAW   # Sonnet for chat


def test_chat_includes_history():
    fake = FakeClient(interview_text="sure, sounds good")
    claw = Claw(find("u01"), client=fake)
    history = [
        {"role": "user", "content": "hey Maya"},
        {"role": "assistant", "content": "hi there!"},
    ]
    reply = run(claw.chat("want to grab coffee?", history))
    assert reply == "sure, sounds good"
    _, kwargs = fake.calls[0]
    sent = kwargs["messages"]
    assert len(sent) == 3                       # history + the new message
    assert sent[-1]["content"] == "want to grab coffee?"


def test_chat_does_not_mutate_history():
    fake = FakeClient(interview_text="ok")
    claw = Claw(find("u01"), client=fake)
    history = []
    run(claw.chat("hello", history))
    assert history == []                        # caller's history left untouched


def test_system_prompt_embeds_full_profile():
    user = find("u01")
    claw = Claw(user, client=FakeClient())
    prompt = claw._system_prompt()
    assert user["name"] in prompt
    assert "weekday_evening" in prompt           # availability window
    assert user["location"] in prompt
    assert user["hobbies"][0] in prompt
    assert "first person" in prompt.lower()


def test_size_text_range_branch():
    claw = Claw(find("u01"), client=FakeClient())  # Maya = [2, 3]
    assert "2 to 3" in claw._size_text()


def test_size_text_no_preference_branch():
    claw = Claw(find("u03"), client=FakeClient())  # Priya = no preference
    assert "no strong preference" in claw._size_text()


def test_question_is_passed_through():
    fake = FakeClient()
    claw = Claw(find("u02"), client=fake)
    run(claw.describe("a very specific question"))
    _, kwargs = fake.calls[0]
    assert kwargs["messages"][0]["content"] == "a very specific question"


# ----- simulated=False: real-resident onboarding mode (PILOT_PLAN stage 3) ----

def _blank_resident(**overrides):
    resident = {"id": 1, "name": None, "age": None, "gender": None, "hobbies": None,
                "personality": None, "occupation": None, "availability": None,
                "location": None, "bio": None, "preferred_group_size": None}
    resident.update(overrides)
    return resident


def test_simulated_defaults_to_true_and_is_unchanged():
    # regression guard: every existing call site/test gets today's behavior.
    claw = Claw(find("u01"), client=FakeClient())
    assert claw.simulated is True
    prompt = claw._system_prompt()
    assert "embody this character" in prompt


def test_real_mode_never_invents_and_uses_the_onboarding_style():
    claw = Claw(_blank_resident(name="Sam"), client=FakeClient(), simulated=False)
    prompt = claw._system_prompt()
    assert "fully invent" not in prompt.lower()
    assert "embody this character" not in prompt.lower()
    assert "REAL person" in prompt
    assert "Name: Sam" in prompt
    assert "Age:" not in prompt          # unknown fields are omitted, not invented


def test_real_mode_with_no_known_facts_says_so_plainly():
    claw = Claw(_blank_resident(), client=FakeClient(), simulated=False)
    prompt = claw._system_prompt()
    assert "nothing yet" in prompt.lower()


def test_real_mode_size_text_not_invoked_when_group_size_unknown():
    # preferred_group_size is None for a brand-new resident -- must not crash
    # the way the simulated _size_text() would on a None value.
    claw = Claw(_blank_resident(), client=FakeClient(), simulated=False)
    claw._system_prompt()   # no exception


def test_real_mode_chat_uses_the_onboarding_model_and_style():
    fake = FakeClient(onboarding_text="Nice to meet you, Sam!")
    claw = Claw(_blank_resident(name="Sam"), client=fake, simulated=False)
    reply = run(claw.chat("hi"))
    assert reply == "Nice to meet you, Sam!"
    kind, kwargs = fake.calls[0]
    assert kind == "onboarding_chat"
    assert kwargs["model"] == config.MODEL_ONBOARDING_CHAT
