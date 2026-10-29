# Completing the team's simulation request — 29 October 2026

## What was present

The original five successful runs already contained the requested evidence: initial
personality prompts, final profiles, hub/agent messages, original group reasons,
raw API inputs/outputs and cost records. They contained **67 completed groups**,
not the 200 requested. The older 286-group experiment in `evaluation/results/`
uses only the code proposer and does not replace live AI decisions.

## What was completed

Idan approved up to **$10 additional** in chat. Fourteen additional successful runs
of the existing `matchmaker.run_day` pipeline produced **133 more completed groups**.
Their recorded additional cost is **$4.781956**, calculated from logged usage and
the simulator's price table. The ledger now totals **$13.419920**, including the
earlier runs, AI audits and replay tests; no reservation remains unsettled.

The final collection has **200 completed group decisions**, **168 distinct
activity/member combinations**, and **831 agent replies**. Dates intentionally cycle
through the same seeded town's seven-day calendar; repeated outcomes are flagged.
The matching rules and product prompts were unchanged during this completion work.

The new runs have **zero hard-constraint violations in the mechanical audit**.
The source consistency checker found **zero errors** when comparing saved group
reasons, final memberships, agent replies and delivered system prompts with the logs.
This is evidence consistency and rule validation, not a claim of social compatibility.

## Files prepared

- `MATCHES_FOR_REVIEW.txt`: one group at a time, original reason, hub invitations
  and agent answers in event order, and existing separate AI audit opinions.
- `review_notes.csv`: one row per group and blank human verdict/notes columns.
  Rebuilding preserves those two columns by match ID.
- `START_HERE.txt` and `HOW_TO_REVIEW_WITH_CLAUDE.txt`: how to use the evidence and
  review one match at a time without a new application or presentation.
- `REQUIREMENTS_STATUS.md` and `requirements_check.json`: completion status,
  per-run evidence checks, failure counts and source file hashes.
- `review_package.zip`: the review files and all per-run records, excluding the
  simulation database. Rebuild with `src/simulation_review.py --package`.

Only **25 groups** have a separate saved AI audit. All 200 have the matchmaker's
original explanations and agent exchanges. The manual review remains to be done:
the new CSV starts with **zero human verdicts**. Shared spreadsheet notes were not inspected.

## Failures and corrections

Restricted execution could not resolve the API hostname. Fourteen failed attempts
produced no groups and incurred zero recorded cost; their error logs are retained.
One further attempt was interrupted during retry sleep and lacks a completed
transcript; its folder contains `INTERRUPTED.txt`. Its unused reservation was released
with an explanation in the ledger. Execution then continued successfully with network access.
The batch now stops after a zero-group run rather than repeating whole failed runs.

A free audit falsely flagged two greetings in
`run_20261029_111310_review`, group `2026-10-31/g8`, event #223. Both recipients
were named Nora, so greeting each as "Nora," was mistaken for naming the other member.
The audit now excludes the recipient's opening greeting while still detecting a name
mentioned later. A regression test covers both cases. The corrected audit was run on
the actual saved record; the original audit files are retained as `*_before_greeting_fix.*`.
No matching decisions or raw conversation records were changed.

## Validation

**283 tests passed.** The new checks cover evidence tampering, conversation ordering,
preservation of human notes, stopping failed batches, budget persistence across restarts,
and the duplicate-first-name audit case. All 200 exported IDs are unique; archive
integrity and the export's absence of credential-shaped strings were checked.

The current changes remain local on `match-eval-tiebreak`; nothing was pushed.
