# Does this meet the team's request?

A match here means one completed activity group. People and invitations are counted separately.

| Requirement | Verified status |
|---|---|
| Run the actual matchmaker locally | Saved live API runs, with model names and per-run manifests. |
| Provide 200 matches for review | 200 completed groups; 0 still needed. |
| Explain every decision | Each group has the hub's verbatim reason and each agent's verbatim answers. |
| Log personalities before and after | Exact initial prompts and final profiles are saved per run; comparisons are checked. |
| Save every conversation | Per-run run_dump.txt and full_simulation.jsonl keep hub messages, replies and call inputs/outputs. |
| Start manual notes | review_notes.csv has one row per group with human_verdict and human_notes columns. |
| Independent AI assessment | 25 groups have saved separate AI audits. Others remain open for review. |
| Human review completed | 0 verdicts in this CSV; shared or other local files were not checked. |

## Files to use

- MATCHES_FOR_REVIEW.txt: read every group in order, including the original reason and answers.
- review_notes.csv: open in Excel and add a verdict and notes per row.
- run_*/run_dump.txt: the full supporting profiles and conversations, suitable for an AI chat.
- requirements_check.json: evidence checks and SHA-256 fingerprints of source files.

The existing live_match_review.xlsx covers the original 67 groups; use the CSV for the expanded set.
The earlier evaluation/results set contains code-proposed groups and is a separate experiment.

## Read the results correctly

Evidence consistency errors: 0. Recorded failed simulation calls: 14. Incomplete run folders: 1. Failures do not count as completed groups.

Repeated dates are independent runs on the same synthetic town. They are separate model decisions,
not 200 different people or proof of real-life friendship compatibility. Older runs and later runs
may use different prompts; each original manifest and record is preserved.

Distinct activity/member combinations so far: 168. The CSV flags repeated combinations for comparison.

Failed runs and incomplete folders remain visible in requirements_check.json. The simulator stores
prompts and replies returned by the API; available thinking summaries are not the model's full hidden reasoning.

## Rebuild for free

```bash
.venv/bin/python src/simulation_review.py
```

This reads saved evidence without API calls and preserves CSV notes by match ID.
