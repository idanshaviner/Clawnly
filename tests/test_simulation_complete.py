"""The paid batch must stop on failures and preserve its allowance across restarts."""

import json

import pytest

import simulation_complete as batch
from conftest import run


class Client:
    async def close(self):
        pass


@pytest.fixture
def offline(monkeypatch, tmp_path):
    monkeypatch.setattr(batch, "STATE", tmp_path / "batch.json")
    monkeypatch.setattr(batch.sim.config, "resolve_api_key", lambda: "test-only")
    monkeypatch.setattr(batch.sim.anthropic, "AsyncAnthropic", lambda **kw: Client())
    monkeypatch.setattr(batch.sim, "town", lambda: [])
    monkeypatch.setattr(batch.sim, "ledger_spent", lambda: 2.0)
    monkeypatch.setattr(batch.simulation_review, "ROOT", tmp_path)
    monkeypatch.setattr(batch.simulation_review, "build", lambda: {"additional_groups_needed": 133,
                                                                 "completed_groups": 67})
    monkeypatch.setattr(batch.sim, "ledger_reserve", lambda *args: 1)
    monkeypatch.setattr(batch.sim, "ledger_settle", lambda *args: None)
    monkeypatch.setattr(batch.orchestration_audit, "audit", lambda *args: None)
    ceilings = []

    def budget(ceiling, total_cap):
        ceilings.append(total_cap)
        return 1.25

    async def failed(*args, **kwargs):
        return {"spent_usd": 0, "groups_locked": 0}

    monkeypatch.setattr(batch.sim, "budget_for", budget)
    monkeypatch.setattr(batch.sim, "simulate", failed)
    return ceilings


def test_a_failed_day_stops_the_batch_instead_of_repeating_calls(offline):
    run(batch.complete())
    state = json.loads(batch.STATE.read_text())
    assert state["attempts"] == 1
    assert state["status"].startswith("stopped: no groups completed")
    assert offline == [12.0]


def test_restart_does_not_grant_another_ten_dollars(offline):
    batch.STATE.write_text(json.dumps({"starting_ledger_usd": 1.0, "absolute_ledger_ceiling_usd": 7.0,
                                      "attempts": 2, "runs": []}))
    run(batch.complete())
    assert offline == [7.0]
    assert json.loads(batch.STATE.read_text())["absolute_ledger_ceiling_usd"] == 7.0
