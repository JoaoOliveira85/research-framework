---
spec_number: 049
title: _cycle_helpers.py God-Module Split
status: SHIPPED
priority: high
priority_reason: |
  Bumped into v1.0.0-rc1 Wave 1 (user decision 2026-06-03): do the quality
  refactor EARLY so the Wave-1/Wave-2 hardening specs (027/029/030/032/038) land
  on the new submodule shape rather than re-touching the god-module. Behaviour-
  preserving, so it de-risks everything downstream without changing run outcomes.
created: 2026-05-30
specified: 2026-06-03
source_input: |
  User direction "do a code quality pass on the whole project so far" (2026-05-30).
  The audit ranked src/research_framework/pipeline/_cycle_helpers.py (1354 LOC,
  39 private functions + process-global mutable flags) as the single highest
  maintainability cliff in src/. This spec was a DRAFT stub until 2026-06-03 when
  /speckit.specify restructured it into house-style.
---

**Status:** shipped(2026-06-03, PR #97) — SHIPPED 0.9.0 (PR #97, 2026-06-03) — behaviour-preserving god-module split into `pipeline/_helpers/` submodules.
**Wave 1 → 0.9.0.** Behaviour-preserving structural refactor; **no functional
change.**

# Feature Specification: `_cycle_helpers.py` God-Module Split

**Feature Branch**: `049-cycle-helpers-split`

## Problem

`src/research_framework/pipeline/_cycle_helpers.py` is the single largest
maintainability liability in `src/`: **1354 LOC, 39 private functions, plus
process-global mutable flags**, covering at least seven unrelated concerns —
script orchestration, quality-report gating, scout-correction retry loops, batch
hashing, cosmetic-correction detection, probe retrieval, and per-cycle state. It
is the coupling hub between `cycle_runner.py`, `orchestrator.py`, and the
`pipeline/steps/` modules. The `_helpers` prefix has signalled "junk drawer,
don't touch" for three release cycles, and the file is now ~1.3× the
second-largest pipeline file (`orchestrator.py` @ 1047 LOC).

It is the residue of three prior refactors that each pushed code in and none
pulled it apart:

1. **Spec 025** thinned `cycle_runner.py` 2350 → 232 LOC by moving helpers *here*.
2. **Specs 028 / 033 / 048** each added one or two more hot-path functions.
3. **No subsequent split.**

This feature splits the module into focused, single-responsibility submodules
**without changing any runtime behaviour**. It is purely structural.

## Why now (Wave 1)

The v1.0.0-rc1 plan (2026-06-03) bumps this into **Wave 1 / 0.9.0** so the split
happens *before* the Wave-1/Wave-2 hardening specs (027/029/030/032/038) touch
the cycle-helpers surface — they should consume the new shape, not the legacy
god-module, and not have to be re-touched after a later split. Because the
refactor is behaviour-preserving it adds no run risk; it only de-risks the
hardening that follows.

## Concrete symptoms (from the 0.6.x audit)

- **Cross-concern coupling**: reading the SG-006 cosmetic-correction gate means
  scrolling past unrelated script-runner code, heartbeat threading, state-write
  I/O, and quality-report writers.
- **Process-global mutable state**: `_should_abort_current_cycle` and
  `_last_note_writer_cap_tripped` leak module-level state across functions —
  safe today only because `run_cycle_steps` resets them at entry; fragile under
  any future call pattern (direct helper calls in tests, parallel cycles).
- **Test-surface drift**: helper tests are scattered across five
  `test_cycle_runner_*.py` files, each touching a different slice. A split lets
  each test file own a focused submodule.
- **Audit verdict**: ranked "Tier B effort 4" — the single highest-effort item
  in the quality pass; a planned, per-submodule split is the correct shape, not
  a one-shot rewrite.

## User Scenarios & Testing *(mandatory)*

*"Users" here are the framework's maintainers and the AI agents that implement
specs against this codebase.*

### User Story 1 — Locate and change one concern without reading the others (Priority: P1) 🎯 MVP

A maintainer fixing the cosmetic-correction (SG-006) gate opens a single focused
submodule (`≤300 LOC`) that contains only cosmetic-correction logic, instead of
scrolling through a 1354-line file mixing seven concerns.

**Why P1**: this is the entire point of the split — bounded, single-responsibility
files. If it isn't achieved, the refactor failed.

**Independent Test**: each of the seven identified concerns resolves to exactly
one submodule under `pipeline/_helpers/`; no submodule exceeds 300 LOC; opening
the submodule shows only that concern's functions.

**Acceptance Scenarios**:

1. **Given** the split is complete, **When** a maintainer greps for the
   SG-006/cosmetic-correction functions, **Then** they live in one submodule and
   nothing unrelated shares that file.
2. **Given** any submodule under `pipeline/_helpers/`, **When** its LOC is
   counted, **Then** it is ≤300 LOC.

### User Story 2 — Existing imports and behaviour are unchanged (Priority: P1, regression)

Every current importer of `_cycle_helpers` symbols (`cycle_runner.py`,
`orchestrator.py`, `pipeline/steps/*`, and the five `test_cycle_runner_*.py`
files) keeps working with no edit, and a cycle produces byte-identical artifacts
before and after the refactor.

**Why P1**: a structural refactor that changes behaviour or breaks importers is a
regression, not a refactor.

**Independent Test**: the full fast suite (`pytest -m "not e2e"`) passes at ≥ the
pre-refactor count with no test-file edits required for import resolution; a
fixture cycle run produces identical output artifacts pre/post.

**Acceptance Scenarios**:

1. **Given** the legacy import path `from research_framework.pipeline._cycle_helpers import <symbol>`, **When** it runs post-refactor, **Then** it resolves (via the re-export shim) without error.
2. **Given** a fixture cycle, **When** it runs pre- and post-refactor, **Then** the produced cycle artifacts are byte-identical (no behaviour change).

### User Story 3 — No hidden cross-call state (Priority: P2)

Per-cycle runtime state (the former process-global abort/cap flags) is carried in
an explicit `CycleRuntimeState` value passed through the cycle context, so a
helper called in isolation (e.g. a unit test, or a hypothetical parallel cycle)
cannot read or corrupt another cycle's flags.

**Why P2**: removes a latent footgun; valuable but secondary to US1/US2. Could be
descoped to a follow-up if `/plan` finds the `run_cycle_steps` signature change
too entangled — but the default is to include it.

**Independent Test**: a static check finds **zero** module-level mutable globals
in `pipeline/_helpers/`; the abort/cap flags are reachable only via the
explicitly-passed state object.

## Requirements *(mandatory)*

### Structural outcomes — FR-001..004
- **FR-001**: `_cycle_helpers.py`'s concerns are decomposed into focused
  single-responsibility submodules under a new private `pipeline/_helpers/`
  subpackage. **No submodule exceeds 300 LOC.**
- **FR-002**: During the multi-PR split, `pipeline/_cycle_helpers.py` is a
  **transitional re-export shim** that keeps imports resolving while submodules
  are extracted PR-by-PR. Because the module is **private** (`_`-prefixed) with
  **only in-repo importers** (no external consumers — Clarifications Q2), the
  **final split PR updates every importer and deletes the shim** — no lingering
  deprecated alias and no cross-release deprecation window.
- **FR-003**: **Zero process-global mutable state** in any new submodule. The
  former `_should_abort_current_cycle` / `_last_note_writer_cap_tripped` flags are
  carried in an explicit per-cycle `CycleRuntimeState` passed through the cycle
  context. **Confirmed in scope (Clarifications Q3)** — the `run_cycle_steps`
  signature change is contained to one entry point and is done as part of this
  split, not deferred.
- **FR-004**: Each submodule maps to one concern from: script-running,
  per-cycle state I/O, quality-report guard, scout-correction loop,
  cosmetic-correction (SG-006), source-signal/probe, and the `CycleRuntimeState`
  type itself.

### Behaviour & safety — FR-005..008
- **FR-005**: **No behaviour change.** The cycle runner produces byte-identical
  artifacts before and after the refactor for the same inputs.
- **FR-006**: The full fast suite (`pytest -m "not e2e"`) passes at ≥ the
  pre-refactor test count, and `ruff check .` + `ruff format --check .` are both
  clean, after the split.
- **FR-007**: The new import topology introduces **no import cycles**. Any helper
  that currently reaches back into `cycle_runner.py` lazily must keep a verified-
  acyclic import shape (eager or lazy as `/plan` determines).
- **FR-008**: A `CHANGELOG` entry under the shipping version documents the new
  private import paths and the removal of `_cycle_helpers.py` (deleted in the
  final split PR — no cross-release deprecation window; Clarifications Q2).

### Process — FR-009
- **FR-009**: The split ships as **one PR per submodule** (reviewable diffs),
  each independently green on the smoke gate (ADR-0007) and preserving the
  seven-tier pyramid shape (ADR-0008).

## Success Criteria *(mandatory)*

- **SC-001**: The largest file under `pipeline/_helpers/` is **≤300 LOC** (down
  from 1354 in a single file).
- **SC-002**: `pipeline/_cycle_helpers.py` is **≤80 LOC** (re-exports only) while
  the split is in progress, and is **deleted** by the final split PR (end state:
  no `_cycle_helpers.py`).
- **SC-003**: A static scan finds **0** module-level mutable globals across
  `pipeline/_helpers/`.
- **SC-004**: Fast suite passes at **≥ pre-refactor count**; **0** ruff errors
  across both gates.
- **SC-005**: Each of the seven concerns is locatable in **exactly one** submodule
  (no concern split across files, no file mixing concerns).
- **SC-006**: A fixture cycle produces **byte-identical** artifacts pre/post
  (behaviour-preservation, validated via the spec-022 harness / a tier-5/6 e2e).
- **SC-007**: The transitional shim keeps imports resolving **during** the split
  (zero importer edits needed per-PR); the **final PR updates all importers** to
  the `pipeline/_helpers/` paths and removes the shim (end state: no legacy path).

## Key Entities

- **`pipeline/_helpers/` subpackage** — the new home; one module per concern.
- **`CycleRuntimeState`** — a dataclass holding per-cycle mutable state
  (abort flag, note-writer-cap-tripped flag, …), passed explicitly through the
  cycle context, replacing the module-level globals.
- **`_cycle_helpers.py` shim** — transitional re-export layer during the split;
  deleted in the final PR (Clarifications Q2).

## Decomposition *(locked at `/speckit.clarify` 2026-06-03 — Clarifications Q1; line-level moves finalized in `/speckit.plan`)*

| Submodule | Concerns | Approx LOC |
|---|---|---|
| `_helpers/script_runner.py` | `_run_script`, `_subprocess`, `_heartbeat_writer`, `_StepError`, OSError handlers | ~200 |
| `_helpers/state.py` | `_state_write` (atomic RMW), `QualityReportState`, `_apply_exit_metadata` | ~150 |
| `_helpers/quality_report_guard.py` | `_write_cycle_quality_report`, spec-025 A6 "never mask exit" guard | ~200 |
| `_helpers/scout_correction.py` | scout-validation retry loop, validator-directive injection | ~200 |
| `_helpers/cosmetic_correction.py` | `_detect_cosmetic_only_correction`, `_snapshot_note_bodies`, `_split_note_frontmatter` (SG-006) | ~150 |
| `_helpers/source_signals.py` | `notify_required_source_degraded`, threshold resolution, probe retrieval | ~150 |
| `_helpers/cycle_state.py` | `CycleRuntimeState` (replaces the process-global flags) | ~80 |
| `_cycle_helpers.py` (legacy) | thin re-export shim | ≤80 |

Target ≈1180 LOC across 8 files (down from 1354 in one), with cross-submodule
coupling now explicit in imports.

## Edge Cases & Risks

- **Test-side private imports**: test files import private symbols by name; the
  shim absorbs most, but `/plan` MUST enumerate every test-side import and confirm
  resolution.
- **Process-global migration (FR-003)**: touches the `run_cycle_steps`
  entry-point signature in `cycle_runner.py` — the highest-risk change; **in scope
  (Clarifications Q3)**, executed as part of the split rather than deferred.
- **Cyclic-import landmines**: some helpers reach back into `cycle_runner.py`
  lazily; splitting may force eager imports that create cycles (FR-007).
- **Spec-028 sidecar interaction**: the `_active_timings` cache lives in
  `cycle_runner.py` but is accessed from the helpers; the split must move the
  cache or expose a stable accessor.

## Assumptions

- The 7-submodule decomposition is **locked** (Clarifications Q1); only the
  line-level moves are finalized in `/plan`.
- The shim is **transitional**, deleted in the final split PR (Clarifications Q2)
  — no cross-release deprecation window (private module, no external consumers).
- FR-003 (`CycleRuntimeState`) is **in scope** (Clarifications Q3), not deferred.
- No `orchestrator.py` or `processors/extract.py` work — separate future specs.

## Dependencies

- **Gated by**: the spec-022 E2E quality harness (regression-detection safety net
  for behaviour-preservation) — already shipped.
- **Blocks**: QW-9 (retire the 10 `run_cycle_steps` monkeypatch sites) — the new
  submodule boundaries dictate the right test-isolation seams, so QW-9 *follows*
  this split.
- **ADR-0007** (mandatory smoke gate) and **ADR-0008** (seven-tier pyramid) apply
  to every PR in the split.

## Acceptance coverage

| User Story | Evidence |
|------------|----------|
| US1 — Locate and change one concern without reading the others | _(deferred to tasks.md — SC-001 per-submodule ≤300-LOC ceiling + single-concern location verification)_ |
| US2 — Existing imports and behaviour are unchanged (regression) | `tests/pipeline/test_cycle_runner.py` + `tests/pipeline/test_cycle_runner_quality_report.py` (behaviour preserved); fast-suite parity |
| US3 — No hidden cross-call state | `tests/pipeline/test_cycle_runtime_state.py` |

## Out of Scope

- Any behaviour change (byte-identical artifacts is a hard requirement).
- `orchestrator.py` (1047 LOC) and `processors/extract.py` (777 LOC) splits.
- New test coverage beyond what the split surfaces (add a focused unit test when a
  helper becomes testable in isolation, but don't gate the spec on it).

## Clarifications

### Session 2026-06-03 — RESOLVED (all 3 recommended)

- **Q1 (submodule granularity) → A**: accept the **7-submodule** decomposition as
  written (`script_runner`, `state`, `quality_report_guard`, `scout_correction`,
  `cosmetic_correction`, `source_signals`, `cycle_state`) + the transitional shim.
  Maps 1:1 to the seven concerns, each ≤300 LOC, one PR per submodule.
- **Q2 (shim lifetime) → A**: the shim is a **transitional scaffold only** —
  `_cycle_helpers.py` is private with no external consumers, so the **final split
  PR updates all importers and deletes it** (no cross-release deprecation window).
- **Q3 (FR-003 scope) → A**: the `CycleRuntimeState` migration is **in scope** in
  this spec; the contained `run_cycle_steps` signature change is done as part of
  the split, not deferred.
