# Audit: run_20261029_023732_pilot

Replies came from: **Claude (live Anthropic API)**.

Event numbers are `seq` in `full_simulation.jsonl` and `[nnnnnn]` in `full_transcript.txt`.

## Numbers

| | |
|---|---|
| agents | 30 |
| days | 2 |
| groups proposed | 12 |
| groups locked | 12 |
| groups dropped | 0 |
| invitations sent | 69 |
| agent replies | 69 |
| answers | {'yes': 67, 'no': 1, 'counter': 1} |
| acceptance rate | 0.971 |
| hard constraint violations | 0 |
| agents accepting a conflict they were shown | 0 |
| ai inconsistent agents | 0 |
| orchestration failures | 0 |
| days not done | 0 |
| simulation cost usd | 0.509644 |
| audit cost usd | 2.25627 |
| ai audit coverage | 12 of 12 groups, 0 of 2 days |

## Rule checks in code (8 findings)

- **medium** · quality issue · hub told others who declined: The hub's round-2 message to e075 in 2026-10-31/g4 names e148 ('Grace'), who had said no. Agents: e075, e148. Groups: 2026-10-31/g4. Events: 433, 452.
  - Why: Whether someone declined is their private answer; the group only needs to know who is coming. Expected: Messages before the lock say who is coming, never who said no. Fix: Say in the resolve prompt never to name decliners, and check hub messages in code.
- **medium** · quality issue · hub told others who declined: The hub's round-2 message to e133 in 2026-10-31/g4 names e148 ('Grace'), who had said no. Agents: e133, e148. Groups: 2026-10-31/g4. Events: 433, 454.
  - Why: Whether someone declined is their private answer; the group only needs to know who is coming. Expected: Messages before the lock say who is coming, never who said no. Fix: Say in the resolve prompt never to name decliners, and check hub messages in code.
- **low** · quality issue · re-asked a yes about an unchanged plan: In round 2 the hub asked 4 people in 2026-10-28/g1 (e081, e043, e078, e167) again although they had said yes and the time hadn't changed. Agents: e081, e043, e078, e167. Groups: 2026-10-28/g1. Events: 172, 174, 176, 178.
  - Why: Each is another agent call that can only confirm or, worse, flip a settled yes. Expected: Round 2 asks only alternates, people who countered, and yeses whose time changed. Fix: Tell the resolve step that confirmations go out after the lock; have code skip re-asks of an unchanged yes.
- **low** · quality issue · re-asked a yes about an unchanged plan: In round 2 the hub asked 5 people in 2026-10-28/g2 (e123, e049, e074, e170, e075) again although they had said yes and the time hadn't changed. Agents: e123, e049, e074, e170, e075. Groups: 2026-10-28/g2. Events: 185, 191, 197, 203, 209.
  - Why: Each is another agent call that can only confirm or, worse, flip a settled yes. Expected: Round 2 asks only alternates, people who countered, and yeses whose time changed. Fix: Tell the resolve step that confirmations go out after the lock; have code skip re-asks of an unchanged yes.
- **low** · quality issue · re-asked a yes about an unchanged plan: In round 2 the hub asked 3 people in 2026-10-28/g3 (e082, e046, e067) again although they had said yes and the time hadn't changed. Agents: e082, e046, e067. Groups: 2026-10-28/g3. Events: 215, 221, 227.
  - Why: Each is another agent call that can only confirm or, worse, flip a settled yes. Expected: Round 2 asks only alternates, people who countered, and yeses whose time changed. Fix: Tell the resolve step that confirmations go out after the lock; have code skip re-asks of an unchanged yes.
- **low** · quality issue · re-asked a yes about an unchanged plan: In round 2 the hub asked 3 people in 2026-10-28/g5 (e038, e069, e111) again although they had said yes and the time hadn't changed. Agents: e038, e069, e111. Groups: 2026-10-28/g5. Events: 257, 263, 269.
  - Why: Each is another agent call that can only confirm or, worse, flip a settled yes. Expected: Round 2 asks only alternates, people who countered, and yeses whose time changed. Fix: Tell the resolve step that confirmations go out after the lock; have code skip re-asks of an unchanged yes.
- **low** · quality issue · re-asked a yes about an unchanged plan: In round 2 the hub asked 5 people in 2026-10-28/g6 (e124, e143, e055, e148, e105) again although they had said yes and the time hadn't changed. Agents: e124, e143, e055, e148, e105. Groups: 2026-10-28/g6. Events: 275, 281, 287, 293, 299.
  - Why: Each is another agent call that can only confirm or, worse, flip a settled yes. Expected: Round 2 asks only alternates, people who countered, and yeses whose time changed. Fix: Tell the resolve step that confirmations go out after the lock; have code skip re-asks of an unchanged yes.
- **low** · quality issue · re-asked a yes about an unchanged plan: In round 2 the hub asked 2 people in 2026-10-31/g4 (e075, e133) again although they had said yes and the time hadn't changed. Agents: e075, e133. Groups: 2026-10-31/g4. Events: 452, 454.
  - Why: Each is another agent call that can only confirm or, worse, flip a settled yes. Expected: Round 2 asks only alternates, people who countered, and yeses whose time changed. Fix: Tell the resolve step that confirmations go out after the lock; have code skip re-asks of an unchanged yes.

## Independent AI audit (claude-fable-5-1, effort medium)

Sampling: every group. Failures: 2.

| Group | Verdict | Summary |
|---|---|---|
| 2026-10-28/g1 | acceptable | Four pickleball lovers, all free Wednesday evening, all within budget for a free event, were proposed, said yes twice and were locked without any conflict. The matchmaking logic was sound and the agents followed their profiles. The main flaws are in the final wrap-up: one message credits Quinn with a love of live music that his profile does not contain, the headline names Black Diamond while the courts are in Maple Valley, and one early pitch overstated how many baseball fans were in the group. |
| 2026-10-28/g2 | acceptable | All five said yes and the group locked cleanly at the original time with accurate, correctly-addressed final messages. The group hangs together on craft beer and the evening slot rather than on trivia: only Kavya's profile mentions trivia, so the matchmaker's stated rationale ('five trivia-keen neighbors') is not supported by the profiles, and one invite leaned on a 'sports fans' claim the profiles don't back. |
| 2026-10-28/g3 | good | A free evening walk for three runners who also enjoy hiking or dog walks, all free Wednesday evening, with two crowd-avoiders well served by a group of three. All three agents said yes for reasons grounded in their profiles, the matchmaker's outreach and final messages were accurate apart from slightly inflating 'really likes' to 'loves', and the group locked cleanly. The only quality wrinkle (re-asking unchanged yeses) was already flagged by code. |
| 2026-10-28/g5 | good | A clean, well-matched group: three retirees who all list birding among their top interests, a free morning walk that fits everyone's calendar and Claire's low-cost budget, and three straightforward yeses in round 1 followed by a lock. The matchmaker's messages used accurate profile facts and named only attendees. The only blemishes are the code-flagged redundant round-2 re-ask and a weak alternate choice that was never needed. |
| 2026-10-28/g6 | acceptable | A free afternoon hike with five people who all have an open Wednesday afternoon and mostly share hiking or history interests; every agent said yes consistently with its profile and the group locked cleanly. The main weaknesses are small embellishments in the matchmaker's pitches and a final message that calls Wei a history lover, which the profile does not support. |
| 2026-10-31/g4 | acceptable | The matchmaker proposed a fixed 7-9:30pm hockey night to three Downtown sports-watchers, one of whom (Grace) avoids late nights; she predictably declined and, with no alternates, the group locked as a pair. All three agents answered in line with their profiles, and the final messages are accurate and name only attendees. The main weaknesses are the foreseeable conflict in the proposal, the matchmaker's false claim that no counters were made, and the already-flagged leaking of Grace's name. |
| 2026-10-28/g4 | good | Four parents with kids at home who all rate coffee or baking highly were matched for a low-cost bakery meetup; all four agents answered in line with their profiles, Chris's early-morning counter was handled cleanly by moving the slot and re-confirming the others, and the group locked with everyone's yes. The only weaknesses are small overstatements in the invites and final messages (Mark described as a parent at home and as loving baking, Imani and Brian credited with interests they don't list). |
| 2026-10-31/g1 | good | A clean, well-founded group: all three list pickleball as a top love, all are free Saturday morning, and the event is free, so budgets are untouched. Every agent said yes with reasons that match its profile, and the final messages name only the three attendees and cite real profile facts. The only blemishes are small overstatements of shared interests in the matchmaker's rationale and one invitation. |
| 2026-10-31/g2 | good | A clean, well-matched group: three Saturday-morning-free neighbors who all list running as a strong interest, asked once each, all three said yes, and the group locked at its original time with no counters or re-asks. The only blemishes are small overstatements of Rachel's interest level (really likes, not loves) and an unaddressed question about her Downtown location and 'avoids long drives' preference that the log cannot resolve. |
| 2026-10-31/g3 | good | A clean, one-round negotiation: five people asked, five clear yeses, group locked at the proposed time with no wasted asks [383][398][403][408][428][464]. The members fit the activity on hiking, history, birding and photography, and the matchmaker's resolve step and final messages are accurate and name only attendees. Only minor framing issues exist: Ryan was pitched a 'gentle-paced walk' while everyone else was told it was a hike, and the final messages/headline stretch neighborhood proximity a little. |
| 2026-10-31/g5 | acceptable | A free Saturday evening walk for three neighbors who all show hiking or dog-walk interests, with free evenings on their calendars; all three agents said yes for reasons grounded in their profiles and the group locked cleanly. The main flaw is in the final messages, where the matchmaker tells Josh that Ron is into crafts, which Ron's profile does not support, plus a few small unsupported embellishments (Josh 'after shifts', Isabel's 'pup', 'Ten Trails regulars'). |
| 2026-10-31/g6 | good | A two-person kayak outing was proposed to two people who both list kayaking and craft beer, both free Saturday afternoon, and both said yes with reasons grounded in their profiles. The matchmaker's messages and the final confirmations stick to profile facts and name only the two confirmed paddlers. The only quibble is a small inferential flourish in Lauren's final message. |

### Findings with evidence (31)

- **medium** · quality issue · AI audit: The final message to Andres says 'Kevin and Quinn both share your love of live music', but Quinn's profile lists no interest in live music. Agents: e081, e043. Groups: 2026-10-28/g1. Events: 326.
  - Why: Final messages must use only facts from the profiles; this attributes an interest to Quinn that the log does not support. Expected: Name only Kevin (and Heather) as sharing live music with Andres. Fix: Change the sentence to reference Kevin and Heather for live music, or Kevin alone.
- **medium** · quality issue · AI audit: The matchmaker's reason for forming the group says 'Five trivia-keen neighbors', but only Kavya's profile lists trivia; the other four profiles contain no trivia interest, and the final message to Kavya acknowledges she is 'the one who actually loves trivia'. Groups: 2026-10-28/g2. Events: 37, 43, 328.
  - Why: The group was justified on an interest the profiles don't show, so the stated rationale is unsupported and internally contradicted by the matchmaker's own later text. Expected: A rationale grounded in the actual shared interest (craft beer, a free evening, low cost) with trivia framed as a relaxed social format. Fix: Rewrite the reason to 'Four craft-beer fans plus a trivia lover, all free Wednesday evening, make a well-sized team.'
- **medium** · quality issue · AI audit: Wei's final message says 'Carlos is another hiking and history lover from Morgan Creek like you', implying Wei loves history. Agents: e124. Groups: 2026-10-28/g6. Events: 336.
  - Why: Wei's profile lists picnics, photography, farmers market, hiking and dog walks but no history interest; final messages must use only profile facts. Expected: Describe only shared facts: Carlos also likes hiking and lives in Morgan Creek. Fix: Change to 'Carlos is another hiking lover from Morgan Creek like you'.
- **medium** · quality issue · AI audit: The matchmaker proposed a fixed-time event running to 9:30pm to Grace, whose profile says she avoids late nights, and had no alternates for the group. Agents: e148. Groups: 2026-10-31/g4. Events: 346, 406, 407, 433, 450.
  - Why: The decline was foreseeable from her profile (code flagged the same conflict to her agent), so a seat was spent on a near-certain no and the group shrank to two. Expected: Either pick a third member without a late-night conflict (e.g. consider Ron) or line up an alternate before asking. Fix: Check avoidances against the fixed end time before inviting, and name at least one alternate for a three-person group.
- **medium** · quality issue · AI audit: Josh's final message says 'Ron's into coffee and crafts too, which lines up nicely with your own interests.' Agents: e105, e052. Groups: 2026-10-31/g5. Events: 482.
  - Why: Ron's profile lists cards, not crafts; the matchmaker attributed a hobby to Ron that the log does not contain, so Josh is being told something false about a fellow attendee. Expected: Final messages should only use facts from the profiles; Ron's actual overlap with Josh is coffee (both 'up for') and mountain biking. Fix: Replace 'coffee and crafts' with 'coffee and mountain biking' in Josh's message.
- **low** · quality issue · AI audit: The final headline says the match is set 'in Black Diamond' while every other reference places the courts in Maple Valley. Groups: 2026-10-28/g1. Events: 36, 326.
  - Why: A conflicting location in the headline could confuse attendees about where to go. Expected: Headline should match the Maple Valley venue stated in the proposal and messages. Fix: Replace 'Black Diamond' with 'Maple Valley' in the headline.
- **low** · quality issue · AI audit: The pitch to Quinn said 'a few of them are baseball fans', but only Kevin lists baseball. Agents: e043. Groups: 2026-10-28/g1. Events: 50.
  - Why: Overstates the shared interest used to sell the plan. Expected: Say one of the group is a baseball fan. Fix: Reword to 'one of them is a big baseball fan too'.
- **low** · quality issue · AI audit: The invite to Rosa says 'there are a few sports fans in the mix for the sports round'. Groups: 2026-10-28/g2. Events: 79, 86.
  - Why: No other member's profile lists watching sports or a team sport; Rohan plays golf and others run, which doesn't support 'a few sports fans', and a 'sports round' is an invented event detail. Expected: Pitch based on facts in the profiles, e.g. shared craft beer. Fix: Drop the sports-fans sentence from Rosa's invite.
- **low** · subjective concern · AI audit: Kavya's final message singles her out: 'You're the one who actually loves trivia on your profile, so lean on you for the tiebreakers.' Groups: 2026-10-28/g2. Events: 328.
  - Why: It is factually true but reads as putting performance pressure on one member and exposes that the rest of the team wasn't picked for trivia interest. Expected: A neutral, welcoming note consistent with the other four messages. Fix: Replace with a line about the team and the shared taproom setting.
- **low** · quality issue · AI audit: Outreach and final messages describe 'really likes' interests as 'loves' (Donna's dog walks and running, Isabel's hiking) [44][84][330], and Donna's agent echoed this in [116]. Agents: e082, e046, e067. Groups: 2026-10-28/g3. Events: 44, 84, 116, 330.
  - Why: Mildly overstates how keen people are on shared interests; harmless here but not strictly what the profiles say. Expected: Describe interests at the strength the profile gives. Fix: Use 'enjoys' or 'really likes' where the profile does not say 'loves'.
- **low** · subjective concern · AI audit: Isabel (23) is paired with two members aged 58 and 61 [38][322]. Agents: e082, e046, e067. Groups: 2026-10-28/g3. Events: 38, 322, 330.
  - Why: A large stage-of-life gap could make the 'chatty' walk less natural, though nothing in the profiles indicates a clash and shared running/hiking interests are strong. Expected: Nothing required; a closer-aged runner would be a nice-to-have if available. Fix: No change needed; note age spread when choosing from the break room in future runs.
- **low** · subjective concern · AI audit: Hannah, an 84-year-old remote worker whose loves are running, coffee and basketball with no birding, fishing or cards interest, was listed as the sole alternate for a group pitched as retirees serious about birds. Agents: e088. Groups: 2026-10-28/g5. Events: 40, 46, 363.
  - Why: Had anyone declined, the fallback would have been someone with no shared interest in the activity, undermining the group's stated rationale. Expected: An alternate with some birding or outdoor-nature interest, or no alternate if none existed in the pool. Fix: Pick alternates by overlap with the activity's core interest rather than calendar availability alone.
- **low** · quality issue · AI audit: Pitches overstate the group: 'a couple of them keen on local history' (only Carlos), 'a few of them are sports fans' (Ryan and Josh), '4 other neighbors who love hiking' (Ryan lists no hiking), plus an invented 'steady pace, with plenty of stops'. Agents: e055, e148, e105. Groups: 2026-10-28/g6. Events: 144, 149, 154.
  - Why: These claims go beyond what the profiles and plan contain and could set wrong expectations. Expected: Pitches should state only counts and traits supported by the profiles. Fix: Use 'one other history buff', 'a couple of sports fans', 'other hikers', and drop the pace claim.
- **low** · subjective concern · AI audit: Ryan, 78, with no hiking interest in his profile, was placed on a three-hour hike. Agents: e055. Groups: 2026-10-28/g6. Events: 144, 159.
  - Why: His fit rests solely on 'history'; the hike itself may be a stretch, though his agent accepted it. Expected: Acceptable given the agent's yes, but worth a note on pace or an easier history option. Fix: None required; consider mentioning the walking distance in the pitch.
- **low** · subjective concern · AI audit: Grace's final message says Josh being a shift worker means 'your schedules and trail pace should line up well'. Agents: e148, e105. Groups: 2026-10-28/g6. Events: 336.
  - Why: Nothing in the profiles supports a pace claim; it is speculation. Expected: Mention only the shared hiking interest and shift-work. Fix: Drop 'and trail pace'.
- **low** · quality issue · AI audit: The resolve step says 'No counters were made' although Grace's agent proposed a 5-7:30pm alternative. Groups: 2026-10-31/g4. Events: 433, 450.
  - Why: The matchmaker misreported the record; the counter couldn't be accepted for a fixed-time event, but the reasoning should acknowledge and dismiss it rather than deny it. Expected: Note Grace's counter and state it can't apply because the game time is fixed. Fix: Change the thoughts to 'Grace countered with 5-7:30pm, but the event is fixed-time so it can't move.'
- **low** · subjective concern · AI audit: The pitch to Grace promised 'fellow baseball fans to chat with', but only Rosa lists baseball; Jack does not. Agents: e148. Groups: 2026-10-31/g4. Events: 406.
  - Why: A plural framing slightly oversells the group's shared interest. Expected: Say 'a fellow baseball fan' or stick to the shared sports-watching interest. Fix: Reword to singular.
- **low** · subjective concern · AI audit: The final pairing puts a 43-year-old commuter with a 20-year-old student. Agents: e075, e133. Groups: 2026-10-31/g4. Events: 471, 480.
  - Why: A large stage-of-life gap in a two-person outing may limit rapport, though the shared sports interest is genuine. Expected: Where possible, a third member closer in age (such as Grace) or a same-neighborhood alternate like Ron for Jack. Fix: No change required; note as a judgment call.
- **low** · quality issue · AI audit: Final messages say Mark 'loves' baking and that everyone/all three are 'parents at home with kids', but Mark's profile shows baking as 'really likes' and his occupation as shift worker. Agents: e035, e047, e041. Groups: 2026-10-28/g4. Events: 332.
  - Why: Final messages should use only facts from the profiles; this mislabels Mark's occupation and interest level. Expected: Describe Mark as a shift worker with kids at home who really likes baking. Fix: Change 'parent at home' to 'parent with kids at home' and 'loves' to 'enjoys' for Mark in the four final messages.
- **low** · quality issue · AI audit: Invites and the group reason claim all four love coffee and baking, but Imani lists no baking interest and Brian lists no coffee interest. Agents: e035, e047, e041. Groups: 2026-10-28/g4. Events: 45, 99, 109.
  - Why: Overstates the shared interests the group was sold on. Expected: Say the group shares coffee or baking rather than both. Fix: Reword to 'parents who love coffee or baking'.
- **low** · subjective concern · AI audit: The initial 9am start was proposed although Chris avoids early mornings, forcing a counter and a second confirmation round. Agents: e127. Groups: 2026-10-28/g4. Events: 39, 136, 168.
  - Why: A later initial slot would likely have avoided the extra round; whether 9am counts as 'early' is a judgment call. Expected: Pick a mid-morning start when a member avoids early mornings. Fix: Propose 10am or later initially.
- **low** · quality issue · AI audit: The matchmaker's rationale says all three share baseball and live music, and Quinn's invitation promises 'fellow baseball fans' (plural). Agents: e081, e078, e043. Groups: 2026-10-31/g1. Events: 349, 359.
  - Why: Andres's profile has no baseball and Quinn's has no live music; only Kevin likes baseball among Quinn's partners, so the shared-interest claims are overstated. Expected: Cite only interests actually present in each profile, e.g. pickleball for all three, baseball for Kevin and Quinn, live music for Andres and Kevin. Fix: Reword [349] to list the pairwise overlaps and change 'fellow baseball fans' in [359] to 'a fellow baseball fan'.
- **low** · subjective concern · AI audit: The event is framed as a 'rotation of doubles' but the group is locked at three people. Agents: e081, e078, e043. Groups: 2026-10-31/g1. Events: 343, 355, 462.
  - Why: Doubles needs four players, so three people cannot actually rotate doubles as advertised. Expected: Either recruit a fourth player or describe the session as singles/rotating play. Fix: Adjust the activity description to match a three-person session.
- **low** · quality issue · AI audit: The matchmaker's reason and final messages describe all three as 'dedicated' runners who 'love' running, and Rachel's agent also said she 'loves' running, but her profile lists running under 'really likes'. Agents: e123. Groups: 2026-10-31/g2. Events: 350, 393, 476.
  - Why: Minor overstatement of a profile fact in messages that should use only profile facts. Expected: Describe Rachel's interest accurately (really likes / enjoys running). Fix: Change 'love running just as much as you do' to 'all into running' or similar.
- **low** · insufficient evidence · AI audit: Rachel lives in Downtown and avoids long drives; the other two are in Lawson Hills and the venue is Ten Trails, but neither the matchmaker nor her agent addressed travel distance. Agents: e123. Groups: 2026-10-31/g2. Events: 372, 393.
  - Why: If Ten Trails is far from Downtown this could conflict with her stated avoidance, but the log gives no location information and code flagged no conflict. Expected: Nothing required if the venue is nearby; the log cannot tell. Fix: No change needed unless venue distance data shows a long drive.
- **low** · subjective concern · AI audit: Ryan (78, no hiking in profile) was pitched a 'gentle-paced walk' while every other member was told it is a hike; the proposal itself is a 3-hour 'Franklin ghost town hike' [386][387] vs [376][381][391][396]. Agents: e055. Groups: 2026-10-31/g3. Events: 386, 387, 408, 376.
  - Why: His agent's yes leans on the softer framing [408]; if the outing is a genuine hike, the pitch oversold its ease to the least hike-inclined, oldest member. Expected: Describe the activity the same way to everyone, or make the easy pace part of the actual plan. Fix: Use the same 'hike' wording in Ryan's pitch, or note the pace in the group plan.
- **low** · quality issue · AI audit: Final messages say Imani is 'in your neck of the woods' for Wei (Morgan Creek vs Black Diamond Ridge), headline calls all five 'Black Diamond neighbors' though they span three neighborhoods, and Wei is said to 'love' hiking when the profile says 'really likes' [478]. Groups: 2026-10-31/g3. Events: 478, 479.
  - Why: Small embellishments beyond the profile facts. Expected: Stick to stated neighborhoods and interest levels. Fix: Drop 'in your neck of the woods', say 'local neighbors', and 'enjoys hiking'.
- **low** · insufficient evidence · AI audit: Imani's agent asserted the trail is 'close to home with no long drive' [428], a fact not present in the proposal or profile [396][397]. Agents: e041. Groups: 2026-10-31/g3. Events: 428, 397.
  - Why: Her profile avoids long drives, so the yes rests partly on a distance claim the log cannot confirm. Expected: Base the answer on shown facts or ask about distance. Fix: Omit the distance claim or have the matchmaker state travel time.
- **low** · quality issue · AI audit: Isabel's final message says 'You and Ron both love dog walks', and the headline calls the three 'Ten Trails regulars'. Agents: e082, e052. Groups: 2026-10-31/g5. Events: 482.
  - Why: Ron only 'really likes' dog walks, and nothing in the log shows any of them frequents Ten Trails, so both are small overstatements beyond the profiles. Expected: Describe the shared interest accurately and avoid unsupported characterizations. Fix: Say Ron 'is also into dog walks' and drop 'regulars' from the headline.
- **low** · subjective concern · AI audit: Pitch to Josh says the walk is a way to 'wind down your Saturday after shifts'; pitch to Isabel says 'bring your pup if you like'. Agents: e105, e082. Groups: 2026-10-31/g5. Events: 416, 421.
  - Why: The profiles show Josh is a shift worker and Isabel likes dog walks, but not that Josh works Saturday or that Isabel owns a dog; these are harmless but unsupported assumptions. Expected: Pitches should stick to what the profile states. Fix: Drop 'after shifts' and 'bring your pup' or phrase them conditionally.
- **low** · subjective concern · AI audit: Lauren's final message says Donna 'also works remotely, so the pace of the day should suit you both well.' Agents: e049. Groups: 2026-10-31/g6. Events: 484.
  - Why: Both being remote workers is a profile fact, but the conclusion about 'the pace of the day' is an inference the log does not support. Expected: Final messages should state profile facts without adding unsupported inferences. Fix: Drop the 'so the pace of the day should suit you both well' clause.

### Findings dropped: no valid evidence cited (0)

None.

Audit failures: day 2026-10-28: spending ceiling reached; the simulation made no further calls; day 2026-10-31: spending ceiling reached; the simulation made no further calls

## Who got a chance (all days)

| Kind | People | In a room | Asked | Placed | Placements |
|---|---|---|---|---|---|
| all | 30 | 30 | 27 | 27 | 42 |
| archetype: commuter | 10 | 10 | 10 | 10 | 17 |
| archetype: parent at home | 4 | 4 | 4 | 4 | 6 |
| archetype: remote worker | 3 | 3 | 3 | 3 | 5 |
| archetype: retiree | 7 | 7 | 5 | 5 | 8 |
| archetype: shift worker | 5 | 5 | 4 | 4 | 5 |
| archetype: student | 1 | 1 | 1 | 1 | 1 |
| budget: any | 14 | 14 | 12 | 12 | 17 |
| budget: free | 3 | 3 | 3 | 3 | 5 |
| budget: low | 13 | 13 | 12 | 12 | 20 |
| kids at home | 5 | 5 | 5 | 5 | 7 |

In a break room on some day but never asked: 3 people.
