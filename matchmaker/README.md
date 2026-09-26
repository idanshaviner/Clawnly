# Run Clawnly (activity groups, hub and spoke)

A single-file page published as a claude.ai Artifact:
https://claude.ai/artifact/1XBuxUg6WCjSXjXgq9FREX

200 emulated adults of Black Diamond, WA (`src/population.py`, census-shaped) and 37 real
local activities (`src/catalog.py`) are embedded in the page. The owner presses
**Run the matchmaker**; it runs on the owner's Claude account and saves the result into
the page, so invited people can read every step.

The run, all hub and spoke (agents never talk to each other):

1. **Break rooms (code)** -- one per activity and time of day, same rules as
   `src/demand.py`: in season and running then, the person is free, within budget, doesn't
   dislike it, doesn't avoid anything about it, and likes it (how much = keenness). The
   Break rooms tab shows who is in each room and why, and why everyone else isn't.
2. **Plan (matchmaker, `complex` tier)** -- groups sized by the matchmaker (no upper limit
   in code), alternates, a personal proposal to each agent. Code rejects anyone not in that
   break room, double bookings, and a "group" of one.
3. **Round 1 (each agent, `quick` tier)** -- the matchmaker asks each person's agent one to
   one; the agent answers yes / no / counter from its person's brief and calendar only.
4. **Resolve (matchmaker)** -- accepts counters by moving the time, calls alternates. Code
   rejects asking anyone outside the group and its alternates, anyone who already said
   yes elsewhere, and asking one person for two groups.
5. **Round 2** -- only the people the matchmaker needs to re-ask.
6. **Lock (code)** -- a group locks once at least 2 people said yes.
7. **The message (matchmaker, `default` tier)** -- what each person receives: what, when,
   where, the others by first name and why they'll get along.

Every message is shown word for word (Negotiation tab); the Orchestrator tab keeps every
Claude call verbatim (exactly what was sent, exactly what came back, how long it took);
every step is logged; and "Copy the run as JSON" exports it all.

To rebuild after changing the people or the catalog, regenerate the embedded
`mm-data` JSON from `population.generate(200, seed=7, start=...)` and `catalog.ACTIVITIES`.
