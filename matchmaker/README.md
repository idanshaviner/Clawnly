# Clawnly Matchmaker (activity groups, hub and spoke)

A single-file page published as a claude.ai Artifact:
https://claude.ai/artifact/1XBuxUg6WCjSXjXgq9FREX

200 emulated adults of Black Diamond, WA (`src/population.py`, census-shaped) and 37 real
local activities (`src/catalog.py`) are embedded in the page. The owner presses
**Run the matchmaker**; it runs on the owner's Claude account and saves the result into
the page, so invited people can read every step.

The run, all hub and spoke (agents never talk to each other):

1. **Break room (code)** -- the same rules as `src/demand.py`: who is free, keen, can afford
   it and doesn't avoid anything about each activity slot that day.
2. **Plan (matchmaker, `complex` tier)** -- groups of 2-5, alternates, a personal proposal to
   each agent. Code rejects anyone not in that slot's break room list, double bookings,
   and groups under 2.
3. **Round 1 (each agent, `quick` tier)** -- the matchmaker asks each person's agent one to
   one; the agent answers yes / no / counter from its person's brief and calendar only.
4. **Resolve (matchmaker)** -- accepts counters by moving the time, calls alternates. Code
   rejects asking anyone outside the group and its alternates, anyone who already said
   yes elsewhere, and asking one person for two groups.
5. **Round 2** -- only the people the matchmaker needs to re-ask.
6. **Lock (code)** -- a group locks only with 2+ yes (max 5).
7. **The message (matchmaker, `default` tier)** -- what each person receives: what, when,
   where, the others by first name and why they'll get along.

Every message is shown word for word (Negotiation tab), every step is logged, Claude calls
are counted per step, and "Copy the run as JSON" exports it.

To rebuild after changing the people or the catalog, regenerate the embedded
`mm-data` JSON from `population.generate(200, seed=7, start=...)` and `catalog.ACTIVITIES`.
