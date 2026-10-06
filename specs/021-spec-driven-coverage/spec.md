# Feature Specification: Spec-Driven Coverage Pursuit

**Feature Branch**: `021-spec-driven-coverage`
**Created**: 2026-05-19
**Status**: planned — Draft (design — not yet planned for a release)
**Input**: User audit of reference-vault-0.2.30 (2026-05-18) — sibling concern to
the code-bridge work captured in `specs/020-code-bridge/spec.md`. Together,
the two specs address the two halves of the "vault feels much smaller than
expected" feedback.

## Clarifications

### Session 2026-05-19 (drafted asynchronously while user tested 0.2.31)

This spec hasn't yet been through an interactive brainstorming pass with
the user. The proposed answers below are the agent's best-effort
**starting positions**; each is flagged as a `[PROPOSED]` decision that
the user should explicitly accept, revise, or override before this spec
moves to `plan.md`.

- **[PROPOSED] Q: New stage, or extend the existing scout?** → A new
  **gap-pursuit** pipeline stage that runs AFTER scout, BEFORE research-
  plan generation. Reasons: (a) parallels 020's "new separate stage"
  pattern — explicit contract, runs on its own cadence; (b) keeps
  scout's code-derived topic-proposal loop untouched (already debugged
  through 5 seam-bug releases); (c) lets gap-pursuit be opt-in via
  `settings.yaml::stages.gap_pursuit.enabled` until the user is happy
  with the behaviour.
- **[PROPOSED] Q: When does it run?** → AFTER scout (so the cycle's
  code-first topic floor is in place) but BEFORE the SG-002 diversity
  gate is evaluated (so gap-pursuit topics count toward the diversity
  requirement). Specifically: between scout's topic emission and the
  research-plan render.
- **[PROPOSED] Q: How does it find topics for empty categories?** →
  Per-category external research queries using the existing
  `agent_call.py` dispatch surface. The stage reads
  `_pipeline/coverage-targets.json`, identifies categories with
  `current < required`, and for each spawns a focused agent call with
  the prompt "given this category description and the existing vault
  shape, propose K topics whose primary sources are NOT the configured
  repos — prefer Tier-2 external docs, Confluence-style intent
  references, or canonical resources for the technology family." Per-
  call K is settable (default 3).
- **[PROPOSED] Q: Same consensus mechanism as 020?** → No. The
  consensus design in 020 is for "this repo is exhausted" verdicts
  where consensus prevents premature give-up. Here, the verdict is
  "what topics fill this gap?" which is fundamentally additive — a
  second agent disagreeing adds topics rather than removing them.
  Use single-agent emission per category; vault authors can bump to
  N=2 via settings (`stages.gap_pursuit.consensus.n`) for cross-
  validation if they want, but the framework default is N=1.
- **[PROPOSED] Q: Per-vault validators?** → Yes, parallels 020 for
  framework-wide consistency. `gap-pursuit.validators.yaml` with the
  same surface shape (declarative YAML + optional Python escape
  hatch). Vault authors typically use this to constrain which
  external source types are acceptable for each category (e.g.
  "concepts" should cite textbooks, not blog posts).
- **[PROPOSED] Q: Interaction with the `topic-propose` skill?** →
  `topic-propose` (the existing scope-bounded tangent proposer)
  remains untouched. `topic-propose` is BACKWARDS-looking ("given
  this cycle's notes, what tangents are worth chasing?"). Gap-pursuit
  is FORWARDS-looking ("given the spec's coverage targets, what's
  missing?"). They compose: topic-propose fills out the next cycle's
  scout pool from anchor notes; gap-pursuit fills it from coverage
  gaps. Both feed the same harvest stage.

### Background — the audit that motivated this spec

The user's reference-vault-0.2.30 trial-run (6 cycles, 3h 28m) produced ~68
notes against a coverage target of ~150. The audit of
`_pipeline/coverage-targets.json` found:

- **Code-derived categories** (services, flows, decisions, kafka) — at
  or near 100% of their required count. Scout consistently proposed
  topics in these buckets because every code-walk surfaced concrete
  entities (`UserService.java`, `payment.flow`).
- **External-only categories** (concepts, learning-modules, java-jvm,
  spring-features) — at **0% across all 6 cycles**. Scout listed them
  in the prompt's "Configured categories" section but emitted zero
  topics tagged with those category names. The SG-002 diversity gate
  fired warnings but allowed the cycle through (its requirement is
  `min(5, unfilled_coverage_categories)` distinct categories, which
  scout met by spreading across the OTHER 8 categories that DID fill).
- **Cost-per-useful-category-fill**: infinite for the empty 4. Even at
  cycle 6 with budget remaining, the scout did not attempt to fill them.

The scout's prompt already knows the categories. What it lacks is an
**explicit forcing function** to propose topics from spec gaps when
code-derived topics aren't producing balanced coverage. The current SG-002
diversity gate is a SOFT check (warns but doesn't halt) and only requires
DISTINCT category labels, not that each category actually advances toward
its required count.

This spec moves the gap-pursuit logic out of the scout prompt (where
it's been a passive instruction the agent ignores) and into a dedicated
stage with deterministic state and a structured prompt designed for the
specific task of "fill this empty category from external sources."

### What this spec is NOT

- It is NOT the code-bridge (spec 020). 020 makes the code-walk cheap so
  scout has token budget for gap-pursuit; 021 uses that freed budget
  productively. They are designed to ship together as the 0.3.0 release.
- It is NOT a replacement for the SG-002 diversity gate. The gate stays
  as the per-cycle safety net; gap-pursuit is the proactive driver. A
  cycle can still trip SG-002 (warning) even with gap-pursuit enabled
  if the agent emits low-quality category fills.
- It is NOT spec-validation enforcement. The spec validator
  (`scripts/validate_spec.py`) already errors on missing
  `coverage_targets`; this spec assumes that validation passes and
  acts on the validated, populated coverage state.
- It is NOT a replacement for `topic-propose`. See `[PROPOSED]`
  decision in Clarifications.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Empty categories fill from external sources (Priority: P1)

A researcher runs `research-framework generate` against a vault whose spec
has 12 coverage categories. Across 6 cycles, 8 categories fill from
code-derived topics, but 4 stay at 0% (the external-only ones from the
0.2.30 audit). With gap-pursuit enabled, cycle 7 detects the 4 empty
categories, spawns one focused agent call per category (4 calls), and
each emits 3 candidate topics. The 12 candidates feed into the cycle's
topic pool alongside scout's code-derived topics. By cycle 10, every
empty category has reached at least 30% of its required count.

**Why this priority**: This is the load-bearing change. The 0.2.30 audit
named coverage skew as a top-3 reason the vault "felt smaller than
expected." Without this, even shipping 020 leaves the underlying
asymmetry untouched.

**Independent Test**: Build a fake vault with 2 categories: one
code-derived (will fill from a stub-extractor) and one external-only.
Run 3 cycles with gap-pursuit disabled — observe external-only stays at
0%. Run 3 cycles with gap-pursuit enabled — observe external-only fills
to ≥ 30% by cycle 3.

**Acceptance Scenarios**:

1. **Given** `_pipeline/coverage-targets.json` shows 4 categories at
   `current < required`, **When** the gap-pursuit stage runs, **Then**
   each gap category receives exactly one focused agent call and emits
   between 1 and K topics tagged with the category name.
2. **Given** a category at `current >= required`, **When** gap-pursuit
   runs, **Then** the stage skips that category and logs "category X:
   filled, no pursuit needed".
3. **Given** all categories are filled, **When** gap-pursuit runs,
   **Then** the stage completes in under 100 ms with zero LLM calls.

---

### User Story 2 — Gap-pursuit topics integrate with the existing pipeline (Priority: P1)

The gap-pursuit topics produced for empty categories feed into the same
topic-pool that scout's code-derived topics use. The research-plan
narrator includes them in the cycle plan. The note-writer batches them
the same way as any other topic. The verifier validates the resulting
notes the same way. No new code paths downstream — gap-pursuit is
strictly an upstream addition.

**Why this priority**: The change is only useful if it ships through
the existing pipeline without seam bugs. P1 because the integration is
where the previous releases (0.2.20–0.2.27) lost the most blood.

**Independent Test**: With gap-pursuit emitting 12 topics across 4
categories, verify: (a) all 12 appear in the research-plan as a
distinct "Coverage pursuit" section; (b) the note-writer batches them
into the same `cycle-NNN-batch-NNN.json` artifacts as scout topics;
(c) `cycle-NNN-research.json` reports `notes_created` that include the
gap-pursuit-derived notes alongside scout-derived notes.

**Acceptance Scenarios**:

1. **Given** gap-pursuit emits topics for cycle N, **When** the
   research-plan render runs, **Then** the plan lists pursuit topics
   in a dedicated section distinguishable from scout topics (by
   prefix or by an explicit `source: "gap_pursuit"` marker).
2. **Given** the note-writer runs on a mix of scout and pursuit
   topics, **When** a pursuit topic produces a note, **Then** the
   note's frontmatter records `proposed_by: "gap_pursuit"` for
   downstream attribution and auditing.
3. **Given** the verifier runs on a gap-pursuit note, **When**
   verification completes, **Then** the verdict is recorded in
   `cycle-NNN-verifier.json` with no distinction from scout-derived
   verdicts (same schema, same gates).

---

### User Story 3 — Per-vault validators shape the topic emission (Priority: P2)

A vault author can drop a `gap-pursuit.validators.yaml` next to their
`research.spec.md` to declare which external source types are
acceptable per category. The validator runs on each emitted topic
before it joins the cycle's topic pool — topics whose proposed
sources fail validation are rejected with a clear error and the
stage spawns one retry call per rejected category. For cross-
category or cross-field rules, the author can add a
`gap-pursuit.validators.py` with `validate(topics, coverage_state)
-> list[str]`. Parallels the validator surface in 020.

**Why this priority**: Without per-vault shaping, gap-pursuit could
fill "concepts" with random blog posts when the vault author wants
canonical references. P2 because P1 works with the framework's
permissive default ("any web source allowed"); the validator is the
quality knob.

**Independent Test**: Author a `validators.yaml` requiring
`concepts` topics to cite sources from a known-good domain list.
Run gap-pursuit with a stub agent returning a topic with an
off-list source. The stage MUST reject the topic, log the error,
and retry with the rejection context. Run with a stub returning a
valid topic — accept and emit.

**Acceptance Scenarios**:

1. **Given** `gap-pursuit.validators.yaml` declares allowed source
   domains for "concepts", **When** the agent proposes a "concepts"
   topic with an off-list source, **Then** the topic is rejected,
   the error is logged with the violated rule, and the stage retries
   ONCE with the rejection context.
2. **Given** the retry also fails validation, **When** the stage
   completes, **Then** the category is marked "pursuit failed for
   cycle N" and the cycle continues without that gap-pursuit
   contribution; SG-002 may then fire on the next gate.
3. **Given** no validators are present, **When** the stage runs,
   **Then** topics pass through with only the framework's default
   schema validation (must have title, category, source).

---

### User Story 4 — Empty-category exhaustion is honest, not papered-over (Priority: P2)

For some vaults, certain coverage categories may not have meaningful
external research available (e.g. "internal-tooling-decisions" in a
private-company vault). After 3 consecutive cycles where gap-pursuit
fails to produce any acceptable topics for category X, the stage
records `pursuit_exhausted: true` for that category and stops trying
on subsequent cycles. The vault author sees this in the run-report
and can either widen the category's source list, lower the required
count, or mark it `required: false`.

**Why this priority**: Without this, gap-pursuit would burn budget
forever on impossible categories. P2 because P1 works for the common
case (categories CAN be filled but aren't); exhaustion handling is
the long-tail correctness.

**Independent Test**: Configure a category with no possible matches
(empty source list, restrictive validator). Run 4 cycles. Verify
cycles 1–3 attempt pursuit and fail; cycle 4 skips the category
entirely; the run-report includes "category X exhausted after 3
cycles".

**Acceptance Scenarios**:

1. **Given** gap-pursuit produces zero accepted topics for category
   X across cycles N, N+1, N+2, **When** cycle N+3 runs, **Then**
   the stage skips category X and logs "exhausted".
2. **Given** category X is marked exhausted, **When** the vault
   author edits the spec to widen the category's allowed sources,
   **Then** the next cycle resets the exhaustion counter and retries.
   (Mechanism: spec changes invalidate the cached exhaustion.)
3. **Given** category X is exhausted, **When** the cycle's
   run-report is written, **Then** it includes an explicit
   "exhausted categories" section flagging the vault author's
   attention.

---

### Edge Cases

- **`coverage-targets.json` missing or unparseable**: gap-pursuit
  skips the stage and logs a warning. The scout still runs (it
  reads the spec's `coverage_targets` directly). This handles
  cycle-0 races where the targets file isn't yet written.
- **All categories at `current == required` but spec has
  `target_extra: K`**: the spec's "extra" buffer is fillable but
  not enforced. Gap-pursuit treats `target_extra` as optional —
  pursues categories with `current < required` only.
- **Category has `note_type` that doesn't match any existing
  template**: same fallback as scout — log a warning and skip the
  category for this cycle. The migrator (013) is the right tool to
  add the missing template.
- **External research returns zero results for a category** (e.g.
  search engine down, all candidates blocked by validator): record
  the failure, increment the per-category exhaustion counter
  (US4), continue.
- **Budget cap reached mid-pursuit**: pursuit stops at the
  category-boundary (not mid-call). The cycle continues with whatever
  pursuit topics WERE produced. Partial pursuit is logged.
- **Spec is updated between cycles to add/remove categories**: the
  exhaustion counter is keyed by `(category_name, spec_hash)`. Spec
  edits implicitly reset the counter for affected categories.
- **Concurrent vaults** (multi-vault deployment, ROADMAP H3): each
  vault's gap-pursuit state is per-vault, lives under that vault's
  `_pipeline/`. No cross-vault contamination.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The framework MUST expose a new pipeline stage
  "gap-pursuit" that runs AFTER the scout stage and BEFORE
  research-plan generation in every cycle.
- **FR-002**: The gap-pursuit stage MUST be implemented as a
  subprocess invocation of a single script
  (`scripts/gap_pursuit.py`), matching the existing per-stage
  invocation pattern.
- **FR-003**: The stage MUST read `_pipeline/coverage-targets.json`
  to identify categories where `current < required`. Categories at
  or above `required` MUST be skipped.
- **FR-004**: For each gap category, the stage MUST spawn exactly
  one focused agent call (default N=1) via `agent_call.py`,
  receiving back a JSON list of K candidate topics (default K=3,
  configurable).
- **FR-005**: Each emitted topic MUST include: `title`,
  `coverage_category`, `proposed_filename`, `proposed_by:
  "gap_pursuit"`, and at least one `source_url` (NOT a `CT-…`
  code-topic id — gap-pursuit topics are external).
- **FR-006**: Emitted topics MUST flow into the same downstream
  pipeline as scout topics: research-plan render, note-writer
  batch, verifier, harvest.
- **FR-007**: The stage MUST write per-cycle output to
  `_pipeline/cycles/cycle-NNN-pursuit.json` with shape:
  `{cycle, timestamp, categories_pursued, topics_emitted,
   exhausted_categories}`.
- **FR-008**: A vault MAY provide `gap-pursuit.validators.yaml`
  next to `research.spec.md`. When present, the stage MUST
  evaluate each emitted topic against it before adding to the pool
  and MUST retry once on validation failure.
- **FR-009**: A vault MAY provide `gap-pursuit.validators.py`
  defining `validate(topics, coverage_state) -> list[str]`. When
  present, the stage MUST execute it after the YAML rules.
- **FR-010**: The stage MUST be opt-in via
  `settings.yaml::stages.gap_pursuit.enabled` (default `false` until
  0.3.0 ships; default flips to `true` on 0.3.0 via the migrator).
- **FR-011**: The stage MUST track per-category exhaustion state
  in `_pipeline/coverage-targets.json` under a new `pursuit_state`
  key, with `{consecutive_empty_cycles, last_attempt_cycle,
  exhausted_after_cycle}`. After 3 consecutive empty cycles,
  the category is marked exhausted and skipped until the spec
  changes (FR-013).
- **FR-012**: The stage MUST be tolerant of category-level failures
  — a single category failing pursuit MUST NOT halt the cycle. The
  failing category's exhaustion counter increments, a WARN is
  logged, and the cycle continues.
- **FR-013**: When the spec's `coverage_targets` block changes
  (detected via a hash stored alongside `pursuit_state`), the
  exhaustion counter MUST reset for affected categories.
- **FR-014**: Cost capture MUST go through `agent_call.py` so the
  cost-guardrail hard-cap policy (ROADMAP H1) applies to
  gap-pursuit calls.

### Key Entities *(include if feature involves data)*

- **PursuitTopic**: a single topic proposal emitted by gap-pursuit.
  Fields: `title`, `coverage_category`, `proposed_filename`,
  `proposed_by: "gap_pursuit"`, `source_urls` (list), `rationale`
  (short string describing why this fills the category),
  `pursued_in_cycle`.
- **PursuitState** (lives in `coverage-targets.json` under
  `pursuit_state`): per-category record of
  `{consecutive_empty_cycles, last_attempt_cycle,
  exhausted_after_cycle | null}`.
- **PursuitArtifact** (`_pipeline/cycles/cycle-NNN-pursuit.json`):
  per-cycle audit record of `{cycle, timestamp,
  categories_pursued, topics_emitted, exhausted_categories}`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the user's reference-vault baseline (12 categories, 6
  cycles), the 4 previously-empty categories (concepts,
  learning-modules, java-jvm, spring-features) MUST reach at least
  **30%** of their required count by cycle 6 when gap-pursuit is
  enabled. (Acceptable lower bound for shipping; aspirational
  target is 80%.)
- **SC-002**: When all categories are filled, the gap-pursuit
  stage MUST complete in under **100 ms** per cycle (the
  no-op path).
- **SC-003**: When `N` categories need pursuit, total stage
  duration MUST scale roughly linearly with `N` (concurrent calls
  are fine; the constraint is no quadratic blow-up in pre-call
  setup).
- **SC-004**: Zero cycles MUST abort due to gap-pursuit failures
  on the user's baseline. A category-level failure surfaces as
  WARN + exhaustion-counter increment, not a halt.
- **SC-005**: When a category exhausts (3 consecutive empty
  cycles), the run-report MUST explicitly surface it in a
  dedicated section, with a one-line suggestion ("widen sources,
  lower required count, or mark required: false").

## Assumptions

- The user's vaults will continue to have a manageable number of
  coverage categories (5–25). Designing for hundreds is out of
  scope.
- "External source" means anything not a configured repo — Tier-2
  docs, search results, Confluence pages, etc. The bridge in spec
  020 handles repo-derived signals; this spec handles everything
  else.
- The `agent_call.py` dispatch surface remains the single LLM entry
  point. Gap-pursuit calls go through it; cost capture and runtime
  selection are inherited.
- The 020 code-bridge ships in the same release. Gap-pursuit
  ASSUMES the scout has freed token budget from code-walk
  elimination; without 020, gap-pursuit still works but the
  realized topic yield will be lower.
- The note-writer can handle a topic with `proposed_by:
  "gap_pursuit"` without code changes — the field is metadata only.
  (Verify in plan.md; if false, the note-writer prompt needs a
  one-line passthrough.)
- The exhaustion counter (FR-011) is acceptable framework state to
  put in `coverage-targets.json`. Vault authors edit this file
  rarely; if they do, they understand the schema. Alternative is
  a separate `_pipeline/pursuit-state.json`, defer that decision
  to plan.md.

## Out of Scope (Explicit)

- The code-bridge (spec 020) — sibling feature that ships in the
  same release.
- Replacing the SG-002 diversity gate. Gap-pursuit is the proactive
  driver; SG-002 is the safety net. Both stay.
- Topic-propose (the existing scope-bounded tangent proposer).
  Topic-propose is BACKWARDS-looking from cycle N's notes;
  gap-pursuit is FORWARDS-looking from the spec. They compose.
- Multi-agent consensus for gap-pursuit emission. Default N=1;
  vault authors can opt in to N=2 via settings, but the framework
  doesn't ship a default consensus mechanism here (the
  brainstorming-decision rationale from 020 doesn't transfer —
  see Clarifications Q4).
- Spec validation enforcement of coverage targets — already handled
  by `scripts/validate_spec.py`.

## Open Questions — to resolve in `plan.md` before implementation

These are NOT clarifications (decisions are proposed above; user can
override) but implementation-time choices that the plan should
resolve:

1. **Where does `pursuit_state` live?** Inside
   `_pipeline/coverage-targets.json` (proposed) or in a separate
   `_pipeline/pursuit-state.json`. Trade-off: same-file means
   atomic state but tighter coupling.
2. **Per-category prompt structure.** The agent call needs a
   prompt that's opinionated about (a) what the category MEANS,
   (b) where external sources should come from, (c) the K-topic
   output schema. Should this prompt be one universal template
   parameterised by category, or per-category templates the vault
   author maintains? Universal-with-parameters is simpler; per-
   category gives finer control. Default proposal: universal,
   with a `category_brief` field in the spec letting the author
   inject category-specific context.
3. **Exhaustion-reset granularity.** When the spec changes,
   reset which counters? Just the affected categories (proposed)
   or all categories? Affected-only is correct but requires diff
   detection; "all" is simpler but loses exhaustion state on
   unrelated edits.
4. **Concurrency.** Pursue categories in parallel (default in
   020's consensus path) or serially? Parallel is faster but
   complicates budget enforcement. Default proposal: serial for
   simplicity; revisit if SC-003 (linearity goal) becomes a
   problem.
5. **Interaction with the `--regenerate-plan-only` CLI flag.**
   Should gap-pursuit run during a plan-only regeneration?
   Proposal: no — plan-only is for refreshing the plan with no
   new topics. Gap-pursuit topics are NEW topics and shouldn't
   appear without a real cycle.
