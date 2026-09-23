"""Shared test fixtures: a fake Anthropic client (zero real API calls) and a
helper for creating a resident who has joined with their agent.

The fake mimics `AsyncAnthropic`: it exposes `.messages.create(**kwargs)` as an
async method and routes each call by a marker phrase in its system prompt --
card (dossier.py), agent turn (agent_talk.py), pairing and verdict
(orchestrator.py). Test code is idiomatic Python; the no-ternary /
no-comprehension style rules apply to the shipped modules, not to tests.
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

import db
import dossier


def text_response(text):
    """Build an object shaped like an Anthropic message with one text block."""
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def json_body(obj):
    """Serialize obj to the full JSON the model would return."""
    return json.dumps(obj)


class FakeMessages:
    def __init__(self, outer):
        self.outer = outer

    async def create(self, **kwargs):
        outer = self.outer
        messages = kwargs.get("messages", [])
        system = kwargs.get("system", "")
        low = system.lower()
        content = messages[-1]["content"]

        if "profile card their clawnly agent will carry" in low:
            outer.calls.append(("card", kwargs))
            if outer.card_fn is not None:
                return text_response(outer.card_fn(system, content))
            return text_response(outer.card_queue.pop(0))
        if "agent-to-agent conversation" in low:
            outer.calls.append(("agent_turn", kwargs))
            for name in outer.fail_names:
                if ("Clawnly agent of " + name + ".") in system:
                    raise RuntimeError("simulated API failure for " + name)
            return text_response(outer.agent_fn(system, content))
        if "decide which agents talk next" in low:
            outer.calls.append(("pairing", kwargs))
            return text_response(outer.pairing_queue.pop(0))
        if "should be invited to meet" in low:
            outer.calls.append(("verdict", kwargs))
            if outer.verdict_fn is not None:
                return text_response(outer.verdict_fn(system, content))
            return text_response(outer.verdict_queue.pop(0))
        raise AssertionError("FakeClient got an unrecognised call: " + system[:120])


class FakeClient:
    """Configurable stand-in for AsyncAnthropic.

    - card_queue / card_fn: dossier.build_card replies
    - agent_fn(system, content): one Claw's message in an agent-to-agent conversation
    - pairing_queue: the hub's pairing replies
    - verdict_queue / verdict_fn: the hub's verdict replies
    - fail_names: people whose agent-turn call should raise
    - calls: every call recorded as (kind, kwargs) for assertions
    """

    def __init__(self, card_queue=None, card_fn=None, agent_fn=None, pairing_queue=None,
                 verdict_queue=None, verdict_fn=None, fail_names=None):
        self.card_queue = list(card_queue or [])
        self.card_fn = card_fn
        self.agent_fn = agent_fn or (lambda system, content: "canned agent message")
        self.pairing_queue = list(pairing_queue or [])
        self.verdict_queue = list(verdict_queue or [])
        self.verdict_fn = verdict_fn
        self.fail_names = set(fail_names or [])
        self.calls = []
        self.messages = FakeMessages(self)

    def kinds(self):
        return [kind for kind, _ in self.calls]


def run(coro):
    """Run an async coroutine from a synchronous test."""
    return asyncio.run(coro)


def reset_db():
    db.init_db()
    db.reset_all()


DOSSIER = ("You're someone real with a real life: new in town, missing a regular table of friends, "
           "honest to a fault, free on Sunday mornings. ") * 5


def make_joined_resident(neighborhood, email, name, source="ChatGPT", card=None, text=DOSSIER):
    """A consented resident who has brought their agent (dossier + card) and joined."""
    resident = db.get_or_create_resident(neighborhood["id"], email, "magic_link")
    db.record_consent(resident["id"])
    if card is None:
        card = {"essence": name + " is real", "free": "Sunday mornings", "area": neighborhood["name"]}
    db.save_dossier_draft(resident["id"], name, source, text, dossier.clean_card(card))
    db.mark_profile_complete(resident["id"])
    return db.get_resident(resident["id"])
