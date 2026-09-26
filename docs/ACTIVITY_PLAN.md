# Plan: from friendship matching to neighborhood activity groups

Status: **proposal for discussion.** Step 1 (the emulated people, the catalog and
the code-only break room) is built; nothing else changes until we agree.

## The product, in one line

People tell their bot what they like, what they don't, and when they're free. A
matchmaker (the orchestrator) looks at what there is to do in the neighborhood,
negotiates with each bot one-to-one, and brings each person a finished plan:
**"Tomorrow 9am: kayaking at Bladensburg Waterfront with 4 neighbors. In?"**
Small groups doing an activity, not friendship matches. **Every group is 2-5
people**: small enough that everyone actually meets everyone. The wow is meeting
people whose agents already know the humans, so the plan can say why these few.

## What changes

| | Today (friendship pilot) | New (activity groups) |
|---|---|---|
| Goal | Two people who could become close friends | A small group (2-5) doing an activity together, tomorrow |
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
                                                   at most one group; every group 2-5 people
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

- `src/catalog.py` -- 30 things to do in one neighborhood, College Park: beers and the
  game at a sports bar, a brewery flight, trivia, karaoke, board games, coffee walks,
  pickleball, kayaking, a garden workday, a food bank shift, and more. Each has tags,
  what people avoid about it, days, day parts, cost, indoor/outdoor. Groups are 2-5.
  Times and prices are invented for simulation.
- `src/population.py` -- 100 emulated College Park neighbors from a seed (same seed,
  same people): weighted likes, dislikes, avoid-list, archetype (student, office, shift
  worker, parent, remote worker), 7-day calendar, budget, and a plain-words brief
  ("what they told their bot").
- `src/demand.py` -- the break room and the proposed groups, no AI calls.
  `.venv/bin/python src/demand.py 2026-09-27` prints the day's groups.

First results (seed 7): **Sunday**: 32 slots could run, 15 groups, **60 of 100** people
have a plan. **Tuesday**: 36 of 100.

## Next steps (after we agree)

1. **Negotiation** (`negotiate.py`): hub <-> agent messages for each proposed group,
   using the person's brief and calendar. Agents on the cheap tier (Haiku), since
   there are ~100 per day; the hub's re-planning on Sonnet. Offline tests with the
   FakeClient, like everything else.
2. **Lock + the final message** (`plans.py`): locked groups and the one message each
   person gets. Emulated final yes/no.
3. **Simulation run + monitor**: run a week for the 100 people; report % of people
   with a plan per day, fill rate per activity, negotiation rounds, counters,
   drop-outs, cost. The same monitor idea as the Lounge.
4. **Where it runs**: the server app (needs the API key in Render) for scale; the
   Lounge can show one day's run.

## Decisions for us

1. ~~Group size~~ -- decided: 2-5 for every activity (two people having a beer over the game counts).
2. **Negotiation depth**: one proposal + one counter round, or more?
3. **Final human step**: emulate it for now, and later a real "In?" message by email/SMS?
4. **One activity per person per day**, or allow morning + evening?
5. **Catalog source**: keep the illustrative catalog for simulation; later real
   listings (events APIs, parks, venues)?
6. **The friendship pipeline** (dossier -> Claw chats -> depth gate): retire it,
   or keep it as a later "these two keep ending up in the same groups" layer?
