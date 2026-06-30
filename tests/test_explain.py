"""Tests for the Master Claw explaining its own decisions (explain.py)."""

from conftest import FakeClient, run
from explain import explain_decision, context_summary


def sample_run():
    return {
        "interviews": {
            "u01": {"profile": {"name": "Maya"}},
            "u04": {"profile": {"name": "Marcus"}},
            "u08": {"profile": {"name": "Ethan"}},
        },
        "groups": [{
            "match": {
                "group": ["u01", "u04"],
                "reason": "Maya and Marcus are both calm weekday-evening people.",
                "scores": {"personality": 4, "availability": 5},
                "why_not": [{"id": "u08", "reason": "Ethan wants a group of 6-8."}],
            },
            "negotiation": {"activity": "a chess night", "rounds": 1, "agreed": True},
        }],
        "unmatched": ["u08"],
    }


def test_context_summary_uses_names_and_facts():
    text = context_summary(sample_run())
    assert "Maya" in text and "Marcus" in text
    assert "Ethan" in text                              # appears in the leftover list
    assert "chess night" in text                       # the negotiation outcome


def test_explain_returns_text_grounded_in_the_record():
    fake = FakeClient(explain_queue=["I paired Maya and Marcus because they're both calm."])
    out = run(explain_decision("why those two?", sample_run(), client=fake))
    assert out == "I paired Maya and Marcus because they're both calm."
    kind, kwargs = fake.calls[0]
    assert kind == "explain"
    # the run record was injected into the system prompt
    assert "Maya" in kwargs["system"] and "calm weekday-evening" in kwargs["system"]


def test_explain_passes_history():
    fake = FakeClient(explain_queue=["because of their schedules"])
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    run(explain_decision("and the timing?", sample_run(), history=history, client=fake))
    _, kwargs = fake.calls[0]
    sent = kwargs["messages"]
    assert len(sent) == 3 and sent[-1]["content"] == "and the timing?"
