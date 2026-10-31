# Audit: run_20261030_212909_retest

Replies came from: **Claude (live Anthropic API)**.

Event numbers are `seq` in `full_simulation.jsonl` and `[nnnnnn]` in `full_transcript.txt`.

## Numbers

| | |
|---|---|
| agents | 200 |
| days | 3 |
| groups proposed | 30 |
| groups locked | 29 |
| groups dropped | 1 |
| invitations sent | 123 |
| agent replies | 123 |
| answers | {'yes': 114, 'no': 9, 'counter': 0} |
| acceptance rate | 0.927 |
| hard constraint violations | 0 |
| agents accepting a conflict they were shown | 0 |
| ai inconsistent agents | 0 |
| orchestration failures | 0 |
| days not done | 0 |
| simulation cost usd | 1.229192 |
| audit cost usd | 2.19538 |
| ai audit coverage | 2 of 30 groups, 2 of 3 days |

## Rule checks in code (0 findings)

None.

## Independent AI audit (claude-fable-5-1, effort medium)

Sampling: all 1 groups code flagged or that didn't lock, plus 7 of the other 29 drawn with seed 7. Failures: 7.

| Group | Verdict | Summary |
|---|---|---|
| 2026-11-01/g4 | weak | The matchmaker built a 'hike' around three retired anglers none of whom list hiking, pitched it to them with fishing-flavored language the event doesn't support, and then spent two more asks on alternates who also don't hike. All agents answered in line with their profiles, four of five declining for exactly that reason, and the group was dropped with only one yes. No hard rule was broken, but the selection and framing were poor and keen hikers in the break room were ignored. |
| 2026-11-01/g10 | good | A clean, all-yes round: four craft-beer fans were proposed, each agent accepted on grounds that match its person's profile, and the group locked without needing alternates. The matchmaker's invitations addressed each person's sensitivities (noise, late nights, cost) and the final messages name only attendees with mostly accurate facts. Only minor wording overstatements and one unsupported claim appear. |

**Day 2026-10-30 (good):** The matchmaker built ten small groups that tracked the break-room evidence closely: every member was a keen or listed participant in the chosen room, times were set to respect late-night and early-morning avoidances, and no one with a competitive or crowd aversion was placed in a poorly matched activity [204]. All 41 people asked accepted in round one and all ten groups locked at their original times, so the resolve step correctly needed no changes [431][433]-[452]. The main weakness is reach: despite stating a goal of spreading plans to as many neighbors as possible, it formed only 10 of the 18 viable rooms and left several people with strong interests (fishing, cribbage, basketball, evening mountain biking, extra pickleball players) unplaced [203][204]. A few proposals also asserted short drives or proximity to drive-averse neighbors without any supporting evidence in the room data [204]. Overall the day's outcome is defensible and well executed, but it under-used the available demand.

**Day 2026-11-01 (acceptable):** Nine of ten groups locked and 33 of 41 people asked were placed, and most groups were built from the keenest people in each room with times that respected stated avoidances [750][992]-[1001]. The main weaknesses are in what the matchmaker chose not to build and how it handled g4: the cribbage room held four strong card/coffee fans with no plans this week yet was never mentioned or formed, while g4 was assembled from three fishing/photography retirees for an event the room defines as a hike, then patched with two more non-hikers after the first two declined for exactly that reason [750][840][850][957][967][979][985]. A zero-plan keenest hiker (e059) was passed over in g8 in favour of alternates who already had plans, and the g8 follow-up was pitched as a 'walk' to a runner after members had been pitched a 'run' [750][957][973]. The day's outcome is defensible overall, but the misallocated group and the overlooked cluster cost several well-fitting neighbors a plan.

### Findings with evidence (15)

- **high** · quality issue · AI audit: The cribbage-and-coffee afternoon room had five keen people (e128, e061, e047, e133, e188), three of them with no plans this week, but no group was planned there and the matchmaker's thoughts never mention it. Agents: e128, e061, e047, e133, e188. Events: 750, 985.
  - Why: The brief is to spread invitations fairly and not pass over people who clearly fit. e061 (83, cards 2, no plans), e047 (cards 2, no plans) and e128 (coffee 2, no plans) were a ready-made low-cost cluster, while a group slot went instead to g4, built from people whose stated interests did not match a hike [750][985]. Expected: Within the 10-group cap, form the cribbage group (or at least weigh it explicitly) ahead of a hike group staffed by non-hikers. Fix: Plan a cribbage/coffee group for e128, e061, e047, e133 with e188 as alternate; drop or re-staff g4.
- **high** · quality issue · AI audit: The matchmaker proposed a Green River Gorge hike to three people whose profiles list fishing but not hiking, explicitly reasoning 'three retired anglers'. Groups: 2026-11-01/g4. Events: 755, 765, 840, 850.
  - Why: The group was selected for an interest the activity doesn't involve; two of three declined for exactly that reason and the group collapsed, while keen hikers (e171, e132, e104, keenness 3) sat unused in the same break room. Expected: Fill a hike with people who list hiking, or propose a fishing outing for the anglers. Fix: Swap the activity to a riverside fishing afternoon for e190/e186/e069, or build the hike from e171/e132/e104.
- **medium** · quality issue · AI audit: Eight of the 18 rooms that met the minimum (two strong-interest people) were not formed, and several keen neighbors were left out entirely or only as alternates: sawyer-fishing (e190:3, e111:2), cribbage (e161:3, e125:2 plus six mild), hoops (e077:3, e091:2), mtb evening (e091:3), lumber-house afternoon (e037:2), sawyer-paddle (e012:2), and three keen pickleball players (e113, e032) were left as alternates while only one court was planned. Agents: e190, e111, e161, e125, e091, e077, e012, e037, e113, e032. Events: 203, 204.
  - Why: The matchmaker's own stated goal was to spread one plan across as many neighbors as possible, yet only 41 of 83 people in rooms were asked; the fishing and cribbage rooms in particular had enough keen and mild members to form a small group, and the pickleball room had 7 keen players for a single 4-person court. Expected: Form additional small groups where two strong-interest people plus mild alternates exist (fishing, cribbage), consider a second pickleball court or a 6-player rotation, and find a slot for e091 (strong in both mtb and hoops). Fix: Review every room meeting the minimum before finalizing; where a room is dropped, record a reason, and offer unplaced keen people a seat in a related room where they appear as alternates.
- **medium** · quality issue · AI audit: g4 was built as 'three retired anglers' for an event the break room defines as a Green River Gorge hike; two of three declined because it is a hike, and the round-2 asks went to two more people (e188 fishing/coffee, e038 photography) with no hiking interest, who also declined, so the group was dropped. Agents: e190, e186, e069, e188, e038, e171, e132. Groups: 2026-11-01/g4. Events: 750, 840, 850, 957, 967, 979, 985.
  - Why: The room listed hiking-keen people (e171:3, e132 in the room, e031/e099/e169) and the matchmaker's own messages described a hike with 'river access'. Re-framing a hike as a fishing outing and then re-asking non-hikers after hike-based declines was unlikely to succeed and cost e069 his only plan [750][840][850][957][967][979][985]. Expected: Staff a hike with at least some hiking-keen members (e.g. e171, free Sunday afternoon and alternate in two groups where he was not needed, or e132), and after two 'not a hiker' declines ask hikers rather than more anglers/photographers. Fix: In round 2 ask e171 or e132 for g4 instead of e188/e038, or merge e069 into another afternoon outing.
- **medium** · quality issue · AI audit: e059 (hiking 2, no plans this week) was in g8's keenest list but was neither invited nor made an alternate; alternates e109 and e170 both already had a plan this week. After e177 declined, e109 was asked instead of e059. Agents: e059, e109, e170, e177. Groups: 2026-11-01/g8. Events: 749, 750, 957, 973.
  - Why: The matchmaker stated that tight seats went to people with fewer plans, but applied the opposite here, passing over a zero-plan keenest neighbor for people with plans [749][750][957]. Expected: Use e059 as first alternate (or member) for g8 consistent with the fewer-plans rule. Fix: Ask e059 for the g8 vacancy before e109/e170.
- **medium** · quality issue · AI audit: Round-1 invitations described the hike with fishing-oriented language ('good river access', 'a chance to try the river together'). Groups: 2026-11-01/g4. Events: 823, 833, 834, 855.
  - Why: The proposed event is a hike, not a fishing trip; the framing misrepresents the activity and led e069's agent to say yes on the basis of fishing. Expected: Describe the activity as what it is. Fix: Remove the river/fishing pitch and state it is a 1-4pm hike along the gorge.
- **medium** · quality issue · AI audit: Both alternates asked in round 2 (e188, e038) have no hiking interest and neither fits the stated 'retirees in their 70s' concept. Groups: 2026-11-01/g4. Events: 957, 961, 963, 967, 979, 985.
  - Why: Two more asks were spent on people whose profiles gave no reason to expect a yes, and the group was dropped anyway. Expected: Ask alternates whose profiles support the activity, such as the keen hikers listed in the break room. Fix: Replace e188/e038 with e171 or e132 or e104 as alternates.
- **low** · insufficient evidence · AI audit: Proposals told drive-averse neighbors that venues were 'not a long drive', 'not far', 'close', or 'no long drive' (e058 for Maple Valley courts, e008/e180 for the Green River Gorge Rd trail, e198 for Lumber House). Agents: e058, e008, e180, e198. Groups: 2026-10-30/g8, 2026-10-30/g5, 2026-10-30/g2. Events: 204.
  - Why: The break-room data gives locations but no distances or travel-time information, so these reassurances were not grounded in anything the matchmaker saw; several of these people explicitly avoid long drives. Expected: Describe the location factually without asserting proximity, or only claim it when the room data supports it. Fix: Only include distance claims when the planning input contains distance or neighborhood-adjacency information.
- **low** · subjective concern · AI audit: Framing drifted between members of the same group: e109 was pitched a 'run/walk' while others in g3 were pitched a 'walk' or 'hike'; e116 was told another member 'loves local history' when e143's history interest is only level 1. Agents: e109, e116. Groups: 2026-10-30/g3, 2026-10-30/g7. Events: 204, 294, 369.
  - Why: Mixed framing within one outing risks mismatched expectations (a runner expecting pace vs. walkers), and the history overstatement is a small inaccuracy; both agents accepted, so impact appears minor. Expected: Consistent description of the activity's pace for all members and accurate characterization of co-members' interests. Fix: Use one shared activity description per group and describe others' interests at the level the profile supports.
- **low** · quality issue · AI audit: Members of g8 were pitched a 'group run' while the room and the round-2 ask describe an 'evening walk'; e177 declined because 'a walk' isn't a draw and e109 (running 3) declined because 'walking' isn't something she loves. Agents: e109, e177. Groups: 2026-11-01/g8. Events: 750, 930, 957, 973.
  - Why: Inconsistent framing between the plan's proposals and the follow-up ask likely contributed to two declines from people whose running interest fit the original pitch [750][930][957][973]. Expected: Describe the activity the same way in every message, matching what the room actually is. Fix: Pitch the round-2 ask as the same relaxed group run offered to the original members, or label it a walk throughout.
- **low** · subjective concern · AI audit: Hoops (e077 basketball 3 with no plans, e160 basketball 3) and the Seahawks afternoon room (e003, e115, e139 — three keen, not two) were dropped as 'two-person options' under the group cap. Agents: e077, e160, e003. Events: 748, 750.
  - Why: The matchmaker's stated reason mischaracterises the Seahawks room's size, and a two-person group is explicitly allowed by the room rule; whether these should have displaced g4 is a judgment call [748][750]. Expected: Accurate counting of room strength when deciding which rooms to drop. Fix: Reconsider hoops or Seahawks before a hike group with no hikers.
- **low** · subjective concern · AI audit: Noah's agent accepted a hike citing his love of fishing and 'a free river outing with fellow anglers'. Agents: e069. Groups: 2026-11-01/g4. Events: 834, 855.
  - Why: The yes rests on an activity the event doesn't include; Noah doesn't list hiking, so the acceptance is weakly grounded, though prompted by the matchmaker's wording. Expected: Judge the proposal as a hike and either accept on Noah's general outdoor fit or ask whether fishing is actually part of it. Fix: Base the reply on the stated activity rather than the invitation's river framing.
- **low** · quality issue · AI audit: Final messages say Ava 'shares your love of book club' and 'the whole crew loves craft beer' although Ava's profile lists book club as only 'up for' and craft beer as 'really likes'. Agents: e117, e085. Groups: 2026-11-01/g10. Events: 1018.
  - Why: The final messages should only state facts from the profiles; these mildly overstate Ava's interest. Expected: Describe Ava as 'up for book club' / 'also into craft beer'. Fix: Soften the wording to match the profile ratings.
- **low** · insufficient evidence · AI audit: The invitation to Mateo claims Lumber House is 'close by'. Agents: e173. Groups: 2026-11-01/g10. Events: 933.
  - Why: Nothing in the log gives the brewery's location relative to Morgan Creek, so the claim is unsupported (though Mateo does not avoid long drives, so no harm). Expected: Invitations should use only facts the matchmaker can support. Fix: Drop 'and close by' or replace with a supported detail such as the early finish.
- **low** · subjective concern · AI audit: Ava and Cody also said yes to Pints at Lumber House on the two preceding days of the run. Agents: e117, e085. Groups: 2026-11-01/g10. Events: 269, 642, 1001.
  - Why: Proposing the same venue and activity to the same people on consecutive days may reduce variety, though the log does not show whether those earlier groups locked. Expected: Vary activities or venues across days for the same person where possible. Fix: Check prior-day assignments before repeating an identical outing.

### Findings dropped: no valid evidence cited (0)

None.

Audit failures: day 2026-10-31: the auditor's reply wasn't JSON; 2026-10-30/g6: spending ceiling reached; the simulation made no further calls; 2026-11-01/g5: spending ceiling reached; the simulation made no further calls; 2026-10-30/g10: spending ceiling reached; the simulation made no further calls; 2026-10-30/g8: spending ceiling reached; the simulation made no further calls; 2026-11-01/g9: spending ceiling reached; the simulation made no further calls; 2026-10-30/g1: spending ceiling reached; the simulation made no further calls

## Who got a chance (all days)

| Kind | People | In a room | Asked | Placed | Placements |
|---|---|---|---|---|---|
| all | 200 | 161 | 95 | 91 | 113 |
| archetype: commuter | 77 | 67 | 40 | 39 | 50 |
| archetype: parent at home | 21 | 13 | 6 | 6 | 9 |
| archetype: remote worker | 47 | 33 | 18 | 18 | 21 |
| archetype: retiree | 22 | 18 | 12 | 9 | 10 |
| archetype: shift worker | 23 | 20 | 13 | 13 | 16 |
| archetype: student | 10 | 10 | 6 | 6 | 7 |
| budget: any | 103 | 84 | 50 | 47 | 56 |
| budget: free | 27 | 19 | 9 | 9 | 14 |
| budget: low | 70 | 58 | 36 | 35 | 43 |
| kids at home | 65 | 36 | 16 | 15 | 19 |

In a break room on some day but never asked: 66 people.
