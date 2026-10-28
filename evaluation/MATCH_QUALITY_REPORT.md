# Match quality report: Run Clawnly, code-only layer

2026-10-27. Reproduce with `.venv/bin/python src/match_eval.py evaluation/results` (no API key,
no cost, about 0.15 seconds). Everything below comes from `evaluation/results/` (after the fix)
and `evaluation/results/baseline/` (before it).

## What was evaluated, and what wasn't

- **A match** is one group made by `demand.propose_groups` for one day: an activity, a day
  part and 2-5 emulated neighbors. This is Clawnly's real, deterministic matching layer. The
  break rooms it uses are exactly what the live matchmaker plans from.
- **Not evaluated:** the LLM steps of `matchmaker.run_day` (the Opus plan, the agent replies,
  the resolve step, the final messages). No API key is configured on this machine and no spend
  was authorized. No model reply was invented. The live matchmaker's *code checks* were tested
  with randomly generated bad plans (see "Rule enforcement" below).
- **Dataset:** seed 7, the same 200 neighbors as `/run`, over two full weeks:
  - **`wk20261028`**: 28 Oct – 3 Nov 2026, the week `/run` plans next.
  - **`wk20260715`**: 15–21 Jul 2026. Summer-only activities run (tubing, dock concerts, lawn yoga).

  That gives **286 matches** (282 before the fix), which is above the 200 asked for. The
  dataset is two full weeks rather than 200 cut from them, because cutting at 200 would drop
  most of a weekend and skew the mix.
- **Files:**
  - `matches.json`: the full records, with every member, their fit, matched likes, rule checks and what their agent would be told
  - `matches.csv`: one row per match
  - `summary.json`: aggregates, fairness tables and per-day coverage
  - `unplaced.json`: who got no group each day
  - `simulation_metadata.json`: commit, seed, timing, `api_calls: 0`

## How quality was judged

| Kind | What | Ground truth? |
|---|---|---|
| Deterministic rule check | Calendar, budget, dislikes, avoided traits, season, running day, size, one group per person per day. These are re-implemented independently in `match_eval.hard_violations`, not by calling `demand.fit`. | Yes, these are the system's own rules |
| Cross-check with the live matchmaker | `matchmaker.plan_checks` run on every member: what their agent would be told argues against the plan. Times are the event's real hours, or the whole day part when the time isn't fixed. | Code-to-code consistency |
| Proxy metrics | Fit score, whether the member likes the activity's main tag (the first tag in the catalog), the group's overlap in likes (mean pairwise Jaccard), age spread, repeated pairs, placement rate by kind of person | **No.** These are signals for review, not verdicts |
| Human judgment | Every group with a proxy flag gets status `needs human review` | Still to be collected (the Ashish/Eitan session) |

No LLM was used to grade anything.

## Results (after the fix)

| | Value |
|---|---|
| Matches / member placements | 286 / 1,239 |
| Group sizes | 5 people: 201 · 4: 17 · 3: 30 · 2: 38 |
| **Hard-rule violations** | **0** |
| Input-order stability | 35 day-runs with shuffled input, **0 differed** |
| Live `check_plan` fuzz | 300 random bad plans, 826 groups kept, **0 rule breaks got through** |
| API calls / runtime | 0 / 141 ms for both weeks |
| Review status | `rule-clean` 67 · `needs human review` 219 |
| Person-days placed | 1,239 of 2,800 (44%) |
| Unplaced but in at least one room | 627 person-days |
| Unplaced with no fitting slot at all | 934 person-days |
| Never placed in a whole week | 25 people (autumn), 15 (summer) |
| Mean fit / overlap in likes / age spread | 2.91 / 0.20 / 32.9 years |

### The flags behind "needs human review"

| Flag | Groups | Members | Notes |
|---|---|---|---|
| Last place settled by tie-break | 148 | – | Normal. It's now a per-day draw rather than id order |
| A member doesn't like the activity's main thing | 133 | 295 (24%) | They got in through a secondary tag |
| A member's agent would be told it conflicts | 111 | 152 | Reasons: ends 9pm+ and they avoid late nights (63), mild interest (69), early start (22) |
| Age spread of 40+ years | 83 | – | 38 groups have 50+ years between youngest and oldest |

## Failure analysis

### F1. Equally keen people were ranked by id: the earliest ids got about 15% more groups (confirmed, fixed)

- **Evidence:** In the baseline, ids e001–e100 averaged 3.15 placed days a week against 2.68
  for e101–e200 (autumn), and 3.50 against 2.98 (summer). Ids are assigned in generation
  order and carry no meaning.
- **Causal test:** Reversing *only* the tie-break flipped the gap. Placements per id quarter
  went from 327/338/286/280 to 264/297/310/347
  (scratch probe, rerunnable from `match_eval.generate` with a reversed sort).
- **Root cause:** `interested.sort(key=(-score, id))` in `demand.break_room`. In 146 of 282
  groups, the last spot was settled by this tie-break. The same order also chose which 8
  people per room Opus sees with a profile (`matchmaker._plan_payload`, `PROFILES_PER_ROOM`),
  so the bias reached the live matchmaker as well.
- **Fix:** Ties are now ordered by `demand.tie_order(day, id)`, a reproducible per-day FNV-1a
  draw, in both `demand.py` and `src/web/run-clawnly.js`. On the live `/run` page, the JS and
  Python values were checked to be equal.
- **Result:** The first-half/second-half gap fell from 0.47 to 0.03 placed days a week
  (autumn) and from 0.52 to 0.14 (summer). Every other aggregate moved by less than 3%, with
  0 rule violations and the same order stability. Severity: medium (a fairness defect, and
  it fed into the LLM).

### F2. Activities filled by people who don't want the main thing (confirmed behavior; whether it's a defect is a product call)

- **Evidence:** 295 of 1,239 placements (24%) are people who don't like the activity's first
  tag. In 5 groups nobody does:
  - `wk20261028-2026-10-28-g11` is **Trivia night as one team, and none of its 5 members likes trivia.** All five came in through `craft_beer`.
  - Others: `wk20261028-2026-10-29-g23`, `wk20261028-2026-11-03-g08`, `wk20260715-2026-07-15-g12`.
- **Root cause:** `demand.fit` scores *any* tag the person likes as interest, and the catalog
  has no notion of a primary tag.
- **Proposed fix (needs a decision):** Weight or require the first tag, or let the catalog
  mark which tags are enough on their own.

### F3. The break room and the agent's checks disagree on time-of-day rules (confirmed, low severity)

- **Evidence:** `demand.fit` treats an outdoor morning as an early start and ignores late
  nights unless the activity carries that trait. `matchmaker.plan_checks` uses the real hours
  (before 9am, or ending 9pm or later). On fixed-time events, 7 groups contain someone whose
  agent would be told it ends too late:
  - **Kraken, 7–9:30pm:** `wk20261028-2026-10-29-g02` and `-10-31-g01`
  - **Trivia, 7–9pm:** `wk20261028-2026-10-28-g11`

  It also goes the other way: the 9am trail cleanup excludes early-morning avoiders even
  though `plan_checks` would not flag a 9am start.
- **Why it's only low severity:** When the plan doesn't fix a time, `check_plan` falls back to
  the whole day part (evening 5–10pm), so every late-night avoider in an evening group gets
  flagged. In the live system Opus usually writes a narrower time, so the 63 "ends 9pm+"
  count overstates the live effect.
- **Proposed fix:** Move `fixed_time` and `parse_hours` into `catalog.py`. Then `fit` can use
  real hours for fixed events, and `check_plan` can use a typical slot rather than the whole
  day part when the plan gives no time. Not done: the evidence covers 7 groups, and it touches
  three modules plus the JS copy.

### F4. Coverage is capped by "one group per slot" in the preview (confirmed for the preview only)

- **Evidence:** 627 person-days are spent unplaced even though the person fits at least one
  room that day. On Tuesday 3 Nov, 127 people fit a room but only 60 were placed.
- **Root cause:** `propose_groups` makes at most one group of 5 per activity x day part. The
  live matchmaker can put several groups in the same room, so this limits the preview and
  this evaluation, not necessarily the product.
- **Proposed fix:** Allow more than one group per slot in the preview, so the code-only
  numbers mean something. Needs a decision: is a second hike group at the same time and place
  acceptable?

### F5. Who gets left out (confirmed outcome; the cause is the population model)

- **Evidence:** People with kids at home averaged 1.92 placed days in the autumn week against
  3.39 for everyone else, and 18 of 65 (28%) were never placed, against 7 of 135 (5%). The
  summer week shows the same pattern.
- **Other gaps:** A free-only budget averaged 2.11 against 3.0 or more. Three likes averaged
  2.53 against six likes at 3.33. Students and retirees came out highest.
- **Root cause:** Mostly `population._calendar` (50% of free time taken when there are kids)
  and a catalog where most activities are low or mid cost. The matcher itself has no
  fairness term.
- **Proposed fix (needs a decision):** Decide whether the matchmaker should favor people
  placed least this week.

### F6. The same people grouped again and again (confirmed)

- **Evidence:** 348 pairs share a group more than once in a week, and one pair shares 6.
  8 identical groups (same people, same activity) recur within a week, for example the same
  five at Early fishing on Lake Sawyer on Wed and Thu (`wk20261028-2026-10-28-g09`,
  `-10-29-g13`). The baseline had 3 such repeats and 379 repeated pairs. With small counts
  the fix moved them both ways, which is variance rather than a trend.
- **Root cause:** Nothing remembers earlier days, and calendars repeat by weekday.
- **Proposed fix (needs a decision):** Repeats might be good, because repeated meetings are
  how friendships form, or they might be a waste.

### F7. Wide age spread (proxy; needs human judgment)

- 38 groups span 50+ years. For example, Cribbage and coffee with members aged 20, 83, 72, 19
  and 78 (`wk20261028-2026-10-28-g06`).
- The live prompt asks Opus to prefer a "similar stage of life", but nothing in code checks it.
- This may well be fine: cross-generational groups could be a feature.

## What works

- **Hard rules are never broken:** 0 violations across 1,239 placements, checked by an
  independent implementation.
- **The live matchmaker's code checks hold:** 300 adversarial plans, and nothing out of a
  room, double-booked or undersized got through.
- **Fully deterministic and order-independent,** and it costs nothing to run.
- **Every group is explainable from recorded state:**
  - the slot's rank and strength
  - each member's score and rank in the room
  - who was skipped because a stronger group already had them
  - who lost a tie

## Representative examples (all IDs are in `matches.json`)

| Kind | Match | Why it's interesting |
|---|---|---|
| Strong | `wk20261028-2026-10-29-g24` | Nine holes at Lake Wilderness. One member loves golf and one really likes it, overlap 0.4, no flags |
| Strong | `wk20260715-2026-07-18-g27` | Dog walk with two people aged 22 and 29, overlap 0.4, no flags |
| Weak | `wk20261028-2026-10-28-g11` | Trivia night where no member likes trivia; one member's agent would also be told it ends too late |
| Weak | `wk20261028-2026-10-28-g04` | Franklin hike where 3 of 5 don't like hiking, overlap 0.075, ages 33–81 |
| Borderline | `wk20261028-2026-10-28-g06` | Cribbage with ages 19–83: wide spread, but four of the five love cards |
| Constraint tension | `wk20261028-2026-10-29-g02` | Kraken until 9:30pm with a late-night avoider (F3) |
| Repeat | `wk20261028-2026-10-28-g09` / `-10-29-g13` | Same five at fishing on two days in a row |
| Unmatched | `unplaced.json` | 25 people got nothing all autumn week |

## Limits of this evaluation

- No LLM step was run, so the agents' yes/no/counter behavior, the locking rate and cost per
  locked group are unknown. That needs a paid run (see `TEAM_REVIEW.md`).
- The proxies (main tag, overlap in likes, age spread) are judgments about what matters, not
  measurements of compatibility.
- The population is synthetic, and calendars repeat by weekday.
- The results were produced from an uncommitted working tree (`git_dirty: true`). Rerun after
  committing to stamp a clean hash.
