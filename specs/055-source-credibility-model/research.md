# Research & Decisions: Source Credibility Model (Spec 055)

**Date**: 2026-06-03 · **Stage**: post-clarify, pre-plan
**Inputs**: the design-direction draft (8e86b94), spec 053 (authority model, in
implementation), spec 030 (the consumer — `tier2_source_ratio` dropped to 055),
spec 048 v2 (ledger), spec 020 (`source_id`).

## Why a standalone spec

`tier2_source_ratio` (spec 030's 4th `source_quality` metric) was **dropped at
030's 2026-06-03 clarify** because "source tier" is modeled nowhere — only a
prose Tier-1/Tier-2 module list in `docs/ROADMAP.md`, which is conceptually
wrong: credibility is per-instance, COI-aware, and topic-scoped, not a static
per-module label. 030 ships its other 3 metrics in Wave 1; 055 owns the model.

## Cross-spec reconciliation (audit findings)

- **053 sets the determinism precedent.** 053 faced the identical tension
  (authority "needs judgement" but gates must be deterministic) and resolved it
  by **declaring authority at spec time, reading frozen data at gate time, never
  judging at runtime** (decisions #4/#5). 055 inherits this verbatim — it is the
  spine of CL-5/CL-6. *Confirmed by reading `specs/053-*/spec.md` §"Locked design
  decisions".*
- **053 already builds the resolution 055 reuses.** 053 FR-004 replaces
  `classify_url` regex-guessing with `citation → source_id → owning data_source →
  role` via `sources_loader.py`. 055's `off_field` predicate reuses exactly this
  + `note_type → authoritative role`. ⇒ **055 should land after 053 ships** so
  the resolution is stable. *(Captured in Dependencies.)*
- **`source_urls` already supports an object form.** The Tier-2 frontmatter list
  accepts both plain strings and `{url, title}` objects (parser
  `check_code_source_coverage.py::_source_urls` handles both). ⇒ credibility
  attaches to the **object form** with no new top-level frontmatter key and no
  parser rewrite. *Verified against the script + `tests/scripts/test_*` fixtures.*
- **030 left a clean seam.** 030's `source_quality` family is "3 keys, extensible";
  its tasks/plan explicitly say `tier2_source_ratio` rides 055. ⇒ 055 delivers the
  level + resolution rule + the tier-2 boundary; 030 wires the calculator. No
  rework of 030's shipped 3 metrics.
- **048 v2 is a read-only consumer.** Annotation is a join over existing
  artifacts; it cannot error on missing data (048 v2's "degrade, never error"
  ethos). ⇒ FR-008 is optional/v1-light.

## Decisions

### D1 — 4-level ordinal enum, not a score (CL-1)
`primary > corroborated > commentary > unvetted`. **Why**: ordinal supports
030's ratio; a fixed enum (like 053's `role`) stays declarable and
byte-deterministic and dodges the false-precision + inter-rater-inconsistency of
a 0.0–1.0 score. 4 levels (not 3) keep "vetted-secondary" (`corroborated`)
distinct from "named opinion" (`commentary`) — the HN-expert vs survey-paper
distinction the user raised. **Alternatives rejected**: numeric score (non-
deterministic assignment); 3 levels (collapses the corroborated/commentary line
the user explicitly cares about).

### D2 — Per-citation with per-source default (CL-2)
Level lives on the citation; a source may declare `default_credibility`.
**Why**: directly answers "HN commenter varies" (per-instance) while avoiding
boilerplate for sources that are uniformly one level (a journal feed defaults to
`corroborated`). **Strict resolution** (explicit → default → FAIL) keeps it
deterministic with no magic fallback. **Alternatives rejected**: per-module
(the wrong model); per-author (no author-identity registry exists — out of
proportion); per-citation-only (boilerplate-heavy for uniform sources).

### D3 — COI as a declared cap to `commentary` (CL-3)
`coi: true` ⇒ `effective = min_rank(declared, commentary)`. **Why**: the OpenAI-
paper case — a stake in the conclusion disqualifies "authoritative" regardless of
format. A *cap* (not a fixed value) preserves ordering for already-low sources.
**Alternatives rejected**: a separate orthogonal dimension (two numbers to reason
about downstream; 030 would need to combine them anyway); out-of-scope-v1 (COI is
one of the three motivating failures — can't defer it).

### D4 — Topic-scope via 053 role mismatch, one-step downgrade (CL-4)
`off_field` = citation source `role` ≠ note_type authoritative `role` ⇒ downgrade
one ordinal step. **Why**: reuses 053 resolution (zero new config), and a
one-step (not floor-to-zero) downgrade matches "out of place" not "worthless".
**Missing-role ⇒ not off_field** so 055 never double-penalizes what 053's
grounding gate already governs. **Alternatives rejected**: a new per-citation
expertise/topic field (new authoring burden + new config surface 053 deliberately
avoided); out-of-scope-v1 (third motivating failure).

### D5 — Declared at note time, frozen in frontmatter (CL-5, CL-6)
Note-writer assigns; verifier shape-validates; 030/048 read. **Why**: the only
option that keeps Principle IV + 053's deterministic-gate rule intact. The
"judgement" is the authoring agent's, recorded as data with rationale — exactly
053's model. **Alternatives rejected**: computed-at-research-time (pushes
heuristics into the pipeline, drifts toward gate-time inference); a runtime
"credibility judge" (explicit Out-of-scope — breaks determinism).

### D6 — Sequencing: after 053, unblocks 030; Wave 2
055 reuses 053's `source_id → role` resolution ⇒ depends on 053 shipping. 030's
calculator depends on 055's level ⇒ 055 unblocks 030's 4th metric. 048 v2
annotation is optional and can trail. **Net**: 053 (Wave 1) → 055 (Wave 2) →
030's `tier2_source_ratio` increment (Wave 2, in 030's follow-up or a thin 055
task). Not run-blocking for the Wave-1 vault runs.

## Open items carried to plan/tasks
- Exact module(s): a `quality/`-adjacent resolver vs a `vault/`-level helper for
  `effective_level` (so both the verifier and 030's calculator import one
  implementation — DRY). *Plan decides placement.*
- Whether the 030 `tier2_source_ratio` calculator task lives in spec 055's
  tasks.md or is handed to 030 as a follow-up. *Recommend: 055 ships the resolver
  + a unit-tested boundary; 030 wires the metric family entry. Confirm in tasks.*
- Author-facing guidelines doc location: `docs/` vs the contract itself.
  *Recommend `docs/source-credibility.md` mirroring `docs/observability-strategy.md`.*

## Determinism / Principle-IV check
Every consumer reads frozen frontmatter; the resolver is a pure function; the
verifier checks shape only. No agent is invoked at gate/metric time. ✅ Consistent
with 053 + Principle IV + Principle V (stdlib + pyyaml; no new dep).
