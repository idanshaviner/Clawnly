# Clawnly — Matchmaker Prototype Spec

**Status:** v1.3 (PoC) · **Date:** 2026-06-20 · **Owner:** Idan Shaviner

> **Note — built beyond this spec.** This document describes the original CLI proof-of-concept.
> The project has since grown into an interactive **web app** (`src/app.py` + `src/web/index.html`).
> Beyond the original `interview → match → popup`, the live pipeline is
> **interview → match → real multi-agent negotiation → popup**, streamed to the browser. Added
> capabilities: chat with each persona, edit/AI-nudge traits, generate a fresh cast, ask the Master
> Claw *why* (`explain.py`), multi-group matching, a Fast/cheap mode, cost metering, and cast
> persistence. The core engine (`claw`, `master_claw`, constraint validator) is unchanged from §3–§6.

---

## 1. Vision & scope

Clawnly fights loneliness by using AI to find people "their people." Each user is represented
by a **Claw** — an AI agent that embodies them. A **Master Claw** orchestrator interviews every
Claw and forms compatible group meetups.

**End goal (not in this build):** Claws learn about a user automatically from connected data
sources (calendar, Google account, social media) — no manual quiz. AI then matches continuously.

**This build = proof-of-concept.** Claws *invent* their humans (12 simulated DC users). The one
job of this PoC is to validate that the **matching is legit** (defined below) — *before* connecting
real user data. "Validate the brain before connecting the senses."

**Definition — "legit" matching (change 2).** A match is *legit* when it is all four of:
1. **Non-random** — measurably beats a random grouping on compatibility (PRD §6a baseline);
2. **Constraint-respecting** — never violates a hard constraint (§6.0 H1–H4);
3. **Grounded** — every part of the reasoning is true to the input data, no fabrication (§6c);
4. **Appropriately selective** — forms a group only when one genuinely fits, and **refuses**
   (`group: []`) when none does.
A match that is merely plausible-sounding but fails any of these is **not** legit.

**Primary goal:** technical PoC.
**The "wow" to prove:** match quality & reasoning.
**Surface:** CLI / console.

---

## 2. Tech stack

- Python 3.11+
- Anthropic Python SDK (`anthropic`), async client
- `asyncio`
- API key from environment variable `ANTHROPIC_API_KEY`
- Models centralized in one config module (see §8), tiered by cost vs. importance:
  - Interview calls: `claude-haiku-4-5` — the cheapest model for the bulk (one per user); these
    are simple "answer as yourself" calls, so quality holds and cost drops
  - Free-style chat (`chat.py`): `claude-sonnet-4-6` — richer model for the interactive surface
  - Master Claw matching call: `claude-opus-4-8` — the reasoning-critical call; match quality is
    the PoC's #1 goal, so it gets the strongest model
  - Popup + negotiation propose/assess calls: `claude-sonnet-4-6`
  - In-character Claw reactions during negotiation: `claude-haiku-4-5` (cheap, many of them)

---

## 3. Architecture & data flow

```
USERS (list[dict])                              # users.py
   │
   ▼
Claw(user)  ── describe(question) -> str        # claw.py   (one Claw per user)
   │
   ▼
MasterClaw                                       # master_claw.py
   ├─ interview_claws() -> dict keyed by id
   │      { id: { "profile": {...}, "q1": str, "q2": str } }
   │
   └─ find_matches(interviews) -> dict
          {
            "group":   [id, ...],               # 3–5 ids (may be [] — see §6)
            "reason":  str,                      # feeds popup
            "scores":  {                         # group-level, integer 1–5 each (rubric in §6a)
                          "personality": int, "availability": int,
                          "interests": int, "size_fit": int
                       },
            "why_not": [ {id, reason}, ... ]     # top 2–3 near-misses only
          }
   │
   ▼  (main.py maps group ids -> full profile dicts)
generate_popup(matched_users: list[dict], match_reason: str) -> dict   # popup.py
   │
   ▼
main.py : interview -> match -> popup, printed with section headers
```

**Key contract decisions (resolve prior inconsistencies):**

- Interviews are **keyed by stable `id`**, not `name` (names may collide; must scale to dozens).
- `find_matches` returns a **structured object**, never a bare list of names — the reasoning is
  the product.
- `match_reason` **originates in `find_matches`** (`reason` field) and flows to the popup; the popup
  must not invent a divergent rationale.
- `main.py` performs the **id → profile dict** lookup between match and popup.
- The match call receives the **full profile of every user** (id, name, age, gender, hobbies,
  personality, occupation, availability, location, preferred_group_size) **alongside** the free-text
  interview answers — so it has the data for every axis it must reason on (personality, interests,
  size, availability), not just the constraint fields. (C2 fix.)

---

## 4. Data model

### 4.1 User (`USERS` in `users.py`)

Each user is a dict:

| field | type | notes |
|---|---|---|
| `id` | str | stable unique id, e.g. `"u01"` |
| `name` | str | display name |
| `age` | int | 24–35 (matches the PRD-pinned target segment) |
| `gender` | str | mixed across the set |
| `hobbies` | list[str] | each drawn from the six categories in `HOBBY_CATEGORIES` (see below) |
| `personality` | str | `"introverted"` / `"extroverted"` / `"mixed"` |
| `occupation` | str | life-stage: `"student"` / `"working professional"` / `"freelancer"` |
| `availability` | list[str] | when actually free; each from `AVAILABILITY_WINDOWS` (see below) |
| `location` | str | a Washington DC neighborhood |
| `bio` | str | first-person, natural, 2–3 sentences, sounds human |
| `preferred_group_size` | `[min, max]` or `"no preference"` | **range**, both inclusive, within 2–8 |

> **Decision (C4 fix):** `preferred_group_size` is a **range** `[min, max]` (or the string
> `"no preference"`), not a scalar. This removes the scalar-vs-range contradiction and makes the
> 3–5 default reconcilable (see §6 constraint rules).

> **Decision (C1 fix):** the range `[min, max]` may extend beyond the 3–5 default (up to 8). A user
> whose **minimum exceeds 5 cannot be hard-satisfied** in a 3–5 meetup; such users are **valid,
> deliberate `why_not` entries** with the reason "wants a larger group than this meetup supports."
> This keeps the data realistic and actively *showcases* the matcher's reasoning rather than hiding
> an unsatisfiable constraint.

**`HOBBY_CATEGORIES`** — a category→examples map kept in `users.py` so coverage is programmatically
verifiable (M3 fix). The six categories: `outdoor`, `creative`, `social`, `professional`, `fitness`,
`intellectual`. Every user's `hobbies` must map to known categories, and the 12-user set must cover
all six.

**`AVAILABILITY_WINDOWS`** — the closed set of time windows a user's `availability` is drawn from
(change 1: availability is distinct from `occupation`). A user lists one or more:
`weekday_daytime`, `weekday_evening`, `weekend_daytime`, `weekend_evening`. This is what makes
schedule **compatibility** computable — two users are time-compatible only if their `availability`
lists **share at least one window**. `occupation` is life-stage context only and is **not** used as a
proxy for availability.

### 4.2 Diversity requirements (12 users)

- Mix of male and female.
- Ages 24–35 (the PRD-pinned target segment).
- Hobbies collectively span all six categories above.
- Personality: at least some of each of the three types.
- Occupation: at least some of each of the three life-stages.
- Availability: varied across users — different windows, some with one window, some with several;
  the set must include users who **do** and **do not** share windows, so availability matching is
  actually exercised.
- `preferred_group_size` varies naturally — some small `[2,3]`, some larger `[5,8]`, some
  `"no preference"`.
- Each person reads as a distinct, real individual — not generic.

---

## 5. Functional requirements

### F1 — `users.py`
- Define `USERS` per §4.
- When run directly (`__main__`), print `USERS` as formatted JSON.
- Architecture scales to dozens of users: adding users = adding profiles only.

### F2 — `claw.py` — `Claw` class
- Constructor takes one user dict.
- `async describe(question: str) -> str`:
  - System prompt loads the user's **full profile** and instructs the Claw to speak in **first
    person** as that user; if AI-emulated (no real person), fully invent and embody the persona
    convincingly and consistently.
  - User message = `question`.
  - Model = Claw model from config; **moderate temperature** so personas read vivid and distinct
    (U3), not flattened.
  - The system prompt instructs answers to be **concise (2–4 sentences)** — bounds the context the
    single match call must hold (C3 mitigation) and controls cost.
- One class, one responsibility. Anthropic client is **injectable** for testing (see §9).

### F3 — `master_claw.py` — `MasterClaw` class
- Instantiates one `Claw` per user in `USERS`.
- `async interview_claws() -> dict`:
  - Asks each Claw the two fixed questions:
    1. "What kinds of social experiences is your user looking for right now?"
    2. "What is your user's availability like and what energy do they bring to group settings?"
  - Runs Claws **concurrently** via `asyncio.gather` with **per-Claw error isolation** — one Claw
    failing does not abort the run (failed Claw recorded with an error marker, excluded from match).
  - The two questions **may be batched into one call per Claw** (returning both answers) to halve
    interview cost/latency; `describe(question)` itself stays single-question.
  - Returns `{ id: { "profile": <profile dict>, "q1": str, "q2": str } }`.
- `async find_matches(interviews: dict) -> dict`:
  - Sends **all** interviews (prose **+ each user's full profile**, per §3) in a single Claude call.
  - Instruct the model to **reason first, then decide** (score candidates across the four
    dimensions before selecting), under the **grounding rules in §6c (change 4).**
  - Forms **one** meetup of **3–5** people by default.
  - Respects `preferred_group_size` per the constraint rules in §6.
  - Considers personality fit, **availability overlap** (shared `AVAILABILITY_WINDOWS`), and
    **complementary (not identical)** interests.
  - `why_not` holds the **top 2–3 near-misses only** (most defensible exclusions), not every
    unselected user.
  - If no valid 3–5 group can satisfy the hard constraints, returns `group: []` with a `reason`
    explaining why (see §6 "no viable group").
  - Returns the structured object in §3 (`group`, `reason`, `scores`, `why_not`).
  - Output via **structured/JSON-safe** mechanism; parsed and validated in code (see §6, §9).

### F4 — `popup.py` — `generate_popup`
- `async generate_popup(matched_users: list[dict], match_reason: str) -> dict`.
- Calls Claude with the matched users' profiles + `match_reason`.
- Returns a parsed dict with:
  - `event_name`, `activity`, `location` (specific DC venue or park),
    `time` (day + time of week), `matched_users` (list of names),
    `reason` (one sentence, specific and personal — **consistent with `match_reason`**, not generic).
- `time` should be **plausible given the group's stated availability** from the interviews; `reason`
  must not contradict the matcher's reasoning.

### F5 — `main.py`
- Runs the full pipeline: interview → match → popup.
- Maps matched `group` ids → full profile dicts before calling `generate_popup`.
- If `find_matches` returns `group: []`, prints the matcher's `reason` and **skips the popup**
  cleanly (no crash).
- Prints each stage with clear section headers (see §7).
- `asyncio.run(...)` at the bottom.

---

## 6. Constraint rules (matching correctness)

### 6.0 Hard constraints vs. soft preferences (change 5)

The single biggest source of differing interpretations. Stated explicitly:

**Hard constraints — must NEVER be violated. Enforced in code (§6 validator); a violating group is
rejected/repaired, never shipped:**
| # | Hard constraint |
|---|---|
| H1 | Every member's `preferred_group_size` range contains the final group size `n` (too-small **and** too-large both fail). `"no preference"` imposes no bound. |
| H2 | The group shares **≥1 common `AVAILABILITY_WINDOW`** — a meetup with no common time is impossible, so a group with empty availability intersection is invalid. |
| H3 | Every member id exists in `USERS`; no id appears twice. |
| H4 | Group size is **3–5** unless H1 legitimately forces otherwise (e.g. all members want `[2,3]`). |

**Soft preferences — optimization signals the matcher *weighs* and *trades off*. Never block a match;
they drive the `scores` and the choice between otherwise-valid groups:**
| # | Soft preference |
|---|---|
| S1 | Personality fit (complementary energy, not clashing). |
| S2 | Complementary-not-identical interests. |
| S3 | Occupation/life-stage diversity (context, lightly weighted). |
| S4 | Location proximity within DC. |
| S5 | *Strength* of availability overlap beyond the H2 minimum (more shared windows = better). |

**Selection rule:** a candidate set is valid only if it satisfies **all** hard constraints; among
valid sets, the matcher picks the one that best optimizes the soft preferences.

**Large-group preferers (C1):** a user whose `min > 5` cannot satisfy H1/H4 in a 3–5 meetup. They are
**correct exclusions**, listed in `why_not` as "wants a larger group than this meetup supports" — not
violations.

**No viable group:** if no set satisfies all hard constraints, `find_matches` returns `group: []`
with an explanatory `reason`; `main.py` skips the popup (F5). Refusing here is a **success** (PRD §6a).

### 6a. Score rubric (change 3 — what makes a 5 vs 3 vs 1)

`scores` are **group-level integers 1–5** per dimension. Anchors so engineers, the model, and
reviewers grade the same way:

| Dim | 5 (excellent) | 3 (workable) | 1 (poor) |
|---|---|---|---|
| `personality` | Complementary energy mix that lifts everyone; no one overwhelmed or sidelined | Mostly fine; mild risk (e.g. all-introvert quiet, or one dominant voice) | Likely clash (e.g. several high-energy extroverts around one calm introvert who wanted low-key) |
| `availability` | All members comfortably share ≥2 windows | Exactly one shared window; tighter to schedule | Only the bare H2 minimum, or borderline — meetup is hard to actually arrange |
| `interests` | Clear common thread **and** enough variety to stay interesting | Some overlap but either too same-y or too scattered | No meaningful shared thread; little to connect over |
| `size_fit` | Final size sits centrally within everyone's preferred range | Size is at the edge of ≥1 member's range | Would violate a member's range — **must not ship** (becomes an H1 repair, not a score of 1) |

The matcher must **populate `scores` from the actual chosen group**, not aspirationally. Low soft
scores are acceptable to ship (with honest reasoning); hard-constraint failures are not.

### 6b. Code-level validation (M4)

After parsing `find_matches` output, a validator asserts the **hard constraints** H1–H4, plus output
hygiene:
- H1: final group size within every member's range (too-small and too-large);
- H2: members' `availability` lists have non-empty intersection;
- H3: every id exists in `USERS`; no duplicates;
- H4: size is 3–5 unless H1 forces otherwise;
- `scores` are integers 1–5; `why_not` has at most 3 entries.
On violation: log and **repair/retry** rather than emit a bad group.

### 6c. Reasoning grounding / hallucination prevention (change 4)

The matcher's value is trust, so its reasoning must be **verifiably true to the inputs** — a
confident, fabricated reason is worse than a weak honest one. Requirements:

- **No invented facts.** Every claim in `reason` and `why_not` must be supported by data actually
  present in that user's profile or interview answers. The model must not assert hobbies, traits,
  availability, or preferences a user does not have.
- **Cite the basis.** Each claim must reference the specific user(s) by `name`/`id` and the specific
  attribute it rests on (e.g. "Maya — `availability` weekend_daytime; `personality` introverted"),
  so a reviewer can check it against the profile in one step.
- **No invented entities.** Only `id`s present in the input may appear in `group` or `why_not`
  (also enforced by H3).
- **Honest uncertainty.** If the evidence for a pairing is thin, the reasoning must say so and the
  relevant `score` must be low — the model may **not** inflate a score to justify a choice.
- **Prompt-level enforcement:** the system prompt states these rules explicitly and instructs the
  model to prefer "no viable group" (§6) over fabricating compatibility.
- **Check-level enforcement:** automated checks confirm every referenced `id` exists (H3) and that
  cited attribute values match the source profile; the eval harness (§13) has a human rater score
  "reasoning grounded in real facts" (PRD §6a, ≥80% bar). Spot-checks flag any claim not traceable
  to an input field.

---

## 7. UX requirements (the console is the product)

- `U1` Staged output with a clear header per phase: Interviews, Matching, Popup.
- `U2` **The reasoning is printed, not hidden** — show the per-dimension `scores`, the chosen
  group with `reason`, and the `why_not` for excluded strong candidates. This is the demo's payoff.
- `U3` Interview answers read as **distinct real people**.
- `U4` Popup rendered as a **readable card**, not raw JSON; `reason` reads personal.
- `U5` Show a top-line **compatibility read** for the group for at-a-glance credibility.

---

## 8. Non-functional requirements

- `N1` **Reproducible matching:** structured JSON output + the code-level validator make runs
  inspectable and re-runnable. (The match model, Opus 4.8, does not accept a `temperature`
  parameter — it was removed on that model family — so reproducibility comes from the structured
  contract and validation, not a temperature knob.) The Sonnet calls (Claw personas, popup,
  negotiation) use moderate temperature for vivid output.
- `N2` **Concurrency:** interviews run via `asyncio.gather`.
- `N3` **Resilience:** per-Claw error isolation; the pipeline completes even if some Claws fail.
- `N4` **Single config source:** model ids + client construction live in one module; key from
  `ANTHROPIC_API_KEY`.
- `N5` **Scalable structure:** pool size and group-size bounds are named constants/parameters, not
  magic numbers. Keying by `id` supports dozens of users.
- `N6` **Cost/latency awareness:** N users ⇒ **N** interview calls (the two questions are batched
  into one call per Claw, on Haiku — `Claw.interview_both`) + 1 match (Opus) + 1 negotiation + 1
  popup. For 12 users that's 15 calls, most on the cheapest model. A fallback splits into two calls
  only if a model omits the answer separator, so an interview is never lost.
- `N7` **Scale ceiling (honest limit):** the single `find_matches` call holds all interviews +
  profiles, so it has a context/quality ceiling. The 2–4-sentence answer cap (F2) keeps this safe
  well past a dozen users; true scale (50+) would need pre-filtering or hierarchical matching —
  **out of PoC scope, flagged for the PRD.**

---

## 9. Quality / testability (QA)

- **Mockable client:** `Claw` and `MasterClaw` accept an injected Anthropic client so the full
  pipeline can run against canned responses with **zero API calls**.
- **Acceptance criteria (testable):**
  1. `users.py` run directly prints valid JSON of exactly 12 users meeting all §4.2 diversity rules,
     including **all six `HOBBY_CATEGORIES` covered** (verifiable via the category map, M3).
  2. **All hard constraints hold (H1–H4, §6.0):** size within every member's range (too-small and
     too-large); members share ≥1 `AVAILABILITY_WINDOW` (H2); every id exists in `USERS` and no id
     appears twice (H3); size 3–5 unless H1 forces otherwise.
  3. `find_matches` output and `generate_popup` output both parse as valid JSON/dict; `scores` are
     integers 1–5; `why_not` ≤ 3 entries.
  4. `match_reason` is non-empty and the popup `reason` is consistent with it.
  5. The `group: []` (no-viable-group) path prints the reason and skips the popup without crashing.
  6. **Grounding (§6c):** every id cited in `reason`/`why_not` exists; spot-checked cited attribute
     values match the source profile (no fabricated facts).
- **Reproducibility (not determinism):** Claude is **not byte-deterministic**, and the match model
  (Opus 4.8) does not expose a `temperature` control anyway. Runs are kept stable and inspectable by
  the structured output contract + the validator. Tests assert **properties** (constraints hold,
  valid JSON, ranges respected) — never exact output equality.

---

## 10. Code style (hard rules)

- **No ternary operators.**
- **No enhanced for-loops** — use index-based or `while` loops where iteration is needed.
  - **Exception (decision):** list comprehensions are permitted **only** for `asyncio.gather`
    fan-out (e.g. building the awaitable list). Everywhere else, index/`while` loops.
- Simple, readable variable names.
- Short, lowercase inline comments.
- Reads naturally; not over-engineered. Each file does one thing only.

---

## 11. Open decisions (resolved in this version)

| # | Decision |
|---|---|
| D1 | `preferred_group_size` is a **range** `[min,max]` or `"no preference"` (not a scalar). |
| D2 | User's own size range is a **hard** constraint; the 3–5 target is a **soft** default that yields to it. |
| D3 | `find_matches` returns a **structured object** (group + reason + scores + why_not), not a name list. |
| D4 | `match_reason` originates in `find_matches` and flows to the popup. |
| D5 | Interviews keyed by **`id`**; match call gets **full profiles** + prose (C2). |
| D6 | List comprehensions allowed **only** for `asyncio.gather` fan-out. |
| D7 | Users wanting `min > 5` are valid **`why_not`** entries, not unsatisfiable bugs (C1). |
| D8 | `scores` are group-level **integers 1–5**; `why_not` capped at **3** entries (M1, M2). |
| D9 | Hobbies validated against a `HOBBY_CATEGORIES` map for testable coverage (M3). |
| D10 | Empty `group: []` is a defined outcome; `main.py` skips the popup (M4). |
| D11 | Match call uses **`claude-opus-4-8`** (strongest model on the reasoning-critical step). |
| D12 | Tests assert **properties**, not byte-equality — Claude isn't deterministic (M5). |
| D13 | `schedule` split into **`occupation`** (life-stage) + **`availability`** (windows). Availability, not occupation, drives schedule compatibility (change 1). |
| D14 | "Legit" is **defined** (PRD §0 / §6a): non-random, constraint-respecting, grounded, appropriately selective (change 2). |
| D15 | `scores` have an explicit **1/3/5 rubric** per dimension (§6a, change 3). |
| D16 | Matcher reasoning is governed by **grounding / anti-hallucination rules** (§6c, change 4). |
| D17 | **Hard constraints (H1–H4) vs soft preferences (S1–S5)** are explicitly separated (§6.0, change 5). H2 adds shared-availability as hard. |

---

## 12. Build order

1. `users.py` (12 users) — **stop for review.**
2. `claw.py` (+ `config.py`, `llm_io.py` support modules)
3. `master_claw.py`
4. `popup.py`
5. `main.py` — end-to-end run.
6. `eval.py` — evaluation harness (§13), after the core pipeline works.

### 12a. Extensions beyond the core PoC (added on request)

These were added after the core spec and are part of the maintained codebase:
- **`negotiation.py`** — a **real multi-round negotiation** between the Master Claw and the group:
  each round the Master Claw *proposes* an activity (Sonnet), every **real Claw reacts in character**
  (`Claw.react`, Haiku, concurrent), and the Master Claw *assesses* whether they're on board (Sonnet)
  — revising up to `max_rounds` until they agree. Returns the full `transcript` for display/replay.
  The live pipeline is **interview → match → negotiate → popup**; the agreed activity feeds the popup.
- **`chat.py`** — interactive free-style chat with any persona (adds `Claw.chat()` with history).
- **`persona_gen.py`** — generate the user cast with Claude instead of hardcoding it; validates the
  output against §4 and retries on schema violations.
- The persona voice lives in a single tunable `PERSONA_STYLE` block in `claw.py`.

All follow the same conventions as the core: Haiku for the cheap interview calls, Sonnet for chat /
popup / negotiation, Opus for the reasoning-critical match; JSON-only prompt + code-side
parse/validate; no `temperature`/prefill on Opus.

---

## 13. Evaluation harness (satisfies PRD §6a — proves "matching is legit")

A single group from one pool is a demo, not evidence. The PoC therefore includes a lightweight
harness (`eval.py`) that runs matching across many pools and scores it against a baseline. Built
**after** the core pipeline (see §12).

- **Pool generation.** Produce **≥10 user pools** beyond the demo set — varied personality,
  occupation, availability, and size-preference mixes. Reuses the same `USERS` schema (§4); pools may be
  hand-authored fixtures and/or generated. Each pool is a `list[dict]` of valid users.
- **Adversarial / "impossible" pools.** Include pools where no good group exists — clashing
  schedules, incompatible size preferences, everyone wanting `[2,3]`, etc. The correct result on
  these is `group: []` (§6).
- **Random baseline.** For each pool, also form a **random** group of the same size from eligible
  users, for head-to-head comparison.
- **Run & record.** For each pool, run `find_matches`, run the constraint validator (§6), and emit a
  record: pool id, matched group + reason + scores, the random group, and any violations.
- **Blind scoring output.** Emit matcher-vs-random groups in a **label-blinded** form so a human
  reviewer can rate each 1–5 ("would these people actually click") without knowing which is which.
- **Aggregate report** against the PRD §6 Phase-1 pass bars:
  - matcher avg rater score ≥ random avg **+ 1.0** across pools;
  - **zero** hard-constraint violations;
  - **100%** correct refusal (`group: []`) on impossible pools;
  - reasoning judged grounded in ≥80% of groups.
- **Cost note:** the harness multiplies API calls by pool count — run it deliberately, not on every
  invocation. Mockable client (§9) allows dry-runs with zero API cost.

---

## 14. Deferred to the PRD (out of PoC scope, do not lose)

These are owned by the next phase, once real personal data enters the picture:

1. **Privacy & consent** — calendar / Google / social ingestion is the product's largest risk
   surface; needs an explicit data-handling, consent, and retention model.
2. **Trust & safety** — real strangers meeting IRL implies identity verification, reporting/blocking,
   and content moderation. Non-negotiable before any real launch.
3. **Success metrics** — define how "matching is legit" is measured with real users (match
   acceptance rate, show-up rate, post-meetup rating). The PoC's qualitative scorecard becomes a
   quantitative feedback loop.
4. **Scale architecture** — replace the single-call matcher with pre-filtering / hierarchical
   matching for 50+ users (see N7).
