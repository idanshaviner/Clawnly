"""Tests for nightly.py -- the hub's automatic round every night after a
neighborhood's first round."""

import datetime

import config
import db
import nightly
from conftest import FakeClient, json_body, make_joined_resident, reset_db, run


def at(hour, day=24):
    return datetime.datetime(2026, 9, day, hour, 5, tzinfo=nightly.timezone())


def neighborhood(first_round_done=True):
    nb = db.get_or_create_neighborhood("ten-trails", "Ten Trails", 10)
    if first_round_done:
        db.mark_batch_triggered(nb["id"])
    return db.get_neighborhood(nb["id"])


def rid(resident):
    return "r" + str(resident["id"])


def speaker_fn(system, content):
    name = system.split("Clawnly agent of ")[1].split(".")[0]
    return name + " needs friends who show up every single week without fail."


def verdict_fn(system, content):
    names = system.split("on behalf of ")[1].split(".")[0].replace("\n", " ").split(" and ")
    a = names[0].strip()
    b = names[1].strip()
    return json_body({
        "thoughts": "reasoning", "depth": 9, "recommend": True, "headline": a + " and " + b + " click",
        "evidence": [{"quote": a + " needs friends who show up every single week", "why": "w"},
                     {"quote": b + " needs friends who show up every single week", "why": "w"}],
        "tensions": [],
        "invite": {"activity": "dinner", "when": "Sunday", "where": "Ten Trails", "to_a": "x", "to_b": "y"},
    })


def round_client(a, b):
    return FakeClient(agent_fn=speaker_fn, verdict_fn=verdict_fn,
                      pairing_queue=[json_body({"thoughts": "t", "pairs": [{"a": rid(a), "b": rid(b), "why": "w"}]})])


def feed(nb):
    return [e["text"] for e in db.list_neighborhood_events(nb["id"])]


def test_due_only_inside_the_nightly_hour(monkeypatch):
    monkeypatch.setattr(config, "resolve_env", lambda name: None)
    assert nightly.is_due(at(config.NIGHTLY_ROUND_HOUR))
    assert not nightly.is_due(at(config.NIGHTLY_ROUND_HOUR + 1))
    assert not nightly.is_due(at(12))


def test_hour_and_timezone_can_be_configured_and_bad_values_fall_back(monkeypatch):
    values = {"CLAWNLY_NIGHTLY_HOUR": "22", "CLAWNLY_TIMEZONE": "Asia/Jerusalem"}
    monkeypatch.setattr(config, "resolve_env", lambda name: values.get(name))
    assert nightly.nightly_hour() == 22
    assert str(nightly.timezone()) == "Asia/Jerusalem"
    values = {"CLAWNLY_NIGHTLY_HOUR": "25", "CLAWNLY_TIMEZONE": "Not/AZone"}
    assert nightly.nightly_hour() == config.NIGHTLY_ROUND_HOUR
    assert str(nightly.timezone()) == config.NIGHTLY_TIMEZONE


def test_a_nightly_round_invites_and_runs_once_a_night(monkeypatch):
    monkeypatch.setattr(config, "resolve_env", lambda name: None)
    reset_db()
    nb = neighborhood()
    noa = make_joined_resident(nb, "a@example.com", "Noa")
    marcus = make_joined_resident(nb, "b@example.com", "Marcus")

    run_ids = run(nightly.run_due_rounds(at(config.NIGHTLY_ROUND_HOUR), client=round_client(noa, marcus)))
    assert len(run_ids) == 1
    assert db.latest_match_acceptance(noa["id"]) is not None
    assert "Nightly round: 2 neighbors are free, 1 pair(s) haven't talked yet." in feed(nb)

    # a restart later in the same hour doesn't run it again
    again = FakeClient()
    assert run(nightly.run_due_rounds(at(config.NIGHTLY_ROUND_HOUR), client=again)) == []
    assert again.calls == []


def test_outside_the_hour_or_before_the_first_round_nothing_runs(monkeypatch):
    monkeypatch.setattr(config, "resolve_env", lambda name: None)
    reset_db()
    nb = neighborhood(first_round_done=False)
    make_joined_resident(nb, "a@example.com", "Noa")
    make_joined_resident(nb, "b@example.com", "Marcus")
    client = FakeClient()
    assert run(nightly.run_due_rounds(at(config.NIGHTLY_ROUND_HOUR), client=client)) == []
    db.mark_batch_triggered(nb["id"])
    assert run(nightly.run_due_rounds(at(12), client=client)) == []
    assert client.calls == []
    assert feed(nb) == []


def test_skips_without_a_paid_call_when_every_free_pair_already_talked(monkeypatch):
    monkeypatch.setattr(config, "resolve_env", lambda name: None)
    reset_db()
    nb = neighborhood()
    noa = make_joined_resident(nb, "a@example.com", "Noa")
    marcus = make_joined_resident(nb, "b@example.com", "Marcus")
    run_id = db.create_run(nb["id"])
    cid = db.save_agent_conversation(run_id, rid(noa), rid(marcus), "why", [])
    db.set_agent_verdict(cid, {"depth": 5, "invited": False}, False)

    client = FakeClient()
    assert run(nightly.run_due_rounds(at(config.NIGHTLY_ROUND_HOUR), client=client)) == []
    assert client.calls == []
    assert "Nightly round skipped: every pair of the 2 free neighbors has already talked." in feed(nb)


def test_skips_when_fewer_than_two_are_free(monkeypatch):
    monkeypatch.setattr(config, "resolve_env", lambda name: None)
    reset_db()
    nb = neighborhood()
    make_joined_resident(nb, "a@example.com", "Noa")
    client = FakeClient()
    assert run(nightly.run_due_rounds(at(config.NIGHTLY_ROUND_HOUR), client=client)) == []
    assert client.calls == []
    assert feed(nb)[-1].startswith("Nightly round skipped: fewer than 2 neighbors are free")


def test_a_failed_nightly_round_is_logged_and_contained(monkeypatch):
    monkeypatch.setattr(config, "resolve_env", lambda name: None)
    reset_db()
    nb = neighborhood()
    make_joined_resident(nb, "a@example.com", "Noa")
    make_joined_resident(nb, "b@example.com", "Marcus")
    # no pairing reply queued -> the hub call blows up inside the round
    assert run(nightly.run_due_rounds(at(config.NIGHTLY_ROUND_HOUR), client=FakeClient())) == []
    assert feed(nb)[-1].startswith("The nightly round failed:")
