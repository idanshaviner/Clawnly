# Clawnly simulations for the 200 match review

Start with **[Clawnly_Match_Review.html](Clawnly_Match_Review.html)**. Download the file
from GitHub using **Download raw file**, then open it in a browser. It contains the
200 decisions, participants' profiles, original reasons, conversations and editable
verdicts and notes. Use **Save reviewed copy** to save your notes into that same file.

For the complete plain-text evidence, use **[ALL_RUNS_DUMP.txt](ALL_RUNS_DUMP.txt)**.
It includes all emulated profiles, messages, group decisions, checks and failed attempts.
It is a large file; use an individual run's dump for an AI chat with a smaller file or context limit.

## Where to find this on GitHub

Repository: **idanshaviner/Clawnly**  
Branch: **match-eval-tiebreak**  
Folder: **simulation_results/**

[Open this folder on GitHub](https://github.com/idanshaviner/Clawnly/tree/match-eval-tiebreak/simulation_results)

## What is ready

- **200 completed AI group decisions**, representing **168 different activity/member combinations**.
  Repeated combinations are flagged; dates intentionally repeat in independent model runs.
- **19 successful live runs** on synthetic neighbors, with **831 hub messages and 831 agent replies**.
- Every decision has the original matchmaker reason, agent answers, model inputs/outputs and source IDs.
- Profile prompts and before/after snapshots are saved. The profiles did not change during the runs.
- **25 groups have a separate saved AI audit.** The remaining groups are open for human or fresh AI review.
- The manual review is still to be completed. Add your verdict and notes in the HTML file or
  [review_notes.csv](review_notes.csv); shared copies and browser-only notes are not counted here.

The 14 connection-failure runs and one interrupted attempt are retained, contribute no matches,
and are explicitly recorded. Matching quality is for the team to judge; passing rule checks
alone does not establish real-world compatibility.

## Folder layout

```text
simulation_results/
  README.md                   This guide
  Clawnly_Match_Review.html    Main file for reading and evaluating matches
  ALL_RUNS_DUMP.txt            Complete plain-text evidence collection
  review_notes.csv            Portable manual verdicts and notes
  runs/                       Original run records, including failed attempts
  reports/                    Current requirements check and historical audit findings
  metadata/                   Manifests of the collection, budget and evidence checks
```

Inside each run:

- `full_simulation.jsonl` keeps the original event stream and model calls.
- `agents_initial.json` and `agents_final.json` keep exact agent prompts and profiles.
- `groups_generated.json` keeps the group decisions, responses and evidence references.
- `run_dump.txt` is the readable version of that run; `full_transcript.txt` is its event transcript.
- `run_manifest.json`, `cost_report.json`, `metrics.json` and audit files document execution and checks.

These evidence files serve different purposes; they have been retained unchanged. Superseded
67-group workbooks, presentation pages, duplicate match summaries and the old ZIP were removed.
The simulation database is an ignored local cache under `metadata/`; the shared evidence is in the run files.

## Rebuild the current review without API calls

From the repository root:

```bash
.venv/bin/python src/simulation_review.py
```

This validates saved evidence and rebuilds the HTML reader, full text dump, CSV and requirements
report. Existing CSV notes and notes embedded in a saved HTML file are preserved. No model is called.
The builders also accept the previous flat run layout for older exports.

New paid simulations need explicit spending approval. Their runner writes new records into
`runs/` and keeps the spending ledger and batch allowance in `metadata/`.

## Review together or with Claude

Pick a match number or full source ID. Read its profiles, original reason and actual replies.
Ask whether the people share enough to enjoy the activity, whether the constraints fit, and
whether the stated reason is supported. Record Good, OK, Bad or Unsure and explain your concern.

For AI assistance, upload an individual `run_dump.txt` and ask it to examine one match at a time,
cite the saved events, distinguish facts from its opinion, and wait for your notes before continuing.

[Requirements status](reports/REQUIREMENTS_STATUS.md) ·
[Completion log](reports/COMPLETION_LOG.md) ·
[Original five-run audit](reports/AUDIT_REPORT.md) ·
[Architecture](reports/architecture_summary.md)
