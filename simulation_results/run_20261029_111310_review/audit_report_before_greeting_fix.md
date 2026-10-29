# Audit: run_20261029_111310_review

Replies came from: **Claude (live Anthropic API)**.

Event numbers are `seq` in `full_simulation.jsonl` and `[nnnnnn]` in `full_transcript.txt`.

## Numbers

| | |
|---|---|
| agents | 200 |
| days | 1 |
| groups proposed | 10 |
| groups locked | 10 |
| groups dropped | 0 |
| invitations sent | 40 |
| agent replies | 40 |
| answers | {'yes': 39, 'no': 1, 'counter': 0} |
| acceptance rate | 0.975 |
| hard constraint violations | 0 |
| agents accepting a conflict they were shown | 0 |
| ai inconsistent agents | None |
| orchestration failures | 0 |
| days not done | 0 |
| simulation cost usd | 0.38707 |
| audit cost usd | None |
| ai audit coverage | None |

## Rule checks in code (2 findings)

- **low** · quality issue · proposal names another person: The hub's proposal to e051 mentions 'Nora', a first name of another member of 2026-10-31/g8. Agents: e051, e045. Groups: 2026-10-31/g8. Events: 223.
  - Why: The plan prompt says not to name the other people before the group is confirmed. Expected: Proposals describe the group without names. Fix: Check proposals in code for members' names before sending (a human should confirm the word is the name, not an ordinary word).
- **low** · quality issue · proposal names another person: The hub's proposal to e045 mentions 'Nora', a first name of another member of 2026-10-31/g8. Agents: e045, e051. Groups: 2026-10-31/g8. Events: 223.
  - Why: The plan prompt says not to name the other people before the group is confirmed. Expected: Proposals describe the group without names. Fix: Check proposals in code for members' names before sending (a human should confirm the word is the name, not an ordinary word).

## Who got a chance (all days)

| Kind | People | In a room | Asked | Placed | Placements |
|---|---|---|---|---|---|
| all | 200 | 147 | 40 | 39 | 39 |
| archetype: commuter | 77 | 64 | 19 | 19 | 19 |
| archetype: parent at home | 21 | 14 | 5 | 5 | 5 |
| archetype: remote worker | 47 | 32 | 5 | 5 | 5 |
| archetype: retiree | 22 | 17 | 5 | 4 | 4 |
| archetype: shift worker | 23 | 11 | 2 | 2 | 2 |
| archetype: student | 10 | 9 | 4 | 4 | 4 |
| budget: any | 103 | 78 | 19 | 18 | 18 |
| budget: free | 27 | 18 | 4 | 4 | 4 |
| budget: low | 70 | 51 | 17 | 17 | 17 |
| kids at home | 65 | 35 | 9 | 9 | 9 |

In a break room on some day but never asked: 107 people.
