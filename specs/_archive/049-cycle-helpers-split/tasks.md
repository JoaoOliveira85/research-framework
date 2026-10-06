---
description: "Task list for spec 049 — _cycle_helpers.py God-Module Split"
---

# Tasks: `_cycle_helpers.py` God-Module Split

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Feature**: 049-cycle-helpers-split | **Branch**: `049-cycle-helpers-split` | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Design**: [research.md](./research.md), [data-model.md](./data-model.md), [quickstart.md](./quickstart.md)

**Input**: Design documents from `/specs/_archive/049-cycle-helpers-split/`
**Prerequisites**: plan.md (PLANNED 2026-06-03), spec.md (CLARIFIED 2026-06-03), research.md, data-model.md, quickstart.md
**Target ship**: 0.9.0 (Wave 1)

**Tests**: TDD is mandatory — tests written and seen to FAIL before the implementation that makes them pass. Behaviour-preservation is primarily verified by the existing suite + spec-022 harness (FR-005/FR-006); the one new test is `tests/pipeline/test_cycle_runtime_state.py` (US3). Run tests/lint via `.venv/bin/python -m pytest …` and `.venv/bin/ruff …` (**NOT** bare `python` — pyenv base has a stale editable install).

**Organization**: Phases group user stories (US1 → US2 → US3), but **execution order** is US1 → US3 wiring → US2 shim delete — see Critical Path in Dependencies. Aligned with the locked 7-submodule plan (one PR per submodule, FR-009). QW-9 (retire 10 `run_cycle_steps` monkeypatch sites) is **out of scope** — plan.md explicitly defers it to follow this split.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no incomplete-task dependency)
- **[USn]**: Which user story this task belongs to (US1, US2, US3)
- Every task cites exact file path(s) and FR-number(s); dependencies noted inline `(depends Txxx)`

## Path Conventions

Single-project layout: package source under `src/research_framework/`, tests under `tests/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm worktree/branch and capture a green baseline before any refactor.

- T001 Confirm on branch `049-cycle-helpers-split` with a clean working tree (`git status`; `git rev-parse --show-toplevel` → worktree root). (FR-009)
- T002 Capture fast-loop baseline: `.venv/bin/python -m pytest -m "not e2e" --co -q` — floor **≥ 1934** collected (research.md §4; SC-004). Record count + date in task notes. (FR-006, SC-004)
  - **Baseline recorded 2026-06-03**: **1887** collected (`1887/1913`, 26 e2e deselected). Below research.md floor — worktree branch count; re-check at T024.
- T003 [P] Capture source LOC baseline: `wc -l src/research_framework/pipeline/_cycle_helpers.py` — expect **1428 LOC** (plan.md; SC-001 starting point). (FR-001)
  - **Baseline recorded 2026-06-03**: **1428** LOC ✓

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Create the `_helpers/` package skeleton and verify the import-topology facts that every subsequent PR relies on.

- T004 Create empty package marker `src/research_framework/pipeline/_helpers/__init__.py`. (FR-001, FR-004)
- T005 [P] Verify production importers of `_cycle_helpers` match research.md §1.1: `src/research_framework/pipeline/cycle_runner.py`, `src/research_framework/pipeline/steps/scout.py`, `src/research_framework/pipeline/steps/research.py`, `src/research_framework/pipeline/steps/postprocess.py` — no others. (FR-007, SC-007)
- T006 [P] Verify the three direct test-side `_cycle_helpers` imports match research.md §2.1: `tests/pipeline/test_stamp_lifecycle_cycle.py:15`, `tests/pipeline/test_cycle_helpers_tree_kill.py:26`, `tests/pipeline/test_budget_guard.py:206` — do **not** repoint until T042 (Phase 8 / US2). (SC-007)
- T007 Run green baseline gates: `.venv/bin/python -m pytest -m "not e2e" -q`, `ruff check .`, `ruff format --check .`, `./build.sh`. If any fail, STOP. (FR-006, FR-009, ADR-0007)
  - **2026-06-03**: ruff green; fast loop 1877 passed (2 pre-existing spec-guard failures outside scope); `./build.sh` fails in worktree without `PYTHONPATH` (venv editable → main repo). Required T007 characterization tests pass with `PYTHONPATH=$PWD/src`.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runner.py::test_steps_execute_in_order`
    - Behavior: Pre-refactor baseline — representative cycle characterization test must pass before any `_helpers/` extraction begins.
    - Tier: 3
    - Notes: FR-006/FR-009 green baseline; companion to T002 count gate.
  - **Test 2**: `tests/quality/test_quality_harness_regression_gate.py::test_no_change_run_passes`
    - Behavior: Spec-022 harness must be green on base ref before first code move (FR-005 floor).
    - Tier: 5

  **TDD discipline**: not required

**Checkpoint**: Foundation ready — submodule extraction (US1) may begin.

---

## Phase 3: User Story 1 — Locate and change one concern without reading the others (Priority: P1) 🎯 MVP

**Goal**: Decompose `_cycle_helpers.py` into seven focused submodules under `pipeline/_helpers/`, each ≤300 LOC and single-concern (FR-001, FR-004, SC-001, SC-005).

**Independent Test**: `wc -l src/research_framework/pipeline/_helpers/*.py` — every file ≤300; each concern's functions live in exactly one submodule per plan.md function map.

> **PR discipline (FR-009)**: ship **one submodule per PR** in the order below. After each PR, run the US2 validation tasks (T023–T028) before merging.

### Tests (write first — must FAIL before impl)

- T008 [US1] No new US1 tests required beyond the existing suite (plan.md Test approach; FR-006). Existing tests in `tests/pipeline/test_cycle_runner*.py`, `tests/pipeline/test_cycle_helpers_tree_kill.py`, etc. are the characterization safety net — they must stay green after each move.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runner.py::test_steps_execute_in_order`
    - Behavior: End-to-end cycle step ordering via `run_cycle_steps` (fake_agent / patched subprocess only — no live LLM). Must pass unchanged after every US1 submodule move; MUST NOT add `monkeypatch(..., "run_cycle_steps", ...)`.
    - Tier: 3
    - Notes: FR-005/FR-006 characterization safety net (plan.md Test approach).
  - **Test 2**: `tests/pipeline/test_cycle_helpers_tree_kill.py::test_run_script_kills_grandchild_on_interrupt`
    - Behavior: `_run_script` process-tree termination on interrupt must remain byte-identical in behavior after script-runner extraction.
    - Tier: 2
    - Notes: Covers `script_runner` concern (FR-001 partial).

  **TDD discipline**: not required

### Implementation — PR 1: `cycle_state.py` (type only; wiring deferred to US3)

> **TDD (red → green)**: Author **T034 first** (isolation test — must FAIL), then **T009** (type impl — makes T034 pass).

- T034 [US3] Write `tests/pipeline/test_cycle_runtime_state.py`: assert `CycleRuntimeState()` defaults (`should_abort=False`, `note_writer_cap_tripped=False`); assert two instances are independent (set flag on one, other unchanged). Run with `.venv/bin/python -m pytest tests/pipeline/test_cycle_runtime_state.py` — must FAIL (ImportError / missing type) before T009. (FR-003, SC-003)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runtime_state.py::test_cycle_runtime_state_defaults_falsy`
    - Behavior: Import `CycleRuntimeState` from `_helpers.cycle_state`; assert a fresh instance has `should_abort is False` and `note_writer_cap_tripped is False`.
    - Tier: 2
    - Notes: `data-model.md` Fields table — default falsy flags.
  - **Test 2**: `tests/pipeline/test_cycle_runtime_state.py::test_cycle_runtime_state_instances_are_independent`
    - Behavior: Construct two instances; set `should_abort=True` on one; assert the other's `should_abort` remains `False`; repeat for `note_writer_cap_tripped`.
    - Tier: 2
    - Notes: `data-model.md` Isolation invariant (US3).

  **TDD discipline**: required

- T009 [US1] Add `src/research_framework/pipeline/_helpers/cycle_state.py` with `@dataclass class CycleRuntimeState` (`should_abort: bool = False`, `note_writer_cap_tripped: bool = False`) per `data-model.md`. **Do not wire yet** — globals stay live. (FR-004, FR-003 partial, depends T034)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runtime_state.py::test_cycle_runtime_state_defaults_falsy`
    - Behavior: After `cycle_state.py` lands, T034 Test 1 must pass (import resolves, defaults correct).
    - Tier: 2
    - Notes: FR-004 — new type only; no wiring yet.
  - **Test 2**: `tests/pipeline/test_cycle_runtime_state.py::test_cycle_runtime_state_instances_are_independent`
    - Behavior: After `cycle_state.py` lands, T034 Test 2 must pass.
    - Tier: 2
    - Notes: FR-003 partial — type exists but globals still live.

  **TDD discipline**: required

### Implementation — PR 2: `script_runner.py`

- T010 [US1] Move verbatim into `src/research_framework/pipeline/_helpers/script_runner.py`: `_subprocess`, `_StepError`, `_hms`, `_heartbeat_interval_s`, `_heartbeat_writer`, `_run_script` (from `src/research_framework/pipeline/_cycle_helpers.py`). Preserve lazy `from research_framework.pipeline import cycle_runner as _cr` inside `_subprocess` (FR-007). (FR-001, FR-004, depends T004)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_helpers_tree_kill.py::test_run_script_kills_grandchild_on_interrupt`
    - Behavior: Verbatim move — `_run_script` must still terminate the full process tree on interrupt; no test edits for import resolution during Phases 1–7.
    - Tier: 2
    - Notes: FR-005 behaviour preservation; `script_runner` concern.
  - **Test 2**: `tests/pipeline/test_cycle_helpers_tree_kill.py::test_run_script_interrupt_returns_promptly`
    - Behavior: Interrupt path must return without hanging after move; lazy `cycle_runner` reach-back preserved (FR-007).
    - Tier: 2

  **TDD discipline**: not required

- T011 [US1] Update transitional shim `src/research_framework/pipeline/_cycle_helpers.py` to re-export moved `script_runner` symbols (`from ._helpers.script_runner import *` or explicit names). Shim must stay ≤80 LOC during split (SC-002). (FR-002, depends T010)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_helpers_tree_kill.py::test_run_script_kills_grandchild_on_interrupt`
    - Behavior: Direct `_cycle_helpers` import of `_run_script` (test-side) must still resolve via shim re-export until Phase 8.
    - Tier: 2
    - Notes: SC-007 transitional shim.
  - **Test 2**: `tests/pipeline/test_budget_guard.py::test_cycle_runner_invokes_pre_dispatch_and_refresh_hooks`
    - Behavior: Budget guard reaches `h._run_script` through shim module object; must pass with shim re-exporting `script_runner` symbols.
    - Tier: 3

  **TDD discipline**: not required

- T012 [US1] Repoint `script_runner`-owned aliases in `src/research_framework/pipeline/cycle_runner.py:67-106` from `h.X` to import from `_helpers.script_runner`. Leave `steps/*.py` on `h.` (shim still resolves). (FR-002, SC-007, depends T011)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runner.py::test_steps_execute_in_order`
    - Behavior: Cycle runner re-export block repointed — full step pipeline must still execute in order without test-file edits.
    - Tier: 3
    - Notes: FR-002 alias repoint; SC-007.
  - **Test 2**: `tests/pipeline/test_cycle_helpers_tree_kill.py::test_run_script_interrupt_returns_promptly`
    - Behavior: `_run_script` behavior unchanged after alias repoint.
    - Tier: 2

  **TDD discipline**: not required

### Implementation — PR 3: `state.py`

- T013 [US1] Move verbatim into `src/research_framework/pipeline/_helpers/state.py`: `_state_write`, `QualityReportState`, `_cycle_num_from_dir`, `_vault_dir_from_state`, `_cycle_num_from_state`, `_apply_exit_metadata`, `_merge_research_notes`, `_read_skipped_topics_from_research`, `_discover_new_markdown_files`, `_vault_notes_content_sha1`, `_stamp_lifecycle_cycle`, `_empty_batch_result_for_pace`. (FR-001, FR-004, depends T010)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_stamp_lifecycle_cycle.py::test_stamps_field_when_missing`
    - Behavior: `_stamp_lifecycle_cycle` verbatim move — must stamp `lifecycle.created_at_cycle` when absent.
    - Tier: 2
    - Notes: Direct test-side import via shim (SC-007 until Phase 8).
  - **Test 2**: `tests/pipeline/test_stamp_lifecycle_cycle.py::test_respects_pre_existing_value`
    - Behavior: Must not overwrite an existing lifecycle field after move.
    - Tier: 2

  **TDD discipline**: not required

- T014 [US1] Extend shim `src/research_framework/pipeline/_cycle_helpers.py` + repoint matching aliases in `src/research_framework/pipeline/cycle_runner.py:67-106` for all moved `state.py` symbols. (FR-002, depends T013)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_stamp_lifecycle_cycle.py::test_stamps_field_when_missing`
    - Behavior: Shim re-export + `cycle_runner` alias repoint — direct test import must still resolve.
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_cycle_runner.py::test_steps_execute_in_order`
    - Behavior: Cycle runner aliases for `state.py` symbols must resolve; full cycle green.
    - Tier: 3

  **TDD discipline**: not required

### Implementation — PR 4: `cosmetic_correction.py`

- T015 [US1] Move verbatim into `src/research_framework/pipeline/_helpers/cosmetic_correction.py`: `_FRONTMATTER_DELIM`, `_split_note_frontmatter`, `_snapshot_note_bodies`, `_detect_cosmetic_only_correction`, `_synthetic_mid_batch_empty_sg005`. Import `GateResult` from `src/research_framework/pipeline/gates.py` (sibling, no cycle). (FR-001, FR-004, depends T013 — may import `_vault_notes_content_sha1` from `.state`)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runner.py::test_verifier_called_after_dfs`
    - Behavior: Full cycle path exercising post-DFS verifier + SG gate machinery must stay green after cosmetic-correction move.
    - Tier: 3
    - Notes: FR-005; SG-005/SG-006 concern (spec US1 acceptance).
  - **Test 2**: `tests/pipeline/test_cycle_runner.py::test_steps_execute_in_order`
    - Behavior: End-to-end cycle must complete without import or gate regressions.
    - Tier: 3

  **TDD discipline**: not required

- T016 [US1] Extend shim + repoint `cycle_runner.py` aliases for `cosmetic_correction` symbols. (FR-002, depends T015)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runner.py::test_verifier_called_after_dfs`
    - Behavior: Shim + alias repoint for cosmetic-correction symbols — behaviour unchanged.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_cycle_runner_scout_correction.py::test_scout_structural_error_triggers_correction_loop`
    - Behavior: Adjacent correction-path tests must remain green (no cross-concern regression from alias repoint).
    - Tier: 3

  **TDD discipline**: not required

### Implementation — PR 5: `scout_correction.py`

- T017 [US1] Move verbatim into `src/research_framework/pipeline/_helpers/scout_correction.py`: `_read_correction_directive_block`, `_archive_applied_directive`, `_render_prompt`, `_render_batch_note_writer_prompt`, `MAX_SCOUT_VALIDATION_RETRIES`, `_retry_scout_with_validation_directive`, `_correction_prompt_text`, `_parse_priority_queue_from_plan_md`. Keep lazy imports for `correction.build_directive` + `gates.GateResult`; import `_run_script` from `.script_runner`. (FR-001, FR-004, FR-007, depends T010, T015)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runner_scout_correction.py::test_scout_structural_error_triggers_correction_loop`
    - Behavior: Scout validation retry loop must behave identically after verbatim move; lazy imports preserved (FR-007).
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_cycle_runner_directive_injection.py::test_retry_prompt_contains_directive_then_succeeds`
    - Behavior: Directive injection + prompt render path must pass unchanged.
    - Tier: 3

  **TDD discipline**: not required

- T018 [US1] Extend shim + repoint `cycle_runner.py` aliases for `scout_correction` symbols. (FR-002, depends T017)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runner_scout_correction.py::test_scout_correction_loop_aborts_after_max_retries`
    - Behavior: `MAX_SCOUT_VALIDATION_RETRIES` alias via `cycle_runner` must still resolve after repoint.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_cycle_runner_directive_injection.py::test_first_attempt_prompt_has_no_directive`
    - Behavior: Prompt render aliases resolve through repointed `cycle_runner` block.
    - Tier: 3

  **TDD discipline**: not required

### Implementation — PR 6: `source_signals.py` + `quality_report_guard.py`

- T019 [US1] Move verbatim into `src/research_framework/pipeline/_helpers/source_signals.py`: `notify_required_source_degraded`, `_load_yaml_settings`, `_pipeline_int_setting`, `_effective_note_writer_batch_size`, `_max_batches_per_cycle`, `_load_spec_for_scout_gates`, `_cycle_quota_for_gates`, `_unfilled_categories_for_gates`, `_probe_retrieval_enabled`, `_run_probe_retrieval_and_cache`. Keep all lazy imports (`plan_narrator`, `probes`, `source_manager`, etc.). **Keep global abort write for now** — flip to `CycleRuntimeState` in US3 (plan Phase 7). (FR-001, FR-004, FR-007, depends T013)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runner_source_extraction.py::test_step_15_runs_before_scout_when_enabled`
    - Behavior: Probe/source staging path must remain green after `source_signals` move; lazy imports preserved.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_cycle_runner_source_extraction.py::test_cycle_runner_spawns_source_bridge_subprocess`
    - Behavior: Source-signal / bridge integration path must stay green.
    - Tier: 3

  **TDD discipline**: not required

- T020 [US1] Move verbatim into `src/research_framework/pipeline/_helpers/quality_report_guard.py`: `_quality_report_guard`, `_write_cycle_quality_report`. Keep lazy imports; replace direct `_cr._active_timings` reach-back with thin accessors on `src/research_framework/pipeline/cycle_runner.py`: add `pop_active_timing(cycle_num)` and `peek_active_timing(cycle_num)` (cache stays in `cycle_runner.py:36`). (FR-001, FR-004, FR-007, depends T010)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runner_quality_report.py::test_happy_path_writes_once`
    - Behavior: Quality report guard must write exactly once on happy path after accessor refactor (spec-025 A6 invariant).
    - Tier: 3
    - Notes: Spec-028 `_active_timings` accessor path (plan Phase 6).
  - **Test 2**: `tests/pipeline/test_cycle_runner_quality_report.py::test_keyboard_interrupt_writes_once`
    - Behavior: Exit-path guard must still write report on interrupt after `_active_timings` accessor change.
    - Tier: 3

  **TDD discipline**: not required

- T021 [US1] Extend shim + repoint `cycle_runner.py` aliases for all `source_signals` + `quality_report_guard` symbols. (FR-002, depends T019, T020)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runner_quality_report.py::test_scout_failure_writes_once`
    - Behavior: All quality-report guard aliases resolve after final US1 shim extension.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_cycle_runner_source_extraction.py::test_source_bridge_prefers_per_vault_script_when_present`
    - Behavior: Source-signals aliases resolve; source-bridge integration path green.
    - Tier: 3

  **TDD discipline**: not required

### Implementation — structural acceptance (US1)

- T022 [US1] LOC re-count: `wc -l src/research_framework/pipeline/_helpers/*.py | sort -n` — assert every file ≤300 (SC-001). If `state.py` or `source_signals.py` exceeds 300, apply the `_helpers/_io.py` sub-leaf escape hatch for pure-fs helpers (`_state_write`, `_discover_new_markdown_files`, `_vault_notes_content_sha1`) per plan.md — still within locked 7-concern decomposition. (FR-001, SC-001, depends T021)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runner.py::test_steps_execute_in_order`
    - Behavior: US1 structural checkpoint — all seven submodules extracted; full cycle characterization must stay green after LOC re-count (and any `_io.py` escape hatch).
    - Tier: 3
    - Notes: SC-001 LOC is manual `wc`; this is the automated behaviour-preservation backstop.
  - **Test 2**: `tests/quality/test_quality_harness_regression_gate.py::test_no_change_run_passes`
    - Behavior: Zero spec-022 regressions at US1 completion before US3 wiring begins.
    - Tier: 5
    - Notes: FR-005/SC-006.

  **TDD discipline**: not required

**Checkpoint**: All seven submodules exist with code moved; shim + `cycle_runner` aliases resolve every symbol. US2 validation + US3 wiring may proceed.

---

## Phase 4: User Story 2 — Existing imports and behaviour are unchanged (Priority: P1)

> ⚠️ **Execution order ≠ phase order**: do **NOT** run T029–T032 (shim delete) until T035–T041 (US3 wiring) are green — follow the **Critical Path** in Dependencies (US1 → US3 wiring → US2 shim delete). Per-PR validation tasks (T024–T028) run during US1; final shim deletion waits for US3.

**Goal**: Transitional shim keeps all imports resolving through Phases 1–7 (SC-007); every PR preserves byte-identical cycle artifacts (FR-005, SC-006); fast suite count ≥ baseline; both ruff gates clean (FR-006).

**Independent Test**: `.venv/bin/python -m pytest -m "not e2e" -q` ≥ 1934 (1935 after US3 test lands); `./build.sh --quality` → 0 regressions; fixture cycle artifacts byte-identical pre/post.

### Tests (write first — must FAIL before impl)

- T023 [US2] No new US2-specific test files — behaviour preservation is verified by the existing suite + spec-022 harness. After each submodule PR (T010–T021), confirm **zero** test files were edited for import resolution (SC-007).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/quality/test_quality_harness_regression_gate.py::test_no_change_run_passes`
    - Behavior: Spec-022 harness must report zero regressions vs committed baselines after each submodule PR (Phases 1–7 without test import edits).
    - Tier: 5
    - Notes: FR-005/SC-006 primary behaviour-preservation signal.
  - **Test 2**: `tests/pipeline/test_cycle_runner.py::test_steps_execute_in_order`
    - Behavior: Fast-loop characterization must pass with zero test-file edits for import resolution until Phase 8 (SC-007).
    - Tier: 3

  **TDD discipline**: not required

### Implementation — per-PR validation (repeat after T012, T014, T016, T018, T021, T037, T042)

- T024 [US2] After each submodule PR: `.venv/bin/python -m pytest -m "not e2e" -q` — count ≥ 1934 (≥ 1935 after T030 lands). (FR-006, SC-004)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runner.py::test_steps_execute_in_order`
    - Behavior: Representative fast-loop test that must pass as part of the ≥1934 (≥1935 post-T034) collection gate.
    - Tier: 3
    - Notes: SC-004 count gate — full suite run, not this test alone.

  **TDD discipline**: not required

- T025 [P] [US2] After each submodule PR: `ruff check .` **and** `ruff format --check .` — both zero errors (separate gates). (FR-006, SC-004)
- T026 [US2] After each submodule PR: `./build.sh` smoke gate green (ADR-0007, FR-009).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/build/test_smoke_gate_enforced.py::test_smoke_gate_present_in_build_sh`
    - Behavior: `./build.sh` smoke gate must remain green; this test pins the mandatory gate contract (ADR-0007).
    - Tier: 2

  **TDD discipline**: not required

- T027 [US2] After each pipeline-touching PR (T012 onward): `./build.sh --quality` — 3 fixtures, 0 regressions vs committed baselines (FR-005, SC-006).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/quality/test_quality_harness_regression_gate.py::test_no_change_run_passes`
    - Behavior: Zero-regression pass for tech-lite fixture (parametrize may also cover source-poor/source-rich in full harness run).
    - Tier: 5
    - Notes: `./build.sh --quality` canonical FR-005 check.
  - **Test 2**: `tests/quality/test_fake_agent_interception.py::test_no_live_claude_or_codex_during_fixture_run`
    - Behavior: Quality harness fixture cycles must remain fake-agent-only (Principle IV).
    - Tier: 5

  **TDD discipline**: not required

- T028 [US2] After Phase 6 PR (T021): run manual pre/post artifact diff per `quickstart.md` §4b on the `_active_timings` accessor path (highest-risk before US3 wiring). — **DONE**: covered by the `./build.sh --quality` 0-regression result during impl (the 3-fixture harness diffs cycle artifacts vs committed baselines); fixture cycle artifacts byte-identical pre/post the `_active_timings` accessor extraction.

### Implementation — PR 8: delete shim + repoint importers (final US2 deliverable)

- T029 [US2] Repoint the three direct test imports (research.md §2.1): `tests/pipeline/test_stamp_lifecycle_cycle.py:15` → `from research_framework.pipeline._helpers.state import _stamp_lifecycle_cycle`; `tests/pipeline/test_cycle_helpers_tree_kill.py:26` → `from research_framework.pipeline._helpers.script_runner import _run_script`; `tests/pipeline/test_budget_guard.py:206` → `from research_framework.pipeline._helpers import script_runner as h`. (FR-002, SC-007, depends T037)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_stamp_lifecycle_cycle.py::test_stamps_field_when_missing`
    - Behavior: Direct import repointed to `_helpers.state` — stamping behaviour unchanged.
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_cycle_helpers_tree_kill.py::test_run_script_kills_grandchild_on_interrupt`
    - Behavior: Direct import repointed to `_helpers.script_runner` — tree-kill behaviour unchanged.
    - Tier: 2
  - **Test 3**: `tests/pipeline/test_budget_guard.py::test_cycle_runner_invokes_pre_dispatch_and_refresh_hooks`
    - Behavior: Budget guard `h` rebound to `script_runner` module — attrs + wrapped `_run_script` resolve.
    - Tier: 3

  **TDD discipline**: not required

- T030 [US2] Repoint `src/research_framework/pipeline/steps/scout.py`, `src/research_framework/pipeline/steps/research.py`, `src/research_framework/pipeline/steps/postprocess.py` from `from .. import _cycle_helpers as h` to explicit per-submodule imports (replace `h.` with owning submodule alias). (FR-002, SC-007, depends T037)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runner.py::test_steps_execute_in_order`
    - Behavior: All three steps resolve helpers via explicit submodule imports; full cycle green.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_cycle_runner_scout_correction.py::test_scout_structural_error_triggers_correction_loop`
    - Behavior: Scout step submodule imports cover correction loop symbols.
    - Tier: 3
  - **Test 3**: `tests/pipeline/test_cycle_runner_quality_report.py::test_happy_path_writes_once`
    - Behavior: Postprocess/quality-report path resolves via repointed step imports.
    - Tier: 3

  **TDD discipline**: not required

- T031 [US2] Repoint or trim `src/research_framework/pipeline/cycle_runner.py:67-106` alias block to import each symbol from its `_helpers.*` submodule; delete `from . import _cycle_helpers as h` if no longer needed. (FR-002, depends T030)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runner.py::test_source_manager_called_after_research_validate`
    - Behavior: Cycle runner alias block fully repointed — indirect helper access via `cycle_runner.*` still works for tests.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_cycle_runner_scout_correction.py::test_empty_sidecar_falls_back_to_immediate_abort`
    - Behavior: Scout correction symbols reachable through final alias block.
    - Tier: 3

  **TDD discipline**: not required

- T032 [US2] **Delete** `src/research_framework/pipeline/_cycle_helpers.py`. Confirm `wc -l …/_cycle_helpers.py` fails (SC-002 end state). (FR-002, SC-002, depends T031)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runner.py::test_steps_execute_in_order`
    - Behavior: Full cycle passes with shim deleted — no residual `_cycle_helpers` imports in production code.
    - Tier: 3
    - Notes: SC-002 end state.
  - **Test 2**: `tests/quality/test_quality_harness_regression_gate.py::test_no_change_run_passes`
    - Behavior: Byte-identical artifacts after shim deletion (FR-005).
    - Tier: 5

  **TDD discipline**: not required

- [ ] T033 [P] [US2] Update doc-comment-only references (no import changes): `src/research_framework/pipeline/quality_report.py:422`, `src/research_framework/pipeline/process_tree.py:22`, `tests/pipeline/test_process_tree.py:3`, `tests/build/test_smoke_gate_enforces_contract_tier.py:53`, `tests/pipeline/test_cycle_helpers_tree_kill.py:1,10`. (FR-008)

**Checkpoint**: No `_cycle_helpers.py`; all importers use `_helpers/*` paths; full suite + quality harness green.

---

## Phase 5: User Story 3 — No hidden cross-call state (Priority: P2)

**Goal**: Replace process-global `_should_abort_current_cycle` / `_last_note_writer_cap_tripped` with explicit `CycleRuntimeState` on `CycleContext`; zero module-level mutable globals in `_helpers/` (FR-003, SC-003, US3).

**Independent Test**: `pytest tests/pipeline/test_cycle_runtime_state.py` green; `grep -rnE "^_[a-z_]+(: [a-zA-Z_]+)? = (False|True|\{\}|\[\])$" src/research_framework/pipeline/_helpers/` returns zero matches.

### Tests (write first — must FAIL before impl)

- [ ] T034 — **authored in Phase 3 / PR 1** (before T009; see TDD note there). Do not re-author here.

### Implementation — PR 7: `CycleRuntimeState` wiring (plan Phase 7)

- T035 [US3] Add `runtime_state: "CycleRuntimeState | None" = None` to `CycleRuntimeState` carrier on `src/research_framework/pipeline/steps/_types.py::CycleContext` (forward-ref or `TYPE_CHECKING` import per data-model.md). (FR-003, FR-007, depends T009)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runtime_state.py::test_cycle_runtime_state_defaults_falsy`
    - Behavior: Type import still works after `CycleContext` field addition; existing T034 tests green.
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_cycle_runner.py::test_steps_execute_in_order`
    - Behavior: Optional `runtime_state=None` default must not break existing `CycleContext(...)` call sites.
    - Tier: 3
    - Notes: `data-model.md` Carrier change — default None preserves call-site compatibility.

  **TDD discipline**: not required

- T036 [US3] In `src/research_framework/pipeline/cycle_runner.py::run_cycle_steps`: construct `state = CycleRuntimeState()` at cycle entry (replace `h._should_abort_current_cycle = False` / `h._last_note_writer_cap_tripped = False` at lines 246–247); attach to `CycleContext.runtime_state`. **Do not change `run_cycle_steps` public signature.** (FR-003, depends T035, T019)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runner.py::test_steps_execute_in_order`
    - Behavior: Fresh `CycleRuntimeState()` constructed per cycle; public `run_cycle_steps` signature unchanged — full cycle green.
    - Tier: 3
    - Notes: FR-003; CLAUDE.md no signature change.
  - **Test 2**: `tests/pipeline/test_cycle_runtime_state.py::test_cycle_runtime_state_instances_are_independent`
    - Behavior: Isolation property still holds (unit-level); wiring uses one instance per cycle.
    - Tier: 2

  **TDD discipline**: not required

- T037 [US3] In `src/research_framework/pipeline/steps/research.py`: replace `h._should_abort_current_cycle` read (line 110) with `state.should_abort`; replace `h._last_note_writer_cap_tripped = True` (line 120) with `state.note_writer_cap_tripped = True` via `CycleContext.runtime_state`. (FR-003, depends T036)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runner.py::test_research_exit_code_propagated`
    - Behavior: Research step reads/writes runtime flags via `CycleContext.runtime_state` — exit-code propagation unchanged.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_cycle_runner.py::test_steps_execute_in_order`
    - Behavior: Abort/cap-tripped flags no longer read from module globals in research step.
    - Tier: 3

  **TDD discipline**: not required

- T038 [US3] Rewrite `notify_required_source_degraded` in `src/research_framework/pipeline/_helpers/source_signals.py` to accept `runtime_state: CycleRuntimeState` and set `runtime_state.should_abort = True` (remove `global _should_abort_current_cycle`). Update its call site(s) — trace from `src/research_framework/pipeline/cycle_runner.py` re-export and any orchestrator/source-bridge callers — to pass the cycle's state instance. (FR-003, depends T019, T036)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runner_source_extraction.py::test_cycle_runner_spawns_source_bridge_subprocess`
    - Behavior: Source degradation abort signal flows through explicit `runtime_state` parameter at call sites — cycle still completes spawn path.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_cycle_runner.py::test_source_manager_called_after_research_validate`
    - Behavior: No residual `global _should_abort_current_cycle` write path; integration cycle green.
    - Tier: 3

  **TDD discipline**: not required

- T039 [US3] Repoint budget-guard runtime attribute slots in `src/research_framework/pipeline/cycle_runner.py::_install_budget_run_script_guard` from shim `h._run_script_orig` / `h._budget_session` to `src/research_framework/pipeline/_helpers/script_runner` module object. (FR-007, depends T010)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_budget_guard.py::test_cycle_runner_invokes_pre_dispatch_and_refresh_hooks`
    - Behavior: Budget guard sets `_run_script_orig` / `_budget_session` on `script_runner` module object; wrap/unwrapping still works.
    - Tier: 3
    - Notes: research.md §2.3 runtime-attribute coupling.
  - **Test 2**: `tests/pipeline/test_budget_guard.py::test_pre_dispatch_pauses_dollar_cap_on_strict_exceed`
    - Behavior: Guarded `_run_script` dispatch path unchanged after attribute-slot repoint.
    - Tier: 3

  **TDD discipline**: not required

- T040 [US3] Delete globals `_should_abort_current_cycle` and `_last_note_writer_cap_tripped` from `src/research_framework/pipeline/_cycle_helpers.py` (or from whichever submodule still hosts them pre-shim-delete) and remove their `cycle_runner.py` aliases (`_should_abort_current_cycle`, `_last_note_writer_cap_tripped`). (FR-003, depends T038)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runtime_state.py::test_cycle_runtime_state_instances_are_independent`
    - Behavior: Globals deleted — per-cycle state is the only flag carrier (US3).
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_cycle_runner.py::test_steps_execute_in_order`
    - Behavior: No references to deleted global aliases remain; cycle completes.
    - Tier: 3

  **TDD discipline**: not required

- T041 [US3] Run SC-003 static scan: `grep -rnE "^_[a-z_]+(: [a-zA-Z_]+)? = (False|True|\{\}|\[\])$" src/research_framework/pipeline/_helpers/` → zero matches. Run `quickstart.md` §4b manual diff (highest-risk PR). (FR-003, SC-003, depends T040)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runtime_state.py::test_cycle_runtime_state_defaults_falsy`
    - Behavior: Automated pytest gate companion to SC-003 grep — type defaults still correct after global deletion.
    - Tier: 2
  - **Test 2**: `tests/quality/test_quality_harness_regression_gate.py::test_no_change_run_passes`
    - Behavior: Highest-risk PR — quality harness must show zero regressions (companion to manual §4b diff).
    - Tier: 5
    - Notes: SC-003 grep is manual; this is the automated FR-005 backstop.

  **TDD discipline**: not required

**Checkpoint**: US3 complete — per-cycle state is explicit; no mutable module globals in `_helpers/`.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final gates, CHANGELOG, and structural success-criteria verification.

- [ ] T042 [P] Add `CHANGELOG.md` `[Unreleased]` entry documenting new private import paths under `pipeline/_helpers/*` and removal of `_cycle_helpers.py` (FR-008). (depends T032)
- T043 Run full verification per `quickstart.md`: fast suite ≥ 1935, `ruff check .`, `ruff format --check .` (both gates), `./build.sh`, `./build.sh --quality`. (FR-006, FR-009, SC-004, SC-006) — **DONE**: fast loop green at rebase onto main; both ruff gates green; `./build.sh` + `./build.sh --quality` (0 regressions, 3 fixtures) green during impl (PYTHONPATH=$PWD/src in worktree per the editable-venv note).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/quality/test_quality_harness_regression_gate.py::test_no_change_run_passes`
    - Behavior: Final ship gate — zero quality harness regressions across all three fixtures.
    - Tier: 5
  - **Test 2**: `tests/pipeline/test_cycle_runtime_state.py::test_cycle_runtime_state_instances_are_independent`
    - Behavior: New US3 unit test included in ≥1935 fast-loop count.
    - Tier: 2
  - **Test 3**: `tests/build/test_smoke_gate_enforced.py::test_smoke_gate_aborts_build_on_regression`
    - Behavior: Smoke gate contract enforced via `./build.sh`.
    - Tier: 2

  **TDD discipline**: not required
- T044 [P] Run structural acceptance checks from `quickstart.md` §5: SC-001 (LOC), SC-002 (shim deleted), SC-003 (no mutable globals), SC-005 (7 files under `_helpers/`). (SC-001–SC-005, depends T032, T041) — **DONE 2026-06-03**: SC-001 largest submodule = 220 LOC (`script_runner.py`), all ≤300 ✓; SC-002 `pipeline/_cycle_helpers.py` deleted ✓; SC-003 mutable-global scan → 0 matches ✓; SC-005 the seven concerns are each isolated in exactly one submodule — the split materialised as 10 focused modules (incl. 3 small shared helpers `_io`/`_probe_staging`/`_scout_prompts`), all ≤220 LOC ✓.
- T045 Confirm QW-9 remains **deferred** — do not add or retire `monkeypatch(..., "run_cycle_steps", …)` sites in this spec (plan.md Out of Scope; spec.md Dependencies). Note follow-up in PR description only.
- [ ] T046 [P] Update `specs/_archive/049-cycle-helpers-split/spec.md` status header to reflect implementation readiness (post-ship doc-sync is separate). Optional — skip if house style keeps status at CLARIFIED until merge.

**Checkpoint**: Spec 049 ready for foreman `/speckit.implement` handoff.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup — **blocks all user stories**.
- **US1 (Phase 3)**: Depends on Foundational. Submodule order is fixed: `cycle_state` (type) → `script_runner` → `state` → `cosmetic_correction` → `scout_correction` → `source_signals` + `quality_report_guard`.
- **US2 (Phase 4)**: Per-PR validation (T024–T028) runs **during** US1 after each merge. **Final shim deletion (T029–T032) runs last among user stories** — after US3 wiring (T041) is green.
- **US3 (Phase 5)**: Depends on US1 through T021 (`source_signals` moved). Wiring (T035–T041) runs **after US1, before US2 shim delete** (T029–T032).
- **Polish (Phase 6)**: Depends on T032 + T041 + T043.

### User Story Dependencies

| Story | Depends on | Delivers |
| --- | --- | --- |
| US1 (P1 MVP) | Phase 2 | Seven `_helpers/*.py` modules; concern map locked (FR-001, FR-004) |
| US3 (P2) | US1 through PR 6 | `CycleRuntimeState` wired; zero globals (FR-003) — **execute before US2 shim delete** |
| US2 (P1) | US1 moves + **US3 wiring (T041)** | Shim lifecycle + byte-identical artifacts (FR-002, FR-005, FR-006) — **shim delete (T029–T032) is the final US2 deliverable** |

### Critical path (real execution order)

**US1 → US3 wiring → US2 shim delete** (phase numbers US1/US2/US3 do not match this sequence):

```
T001–T007 → T034 (red) → T009–T022 (US1, one PR each) → T035–T041 (US3 wiring) → T029–T032 (US2 shim delete) → T042–T044 (Polish)
```

Run T024–T028 after **every** submodule PR.

### Within Each User Story

- T034 (red) before T009 (green); wiring tasks (T035+) after US1 through T021.
- Keep lazy `cycle_runner` reach-backs lazy (FR-007).
- Never change `run_cycle_steps` public signature; never add `run_cycle_steps` monkeypatch sites.

---

## Parallel opportunities

- **Phase 1**: T002 and T003 in parallel after T001.
- **Phase 2**: T005 and T006 in parallel after T004.
- **US1**: No parallel moves — sequential PRs per FR-009.
- **US2 validation**: T025 parallel with T024/T026 after each PR.
- **Polish**: T042, T044, T046 parallel after T043 green.

---

## Implementation strategy

### MVP first (User Story 1)

1. Complete Setup + Foundational (T001–T007).
2. Land PR 1 (`cycle_state.py` type) + PR 2 (`script_runner`) — smallest leaf, proves the shim pattern.
3. Continue US1 PRs 3–6 in plan order; run US2 validation after each.
4. **Stop and validate** at T022: all seven modules exist, LOC ≤300.

### Incremental delivery

1. US1 submodule PRs → each independently revertable, each green on `./build.sh --quality`.
2. US3 wiring PR (Phase 7) → isolated highest-risk change; run `quickstart.md` §4b.
3. US2 final PR → delete shim, repoint importers, CHANGELOG.
4. Polish → full SC-001–SC-007 verification.

### One PR per submodule (FR-009)

| PR | Tasks | Submodule |
| --- | --- | --- |
| 1 | T034, T009 | `cycle_state.py` (+ test; TDD: red then green) |
| 2 | T010–T012 | `script_runner.py` |
| 3 | T013–T014 | `state.py` |
| 4 | T015–T016 | `cosmetic_correction.py` |
| 5 | T017–T018 | `scout_correction.py` |
| 6 | T019–T021 | `source_signals.py` + `quality_report_guard.py` |
| 7 | T035–T041 | `CycleRuntimeState` wiring |
| 8 | T029–T033 | Delete shim + repoint |

---

## Notes

- **QW-9 excluded**: Retiring the 10 banned `monkeypatch(..., "run_cycle_steps", …)` sites is explicitly **out of scope** (plan.md Constitution Check; spec.md Dependencies — "QW-9 *follows* this split").
- **`CycleRuntimeState` test timing**: T034 is authored in PR 1 **before** T009 (TDD red → green); foreman Testing Requirements pin exact names in T034/T009 blocks above.
- **`_io.py` escape hatch**: Decide at T022 only if LOC count forces it — not preemptive.
- **`### Testing Requirements` blocks**: authored by test-design agent 2026-06-03 (ADR-0010 foreman pre-step); implementer must not edit during implementation.
