"""Tests for batch.py -- the neighborhood trigger that runs the hub and turns
its invitations into the mutual yes/no gate."""

import asyncio

import batch
import db
from conftest import FakeClient, json_body, make_joined_resident, reset_db, run


def neighborhood(threshold=3):
    return db.get_or_create_neighborhood("ten-trails", "Ten Trails", threshold)


def speaker_fn(system, content):
    name = system.split("Clawnly agent of ")[1].split(".")[0]
    return name + " needs friends who show up every single week without fail."


def pairing(pairs):
    return json_body({"thoughts": "pool thoughts", "pairs": pairs})


def verdict_fn(depths):
    # depths: {"Noa+Marcus": 9, ...}; the pitches deliberately name the other person
    def fn(system, content):
        names = system.split("on behalf of ")[1].split(".")[0].replace("\n", " ").split(" and ")
        a = names[0].strip()
        b = names[1].strip()
        depth = depths.get(a + "+" + b, 5)
        return json_body({
            "thoughts": "reasoning", "depth": depth, "recommend": depth >= 8, "headline": a + " and " + b + " click",
            "evidence": [{"quote": "needs friends who show up every single week", "why": "w"},
                         {"quote": "show up every single week without fail", "why": "w"}],
            "tensions": [],
            "invite": {"activity": "dinner", "when": "Sunday", "where": "Ten Trails",
                       "to_a": "You and " + b + " both want a steady table. " + b.upper() + " is ready.",
                       "to_b": "You and " + a + " both want a steady table."},
        })
    return fn


def rid(resident):
    return "r" + str(resident["id"])


# ----- pure pieces -------------------------------------------------------------

def test_resident_to_person_is_the_agents_input():
    reset_db()
    nb = neighborhood()
    r = make_joined_resident(nb, "a@example.com", "Noa", source="Claude")
    person = batch.resident_to_person(r)
    assert person["id"] == rid(r)
    assert person["name"] == "Noa" and person["source"] == "Claude"
    assert person["dossier"] == r["dossier_text"]
    assert person["card"] == r["card"]


def test_blind_removes_the_other_persons_name_whatever_the_case():
    text = batch._blind("Marcus cooks. MARCUS listens. Marcusville stays.", "Marcus")
    assert text == "your match cooks. your match listens. Marcusville stays."
    assert batch._blind("unchanged", "") == "unchanged"


def test_pick_invitations_strongest_first_and_one_per_person():
    conversations = [
        {"a": "r1", "b": "r2", "verdict": {"depth": 8}},
        {"a": "r1", "b": "r3", "verdict": {"depth": 10}},
        {"a": "r4", "b": "r5", "verdict": {"depth": 9}},
    ]
    kept, held_back = batch.pick_invitations(conversations)
    assert [(c["a"], c["b"]) for c in kept] == [("r1", "r3"), ("r4", "r5")]
    assert [(c["a"], c["b"]) for c in held_back] == [("r1", "r2")]


# ----- the automatic trigger -------------------------------------------------------

def test_below_threshold_does_nothing():
    reset_db()
    nb = neighborhood(threshold=3)
    make_joined_resident(nb, "a@example.com", "Noa")
    make_joined_resident(nb, "b@example.com", "Marcus")
    client = FakeClient()
    run(batch.check_and_trigger_batch(nb["id"], client=client))
    assert client.calls == []
    assert db.get_neighborhood(nb["id"])["batch_triggered_at"] is None


def test_threshold_runs_one_round_and_creates_blind_invitations():
    reset_db()
    nb = neighborhood(threshold=3)
    noa = make_joined_resident(nb, "a@example.com", "Noa")
    marcus = make_joined_resident(nb, "b@example.com", "Marcus")
    sam = make_joined_resident(nb, "c@example.com", "Sam")
    client = FakeClient(agent_fn=speaker_fn,
                        pairing_queue=[pairing([{"a": rid(noa), "b": rid(marcus), "why": "x"},
                                                {"a": rid(noa), "b": rid(sam), "why": "y"}])],
                        verdict_fn=verdict_fn({"Noa+Marcus": 9, "Noa+Sam": 10}))
    run(batch.check_and_trigger_batch(nb["id"], client=client))

    # cards were built at signup, so the round makes no card calls
    assert "card" not in client.kinds()
    assert client.kinds().count("verdict") == 2

    # both conversations passed the gate, but Noa can only hold one invitation: Sam (10) beats Marcus (9)
    runs = db.list_runs_for_neighborhood(nb["id"])
    assert len(runs) == 1 and runs[0]["invitation_count"] == 1 and runs[0]["usage"]["total"] > 0
    acceptance = db.latest_match_acceptance(noa["id"])
    match = db.get_match(acceptance["match_id"])
    assert match["member_ids"] == [rid(noa), rid(sam)]
    assert db.latest_match_acceptance(marcus["id"]) is None

    # the pitch each person reads before saying yes never names the other person
    pitches = match["details"]["pitches"]
    assert "Sam" not in pitches[rid(noa)] and "SAM" not in pitches[rid(noa)]
    assert "your match" in pitches[rid(noa)]
    assert "Noa" not in pitches[rid(sam)]
    assert match["details"]["invite"]["activity"] == "dinner"

    events = db.list_events(runs[0]["id"])
    texts = [e["text"] for e in events]
    assert any("Held back the invitation for Noa + Marcus" in t for t in texts)
    assert any("Invitation sent to Noa and Sam" in t for t in texts)


def test_trigger_fires_only_once():
    reset_db()
    nb = neighborhood(threshold=2)
    noa = make_joined_resident(nb, "a@example.com", "Noa")
    marcus = make_joined_resident(nb, "b@example.com", "Marcus")
    first = FakeClient(agent_fn=speaker_fn, pairing_queue=[pairing([{"a": rid(noa), "b": rid(marcus), "why": "x"}])],
                       verdict_fn=verdict_fn({}))
    run(batch.check_and_trigger_batch(nb["id"], client=first))
    second = FakeClient()
    run(batch.check_and_trigger_batch(nb["id"], client=second))
    assert second.calls == []
    assert len(db.list_runs_for_neighborhood(nb["id"])) == 1


def test_a_failed_round_is_contained():
    reset_db()
    nb = neighborhood(threshold=2)
    make_joined_resident(nb, "a@example.com", "Noa")
    make_joined_resident(nb, "b@example.com", "Marcus")
    # no pairing reply queued -> the hub call itself blows up inside the round
    run(batch.check_and_trigger_batch(nb["id"], client=FakeClient()))
    assert db.get_neighborhood(nb["id"])["batch_triggered_at"] is not None


def test_schedule_check_keeps_a_reference_until_done(monkeypatch):
    reset_db()
    seen = []

    async def fake_check(neighborhood_id, client=None):
        seen.append(neighborhood_id)

    monkeypatch.setattr(batch, "check_and_trigger_batch", fake_check)

    async def go():
        task = batch.schedule_check(42)
        assert task in batch._RUNNING
        await task
        await asyncio.sleep(0)
        return task

    task = run(go())
    assert seen == [42]
    assert task not in batch._RUNNING


# ----- the admin "run a round now" override ----------------------------------------------

def test_force_trigger_ignores_the_threshold():
    reset_db()
    nb = neighborhood(threshold=100)
    noa = make_joined_resident(nb, "a@example.com", "Noa")
    marcus = make_joined_resident(nb, "b@example.com", "Marcus")
    client = FakeClient(agent_fn=speaker_fn, pairing_queue=[pairing([{"a": rid(noa), "b": rid(marcus), "why": "x"}])],
                        verdict_fn=verdict_fn({"Noa+Marcus": 9}))
    run_id, error = run(batch.force_trigger_batch(nb["id"], client=client))
    assert error is None and run_id is not None
    assert db.latest_match_acceptance(noa["id"]) is not None


def test_force_trigger_needs_two_people_and_a_real_neighborhood():
    reset_db()
    nb = neighborhood()
    make_joined_resident(nb, "a@example.com", "Noa")
    run_id, error = run(batch.force_trigger_batch(nb["id"], client=FakeClient()))
    assert run_id is None and "at least 2" in error
    run_id, error = run(batch.force_trigger_batch(999999, client=FakeClient()))
    assert run_id is None and "No such neighborhood" in error
