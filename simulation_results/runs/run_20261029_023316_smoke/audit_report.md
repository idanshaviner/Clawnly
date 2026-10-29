# Audit: run_20261029_023316_smoke

Replies came from: **Claude (live Anthropic API)**.

Event numbers are `seq` in `full_simulation.jsonl` and `[nnnnnn]` in `full_transcript.txt`.

## Numbers

| | |
|---|---|
| agents | 8 |
| days | 1 |
| groups proposed | 3 |
| groups locked | 3 |
| groups dropped | 0 |
| invitations sent | 8 |
| agent replies | 8 |
| answers | {'yes': 7, 'no': 1, 'counter': 0} |
| acceptance rate | 0.875 |
| hard constraint violations | 0 |
| agents accepting a conflict they were shown | 0 |
| ai inconsistent agents | 0 |
| orchestration failures | 0 |
| days not done | 0 |
| simulation cost usd | 0.094614 |
| audit cost usd | 0.62607 |
| ai audit coverage | 3 of 3 groups, 1 of 1 days |

## Rule checks in code (0 findings)

None.

## Independent AI audit (claude-fable-5-1, effort medium)

Sampling: every group. Failures: 0.

| Group | Verdict | Summary |
|---|---|---|
| 2026-10-31/g1 | good | A clean two-person pairing: Wei and Susan both have hiking and photography near the top of their profiles, are both free Saturday morning, and the free cost satisfies both budgets. Both agents said yes with reasons that match their profiles, the matchmaker needed no alternates, and the final messages name only the two attendees and use only profile facts. The only quibble is mild overstatement of 'love' versus 'really likes' in some messages. |
| 2026-10-31/g2 | good | A clean two-person match: both members are Morgan Creek residents who rank history and hiking among their top interests, both avoid loud places, both are free Saturday afternoon, and the free cost respects Imani's budget. Both agents accepted on grounds that match their profiles, the matchmaker's messages were accurate and named only the two attendees, and the group locked in a single round without waste. |
| 2026-10-31/g3 | acceptable | The final trio (Cody, Rosa, Kevin) is a sound sports-and-beer group that locked at the proposed time with no counters or re-asks. The main weakness is the matchmaker's original framing of 'four big sports fans' when Olivia's profile has no sports-watching interest at all and she avoids competitive settings, making her decline predictable and the ask somewhat wasted. Final messages are mostly accurate but lean on small overstatements of interest levels. |

**Day 2026-10-31 (good):** The plan tracked the break-room keenness scores closely: g1 took the two 5-rated people from the gorge morning room, g2 took two 5-rated Morgan Creek history-and-hiking people from the franklin afternoon room, and g3 took all four top-rated people from the kraken evening room [12]. All 8 neighbors were asked, 7 said yes, and the one decline (Olivia, e158) was for a reason not visible in her profile or room score, so the matchmaker could not have anticipated it [12][54]. The resolve step kept all three groups at their original times, correctly noting there were no unused alternates for g3 [60][62-67]. The outcome is defensible; the only soft points are the deliberate choice of two-person groups, a small overstatement in one invitation, and no attempt to re-place Olivia after her decline.

### Findings with evidence (9)

- **medium** · quality issue · AI audit: The matchmaker described the group as 'Four big sports fans' and invited Olivia, whose profile lists no sports-watching interest and an 'avoids: competitive' flag. Agents: e158. Groups: 2026-10-31/g3. Events: 19, 16, 41, 54, 60.
  - Why: The rationale was not supported by her profile, and the invite produced a predictable decline, leaving a three-person group with no alternates. Expected: Either pick someone with a sports interest or frame the group honestly as three fans plus a food/beer companion. Fix: Base the group reason only on interests each invitee actually has.
- **low** · subjective concern · AI audit: The matchmaker's reason [17] says both 'love photography' and the invite to Susan [22] says the other neighbor 'loves hiking and photography as much as you do', but Wei only 'really likes' hiking and Susan only 'really likes' photography. Groups: 2026-10-31/g1. Events: 17, 22.
  - Why: Slight overstatement of interest levels, though the underlying facts (both have both interests) are true. Expected: Describe interests at the level the profiles state. Fix: Phrase as 'into hiking and photography' rather than 'loves' where the profile says 'really likes'.
- **low** · insufficient evidence · AI audit: Imani's profile says she avoids long drives, and neither the matchmaker nor her agent addressed how far the Franklin trail on Green River Gorge Rd is from Morgan Creek. Agents: e020. Groups: 2026-10-31/g2. Events: 24, 25, 33.
  - Why: If the trailhead is a long drive it would clash with a stated avoidance, but the log gives no distance information and code found no conflict. Expected: The matchmaker or agent could have noted the travel distance when evaluating the location. Fix: Mention approximate travel time from Morgan Creek in the invitation when a person avoids long drives.
- **low** · quality issue · AI audit: Rosa was told the three others 'love sports and craft beer as much as you do'. Agents: e075. Groups: 2026-10-31/g3. Events: 36.
  - Why: Cody has no craft beer interest and Olivia has no sports interest, so the claim overstated the fit. Expected: Describe the others' interests accurately ('a couple share your love of craft beer'). Fix: Soften 'three other neighbors who love sports and craft beer' to match the profiles.
- **low** · quality issue · AI audit: Final messages say 'all three of you loving to watch sports' and 'You all love watching sports and golf', and the headline calls them 'Black Diamond regulars'. Agents: e094, e157. Groups: 2026-10-31/g3. Events: 72.
  - Why: Kevin only 'really likes' watching sports, Rosa is merely 'up for' golf, and the three live in Ten Trails, Downtown and Black Diamond Ridge; 'regulars' is not in any profile. Expected: Use interest levels as stated and avoid inventing a shared label. Fix: Rephrase to 'you all enjoy watching sports' and drop 'regulars'.
- **low** · insufficient evidence · AI audit: Kevin avoids crowds, yet neither the matchmaker nor his agent addressed whether a grill on a Saturday game night / Halloween would be crowded. Agents: e157. Groups: 2026-10-31/g3. Events: 46, 47, 57.
  - Why: A potentially relevant discomfort went unexamined, though the log gives no information about expected crowd size. Expected: The agent or matchmaker could have noted the small-group, relaxed framing explicitly against the crowds concern. Fix: Have the agent acknowledge the crowds flag when saying yes.
- **low** · subjective concern · AI audit: The four daytime hikers were split into two groups of two rather than one group of four, leaving each hike one decline away from collapsing. Agents: e124, e104, e020, e143. Groups: g1, g2. Events: 12, 28, 33, 38, 43.
  - Why: The matchmaker's own thoughts note the hikers 'would stack into one group of four if left alone' and chose to split them [12]; it worked because all four said yes [28][33][38][43], but the plan carried avoidable fragility. Expected: Either one group of four on a shared top-rated hike (franklin afternoon had all four at 5), or two groups with overlapping alternates who were not already committed elsewhere. Fix: When splitting a cohort into pairs, keep uncommitted alternates available or default to a single larger group.
- **low** · quality issue · AI audit: After Olivia declined g3, the matchmaker made no attempt to find her another placement, leaving her the only unplaced neighbor. Agents: e158. Groups: g3. Events: 12, 54, 60.
  - Why: The resolve step only stated there were no alternates to ask for g3 [60]; it did not consider the other evening rooms where she scored highly (big-block 6, vault-music 4) [12], though every other evening person was already committed to g3, so options were genuinely thin. Expected: A brief check of whether any alternative group could be formed for the declined person before closing the day. Fix: On a decline, scan the declined person's other high-scoring rooms for anyone not yet placed before concluding no re-ask is possible.
- **low** · quality issue · AI audit: Rosa's invitation said she'd be with 'three other neighbors who love sports and craft beer as much as you do', but Cody (e094) lists no craft beer interest. Agents: e075. Groups: g3. Events: 12.
  - Why: Profiles show craft beer only for e075, e158 and e157; e094 has golf, dining, watch sports, hiking [12]. The claim slightly overstates the group's shared interests. Expected: Invitations describe co-members' interests accurately, e.g. 'some of them are craft beer fans' as used in Kevin's message. Fix: Only state shared interests that every referenced member actually lists.

### Findings dropped: no valid evidence cited (0)

None.

## Who got a chance (all days)

| Kind | People | In a room | Asked | Placed | Placements |
|---|---|---|---|---|---|
| all | 8 | 8 | 8 | 7 | 7 |
| archetype: commuter | 4 | 4 | 4 | 3 | 3 |
| archetype: parent at home | 1 | 1 | 1 | 1 | 1 |
| archetype: remote worker | 2 | 2 | 2 | 2 | 2 |
| archetype: retiree | 1 | 1 | 1 | 1 | 1 |
| budget: any | 3 | 3 | 3 | 2 | 2 |
| budget: free | 1 | 1 | 1 | 1 | 1 |
| budget: low | 4 | 4 | 4 | 4 | 4 |
| kids at home | 1 | 1 | 1 | 1 | 1 |

In a break room on some day but never asked: 0 people.
