"""Tests for orchestrator.py -- the hub: pick pairs, run agent conversations,
judge them, and gate invitations in code."""

import json

import db
import orchestrator
from conftest import FakeClient, json_body, run

LONG = "You are someone real with a real life and real needs from friends. " * 10


def reset():
    db.init_db()
    db.reset_all()


def people():
    names = [("s1", "Noa"), ("s2", "Marcus"), ("s3", "Priya"), ("s4", "Jonah")]
    out = []
    for pid, name in names:
        out.append({"id": pid, "name": name, "source": "ChatGPT", "dossier": name + " DOSSIER. " + LONG})
    return out


def card_fn(system, content):
    return json_body({"essence": "someone real", "free": "Sundays", "area": "Seattle",
                      "real_vs_public": {"score": 4, "note": "fairly real"}})


def speaker_fn(system, content):
    name = system.split("Clawnly agent of ")[1].split(".")[0]
    return name + " needs friends who show up every single week without fail."


def verdict_for(strong_pair):
    # recommend only the named pair; cite one real quote, one real, one invented.
    def fn(system, content):
        strong = strong_pair in system
        depth = 5
        if strong:
            depth = 9
        return json_body({
            "thoughts": "reasoning", "depth": depth, "recommend": strong, "headline": "headline",
            "evidence": [
                {"quote": "needs friends who show up every single week", "why": "consistency"},
                {"quote": "show up every single week without fail", "why": "reliability"},
                {"quote": "they both secretly love opera", "why": "invented"},
            ],
            "tensions": ["risk"],
            "invite": {"activity": "dinner", "when": "Sunday", "where": "Seattle", "to_a": "a", "to_b": "b"},
        })
    return fn


def pairing(pairs, thoughts="pool thoughts"):
    return json_body({"thoughts": thoughts, "pairs": pairs})


# ----- pure checks ----------------------------------------------------------------

def test_clean_pairs_rejects_what_the_rules_forbid():
    by_id = {}
    for p in people():
        by_id[p["id"]] = p
    raw = [
        {"a": "s1", "b": "s2", "why": "ok"},
        {"a": "s2", "b": "s1", "why": "duplicate, silently skipped"},
        {"a": "s1", "b": "s1", "why": "self"},
        {"a": "s1", "b": "zz", "why": "unknown"},
        {"a": "s3", "b": "s4", "why": "already talked"},
        {"a": "s1", "b": "s3", "why": "ok"},
        {"a": "s1", "b": "s4", "why": "s1 over the limit"},
        "not a dict",
    ]
    pairs, rejected = orchestrator.clean_pairs(raw, by_id, {orchestrator.pair_key("s3", "s4")})
    assert [(p["a"], p["b"]) for p in pairs] == [("s1", "s2"), ("s1", "s3")]
    assert len(rejected) == 5
    assert any("paired with themselves" in r for r in rejected)
    assert any("unknown id" in r for r in rejected)
    assert any("already talked" in r for r in rejected)
    assert any("per-person limit" in r for r in rejected)


def test_clean_pairs_handles_a_missing_list():
    pairs, rejected = orchestrator.clean_pairs(None, {}, set())
    assert pairs == [] and rejected == ["hub returned no pair list"]


def test_verify_evidence_keeps_only_verbatim_quotes():
    transcript = "Noa's agent: Noa misses Friday dinners — a long table, too much food."
    kept, dropped = orchestrator.verify_evidence([
        {"quote": "misses Friday dinners - a long table", "why": "punctuation differences are fine"},
        {"quote": "Noa loves opera and skydiving", "why": "invented"},
        {"quote": "Noa", "why": "too short to count"},
        {"no": "quote"},
    ], transcript)
    assert [k["quote"] for k in kept] == ["misses Friday dinners - a long table"]
    assert dropped == ["Noa loves opera and skydiving", "Noa"]


def test_gate_needs_recommend_depth_and_verified_quotes():
    two = [{"quote": "a"}, {"quote": "b"}]
    assert orchestrator.gate({"recommend": True, "depth": 9}, two) == (9, [])
    depth, reasons = orchestrator.gate({"recommend": True, "depth": 7}, two)
    assert reasons == ["depth 7 < 8"]
    depth, reasons = orchestrator.gate({"recommend": False, "depth": 9}, two)
    assert reasons == ["hub did not recommend"]
    depth, reasons = orchestrator.gate({"recommend": True, "depth": 9}, two[:1])
    assert reasons == ["only 1 verified quote(s), need 2"]
    depth, reasons = orchestrator.gate({"recommend": "yes", "depth": "9"}, two)
    assert depth == 0 and len(reasons) == 2


# ----- a full round ------------------------------------------------------------------

def test_full_round_pairs_talks_judges_and_invites_only_through_the_gate():
    reset()
    client = FakeClient(
        card_fn=card_fn, agent_fn=speaker_fn,
        pairing_queue=[pairing([{"a": "s1", "b": "s2", "why": "tables"}, {"a": "s3", "b": "s4", "why": "maybe"},
                                {"a": "s1", "b": "s1", "why": "bad"}])],
        verdict_fn=verdict_for("Noa\nand Marcus"),
    )
    streamed = []
    result = run(orchestrator.run_round(people(), client=client, on_event=streamed.append))

    kinds = client.kinds()
    assert kinds.count("card") == 4
    assert kinds.count("pairing") == 1
    assert kinds.count("agent_turn") == 12
    assert kinds.count("verdict") == 2

    assert len(result["conversations"]) == 2
    assert len(result["invitations"]) == 1
    invited = result["invitations"][0]
    assert (invited["a"], invited["b"]) == ("s1", "s2")
    assert invited["verdict"]["depth"] == 9
    assert len(invited["verdict"]["evidence"]) == 2
    assert invited["verdict"]["dropped"] == ["they both secretly love opera"]

    # everything is persisted: conversations with turns + verdicts, and the log
    saved = db.list_agent_conversations(result["run_id"])
    assert len(saved) == 2
    assert all(len(c["turns"]) == 6 for c in saved)
    assert sorted(c["invited"] for c in saved) == [False, True]
    events = db.list_events(result["run_id"])
    texts = [e["text"] for e in events]
    assert any(e["kind"] == "thought" and e["text"] == "pool thoughts" for e in events)
    assert any("paired with themselves" in t for t in texts)
    assert any("Discarded 1 evidence quote" in t for t in texts)
    assert any("Gate passed for Noa + Marcus" in t for t in texts)
    assert any("No invitation for Priya + Jonah" in t for t in texts)
    assert sum(1 for e in events if e["kind"] == "message") == 12
    assert len(streamed) == len(events)


def test_hub_never_pairs_the_same_agents_twice():
    reset()
    everyone = people()
    first = FakeClient(card_fn=card_fn, agent_fn=speaker_fn,
                       pairing_queue=[pairing([{"a": "s1", "b": "s2", "why": "x"}])],
                       verdict_fn=verdict_for("nobody"))
    run(orchestrator.run_round(everyone, client=first))
    second = FakeClient(card_fn=card_fn, agent_fn=speaker_fn,
                        pairing_queue=[pairing([{"a": "s2", "b": "s1", "why": "again"}, {"a": "s3", "b": "s4", "why": "new"}])],
                        verdict_fn=verdict_for("nobody"))
    result = run(orchestrator.run_round(everyone, client=second))
    assert [(c["a"], c["b"]) for c in result["conversations"]] == [("s3", "s4")]
    # cards built in round 1 are reused, and round 2 tells the hub who already talked
    assert "card" not in second.kinds()
    assert "s1|s2" in second.calls[0][1]["messages"][0]["content"]
    texts = [e["text"] for e in db.list_events(result["run_id"])]
    assert any("already talked" in t for t in texts)


def test_one_failed_conversation_does_not_sink_the_round():
    reset()
    client = FakeClient(card_fn=card_fn, agent_fn=speaker_fn, fail_names=["Priya"],
                        pairing_queue=[pairing([{"a": "s1", "b": "s2", "why": "x"}, {"a": "s3", "b": "s4", "why": "y"}])],
                        verdict_fn=verdict_for("Noa\nand Marcus"))
    result = run(orchestrator.run_round(people(), client=client))
    assert len(result["invitations"]) == 1
    failed = [c for c in result["conversations"] if c.get("error")]
    assert len(failed) == 1 and failed[0]["a"] == "s3"
    texts = [e["text"] for e in db.list_events(result["run_id"])]
    assert any("Conversation Priya + Jonah failed" in t for t in texts)


def test_newcomers_are_named_to_the_hub():
    reset()
    client = FakeClient(card_fn=card_fn, agent_fn=speaker_fn, pairing_queue=[pairing([])])
    run(orchestrator.run_round(people(), client=client))
    payload = client.calls[-1][1]["messages"][0]["content"]
    assert "New arrivals" in payload and "s1" in payload


def test_fewer_than_two_people_skips_pairing():
    reset()
    client = FakeClient(card_fn=card_fn)
    result = run(orchestrator.run_round(people()[:1], client=client))
    assert "pairing" not in client.kinds()
    assert result["conversations"] == []


# ----- logs: every Claude call, usage, and failures -----------------------------------

def test_every_round_call_is_logged_verbatim_with_usage():
    reset()
    client = FakeClient(card_fn=card_fn, agent_fn=speaker_fn,
                        pairing_queue=[pairing([{"a": "s1", "b": "s2", "why": "x"}])],
                        verdict_fn=verdict_for("Noa\nand Marcus"))
    result = run(orchestrator.run_round(people(), client=client))
    calls = db.list_ai_calls(result["run_id"])
    assert len(calls) == len(client.calls)
    purposes = [c["purpose"] for c in calls]
    assert purposes.count("card") == 4 and purposes.count("pairing") == 1
    assert purposes.count("agent_turn") == 6 and purposes.count("verdict") == 1
    assert all(c["reply"] for c in calls)
    assert result["usage"]["total"] == len(client.calls)
    assert db.get_run(result["run_id"])["usage"]["total"] == len(client.calls)


def test_a_crashed_round_leaves_its_failure_and_usage_in_the_log():
    reset()
    client = FakeClient(card_fn=card_fn)       # no pairing reply queued -> the hub call blows up
    try:
        run(orchestrator.run_round(people(), client=client, neighborhood_id=5))
        assert False, "expected the round to raise"
    except IndexError:
        pass
    run_id = db.list_runs_for_neighborhood(5)[0]["id"]
    texts = [e["text"] for e in db.list_events(run_id)]
    assert any(t.startswith("Round failed:") for t in texts)
    assert db.get_run(run_id)["usage"]["total"] == 5        # 4 cards + the failed pairing call
    failed = [c for c in db.list_ai_calls(run_id) if c["error"]]
    assert len(failed) == 1 and failed[0]["purpose"] == "pairing"
    assert all(e["neighborhood_id"] == 5 for e in db.list_events(run_id))
