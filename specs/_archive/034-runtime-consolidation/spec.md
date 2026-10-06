# Feature Specification: Pipeline Runtime Consolidation

> **🗄️ SUBSUMED BY ADR-0009 + spec 020 (2026-05-26).** This spec's
> question — "two runtimes coexist, decide which wins"
> (`pipeline.runner.{run_full,run_collect,...}` 7-phase entry points
> + `pipeline.orchestrator.run_cycles` cycle-runner) — is answered
> by ADR-0009 option A: `pipeline.orchestrator.run_cycles`
> (cycle-runner) is the canonical entry point; the 015g 7-phase
> `pipeline.runner.run_full` (and sibling `run_collect`, `run_extract`,
> `run_scout`, `run_resume`, `run_finish`) is the legacy surface
> preserved during the revival sprint and retired in a batched
> cleanup post-sprint as 020 modules port. The "two-runtimes
> architectural smell" framing is resolved at the ADR level, not
> via a standalone spec.
> Do NOT plan against 034 directly; open
> `docs/adr/0009-collectors-vs-modules-reconciliation.md` instead.
> This file is kept as design-history.

**Feature Branch**: `034-runtime-consolidation` *(not branched; subsumed)*
**Created**: 2026-05-22
**Status**: superseded(by ADR-0009, spec 020) — 🗄️ SUBSUMED BY ADR-0009 + spec 020 (2026-05-26)
**Input**: User description: "Code audit surfaced an architectural smell: `pipeline/runner.py` (the 015g 7-phase collect→extract→…→indexer orchestrator) coexists with `pipeline/orchestrator.run_cycles` (the cycle-runner orchestrator). They have the SAME conceptual role (drive a multi-phase vault workflow) but different surfaces. Naming collision (nothing imports `runner.py` from a path called `orchestrator/`). Decision needed: consolidate to one entry point, or formalize as two distinct runtimes with documented use cases."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Single canonical entry point for "run a vault workflow" (Priority: P2)

When a contributor (or future agent) needs to invoke a multi-phase vault workflow, they should find exactly one canonical entry point. Today they find two: `pipeline.runner.run` (7-phase 015g) and `pipeline.orchestrator.run_cycles` (cycle-runner). Without a decision, both grow drift.

**Why this priority**: Code-organization correctness. Doesn't bite production today but every refactor that touches either path makes the divergence worse.

**Independent Test**: Read `docs/ARCHITECTURE.md`'s pipeline section. Verify it documents exactly one canonical "run a workflow" entry point (or two, with clear use-case separation). Verify all in-tree callers (`cli/`, `scripts/`, tests, vault generator) go through the documented entry point(s).

**Acceptance Scenarios**:

1. **Given** a contributor needs to invoke a vault workflow, **When** they read `docs/ARCHITECTURE.md`, **Then** they find exactly one canonical entry point (or two with clearly-distinct use cases).
2. **Given** all in-tree callers, **When** they're enumerated, **Then** each one invokes the documented entry point — no "private" / "legacy" backdoor invocations remain.

---

### User Story 2 — Module names reflect intent (Priority: P3)

`pipeline/runner.py` is the 015g orchestrator. `pipeline/orchestrator.py` exists but doesn't own the 7-phase flow. The names are inverted relative to intent. Rename or restructure.

**Why this priority**: Discoverability. New contributors are likely to look in the file named "orchestrator" for the orchestrating logic.

**Acceptance Scenarios**:

1. **Given** a new contributor scanning `pipeline/` for "where does the orchestration happen", **When** they read filenames, **Then** the answer is obvious from the filename.

---

### Edge Cases

- What if `runner.py` is referenced by vault-generated `./vault` script content? Renaming would require dist-templates updates + a deprecation cycle.
- What about the test suite — how much of the test corpus assumes the current module names?
- What about backward compatibility for vault content / scripts published before the rename?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A DECISION MUST be recorded for `pipeline/runner.py` vs `pipeline/orchestrator.run_cycles`. Three options: (a) CONSOLIDATE to one canonical entry point and deprecate the other; (b) RENAME files so module names reflect intent (both stay); (c) KEEP both as-is and document the distinction clearly in ARCHITECTURE.md. [NEEDS CLARIFICATION: which option? Requires brainstorming session — design space is broader than a simple FR can capture.]
- **FR-002**: Once the decision lands, `docs/ARCHITECTURE.md` MUST document the resolution prominently.
- **FR-003**: If consolidation (option a) is chosen, the deprecated path MUST emit a `DeprecationWarning` for at least one full release cycle before removal.
- **FR-004**: If renaming (option b) is chosen, the old module names MUST be preserved as compat shims for at least one release cycle.
- **FR-005**: Any vault-script template references to either module MUST be updated. The compat shim approach SHOULD prevent breaking existing vaults.

### Key Entities

- **`pipeline/runner.py`**: Currently the 015g 7-phase orchestrator (collect → extract → …).
- **`pipeline/orchestrator.run_cycles`**: Currently the cycle-runner orchestrator (multi-cycle research loop).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new contributor reading `docs/ARCHITECTURE.md` can identify the canonical "run a vault workflow" entry point(s) in <2 minutes.
- **SC-002**: `rg "pipeline.runner|pipeline.orchestrator" src/` returns results that all align with the documented usage pattern.
- **SC-003**: If consolidation is chosen: only ONE entry point is documented + advertised in tests + CLI. The other is a deprecated shim.

## Assumptions

- The two paths have non-overlapping behaviour (one is multi-cycle research; the other is single-pipeline-pass collect→extract). If they overlap more than expected, the consolidation option is less viable.
- The vault content / scripts published to date can be migrated via the existing `./vault update` flow.
- The decision can wait for `/speckit.clarify` — no production bug forces it.

## Dependencies

- Soft on spec 023 (flow separation) — VaultHandle abstraction may inform the entry-point shape.
- Soft on spec 015h (retire vault-local scripts) — if that work continues, it touches `runner.py`.

## Acceptance coverage

Draft — evidence cells will be populated by `/speckit.tasks` for
this spec. Listed for the ADR-0008 guard so the spec is accepted
into the queue (the guard refuses any G/W/T-bearing spec without
this section).

| User Story | Evidence |
|------------|----------|
| US1 — Single canonical entry point for "run a vault workflow" | _(deferred to tasks.md — populated by `/speckit.tasks`)_ |
| US2 — Module names reflect intent | _(deferred to tasks.md — populated by `/speckit.tasks`)_ |

## Out of Scope

- Reworking the 7-phase flow itself. That's spec 015a-h territory.
- Reworking the cycle runner. That was spec 025 B3 (shipped).
- Cross-cutting refactors beyond the runner / orchestrator question.
