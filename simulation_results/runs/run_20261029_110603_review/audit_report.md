# Audit: run_20261029_110603_review

Replies came from: **Claude (live Anthropic API)**.

Event numbers are `seq` in `full_simulation.jsonl` and `[nnnnnn]` in `full_transcript.txt`.

## Numbers

| | |
|---|---|
| agents | 200 |
| days | 1 |
| groups proposed | 0 |
| groups locked | 0 |
| groups dropped | 0 |
| invitations sent | 0 |
| agent replies | 0 |
| answers | {'yes': 0, 'no': 0, 'counter': 0} |
| acceptance rate | None |
| hard constraint violations | 0 |
| agents accepting a conflict they were shown | 0 |
| ai inconsistent agents | None |
| orchestration failures | 1 |
| days not done | 1 |
| simulation cost usd | 0.0 |
| audit cost usd | None |
| ai audit coverage | None |

## Rule checks in code (3 findings)

- **high** · confirmed violation · a Claude call failed: The matchmaker_plan call failed after 3 attempt(s): APIConnectionError: Connection error. Events: 204.
  - Why: A failed agent call is counted as a no; a failed hub call stops the day. Expected: Calls succeed, or the failure is visible to the person and retried. Fix: Look at the error; retry transient ones (the harness already does).
- **info** · insufficient evidence · a call was retried: The matchmaker_plan call was retried: APIConnectionError: Connection error. Events: 205.
  - Why: Only a concern if it keeps happening. Expected: - Fix: -
- **info** · insufficient evidence · a call was retried: The matchmaker_plan call was retried: APIConnectionError: Connection error. Events: 206.
  - Why: Only a concern if it keeps happening. Expected: - Fix: -

## Who got a chance (all days)

| Kind | People | In a room | Asked | Placed | Placements |
|---|---|---|---|---|---|
| all | 200 | 135 | 0 | 0 | 0 |
| archetype: commuter | 77 | 49 | 0 | 0 | 0 |
| archetype: parent at home | 21 | 12 | 0 | 0 | 0 |
| archetype: remote worker | 47 | 34 | 0 | 0 | 0 |
| archetype: retiree | 22 | 18 | 0 | 0 | 0 |
| archetype: shift worker | 23 | 13 | 0 | 0 | 0 |
| archetype: student | 10 | 9 | 0 | 0 | 0 |
| budget: any | 103 | 73 | 0 | 0 | 0 |
| budget: free | 27 | 17 | 0 | 0 | 0 |
| budget: low | 70 | 45 | 0 | 0 | 0 |
| kids at home | 65 | 30 | 0 | 0 | 0 |

In a break room on some day but never asked: 135 people.
