# Orchestration simulations

## Team request and expanded review (29 October 2026)

Start with `REQUIREMENTS_STATUS.md` for the current verified count against the team's
200-group target. `requirements_check.json` checks the source evidence and records
failed and unfinished runs as well as successful ones.

- `MATCHES_FOR_REVIEW.txt`: each saved group, its original matchmaker reason, and
  every member's agent answers, one group at a time.
- `review_notes.csv`: the same group IDs with blank verdict and notes columns, ready
  for Excel or a shared spreadsheet. Rebuilding preserves notes already entered.
- `HOW_TO_REVIEW_WITH_CLAUDE.txt`: a prompt for reviewing one group at a time using
  its saved evidence. Profiles and full conversations are in each run's `run_dump.txt`.

The check and exports run for free with:

```bash
.venv/bin/python src/simulation_review.py
```

The additional runs use the existing live matchmaker and log recorder. Idan approved
up to $10 additional for completing the target; `completion_batch.json` fixes that
allowance across restarts. `src/simulation_complete.py --run` continues the batch
under that limit. Dates cycle through the seeded town's existing seven-day calendar;
repeated dates are independent model reruns. Repeated activity/member combinations
are flagged. Reviewers should compare earlier and later prompts separately.

The reports, full-record book, and Excel workbook described below document the
**original five-run baseline (67 groups)**. Use the expanded CSV/text files above
for the current complete collection. Only 25 baseline groups have a separate saved
AI audit; other groups have rule checks and remain open for human or fresh AI review.

These are end-to-end runs of the real Run Clawnly matchmaker (`matchmaker.run_day`) on the
emulated Black Diamond town. Each run gets its own folder, `run_YYYYMMDD_HHMMSS_<stage>/`. How the
system works and what was confirmed before any paid run: `architecture_summary.md`.

## Status (2026-10-29)

- **Five live runs against Claude are done and audited.** Start with `EXECUTIVE_SUMMARY.md`, then
  `AUDIT_REPORT.md`.
- Each run folder holds the full logs, and when audited also `audit_report.md`, `metrics.json` and
  the auditor's verbatim calls (`audit_calls.jsonl`).
- `spend_ledger.json` records every paid step: $8.64 of the $10 cap.

| Folder | Stage | Code |
|---|---|---|
| `run_20261029_023316_smoke` | 8 people, 1 day | before fixes |
| `run_20261029_023732_pilot` | 30 people, 2 days | before fixes |
| `run_20261029_025000_town` | 200 people, 3 days; also the agent replays (`probe_*`) | before fixes |
| `run_20261029_030412_pilot` | the same 30 people and days | after fixes |
| `run_20261029_030721_town` | 200 people, Sat 31 Oct | after fixes |

## Start here

- **`RUN_CLAWNLY_FULL_RECORD.md`:** everything in one readable file, about 199k tokens. It has:
  - the short answer
  - how the system works
  - the audit's findings
  - a guide to evaluating it yourself
  - every person once, across all runs
  - every run's conversations and groups

  To rebuild it:
  `.venv/bin/python src/run_dump.py --book simulation_results/RUN_CLAWNLY_FULL_RECORD.md simulation_results/run_*`
- **`live_match_review.xlsx`:** review the 67 live matches one by one.
  - The Matches tab has one row per group: who's in it, the matchmaker's reason, every agent's answer and reason
    (verbatim), the rule checks, Claude's read, and your verdict and notes.
  - The Answers tab has one row per invitation (296).
  - Claude's read comes from the Fable 5.1 audit for 25 groups and from rules for the other 42. On the groups both
    read, the rules agree with Fable 10 times out of 25 and are the stricter of the two.
- **`REPORT.html`:** a one-page visual summary.

## Everything in one text file, for reading or for any AI chat

No dashboard or tooling is needed. Each run folder has `run_dump.txt`: the whole run as plain
text, written for a person scrolling it and for an AI chat it's pasted or uploaded into.

1. Every emulated person's personality prompt (exactly what their agent got) before, and after:
   the profile, checked unchanged, plus every answer they gave and where they were placed.
2. Every message between the hub and each agent, with what code showed the agent, plus each day's
   plan input, the hub's reasoning, the resolve step and the final messages.
3. Every group: activity, time, members, the hub's reason, shared likes, every answer, and the
   code checks at the final time.
4. The timeline: every event, one line each.
5. What our checks found, last, so a fresh review can skip it.

Every line carries its event number `[#n]`, which also points into `full_transcript.txt`.

| File | Size |
|---|---|
| `run_20261029_023316_smoke/run_dump.txt` | ~13k tokens |
| `run_20261029_023732_pilot/run_dump.txt` | ~58k tokens |
| `run_20261029_025000_town/run_dump.txt` | ~154k tokens (fits a 200k chat on its own) |
| `run_20261029_030412_pilot/run_dump.txt` | ~46k tokens |
| `run_20261029_030721_town/run_dump.txt` | ~83k tokens |
| `ALL_RUNS_DUMP.txt` (all five) | ~353k tokens (needs a 1M-context model, or a chat project that searches files) |

New runs and audits write `run_dump.txt` automatically. To rebuild:

```bash
.venv/bin/python src/run_dump.py simulation_results/run_<stamp>_<stage>
.venv/bin/python src/run_dump.py --all simulation_results/ALL_RUNS_DUMP.txt simulation_results/run_*
```

## Reproduce

Requirements:
- Python 3.11 or later, plus `.venv` from `requirements.txt` (anthropic SDK 2.3.0)
- `ANTHROPIC_API_KEY` in the environment, or in the gitignored `.env`

```bash
.venv/bin/python src/orchestration_sim.py estimate
.venv/bin/python src/orchestration_sim.py run smoke
.venv/bin/python src/orchestration_audit.py simulation_results/run_<stamp>_smoke --ai
```

Every paid command takes `--ceiling DOLLARS`. None can start with more than what's left of
`orchestration_sim.TOTAL_CAP` ($10) in `spend_ledger.json`. These are the exact commands used:

```bash
.venv/bin/python src/orchestration_sim.py run smoke
.venv/bin/python src/orchestration_audit.py simulation_results/run_20261029_023316_smoke --ai --ceiling 2.0
.venv/bin/python src/orchestration_sim.py run pilot
.venv/bin/python src/orchestration_audit.py simulation_results/run_20261029_023732_pilot --ai --ceiling 3.0
.venv/bin/python src/orchestration_sim.py run town --ceiling 2.5
.venv/bin/python src/orchestration_audit.py simulation_results/run_20261029_025000_town --ai --sample 6 --ceiling 2.3
.venv/bin/python src/orchestration_sim.py run pilot --ceiling 0.9
.venv/bin/python src/orchestration_sim.py run town --days 2026-10-31 --ceiling 0.8
.venv/bin/python src/orchestration_audit.py probe simulation_results/run_20261029_025000_town 560,562 5
.venv/bin/python src/orchestration_audit.py simulation_results/run_20261029_030412_pilot --ai --sample 8 --no-days --ceiling 2.0
```

Free checks, with no API calls:

```bash
.venv/bin/python src/orchestration_audit.py simulation_results/run_20261029_023732_pilot
.venv/bin/python src/orchestration_audit.py compare simulation_results/run_20261029_023732_pilot simulation_results/run_20261029_030412_pilot
.venv/bin/python src/orchestration_audit.py compare simulation_results/run_20261029_025000_town simulation_results/run_20261029_030721_town 2026-10-31
```

Stages, fixed in `orchestration_sim.STAGES`:
- **Town:** seed 7; calendars start Wed 28 Oct 2026, the same week as `evaluation/results`
  (`wk20261028`).
- **Smaller stages:** they take the keenest 4 people from each of the day's strongest break
  rooms (`cohort`). These are the same people as in the full town.

| Stage | People | Days | Groups/day | Estimate | Actual |
|---|---|---|---|---|---|
| smoke | 8 | Sat 31 Oct | 3 | $0.17–0.58 | $0.09 |
| pilot | 30 | Wed 28, Sat 31 Oct | 6 | $0.55–2.02 | $0.51 |
| town | 200 | Wed 28, Sat 31 Oct, Sun 1 Nov | 10 | $1.17–4.32 | $1.08 |

How the estimate is built:
- Input sizes come from the real prompt builders.
- Output sizes, thinking included, are assumptions: plan 4–12k tokens, agent reply 250–1,500,
  resolve 1.5–6k, message 600–2.5k.
- The ceiling is checked before every call against that call's worst case (`max_tokens`), so a
  stage can never spend more than its ceiling.

Audit cost:
- Audit prompts were measured on a scripted town-scale day with realistic reply lengths: about
  20k characters (≈5.6k tokens) per group and 55k (≈16k tokens) per 200-person day.
- With 2–6k output tokens per group:
  - `claude-fable-5-1`: about $0.16–0.36 per group. Actual: $0.11–0.26 per group, and $0.17 (8 people) to $0.53 (200 people) per day.
  - `claude-sonnet-5-5`: about $0.03–0.07 per group
- `--sample N` audits every group code flagged and every group that didn't lock, plus a seeded
  draw from the rest.

LLM replies vary from run to run. The seed fixes the people, calendars and break rooms, not
what the models say. Each manifest records the commit, models, effort and SDK version.
