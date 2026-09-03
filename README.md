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
│   ├── app.py              ← FastAPI backend tying all routes together
│   └── web/                ← plain HTML/JS pages, no build step
│       ├── index.html      ← admin console (run the PoC pipeline, edit the cast)
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
`CLAWNLY_ADMIN_EMAILS` (comma-separated admin allowlist), `CLAWNLY_DEMO_ONLY` /
`CLAWNLY_BYOK` (public-demo-deploy safety switches -- leave both unset for a
real pilot deploy), `CLAWNLY_DB_PATH` (override the SQLite file location).

## Run

```bash
.venv/bin/python src/app.py         # the whole app (or double-click Clawnly.command) — http://127.0.0.1:8000
.venv/bin/python src/demo.py        # FREE: full PoC pipeline offline, scripted AI (no API, no cost)
.venv/bin/python src/users.py       # FREE: print the 12 simulated users as JSON
.venv/bin/python src/main.py        # COSTS ~cents: interview -> match -> negotiate -> popup, real Claude
.venv/bin/python src/eval.py        # COSTS ~cents: evaluation harness across many pools
.venv/bin/python src/dryrun.py      # COSTS real $: N AI personas through the REAL pilot pipeline
                                     #   (see its module docstring -- chat vs. bulk mode, cost notes)
```

Inside the app: the admin console (`/`) has a free **Demo mode**; Live mode
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
