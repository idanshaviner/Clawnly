# Team review: 200+ matches (Ashish, Eitan, Idan)

Prepared 2026-10-27. Details: `MATCH_QUALITY_REPORT.md`. How the system works:
`docs/MATCHING_ARCHITECTURE.md`. Raw records: `evaluation/results/matches.json` and `.csv`.

## In plain English

Run Clawnly matches neighbors into small activity groups in two layers:

1. **Code (free, deterministic).** For each activity and time of day, code works out who is
   free, interested, within budget and not put off by anything about it. We call each of these
   a "break room".
2. **The AI matchmaker.** It picks groups from those rooms, asks each person's agent, and
   locks a group once two or more say yes.

We ran the **code layer** for real on the same 200 emulated neighbors `/run` uses, over two
full weeks, an autumn week and a summer week. That produced **286 groups**. We couldn't run
the AI layer: there's no API key here and no spend was approved. So this review covers the
groups the code would propose and the rules the AI is held to, not the agents' decisions.

**Headline findings:**

- **The rules hold.** Across 1,239 placements:
  - 0 people were placed while busy, over budget, or into something they dislike or avoid
  - 300 deliberately broken AI plans were fed to the live code checks, and none got through
- **Fixed today: a fairness bug.** When people were equally keen, the earliest ids won, so
  about half the town got roughly 15% more groups. That ordering also chose which 8 people per
  room the AI sees. Ties now use a fair per-day draw, and the gap is essentially gone.
- **Quality questions for us:**
  - 24% of placements are people who don't care about the activity's main thing. One trivia
    night has five beer fans and no trivia fans.
  - People with kids are placed about half as often.
  - The same five people can be grouped two days running.
  - 83 groups span 40+ years in age.

## Walk through these together (about 30 min)

Open `evaluation/results/matches.json` and search for the ID. Each record shows each
member's likes, score, rank in the room, the rule checks, what their agent would be told, and
how the group was chosen.

| # | Match ID | What to decide |
|---|---|---|
| 1 | `wk20261028-2026-10-29-g24` | Golf for two. Is this what a good match looks like? |
| 2 | `wk20261028-2026-10-28-g11` | Trivia night with no trivia fans (Q1) |
| 3 | `wk20261028-2026-10-28-g04` | Ghost-town hike: 3 of 5 don't like hiking, ages 33–81 (Q1, Q2) |
| 4 | `wk20261028-2026-10-28-g06` | Cribbage, ages 19–83, everyone keen. Good or bad? (Q2) |
| 5 | `wk20261028-2026-10-28-g09` + `-10-29-g13` | Same five people fishing two days in a row (Q4) |
| 6 | `wk20261028-2026-10-29-g02` | Kraken until 9:30pm with someone who avoids late nights (Q5) |
| 7 | `unplaced.json`, run `wk20261028` | 25 people got nothing all week: who are they? (Q6) |
| 8 | `wk20260715-2026-07-18-g27` | Summer dog walk for two: is a pair a group? |

## Questions only you can answer

1. **Main thing vs. side thing.** Should liking an activity's secondary tag (beer at trivia,
   coffee at cribbage) be enough to place someone? Options:
   - a. as now
   - b. require the main tag
   - c. score the main tag higher
2. **Stage of life.** Should code limit age spread, or leave it to the AI's judgment? Is a
   19–83 cribbage table a feature?
3. **More than one group per activity and time.** Would you send two hiking groups out at the
   same time and place? 627 person-days went unused in this preview because of this.
4. **Repeats.** Same group again on the next day: avoid it, allow it, or encourage it
   (repeated meetings build friendships)?
5. **Late nights.** Is 9pm "late"? The code layers disagree today (F3 in the report).
6. **Who gets left out.** Should the matchmaker favor people who've been placed least this
   week? Parents, free-only budgets and people with few likes lose out most. Is the "50% of
   free time is taken when you have kids" assumption right?
7. **A paid live run.** May we run the AI layer to get 200 *negotiated* groups?
   - One `run_day` with up to 10 groups is roughly 60–70 Claude calls: 2 on Opus, the rest on
     Sonnet.
   - 200 locked groups is roughly 20–25 runs.
   - Suggest one run first, then read its cost from `db.ai_calls` before committing to the rest.
8. **The friendship pilot** (not evaluated here). Two bugs were found by reading the code:
   - a deep-fit pair that's held back (because one of them got a stronger invitation that
     round) is never offered again
   - removing someone from the admin list doesn't end their 30-day admin session

   Fix both? The first changes matching behavior.

## Next engineering priorities

See `docs/ENGINEERING_ROADMAP.md`. Short version, in order:

1. Merge today's work: the tie-break fix, the evaluator and the test fix.
2. Answer Q1–Q4. Each answer becomes a small, measured change.
3. One authorized live `run_day` (Q7), then extend `match_eval.py` to read
   `db.matchmaker_runs`, so negotiated groups get the same checks.
4. The pilot fixes from Q8.
