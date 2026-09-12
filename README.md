# Clawnly — AI Matchmaking (PoC + real-user pilot)

Multi-agent matchmaking that fights loneliness by finding people "their people."
Each user has a **Claw** (an AI agent that speaks for them); a **Master Claw**
interviews every Claw and forms small, genuinely-compatible groups for a
real-world meetup, with visible, grounded reasoning. See
[docs/PRD.md](docs/PRD.md) for the product vision and
[docs/SPEC.md](docs/SPEC.md) for the original technical spec.

**Current status:** the matching PoC (interview → match → negotiate → meetup)
is done and tested on simulated/AI-generated people. On top of it, a real-user
neighborhood pilot is built: invite-link registration, an onboarding chat that
learns about a real resident, threshold-triggered batch matching, a
mutual-accept reveal gate (nobody sees who they're matched with until both
sides say yes), and an admin dashboard. **Read
[docs/ROADMAP.md](docs/ROADMAP.md) first** — it tracks exactly what's done,
what's not, and what's needed before a real launch. The frozen design for the
pilot lives in [docs/PILOT_PLAN.md](docs/PILOT_PLAN.md).

`src/app.py` is the one FastAPI server behind everything below — every route,
demo console and real pilot alike, is defined there and calls into the modules
described further down. It is not legacy code; it's actively maintained and
is the current entry point for the whole application.

## Two experiences in one app

The server hosts two mostly-separate things side by side, sharing the same
matching engine underneath:

1. **The original demo console** (`/`) — for the *simulated* cast (the original
   12 seed people, or a generated Black Diamond cohort of up to 100). Edit
   people, run the matcher (free Demo mode or real Live mode), chat with
   personas, ask the Master Claw why it did something. Predates the pilot and
   has nothing to do with real residents.
2. **The real-user pilot** (`/join/<slug>` onward) — real accounts, a real
   onboarding conversation, real matching, real (small) meetups.

Don't confuse the two "admin"-ish surfaces this produces — see below.

## Black Diamond 100 (demo console)

A playable, reviewable simulation of ~100 platonic neighbors in Black Diamond,
Washington. This lives entirely on `/` (the demo console) — it does **not**
touch `/join`, onboarding, or real residents.

1. Start the app: `.venv/bin/python src/app.py` then open http://127.0.0.1:8000
2. Leave **Demo (free, offline)** selected so nothing hits Anthropic.
3. In **Black Diamond · 100-person simulation**, the theme defaults to
   neighbors in Black Diamond (ages 24–40, friendship / activity partners, not
   dating) and count defaults to 100. Tweak either if you want.
4. Click **1. Generate cast** — Demo builds 100 schema-valid scripted people
   locally (no API). Switch to Live first only if you want Claude to invent
   them (slow + costly at 100).
5. Click **2. Run the matchmaker** (or the header Run button). Demo completes
   end-to-end with `DemoClient`: interviews, multiple groups from
   `find_all_matches`, negotiation, meetup cards, plus unmatched leftovers.
6. Browse groups (members, reason, scores, why_not) and the unmatched list.
7. Thumbs-up / thumbs-down a group (optional note). That feedback is persisted
   and injected into the Master Claw on the **next** run.
8. Run again to see the matcher read those lessons. **Reset to original 12**
   restores the seed cast without wiping feedback.

Live at N=100 is many interview + match calls on real Claude — expect minutes
and real spend; keep Demo selected unless you mean to pay.

## The resident (real user) walkthrough

Start the server (`.venv/bin/python src/app.py`), then walk through these
URLs in order — there is currently no in-app navigation linking them together
(see the caveat after step 2), so you need to know the next URL yourself:

**1. `/join/<slug>`** (e.g. `/join/ten-trails`) — the invite link a resident
gets. A static page (`web/join.html`); no login required to view it. Check
"I understand," then either:
- **Continue with Google** → `/auth/google/login` → `auth.py`'s OAuth flow
  (needs `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` in `.env`), or
- Enter an email → `POST /api/auth/magic-link/request` (needs
  `RESEND_API_KEY`; without it, the sign-in link is printed to the **server
  console** instead of emailed — this is how you test the whole flow locally
  without a Resend account).

Either path ends in `auth.py` creating a `residents` row for that neighborhood
(`db.get_or_create_resident`), starting a session (cookie), and redirecting
to `/consent`.

**2. `/consent`** — the consent text; "I agree" → `POST /api/consent` →
`db.record_consent` stamps `consent_agreed_at` (first agreement wins, a
double-click is a no-op).

> **Known gap:** after agreeing, the page just says "you're all set" — it does
> not link or redirect to `/onboarding`. The same is true between finishing
> onboarding and `/my-match`. Today a resident (or you, testing) has to
> already know the next URL. Worth fixing before a real launch.

**3. `/onboarding`** — the actual chat. Each message → `POST
/api/onboarding/message` → `onboarding.take_turn`, which does two AI calls:
1. The resident's own Claw (`claw.py`, `simulated=False`) replies — grounded
   *only* in what's actually been said so far in this conversation, never
   invented (see `REAL_ONBOARDING_STYLE` in `claw.py`).
2. A second, cheap call re-reads the whole transcript and extracts profile
   fields (hobbies, availability, personality, bio, etc.), plus checks 5
   gating "slots": personality/energy, interests, availability, group size,
   and what they're seeking.

Once all 5 slots are genuinely evidenced (or a hard 20-turn safety cap is
hit), the profile is marked complete, which fires `batch.check_and_trigger_
batch` in the background: it checks whether the neighborhood has reached its
batch threshold (`config.MATCH_BATCH_THRESHOLD = 100` by default, snapshotted
per-neighborhood at creation) among *eligible* residents (profile-complete and
not already tied up in a live match), and if so, runs the real engine
(interview → match → negotiate → venue) across everyone at once.

**4. `/my-match`** — polls `GET /api/my-match` for status:
- `not_yet_batched` — still waiting for the cohort to fill up.
- `pending` — a match was formed; shows **only the reason + group size, no
  names** — this is the mutual-accept reveal gate.
- `waiting` — you accepted; waiting on the rest of the group.
- `sealed` — everyone accepted → full first-name reveal of the other members
  + the real meetup card (venue, time, the grounded reason for that plan).
- `dissolved` — someone declined → the match is void and you're released back
  into the pool. Nothing automatically re-triggers a new batch for you yet —
  today that needs an admin to hit "trigger batch now" (see below).

**5. `/privacy`** — a static, plain-language privacy page, linked from the
join page's consent text.

## Admin — there are two different panels, don't mix them up

**`/` (the demo console)** — for the *simulated* cast only (seed 12 or a
generated Black Diamond cohort up to 100), as described above. No login/role
check at all; it's a local dev tool. Nothing here touches real residents.

**`/admin` (the real pilot dashboard)** — for monitoring actual
neighborhoods/residents. Every route under it is gated by `_require_admin` in
`app.py`: your session's `role` must be `"admin"`, decided once, server-side,
the moment you log in — `auth.is_admin(email)` checks your email against the
`CLAWNLY_ADMIN_EMAILS` env var (comma-separated list). It is never
client-supplied or editable after the fact. Add your email to that env var,
then sign in at **`/admin/login`** with that address — a plain login page
that never attaches a neighborhood, so you land straight on the dashboard.
(Logging in through `/join/<slug>` with an admin email is a *different*,
intentional path: it still creates a resident row for that neighborhood, so
an admin can experience the real resident flow too, through their own
email — but it lands you on `/consent`, not the dashboard.) Shows:
- Every neighborhood's progress (`complete-profiles / threshold`)
- Per-neighborhood resident list with status (`onboarding` /
  `complete_unmatched` / `match_pending` / `match_waiting` / `sealed` /
  `dissolved`) — computed live from existing data, nothing separately tracked
- Recent runs with group/unmatched counts, usage (API call counts), and any
  interview errors
- A **"trigger batch now"** button (`batch.force_trigger_batch`) that bypasses
  the threshold entirely — the only current way to re-match residents
  released by a decline, and handy for testing with a small cohort

## How it works underneath (architecture)

**Core matching engine** — shared by both the demo console and the real
pilot; do not modify its core logic without an explicit request (new
capability gets added around it, not into it):

```
claw.py          one AI agent that speaks for one person (simulated persona
                 OR a real resident, via the simulated=True/False flag)
   ↓
master_claw.py   interviews every Claw, forms a group, VALIDATES hard
                 constraints in code (group size, availability overlap —
                 never trusted to the model alone), retries or refuses
                 rather than shipping a bad/weak match
   ↓
negotiation.py   the formed group tries to agree on one shared activity
                 (bounded rounds; ships nothing if they never agree)
   ↓
popup.py         the agreed plan → a concrete, grounded venue/time card
```

**Real-user pilot layer** — built around that engine, wraps it for real
people:

| Module | Job |
|---|---|
| `auth.py` | Google OAuth + email magic-link login, sessions (cookie → DB row, never a JWT) |
| `db.py` | all persistence — one SQLite file; see its module docstring for the full table list |
| `onboarding.py` | the real onboarding chat + per-turn profile extraction |
| `batch.py` | decides *when* and *how* to run the core engine on real residents (threshold trigger + manual admin override), maps resident rows into the exact profile shape the engine expects |
| `my_match.py` | the mutual-accept reveal gate — pure DB/routing logic, no AI calls of its own |
| `admin.py` | read-only aggregation for the admin dashboard, reusing data the other modules already persist |
| `usage.py` | wraps any client to tally API call counts for the usage view |
| `dryrun.py` | a dev/ops tool — drives AI-generated personas through the *real* pipeline end to end, for pre-launch validation (see its own docstring: `chat` vs `bulk` mode, real cost) |
| `pilot_demo.py` | a dev/ops tool — the free, offline, zero-cost counterpart to `dryrun.py`: scripted replies, same real production code path, good for a quick sanity check of the plumbing before spending anything |
| `pilot_visual_demo.py` | `pilot_demo.py`'s browser-driven sibling — same scripted-AI approach, but runs the real `app.py` server and drives it with an actual browser, so it captures what a resident really sees (screen recording + screenshots), not a terminal transcript |

`app.py` is the glue: every URL described above is a route in that one file,
and each route is a thin wrapper that calls into the modules above — it holds
almost no logic of its own.

## Project layout

```
Clawnly/
├── README.md              ← you are here
├── requirements.txt
├── pyproject.toml         ← project + test config
├── render.yaml            ← Render deploy config (two services: public demo, real pilot)
├── docs/
│   ├── PRD.md             ← product vision, roadmap, metrics
│   ├── SPEC.md            ← original technical spec (still mostly accurate)
│   ├── ROADMAP.md         ← START HERE — live build status, what's next
│   └── PILOT_PLAN.md      ← frozen design for the real-user pilot
├── src/
│   │  -- core matching engine (PoC, do not modify without an explicit request) --
│   ├── config.py          ← model ids/tiers, temperatures, the API client
│   ├── users.py           ← the 12 demo users + hobby/availability vocab
│   ├── llm_io.py          ← parse JSON safely out of model replies
│   ├── claw.py            ← Claw: speaks for one user (simulated OR real resident)
│   ├── master_claw.py     ← interviews + forms + validates a group
│   ├── negotiation.py     ← group reaches (or doesn't reach) a shared plan
│   ├── popup.py           ← the agreed plan → a concrete meetup card
│   ├── explain.py         ← Master Claw explains its own decisions
│   ├── main.py            ← runs the full pipeline (entry point)
│   ├── persona_gen.py     ← AI-generates a fresh cast of simulated users
│   ├── eval.py            ← quality harness across many simulated pools
│   ├── demo.py            ← free offline run, scripted AI (no API calls)
│   │  -- real-user neighborhood pilot --
│   ├── db.py               ← SQLite persistence (see its docstring for every table)
│   ├── auth.py             ← Google OAuth + email magic-link, sessions
│   ├── onboarding.py       ← the real onboarding chat + profile extraction
│   ├── batch.py            ← threshold/manual batch trigger, real-pipeline wiring
│   ├── my_match.py         ← the mutual-accept reveal gate
│   ├── admin.py            ← admin dashboard data (progress, residents, usage)
│   ├── usage.py            ← call-count usage tracking wrapper
│   ├── dryrun.py           ← pre-launch tool: AI personas through the real pipeline
│   ├── pilot_demo.py       ← free/offline counterpart to dryrun.py, zero cost
│   ├── pilot_visual_demo.py ← pilot_demo.py, but through a real browser (screen recording)
│   ├── app.py              ← FastAPI backend tying all routes together
│   └── web/                ← plain HTML/JS pages, no build step
│       ├── index.html      ← demo console (run the PoC pipeline, edit the cast)
│       ├── join.html       ← resident invite-link landing + login
│       ├── consent.html    ← resident consent capture
│       ├── onboarding.html ← the resident's onboarding chat
│       ├── my-match.html   ← pending/waiting/sealed match reveal
│       ├── admin.html      ← pilot admin dashboard
│       └── privacy.html    ← alpha-stage privacy page
└── tests/                  ← one test file per module (run: python -m pytest)
```

## Setup

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Real secrets go in a gitignored `.env` file at the project root, one
`NAME=value` per line (never committed, never printed/logged):

```
ANTHROPIC_API_KEY=sk-ant-...       # required for any Live/real-pilot AI call
GOOGLE_CLIENT_ID=...               # optional -- Google login (auth.py)
GOOGLE_CLIENT_SECRET=...           # optional -- pairs with the above
RESEND_API_KEY=...                 # optional -- email magic links (dev mode
                                    #   prints the link to the console instead)
```

Also useful, set as real env vars (not `.env`) when running the pilot:
`CLAWNLY_ADMIN_EMAILS` (comma-separated admin allowlist — see "Admin" above),
`CLAWNLY_DEMO_ONLY` / `CLAWNLY_BYOK` (public-demo-deploy safety switches --
leave both unset for a real pilot deploy), `CLAWNLY_DB_PATH` (override the
SQLite file location).

## Run

```bash
.venv/bin/python src/app.py         # the whole app (or double-click Clawnly.command) — http://127.0.0.1:8000
.venv/bin/python src/demo.py        # FREE: full PoC pipeline offline, scripted AI (no API, no cost)
.venv/bin/python src/pilot_demo.py  # FREE: real PILOT flow offline -- onboarding, batch trigger,
                                     #   matching, and the mutual-accept reveal gate incl. a decline
.venv/bin/python src/pilot_visual_demo.py  # FREE: the same real pilot flow, but through the actual
                                     #   browser UI (screen recording + screenshots) -- see what a
                                     #   resident really sees, not a terminal transcript. Needs
                                     #   `pip install playwright && playwright install chromium`.
.venv/bin/python src/users.py       # FREE: print the 12 simulated users as JSON
.venv/bin/python src/main.py        # COSTS ~cents: interview -> match -> negotiate -> popup, real Claude
.venv/bin/python src/eval.py        # COSTS ~cents: evaluation harness across many pools
.venv/bin/python src/dryrun.py      # COSTS real $: N AI personas through the REAL pilot pipeline
                                     #   (see its module docstring -- chat vs. bulk mode, cost notes)
```

Inside the app: the demo console (`/`) has a free **Demo mode**; Live mode
(chatting/editing/running with real Claude) needs `ANTHROPIC_API_KEY`. The
resident-facing pilot (`/join/<slug>` onward) always uses the server's real
key -- there is no demo mode for real resident data.

## Test

```bash
.venv/bin/python -m pytest -q
```

The full suite (300ish tests) runs offline against a fake Anthropic client
(`tests/conftest.py`) -- zero real API calls, ever. One test file per module.

## Hard style rules (non-negotiable, see `CLAUDE.md`)

No ternaries. No enhanced `for` loops (index-based/`while` only -- the one
exception is a list comprehension building an `asyncio.gather` list). Each
module does one job; this codebase has never used subpackages. Read
`CLAUDE.md` before making changes -- it's the actual working agreement for
this project, not just AI-agent instructions.
