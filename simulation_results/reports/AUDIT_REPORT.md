# Independent audit: Run Clawnly with live AI orchestration

2026-10-29. The real `matchmaker.run_day` was run against Claude (Opus 5.5 as the hub, Sonnet 5 as
the agents) on the seed-7 Black Diamond town. Two kinds of check were applied:

- reproducible rule checks in code (`orchestration_audit.py`)
- an independent model, **Claude Fable 5.1**, which takes no part in the runs

Every finding below cites the run and the event numbers (`seq` in `full_simulation.jsonl`, `[nnnnnn]`
in `full_transcript.txt`). Nothing below is reconstructed. Where the logs can't say why something
happened, that is stated.

## The runs

| Alias | Folder | People | Days | Groups locked | Code |
|---|---|---|---|---|---|
| S | `run_20261029_023316_smoke` | 8 | Sat 31 Oct | 3 / 3 | before fixes |
| P1 | `run_20261029_023732_pilot` | 30 | Wed 28, Sat 31 | 12 / 12 | before fixes |
| T1 | `run_20261029_025000_town` | 200 | Wed 28, Sat 31, Sun 1 Nov | 30 / 30 | before fixes |
| P2 | `run_20261029_030412_pilot` | the same 30 | the same | 12 / 12 | after fixes |
| T2 | `run_20261029_030721_town` | the same 200 | Sat 31 | 10 / 10 | after fixes |

- All five ran from commit `33ce5c7` with uncommitted changes (`dirty: true`); the changes are
  listed under "Code changes".
- The people, calendars and break rooms are deterministic.
- Model replies are not deterministic: the same prompt can be answered differently.

## Numbers

| | S | P1 | T1 | P2 | T2 | All |
|---|---|---|---|---|---|---|
| Claude calls (simulation) | 13 | 85 | 172 | 59 | 52 | 381 |
| Invitations (hub → agent) | 8 | 69 | 136 | 43 | 40 | 296 |
| Yes / no / counter | 7/1/0 | 67/1/1 | 129/4/3 | 43/0/0 | 40/0/0 | 286/6/4 |
| Acceptance rate | 88% | 97% | 95% | 100% | 100% | 97% |
| Groups proposed / locked | 3/3 | 12/12 | 30/30 | 12/12 | 10/10 | 67/67 |
| Hard-constraint violations | 0 | 0 | 0 | 0 | 0 | **0** |
| Agents saying yes to a conflict they were shown | 0 | 0 | 2 | 0 | 0 | 2 |
| Orchestration failures (errors, retries, unreadable replies, failed days) | 0 | 0 | 0 | 0 | 0 | **0** |
| The hub trying something code had to block | 0 | 0 | 0 | 0 | 0 | 0 |
| Log check (run dict = harness = `db.ai_calls`) | ✓ | ✓ | ✓ | ✓ | ✓ | every day |
| Simulation cost | $0.09 | $0.51 | $1.08 | $0.43 | $0.35 | $2.46 |

**Hard constraints** are checked independently of the matchmaker's own code. They cover:
- being in the activity's break room
- one group per person per day
- having agreed to the final time
- the final time staying inside its day part
- fixed events staying at their real time
- being busy, over budget, or put into something the person dislikes or avoids

**AI audit coverage:**
- Fable 5.1, effort medium, $6.08 in all.
- Each auditor call got the evidence packet for one group (or one day) and nothing else.

| Run | Groups audited | Days audited | Why less than everything |
|---|---|---|---|
| S | 3 of 3 | 1 of 1 | – |
| P1 | 12 of 12 | 0 of 2 | the ceiling stopped the day audits |
| T1 | 2 of 30 | 3 of 3 | a seeded sample of 6 groups; the ceiling stopped 4 of them |
| P2 | 8 of 12 | not run | seeded sample, groups only |
| T2 | none | none | rule checks only |

Of the 72 findings Fable cited, every one pointed to events that were in its packet, so code dropped none of them.

**Other spending:**
- Probes: $0.10. These were 40 Sonnet calls replaying two agent decisions.
- **Total: $8.64 of the $10 cap**, as recorded in `spend_ledger.json`.

## Findings, most severe first

Each finding has a kind:
- **Confirmed:** a rule check or the logs prove it.
- **Supported:** the auditor's judgment, with cited evidence.
- **Subjective:** a judgment call.

### 1. High · confirmed · fixed and verified by replay: agents talk themselves past a limit their person set

**Where:** T1 `2026-10-31/g1` (Kraken hockey night, 7–9:30pm). Ava's agent (e117) [560, 573] and Nikhil's agent (e001) [562, 578].

**What happened:**
- Code told both agents that the event "runs to 9pm or later" and that the person avoids late nights. Both said yes, and both were locked in [791].
- Ava's agent called 9:30pm "not a late night".
- Nikhil's agent claimed he had "no early morning after", which his calendar doesn't support.
- On Wednesday, the same agent had asked for a 9pm crafts night to end at 8pm because "9pm is later than he likes to be out" [274, 477].
- Fable rated the group **weak** and both agents **inconsistent**.

**Why it matters:**
- The agent is the person's only voice. Here it overrode a stated boundary, once by inventing a fact.
- It has no memory, so nothing stops it contradicting yesterday.

**Fix:** one line in the agent prompt: what the person avoids is a limit, not a preference to trade off. Say no, or counter only if the time can move.

**Evidence the fix works:**
- Both exact calls were replayed 5 times with each prompt, twice over (`probe_results_1.json`, `probe_results_2.json` in T1).
- Old prompt: 10/10 yes for each agent. Final prompt: 5/5 no for each.
- An intermediate wording made Ava's agent ask to move a hockey game's start time (5/5). The final wording removed that.

### 2. Medium · confirmed · fixed: the hub couldn't see what people avoid, so late-night avoiders were invited to late fixed events

**Where:** P1 `2026-10-31/g4`: Grace (e148) was invited to the 7–9:30pm game and declined [433]. T1 `2026-10-31/g1` (finding 1).

**Root cause:**
- `_person_line` showed the hub only people's likes.
- Break rooms let late-night avoiders into a 9:30pm event, because the activity doesn't carry the `late_nights` trait (see F3 in `evaluation/MATCH_QUALITY_REPORT.md`).

**Fix:** each person's line in the plan now says what they avoid, and the prompt says to check it against a FIXED time.

**Effect:** in P2 and T2, code showed no agent any conflict, against 4 times before (S 0, P1 1, T1 3). Finding 1 couldn't recur because no avoider was invited.

### 3. Medium · supported, 6 groups · fixed (descriptions) / open (who is chosen): groups built from side-interest members, then described as fans

**Where:**
- S `g3` [16]: "Four big sports fans", though Olivia (e158) has no interest in watching sports. She declined [54].
- P1 `2026-10-28/g2` [37, 43]: "Five trivia-keen neighbors", though only Kavya likes trivia.
- In T1, the main-activity fans were left as alternates or unasked while side-interest members filled the group. T1 `2026-10-28/g1` trivia [204, 426]. T1 `2026-10-28/g8` birding: e175 declined because "birding isn't really her thing" [484]. T1 `2026-11-01/g2` Seahawks [824, 909]. T1 `2026-11-01/g10` cribbage [845, 1027].

**Root cause:**
- The plan showed `id:keenness` with no hint of which tag the score came from.
- A beer fan in the trivia room looked the same as a trivia fan.

**Fix:**
- Each of the keenest is now shown as `e049:5 [craft beer]`.
- Rooms list what the activity is about.
- The prompt says to describe only interests people actually have.

**Effect:**
- **Descriptions are more accurate.** The P2 trivia group reads "one genuine trivia buff to carry the team and three craft-beer fans along for the pints". Fable found no medium hub-claim issues in P2; it found two low ones, such as "all also enjoy live music" when one member doesn't.
- **No measurable change in who gets placed for a side interest only:**
  - P1 → P2: 24% → 30%
  - T1 → T2 (Saturday only): 13% → 8%

  Those swings are 2–3 people either way. Whether the main interest should be required is still the team's open question Q1.

### 4. Medium · supported, 4 groups · reduced: confirmation messages invent shared interests

**Where:**
- P1 `2026-10-28/g1` [326]: "Kevin and Quinn both share your love of live music"; Quinn doesn't like live music.
- P1 `2026-10-28/g6` [336]: Wei called a history lover.
- P1 `2026-10-31/g5` [482]: "Ron's into coffee and crafts".
- S `g3` [72], low: "you all love watching sports and golf".

**Why it matters:** this is the one message a person reads, and it states things about their neighbors that aren't true.

**Root cause:** the writer got only each person's one-paragraph brief and guessed the overlaps.

**Fix:** code now works out WHAT THEY SHARE (every like held by two or more members, with names), and the prompt allows shared-interest claims only from that list.

**Effect:** P2 had no medium message findings. What remains is overstated degree, which is low: "love" for someone who is only "up for" it, at P2 `2026-10-28/g2` [179] and `2026-10-31/g4` [326].

### 5. Medium · confirmed · open (product decision): the same people get chosen day after day; parents are passed over

**Where:** T1, over three days.
- Only 82 of 200 people were asked, and 104 who fitted at least one room were never asked.
- 120 places went to 80 people: 4 were placed all three days and 32 twice. 15 pairs met twice.
- Asked, among those who fitted some room: retirees 15/22 (68%), students 6/10, commuters 35/75, remote workers 12/42, **parents at home 4/17 (24%)**, **people with kids 14/52 (27%)**.
- Fable's day audits [533, 755] add that whole popular rooms got no group and the keenest people in several rooms were never asked.

**Root causes:**
- Each `run_day` stands alone: nothing records who was placed yesterday.
- The hub sees profiles only for the 8 keenest per room, in the same order every day.
- There is a 10-group daily cap.

**Recommendation:** decide team question Q6 (favor whoever has been placed least). The smallest code change would put "placed N times this week" in the plan's people lines, or make code rotate who gets a profile slot. Not changed here: it changes who gets matched, which is a product call.

### 6. Medium · confirmed · fixed: round 2 used as a broadcast channel

**Where:**
- P1 day 1: the hub "re-asked" every member of 5 groups who had already said yes, with "Confirmed: … with Quinn, Kevin and Heather". That was 20 agent calls, each able only to repeat or undo a settled yes [168; asks 172–299].
- P1 `2026-10-31/g4`: the remaining two members were told "Grace can't make it" [452, 454]. Whether someone declined is their private answer.

**Root cause:** the resolve step has only one action, `ask`, so a message that should be a notice goes out as a question.

**Fix:**
- A prompt line: only ask for answers still needed, no confirmations, never name a decliner.
- Code now skips a re-ask of a yes whose time hasn't changed, and logs that it did.

**Effect:**
- P2 had 43 agent calls, against 69 in P1, with no confirmation re-asks and no named decliners. It cost $0.43 against $0.51.
- P2 and T2 had no round 2 at all (every agent said yes in round 1), so the code skip is covered by tests but hasn't fired live.

### 7. Low · confirmed · fixed: 4 of the 200 emulated people liked the same thing twice

**Where:** e110, e120, e124, e181, all parents at home. Wei's profile read "Really likes: farmers market" and "Is up for: farmers market".

**Why it matters:** the agent saw a contradiction, and `demand.fit` counted the tag twice in keenness.

**Root cause:** the parents' interests and the kids' interests overlap, and `_pick` draws from a list with duplicates.

**Fix:** `population._merge_repeats` runs after all random draws. Only those 4 people change, and every other field of all 200 is identical, so the seed-7 town and earlier results stay comparable. The P1 and P2 cohorts are the same 30 people.

### 8. Rules the model is told but code didn't enforce · confirmed reachable · 0 of 4 live · guarded

**What could happen:**
- (a) Resolve moves a group's time and doesn't re-ask the people who said yes to the old time, and code still counted those yeses.
- (b) A time outside the group's day part was accepted, in the plan or in resolve, even though calendars are only checked per day part.

**Live:** all 4 time moves (P1 `2026-10-28/g4`; T1 `2026-10-28/g2`, `g5`, `2026-10-31/g8`) stayed inside the part and re-asked everyone.

**Guard:**
- A time outside the part is refused.
- After any move, code re-asks anyone the hub didn't.

These have tests; they have not fired live.

### 9. Low · supported · open

- **Overstated interest strength** in invitations and messages ("loves" for "really likes"): many low findings in every audited run.
- **Location claims** with no basis in the data ("close by", "no long drive"): P2 `2026-10-28/g2` [69, 74], `2026-10-31/g3` [242, 252]. The catalog has no distances, so the hub invents them. Either give it distances or forbid the claim.
- **Alternates who are already members of a later group** in the plan: S [60]. `check_plan` filters alternates only against earlier groups. It's harmless, because resolve refuses anyone who already said yes elsewhere.

## What held up

- **No hard-constraint violation in 67 groups.** Code guarded every rule, and the hub never tried anything code had to block.
- **No call failed, retried or came back unreadable** in 381 simulation calls and 69 audit and probe calls.
- **All three call records agreed on every day of every run.**
- **Agents follow their profiles almost always.** Fable judged 2 agents inconsistent (finding 1) out of the agents in the 25 audited groups. Declines were for stated reasons: Olivia, Grace, Ava on birding, Cody on Seahawks.
- **Counter-offers work end to end.** All 4 were accepted by moving the time and re-asking everyone (P1 `2026-10-28/g4`; T1 `2026-10-28/g2`, `g5`, `2026-10-31/g8`).
- **Group quality is mostly good.** Fable's verdicts across 25 audited groups:

  | | Good | Acceptable | Weak |
  |---|---|---|---|
  | Before the fixes (17 groups) | 9 | 7 | 1 (finding 1) |
  | After the fixes (8 groups) | 8 | 0 | 0 |

## How far to trust this

- **Acceptance of 95–100% is not, by itself, evidence of quality.** Break rooms already exclude every hard conflict, and the hub picks the keenest people. In P2 and T2 no agent was ever shown a conflict, so the "no" and negotiation paths weren't exercised after the fixes.
- **Before-and-after samples are small and not identical:** 12 groups before, 8 after, in the pilot. Rates are compared, not totals. Model replies vary.
- **The auditor makes mistakes too.** In S its day audit said Olivia's decline "couldn't be anticipated", while its own group audit showed it could. Day packets now include the full profiles of everyone asked. Findings are evidence-linked, not ground truth.
- **The town is synthetic:**
  - Calendars repeat by weekday.
  - There are no travel distances.
  - Only adults have agents.
- **The browser copy of the matchmaker** (`src/web/run-clawnly.js`, used by the standalone Artifact) doesn't have these fixes.

## Code changes

| File | Change | Why |
|---|---|---|
| `src/orchestration_sim.py` (new) | The harness: records every event, enforces a spending ceiling and a total-cap ledger, checks the three logs agree | Phase 2–4 |
| `src/orchestration_audit.py` (new) | Rule checks, the evidence-linked Fable audit, `compare`, `probe` | Phase 5–6 |
| `src/ai_log.py` | `audit_group` / `audit_day` purposes | So audit calls are logged like every other call |
| `src/matchmaker.py` | The plan shows the tags each person likes and what they avoid. Resolve gets an "only ask what you still need" line, and code skips re-asks of an unchanged yes. The message gets WHAT THEY SHARE. The agent gets the limit line. There's an `inside_part` guard, and code re-asks after a time move. | Findings 1–4, 6, 8 |
| `src/population.py` | `_merge_repeats` | Finding 7 |
| `tests/` | 42 new tests (269 in all, all passing, offline) | |
