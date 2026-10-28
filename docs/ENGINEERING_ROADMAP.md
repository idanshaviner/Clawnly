# Engineering roadmap (about 5 hours a week)

Started 2026-10-27, based on the evaluation in `evaluation/MATCH_QUALITY_REPORT.md`. The
target is a stable, measurable matcher by 31 Oct 2026, with prompt and quality work after
that. Each item states the time it needs, what it depends on, and when it counts as done.

## Done (27 Oct)

| Item | Evidence |
|---|---|
| Baseline: 220 tests. One failed because a login cookie leaked between tests in `test_auth.py`. Fixed by clearing the shared client's cookies in `reset_state` | `pytest -q`: 227 passed |
| Offline evaluator `src/match_eval.py` + `tests/test_match_eval.py` | 286 records, 0 API calls |
| F1 fix: ties ranked by a per-day draw instead of id (`demand.tie_order`, JS mirror) | id-half gap 0.47 -> 0.03 placed days/week; JS and Python hashes equal on live `/run` |
| `docs/MATCHING_ARCHITECTURE.md`, `evaluation/MATCH_QUALITY_REPORT.md`, `evaluation/TEAM_REVIEW.md` | – |

## Essential, by 31 Oct (about 5h)

| # | Task | Hours | Depends on | Done when |
|---|---|---|---|---|
| 1 | Review and commit today's changes, then rerun `match_eval.py` so the metadata carries a clean commit hash | 0.5 | Idan | `git_dirty: false` in `simulation_metadata.json` |
| 2 | Team review session (`TEAM_REVIEW.md`) | 1 | Ashish, Eitan | Q1–Q8 answered and written into `TEAM_REVIEW.md` |
| 3 | Regenerate and republish the standalone Artifact `matchmaker/run-clawnly.html` so it carries the tie-break fix (`run_clawnly.py <path> <first day>`; read `matchmaker/README.md` first) | 0.5 | 1 | The Artifact's JS contains `tieOrder` |
| 4 | Implement the Q1 decision (main tag), with a test and a before/after eval | 1.5 | 2 | Groups with no member liking the main tag go from 5 to 0, or the trade-off is documented |
| 5 | One authorized live `run_day` (10 groups), read its cost from `db.ai_calls` | 1 | Q7 approval and a workspace-scoped key | A saved run in `db.matchmaker_runs`, with its call count and tokens recorded |
| 6 | Update `docs/ROADMAP.md` / `CLAUDE.md` current state | 0.5 | 1 | Docs match the code |

## Next (November, about 5h a week)

| # | Task | Hours | Done when |
|---|---|---|---|
| 7 | Extend `match_eval.py` to read negotiated groups from `db.matchmaker_runs` (same checks, plus agent answers, counters and lock rate) | 2 | A report on 200 *negotiated* groups |
| 8 | F3: move time parsing into `catalog.py`, and use real hours in `fit` for fixed events (Python + JS) | 1.5 | 0 fixed-event late/early conflicts in the eval |
| 9 | Q3: allow more than one group per slot in the preview (if approved) | 1 | Person-days unplaced-but-in-a-room drop, measured |
| 10 | Q4/Q6: a variety or fairness term (least-placed first, or avoid repeats), if approved | 2 | Never-placed count and repeat count measured before and after |
| 11 | Pilot: re-offer held-back deep fits (`orchestrator.py:405` treats them as done) | 1.5 | A test shows the pair is eligible again once both are free |
| 12 | Pilot security: check `auth.is_admin` on every admin request, not only at login | 0.5 | A test: remove the email from the list and the existing session gets 403. `security-review` pass |
| 13 | Pilot: one lock so the first round, nightly rounds and the admin button can't run a round at the same time for one neighborhood | 1.5 | A test runs two at once and only one goes ahead |

## Optional

- Fix the README model names, the "three tiers" comment in `config.py`, and the duplicated keys in `catalog._a`.
- Vary calendars from week to week (today they repeat by weekday for the same seed).
- Run "Run a round now" in the background (it currently holds the HTTP request for minutes).
- Make magic-link sign-in a POST behind the GET page, so email scanners can't burn the link.

## Weekly rhythm (5h)

- 1h: run `match_eval.py` (and a live run when approved), and refresh the results
- 1.5h: read flagged groups and find root causes
- 1.5h: one targeted change, with a test and a before/after eval
- 1h: update the docs and post to Ashish/Eitan

Essential beats optional. If a week runs short, drop the optional items first, never the before/after eval.
