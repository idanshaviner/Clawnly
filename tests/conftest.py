"""Shared test fixtures: a fake Anthropic client (zero real API calls).

The fake mimics `AsyncAnthropic`: it exposes `.messages.create(**kwargs)` as an
async method and routes each call to interview / match / popup based on the
request shape, so the entire pipeline can be exercised offline. Test code is
idiomatic Python; the no-ternary / no-comprehension style rules in SPEC 10
apply to the shipped modules, not to tests.
"""

import asyncio
import json
import os
from types import SimpleNamespace

# isolate the test database from the real clawnly.db a manual run would create.
# Must happen before db.py (or app.py, which imports it) is first imported --
# conftest.py is always loaded before test modules, so this is early enough.
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("CLAWNLY_DB_PATH", os.path.join(_TESTS_DIR, "test_clawnly.db"))

import config


def text_response(text):
    """Build an object shaped like an Anthropic message with one text block."""
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def json_body(obj):
    """Serialize obj to the full JSON the model would return (no prefill trick)."""
    return json.dumps(obj)


class FakeMessages:
    def __init__(self, outer):
        self.outer = outer

    async def create(self, **kwargs):
        outer = self.outer
        messages = kwargs.get("messages", [])
        system = kwargs.get("system", "")
        low = system.lower()

        # route by distinctive markers in the system prompt (assistant-prefill is
        # no longer used, so every call ends with a user message).
        # agent-to-agent orchestration first: its prompts are the newest.
        if "profile card their clawnly agent will carry" in low:
            outer.calls.append(("card", kwargs))
            if outer.card_fn is not None:
                return text_response(outer.card_fn(system, messages[-1]["content"]))
            return text_response(outer.card_queue.pop(0))
        if "agent-to-agent conversation" in low:
            outer.calls.append(("agent_turn", kwargs))
            for name in outer.fail_names:
                if ("Clawnly agent of " + name + ".") in system:
                    raise RuntimeError("simulated API failure for " + name)
            return text_response(outer.agent_fn(system, messages[-1]["content"]))
        if "decide which agents talk next" in low:
            outer.calls.append(("pairing", kwargs))
            return text_response(outer.pairing_queue.pop(0))
        if "should be invited to meet" in low:
            outer.calls.append(("verdict", kwargs))
            if outer.verdict_fn is not None:
                return text_response(outer.verdict_fn(system, messages[-1]["content"]))
            return text_response(outer.verdict_queue.pop(0))
        if "actual human on the other end" in low:
            # a real (simulated=False) resident's onboarding chat reply.
            outer.calls.append(("onboarding_chat", kwargs))
            content = messages[-1]["content"]
            answer = outer.onboarding_text
            if outer.onboarding_fn is not None:
                answer = outer.onboarding_fn(system, content)
            return text_response(answer)
        if "personality_energy" in low:
            # the per-turn slot-completeness + field-extraction call.
            outer.calls.append(("onboarding_extract", kwargs))
            return text_response(outer.extraction_queue.pop(0))
        if "embody this character" in low:
            # a Claw persona call (interview describe/batch, or free-style chat)
            outer.calls.append(("interview", kwargs))
            for name in outer.fail_names:
                if ("You ARE " + name) in system:
                    raise RuntimeError("simulated API failure for " + name)
            content = messages[-1]["content"]
            answer = outer.interview_text
            if outer.interview_fn is not None:
                answer = outer.interview_fn(system, content)
            # a batched interview asks for two "===" separated answers
            if "Separate your two answers" in content:
                return text_response(answer + "\n===\n" + answer)
            return text_response(answer)
        if kwargs.get("model") == config.MODEL_MATCH or "form one meetup" in low:
            # route the match by model OR its unique marker (fast mode uses Sonnet)
            outer.calls.append(("match", kwargs))
            return text_response(outer.match_queue.pop(0))
        if "joint activity" in low:
            outer.calls.append(("propose", kwargs))
            return text_response(outer.propose_queue.pop(0))
        if "on board" in low:
            outer.calls.append(("assess", kwargs))
            return text_response(outer.assess_queue.pop(0))
        if "just ran this matching" in low:
            outer.calls.append(("explain", kwargs))
            return text_response(outer.explain_queue.pop(0))
        if "revise a person's profile" in low:
            outer.calls.append(("nudge", kwargs))
            return text_response(outer.nudge_queue.pop(0))
        if "generate simulated user" in low:
            outer.calls.append(("generation", kwargs))
            return text_response(outer.generation_queue.pop(0))
        outer.calls.append(("popup", kwargs))
        return text_response(outer.popup_queue.pop(0))


class FakeClient:
    """Configurable stand-in for AsyncAnthropic.

    - interview_text / interview_fn: what Claws return when interviewed / reacting
    - match_queue / popup_queue / propose_queue / assess_queue / generation_queue:
      FIFO canned replies for those call types
    - fail_names: persona names whose interview (or agent-turn) call should raise
    - card_queue / card_fn, agent_fn, pairing_queue, verdict_queue / verdict_fn:
      the agent-to-agent orchestration calls (dossier / agent_talk / orchestrator)
    - calls: every call recorded as (kind, kwargs) for assertions
    """

    def __init__(self, interview_text="canned interview answer", interview_fn=None,
                 match_queue=None, popup_queue=None, propose_queue=None,
                 assess_queue=None, explain_queue=None, generation_queue=None,
                 nudge_queue=None, fail_names=None,
                 onboarding_text="canned onboarding reply", onboarding_fn=None,
                 extraction_queue=None, card_queue=None, card_fn=None, agent_fn=None,
                 pairing_queue=None, verdict_queue=None, verdict_fn=None):
        self.interview_text = interview_text
        self.interview_fn = interview_fn
        self.match_queue = list(match_queue or [])
        self.popup_queue = list(popup_queue or [])
        self.propose_queue = list(propose_queue or [])
        self.assess_queue = list(assess_queue or [])
        self.explain_queue = list(explain_queue or [])
        self.generation_queue = list(generation_queue or [])
        self.nudge_queue = list(nudge_queue or [])
        self.fail_names = set(fail_names or [])
        self.onboarding_text = onboarding_text
        self.onboarding_fn = onboarding_fn
        self.extraction_queue = list(extraction_queue or [])
        self.card_queue = list(card_queue or [])
        self.card_fn = card_fn
        self.agent_fn = agent_fn or (lambda system, content: "canned agent message")
        self.pairing_queue = list(pairing_queue or [])
        self.verdict_queue = list(verdict_queue or [])
        self.verdict_fn = verdict_fn
        self.calls = []
        self.messages = FakeMessages(self)

    def kinds(self):
        return [kind for kind, _ in self.calls]


def run(coro):
    """Run an async coroutine from a synchronous test."""
    return asyncio.run(coro)
