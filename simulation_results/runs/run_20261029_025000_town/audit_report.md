# Audit: run_20261029_025000_town

Replies came from: **Claude (live Anthropic API)**.

Event numbers are `seq` in `full_simulation.jsonl` and `[nnnnnn]` in `full_transcript.txt`.

## Numbers

| | |
|---|---|
| agents | 200 |
| days | 3 |
| groups proposed | 30 |
| groups locked | 30 |
| groups dropped | 0 |
| invitations sent | 136 |
| agent replies | 136 |
| answers | {'yes': 129, 'no': 4, 'counter': 3} |
| acceptance rate | 0.949 |
| hard constraint violations | 0 |
| agents accepting a conflict they were shown | 2 |
| ai inconsistent agents | 2 |
| orchestration failures | 0 |
| days not done | 0 |
| simulation cost usd | 1.076078 |
| audit cost usd | 1.97362 |
| ai audit coverage | 2 of 30 groups, 3 of 3 days |

## Rule checks in code (4 findings)

- **medium** · quality issue · agent accepted a conflict it was shown: e117's agent said yes to 2026-10-31/g1 although code told it: It runs to 9pm or later, and Ava avoids late nights. Agents: e117. Groups: 2026-10-31/g1. Events: 560, 573.
  - Why: The agent is meant to check the plan against its person's profile; this yes ignores a conflict it was handed. Expected: No, or a counter that removes the conflict, unless the agent explains why it doesn't apply. Fix: Tighten the agent prompt, or have code refuse a yes that contradicts a hard check.
- **medium** · quality issue · agent accepted a conflict it was shown: e001's agent said yes to 2026-10-31/g1 although code told it: It runs to 9pm or later, and Nikhil avoids late nights. Agents: e001. Groups: 2026-10-31/g1. Events: 562, 578.
  - Why: The agent is meant to check the plan against its person's profile; this yes ignores a conflict it was handed. Expected: No, or a counter that removes the conflict, unless the agent explains why it doesn't apply. Fix: Tighten the agent prompt, or have code refuse a yes that contradicts a hard check.
- **medium** · quality issue · locked into a late night they avoid: e117 is locked into 2026-10-31/g1 (Kraken hockey night, 7pm-9:30pm): It runs to 9pm or later, and Ava avoids late nights. Agents: e117. Groups: 2026-10-31/g1. Events: 573, 791.
  - Why: The final plan conflicts with what this person told their agent. Expected: Nobody is locked into a plan their own profile rules out. Fix: Re-run plan_checks at lock time and refuse members with a hard conflict.
- **medium** · quality issue · locked into a late night they avoid: e001 is locked into 2026-10-31/g1 (Kraken hockey night, 7pm-9:30pm): It runs to 9pm or later, and Nikhil avoids late nights. Agents: e001. Groups: 2026-10-31/g1. Events: 578, 791.
  - Why: The final plan conflicts with what this person told their agent. Expected: Nobody is locked into a plan their own profile rules out. Fix: Re-run plan_checks at lock time and refuse members with a hard conflict.

## Independent AI audit (claude-fable-5-1, effort medium)

Sampling: all 1 groups code flagged or that didn't lock, plus 5 of the other 29 drawn with seed 7. Failures: 4.

| Group | Verdict | Summary |
|---|---|---|
| 2026-10-31/g1 | weak | The group is a sensible sports-watching table and the proposal, resolution and final messages are clean, but half of it rests on two agents saying yes to a late-night conflict code explicitly showed them. Ava's agent simply redefined 9:30pm as 'not a late night', and Nikhil's agent accepted 9:30pm after having countered a 9pm end as too late earlier in the run, while citing a 'no early morning after' that the calendar does not support. The matchmaker then locked the group without addressing either flag. |
| 2026-11-01/g10 | acceptable | The group locked cleanly with four quick yeses and no counters or declines, and all four agents answered in line with their profiles. The main weakness is composition: Hannah has no card interest at all while two keen card lovers (Liam A., Claire B.) sat unasked in the same break room, and the alternates chosen were also non-card people. Final messages are accurate on names and logistics but slightly inflate shared interests. |

**Day 2026-10-28 (acceptable):** The matchmaker planned ten groups that largely tracked the break-room evidence (fishing retirees, kayakers, MTB riders, pickleball foursome, crafts makers) and handled round 1 cleanly: both counters were accepted by shifting times and re-confirming everyone, and both declines were backfilled from unconflicted alternates, so all ten groups locked with 40 of 42 placed [426][490]-[509]. The weaker spots are in composition and spread: the trivia team was built from five people with no listed trivia interest while the one listed trivia lover in the room was only an alternate; the birding walk was filled with two non-birders over an available birder, producing a predictable decline; and large rooms (ten-trails 50, pickleball with eight keen-3 players) yielded a single foursome each, leaving clearly fitting people unasked. Several proposal messages slightly overstated shared interests. The day's outcome is defensible, but the planning left obvious fit on the table.

**Day 2026-10-31 (good):** The matchmaker planned ten small groups built around the two fixed evening events and the keenest-listed people in each room, with themes (history, photography, young riders) that the profiles actually support [533]. Every one of the 40 people asked said yes in round one except one counter, which it handled correctly by accepting the earlier time for a non-fixed event and re-confirming all members before locking [713][755][767]-[778][781]-[800]. The weakness is coverage and fairness: only 40 of 147 people in rooms were asked, several large or high-keenness rooms were left entirely unplanned, and some clearly keener candidates (e.g. e157 at 5 for Kraken) were passed over for less keen ones [533]. The day's outcome is defensible and all groups locked, but a few keen, available neighbors were left out without any stated reason.

**Day 2026-11-01 (good):** The matchmaker built ten groups of four from the break rooms, grounding most picks in room keenness and profile interests (photographers on the Gorge, history buffs at Franklin and the museum, picnic lovers at Flaming Geyser, twenty-somethings on the evening walk) [824]. All ten groups locked with four yeses after two declines were covered by alternates who accepted [1046][1052][1056][1059]-[1068]. The main weakness is the evening Seahawks group, where three of four initial members (e085, e074, e189) show no watch-sports interest in their profiles while e001 (watch sports 3) sat as second alternate; e085's decline was foreseeable and e198 was chosen over e001 on replacement [824][909][1046]. A few highly keen people (e153, e121, e173) were asked nowhere despite appearing near the top of several rooms, but with only 40 slots this is a judgment call rather than an error. The day's outcome is defensible and efficient (42 asked, 40 placed).

### Findings with evidence (16)

- **high** · quality issue · AI audit: Nikhil's agent accepted a 9:30pm finish, stating he has 'no early morning after', although his Sunday calendar shows only a free evening, and the same agent countered a 9pm end as 'later than he likes to be out' on Wednesday. Agents: e001. Groups: 2026-10-31/g1. Events: 562, 578, 274, 477.
  - Why: The yes rests on an unsupported calendar claim and directly contradicts the agent's own earlier reading of Nikhil's late-night avoidance, so the acceptance is not defensible from the profile. Expected: A counter or decline consistent with [274], or a yes grounded only in facts the profile contains. Fix: Remove the 'no early morning after' claim and treat the late-night flag the same way the agent did in [274].
- **medium** · quality issue · AI audit: Trivia team was assembled from five people whose profiles show no trivia interest (craft beer/golf/sports only), while e170 (trivia 3) was relegated to alternate and e196 (trivia 3, in the room) was not asked at all. Agents: e074, e075, e062, e157, e198, e170, e196. Groups: 2026-10-28/g1. Events: 204, 249, 426, 447, 500.
  - Why: The matchmaker's own 'why' frames g1 as a craft-beer group rather than a trivia group, so the activity itself was not the basis for selection; e170 only joined after e062 declined. Expected: Lead with people who list trivia (e170, e196), then fill with craft-beer fans. Fix: Seed activity-specific groups with people whose profiles name that activity before adding adjacent-interest fillers.
- **medium** · quality issue · AI audit: Birding walk was staffed with e175 and e136, neither of whom lists birding, while e060 (birding 2, in the room) was held as an alternate; e175 declined precisely because birding isn't her thing. Agents: e175, e136, e060, e038. Groups: 2026-10-28/g8. Events: 204, 384, 426, 484, 507.
  - Why: The plan substituted photography for birding as the matching basis, and the proposal to e038 told him 'the others love photography' rather than birding; the group also launched at only 3 people. Expected: Fill the birding group with people who list birding first (e060), keeping photographers as secondary fits or alternates. Fix: Prioritize the room's activity interest over proxy interests; use proxies only to fill remaining seats.
- **medium** · quality issue · AI audit: Pickleball room had eight players at keen score 3 (all pickleball 3 in profile) but only one foursome was formed, leaving e078, e167, e174, e182 unplaced (two as alternates, two never asked); the 50-person ten-trails room produced one group of 4, with e122 and e132 (keen 3) only alternates. Agents: e078, e167, e174, e182, e122, e132. Groups: 2026-10-28/g3, 2026-10-28/g10. Events: 204, 426, 502, 509.
  - Why: These people clearly fit by the matchmaker's own evidence; the plan's stated preference for a 'clean doubles foursome' and 3-5 person groups did not preclude running a second group from the same room. Expected: A second pickleball foursome and/or a second Ten Trails walking group drawn from the remaining keenest people. Fix: When a room has more clearly-fitting people than one group can hold, spin up additional parallel groups from the same room.
- **medium** · quality issue · AI audit: Several people who were the keenest in their rooms were never asked, while less keen people were placed in the same or similar activities; whole popular rooms (bakery morning, potluck, trail cleanup, Ten Trails walk, Franklin/Gorge morning) got no group at all. Agents: e157, e188, e127, e053, e081, e031, e184, e041. Groups: 2026-10-31/g1. Events: 533, 755.
  - Why: e157 was at 5 for the fixed Kraken night but e001 (3) was chosen instead and e157 was not placed anywhere; e081 is listed first in both pickleball rooms and the paddle rooms and was never asked; e188 (5) and e127 (4) led the bakery room, e053 (5) led the potluck, and e031/e184/e041 appear in the keenest list of four to five rooms each, yet none were invited. Only 40 of 147 people in rooms were asked, and the log gives no reason for skipping these [533]. Expected: Fill fixed-event groups with the keenest available people first, and plan at least one group for rooms where a clear keenest person exists (bakery, potluck, trail cleanup) so recurring high-keenness neighbors are not left idle. Fix: Add an 11th-12th group (e.g. bakery morning with e188/e127, trail cleanup with e159/e081), and prefer e157 over e001 or use him as first alternate for g1.
- **medium** · quality issue · AI audit: The evening Seahawks watch party was filled mostly with people whose profiles show no watch-sports interest; e085 (craft beer, mountain biking, book club, basketball) declined because he isn't into watching sports, and the replacement e198 (craft beer, running, boating) also lacks that interest, while e001 (watch sports 3) was left as an unused alternate. Agents: e085, e074, e189, e001, e198. Groups: 2026-11-01/g2. Events: 824, 909, 1046, 1056.
  - Why: Room keenness was a flat 3 for everyone, so profile interests should have driven selection; the 'why' called them sports fans but only e058 lists watch sports [824]. The decline was predictable and the mechanical 'first alternate' choice ignored the better-fitting e001 [1046]. Expected: Pick members for a watch party who list watch sports, and on a decline prefer the alternate whose profile best matches the activity. Fix: Put e001 ahead of e198 (or in e085's original slot) for g2; reserve e085 for a brewery or book-club style outing.
- **medium** · quality issue · AI audit: Ava's agent said yes to a 7-9:30pm event after code told it the event runs past 9pm and Ava avoids late nights, rationalizing that 9:30pm is 'not a late night'. Agents: e117. Groups: 2026-10-31/g1. Events: 560, 573.
  - Why: The agent overrode an explicit profile avoidance with its own opinion rather than the person's, and also ignored Ava's crowd avoidance for a bar on game night. Expected: A decline, or a yes that acknowledges the late-night and crowd concerns and explains why Ava would still accept. Fix: Have the agent decline or explicitly justify accepting against the shown late-night flag instead of redefining it.
- **medium** · quality issue · AI audit: The matchmaker proposed a fixed-time 7-9:30pm event to two members who avoid late nights and locked the group without addressing the conflicts, while listing Jim (no sports-watching interest, avoids crowds and spending) as an alternate. Groups: 2026-10-31/g1. Events: 535, 545, 560, 562, 755, 781.
  - Why: Half the group now carries a known lifestyle conflict even though the break room offered other sports-watching beer and golf fans, and the alternate pool offered little real backup. Expected: Prefer members without a late-night avoidance for a fixed late event, or at least choose alternates who like watching sports. Fix: Swap one late-night avoider for a break-room sports watcher such as Kevin B., and replace Jim with a sports-watching alternate.
- **medium** · quality issue · AI audit: Hannah, who lists no interest in cards, was placed in a four-hand cribbage game while Liam A. and Claire B. (both cards 3, keenness 3, retirees) were in the same break room and not asked; the alternates Arjun and Gary also have no card interest. Agents: e088. Groups: 2026-11-01/g10. Events: 845, 1027, 1043, 1078.
  - Why: A cribbage table needs four players; a seat given to someone with no card interest weakens the activity's stated purpose ('card lovers') and ignores better-fitting candidates. Expected: Fill the fourth seat and alternates from the card-keen candidates in the break room. Fix: Ask Liam A. or Claire B. for the fourth seat; keep Hannah for a coffee-centric group.
- **low** · quality issue · AI audit: Some proposals overstated shared traits: e012 was told 'the whole group' loves kayaking though e067 rates it 2; e035 was told the group is 'into baking and family life' though e008 (22, no kids) has no family noted; e124 was promised 'another photo fan' when e100 rates photography 1. Agents: e012, e035, e124. Groups: 2026-10-28/g7, 2026-10-28/g5, 2026-10-28/g4. Events: 204.
  - Why: Minor inaccuracies in pitch text, not material to decisions, but they slightly misrepresent the group to the invitee. Expected: Pitches that only claim what the profiles support. Fix: Generate 'why' claims from the actual interest scores of the other members.
- **low** · quality issue · AI audit: The two people most keen on the day's most popular evening room (Ten Trails walk: e082 at 8, e051 at 6) were redirected to the 1-hour dog walk, and that larger room was never planned. Agents: e082, e051. Groups: 2026-10-31/g6. Events: 533, 668, 673.
  - Why: The matchmaker's stated reason was that dog lovers were 'a natural fit' for the smaller walk, but the room evidence shows e082's strongest signal of the whole day was the Ten Trails walk. Both accepted, so the outcome held, but a 32-person room with the day's top keenness went unused [533][673][668]. Expected: Plan the Ten Trails walk for its keenest people, or at least note why it was dropped. Fix: Keep the dog walk for e011/e045 and others, and run an Evening Ten Trails walk with e082, e051, e098, e148 or similar.
- **low** · quality issue · AI audit: Some proposal texts overstate shared interests and the plan miscounts its own reach. Agents: e001, e094, e085. Groups: 2026-10-31/g1, 2026-10-31/g3. Events: 533.
  - Why: e001 was told the other three 'love watching sports and golf', but e117 lists no golf; e085 was told companions 'enjoy good food and craft beer', but e131 lists no craft beer. The plan's thoughts claim 41 neighbors placed while the groups total 40 [533]. These did not affect acceptance. Expected: Proposal claims should match the listed interests of the actual members, and summary counts should be accurate. Fix: Describe only interests the members actually have (e.g. 'sports fans, a couple of whom golf').
- **low** · quality issue · AI audit: Group rationales overstate fit: g1 is described as 'four committed sports watchers' though e051's profile has no watch-sports interest, and g10 as 'card lovers' though e088 lists no cards interest and e190 only cards 2. Agents: e051, e088, e190. Groups: 2026-11-01/g1, 2026-11-01/g10. Events: 824, 869, 1043, 1037.
  - Why: The individual proposals were honest (craft beer for e051, coffee for e088), and all accepted, but the internal justification doesn't match the profiles shown [824]. Expected: Group 'why' text should reflect the actual interests of the members chosen. Fix: Either choose members who match the stated theme (e.g., e153 or e129 for sports) or describe the group accurately as a mixed beer/coffee social.
- **low** · subjective concern · AI audit: Several people near the top of multiple rooms were not asked at all: e153 (keen 4 in gorge, franklin and afternoon Seahawks; watch sports 3), e121 (keen 4 in gorge), e173 and e043 (keen 3 in pickleball rooms, pickleball 3), while lower-keenness 'also' members such as e113, e162 and e111 were placed. Agents: e153, e121, e173, e043. Groups: 2026-11-01/g1, 2026-11-01/g3, 2026-11-01/g4, 2026-11-01/g5. Events: 824, 1046.
  - Why: With 46-person hiking rooms and only four slots per group, passing over some keen people is unavoidable, but e153 in particular was a strong fit for three different groups and ended up only as a second alternate [824][1046]. Expected: Keenest multi-room people get at least one invitation or are listed as first alternates. Fix: Make e153 first alternate in g1 or g4 and e001/e173 first alternates where they fit; consider an 11th group from the oversubscribed hiking rooms.
- **low** · subjective concern · AI audit: Ava avoids crowds, and a hockey night at a grill is plausibly crowded, but neither code nor the matchmaker nor her agent raised it. Agents: e117. Groups: 2026-10-31/g1. Events: 559, 573.
  - Why: It is a second profile avoidance that could make the evening unpleasant for her, though the log cannot show how busy the venue will be. Expected: The matchmaker or agent should at least note the crowd avoidance when pitching a game-night bar. Fix: Mention table/seating or crowd expectations in the pitch to Ava or pick a crowd-tolerant member.
- **low** · quality issue · AI audit: Final messages say Tom 'loves' golf and Grace shares 'a love for basketball', and Jack was told 'some experienced players will be at the table'; Tom is only 'up for' golf, Grace only 'up for' basketball, and no profile mentions cribbage experience. Groups: 2026-11-01/g10. Events: 1032, 1097.
  - Why: Messages should use only facts from the profiles; inflated or invented details mislead attendees about each other. Expected: Describe shared interests at their actual strength and omit claims the profiles don't support. Fix: Soften to 'Tom also enjoys golf', 'Grace is up for basketball too', and drop the 'experienced players' line.

### Findings dropped: no valid evidence cited (0)

None.

Audit failures: 2026-10-28/g6: spending ceiling reached; the simulation made no further calls; 2026-11-01/g5: spending ceiling reached; the simulation made no further calls; 2026-10-28/g10: spending ceiling reached; the simulation made no further calls; 2026-10-28/g8: spending ceiling reached; the simulation made no further calls

## Who got a chance (all days)

| Kind | People | In a room | Asked | Placed | Placements |
|---|---|---|---|---|---|
| all | 200 | 186 | 82 | 80 | 120 |
| archetype: commuter | 77 | 75 | 35 | 34 | 52 |
| archetype: parent at home | 21 | 17 | 4 | 4 | 7 |
| archetype: remote worker | 47 | 42 | 12 | 12 | 19 |
| archetype: retiree | 22 | 22 | 15 | 15 | 21 |
| archetype: shift worker | 23 | 20 | 10 | 9 | 11 |
| archetype: student | 10 | 10 | 6 | 6 | 10 |
| budget: any | 103 | 98 | 38 | 38 | 56 |
| budget: free | 27 | 22 | 8 | 7 | 12 |
| budget: low | 70 | 66 | 36 | 35 | 52 |
| kids at home | 65 | 52 | 14 | 13 | 20 |

In a break room on some day but never asked: 104 people.
