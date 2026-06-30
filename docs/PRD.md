# Clawnly — Product Requirements Document

**Status:** v0.3 (Draft) · **Date:** 2026-06-20 · **Owner:** Idan Shaviner
**Related:** [SPEC.md](SPEC.md) — technical spec for Phase 1 (the matching PoC)

---

## 0. Definition — what "legit" matching means (change 2)

"Legit" is the word the whole product hinges on, so it is defined once here and used everywhere. A
match is **legit** when it is all four of:

1. **Non-random** — it measurably beats a random grouping on compatibility (the §6a baseline test).
2. **Constraint-respecting** — it never violates a **hard constraint** (group-size range, shared
   availability, valid membership — SPEC §6.0).
3. **Grounded** — every claim in its reasoning is **true to the user data**, with no fabricated
   facts (SPEC §6c).
4. **Appropriately selective** — it forms a group only when one genuinely fits, and **refuses** when
   none does.

A grouping that merely *sounds* plausible but fails any of these is **not** legit. Proving the
matcher hits all four on varied pools (§6a) is the entire purpose of Phase 1.

---

## 1. TL;DR

Clawnly fights loneliness by giving every person an AI agent — a **Claw** — that learns who they
are and finds them *their people*: small groups of compatible humans to meet in real life. A
**Master Claw** orchestrator reasons across everyone's Claws to form groups that genuinely fit, and
proposes a concrete meetup.

The hard, unproven question is **"is the matching legit?"** — does an AI actually form groups that
make sense, and can it show why? Everything else (data integrations, a real app, growth) is wasted
if the answer is no. So we prove the matching brain first (Phase 1 PoC), then connect real data.

---

## 2. Problem & opportunity

**Target segment (pinned, M2):** adults **24–35** — old enough to have lost the built-in social
scaffolding of school, young enough to expect to solve it with an app. Market, personas, and
geography below all refer to this band. (18–23 is a future segment, not the initial focus.)

**Problem.** Loneliness is widespread and rising, especially among adults 24–35. Existing tools
either optimize for romance (dating apps) or dump people into large, low-signal communities
(Meetup, Discord). Making *platonic* friends as an adult is high-friction: it takes repeated,
unstructured exposure that busy adult life rarely provides.

**Why now.**
- A wave of "strangers → IRL group meetup" apps has validated demand — **Timeleft** (dinners of
  ~6), **222** (personality-matched event invites), **Pie** (quiz → groups of 6). People *want*
  curated, low-pressure, in-person group experiences.
- But all of them match on a **static personality quiz + a clustering algorithm**. Matching is
  shallow and opaque — users can't see *why* they were grouped, and the signal is whatever a
  one-time quiz captured.
- **The gap:** nobody uses a per-user conversational agent that can be *interviewed* and can reason
  about fit in natural language, grounded in rich, evolving personal context. That is Clawnly's
  wedge — and it's newly feasible with current LLMs.

**Opportunity.** Be the first matchmaker whose matching is (a) **deep** (reasons over real, evolving
context, not a quiz) and (b) **legible** (explains why this group, and why not others) — building
trust that static-quiz competitors structurally can't.

---

## 3. Vision & strategy

**Vision.** Everyone has a Claw that quietly understands them and continuously connects them to a
few people they'll genuinely click with — turning the emerging AI agent ecosystem into an antidote
to loneliness.

**Strategy — earn trust in stages:**
1. **Prove the brain.** Show AI can form sensible, explainable groups from rich profiles. (PoC)
2. **Feed the brain real data.** Let Claws learn from connected sources (calendar, Google, social)
   so onboarding is effortless and matching improves over time.
3. **Close the loop.** Real meetups → feedback → better matching → retention and word of mouth.

**Sequencing principle:** *validate the brain before connecting the senses.* Data integration is
expensive and risky (privacy, trust); we only earn the right to it once matching is proven.

---

## 4. Target users

**Primary persona — "New-in-town Nora" (24–32).** Recently moved or life-stage-shifted (new job,
post-grad, breakup). Socially capable but lacks an existing circle; finds large meetups draining and
dating apps off-target. Wants a few real friends with low effort and low awkwardness.

**Secondary persona — "Stretched-thin Sam" (28–35).** Working professional whose social life shrank
around work. Time-poor, schedule-constrained; needs matching that respects real availability and
small-group preferences.

**Common needs:** low friction to start, genuine compatibility (not random), small/safe group
settings, a concrete plan (when/where), and trust that it's worth showing up.

---

## 5. Goals & non-goals

**Goals**
- G1 — Prove AI can form compatible groups with **visible, grounded reasoning** (Phase 1).
- G2 — Make onboarding effortless via **automatic learning** from connected data (Phase 2+).
- G3 — Produce meetups people **accept and show up to** (Phase 3+).
- G4 — Build **trust** through transparency (the "why this group") and safety.

**Non-goals**
- NG1 — Not a dating app. Platonic group matching only.
- NG2 — Not a large-community / feed product. Small, curated groups.
- NG3 — Phase 1 is **not** a user-facing app, has no real users, and stores no personal data.
- NG4 — Not building our own foundation model; we orchestrate Claude.

---

## 6. Success metrics

**Phase 1 (PoC) — "is it legit" (full protocol in §6a):**
| Metric | Target (pass bar) |
|---|---|
| Beats random baseline on rater "would-click" score | matcher avg ≥ random avg + **1.0** on a 1–5 scale, across **≥10 pools** |
| Hard-constraint violations (size, dup, invalid id) | **0** (any violation = fail) |
| Correct refusal on no-viable-group pools | declines to force a match in **100%** of "impossible" pools |
| Reasoning is grounded & defensible | rater agrees `reason`/`why_not` cite real facts in **≥80%** of groups |

**Phase 2+ (with real users) — quantitative loop (deferred, see SPEC §14). Targets are directional
v1 hypotheses, to be calibrated after first cohort:**
| Metric | Definition | Directional target |
|---|---|---|
| Match acceptance rate | % of proposed meetups users opt into | ≥ 40% |
| Show-up rate | % of accepted meetups attended | ≥ 70% |
| Post-meetup rating | "would meet these people again?" | ≥ 60% yes |
| Repeat rate | users requesting another match within 30d | ≥ 50% |
| Time-to-first-meetup | onboarding → first IRL meetup | ≤ 2 weeks |

*Owner:* product. *Instrumentation:* Phase-1 metrics via the eval harness (§6a); Phase-2 metrics via
in-app events + post-meetup survey.

### 6a. Phase-1 evaluation plan (the PoC's reason to exist)

The core hypothesis — *AI forms sensible, explainable groups, not random ones* — cannot be proven by
a single run on one easy pool. The PoC must therefore ship with an **evaluation harness** (SPEC §13):

- **Multiple, varied pools.** Run across **≥10 generated pools** (different seeds/compositions), not
  the one demo pool. One group from one pool is a demo, not evidence.
- **Deliberately hard cases.** Include pools with near-conflicts, incompatible schedules, clashing
  size preferences, and **"no good group exists"** pools. Easy pools prove nothing (addresses R2).
- **Random baseline.** For each pool, compare the matcher's group against a **randomly formed group**
  of the same size. *Beating random on rater score is the cleanest proof of "not random."*
- **Refusal as a positive result.** On impossible pools, the legit outcome is to **decline** (SPEC
  `group: []`). Forcing a bad match there is a failure; refusing is a pass.
- **Judging.** A rubric (1–5 "would these people actually click") applied **blind** (rater doesn't
  know which group is matcher vs. random) by ≥1 reviewer; constraint checks are automated.
- **Pass bar:** the §6 Phase-1 table is met in aggregate across the pools.

---

## 7. Product principles

1. **Legibility over magic.** Always show *why* a match was made. Trust is the product.
2. **Compatibility over volume.** A few right people beat many random ones.
3. **Respect stated preferences as constraints**, not suggestions (e.g. group size).
4. **Effort goes down over time.** Each connected data source should reduce what we ask the user.
5. **Safety is a feature, not a checkbox** — especially once strangers meet IRL.
6. **Privacy by consent.** Personal data is connected deliberately, used transparently, minimally.
7. **Inclusive by design.** The product serves people for whom socializing is *hard* — social
   anxiety, neurodiversity, accessibility needs. Matching, group sizes, and venue suggestions should
   accommodate this, not assume an extroverted default.

---

## 8. Functional requirements (by epic)

### Epic A — Claw (user agent) · *Phase 1*
- A1 Each user is represented by a Claw that embodies them and answers in first person.
- A2 In the PoC, Claws **invent** believable, distinct personas. (SPEC F2)
- A3 *(Phase 2)* Claws learn from connected real data instead of inventing.

### Epic B — Master Claw (matching) · *Phase 1, core*
> Scope note: Phase 1 forms **one** group per run (SPEC §3). "Groups" (plural) elsewhere in this
> doc refers to the product vision; multi-group / pool-partitioning is Phase 3+.
- B1 Interview every Claw about social goals, availability, and group energy. (SPEC F3)
- B2 Form a compatible group, **reason-first**, across personality, **availability overlap**,
    complementary interests, and size preference. (SPEC F3, §6) Availability (when free) is matched
    separately from occupation (life-stage) — change 1.
- B3 Output a structured result with **scores, a reason, and a why-not** for near-misses. (SPEC §3)
- B4 Enforce hard constraints in code (size), with repair/retry on violation. (SPEC §6)

### Epic C — Meetup proposal (popup) · *Phase 1*
- C1 Generate a concrete meetup: activity, specific venue, day/time, members, personal reason.
    (SPEC F4)
- C2 Proposal must be consistent with the matcher's reasoning and the group's stated availability.

### Epic D — Pipeline & presentation · *Phase 1*
- D1 Run interview → match → popup end-to-end with legible, staged output. (SPEC F5, §7)

### Epic E — Automatic learning · *Phase 2 (deferred)*
- E1 Connect **one lead data source** first (decision §14.4) with explicit consent — *not* all three
    at once. Calendar/Google/social beyond the lead source are **Phase 2b/3** (M3). This bounds
    Phase 2 and resolves the roadmap-vs-open-question contradiction.
- E2 Derive an evolving profile the Claw embodies, replacing the manual/invented profile.

### Epic F — Real meetups & feedback loop · *Phase 3 (deferred)*
- F1 Deliver proposals to real users; capture accept / attend / rate.
- F2 Feed outcomes back to improve future matching.

### Epic G — Trust & safety · *Phase 2/3 (deferred)*
- G1 Identity verification, reporting/blocking, moderation for IRL safety.

---

## 9. Key UX flows

**Phase 1 (console — the demo *is* the UX):** staged output where the **reasoning is visible** —
the per-dimension scorecard, the chosen group with its reason, and the why-not. Payoff is a readable
meetup card. (SPEC §7.)

**Phase 2+ (target app, indicative):**
1. **Effortless onboarding** — connect a source or two; Clawnly learns; minimal questions.
2. **The proposal** — a meetup card with *who, what, where, when,* and a clear **"why you four"**.
3. **Opt-in & coordinate** — accept, light pre-meetup chat / icebreaker.
4. **After** — quick rating that improves future matches.

---

## 10. Non-functional requirements (product-level)

- Reliability: pipeline completes even if individual Claws fail. (SPEC N3)
- Reproducibility: matching is stable and inspectable, tested by properties not byte-equality.
  (SPEC N1, §9)
- Scalability: architecture scales to dozens now; 50+ needs hierarchical matching (deferred).
  (SPEC N5, N7)
- Cost/latency: understood and bounded per run. (SPEC N6)
- Model strategy: strongest model on the reasoning-critical match step. (SPEC §2)

---

## 11. Privacy, trust & safety (gated to Phase 2+)

The moment real personal data and real strangers enter, these become first-class requirements
(currently **out of PoC scope**, owned here for the roadmap):
- **Consent & data handling** — explicit, revocable consent per source; minimal collection; clear
  retention; user-visible "what Clawnly knows about me."
- **Safety for IRL** — identity verification, reporting/blocking, moderation, public-venue defaults.
- **Transparency** — the "why" extends to "why we used this data."

---

## 12. Roadmap

| Phase | Goal | Scope | Exit criteria |
|---|---|---|---|
| **1 — Matching PoC** *(now)* | Prove matching is legit | SPEC.md: 12 simulated users, Claw, Master Claw, popup, CLI | Groups make sense + explainable + constraints honored |
| **2 — Real learning** | Effortless onboarding | **One** lead data-source connector (§14.4), consent, evolving profiles, privacy model | Real-data Claws meet Phase-2 quantitative targets (§6), not "as good as invented" |
| **2b — More sources** | Richer profiles | Remaining connectors (calendar/Google/social) | Each added source measurably lifts match acceptance |
| **3 — Real meetups** | Sensible groups become real friendships | User app, proposals, feedback loop, trust & safety | Acceptance ≥40%, show-up ≥70%, repeat ≥50% (§6) |

---

## 13. Risks & open questions

| # | Risk | Sev | Likelihood | Mitigation / open question |
|---|---|---|---|---|
| R1 | Matching may not feel legit | High | Med | Phase 1 eval harness vs. random baseline (§6a) is the de-risk |
| R2 | Simulated personas flatter the matcher | High | Med | §6a hard/adversarial pools + beat-random bar; *open:* real-difficulty representativeness |
| R3 | Privacy is the Phase-2 adoption gate | High | High | Lead with one minimal source (E1); *open:* MVP data set that still lifts matching |
| R4 | IRL safety incident | Critical | Low | Verification + moderation bar before any real meetup (§11); *open:* the exact bar |
| R5 | Scale economics (LLM cost/pool size) | Med | Med | Hierarchical matching at 50+ (SPEC N7); *open:* unit cost at scale |
| R6 | Incumbents add LLM matching | Med | Med | Real moat = the **feedback-loop data network effect** (Epic F) — outcome data compounds; legibility + speed are the near-term edge, not the long-term moat |

---

## 14. Business model (out of scope now, flagged deliberately)

Monetization is **not** being designed in Phases 1–2; noted here so its absence is a choice, not an
oversight. Likely candidates, consistent with the market (Timeleft/222/Pie): **subscription** for
ongoing matching and/or **event/venue economics** (partner venues, paid experiences). To be defined
once the matching + meetup loop shows retention (Phase 3).

## 15. Assumptions & dependencies

- **Anthropic API** availability, latency, rate limits, and cost are load-bearing; model choices and
  cost envelope are tracked in [SPEC.md](SPEC.md) §2/§8.
- Model behavior is **not byte-deterministic**; evaluation relies on properties + aggregate scores,
  not exact reproduction (SPEC §9).
- Phase 1 assumes **simulated** users are a *useful-but-imperfect* proxy for real ones (see R2) — the
  hard/adversarial pools in §6a exist to limit how much this assumption can flatter results.
- Phases 2+ assume users will **consent to connect at least one personal data source** — the central
  Phase-2 adoption bet (R3).

## 16. Open decisions for sign-off

1. Confirm Phase 1 success is **qualitative human judgment** ("makes sense + explainable"), with
   quantitative metrics deferred to Phase 2.
2. Confirm the **platonic-group-only, not dating** positioning (NG1).
3. Confirm **Washington DC** as the PoC/initial geography.
4. Prioritize the first **data source** for Phase 2 (calendar vs. Google vs. social) — biggest
   matching lift per privacy cost.
