# Clawnly -- instructions for Claude Code

Read this first in every session. Full product vision lives in `docs/PRD.md`; the
original technical spec (still mostly accurate, but the app has grown beyond it)
is `docs/SPEC.md`. The engineering roadmap and current build status live in
`docs/ROADMAP.md` -- read that before starting any new work so you know what's
already done and what's next.

## What this project is

An AI matchmaking prototype: a Master Claw reasons across user profiles to form
small, genuinely-compatible real-world friend groups, with grounded, defensible
reasoning and hard constraints enforced in code (never trusted to the LLM). See
`docs/PRD.md` section 0 for the exact definition of "legit matching" the whole
product is built to prove.

## Current state (keep this updated)

- Core matching engine (`claw.py`, `master_claw.py`, `negotiation.py`, `popup.py`)
  is stable and tested. **Do not modify its core logic without an explicit
  request** -- new capability gets added around it, not into it.
- Persistence: SQLite via `db.py` (plain `sqlite3`, no ORM -- see its module
  docstring for the full table list). Replaced the old in-memory `STATE` dict
  and flat `cast.json`/`feedback.json` files.
- Real-user pilot (neighborhood registration -> onboarding -> threshold-triggered
  matching) is in progress. `src/auth.py` (Google OAuth + email magic link,
  session-cookie-backed by a `sessions` table) is built and tested. See
  `docs/ROADMAP.md` for the staged build plan and exactly which stage is done.

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
  routes `client.messages.create(**kwargs)` by inspecting the system prompt --
  zero real API calls in CI, ever. Follow this pattern for any new AI call site.
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
(Sonnet), `MODEL_PREMIUM` (Opus) -- and named per-task aliases on top of them
(`MODEL_MATCH`, `MODEL_CLAW`, etc). When adding a new AI call, pick the
cheapest tier that can reliably do the job; read the comments in `config.py`
for the reasoning behind each existing task's tier before changing one.
