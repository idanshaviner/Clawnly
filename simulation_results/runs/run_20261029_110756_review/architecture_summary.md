# Run Clawnly orchestration: architecture summary

Written 2026-10-29 from the code on branch `match-eval-tiebreak` (it starts from `33ce5c7`; no
new commits were on `origin/main`). Every claim below points to the code. This file is copied
into each simulation run folder.

## The path from people to a confirmed group

| Step | Who | Where | What it does |
|---|---|---|---|
| 0. People | code | `population.generate(200, seed=7, start)` | 200 fictional Black Diamond adults. Each has likes (weight 1–3), dislikes, things they avoid, a budget, an archetype, kids at home or not, and a 7-day calendar of free day parts. Seeded, so the town is identical every run. |
| 1. Break rooms | code | `demand.break_room` | One room per activity and day part. A room holds everyone who is free, interested, within budget and avoids nothing about the activity. |
| 2. Plan | **Opus 5.5** (effort medium) | `matchmaker._plan_system/_plan_payload` | Sees every room. For each room it gets the keenest 8 as `id:score`, plus one profile line per listed person; everyone else in the room appears by id only. It plans up to N groups, picks a time, names up to 2 alternates per group, and writes a personal proposal to each member. |
| 3. Code check | code | `matchmaker.check_plan` | Keeps only people who are in that room and not in another group. Drops groups with fewer than 2 people. Forces fixed events (games, concerts) to their real time. The time of any other event is **not** checked. |
| 4. Round 1 | **Sonnet 5** (effort medium), one call per member, 4 at a time | `_agent_system/_agent_payload` | Each agent gets its person's full profile and week, the proposal, and what `plan_checks` found. It answers `yes`, `no` or `counter`, with one sentence. |
| 5. Resolve | **Opus 5.5** | `_resolve_system/_resolve_payload` | Sees each member's state and counter text, but **not** their reasons. Sees alternates by name only. It keeps or drops each group, can move the time, and re-asks members or alternates. |
| 6. Code check | code | `_resolve_jobs` | Only members or alternates can be asked, never someone who already said yes elsewhere, and each person is asked for only one group. A fixed event can't move. Any other new time is accepted without checks. |
| 7. Round 2 | Sonnet 5 | as in round 1 | Only the people re-asked in step 5. |
| 8. Lock | code | `run_day` step 6 | A group locks when 2 or more members said yes. There is no upper size limit. |
| 9. Message | Sonnet 5, one call per locked group | `_message_system/_message_payload` | Writes each person's confirmation, naming the others and giving a reason they'll get along. |

Each run is one dict holding every message, every step and every call verbatim. It is saved to
`db.matchmaker_runs`, and each call goes to `db.ai_calls` through `ai_log.LoggedClient`. It's served
at `/run`, where admins can start a run. Agents never talk to each other. Steps 2, 4, 5, 7 and 9 are
the only AI; everything else is code.

## What an "agent" is, and what it remembers

- **Personality** is the profile itself, rendered by `agent_profile` into the agent's system
  prompt. There is no separate persona, goal or style. The prompt's goal is to speak for the
  person and say yes only if the plan genuinely fits.
- **Memory: none.** Each agent call is a single turn: the profile plus the one proposal in front
  of it.
  - In round 2 an agent doesn't see its own round-1 answer.
  - Nothing an agent says is written back to the profile.
  - Nothing carries over from one day to the next.

  The simulation therefore records profiles before and after and proves they are unchanged
  (`agents_final.json`). It keeps what agents *said* as conversation, not as a state change.
  "Personality evolution" can't happen in this product today.

## Already confirmed in code, before any paid run

*Update after the live runs:*
- *1 and 2 never happened live: 4 time moves, all handled correctly.*
- *Both are now guarded in code (`matchmaker.inside_part`, plus a code re-ask after a move).*
- *3 never happened: 0 unreadable replies in 381 calls.*
- *See `AUDIT_REPORT.md`.*

Each of these is reproduced by an offline test that drives the real `run_day` with scripted
replies (`tests/test_orchestration_audit.py`). These tests prove the path exists. How often
the live models take it is what the paid run measures.

1. **A group can be locked at a time its members never agreed to.** The resolve step can move a
   group's time without re-asking the people who already said yes. Code still counts their old
   yes (`_resolve_jobs` and the lock step).
2. **A time outside the group's day part is accepted, in the plan and in resolve.** Calendars and
   break rooms are checked per day part, so a morning group moved to 7–9pm is never checked
   against anyone's evening. In the test, a museum visit ends up at 7–9pm.
3. **An agent reply that isn't JSON silently becomes "no".** `_ask_agent` defaults to "no", and
   the run log shows NO with no error.
4. **Resolve adapts blind.** It sees "no" but not why, and sees alternates by name only
   (`_resolve_payload`). Whether that hurts is a question for the AI audit.
5. **The plan profiles only the 8 keenest people per room.** Everyone else is an id with no
   profile, so the hub can only pick them blind.
6. Cosmetic: names end in "." and the prompt adds another one ("You are the personal agent of
   Rosa G..").

## What was missing for a real end-to-end run, and what was added

- **A harness:** `src/orchestration_sim.py`. It runs the unmodified `matchmaker.run_day` with a
  recording client.
  - Every request and reply is kept verbatim, with usage, cost, latency and retries.
  - Each call is linked to its person, group, round and the group's time at that moment.
  - Every group and member state change is kept with before and after.
  - One numbered JSONL timeline and a readable transcript.
  - A spending ceiling that refuses any call whose worst case could cross it. It is checked
    before the call, counting calls already in flight.
  - Its own SQLite file, so the app's database is never touched.
  - A per-day check that three independent records of the calls agree: the run dict, the
    harness, and `db.ai_calls`.
- **One change to the requests:** the harness asks for `thinking.display = "summarized"`, so the
  model's reasoning summary is kept. Thinking is on and billed the same without it. The change
  is recorded in each run's manifest; `--no-thinking-summaries` turns it off.
- **An audit:** `src/orchestration_audit.py`.
  - Rule checks in code, each finding citing event numbers.
  - An independent model (default `claude-fable-5-1`, which the run itself never uses) reviews
    each group's evidence packet.
  - Code drops any AI finding that cites an event the auditor wasn't shown.
- **Not available on this machine:** an Anthropic API key. There is no `.env` and no
  `ANTHROPIC_API_KEY`. Nothing has been run against Claude yet.

## Models and cost

- Prices per million tokens (input / output):
  - Opus 5.5: $4 / $20
  - Sonnet 5: $2 / $10
  - Fable 5.1: $10 / $50
  - Sonnet 5.5: $2 / $10
- Output includes thinking.
- Run `.venv/bin/python src/orchestration_sim.py estimate` for the per-stage estimate. It uses
  exact prompt sizes from the real prompt builders and assumed reply sizes.

## Out of scope

The friendship pilot (`orchestrator.py`, `agent_talk.py`) is a separate AI orchestration. There,
agents do talk to each other, about real residents' dossiers. It isn't simulated here.
