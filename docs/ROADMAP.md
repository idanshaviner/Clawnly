# Clawnly -- Engineering Roadmap

Living document. Update the status line on a milestone whenever it changes.
Read this before starting new work so you know what's already done.

Written for real-user launch, per `docs/PRD.md`: prove matching is legit on
simulated data (done, Phase 1), then connect real users starting with a single
dense neighborhood pilot, then scale. See PRD section 12 for the product-level
phase gates this technical roadmap maps onto.

---

## Milestone 1 -- Real persistence
**Status: DONE.**
Replaced the in-memory `STATE` dict + flat `cast.json`/`feedback.json` files
with SQLite (`src/db.py`): users, runs, interviews, matches, negotiations,
meetups, feedback. Restart-safe. Zero changes to the matching/negotiation/popup
logic -- purely a storage swap. 168 tests at completion.

## Milestone 2 -- Cost-efficient AI architecture
**Status: PARTIALLY DONE.**
`config.py` now defines three model tiers (`MODEL_CHEAP`/`MODEL_REASONING`/
`MODEL_PREMIUM`) with named per-task aliases on top -- route new AI tasks to
the cheapest tier that can do the job. **Still missing:** real token/dollar
usage tracking (today's `CountingClient` in `app.py` only counts API *calls*
per model, not tokens or cost) and a real multi-provider adapter if a
non-Anthropic model is ever tried. Known cost risks to watch: the match-call
retry loop (`master_claw.find_matches`, up to 3x the most expensive call per
group on a bad reply), and `_feedback_text()` re-injecting *every* piece of
feedback ever collected into every future match call, uncapped.

## Milestone 3 -- Production-quality matchmaking engine
**Status: NOT STARTED** (beyond what Milestone 1 already hardened: score/why_not
validation, computed shared-hobby/availability compatibility hints).
Needed once real users exist: geography as a HARD constraint (H5 -- radius,
mirroring the existing H1-H4 pattern in `_validate_group`) and an age-range
hard constraint (H6). Today neither exists in code at all -- `location`/`age`
are decorative text sent to the model, not validated.

## Milestone 4 -- Real-user onboarding
**Status: IN PROGRESS.** See the neighborhood-pilot plan below -- this
milestone and Milestone 4 are effectively the same piece of work, being built
in stages.

## Milestone 5 -- Geographic matchmaking
**Status: NOT STARTED**, but simplified for the pilot: since the pilot is a
single invite-link-scoped neighborhood cohort, "geography" for now just means
"whoever registered through this neighborhood's link" -- real radius-based
matching across multiple neighborhoods is deferred until there's more than one.
The confirmed real pilot cohort is "Ten Trails" (confirmed 2026-09-01, from
the brand pitch video review) -- use it as the actual invite-link slug/name
at launch.

## Milestone 6 -- Group negotiation
**Status: DONE**, no changes needed. Already bounded (max 4 rounds), cheap
model for the many per-person reactions, no full-history resend each round.
Worth adding once real usage exists: track rounds-to-agreement / cost-per-
negotiation in the usage table from Milestone 2.

## Milestone 7 -- Meetup creation
**Status: DONE** for the engine (`popup.py` already produces grounded, specific
venue suggestions). Not yet code-validated: that the suggested time actually
falls within the group's shared availability windows (currently prompt-
instructed only, not checked in code like the hard constraints are).

## Milestone 8 -- Feedback/evaluation loop
**Status: PARTIALLY DONE.** Thumbs-up/down + note exists and is persisted
(Milestone 1), but is still global/unlinked to a specific match. Needed:
link feedback to a specific `matches` row, structured "did you meet / would
meet again" capture (not just free text), and a cap on how much feedback gets
reinjected into future match prompts (see the cost risk noted in Milestone 2).

## Milestone 9 -- Seattle/neighborhood pilot
**Status: IN PROGRESS.** This is the neighborhood-pilot plan below.

## Milestone 10 -- Scaling architecture
**Status: NOT STARTED, intentionally.** Don't start this until the pilot has
actually run. Known gaps already flagged (from an earlier security pass):
no per-request auth existed before this pilot's auth work (now partially
addressed), no rate limiting anywhere, and the admin/BYOK/demo-only mode
switches in `app.py` need re-auditing now that real accounts exist.

## Milestone 11 -- Monetization readiness
**Status: NOT STARTED, intentionally.** Data-only milestone (instrument
meetup volume, repeat rate, retention, cost-per-user) once pilot data exists
-- no payment code until then.

---

## Neighborhood pilot (Milestones 4 + 9): staged build plan

Full plan with reasoning was approved via Claude Code's plan mode; a copy
lives at `docs/PILOT_PLAN.md` in this repo for durability (plan-mode files
live outside the repo and aren't guaranteed to stick around).

**Stage 1 -- Data model + auth backbone: DONE.**
`src/auth.py` (Google OAuth via `authlib` + email magic link via a plain
Resend `httpx` call, dev-mode console-log fallback if `RESEND_API_KEY` isn't
set), new `db.py` tables (`neighborhoods`, `residents`, `onboarding_messages`,
`sessions`, `magic_link_tokens`, `oauth_states`), routes wired into `app.py`
(`/auth/google/login`, `/auth/google/callback`, `/auth/magic-link/verify`,
`/api/auth/magic-link/request`, `/api/auth/logout`, `/api/me`). Verified
against a real running server, not just mocked tests: full magic-link
round-trip, session survives a restart, admin allowlist path, idempotent
resident creation, single-use token enforcement. 203 tests passing.

Needs from the human operator before real Google/email login work (not
blocking -- dev mode already works): a Google Cloud OAuth app (redirect URI
`{domain}/auth/google/callback`; **watch the 100-test-user cap on "Testing"
publishing status -- same number as the batch threshold**) and a Resend
account + verified sending domain. Both go in `.env`.

**Stage 2 -- Registration + consent: DONE.**
`web/join.html` (invite-link landing page at `GET /join/{slug}`, alpha
banner + framing, Google/magic-link login) and `web/consent.html` (`GET
/consent`) plus `db.record_consent` / `POST /api/consent` (idempotent --
first agreement wins) capture `consent_agreed_at` on the resident row.
Google/magic-link login now branches on role: a resident is redirected to
`/consent` after login, an admin still gets the plain proof-of-login page
(no admin dashboard yet). `/api/me` now also reports `consent_agreed_at`.
Verified live against a running server (direct DB-seeded session, since
this dev machine's real Resend/Google creds are already configured and
sending a real email wasn't needed to exercise the new routes). 211 tests
passing.

**Stage 3 -- Onboarding chat + completeness tracking: DONE.**
`Claw.__init__` gained `simulated=True` (default -- zero change to existing
behavior, regression-tested in `test_claw.py`); `simulated=False` builds its
system prompt (`REAL_ONBOARDING_STYLE` in `claw.py`) strictly from stored
profile fields actually known so far + persisted conversation, explicitly
never inventing. New flat module `src/onboarding.py`: `take_turn(resident,
message, client=None)` runs the chat reply (now correctly on
`config.MODEL_ONBOARDING_CHAT`, previously-unused since Stage 1) + a second
structured call on `MODEL_ONBOARDING_COMPLETENESS` that reports which of the
five gating slots (`onboarding.SLOT_NAMES`) are genuinely evidenced plus
best-effort values for the rest of the resident row; extracted
hobbies/availability/group-size are validated against the same closed
vocabularies `persona_gen.py` uses before being persisted (anything invalid
is dropped, never trusted blindly). Hard 20-turn cap
(`MAX_ONBOARDING_TURNS`) force-completes. A bookkeeping (extraction) failure
never turns an already-successful reply into a visible error -- both sides
of the exchange are persisted first; the reply always reaches the resident.
New routes: `GET /onboarding`, `GET /api/onboarding/history`, `POST
/api/onboarding/message` (all gated by `_require_consented_resident` in
`app.py` -- resident resolved only from the session cookie, 403 without
consent). Onboarding always uses the server's real client (no demo/BYOK
toggle -- this is private authenticated real-user data, deliberately never
tested against scripted fake replies). Live-verified against a running
server: auth/consent gating (401/403), restart-durability of persisted
messages + profile fields + slots_status. The one real end-to-end chat call
during live verification surfaced that this dev machine's configured
`ANTHROPIC_API_KEY` is currently invalid/expired (a pre-existing environment
issue, not a code bug -- the route correctly returned a clean 500 with no
partial DB writes). 235 tests passing.

**Stage 4 -- Batch trigger + real-pipeline wiring: NOT STARTED.**
New `src/batch.py`: `check_and_trigger_batch(neighborhood_id)`, called
synchronously right after a resident's profile is marked complete (no
scheduler/poller -- see the plan doc for why). Maps complete residents into
the same profile-dict shape `run_pipeline` already expects (id prefixed
`"r"`, e.g. `"r17"`, so no collision with the demo cast's `"u01"` ids), then
calls the existing, **unmodified** `run_pipeline()`.

**Stage 5 -- Match acceptance (mutual reveal gate) + resident-facing results
page: NOT STARTED.** Reshaped 2026-09-01 after reviewing a brand pitch video
(see `docs/PILOT_PLAN.md`'s addendum) -- adds a step that doesn't exist in
code today: before a resident sees who else is in their formed group, they
see only the match's reason + group size and accept/decline; once every
member accepts, the match is sealed (full reveal, and `negotiation.py` ->
`popup.py` run for the first time for that match); a decline dissolves the
match and releases its members back into the pool for the next batch,
without redoing onboarding. New `match_acceptances` table,
`/api/my-match` + `/api/my-match/respond`, `web/my-match.html`. In-app only
(confirmed decision -- no email notification for the pilot). Fold in
Milestone 8's structured post-meetup feedback if scope allows.

**Stage 6 -- Admin dashboard: NOT STARTED.**
Neighborhood progress, resident list + status, manual "trigger batch now"
override, usage visibility (reusing the `CountingClient` call-count pattern --
full dollar tracking is Milestone 2, not rebuilt here).

---

## Highest-priority items if picking up fresh work (not already covered above)

1. Continue the neighborhood-pilot stages in order (2 -> 6) -- each depends on
   the last.
2. Milestone 2's real token/cost tracking, once pilot usage exists to make it
   worth building.
3. Milestone 3's geo/age hard constraints, needed before the pilot can safely
   scale past one neighborhood.
4. Milestone 8's feedback-cap fix -- cheap, and the risk it addresses is
   already live, not hypothetical.
