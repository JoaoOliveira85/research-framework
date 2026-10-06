---
spec_number: 055
title: Source Credibility Model (Contextual Tiering)
status: SHIPPED 0.10.0 (PR #112, 2026-06-04) — 4-level ordinal enum, per-citation, COI-cap, 053-role topic-scope, declared-in-frontmatter; verifier `IX-credibility-*` shape rules; `tier2_source_ratio` metric.
priority: medium
priority_reason: |
  v1.0.0-rc1 Wave 2 / 0.10.0. Created 2026-06-03 when spec 030's
  `tier2_source_ratio` metric was dropped from v3 — it needs a real source-
  credibility model, which does not exist. The naive static per-module
  "Tier-1/Tier-2" ranking (only prose in ROADMAP) is conceptually wrong; this
  spec establishes a defensible, consistent credibility model. Not run-blocking
  for Wave 1, but the user wants it "properly done."
created: 2026-06-03
source_input: |
  User direction 2026-06-03 during 030's clarify: "hackernews can't be tier 2
  because some user might be more credible than another. A research paper written
  by OpenAI saying how GPT is amazing is also not very authoritative due to
  conflict of interest. On the other hand just because someone is an industry
  leader on a field (highly authoritative) they might be out of place talking
  about some other topic. So the concept has a lot more nuance than this and we
  have to establish guidelines and how to draw a line on what a tier is
  consistently."
---

**Status:** shipped(2026-06-04, PR #112) — SHIPPED 0.10.0 (PR #112, 2026-06-04). Contextual 4-level credibility enum, COI cap,
053-role off-field downgrade, verifier shape rules, `tier2_source_ratio` metric.

# Feature Specification: Source Credibility Model (Contextual Tiering)

**Feature Branch**: `055-source-credibility-model`

## Problem

The framework needs a **consistent, defensible way to assess how credible /
authoritative a source is for a given claim** — a "tier" or weight. Spec 030
wanted a `tier2_source_ratio` quality metric ("are lower-tier sources displacing
higher-tier ones?") but had nowhere to get a source's tier: the only "tiers" that
exist are a **prose Tier-1/Tier-2 list of modules** in `docs/ROADMAP.md`, which is
**conceptually wrong** as a credibility signal.

Credibility is **not a static per-module label**. Three concrete failures of the
naive model (user, 2026-06-03):

1. **Per-instance, not per-module.** "HackerNews = Tier 2" is wrong — one HN
   commenter may be a domain expert, another a random opinion. The *source
   instance / author* matters, not the platform.
2. **Conflict-of-interest-aware.** A peer-reviewed paper authored by OpenAI
   concluding "GPT is amazing" is **low**-authority *on that claim* despite being
   a "research paper" — the author has a stake in the conclusion.
3. **Topic-scoped.** An industry leader who is highly authoritative *in their
   field* is **out of place** (low authority) commenting on an unrelated topic.

So credibility is **contextual**: a function of `(source instance, author,
claim, topic, conflict-of-interest)` — not a constant. This spec's job is to
establish **how to draw that line consistently** and encode it so gates/metrics
can use it without per-case hand-waving.

## Relationship to spec 053 (Source Authority)

053 established **claim-type-scoped AUTHORITY**: a claim of type T must be
anchored by a source whose `role` (behaviour / intent / domain) is authoritative
for T, with `priority` breaking ties *within* a role. 053 deliberately treats
authority as a **static, author-declared** property (no runtime LLM judgement —
deterministic gates). It assigns `role`/`priority` to `data_sources[]` **at spec
time** and resolves a citation to its owning source via spec-020 `source_id`
(`citation → source_id → owning data_source → role`).

This spec adds the **credibility / quality dimension that 053 left flat**: *given*
a source is the right role for a claim, *how much do we trust this particular
source instance, by this particular author, for this particular claim?* It is the
nuance layer **on top of** 053's role/priority axis.

**Non-negotiable inherited from 053** (decisions #4, #5): gates stay
**deterministic**; any judgement happens at **authoring/research time** and is
**recorded as data**; runtime gates and metrics read only the recorded data and
NEVER re-judge. Whatever shape CL-1..CL-6 choose, this boundary holds.

```
053 axis (WHO may anchor):   role ∈ {behaviour, intent, domain} + priority (within-role tiebreak)
055 axis (HOW MUCH to trust): credibility level, per-citation, contextual (author/COI/topic)
                              ── orthogonal; 055 never overrides 053's role gate, it weights within it
```

## Clarifications

### Session 2026-06-03 (CL-1..CL-6 locked — the model shape)

All six adopted the 053-consistent recommendation. The resulting model:

- **CL-1 — Scale.** A **4-level ordinal enum**: `primary > corroborated >
  commentary > unvetted`. Ordinal so 030 can compute a ratio; enum (not free
  score) so it is declarable and deterministic (mirrors 053's `role` enum).
  Definitions in `contracts/credibility-model.contract.md`.
- **CL-2 — Granularity.** **Per-citation**, with an optional per-source
  `default_credibility` (declared on the `data_sources[]` entry / module
  `sources.yaml`) that the author overrides per instance. The effective input is
  `citation value → else source default → else FAIL` (no silent magic default).
- **CL-3 — Conflict-of-interest.** A **declared `coi` signal on the citation**
  that **caps the effective level at `commentary`** (COI-tainted sources can never
  be `primary`/`corroborated`). Author-declared at note time with rationale.
- **CL-4 — Topic-scoping.** **Reuse 053's `note_type → authoritative role`.**
  Off-field = the citation's source `role` is NOT the authoritative role for the
  note's note_type ⇒ **one-step ordinal downgrade** (floored at `unvetted`). No
  new per-topic config; pure function of recorded data.
- **CL-5 — Declarative vs computed.** **Declared** by the authoring agent
  (note-writer) at note time, recorded as frozen data with a short rationale. The
  only fully 053-consistent / Principle-IV-safe option — judgement lives at
  authoring time, never at gate time.
- **CL-6 — Storage + validator.** **Per-citation note frontmatter** (beside the
  Principle IX Tier-2 citation): each Tier-2 `sources[]` entry gains
  `credibility` (+ optional `coi`, `credibility_rationale`). **Note-writer writes;
  verifier shape-validates** (presence + valid enum + well-formed COI — never a
  re-judgement of the *value*); 030's calculator + 048 v2's ledger **read** it.

**Derived resolution function** (deterministic; the single rule every consumer
uses — full spec in the contract):

```
declared   = citation.credibility  OR  owning_source.default_credibility  OR  FAIL
after_coi  = cap_to('commentary', declared)        if citation.coi   else declared
effective  = downgrade_one_step(after_coi)         if off_field(...)  else after_coi
# off_field(citation, note) := citation.source.role != note.note_type.authoritative_role
```

`tier2_source_ratio` (spec 030) = `count(effective ∈ {commentary, unvetted}) /
count(all Tier-2 citations in the cycle)`. The "tier-2 boundary" (below
`corroborated`) is documented in the contract; 030 confirms it at implementation.

- **Spec 030** — the deferred `tier2_source_ratio` quality metric. 030 ships 3
  `source_quality` metrics today and will add the 4th once 055 defines a level a
  calculator can read deterministically. **This is the primary driver.**
- **Spec 048 v2** — the source-consideration ledger can annotate `USED` sources
  with their recorded credibility level (a diagnosability enrichment).
- **Spec 053** — within-role `priority` tie-breaking / weighting MAY later consult
  credibility (a v1.1+ consideration, not v1 of 055).

## User Scenarios & Testing *(mandatory)*

> The gates/metrics that consume the model ARE the tests. Per 053's pattern,
> the credibility datum is **declared at authoring time** and **read
> deterministically** downstream — so every story below has a deterministic,
> LLM-free verification (the authoring agent's judgement is fixture input, never
> exercised at test time).

### User Story 1 — A note records a credibility level per citation (Priority: P1, the data-production path)

When a note is authored, each Tier-2 citation (per Principle IX) carries a
**recorded credibility level** chosen by the authoring agent at write time and
checked by the verifier. The level is frozen frontmatter data, not recomputed.

**Why P1**: nothing downstream (030's metric, 048 v2's annotation) can exist
until the level is *produced and stored* on the note. This is the foundation.

**Independent Test**: a fixture note with declared citation credibility records
parses; the verifier passes a well-formed record and FAILs a malformed/missing
one — deterministically, with no agent call at gate time.

### User Story 2 — `tier2_source_ratio` computes deterministically from recorded levels (Priority: P1, the motivating consumer)

Spec 030's calculator reads the recorded levels across a cycle's notes and emits
`tier2_source_ratio` (fraction of consulted sources at/below the "lower-authority"
boundary) as a byte-deterministic float, with a baseline + regression threshold.

**Why P1**: this is the metric whose absence created spec 055.

**Independent Test**: given a fixed set of fixture notes with known levels, the
metric returns the same float every run; flipping one citation from primary →
commentary moves the ratio in the expected direction.

### User Story 3 — Conflict-of-interest caps credibility (Priority: P2, the COI detector)

The "OpenAI paper praising GPT" case: a citation declared with a COI relationship
to the claim subject is **capped** below the level its source-type alone would
earn — recorded at authoring time, read deterministically.

**Independent Test**: a fixture citation with `coi` declared resolves to a capped
level even though its source role/type would otherwise rank higher; the cap is a
pure function of the recorded fields.

### User Story 4 — Off-field authority is downgraded (Priority: P2, topic-scoping)

The "industry leader off-topic" case: an author authoritative for one claim-type
is recorded at a lower level when cited for a claim-type outside their field.

**Independent Test**: two fixture citations from the same author against
different claim-types resolve to different levels per the recorded topic-scope
signal — deterministically.

### User Story 5 — Ledger annotates USED sources with credibility (Priority: P3, diagnosability)

Spec 048 v2's source-consideration ledger shows, for each `USED` source, the
recorded credibility level, so a reviewer can see *not just that a source was
used, but how much it was trusted*.

**Independent Test**: the ledger row for a `USED` source carries the level joined
from the note frontmatter; absence degrades to "unannotated", never an error.

## Requirements *(mandatory)*

> CL-1..CL-6 are **locked** (see Clarifications); the FRs below are resolved.
> Authoritative shapes live in `contracts/credibility-model.contract.md`.

### The credibility datum — FR-001..003

- **FR-001 (CL-1 + CL-2 resolved)**: The framework MUST define the credibility
  level as a **4-value ordinal enum** — `primary > corroborated > commentary >
  unvetted` — assigned **per-citation**. Each value has a documented definition
  (FR-009) precise enough that two authors assign the same citation the same
  level. A `data_sources[]` entry / module `sources.yaml` MAY declare a
  `default_credibility` (one of the four) used when a citation omits an explicit
  value; if neither an explicit value nor a default exists, validation **FAILs**
  (no silent default).
- **FR-002 (CL-5 + CL-6 resolved)**: The level MUST be **declared by the
  authoring agent at note time and recorded as frozen frontmatter data**; no gate
  or metric re-derives it via LLM judgement at evaluation time (053 decision
  #4/#5, inherited and non-negotiable). Storage = the note's Tier-2 `sources[]`
  frontmatter entries, each gaining `credibility` (+ optional `coi`,
  `credibility_rationale`). The **note-writer writes** these; the **verifier
  shape-validates** them (presence + valid enum + well-formed COI), never
  re-judging the value; 030's calculator and 048 v2's ledger **read** them.
- **FR-003**: The recorded datum MUST attach to a citation in a way that resolves
  back to a 053/spec-020 source via `source_id` (no parallel identity scheme; no
  new `identity:` field — reuse `manifest.source_id_from`, consistent with 053
  FR-003). This is what makes `off_field` (FR-005) and the per-source
  `default_credibility` (FR-001) resolvable.

### Contextual modifiers — FR-004..005

- **FR-004 (CL-3 resolved — COI cap)**: A citation MAY declare a `coi` signal
  (the author has a stake in the claim). When present, the **effective** level is
  **capped at `commentary`** — i.e. `effective = min_rank(declared, commentary)` —
  so a COI-tainted source can never resolve to `primary`/`corroborated` regardless
  of its source type. The cap is a pure function of the recorded fields. COI is
  author-declared at note time with a rationale.
- **FR-005 (CL-4 resolved — topic-scope downgrade)**: Credibility MUST vary by
  claim-type via **053's `note → note_type → authoritative role`** resolution.
  When a citation's source `role` (via `source_id`) is **NOT** the authoritative
  role for the note's note_type (off-field), its level is **downgraded one
  ordinal step** (floored at `unvetted`). No new per-topic config; the
  `off_field` predicate is a pure function of recorded data. The COI cap (FR-004)
  applies **before** the topic downgrade (see the resolution function in
  Clarifications).

### Consumption surface — FR-006..008

- **FR-006**: Spec 030's `source_quality` family MUST be extensible with
  `tier2_source_ratio` computed purely from recorded levels (a deterministic
  calculator reading frozen frontmatter), with a baseline + the existing moderate
  regression gate. 055 delivers the level + the resolution rule; 030 wires the
  calculator (sequencing per Dependencies).
- **FR-007**: The verifier (`.agents/skills/verifier`) MUST reject a note whose
  Tier-2 citations lack a well-formed credibility record once the model ships
  (presence + shape check only — never a re-judgement of the *value*).
- **FR-008**: Spec 048 v2's ledger MUST be able to annotate a `USED` source with
  its recorded level by joining existing artifacts (read-only; missing → degrade
  to unannotated, never error). `[v1-optional — confirm at clarify whether this rides 055 v1 or is a 048-v2 follow-up.]`

### Authoring guidance — FR-009

- **FR-009**: The credibility model MUST be documented as **author-facing
  guidelines** (a contract doc, akin to 053's locked decisions) so the level
  assignment is reproducible by humans and agents — the "draw the line
  consistently" requirement that motivated a standalone spec. The note-writer /
  source-relevance skills are updated to apply the guidelines at authoring time.

## Key Entities

- **Credibility level** — the ordinal/score datum (CL-1) at the chosen
  granularity (CL-2). The single source of truth for "how much do we trust this".
- **Citation credibility record** — the frozen per-citation frontmatter carrying
  the level (+ COI signal CL-3, + topic-scope signal CL-4, + a short rationale, by
  053's "declare with rationale" precedent). Written at authoring time; read by
  gates/metrics.
- **COI signal** — the declared conflict-of-interest (CL-3) that caps a level.
- **`tier2_source_ratio`** — the spec-030 `source_quality` metric computed from
  recorded levels; the "lower-authority displacing higher-authority" detector.
- **Credibility guidelines doc** — the author-facing contract (FR-009) defining
  each level and how COI/topic-scope adjust it.

## Determinism boundary & guardrails (non-negotiable, inherited from 053 + constitution)

- Credibility is **assessed at authoring/research time and recorded as data**;
  gates and metrics read the recorded data only. **No LLM judgement at gate
  time.** (053 decisions #4/#5; Principle IV.)
- Every consuming gate/metric is a deterministic script with its own unit tests
  (pattern: `tests/scripts/test_check_intent_drift.py`, `tests/quality/unit/test_source_quality.py`).
- `research.spec.md` is user-owned — the model reads declarations, never rewrites
  the spec.
- No new runtime dependency (Principle V). Stdlib + existing `pyyaml`.

## Dependencies & relationships

- **Extends spec 053** (source authority) — adds the credibility/quality axis on
  top of role/priority. **Should land after 053 ships** so the `source_id →
  role` resolution it reuses is stable. *(053 is Wave 1, in implementation.)*
- **Unblocks spec 030** — `tier2_source_ratio`. 030 ships its other 3
  `source_quality` metrics in Wave 1 without waiting; the 4th rides 055.
- **Enriches spec 048 v2** (source-consideration ledger) — optional annotation
  (FR-008).
- **Reuses spec 020** `source_id` / `source_id_from` / `sources_loader.py` for
  citation→source resolution (no parallel identity scheme).
- **Touches the verifier + note-writer + source-relevance skills** (authoring-time
  application of the guidelines).

## Out of Scope (v1 — confirm at clarify)

- A runtime LLM "credibility judge" invoked at gate/metric time (breaks 053's
  deterministic-gate principle).
- Re-litigating 053's role/priority authority axis (055 *extends* it; it never
  overrides the role gate).
- Numeric reputation scoring of platforms/authors from external signals
  (citations counts, follower counts, etc.) — out of scope; the model is
  declarative, not scraped.
- Back-filling credibility onto historical notes from prior cycles (the model
  applies going forward; a migration pass, if wanted, is its own follow-up).

## Success Criteria

- A documented credibility-guidelines contract exists such that two authors
  (human or agent) independently assign the same fixture citation the same level
  (FR-009 — the "consistency" bar that justified the spec).
- A fixture note's declared citation credibility records parse and validate; the
  verifier deterministically accepts well-formed and rejects malformed records
  (US1, FR-007).
- `tier2_source_ratio` computes as a byte-deterministic float from recorded
  levels with a committed baseline and the moderate regression gate (US2, FR-006).
- The COI cap (US3) and topic-scope downgrade (US4) are pure functions of the
  recorded fields — same input, same level, every run.
- No gate or metric invokes an LLM at evaluation time (determinism boundary).

## The six guideline questions — RESOLVED

CL-1..CL-6 are **locked** (`/speckit.clarify` 2026-06-03) — see **§Clarifications**
for the full resolution and the derived deterministic resolution function. In
brief: 4-level ordinal enum (CL-1), per-citation with per-source default (CL-2),
COI caps at `commentary` (CL-3), 053-role off-field one-step downgrade (CL-4),
declared at note time (CL-5), in per-citation frontmatter (CL-6).

## Next steps

1. ~~`/speckit.clarify` — lock CL-1..CL-6~~ ✅ **done 2026-06-03.**
2. `/speckit.plan` — datum schema, the resolution rule, verifier/calculator
   touch-points, the guidelines doc. *(this pass)*
3. `/speckit.tasks` + `/speckit.analyze` — TDD task breakdown; cross-check vs 030
   (calculator) and 048 v2 (ledger annotation). *(this pass)*
4. ~~Implement in Wave 2; spec 030 picks up `tier2_source_ratio` against the model.~~ ✅

## Acceptance coverage

| User Story | Evidence |
|------------|----------|
| US1 — per-citation level recorded + resolver | `tests/vault/test_credibility.py::test_level_enum_order`, `test_effective_level_matrix`, `test_resolution_order`, `test_off_field_missing_role_is_not_off_field`, `test_default_credibility_loaded`, `test_invalid_default_warns` |
| US1 — verifier shape validation | `tests/pipeline/test_verifier.py::test_credibility_wellformed_passes`, `test_credibility_unresolved_fails`, `test_credibility_bad_enum_fails`, `test_coi_non_boolean_fails` |
| US2 — `tier2_source_ratio` metric | `tests/quality/unit/test_source_quality.py::test_tier2_source_ratio_deterministic`, `test_tier2_ratio_moves_on_level_flip` |
| US3 — COI cap end-to-end | `tests/quality/unit/test_credibility_e2e.py::test_coi_caps_through_resolver_and_metric` |
| US4 — off-field downgrade end-to-end | `tests/quality/unit/test_credibility_e2e.py::test_off_field_downgrade_and_combined_coi` |
| US5 — ledger annotation (optional) | _(deferred — 048 v2 follow-up; see tasks T022)_ |
| FR-009 — author guidelines | `docs/source-credibility.md` + skill updates under `.agents/skills/` |
