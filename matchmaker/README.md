# Run Clawnly (activity groups, hub and spoke)

Two ways to run the same page:

- **On the Clawnly app, at `/run`** (the real URL): the server runs the matchmaker with its
  own key -- `src/matchmaker.py` (Opus 5.5 plans and resolves, Sonnet 5 speaks for each
  agent and writes the messages), started by `src/run_clawnly.py`, saved to
  `db.matchmaker_runs` after every step. Anyone with the link watches live and replays;
  only a Clawnly admin (`CLAWNLY_ADMIN_EMAILS`, signed in at `/admin/login`) can start a
  run, one at a time. Every call is also in `db.ai_calls`.
- **As a claude.ai Artifact**: https://claude.ai/artifact/1XBuxUg6WCjSXjXgq9FREX -- runs on
  the owner's Claude account in the browser and saves into the page.

The page's sources are `src/web/run-clawnly.js`, `run-clawnly.css` and
`run-clawnly-head.html`; `run-clawnly.html` here is the assembled Artifact copy. The
server serves them with a `mm-mode` flag set to `"server"`; without it the page is the
Artifact.

200 emulated adults of Black Diamond, WA (`src/population.py`, census-shaped) and 37 real
local activities (`src/catalog.py`) are embedded in the page. The owner presses
**Run the matchmaker**; it runs on the owner's Claude account and saves the result into
the page, so invited people can read every step.

**What people see first is one screen**, after Muse's lesson that an agent should feel like
messaging and show itself at work: the town (the Clawnly hub in the middle, 200 neighbor
dots around it by area), one sentence for the result, and the plan cards. "Replay how it
happened" plays a saved run back in about 25 seconds (lines from the hub to each agent as
it asks, dots turning green / amber / red as they answer, groups lighting up in their
color) without using any Claude. "Open someone's phone" shows the one message a person
gets. Tapping a plan shows how it came together. Everything below lives behind
**Behind the scenes** (Negotiation, Orchestrator calls, Break rooms, People, Things to do, Log).

The run, all hub and spoke (agents never talk to each other):

1. **Break rooms (code)** -- one per activity and time of day, same rules as
   `src/demand.py`: in season and running then, the person is free, within budget, doesn't
   dislike it, doesn't avoid anything about it, and likes it (how much = keenness). The
   Break rooms tab shows who is in each room and why, and why everyone else isn't.
2. **Plan (matchmaker, `complex` tier)** -- groups sized by the matchmaker (no upper limit
   in code), alternates, a personal proposal to each agent. Code rejects anyone not in that
   break room, double bookings, and a "group" of one.
3. **Round 1 (each agent, `default` tier -- never the fast one)** -- the matchmaker asks each person's agent one to
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

**What each agent checks** (Idan's change): the agent gets its person's full profile (likes by
strength, dislikes, what they avoid, budget, the whole week's calendar) and a list of what code
found against the plan (`plan_checks`: an early start for someone who avoids early mornings, a
late finish, over budget, busy then, only a mild interest). A no is a normal answer.

**Real events keep real times**: activities with a `fixed` time in `src/catalog.py` (Seahawks
kickoffs, Kraken puck drop, the dock concert, live music, trivia, the trail work party) always
meet then. Code overrides whatever time the plan wrote, and refuses the matchmaker's later
attempts to move it.

**A smaller plan**: each break room lists its 8 keenest people as `id:keenness` and the rest by
id; every listed person's profile appears once, under PEOPLE. For Sunday 27 Sep that's about
5,600 tokens instead of 16,300.

To rebuild this file after changing the page, the people or the catalog:
`.venv/bin/python src/run_clawnly.py matchmaker/run-clawnly.html 2026-09-27`
