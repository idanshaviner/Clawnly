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
**Status: All 6 build stages DONE** (registration/consent, onboarding chat,
batch trigger, mutual reveal gate, admin dashboard) -- see the neighborhood-
pilot plan below; this milestone and Milestone 9 are effectively the same
piece of work, built in stages. Not yet "launched": still needs the human
prerequisites Stage 1 flagged (a Google OAuth consent screen moved to
production, a verified Resend sending domain) and an actual cohort of real
residents.

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
**Status: All 6 build stages DONE**, real launch still pending (see Milestone
4's note above). This is the neighborhood-pilot plan below.

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

**Stage 4 -- Batch trigger + real-pipeline wiring: DONE.**
New `src/batch.py`: `check_and_trigger_batch(neighborhood_id, client=None)`,
called synchronously (fire-and-forget via `asyncio.create_task`, same pattern
`/api/run-stream` already uses) right after `db.mark_profile_complete` in
`onboarding.py`'s `take_turn`. Counts `db.list_complete_residents`, and once
the count meets the neighborhood's snapshotted `batch_threshold`, does the
compare-and-swap (`db.try_trigger_batch` -- `UPDATE ... WHERE
batch_triggered_at IS NULL`, guarded by `sqlite3`'s `cursor.rowcount`) so two
near-simultaneous completions can't double-trigger. `batch.resident_to_profile`
maps each complete resident into the exact profile-dict shape
`run_pipeline`/`MasterClaw`/`Claw(simulated=True)` already require (id
prefixed `"r"`, e.g. `"r17"`; every field is mandatory there, so anything
onboarding's best-effort extraction never caught gets a plain, honest,
schema-valid default -- never blocks or crashes the run). Calls the existing,
**unmodified** `run_pipeline()`, then persists via a new shared
`db.persist_run_result(mode, signature, result, neighborhood_id=None)` --
extracted from app.py's old inline `_persist_run` body so admin-console runs
and real-pilot batch runs share one save path; `runs.neighborhood_id` (Stage
1's nullable column) tags a batch run. A pipeline exception after the CAS has
fired is caught and logged, not raised (the fire-and-forget task must never
surface an error through an unrelated resident's chat reply) -- an accepted
alpha limitation: the neighborhood's one-shot trigger is then spent with
nothing persisted, needing operator intervention (Stage 6). 12 new tests
(`tests/test_batch.py`), 246 passing. Live-verified against a running server
with an isolated DB: seeded 3 complete residents at `batch_threshold=3`,
confirmed the CAS fires exactly once (a second call is a no-op, one `runs`
row), confirmed `resident_to_profile`'s output is a well-formed request that
reaches the real Anthropic API (this dev machine's expired key returns a
clean per-interview 401, isolated by `master_claw.py`'s existing per-Claw
error handling -- the run still completes and persists with 0 groups, not a
crash), and confirmed both the CAS state and the persisted run survive a
server restart.

**Stage 5 -- Match acceptance (mutual reveal gate) + resident-facing results
page: DONE.** New `match_acceptances` table (one row per resident member of a
formed match, `status` pending/accepted/declined) plus `sealed_at`/
`dissolved_at` columns on the existing `matches` table. Rows are created
automatically by `db.persist_run_result` for every "r"-prefixed member of a
formed group (a no-op for admin-console runs, whose members are all
"u01"-style ids) -- so Stage 4's batch persistence and Stage 5's reveal gate
share one code path with no duplication.

New `src/my_match.py` (pure DB/routing logic, no AI calls of its own):
`get_state(resident)` resolves state strictly from the caller's own most
recent `match_acceptances` row (`db.latest_match_acceptance`, never a
client-supplied id) -- `not_yet_batched` / `no_match` / `pending` (reason +
group size only, no other names) / `waiting` (accepted, not sealed yet) /
`sealed` (first-name reveal of every other member + the meetup card, which
was already computed by `batch.py`'s pipeline run -- see `my_match.py`'s
docstring for why negotiation/popup run eagerly during the batch rather than
lazily on seal) / `dissolved`. `respond(resident, match_id, response)` writes
only the caller's own row (`db.respond_to_acceptance`, guarded the same
first-response-wins way as `record_consent`); the accept that completes the
set calls `db.mark_match_sealed`, a decline calls `db.mark_match_dissolved`
which dissolves the match for every member. Releasing dissolved members back
into the pool needed no new resident-level column: `db.list_eligible_residents`
(profile-complete AND not tied to a match whose `dissolved_at IS NULL`)
naturally re-includes them once their match is marked dissolved;
`batch.check_and_trigger_batch` now calls this instead of the plain
completeness count.

New routes `GET /api/my-match`, `POST /api/my-match/respond`, and
`GET /my-match` (`web/my-match.html`, same cream/sage/serif style as
`join.html`/`consent.html`/`onboarding.html`), both API routes gated by the
existing `_require_consented_resident`. In-app only (confirmed decision -- no
email notification for the pilot). Milestone 8's structured post-meetup
feedback was left as a fast-follow, not folded in, to keep this stage
reviewable on its own.

28 new tests (`tests/test_my_match.py`, plus additions to `tests/test_db.py`
and `tests/test_auth.py`), 274 passing. A `security-review` pass on the new
routes/table found no high-confidence issues (parameterized SQL throughout,
every dynamic value in `my-match.html` written via `textContent` not
`innerHTML`, `respond` scoped to `(match_id, resident_id)` from the session
so one resident's request can never touch another's row). Live-verified
against a running server with an isolated DB: seeded a 3-person match and
drove the real `/api/my-match` + `/api/my-match/respond` routes with three
separate session cookies through pending -> waiting -> sealed (confirmed the
pending payload never leaks names, and each sealed viewer sees only the
OTHER two first names), confirmed an IDOR attempt against a match the caller
isn't a member of is rejected, confirmed sealed state survives a server
restart, and separately confirmed a decline dissolves a second match for both
members and both re-appear in `db.list_eligible_residents` immediately after.

**Known caveat carried into Stage 6:** `check_and_trigger_batch`'s
compare-and-swap is one-shot per neighborhood (`batch_triggered_at` is never
reset), so residents released by a decline are correctly eligible again in
`db.list_eligible_residents`, but nothing currently fires a *second* trigger
to actually re-match them -- that needs Stage 6's planned manual "trigger
batch now" admin override (or a future reset-on-release design), not
engineered around here per CLAUDE.md's guidance not to build ahead of an
actual need.

**Stage 6 -- Admin dashboard: DONE.**
Built as a stretch goal after Stage 5, same rigor. Pure read-only aggregation
of data the earlier stages already persist, per the plan ("reusing existing
data rather than building new tracking") -- no new tracking tables.

New `src/admin.py`: `list_neighborhood_progress()` / `neighborhood_progress()`
(`complete_count`/`resident_count` vs. `batch_threshold`), `resident_summaries`
(a plain status rollup -- `onboarding` / `complete_unmatched` / `match_pending`
/ `match_waiting` / `sealed` / `dissolved` -- computed from
`profile_complete_at` + the resident's latest `match_acceptances` row + its
match's `sealed_at`/`dissolved_at`, nothing new tracked), and
`recent_run_summaries` (group/unmatched counts + usage, and any interview
`error` records -- the plan's "recent interview/batch failures" requirement,
reusing `db.load_run_result` rather than a new failure-tracking mechanism).

New `src/usage.py`: `CountingClient`, extracted verbatim from app.py's old
inline definition so `batch.py`'s real-pilot runs (both the automatic
threshold trigger and the new manual override) can report a call-count usage
tally the same way the admin console always has -- `app.py`'s own usage meter
is unchanged, just now imports the shared wrapper. `db.persist_run_result`
saves `result["usage"]` (when present) to a new `runs.usage` column
(`db.set_run_usage`); `db.list_runs_for_neighborhood` surfaces it per run.

New `batch.force_trigger_batch(neighborhood_id, client=None)`: the admin
dashboard's manual "trigger batch now" override -- bypasses `batch_threshold`
entirely (useful for testing, and for actually re-matching residents a
decline released back into the pool, resolving Stage 5's noted caveat -- see
`db.mark_batch_triggered`, which unlike the automatic path's
compare-and-swap is allowed to fire again after an earlier trigger). Still
enforces the one real structural floor -- at least 2 eligible residents
(`master_claw.py`'s own H4 minimum for any group at all) -- and, since it
runs synchronously inside an authenticated admin request rather than
fire-and-forget, lets a pipeline exception propagate as a real error instead
of being swallowed.

New routes `GET /admin` (`web/admin.html` -- plain/functional styling
matching `web/index.html`'s existing admin-console palette, not the
resident-facing cream/sage style; ungated itself, its JS calls gated APIs
the same way `onboarding.html`/`my-match.html` already do), `GET
/api/admin/neighborhoods`, `GET /api/admin/neighborhoods/{id}` (residents +
recent runs), and `POST /api/admin/neighborhoods/{id}/trigger`, all gated by
a new `_require_admin` (same 401/403 shape as `_require_consented_resident`,
checking `session["role"] == "admin"` -- a role only ever assigned
server-side by `auth.is_admin`'s email allowlist, never client-supplied).

29 new tests (`tests/test_admin.py` + additions to `tests/test_batch.py`/
`tests/test_auth.py`), 295 passing. A `security-review` pass on the new
admin routes/table found no high-confidence issues (every route behind
`_require_admin`; the `role` on a session traces back only to the
server-side allowlist check, never a client-supplied value; parameterized
SQL throughout; every dynamic value in `admin.html` written through the
existing `esc()`-before-`innerHTML` pattern). Live-verified against a
running server with an isolated DB and, for the first time this session, a
now-valid `ANTHROPIC_API_KEY`: seeded 3 real residents, ran
`check_and_trigger_batch` for real (a genuine Opus-matched, Sonnet-negotiated,
grounded group with a real venue suggestion -- Rattlesnake Ledge, WA -- came
back), drove all three through `/api/my-match`'s pending -> waiting -> sealed
with real content, confirmed `/api/admin/neighborhoods` and its detail route
reflect that run's real progress/status/usage (visually checked in a
browser, not just curl), confirmed a non-admin resident session gets a clean
403 on every `/api/admin/*` route, exercised
`POST /api/admin/neighborhoods/{id}/trigger` for real against a second
neighborhood with only 2 residents and a threshold of 100 -- the override
correctly bypassed the threshold and ran a real pipeline call, which
correctly declined to form a group of 2 (H4) rather than shipping a bad one,
and confirmed all of the above survives a server restart.

**Post-Stage-6 fixes and tooling.** All 6 build stages above were done as of
commit `81de12e`. Since then, two separate efforts landed on `main` -- this
session's own follow-up fixes, and a second, independent Claude Code session
that opened and merged its own PR (`claude/ten-trails-alpha-sim-2jz01d`,
merged as PR #1, commit `4806775`) without this session's direct involvement.
Recording both here since neither was captured at the time:

*This session's fixes (live-testing-driven):*
- `join.html`'s "Continue with Google" button could be clicked through even
  while visually disabled (a disabled `<button>` inside an `<a>` lets clicks
  fall through to the anchor in most browsers) -- fixed to gate navigation in
  the click handler instead of relying on the anchor + disabled-button trick.
- `consent.html` never forwarded to `/onboarding` after agreeing (or on a
  repeat visit once already consented); `onboarding.html` never linked to
  `/my-match` once complete. Both now auto-advance.
- `_post_login_response` routed purely on session `role`, so an
  admin-allowlisted email signing in through a real `/join/<slug>` link got
  stuck on a placeholder page even though a real resident row existed for
  them. Now routes on whether a resident row exists instead.
- `master_claw._compatibility_hints` was unbounded -- harmless at demo scale
  (12 people) but the pairwise hint list can hit hundreds of lines at
  real-neighborhood scale, inflating the priciest input tokens on every one
  of the ~25-30 sequential match-forming calls a large batch needs. Capped to
  the 20 strongest pairs by signal strength (`MAX_HINT_PAIRS`).
- `Clawnly.command`'s dependency-freshness check only verified
  `fastapi`/`uvicorn`/`anthropic` importable, not `authlib`/`httpx` -- an
  existing venv predating the pilot's auth work would falsely pass and then
  crash on startup. Widened the check.
- New `src/dryrun.py`: drives AI-generated personas through the real pilot
  pipeline end to end for pre-launch validation (`chat` mode -- full
  simulated onboarding conversation; `bulk` mode -- skips the chat and seeds
  profiles directly, for testing matching quality/diversity at real scale
  without paying for hundreds of chat turns). Real API cost. Run twice this
  session: correctly refused an unsatisfiable 6-person pool, and produced a
  real sealed 3-person match with a grounded reason and a real venue.

*The independent session's PR (`4806775`), not yet cross-checked in depth by
this session beyond confirming the full test suite still passes (298) and
skimming each module's docstring -- treat as verified-by-a-different-session,
not by this one:*
- New `src/pilot_demo.py` -- a **free, offline** simulation of the real
  onboarding -> batch -> match -> reveal-gate cycle (scripted AI replies, zero
  cost), explicitly positioned as a companion to `dryrun.py` for sanity-
  checking the pilot's plumbing without spending money.
- New `src/pilot_visual_demo.py` -- same idea, but drives the real `app.py`
  server through an actual browser (Playwright, an added-only-for-this
  optional dependency) instead of a terminal transcript, to see what a
  resident actually clicks through. Outputs a screen recording + screenshots
  to a gitignored `pilot_visual_demo_output/`.
- New `GET /admin/login` (`web/admin-login.html`) -- a dedicated admin login
  page that never attaches a neighborhood, landing straight on `/admin`.
  Complements (does not replace) this session's resident-row-based routing
  fix above: logging in via `/join/<slug>` with an admin email still creates
  a resident row and lands on `/consent`, intentionally, so an admin can
  still experience the resident flow through their own account.
- Removed hardcoded "Seattle" from `persona_gen.py`'s generated-neighborhood
  field and from `master_claw.py`/`popup.py`'s match/venue prompts for real
  (non-simulated) neighborhoods -- real neighborhoods like Ten Trails aren't
  Seattle-based; the demo cast's Seattle theming is unaffected.
- `render.yaml`'s `clawnly-pilot` service moved off the free plan onto
  `starter` with a persistent disk mounted at `/var/data` (`CLAWNLY_DB_PATH`
  pointed there) -- Render's free tier has no persistent disk, so `db.py`'s
  SQLite file would have been silently wiped on every deploy/restart.

**Before doing new pilot work, reconcile: read the actual current
`src/app.py`, `src/pilot_demo.py`, and `src/web/admin-login.html` rather than
trusting this summary alone** -- two independently-written accounts of the
same stretch of work were only just merged together here.

**A third independent PR** (`black-diamond-100-sim`, merged as PR #2, commit
`dd72b32`) landed next, unrelated to the real pilot -- it scales up the
**original demo console** (`/`, the simulated cast), not the pilot:
- `persona_gen.build_demo_cast(count, theme)` -- instant, zero-API-call,
  schema-valid cast generation (up to `MAX_GEN_COUNT = 100` people) for Demo
  mode; `clamp_count`/`clamp_theme` bound and sanitize the inputs. Live mode
  still uses the real AI-based `generate_users` (same cap, but costs money).
  `POST /api/generate-cast` now takes `count`/`theme` and branches on mode.
- A real bug fix directly relevant to matching at scale: `MasterClaw.
  find_all_matches` had a hardcoded `max_groups=6` -- harmless at the
  12-person demo scale, but would have silently capped a 100-person pool at
  6 groups (~30 people considered, ~70 left unmatched even if more valid
  groups existed). Now scales with pool size (`len(remaining) // 3`, floored
  at 6) when `max_groups` isn't passed explicitly.
- `web/index.html` updated with count/theme controls for generating a larger
  cast in the browser -- this is the "Black Diamond" 100-person scenario
  referenced in the branch name, playable entirely for free.

None of this touches `auth.py`, `db.py`'s pilot tables, or any `/join`,
`/consent`, `/onboarding`, `/my-match`, or `/admin*` route -- it's additive
to the pre-pilot demo console only. 314 tests passing (up from 298) after
this merge, confirmed green.

**Given three independently-merged PRs have now landed on this repo without
this session's involvement, treat this ROADMAP as reliable only as of
`dd72b32` -- always `git fetch` and diff before assuming it's still current
(see the working-rhythm rule in `CLAUDE.md`).**

---

## Highest-priority items if picking up fresh work (not already covered above)

1. All 6 neighborhood-pilot build stages are done (see Milestones 4/9) --
   next is the actual launch: get the Google OAuth consent screen to
   production, a verified Resend sending domain, and invite the real Ten
   Trails cohort. A second automatic re-trigger mechanism (beyond Stage 6's
   manual override) is worth revisiting once real decline/dissolve volume
   exists to justify it -- see Stage 5's noted caveat in the stage-6 entry.
2. Milestone 2's real token/cost tracking, once pilot usage exists to make it
   worth building. Stage 6 added interim call-count-only usage visibility
   (`usage.py`); real dollar tracking is still this milestone, not rebuilt.
3. Milestone 3's geo/age hard constraints, needed before the pilot can safely
   scale past one neighborhood.
4. Milestone 8's feedback-cap fix -- cheap, and the risk it addresses is
   already live, not hypothetical. Its structured post-meetup feedback half
   was also left as a fast-follow to Stage 5's my-match.html, not folded in.
