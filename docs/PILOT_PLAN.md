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

## Addendum (2026-09-01): brand pitch video review -- new confirmed decisions

The user shared a 36-second silent brand/pitch video (motion graphics, not app footage) for
introducing the product, set in a neighborhood called "Ten Trails." It depicts: an onboarding
chat ("You talk. Not a form. Not a profile."), no browsing/feed, a single named match with a
reason and a mutual yes/no accept where "she will not see your name unless she also says yes,"
a low-commitment first meetup ("fifteen minutes... you never have to do it again"), and a
structured post-meetup "did you meet / would you meet again" check. Reviewed against the existing
docs and confirmed with the user:

1. **Group matching stays.** The video's "one neighbor" framing is brand storytelling, not a spec
   change -- PRD.md's NG1 ("platonic **group** matching only") and the existing group-of-3-to-5
   engine (`master_claw.py`) are unchanged. Do not build 1:1 matching.
2. **New: a mutual-accept reveal gate.** Nothing like this exists in code today. Adapted from the
   video's 1:1 mechanic to the group model -- see "Match acceptance (mutual reveal gate)" below.
   This reshapes Stage 5.
3. **"Ten Trails" is the real target pilot neighborhood** (not a placeholder). Use it as the
   actual invite-link slug/name when the real pilot launches; existing test fixtures
   (`ballard`/`fremont`) are arbitrary and unaffected -- neighborhoods are already
   self-provisioned from whatever slug an invite link uses, so this is a launch-config choice,
   not a code change.
4. **Visual redesign, now.** The resident-facing pages should adopt the video's visual language --
   a serif display face, a warm cream/sage palette, calmer and less "SaaS admin panel" than the
   current plain style. Applies going forward to `join.html`/`consent.html`/`onboarding.html`
   (redesigned in this pass) and every resident-facing page built after (`my-match.html`,
   Stage 5). The admin console (`web/index.html`) is unaffected -- it's an internal tool, not
   resident-facing.

### Match acceptance (mutual reveal gate) -- design for the reshaped Stage 5

Adapting the video's "one neighbor, a reason, yes or no, both say yes to reveal" to an N-person
group (design call made by Claude, product direction confirmed by the user):

- New `db.py` table `match_acceptances`: one row per real (resident-sourced) member of a formed
  match -- `match_id`, `resident_id`, `status` (`pending`/`accepted`/`declined`), `created_at`,
  `responded_at`. Created (all `pending`) right after `batch.py` persists a match via the existing
  `db.save_match`, for every member whose id came from a resident (not the demo cast).
- `GET /api/my-match`: resolves the caller's resident id from the session (never a client-supplied
  id, same pattern as `_require_consented_resident`). While their acceptance is `pending`: returns
  the match's `reason` text and group size, WITHOUT the other members' names -- "N neighbors. A
  reason. Yes or no," mirroring the video. While `accepted` and waiting on others: a waiting
  state. Once every member has `accepted` (the match is "sealed"): full reveal -- other members'
  first names, and the existing `negotiation.py` -> `popup.py` flow (unmodified) runs for that
  match for the first time, so the returned payload includes the resulting meetup card once ready.
  If anyone `declined`: every other member's row also resolves to a "didn't come together" state.
- `POST /api/my-match/respond` (`{"match_id", "response": "accept"|"decline"}`): updates only the
  caller's own row (enforced via session, same IDOR-safe pattern already used throughout auth.py/
  app.py). On the accept that completes the set, seal the match and kick off negotiation/popup.
  On a decline, dissolve the match for everyone and release its resident members back into the
  eligible pool for the next batch trigger (new `db` helper -- do not make them redo onboarding).
- `web/my-match.html`: pending (reason + Accept/Decline), waiting, sealed (full reveal + meetup
  card -- date/time/place, "I'll be there" / "Need a different time," matching the video), and
  dissolved ("this one didn't come together -- you're still in the pool"). "Need a different
  time" can be a lightweight note-to-admin for a first pass, not live re-negotiation.
- The video's post-meetup "did you meet / would you meet again" screen maps directly onto the
  already-planned Milestone 8 (structured feedback, not yet built, currently global/unlinked to a
  match). Natural to build in the same pass as `my-match.html` since it's the same page's later
  state, but can also stay a separate fast-follow if scope needs trimming.

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
`web/admin.html` (the dashboard). Resident-facing pages (`join`/`consent`/`onboarding`/`my-match`)
adopt the brand video's visual language (serif display face, cream/sage palette) per the 2026-09-01
addendum above; `admin.html` stays plain/functional -- it's an internal tool, not resident-facing.

## Build sequence

This is a lot of surface area touching auth for the first time, so build and check in on it in
stages rather than one pass, the same way Milestone 1 went:

1. **Data model + auth backbone** -- new `db.py` tables, `auth.py` (Google OAuth + magic link +
   sessions), login/callback/logout routes, admin gating. No onboarding chat yet. **DONE.**
2. **Registration + consent** -- the invite-link landing page, neighborhood creation, consent
   capture. **DONE.**
3. **Onboarding chat + completeness tracking** -- the `simulated=False` Claw mode, persisted
   conversation, the slot-tracking completeness check, the turn cap. **DONE.** (Field
   coverage note: the five named slots gate `profile_complete_at`; the extra resident columns
   -- name/age/gender/location/occupation/bio -- are filled in best-effort by the same
   extraction call but never block completion, per your call when this stage was planned.)
4. **Batch trigger + real-pipeline wiring** -- `batch.py`, resident->profile-dict mapping, reusing
   `run_pipeline` and the existing persistence helpers.
5. **Match acceptance (mutual reveal gate) + resident-facing results page** -- reshaped by the
   2026-09-01 addendum above: `match_acceptances` table, `/api/my-match` + `/api/my-match/respond`,
   `web/my-match.html` (pending/waiting/sealed/dissolved states), negotiation/popup only runs once
   a match is sealed. Fold in Milestone 8's structured post-meetup feedback if scope allows.
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
