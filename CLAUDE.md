# Clawnly -- instructions for Claude Code

Read this first in every session. What's being built right now, and in what
order, is `docs/THIS_WEEK.md`; the longer-running history is `docs/ROADMAP.md`.
`README.md` describes the product and the code as they are today.

## What this project is

Agent-to-agent friend matching. Each person brings the AI that already knows
them (ChatGPT, Claude, Muse, Instinct); what it writes about the real person
becomes their Claw's dossier. Claws talk privately with each other; a hub picks
who talks, judges every conversation, and invites two people to meet only when
the fit is deep and provable from the transcript. Humans only say yes or no.
Every hub thought, agent message and code check is logged. Hard rules (pair
limits, verbatim-quote evidence, the depth gate, one invitation per person,
name-blind pitches) are enforced in code, never trusted to the model.

## Current state (keep this updated)

- **2026-09-23: agent-to-agent pivot, old logic removed.** The core is
  `dossier.py` (import prompt + card) -> `agent_talk.py` (the Claw) ->
  `orchestrator.py` (the hub: pair -> talk -> judge -> gate), with every step in
  `db.events` and every conversation in `db.agent_conversations`. `batch.py`
  runs a hub round for a neighborhood and turns invitations into the yes/no gate
  (`my_match.py`, stored as `matches` + `match_acceptances`).
- The old group matcher, negotiation, meetup popups, onboarding chat, demo
  console and its tooling are gone. They live on the `pre-agent-pivot` branch.
  Don't resurrect them; take ideas from there deliberately.
- Real-user pilot flow: `/join/<slug>` -> login (`auth.py`, Google OAuth + email
  magic link, sessions in SQLite) -> `/consent` -> `/onboarding` (bring your
  agent, `bring_agent.py`) -> hub round -> `/my-match`. Admin at `/admin`.
- Persistence: SQLite via `db.py` (plain `sqlite3`, no ORM -- its module
  docstring lists every table).
- `lounge/clawnly-lounge.html` is a separate, shareable prototype of the same
  idea, published as a claude.ai Artifact. Read its `README.md` before
  republishing it: its saved state lives inside the published page.

## Hard style rules (SPEC section 10 -- these are non-negotiable, not style preference)

- No ternary operators.
- No enhanced for-loops -- index-based or `while` loops. The ONE exception:
  list comprehensions are allowed for `asyncio.gather` fan-out (building the
  awaitable list), nowhere else.
- Simple, readable variable names. Short, lowercase inline comments explaining
  *why*, not *what* -- the code should read as what it does without them.
- Each module does one job. Prefer a new flat module (`auth.py`, `batch.py`,
  ...) over a subpackage -- this codebase has never used subpackages.

## Testing

- Everything runs offline against a `FakeClient` (`tests/conftest.py`) that
  routes `client.messages.create(**kwargs)` by a marker phrase in the system
  prompt (card / agent turn / pairing / verdict) -- zero real API calls in CI,
  ever. Follow this pattern for any new AI call site, and keep the marker phrase
  on one line of the prompt (a line break inside it silently breaks routing).
- `conftest.make_joined_resident()` creates a consented resident who has
  brought their agent -- use it instead of hand-building resident rows.
- `tests/conftest.py` points `CLAWNLY_DB_PATH` at an isolated test database
  before anything imports `db.py` -- tests never touch the real `clawnly.db`.
- One test file per module (`test_auth.py` <-> `auth.py`, etc). `pytest -q`
  must stay green after every change -- if it doesn't, fix it before moving on,
  don't leave a red suite for later.
- **`config.resolve_env()` falls back to reading the real `.env` file on disk**,
  which may have real secrets in it on a dev machine. Any test asserting
  "X is not configured" must patch `config.resolve_env` itself (see
  `clear_env()` in `tests/test_auth.py`) -- `monkeypatch.delenv` alone is not
  enough and will silently pass/fail depending on what's in `.env` that day.
- After tests pass, verify the actual behavior against a **live running
  server** (`.venv/bin/python src/app.py`, then real `curl`/browser calls, then
  kill it) before calling something done -- this caught real bugs unit tests
  didn't, twice already this project (restart-durability, the exact issue
  above). Don't skip it for anything touching persistence, auth, or a new route.

## Secrets

- Real secrets (Anthropic key, Google OAuth client id/secret, Resend API key)
  live in a gitignored `.env` at the project root, one `NAME=value` per line.
  `config.resolve_env(name)` reads env-first then falls back to that file.
- **Never** print, log, or echo the contents of `.env` -- if you need to check
  what's configured, list key *names* only (`grep -oE '^[A-Z_]+=' .env`), never
  values.
- Anything touching `auth.py`, `db.py`'s session/token tables, or new routes
  handling login/personal data should get a `security-review` pass before
  being considered done.

## Working rhythm this project has used successfully

- For anything non-trivial (new auth surface, a new architectural piece,
  multiple valid approaches) -- use plan mode, get explicit approval, THEN
  build. Don't skip straight to code on judgment calls that are really the
  user's to make.
- Build in reviewable stages, not one giant pass -- explain a stage plainly,
  build it, run the full test suite, verify it live, then report back and
  let the user decide whether to continue immediately or pick it up later.
- When you notice a real gap while building something else (e.g. a test that
  turns out to be wrong, not just failing), fix the actual root cause and say
  so plainly -- don't paper over a red test.
- Default to making the reasonable call on minor implementation details (an
  obvious variable name, a small helper's exact signature, which existing
  pattern to reuse) without stopping to ask. Stop and ask only when a decision
  is genuinely the user's to make -- a product/business tradeoff, anything
  destructive, anything needing a credential or account only they have.
- **`git fetch` and check `git log HEAD..origin/main` before starting new
  work, every session.** The user runs multiple Claude Code sessions against
  this same repo (including cloud/PR-based ones) -- confirmed in practice
  when a separate session's PR merged 7 commits (new demo tooling, an admin
  login route, a Render disk fix) that this session only discovered by
  accident. `docs/ROADMAP.md` is the source of truth, but only if it's
  actually current -- if local is behind, pull first and skim what changed
  before trusting ROADMAP.md's account of "done."

## Model routing (product's own AI calls, not Claude Code's own model)

`config.py` defines three tiers -- `MODEL_CHEAP` (Haiku), `MODEL_REASONING`
(Sonnet), `MODEL_PREMIUM` (Opus 5.5) -- and named per-task aliases on top of
them (`MODEL_AGENT_TURN`, `MODEL_HUB_VERDICT`, etc). When adding a new AI call,
pick the cheapest tier that can reliably do the job; read the comments in
`config.py` before changing one. Opus 5.5 has thinking always on (it counts
toward `max_tokens`, so keep caps generous) and rejects `temperature` -- depth is
set with `config.HUB_EFFORT`.
