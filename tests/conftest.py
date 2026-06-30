"""Shared test fixtures: a fake Anthropic client (zero real API calls).

The fake mimics `AsyncAnthropic`: it exposes `.messages.create(**kwargs)` as an
async method and routes each call to interview / match / popup based on the
request shape, so the entire pipeline can be exercised offline. Test code is
idiomatic Python; the no-ternary / no-comprehension style rules in SPEC 10
apply to the shipped modules, not to tests.
"""

import asyncio
import json
from types import SimpleNamespace

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
    - fail_names: persona names whose interview call should raise
    - calls: every call recorded as (kind, kwargs) for assertions
    """

    def __init__(self, interview_text="canned interview answer", interview_fn=None,
                 match_queue=None, popup_queue=None, propose_queue=None,
                 assess_queue=None, explain_queue=None, generation_queue=None,
                 nudge_queue=None, fail_names=None):
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
        self.calls = []
        self.messages = FakeMessages(self)

    def kinds(self):
        return [kind for kind, _ in self.calls]


def run(coro):
    """Run an async coroutine from a synchronous test."""
    return asyncio.run(coro)
