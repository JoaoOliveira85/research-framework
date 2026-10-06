# Implementation Plan: Plastic-but-Enforceable Source Authority

**Branch**: `053-source-authority-strategy` | **Date**: 2026-06-02 | **Spec**: `specs/053-source-authority-strategy/spec.md`
**Input**: Feature specification + `docs/handoff-source-strategy.md`

## Summary

Generalize the *shipped* hardcoded `code=behaviour` / `Confluence=intent`
authority model (specs 002/019) into a per-vault declarable `role`+`priority`
model with a **derived trunk**, so journal-/docs-/code-first vaults all enforce
on the same pipeline without weakening enforcement. Technical approach:
**generalize 3 existing deterministic gate scripts** (code-hardcoded →
strategy-driven via `citation → source_id → owning data_source → role`
resolution, reusing `sources_loader.py`), **add one new gate** (trunk-inversion,
on the spec-048-v2 Source-Consideration Ledger), and prove it with **3 fixtures**
(code-first regression, journal-first abstraction proof, bad-faith FAIL). No new
subsystem; no new runtime dependencies.

## Technical Context

**Language/Version**: Python 3.11+ (repo `requires-python`).
**Primary Dependencies**: stdlib + already-present `pyyaml` + `jinja2`. **No new
runtime dependencies** (Principle V).
**Storage**: filesystem under vault root — `research.spec.md` (schema),
`note_type` declarations, `_pipeline/cycles/*`, the spec-048-v2
`cycle-NNN-source-ledger.json`. No DB schema changes.
**Testing**: pytest; deterministic gate scripts each with unit tests (pattern
`tests/scripts/test_check_intent_drift.py`); fixtures under `tests/fixtures/`.
**Target Platform**: macOS/Linux dev + CI.
**Project Type**: single project (`src/` + `scripts/` + fixtures).
**Performance Goals**: N/A — gates are short deterministic passes over per-cycle
artifacts (no hot path).
**Constraints**: LLM-free at runtime (decisions #4/#5); `research.spec.md` is
user-owned (read, never rewrite); **hard dependency on spec 048 v2** (the
trunk-inversion gate reads the ledger — 048 v2 must ship first).
**Scale/Scope**: 3 gates generalized + 1 new gate + schema additions + 3
fixtures. Charter (v1.1) + HOME.md/reconciliation (v1.2) are OUT of this plan.

## Constitution Check

*GATE: must pass before Phase 0. Re-checked after Phase 1.*

| Principle | Assessment |
|---|---|
| **I. Script-Validated Quality Gates (NON-NEGOTIABLE)** | ✅ This feature *is* Principle I — all enforcement is deterministic scripts with exit codes + their own tests. |
| **III. Test-First (TDD, NON-NEGOTIABLE)** | ✅ The 3 fixtures + gate unit tests are written **before** the generalization. |
| **IV. Agent-Script Separation** | ✅ Authority is *declared* at spec time + read by scripts; the runtime agent never judges authority (decision #4). |
| **V. Offline-First, No New Deps** | ✅ Generalizes existing code; stdlib + existing deps only. |
| **VII. External Sources Mandatory** + **IX. Vault-First Citation (NON-NEGOTIABLE)** | ✅ The grounding gate strengthens citation enforcement (claim → authoritative-role source); never weakens it. |
| **II. Phase Sequencing** / **VIII. No Placeholders** / **X. Vault-Git** | ✅ No change (v1.2, deferred, reuses spec-027 git snapshot/rollback). |

**Result: PASS — no violations, no Complexity-Tracking entries needed.** This is
a generalization that *tightens* the enforcement story.

## Project Structure

### Documentation (this feature)
```text
specs/053-source-authority-strategy/
├── plan.md          # this file
├── research.md      # Phase 0 — decisions D1..D7
├── data-model.md    # Phase 1 — entities + resolution rules
├── contracts/       # Phase 1 — gate contracts + scout-report v3 shape
├── quickstart.md    # Phase 1 — exercise each gate + the 3 fixtures
└── tasks.md         # Phase 2 (/speckit.tasks — NOT this command)
```

### Source touched (repository root)
```text
research.spec.md schema (consumed)   # role+priority on every data_source;
                                     # note_type declares authoritative role +
                                     # (opt-in) authority_section/complementary_section
scripts/check_code_source_coverage.py   # → Grounding gate (FR-004): note→note_type→role; citation→source_id→role
scripts/check_intent_drift.py           # → Drift gate (FR-005): authority vs complementary; opt-in; flag→authority_drift
scripts/validate_cycle.py               # → Trunk-seed/attach gate (FR-006): topics_from_code→topics_from_trunk; resolve via source_id; `if signatures:`-style guard for pure-domain
scripts/check_trunk_inversion.py (new)  # → Trunk-inversion gate (FR-007): on the 048-v2 ledger
src/research_framework/pipeline/source_bridge/sources_loader.py   # reused for source_id→data_source→role resolution
tests/fixtures/vault-code-first/        # regression (extend)
tests/fixtures/vault-journal-first/     # NEW — abstraction proof (no behaviour source)
tests/fixtures/vault-bad-faith/         # NEW — trunk-inversion FAIL
tests/scripts/test_*                    # gate unit tests (TDD, first)
```

## Phase 0 — Research (→ research.md)
Most unknowns resolved by the brief + `/speckit.clarify` (Q1–Q3). research.md
records decisions D1..D7 with rationale (claim-type resolution, trunk
uniqueness, opt-in drift, source_id→role resolution reuse, ledger-coupling for
the trunk-inversion gate, the scout-report v2→v3 contract bump, and the 048-v2
sequencing dependency).

## Phase 1 — Design (→ data-model.md, contracts/, quickstart.md)
- **data-model.md**: `DataSource{role, priority}`, `NoteType{authoritative_role,
  authority_section?, complementary_section?}`, derived `Trunk`, claim-type
  resolution rule, the consumed ledger `verdict` (from 048 v2).
- **contracts/**: the 4 gate contracts (grounding / drift / trunk-seed /
  trunk-inversion) as deterministic exit-code contracts + the scout-report **v3**
  shape (`topics_from_trunk`, `parent_trunk_topic_id`) with the
  `_warn_deprecated_termination_shape_once` back-compat path.
- **quickstart.md**: how to run each gate + the 3 fixtures.
- Agent context: run `.specify/scripts/bash/update-agent-context.sh claude`.

## Complexity / risks
- **Hard dependency on spec 048 v2** (trunk-inversion gate). 053 cannot fully
  ship before 048 v2; FR-004/005/006 are independently shippable, so FR-007 can
  land as a follow-on once 048 v2 exists. *(Sequencing, not a violation.)*
- **Scout-report contract bump (v2→v3)**: `topics_from_code → topics_from_trunk`,
  mitigated by the existing `_warn_deprecated_termination_shape_once` path.
- **Pure-domain vault edge**: the trunk-seed gate must NOT trip "trunk empty"
  when no trunk is derivable — mirror the existing `if signatures:` guard
  (`validate_cycle.py` ~L773).
