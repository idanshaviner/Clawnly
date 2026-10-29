# Audit: run_20261029_030412_pilot

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
| invitations sent | 43 |
| agent replies | 43 |
| answers | {'yes': 43, 'no': 0, 'counter': 0} |
| acceptance rate | 1.0 |
| hard constraint violations | 0 |
| agents accepting a conflict they were shown | 0 |
| ai inconsistent agents | 0 |
| orchestration failures | 0 |
| days not done | 0 |
| simulation cost usd | 0.43068 |
| audit cost usd | 1.21977 |
| ai audit coverage | 8 of 12 groups, 0 of 2 days |

## Rule checks in code (0 findings)

None.

## Independent AI audit (claude-fable-5-1, effort medium)

Sampling: all 0 groups code flagged or that didn't lock, plus 8 of the other 12 drawn with seed 7. Failures: 0.

| Group | Verdict | Summary |
|---|---|---|
| 2026-10-31/g2 | good | Four runners who are all free Saturday morning were offered a free, easy 5K, and every agent said yes with reasons that match their profiles. The matchmaker correctly kept the group as proposed and the final messages name only the four attendees using profile facts. Only minor wording overstatements and one unverifiable claim appear. |
| 2026-10-31/g6 | good | A clean two-person pairing of neighbors from the same village who both rank hiking highly, at a free evening slot both calendars show as open. Both agents said yes for reasons grounded in their profiles, the matchmaker needed no alternates or counters, and the final messages name only the two attendees with accurate facts. The only blemish is the matchmaker's small assumption that Isabel owns a dog. |
| 2026-10-28/g4 | good | Four parents with kids, all free Wednesday morning and all with coffee or baking in their profiles, were offered a low-cost 9:30-11am bakery meetup that respects Chris's early-morning avoidance and Imani's low-drive and low-cost needs. All four agents said yes with profile-grounded reasons, the matchmaker correctly kept the group unchanged, and the final messages name only attendees. Only minor overstatements of shared interests appear in the pitches and confirmations. |
| 2026-10-31/g5 | good | A clean three-person board game night: all three members are free Saturday evening, all list cards as a love or strong like, the event is free (fitting Grace's budget), and the 8:30pm end respects Grace's and Ron's avoidance of late nights. Every agent said yes for reasons grounded in its profile, the matchmaker kept the plan unchanged, and the final messages name only attendees and use only profile facts. |
| 2026-10-31/g3 | good | A clean one-round negotiation: three craft-beer fans free Saturday afternoon were asked, all three said yes consistently with their profiles, and the group locked at the proposed time with accurate final messages naming only attendees. The only blemish is the matchmaker's internal rationale claiming all three enjoy live music when Rosa's profile never mentions it. |
| 2026-10-28/g5 | good | A free Wednesday-morning birding walk pairing three birders (Ron, Noah, Claire) with a photographer (Wei) who avoids crowds and competition. All four agents said yes with reasons that match their profiles and calendars, the matchmaker kept the original time with no declines or counters to handle, and the final messages name only confirmed members using profile facts. Only minor wording overstatements and a headline label the log can't fully support. |
| 2026-10-31/g4 | good | Three neighbors with genuine on-water interests (boating, kayaking) were offered a low-cost Saturday afternoon paddle that fits all three calendars and Lauren's budget, and every agent said yes for reasons grounded in its profile. The matchmaker locked the group without changes and sent final messages that name only the three members and draw on profile facts. The only nit is slightly inflated wording about how strongly some members 'love' shared interests. |
| 2026-10-28/g2 | good | A clean four-person pickleball doubles group where every member lists pickleball as a top interest, is free Wednesday evening, and the event is free, satisfying the two budget-conscious members. All four agents accepted on the first round with reasons matching their profiles, and the matchmaker locked without needing alternates or re-asks. The only blemishes are minor: the final messages inflate Heather's 'up for' running into a shared 'love', and the proximity claims to Kevin and Heather rest on nothing visible in the log. |

### Findings with evidence (16)

- **low** · quality issue · AI audit: Final messages say Kavya and Kevin 'both love live music and trivia' and Kevin and Quinn 'both love pickleball and baseball' [322]. Groups: 2026-10-31/g2. Events: 322.
  - Why: Kevin only 'really likes' live music and is 'up for' trivia; Quinn only 'really likes' baseball, so the intensity is overstated. Expected: Shared interests described at the strength the profiles give. Fix: Change 'both love' to 'both enjoy' or similar.
- **low** · insufficient evidence · AI audit: The invitation to Kevin claims the venue is 'close to home' [232]. Groups: 2026-10-31/g2. Events: 232.
  - Why: Kevin avoids long drives and no profile or event data states where Ten Trails is relative to Lawson Hills, so the claim is unsupported by the log. Expected: Only state proximity if known from the data. Fix: Drop 'close to home' or state the actual location.
- **low** · quality issue · AI audit: Quinn's agent justified its yes with Quinn's 'love of running' [259]. Agents: e043. Groups: 2026-10-31/g2. Events: 259.
  - Why: The profile lists running under 'really likes', not 'loves'; a slight overstatement, though the decision is still correct. Expected: Reasons that mirror the profile's stated strength. Fix: Say 'really likes running'.
- **low** · quality issue · AI audit: The matchmaker told Isabel 'your dog is welcome' [287]. Agents: e082. Groups: 2026-10-31/g6. Events: 287, 288, 297.
  - Why: Her profile lists 'dog walks' as an interest but nowhere says she owns a dog; the log also gives no basis for the trail's dog policy. Expected: Mention only what the profile supports, e.g. that it is a dog-walk-style outing or that dogs are allowed if known. Fix: Change 'your dog is welcome' to 'dogs are welcome'.
- **low** · subjective concern · AI audit: The group was planned and locked at only 2 people while Grace C. (hiking 3, keenness 3, overlaps on baseball and watch sports) sat unasked in the break room [199][313]. Agents: e082, e105. Groups: 2026-10-31/g6. Events: 199, 306, 313, 319.
  - Why: A two-person group is fragile and Grace appears at least as compatible as either member, though the log does not show why she was excluded. Expected: Consider inviting the keenest compatible break-room member to reach three. Fix: Ask Grace C. as a third before locking.
- **low** · quality issue · AI audit: Pitches and confirmations generalised interests beyond the profiles: Chris was told the other three parents are 'into baking' though Imani lists no baking, and Imani's confirmation says Chris loves coffee though he is only 'up for' it. Agents: e127, e041. Groups: 2026-10-28/g4. Events: 45, 99, 183.
  - Why: Final and pitch messages should use only facts from the profiles; small overstatements set slightly wrong expectations. Expected: Describe shared interests only where the profiles support them. Fix: Say 'two other parents into baking' to Chris and 'you and Mark both love coffee, and Chris enjoys it too' to Imani.
- **low** · subjective concern · AI audit: Mark is 'not into dining' and was placed in a bakery coffee-and-pastries meetup; code found no conflict and his agent accepted. Agents: e035. Groups: 2026-10-28/g4. Events: 95, 121.
  - Why: A bakery table is arguably a light form of dining; it is a judgment call whether this touches his dislike. Expected: Nothing required; coffee is his top love and the agent accepted knowingly. Fix: None needed.
- **low** · subjective concern · AI audit: The invite to Ron asserts the night is 'friendly and casual, not competitive' [282], and Ron's agent leaned on that assurance when accepting [294], though the event description itself only says 'board game night at a neighbor's table' [198]. Agents: e052. Groups: 2026-10-31/g5. Events: 282, 294, 198, 328.
  - Why: Ron avoids competitive settings; if the games turn competitive the assurance was the matchmaker's framing rather than a documented feature of the event. Expected: Frame the tone as a suggestion (e.g. 'meant to be casual') rather than a guarantee, or note it in the final message so the group knows Ron prefers low-key play. Fix: Soften 'not competitive' to 'meant to be casual' in the invite and final message to Ron.
- **low** · quality issue · AI audit: The matchmaker's rationale says all three members 'also enjoy live music', but Rosa's profile lists no interest in live music. Agents: e075. Groups: 2026-10-31/g3. Events: 202, 196.
  - Why: The group reasoning rests partly on an invented shared trait, even though the invites and final messages did not repeat the error. Expected: Rationale should cite only interests actually in the profiles (craft beer for all three; live music for Rachel and Heather only). Fix: Reword the reason to 'three craft-beer lovers, two of whom also enjoy live music'.
- **low** · insufficient evidence · AI audit: The matchmaker told Rachel the brewery is 'close by' and Heather it is 'nearby'; both avoid long drives, Rachel is in Downtown and Heather in Lake Sawyer, but the venue's location is not in the log. Agents: e123, e167. Groups: 2026-10-31/g3. Events: 242, 252.
  - Why: If the venue is far from either neighborhood the invite would misstate a fact that matters to both people's avoidances; the log cannot confirm either way. Expected: Proximity claims should be verifiable against the venue location. Fix: Include the venue's neighborhood in the proposal or drop the unverified proximity claim.
- **low** · quality issue · AI audit: Invites and confirmations describe 'really likes' items as favorites/loves (Ron's photography [114][185], Claire's birding [185]) and tell Noah all three others 'enjoy birds' though Wei lists no birding [119]. Agents: e038, e069, e111, e124. Groups: 2026-10-28/g5. Events: 114, 119, 185.
  - Why: Small overstatements of profile facts can set mismatched expectations about companions. Expected: Describe interests at the strength the profile gives them. Fix: Use 'enjoys' or 'is into' for really-likes items and say Wei is there for photography.
- **low** · subjective concern · AI audit: Headline says 'Four Black Diamond neighbors meet at dawn' though only Ron and Claire live in Black Diamond Ridge (Noah: Downtown, Wei: Morgan Creek), and the 8am start is described as dawn. Groups: 2026-10-28/g5. Events: 185, 186.
  - Why: The profiles don't establish all four as Black Diamond residents, and 'dawn' isn't in the plan. Expected: Headline limited to facts in the profiles and plan. Fix: Change to 'Four neighbors meet Wednesday morning for Lake Sawyer birds'.
- **low** · quality issue · AI audit: Confirmations to Noah and Claire name only Ron and Claire / Ron and Noah, leaving Wei unmentioned as a participant. Agents: e069, e111. Groups: 2026-10-28/g5. Events: 175, 185.
  - Why: Members should know who is actually coming; two of four messages omit a confirmed attendee. Expected: Each confirmation lists all other attendees. Fix: Add 'and Wei' to Noah's and Claire's messages.
- **low** · subjective concern · AI audit: Final messages say Andres and Donna 'both love boating' and Donna/Lauren 'love' running and craft beer, when Donna is only 'up for' boating and craft beer and Lauren only 'up for' running. Agents: e081, e067, e049. Groups: 2026-10-31/g4. Events: 326.
  - Why: The shared interests are real but the intensity is overstated, which could set slightly inflated expectations. Expected: Describe shared interests at the level the profiles support. Fix: Reword to 'you both enjoy' or 'you share an interest in' rather than 'love'.
- **low** · quality issue · AI audit: The final messages say Quinn, Kevin, and Heather 'all love running' and that Heather's 'love of running' is shared, but Heather's profile lists running only as 'is up for'. Agents: e167, e043, e078. Groups: 2026-10-28/g2. Events: 179.
  - Why: The confirmation inflates a profile fact, so members receive a slightly inaccurate picture of what they have in common. Expected: Describe shared interests at the intensity the profiles actually state. Fix: Change the running line to say Heather is 'also up for running' rather than loves it.
- **low** · insufficient evidence · AI audit: The matchmaker told Kevin the courts are 'a short trip' and told Heather they are 'close to Lake Sawyer, so no long drive', and Heather's agent repeated 'close by'. Agents: e078, e167. Groups: 2026-10-28/g2. Events: 69, 74, 91.
  - Why: Both people avoid long drives, and nothing in the log establishes distances between Lawson Hills, Lake Sawyer, and Maple Valley, so the reassurance is unsupported. Expected: Either cite a known distance or avoid asserting proximity and let the agent judge. Fix: Drop the proximity claims or replace them with a neutral mention of the location.

### Findings dropped: no valid evidence cited (0)

None.

## Who got a chance (all days)

| Kind | People | In a room | Asked | Placed | Placements |
|---|---|---|---|---|---|
| all | 30 | 30 | 26 | 26 | 43 |
| archetype: commuter | 10 | 10 | 9 | 9 | 17 |
| archetype: parent at home | 4 | 4 | 4 | 4 | 6 |
| archetype: remote worker | 3 | 3 | 3 | 3 | 5 |
| archetype: retiree | 7 | 7 | 5 | 5 | 8 |
| archetype: shift worker | 5 | 5 | 4 | 4 | 6 |
| archetype: student | 1 | 1 | 1 | 1 | 1 |
| budget: any | 14 | 14 | 11 | 11 | 16 |
| budget: free | 3 | 3 | 3 | 3 | 5 |
| budget: low | 13 | 13 | 12 | 12 | 22 |
| kids at home | 5 | 5 | 5 | 5 | 7 |

In a break room on some day but never asked: 4 people.
