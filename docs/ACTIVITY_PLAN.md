# Plan: from friendship matching to neighborhood activity groups (Black Diamond, WA)

Status: **the simulation is built and runs at `/run` on the Clawnly app** (and as the
Run Clawnly Artifact). The resident pilot (signup, nightly rounds) still runs the
friendship pipeline until we decide to switch it (decision 6 below).

## The product, in one line

People tell their bot what they like, what they don't, and when they're free. A
matchmaker (the orchestrator) looks at what there is to do in the neighborhood,
negotiates with each bot one-to-one, and brings each person a finished plan:
**"Tomorrow 9am: kayaking at Bladensburg Waterfront with 4 neighbors. In?"**
Small groups doing an activity, not friendship matches. **No size rule beyond "at least
two"**: the matchmaker sizes each group to the activity and the people (two people having a
beer over the game is a group). The wow is meeting
people whose agents already know the humans, so the plan can say why these few.

## What changes

| | Today (friendship pilot) | New (activity groups) |
|---|---|---|
| Goal | Two people who could become close friends | A small group doing an activity together, tomorrow |
| Agents talking to each other | Yes, 6-message private chats | **Never.** Every conversation is hub <-> one agent |
| What the hub reads | Dossiers, then transcripts | Each person's likes, dislikes, avoid-list, budget, travel, calendar |
| Common ground | The hub judges chemistry | The break room: code finds who is free, keen and able for each activity slot |
| Negotiation | None | The hub proposes a slot to each agent; the agent accepts, declines or counters, from its person's brief |
| Output to humans | "Meet this person?" | "Here's your plan for tomorrow, with these people" |
| Humans in the loop | Yes/no | Emulated for now; a real person only sees the final plan |

## How the orchestrator works (hub and spoke)

```
            people tell their bots:  likes / dislikes / avoid / budget / travel / calendar
                                              |
 neighborhood catalog  ──►  1. BREAK ROOM (code)   who could do which activity, when
 (things to do)                 every activity x day part -> free, keen, able candidates
                                              |
                            2. PROPOSE (code)      strongest slots first; each person in
                                                   at most one group; at least 2 people
                                              |
                            3. NEGOTIATE (hub <-> each agent, one at a time, never agent<->agent)
                                 hub: "Kayaking, Sun 9-11am, Bladensburg, 4 others, $20. In?"
                                 agent (from its person's brief + calendar): yes / no / counter
                                   ("yes if it starts after 10", "prefers paddleboarding")
                                 hub adjusts within the activity's window and re-asks, max 2 rounds
                                              |
                            4. LOCK (code)         a group locks only when >= 2 said yes;
                                                   people who said no go back to the break room
                                              |
                            5. THE MAGIC           each person gets one message: what, when,
                                                   where, and why these 1-4 others
```

Every step is logged like today: the break room's candidate lists, every proposal,
every agent reply and counter, every lock and every drop.

## What's built (step 1)

- `src/catalog.py` -- **37 things to do in and around Black Diamond, WA**, grounded in real
  places and recurring events: Lake Sawyer Regional Park (paddling, fishing, swimming,
  birding) and its summer dock concerts, the Black Diamond Historical Museum (free; Thu,
  Sat, Sun), Black Diamond Bakery, the Franklin ghost town trail, the Green River Gorge,
  Flaming Geyser State Park (tubing, RC airfield), Black Diamond Open Space singletrack,
  the BMX track, The Vault Taphouse (Seahawks, live music), Lumber House, Big Block
  Brewery, Black Diamond Grill (Kraken nights), Lake Wilderness Golf Course, the Maple
  Valley Farmers Market (Sat 9-2), a Mount Rainier day hike. Each has tags, what people
  avoid about it, days, day parts, **months it runs** (tubing and dock concerts are
  summer-only), cost. Exact times and prices are estimates.
- `src/population.py` -- **200 emulated adults** following the city's census profile (ACS
  2024 5-year: median age 38, 65+ about 10% of residents, 39% of households with kids,
  median household income about $141k, names in the city's proportions -- ethnicity is
  never stored or used). Each has weighted likes (leaning by stage of life: retirees
  toward history, golf, birding; students toward BMX, biking), dislikes, an avoid-list,
  an archetype (student, commuter, shift worker, parent at home, remote worker, retiree),
  kids at home, a Black Diamond area, a 7-day calendar, a budget, and a plain-words brief.
- `src/demand.py` -- the break room and the proposed groups, no AI calls.
  `.venv/bin/python src/demand.py 2026-09-27` prints the day's groups.

First results (seed 7): **Sunday 27 Sep**: 39 slots could run, 27 groups, **124 of 200**
have a plan (two Seahawks watch groups at The Vault, ghost town hikes, cribbage at the
bakery). **Tuesday**: 73 of 200.

## Built next: the matchmaker, at a real URL

- `src/matchmaker.py` -- one day, hub and spoke: break rooms (code) -> plan (Opus 5.5) ->
  round 1, each agent one to one (Sonnet 5) -> resolve counters and declines (Opus) ->
  round 2 -> lock at >= 2 yes (code) -> the message each person gets (Sonnet). Code
  rejects anyone outside the break room, double bookings, and round-2 asks outside a
  group's members and alternates. No Haiku anywhere.
- `src/run_clawnly.py` + `/run` -- the Run Clawnly page served by the app. Anyone with the
  link watches live and replays; only an admin starts a run (the server's key pays), one
  at a time; saved to `db.matchmaker_runs` after every step; every Claude call verbatim
  in the run and in `db.ai_calls`.

Still open: a week-long simulation report (percent with a plan per day, fill rate per
activity, counters, drop-outs, cost) and switching the resident pilot over.

## Decisions for us

1. ~~Group size~~ -- decided: no upper limit in code; at least 2; the matchmaker sizes it.
2. **Negotiation depth**: one proposal + one counter round, or more?
3. **Final human step**: emulate it for now, and later a real "In?" message by email/SMS?
4. **One activity per person per day**, or allow morning + evening?
5. **Catalog source**: keep the illustrative catalog for simulation; later real
   listings (events APIs, parks, venues)?
6. **The friendship pipeline** (dossier -> Claw chats -> depth gate): retire it,
   or keep it as a later "these two keep ending up in the same groups" layer?
