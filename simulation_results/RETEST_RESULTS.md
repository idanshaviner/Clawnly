# Retest of the team's five fixes (2026-10-30)

The review of the first 200 live groups found that agents said yes too easily, with 806 of 831 answers yes (97%), and that a few people got most of the plans. Commit `7c99190` made five fixes. This retest ran them live against Claude.

- **Run:** `runs/run_20261030_212909_retest/`, made with `orchestration_sim.py run retest --ceiling 2.50 --total-cap 18.41` on commit `7c99190`.
- **Town:** the same 200 neighbors as before, made busier and pickier, with about 40% less free time and twice the share of mild likes. Three days in a row (Fri 30 Oct to Sun 1 Nov), so plan counts carry from day to day.
- **Spend:** $3.52 of the $5 approved. That's $1.23 for the run, $0.10 for the replays and $2.20 for the Fable audit. The ledger total is now $16.94.

## Results

| | Before (first 200 groups) | Retest |
|---|---|---|
| Groups | 200 locked | 29 of 30 locked |
| Agent answers | 831: 806 yes (97%), 20 no, 5 counter | 123: 114 yes (93%), 9 no, 0 counter |
| Hard-rule problems | 0 | 0 |
| Mild-interest invitations | 6 (4 yes, including Donna and Valeria) | 0 |
| Yes despite a conflict shown | 2 of 7 | none shown |
| Seats that went to a side interest | 22% | 25% (28 of 113) |
| Most plans for one person | Wei T., 22 across 19 independent runs | 3 in 3 days (one person) |

Before and after are different towns, so read the comparison as behavior, not as a score.

## Each fix

1. **Code refuses a yes that conflicts with the profile: not tested live.** No invitation in the retest ran into a conflict. The matchmaker now sees what people avoid and picked times around it. The fix is covered by tests.
2. **Members need a strong interest: worked.** No one with only a mild interest was invited, either as a member or as an alternate.
3. **A yes needs a strong reason: worked.** Every yes came with a reason. Replays of the original calls, 10 times each:

   | | Old prompt | New prompt |
   |---|---|---|
   | Donna B. (Seahawks, only "up for it") | yes 10 of 10 | no 10 of 10 |
   | Valeria G. (book club, only "up for it") | yes 10 of 10 | no 10 of 10 |

4. **Fewer plans first: worked within each activity slot, with one gap.**
   - 91 different people got the 113 seats, and 21 of them got two or more.
   - Every time someone got a second or third plan, nobody in that same activity slot who had a strong interest and no plan was left out.
   - **The gap:** in one case the matchmaker asked an alternate who already had a plan instead of Donna, who had none, and Donna ended the 3 days with no plan. Code puts people with fewer plans first in each room, but nothing makes the matchmaker follow that order when it picks alternates.
5. **Retest town: run.**

## What the retest found

- **All 9 no's were side-interest invitations.** People who like the main activity said yes 85 times out of 85. People there only for a side interest said yes 29 times and no 9 times. The agents now push back on side-interest invitations, but not consistently: for the Green River Gorge hike, side-interest people split 5 yes and 5 no.
- **Q1 is now the main open question:** should liking the main activity be required? Fable's one weak verdict was a hike the matchmaker built from three fishing fans. Four of the five people asked declined for exactly that reason, while keen hikers in the same room went unused.
- **Fable's verdicts:**
  - **Days:** Fri good, Sun acceptable. Saturday's review failed because the reply wasn't JSON.
  - **Groups:** one good, one weak (the dropped hike).
  - **Coverage:** only 2 of the 30 groups were reviewed. The day reviews read all 200 profiles, and they used up the audit's $2.50 ceiling.
- **Smaller points from Fable:**
  - On Sunday the matchmaker used one of its 10 group slots on that weak hike and skipped a ready-made cribbage group of people with no plans. Fable also counted Friday's 10 of 18 possible groups against it, but the run's limit was 10 groups a day.
  - Proposals told people who avoid long drives that a place was "not far", which nothing in the data supports.
  - One group was pitched as a run to some members and a walk to others.

## Questions for the team

- **Q1:** should liking the main activity be required for a seat?
- Should code also make the matchmaker pick alternates with fewer plans first?
- Is it worth $1–1.50 more for Fable to review more of the 29 groups? Without the day reviews, each group costs about $0.10–0.30.
