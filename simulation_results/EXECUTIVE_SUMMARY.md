# Run Clawnly with real AI: what we ran, what we found, what's fixed

2026-10-29. Details are in `AUDIT_REPORT.md`, and every claim there cites the logged event behind it.

## What we ran

- **The real matchmaker, end to end, against Claude.**
  - Opus 5.5 plans the day and handles declines and counter-offers.
  - Sonnet 5 plays each person's agent and writes the confirmation messages.
  - Code builds the pools of eligible people and locks groups.
- **On the same 200 emulated Black Diamond neighbors as the earlier code-only test**, in stages:
  - 8 people for a day
  - 30 people for two days
  - all 200 for three days
  - then the pilot and one town day again after the fixes
- **Totals:** 67 groups, 296 invitations and 381 Claude calls, every one logged verbatim.
- **Every group was reviewed two ways:**
  - rule checks in code
  - an independent model, Claude Fable 5.1, which played no part in the runs. It judged 25 groups and 4 full days from the logs alone.
- **Spent $8.64 of the $10 cap:**
  - $2.46 on the simulations
  - $6.08 on the audit
  - $0.10 on replay tests

## Did it work?

**Yes, mechanically.**
- Every run completed, and all 67 proposed groups locked.
- No call failed.
- No one was placed while busy, over budget, double-booked, outside their activity's pool, or at a time they hadn't agreed to.
- The planner never tried anything the code had to block.
- The logs are complete: three independent records of every call agree.

**Mostly yes, socially.** The independent auditor's verdicts:

| | Good | Acceptable | Weak |
|---|---|---|---|
| Before the fixes (17 groups) | 9 | 7 | 1 |
| After the fixes (8 groups) | 8 | 0 | 0 |

## The problems that mattered

1. **Agents sometimes talked themselves past their person's limits.**
   - Two agents accepted a hockey game ending at 9:30pm for people who avoid late nights.
   - One invented a reason ("no early morning after").
   - The same agent had asked for a 9pm event to end earlier two days before.
   - **Fixed:** replayed 10 times each, the old prompt said yes every time and the new one says no every time.
2. **The planner couldn't see what people avoid,** so it invited late-night avoiders to late events.
   - **Fixed:** after the fix, no one was sent a plan that clashed with what they avoid (4 times before).
3. **The planner described groups by interests they didn't have,** for example "five trivia-keen neighbors" when one of five liked trivia.
   - **Descriptions fixed:** they're now accurate.
   - **Still open:** *who* gets chosen didn't measurably change. About a quarter of placements are people who are there for a side interest, the same as in the code-only test. That's the team's open question Q1.
4. **Confirmation messages invented shared interests** ("Quinn shares your love of live music"; he doesn't).
   - **Mostly fixed:** code now works out what each group really shares. Some exaggeration remains ("loves" for "is up for").
5. **The same people get chosen every day, and parents get passed over.**
   - Over three days only 82 of 200 people were asked. 4 were placed all three days.
   - Parents at home who fitted an activity were asked 24% of the time; retirees 68%.
   - **Not fixed:** the planner has no memory of earlier days, and changing who gets matched is a product decision (Q6).
6. **Round two was used for pointless "confirmed!" messages, and once to tell people who had declined.**
   - **Fixed:** agent calls in the pilot dropped from 69 to 43, and the cost from $0.51 to $0.43.

## What still needs attention

- **Decide Q1 and Q6.** Q1: should the main interest be required? Q6: should the planner favor people placed least? These drive problems 3 and 5.
- **Exercise declines and negotiation after the fixes.** In the after-fix runs every agent said yes at once, so the new code guards haven't fired live yet; they're covered by tests only. A run with tighter calendars or busier people would test them.
- **Bring the browser copy of the matchmaker in line** (the standalone Artifact page), then republish it.
- **Give the planner travel distances, or stop it claiming "close by".**
- **Commit:** nothing is committed or pushed yet.

## Ready for a larger pilot?

**Yes for the mechanics and the logging, with two conditions:** settle Q6 (fairness across days) before real people use it, and run one more paid stage that includes declines to confirm the new guards behave live. For a 200-person run, the matchmaker costs about $0.35–0.40 a day at 10 groups.
