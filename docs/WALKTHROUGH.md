# How Clawnly actually works: a code walkthrough

Written 2026-09-23 against `main` @ `9151ac3` (314 tests passing). Every claim
cites `file:line` so you can open the code next to it. The "verified" findings
in section 7 were reproduced by running the real code, not only by reading it.

Sections 1-5 explain the code as it is. Section 6 maps Eitan's feedback onto
it. Section 7 lists real problems found along the way. Section 8 asks whether
this should be rewritten.

---

## 0. The one-minute version

1. Every person gets a **Claw**, an LLM prompted to "be" that person.
2. A **Master Claw** (the hub) asks every Claw two questions, then sends
   *everyone's* profile plus answers to one Opus call. That call picks one group of
   3-5 people. Code checks the group against hard rules; if it fails, it asks
   again (up to 3 times).
3. It removes that group from the pool and repeats until the model returns
   "no good group". That gives a greedy partition, one group at a time.
4. For each group, the Master Claw pitches an activity. Each Claw reacts in
   one or two sentences, and the Master Claw decides whether everyone is on
   board. Up to 4 rounds.
5. If they "agreed", one more call turns the activity into 2-3 concrete meetup
   options (venue, time).
6. In the real pilot, a person chats with their Claw until 5 profile "slots"
   are filled. When 100 people in a neighborhood are complete, steps 2-5 run
   once for all of them. Each person then sees a reason and says yes or no,
   and names are revealed only if everyone says yes.

---

## 1. What's in `src/`, and how much of it is the product

| Bucket | Files (lines) | Total |
|---|---|---|
| **Product logic** (the brain + the pilot flow) | `claw.py` 189, `master_claw.py` 546, `negotiation.py` 183, `popup.py` 123, `main.py` 202, `batch.py` 218, `onboarding.py` 264, `my_match.py` 149 | **~1,870** |
| **Plumbing** (storage, web, auth, config) | `db.py` 1027, `app.py` 778, `auth.py` 195, `config.py` 135, `admin.py` 94, `explain.py` 85, `llm_io.py` 33, `usage.py` 28 | ~2,380 |
| **Demo / simulation / eval tooling** | `persona_gen.py` 522, `demo.py` 452, `pilot_demo.py` 391, `eval.py` 383, `pilot_visual_demo.py` 346, `dryrun.py` 329, `users.py` 260 | ~2,680 |

Takeaway: the actual reasoning code is small, under 2,000 lines, and readable.
There's more simulation tooling than product. The complexity doesn't come
from the engine. It comes from two different worlds (an invented demo cast and
real residents) being forced through one engine by a thin adapter
(`batch.resident_to_profile`). Most of the real bugs are in that adapter
(section 7).

---

## 2. The shape: hub and spoke (it already is one)

```
                        ┌──────────────────────────┐
                        │   MASTER CLAW  (hub)     │
                        │  master_claw.py          │
                        │  negotiation.py          │
                        │  popup.py                │
                        └──┬───────┬────────┬──────┘
             interview Q's │       │        │  pitch -> react
             answers  ▲    │       │        │
                      │    ▼       ▼        ▼
                   ┌─────┐  ┌─────┐  ┌─────┐
                   │Claw │  │Claw │  │Claw │   ... one per person (spokes)
                   │Maya │  │Sam  │  │Dana │   claw.py
                   └─────┘  └─────┘  └─────┘
```

- Spokes **never talk to each other.** Every message goes through the hub.
- Spokes have **no memory**: each spoke call is a fresh single-turn prompt
  (`claw.py:131` `_ask`), apart from onboarding chat, which replays the transcript.
- Spokes can't propose anything. They only answer questions and react to pitches.
- The hub's "thinking" is never recorded (section 6.2).

---

## 3. Every AI call in the system

| # | Where | Model | Who is "speaking" | Output | What code verifies |
|---|---|---|---|---|---|
| 1 | `onboarding.py:227` -> `claw.py:176` `chat` | Sonnet | Resident's Claw, **real mode** (`simulated=False`) | free-text reply | nothing (it's conversation) |
| 2 | `onboarding.py:202` `_extract` | Haiku | silent reader of the transcript | JSON `{slots, fields}` | `_clean_fields` (`:151`) drops anything off the allowed word lists |
| 3 | `master_claw.py:95` -> `claw.py:146` `interview_both` | Haiku | every Claw, **always simulated mode** (see 7.1) | 2 answers split on `===` | nothing |
| 4 | `master_claw.py:318` `_call_match` | **Opus**, effort=medium | Master Claw | JSON `{group, reason, scores, why_not}` | H1-H4, ids, score shape, quality >= 3.5, up to 3 attempts |
| 5 | `negotiation.py:89` `_propose` | Sonnet | Master Claw | `{activity, pitch}` | falls back to "grab a coffee" if unparseable |
| 6 | `negotiation.py:138` -> `claw.py:165` `react` | Haiku | every group member's Claw (simulated) | 1-2 sentences | nothing |
| 7 | `negotiation.py:102` `_assess` | Sonnet | Master Claw | `{members[], agreed, concern}` | code forces `agreed=false` if any member is `on_board:false`, but see 7.4 |
| 8 | `popup.py:271` `generate_popup` | Sonnet | meetup planner | 2-3 `{event_name, activity, location, time, reason}` | nothing checks time is inside the shared windows |
| 9 | `explain.py:70` `explain_decision` | Sonnet | Master Claw "explaining itself" | free text | nothing (and it only sees the final `reason`, see 6.2) |
| 10 | `persona_gen.py` | Sonnet | persona inventor | demo profiles | `validate_users` |

Model tiers live in `config.py:16-41`. The quality bar is `MIN_MATCH_QUALITY = 3.5`
(`config.py:61`), and the pilot batch size is `MATCH_BATCH_THRESHOLD = 100` (`config.py:70`).

---

## 4. Flow A: one full matching run, step by step

Entry point: `run_pipeline(users, client, ...)` at `main.py:122`. The demo
console (`/api/run`, `/api/run-stream`) and the real pilot batch both call it.

### Step 1: build the agents (`master_claw.py:69-91`)
- One `Claw(user, client)` per profile (`:87`). Note that it passes no
  `simulated=` argument, so it defaults to `True`: *"there is no real person
  behind you, so fully invent and embody this character"* (`claw.py:18-27`).
- It keeps `users_by_id` and `claws_by_id` lookups for the validators.
- `feedback` = every thumbs-up/down ever recorded (demo console only; the pilot passes none).

### Step 2: interviews (`master_claw.py:95-118`)
- It asks all Claws concurrently with `asyncio.gather` (`:108`).
- Each Claw gets **one** Haiku call containing both questions (`claw.py:146`).
  The system prompt is `PERSONA_STYLE` plus the profile fields (`claw.py:73-95`). The
  answer is split on `===`, and if that fails it makes two separate calls (`:157-163`).
- If one Claw errors, it's recorded as `{"error": ...}` and that person is
  silently dropped from matching (`_candidate_ids`, `:306`).
- **What this step actually adds:** the answers are generated *from the same
  profile the matcher is about to see anyway*. They add no new facts. They add
  invented prose ("looking for: ...") that the matcher then reads as evidence (7.9).

### Step 3: partition the pool (`find_all_matches`, `master_claw.py:399-446`)
```
remaining = everyone interviewed OK
max_groups = max(6, len(remaining) // 3)
while groups < max_groups and len(remaining) >= 3:
    result = find_matches(remaining)      # one Opus decision (+ retries)
    if result is empty: STOP              # :423 -- one "no" ends the whole run
    remove result's members from remaining
return groups, unmatched = remaining
```
It's **greedy and sequential.** Group 1 gets the pick of the whole pool, group 2
the pick of what's left, and so on. Nothing ever reconsiders an earlier group.

### Step 3a: one match decision (`find_matches`, `master_claw.py:332-385`)
```
attempt 0..2:
    payload = profiles + interview answers + computed hints + past feedback + last error
    result  = Opus(payload)                                    -> JSON
    not JSON?                  -> "not valid JSON", retry
    empty group?               -> accept ("declined"), unless why_not cites a fake id
    _validate_group            -> H1 size in everyone's range, H2 a shared window,
                                  H3 real/unique ids, H4 size 3-5 (2 if someone forces it)
    _validate_why_not          -> every cited id must exist
    _validate_scores           -> exactly 4 dims, each 1-5
    any problems?              -> send problems back to Opus, retry
    avg(scores) < 3.5?         -> "only averages X, propose stronger or empty", retry
    else                       -> ship it
after 3 failures               -> empty group (never ship a bad one)
```
The hard constraints live in code (`:450-507`), not in the model. That's the
strongest part of the design and matches PRD §0's "legit" definition.

### Step 3b: what Opus actually sees (`_match_payload`, `:180-213`)
For each candidate: id, name, age, gender, personality, occupation,
neighborhood, availability, hobbies, preferred size, and the two invented
interview answers. Then:
- **Computed compatibility hints** (`:215-283`): exact shared-hobby pairs and
  pairs sharing 2+ availability windows, strongest 20 of each, labelled
  *"ground truth ... do not contradict them"*.
- **Lessons from past feedback** (`:285-304`): every rating ever, uncapped.
- **The last attempt's error message**, if this is a retry.

The system prompt (`:122-178`) says *"Reason FIRST, then choose"*. It also
says *"Return ONLY a JSON object"*, and no thinking/reasoning channel is
enabled on the call (`:323-329`). So the model has nowhere to put its
reasoning. The `reason` field is written after the choice, and nothing
records the thinking (6.2).

### Step 4: negotiation per group (`negotiation.py:114-183`)
```
proposal = Master.propose(group summary)                 # Sonnet
for round 1..4:
    reactions = every Claw.react(pitch)  (concurrently)  # Haiku, simulated personas
    verdict   = Master.assess(activity, reactions)       # Sonnet
    if any member on_board == false: agreed = false      # code override, :154-159
    if agreed or round 4: stop
    proposal  = Master.propose(summary + "concern was: ...")
```
Claws don't see each other's reactions and don't remember earlier rounds.
The whole transcript is kept and persisted.

### Step 5: meetup card (`popup.py:271-306`)
This only runs if `plan["agreed"]` (`main.py:180`). One Sonnet call returns 2-3 options
anchored on the agreed activity and the group's shared windows. A bad reply falls
back to a generic "casual hangout, this weekend" card (`popup.py:223`).

### Step 6: persist (`db.persist_run_result`, `db.py:401-428`)
Saves the interviews, each final match (group/reason/scores/why_not), each
negotiation transcript, each meetup, and the call-count usage. For real residents
(ids like `r17`), it also creates a `pending` row in `match_acceptances` for each member.

---

## 5. Flow B: the real neighborhood pilot, end to end

```
/join/<slug> ─► Google or magic-link login (auth.py) ─► /consent (db.record_consent)
      │
      ▼
/onboarding  ── each message: onboarding.take_turn (onboarding.py:218)
      │          1. Claw(simulated=False).chat(message, full history)   [Sonnet]
      │          2. save both messages
      │          3. _extract(full transcript) -> slots + fields          [Haiku]
      │             _clean_fields keeps only on-vocabulary values
      │          4. complete = all 5 slots true  OR  20 user turns
      │          5. if complete: fire-and-forget batch.check_and_trigger_batch
      ▼
batch.check_and_trigger_batch (batch.py:337)
      eligible = complete residents not in a live match   (db.py:772)
      if eligible < neighborhood.batch_threshold (100): return
      try_trigger_batch: UPDATE ... WHERE batch_triggered_at IS NULL  (one-shot CAS, db.py:623)
      profiles = resident_to_profile(each)                (batch.py:294)  <-- the adapter
      run_pipeline(profiles)  == Flow A, unchanged
      persist_run_result + pending acceptances
      ▼
/my-match  (my_match.get_state, my_match.py:353)
      not_yet_batched ─► pending (reason + group size) ─accept─► waiting ─all accept─► sealed
                                     │                                               (first names +
                                     └─decline─► dissolved (for everyone;             meetup card)
                                                  members become eligible again,
                                                  but only an admin "trigger now"
                                                  re-matches them: batch.py:391)
```

Things to notice:
- The **5 gating slots** (`onboarding.py:32`) are booleans that Haiku *judges*. They
  aren't derived from whether the structured fields actually got captured (7.2).
- The **negotiation and meetup run before any human says yes.** The humans
  only ever see the result of an agent conversation they weren't part of (6.1).
- Nothing the resident actually *said* reaches the matcher. Only the extracted
  fields do, after passing through `resident_to_profile` (7.1, 7.2).

---

## 6. Eitan's feedback, mapped to the code

> *"Technology is there to represent Agents as a Human. The tech is representing
> human through Agents. Emulation of people is available."*

**6.1 Representation.** The Claw *is* meant to be the human's representative.
- In the demo that's fine: the Claw plays an invented persona, which is honest.
- **In the real pilot, the representative isn't built from the human.** During
  interviews and negotiation, a real resident's Claw is the *simulated* persona
  (`master_claw.py:87` passes no `simulated=False`). It's told there is no real
  person and to invent. Its only source is an 11-field profile with defaults
  filled in (7.2), not the resident's own words. So when "Dana's Claw" tells the
  Master Claw it loves the hike plan, Haiku made that up.
- "Emulation of people is available": the pieces exist (`persona_gen.py`,
  `dryrun.py`, `simulated=True`), but they're used to *test* the product, not to
  *represent* the person inside it.

> *"We need to understand the orchestration and logs deeply. Thoughts of
> orchestrator, Activity Logs, everything happen behind the scene before a human
> gets even involved."*

**6.2 Observability: this is the biggest gap.** What's kept today versus what's thrown away:

| Kept (in SQLite) | Thrown away |
|---|---|
| Interview answers | The exact prompt sent on every call |
| The **final** group/reason/scores/why_not | Every **rejected** match attempt, and *why* it was rejected (validator problems, quality-gate misses) |
| Negotiation transcript (proposals, reactions, verdicts) | Raw model replies, including unparseable ones |
| Meetup card | The orchestrator's reasoning (none is requested or captured; see 4, Step 3b) |
| Call count by model per run | Tokens, cost, latency per call |
| Onboarding chat messages | Per-turn extraction output (only the latest merged profile survives) |
| | Batch failures (`print()` to stdout only, `batch.py:378`) |

`explain.py` ("ask the Master Claw why") doesn't read a log. It gets a summary
of the **final** groups and reasons (`explain.py:19`) and writes a plausible
story in the first person. It's after-the-fact storytelling, not a record.
So when Eitan asks for "thoughts of the orchestrator", the honest answer is
that the system can't show them today, because it never writes them down.

> *"Suggestions hit rate is 99.9%. Humans should not get involved."*

**6.3 Hit rate.**
- **No hit-rate metric exists anywhere.** The natural signal is already stored,
  `match_acceptances.status` (accepted/declined), but nothing aggregates it and
  nothing feeds it back. The pilot batch passes no feedback into the matcher
  (`batch.py:386`).
- `eval.py` measures something different: constraint violations and correct
  refusals on synthetic pools with **code-generated** interview answers
  (`eval.py:28`). It's a good legitimacy test, not a hit-rate measure.
- The *shape* already fits his goal: the human only sees one yes/no. But the
  thing they say yes to was negotiated by invented reactions (6.1), so a high
  hit rate would be luck, not design.

> *"Agent conversation needs deep understanding."*

**6.4 The agent conversation is thin.** The only agent-to-agent exchange is
negotiation: the hub pitches, each spoke reacts in 1-2 sentences, and the hub judges.
Spokes don't hear each other, don't remember, can't counter-propose, and in the
pilot don't know the human (6.1). If assess fails to parse twice, the code
declares the group **agreed** (7.4).

> *"Emulation of Hub and Spoke Architecture with deep seek."*

**6.5 Emulating it cheaply.** The architecture already *is* hub-and-spoke
(section 2). The most likely reading is: run the whole system on emulated people
with a cheap model (DeepSeek), at scale, and study the logs before any real
human is involved. What stands in the way:
- `config.py:118-135` hard-wires `AsyncAnthropic`. On the plus side, *every* call
  site takes an injectable `client` with a `messages.create(**kwargs)` shape, so an
  adapter to another provider is small.
- Without 6.2's logging, a big emulation produces outcomes you can't inspect.
- *Ask Eitan to confirm:* "deep seek" may mean the DeepSeek model, or it may
  just mean "seek deeply". Also, real resident data must not go to a
  third-party model without consent. That limits DeepSeek to emulation.

> *"Learn with Nathan with logs. Get the architecture. Emulate people and ask him questions."*

**6.6** Your own note makes the same point as 6.2: you can't learn from logs
that aren't written. Emulation plus a full event log plus a replay view is what
you'd bring to Nathan.

---

## 7. Verified problems found during this walkthrough

**7.1 Real residents are emulated, not represented. (Verified.)**
`MasterClaw.__init__` creates `Claw(user, client=...)` with `simulated=True`
by default (`master_claw.py:87`). I built a real-shaped resident, ran it through
`resident_to_profile` and `MasterClaw`, and the Claw's system prompt starts:
*"You ARE Dana ... You are an AI-emulated persona: there is no real person
behind you, so fully invent and embody this character."* The interview answers
and negotiation reactions for real people are therefore fiction.

**7.2 The profile adapter silently swaps in invented values, then calls them "ground truth". (Verified.)**
The extraction prompt asks for personality *"in their own terms"* and
occupation as free text (`onboarding.py:79-80`). But `resident_to_profile` only
accepts the exact words `introverted/extroverted/mixed` and `student/working
professional/freelancer` (`batch.py:229-230, 307-311`). Anything else becomes
`mixed` / `working professional`. Availability or hobbies that don't exactly
match the fixed word lists are dropped, and `batch.py:235-237` then fills in
`["reading","hiking"]` and `["weekday_evening","weekend_daytime"]`. Reproduced:

```
said:     personality "quiet, recharges alone"  occupation "nurse on night shifts"
          availability ["weekends"]              hobbies ["board games","Settlers of Catan"]
matcher:  personality "mixed"                   occupation "working professional"
          availability [weekday_evening, weekend_daytime]   hobbies ["board games"]
hint:     "Dana & Leo: 2 shared windows -- weekday_evening, weekend_daytime"
          (labelled "ground truth ... do not contradict")
```

That's a night-shift nurse matched as free on weekday evenings, with the hard
constraint H2 checked against availability she never gave. Everyone who got
the default hobbies also shows up as an "EXACT shared hobby" pair. The demos
don't catch any of this because their scripted extraction returns the exact
allowed words (`pilot_demo.py:42-89`). Completeness is judged by Haiku's slot
booleans, not by whether the fields survived validation.

**7.3 The "blind" pending screen leaks names. (Verified by reading.)** The pending
state returns `match["reason"]` (`my_match.py:371-374`). The matcher is told to
write that reason *"citing names"*, e.g. *"Maya & Aisha both do puzzles"*
(`master_claw.py:163-171`). The tests pass only because their fixture reasons
contain no names (`tests/test_my_match.py:27`).

**7.4 An unreadable verdict counts as agreement.** If `_assess` can't parse JSON
twice, it returns `{"agreed": True}` (`negotiation.py:110`). A missing `agreed` key
also defaults to `True` (`:151`). Either way, a meetup can ship without real agreement.

**7.5 The meetup time is never checked against availability** (known; ROADMAP M7).

**7.6 Greedy partitioning costs a lot at pilot scale. (Measured with the offline demo client.)**

| people | groups | total calls | Opus calls (sequential) | ~Opus input tokens |
|---|---|---|---|---|
| 12 | 2 | 27 | 3 | ~7k |
| 100 | 22 | 255 | 23 | **~277k** |

The Opus calls run one after another, and each carries the whole remaining pool.
That's with scripted one-line interview answers and negotiation always agreeing in
round 1, so real runs will be larger. Early groups take the strongest people, and a
single "empty" reply ends the run for everyone left (`master_claw.py:423`).

**7.7 The pilot has no learning loop.** Accept/decline is stored but never
used, and no feedback is passed into pilot runs.

**7.8 The fire-and-forget task isn't referenced** (`onboarding.py:258`). Python can
garbage-collect an unreferenced pending task. It's minor, but it sits on the only
automatic batch trigger.

**7.9 The interview step adds cost without adding information.** In both modes the answers
are generated from the same profile the matcher already receives.

---

## 8. Is it too complex? Should we rewrite?

**The code isn't too complex.** The engine is ~1,900 readable, well-tested
lines. The *design* has three structural gaps, and patching them one at a time
won't close them:

1. The Claw doesn't represent the human (7.1, 7.2). That's the core of
   Eitan's first point, and it's in the middle of the flow, not at the edges.
2. Nothing is observable (6.2), so you can't learn, debug, or show "thoughts".
3. Matching is a greedy series of big LLM calls (7.6). That's fine at 12 people
   and costly and order-dependent at 100.

**Recommendation: rewrite the pilot's core, not the whole app.** With 0
customers this is the cheapest moment. Keep `auth.py`, the session/consent
tables, the reveal-gate state machine and UI, and the hard-constraint
validators. They're sound. Rebuild the middle in this order:

1. **Event log first.** Add one `events` table: run, step, actor (hub/spoke/code),
   kind, prompt, raw reply, parsed result, validator verdict, tokens, milliseconds.
   Every `messages.create` goes through one wrapper (an extension of
   `usage.CountingClient`), so tracing is automatic. Add an admin "replay a run"
   view. This is Eitan's #2, and it makes everything after it measurable.
2. **A Claw that is the person.** Store the resident's own words (the transcript)
   plus a Claw-written dossier where each claim cites the message it came from.
   Interviews and reactions answer from that with `simulated=False`, and
   "I don't know, I'd have to ask them" is an allowed answer.
3. **No silent defaults.** Keep free text and the normalized value side by side.
   A field that fails validation is asked about again in onboarding, never invented.
4. **Code proposes, the LLM judges.** Deterministic code builds candidate groups
   that already satisfy the hard constraints and ranks them by shared
   hobbies/windows. Opus then judges a *shortlist* with small prompts, instead of
   partitioning 100 people one greedy call at a time.
5. **Hit rate as a first-class number.** Accept rate per run (show-up rate
   later), computed from `match_acceptances` and fed back into matching.
6. **Emulation mode = the same code with emulated humans** (persona Claws also
   answer the reveal gate), with a pluggable cheap model. That's Eitan's
   hub-and-spoke emulation: measure simulated hit rate and read the logs
   before a real person is involved.

**Decisions only you can make:**
- The scope of the rewrite: this pilot core only (recommended), or the whole app.
- Whether a non-Anthropic model (DeepSeek) is acceptable, and whether only for
  emulated people (recommended) or also for real resident data.
- What "hit rate" means for the business: accept rate, show-up rate, or
  "would meet again". Each one changes what the agents optimize for.
