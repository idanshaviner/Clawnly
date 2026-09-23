# Clawnly

**Your agent meets your neighbors' agents first. You only say yes or no.**

Clawnly finds people real friends. Everyone brings the AI that already knows
them (ChatGPT, Claude, Muse, Instinct), and it writes an honest portrait of the
*real* person, not their social-media self. That portrait becomes their
**Claw**: an agent that represents them in private conversations with other
people's agents. A **hub** decides who should talk, reads every conversation,
and invites two people to meet only when the fit is deep and it can prove it
with quotes from the conversation. Humans step in once: yes or no.

Everything behind the scenes is logged and readable in `/admin`: every hub
thought and decision, every agent message, every check the code runs on the
hub, every Claude call verbatim (exact prompt, raw reply, tokens, time, errors),
and every human step (signup, join, yes/no, reveal, admin actions).

---

## Two ways to see it

| | What | Where |
|---|---|---|
| **Clawnly Lounge** | A shareable prototype of the whole idea. Runs on each viewer's own Claude account; no server, no API key. | [claude.ai/artifact/LUqHTUzFhN6JiKNCEmN3Ro](https://claude.ai/artifact/LUqHTUzFhN6JiKNCEmN3Ro) (source: `lounge/`) |
| **The pilot app** | The real product for a neighborhood cohort: invite link, login, consent, bring your agent, hub rounds, yes/no invitations, admin dashboard. | this repo, `src/` |

---

## What a resident experiences (pilot app)

1. **Invite link** `/join/<neighborhood>` -> sign in with Google or an emailed link.
2. **Consent** `/consent` -> plain-language: what they paste, who reads it.
3. **Bring your agent** `/onboarding` -> copy one prompt into the AI that knows
   them, paste its answer, see the card their agent will carry (with a
   "real-you" score and what the agent will say "I don't know" about), join.
4. **Wait.** When enough neighbors have joined, the hub runs a round on its own.
5. **Invitation** `/my-match` -> "Your agent found someone" with a pitch that
   doesn't reveal who. Yes or no. If both say yes: first names and the proposed
   meetup appear. If either says no, both go back into the pool.

The admin (`/admin/login` -> `/admin`) sees each neighborhood's progress, every
resident's status, each round's counts and API usage, and a **Behind the scenes**
view of any round: every conversation word for word and the full activity log.
The admin can also run a round right away.

---

## How it works underneath

```
 dossier.py            agent_talk.py                 orchestrator.py (the hub)            batch.py / my_match.py
 ──────────            ─────────────                 ─────────────────────────            ──────────────────────
 pasted portrait  ──►  a Claw per person:       ◄──  1. PAIR: pick who should talk   ──►  one invitation per person
 -> a card             knows ONLY its person's       2. TALK: 6-message private chat      per round, name-blinded
 (unknowns kept,       dossier, speaks ABOUT         3. JUDGE: depth 1-10, reasoning,     pitch -> mutual yes/no
  real-vs-public       them, says "I don't know"        evidence quotes, invitation       -> reveal on both yes
  score)               instead of inventing          4. GATE (code): recommend AND
                                                        depth >= 8 AND >= 2 quotes that
                                                        really appear in the transcript

   every step above -> db.events (the activity log); every Claude call -> db.ai_calls (verbatim)
```

**Rules enforced in code, never trusted to the model:**
- Pairs: no unknown people, no self-pairs, no repeats, at most 2 conversations per person per round.
- Evidence: any quote not found word for word in the transcript is discarded and logged.
- Invitations: only when the hub recommends it, depth is >= 8/10, and >= 2 quotes check out.
- One live invitation per person; the strongest wins, the rest are held back and logged.
- Before both say yes, the pitch each person reads never names the other.

**Models** (`src/config.py`): the hub's verdict runs on Claude Opus 5.5
(`claude-opus-5-5`, effort `medium`); agent turns, cards and pairing run on
Claude Sonnet 4.6.

---

## Project layout

```
src/
  app.py            FastAPI app: pages + JSON routes for the whole pilot
  auth.py           Google OAuth + email magic links, one session model
  config.py         model tiers, effort, batch threshold, API client
  db.py             SQLite storage (see its docstring for every table)
  dossier.py        the "bring your agent" prompt + building the card
  bring_agent.py    signup: preview a card, then join with exactly that card
  agent_talk.py     the Claw: one person's agent in a private conversation
  orchestrator.py   the hub: pair -> talk -> judge -> gate, all logged
  batch.py          runs a hub round for a neighborhood -> yes/no invitations
  my_match.py       the mutual yes/no gate and the reveal
  admin.py          dashboard aggregation + a round's behind-the-scenes record
  ai_log.py         logs every Claude call verbatim (prompt, reply, tokens, time, errors)
  llm_io.py         reading JSON out of model replies
  sample_people.py  8 fictional people for trying a round from the command line
  web/              join, consent, onboarding (bring your agent), my-match,
                    admin, admin-login, privacy -- plain HTML/JS, no build step
tests/              one test file per module; an offline FakeClient, zero real API calls
lounge/             the Clawnly Lounge prototype (a single HTML file published as an Artifact)
docs/               THIS_WEEK.md (the current plan), ROADMAP.md, and historical docs
```

---

## Setup

Python 3.11+.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Secrets go in a gitignored `.env` at the project root, one `NAME=value` per line
(or as real environment variables, which win):

| Name | What for |
|---|---|
| `ANTHROPIC_API_KEY` | every AI call. Create it **inside a workspace** in the Anthropic Console, or calls are refused |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | "Continue with Google" |
| `RESEND_API_KEY` | emailed sign-in links (without it, links print to the server console: fine locally) |
| `CLAWNLY_ADMIN_EMAILS` | comma-separated emails that can open `/admin` |

## Run

```bash
.venv/bin/python src/app.py        # or double-click Clawnly.command on a Mac
```

Then open `http://127.0.0.1:8000/join/ten-trails` to go through it as a resident.

Try one hub round on the 8 fictional sample people and watch every event print
(real API calls, needs the key):

```bash
.venv/bin/python src/orchestrator.py
```

## Test

```bash
.venv/bin/python -m pytest -q
```

Everything runs offline against `tests/conftest.py`'s `FakeClient`.

## Deploy

`render.yaml` defines the `clawnly-pilot` service (paid plan, because the
SQLite database needs Render's persistent disk). Fill in the secrets above in
Render's dashboard.

---

## History

On 2026-09-23 the product moved from "a matcher reads everyone's profile and
forms groups" to agent-to-agent. The old code (the group matcher, negotiation,
meetup popups, the onboarding chat, the demo console and its tools) was
removed. It is preserved on the **`pre-agent-pivot`** branch. See
`docs/WALKTHROUGH.md` for why, and `docs/THIS_WEEK.md` for what's next.

Style rules for this codebase (no ternaries, index loops, one job per flat
module) are in `CLAUDE.md`.
