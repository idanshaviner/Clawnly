"""Every call to Claude, logged verbatim.

LoggedClient wraps any Anthropic-shaped client. Each messages.create() is
written to db.ai_calls -- what it was for, the model, the exact system
prompt and messages, the raw reply text, tokens, how long it took, and any
error -- and counted by model for the round's usage meter. Nothing about the
call itself changes; a failed call is logged and then re-raised.

Used for every hub round (orchestrator.run_round) and every signup card
(bring_agent.preview), so no Claude call in the product goes unrecorded.
"""

import time

import db
from llm_io import join_text


# the same marker phrases each prompt carries (and tests/conftest.py routes on)
PURPOSES = [
    ["profile card their clawnly agent will carry", "card"],
    ["agent-to-agent conversation", "agent_turn"],
    ["decide which agents talk next", "pairing"],
    ["should be invited to meet", "verdict"],
]


def purpose_of(system):
    low = str(system or "").lower()
    i = 0
    while i < len(PURPOSES):
        if PURPOSES[i][0] in low:
            return PURPOSES[i][1]
        i += 1
    return "other"


def _usage_numbers(message):
    # (input_tokens, output_tokens); None when the reply carries no usage (e.g. a test fake)
    usage = getattr(message, "usage", None)
    if usage is None:
        return None, None
    return getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None)


class _LoggedMessages:
    def __init__(self, inner, owner):
        self._inner = inner
        self._owner = owner

    async def create(self, **kwargs):
        owner = self._owner
        model = kwargs.get("model", "?")
        system = kwargs.get("system", "")
        messages = kwargs.get("messages", [])
        owner.counter["total"] += 1
        by_model = owner.counter["by_model"]
        by_model[model] = by_model.get(model, 0) + 1
        started = time.monotonic()
        try:
            message = await self._inner.create(**kwargs)
        except Exception as error:
            ms = int((time.monotonic() - started) * 1000)
            db.log_ai_call(owner.run_id, owner.neighborhood_id, owner.resident_id, purpose_of(system),
                           model, system, messages, None, None, None, ms, str(error))
            raise
        ms = int((time.monotonic() - started) * 1000)
        input_tokens, output_tokens = _usage_numbers(message)
        db.log_ai_call(owner.run_id, owner.neighborhood_id, owner.resident_id, purpose_of(system),
                       model, system, messages, join_text(message), input_tokens, output_tokens, ms, None)
        return message


class LoggedClient:
    def __init__(self, inner, run_id=None, neighborhood_id=None, resident_id=None):
        self.run_id = run_id
        self.neighborhood_id = neighborhood_id
        self.resident_id = resident_id
        self.counter = {"total": 0, "by_model": {}}
        self.messages = _LoggedMessages(inner.messages, self)
