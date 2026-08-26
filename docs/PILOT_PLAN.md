# Real-user neighborhood pilot: registration, onboarding, threshold-triggered matching

> Copied into the repo from an approved Claude Code plan-mode session for
> durability (plan files live in `~/.claude/plans/` outside the repo and
> aren't guaranteed to persist). See `docs/ROADMAP.md` for current stage
> status -- this file is the frozen plan, not the live status tracker.

## Context

Clawnly's matching engine (`master_claw.py`, `negotiation.py`, `popup.py`, `claw.py`) and its
persistence layer (`db.py`, built in Milestone 1) are solid and battle-tested against 168 offline
tests. Everything built so far assumes one operator clicking "Run" against a single shared,
admin-editable cast of either simulated or AI-generated people.

We're now launching a real pilot in one neighborhood: residents register through an invite link,
log in, have an open-ended conversation with their own Claw (not the current fixed two-question
interview), and once ~100 residents are profile-complete, the existing pipeline runs automatically
and each resulting group sees their meetup suggestion in-app. This is the first time real names,
real emails, and real personal conversations enter the system, so auth, consent, and per-user data
isolation become first-class requirements for the first time.

Decisions already confirmed with the user:
- **Login:** Google OAuth + email magic-link, both offered.
- **No ChatGPT-history import** -- the Claw conversation is the only way the system learns about someone.
- **Trigger:** headcount threshold (100), configurable, no time-based backstop requested.
- **Notification:** in-app only, no email for meetup delivery.
- **Consent:** "figure it out -- alpha mode." Baseline consent + an alpha-mode framing, not a
  substitute for real legal review before a wider launch.
- **Admin:** full monitoring is wanted; the existing "only the Master Claw ever aggregates across
  users, individual Claws never talk to each other" boundary must be preserved and extended into
  auth (a resident's session can only ever act on their own data).

A focused technical-design sub-agent validated two of the riskiest choices below (auth mechanism,
background trigger mechanism) against this exact repo; their recommendations are incorporated.

## Key architecture decisions

**Auth.** Extend `db.py` (same style: plain `sqlite3`, module-level functions, JSON-in-TEXT
columns) with `sessions` and `magic_link_tokens` tables -- this replaces/extends the existing
in-memory `_SESSIONS` dict pattern already in `app.py` with a durable version. New `src/auth.py`
module (one flat file, matching `claw.py`/`negotiation.py` style):
- Google OAuth via `authlib` (new dependency -- pure Python, no native build step; hand-rolling
  OAuth2 code-exchange/state/PKCE is exactly the kind of thing not worth reinventing).
- Magic links: `secrets.token_urlsafe(32)`, stored **hashed**, single-use, expiring. Sent via
  **Resend** (free tier covers pilot scale) using a plain `httpx.post` call -- no email SDK
  dependency. `httpx` gets added to `requirements.txt` explicitly (it's currently only a transitive
  dependency via starlette's test client, not safe to rely on for production code).
- Sessions: opaque token in an httpOnly/secure/samesite cookie, validated via a `sessions` table
  lookup (not a JWT -- a DB lookup is simpler, trivially revocable, and consistent with `db.py`'s
  existing style).
- Admin gating: `config.ADMIN_EMAILS = [...]`, checked the same way `_validate_changes` already
  gates other things -- no RBAC framework, this is a single-operator alpha.

**Manual prerequisite, flagged loudly:** a Google Cloud OAuth consent screen must be registered
before Google login works. **Important:** an app left in "Testing" publishing status caps at 100
test users -- the same number as our batch threshold. Either the consent screen needs to move to
"In production" (may require Google's review) or this will silently block exactly the residents who
matter most (the ones who complete the cohort). Flagging this now so it's handled in parallel, not
discovered at resident #100.

Also needed from you before Google login can work at all: the OAuth client id/secret from that
Cloud Console app. And for magic links: a Resend account + verified sending domain + API key.
Both follow the same `.env` pattern `config.resolve_api_key()` already uses for the Anthropic key.

**Background trigger.** No scheduler, no queue system. `src/batch.py` adds
`check_and_trigger_batch(neighborhood_id)`, called synchronously right after a resident's onboarding
is marked complete (the only event that can cross the threshold -- a poller would just add latency
for no benefit at this scale). It counts complete residents for that cohort, and does a
compare-and-swap `UPDATE neighborhoods SET batch_triggered_at=? WHERE id=? AND batch_triggered_at
IS NULL` to guard against two near-simultaneous completions double-triggering, then
`asyncio.create_task(...)` -- the same fire-and-forget pattern `/api/run-stream` already uses.

**Data model -- new tables, existing tables untouched.** The current `users` table stays exactly as
it is (it's the demo/admin-console cast -- still useful, including as the "we gave AI 12 strangers"
marketing hook from the PRD). Real residents are a different concept entirely: partially-filled
profiles that build up over a conversation, tied to a login identity and a neighborhood. New tables
in `db.py`:
- `neighborhoods`: id, slug, name, invite_code, batch_threshold (snapshotted from
  `config.MATCH_BATCH_THRESHOLD` at creation time -- see below), batch_triggered_at, created_at.
- `residents`: id, neighborhood_id, email, auth_method, consent_agreed_at, the same profile fields
  `users` has (all nullable -- they fill in over the conversation), `slots_status` (JSON, e.g.
  `{"personality":"filled","interests":"missing",...}`), `profile_complete_at`, created_at.
  UNIQUE(neighborhood_id, email).
- `onboarding_messages`: id, resident_id, role, content, created_at -- the persistent chat transcript
  (today's `Claw.chat()` only takes an in-request `history` list; this makes it durable across
  sessions, the same problem Milestone 1 already solved for the admin cast).
- `sessions`, `magic_link_tokens` (auth, above).

`runs` (existing table) gets one new nullable column, `neighborhood_id`, so a real pilot batch is
distinguishable from a demo-cast run in the same table -- no parallel history table needed. When a
batch triggers, complete residents are mapped into the exact same profile-dict shape
`run_pipeline`/`MasterClaw` already expect (id prefixed `"r"` + resident id, e.g. `"r17"`, so
there's no possible collision with demo-cast `"u01"`-style ids), and the **existing**
`run_pipeline()` is called completely unmodified. Persistence of the result reuses
`db.create_run`/`save_interviews`/`save_match`/`save_negotiation`/`save_meetup`/`finish_run` exactly
as `app.py::_persist_run` already does for the admin console.

**Threshold config.** `config.MATCH_BATCH_THRESHOLD = 100`, commented like the existing
`MIN_MATCH_QUALITY`/`MATCH_EFFORT` tunables -- the "easy to change later" lever you asked for. Each
neighborhood snapshots this value into its own `batch_threshold` column at creation time, so
changing the global default doesn't retroactively shift the bar for a cohort already in progress.

**Real-user Claw mode.** `claw.py`'s current persona prompt explicitly instructs the model to
*invent* facts ("fully invent and embody this character") -- correct for the simulated demo cast,
wrong and unsafe for a real person. Add a `simulated=True` parameter to `Claw.__init__` (default
`True`, so every existing call site and test is completely unaffected) -- when `False`, the system
prompt instead grounds the Claw strictly in stored profile fields + persisted conversation history,
explicitly forbidding invention. This is the one required change inside `claw.py`; `master_claw.py`,
`negotiation.py`, `popup.py` are not touched at all.

**Onboarding completeness.** One user-facing chat call per turn (unchanged UX), plus a lightweight
follow-up structured call on the cheap tier (`config.MODEL_ONBOARDING_COMPLETENESS`, Haiku -- cheap
enough to run every turn, unlike the conversational reply itself) that reads the transcript so far
and returns which of the five slots (personality/energy, interests, availability, group-size
preference, what they're seeking) are genuinely filled with evidence, not guessed. When all slots
read filled, mark `profile_complete_at` and call `check_and_trigger_batch`. A hard cap (~20 turns)
force-completes with whatever's gathered so nobody gets stuck in an endless conversation -- the same
safety-valve pattern `master_claw.py`'s `MAX_MATCH_ATTEMPTS` retry loop already uses elsewhere in
this codebase.

**Consent + alpha framing.** A plain-language consent screen shown once, before the first
onboarding message: what's collected, that a Master Claw uses it to arrange real-world meetups with
strangers, and that this is alpha/experimental. Stored as `consent_agreed_at` on the resident row.
A persistent "alpha" banner in the resident-facing UI. A self-service `/api/account/delete` a
logged-in resident can call themselves. Known accepted limitation for alpha: if someone deletes
their account after already being placed in an agreed meetup, their teammates' view of "who's in my
group" isn't retroactively cleaned up -- flagged for manual admin handling rather than engineered
around now.

**Admin surface.** New auth-gated routes (`is_admin(email)`), reusing existing data rather than
building new tracking: neighborhood progress (`count(profile_complete_at) / batch_threshold`),
resident list per neighborhood with status, a manual "trigger batch now" override (bypasses the
threshold -- useful for testing), and usage visibility reusing the existing `CountingClient`
call-count pattern from `app.py` (full token/dollar cost tracking is real Milestone 2 work from the
roadmap -- out of scope here, this just surfaces what's already collected). Recent interview/batch
failures surfaced from the existing `error` field on interview records.

**Frontend.** New plain HTML/JS pages, same no-build-step style as the existing `web/index.html`
(including its `esc()` XSS-safe rendering pattern) -- `web/join.html` (neighborhood landing +
login), `web/onboarding.html` (the chat), `web/my-match.html` (a resident's result once matched),
`web/admin.html` (the dashboard). Not visually polished yet -- functional first.

## Build sequence

This is a lot of surface area touching auth for the first time, so build and check in on it in
stages rather than one pass, the same way Milestone 1 went:

1. **Data model + auth backbone** -- new `db.py` tables, `auth.py` (Google OAuth + magic link +
   sessions), login/callback/logout routes, admin gating. No onboarding chat yet. **DONE.**
2. **Registration + consent** -- the invite-link landing page, neighborhood creation, consent
   capture. **DONE.**
3. **Onboarding chat + completeness tracking** -- the `simulated=False` Claw mode, persisted
   conversation, the slot-tracking completeness check, the turn cap.
4. **Batch trigger + real-pipeline wiring** -- `batch.py`, resident->profile-dict mapping, reusing
   `run_pipeline` and the existing persistence helpers.
5. **Resident-facing results page** -- "my match" lookup and display.
6. **Admin dashboard** -- progress view, resident list, manual trigger override, usage visibility.

## Tests

Follow the existing offline `FakeClient`/`conftest.py` pattern throughout -- no real API calls, no
real OAuth/email calls in CI (mock `authlib`'s token exchange and the Resend `httpx.post` call the
same way `_client_for` is already mocked in `test_app.py`). Each new module gets its own test file
matching the existing one-test-file-per-module convention (`test_auth.py`, `test_batch.py`, etc.).
Explicit coverage needed: session validity/expiry, magic-link single-use, the batch-trigger
compare-and-swap under concurrent completions, the turn-cap force-completion, and that
`simulated=True` Claw behavior is byte-for-byte unchanged from today (regression guard on the
existing tests plus new ones).

## Verification

After each stage: run `pytest -q` (must stay green throughout -- no existing test should ever
break, since none of this touches the matching/negotiation/popup logic), then manually exercise the
new stage's flow against the running app (`python src/app.py`) -- e.g. after stage 1, actually click
through Google's real OAuth consent screen and a real magic-link email rather than trusting mocks
alone, the same way Milestone 1 was checked with real curl calls against a live server before/after
a restart. **A test-isolation lesson from stage 1: `config.resolve_env()` reads the real `.env`
file as a fallback, so any test asserting "not configured" must patch `resolve_env` itself, not
just `monkeypatch.delenv` -- see `clear_env()` in `tests/test_auth.py`.**
