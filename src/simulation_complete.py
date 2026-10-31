"""Complete the 200-group review using the existing live simulator and its spending guard.

Requires explicit spend authorization. The batch file fixes the total budget on first
use; restarting never grants another allowance. Each day is an independent run on
the same seeded town, and repeated dates are intentional model reruns.

    .venv/bin/python src/simulation_complete.py --run
"""

import asyncio
import datetime
import json
from pathlib import Path
import sys

import orchestration_sim as sim
import orchestration_audit
import simulation_review


STATE = simulation_review.metadata_path(simulation_review.ROOT, "completion_batch.json")


async def complete():
    if STATE.exists():
        state = simulation_review.read(STATE)
    else:
        spent = sim.ledger_spent()
        state = {"authorization": "Idan approved up to $10 additional in chat on 2026-10-29",
                 "starting_ledger_usd": spent, "additional_budget_usd": 10.0,
                 "absolute_ledger_ceiling_usd": round(spent + 10.0, 6),
                 "target_groups": 200, "runs": [], "attempts": 0,
                 "method": "200-person seed-7 town; cycle seven existing calendar dates; independent reruns"}
        save(state)
    key = sim.config.resolve_api_key()
    if not key:
        raise RuntimeError("Anthropic API key is not configured")
    client = sim.anthropic.AsyncAnthropic(api_key=key, base_url="https://api.anthropic.com",
                                         timeout=300.0, max_retries=0)
    people = sim.town()
    try:
        while state["attempts"] < 60:
            checked = simulation_review.build()
            missing = checked["additional_groups_needed"]
            if missing == 0:
                state["status"] = "complete"
                break
            ceiling = sim.budget_for(1.25, total_cap=state["absolute_ledger_ceiling_usd"])
            if ceiling < 0.55:
                state["status"] = "stopped: too little budget for another safely reserved run"
                break
            day = (datetime.date.fromisoformat(sim.WEEK_START)
                   + datetime.timedelta(days=state["attempts"] % 7)).isoformat()
            state["attempts"] += 1
            folder = simulation_review.ROOT / "runs" / ("run_" + sim._stamp() + "_review")
            groups = min(10, missing)
            save(state)
            entry = sim.ledger_reserve("simulation review completion", folder.name, ceiling)
            manifest = await sim.simulate(people, [day], groups, client, str(folder), ceiling,
                                          stage="review", live=True, thinking_summaries=True,
                                          command="src/simulation_complete.py --run")
            sim.ledger_settle(entry, manifest["spent_usd"])
            state["runs"].append(folder.name)
            state["additional_spent_usd"] = round(sim.ledger_spent() - state["starting_ledger_usd"], 6)
            save(state)
            orchestration_audit.audit(str(folder))
            print(json.dumps({"run": folder.name, "day": day, "locked": manifest["groups_locked"],
                              "total_groups": checked["completed_groups"] + manifest["groups_locked"],
                              "additional_spent_usd": state["additional_spent_usd"]}), flush=True)
            if manifest["groups_locked"] == 0:
                state["status"] = "stopped: no groups completed; inspect the run before retrying"
                break
        else:
            state["status"] = "stopped: 60-run safety limit"
    finally:
        await client.close()
        state["additional_spent_usd"] = round(sim.ledger_spent() - state["starting_ledger_usd"], 6)
        save(state)
        simulation_review.build()


def save(state):
    STATE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1:] != ["--run"]:
        print("Paid execution requires: simulation_complete.py --run")
        sys.exit(2)
    asyncio.run(complete())
