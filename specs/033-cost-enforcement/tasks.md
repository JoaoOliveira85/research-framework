---
description: "Task list for spec 033 — Cost Enforcement"
---

# Tasks: Cost Enforcement (Spec 033)

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Input**: Design documents from `/specs/033-cost-enforcement/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅
**Hard runtime dependency**: Spec 028 sidecar v1.1 producer on `main` (contract merged; implementation is Wave 1 of revival sprint). Tasks may use committed fixture sidecars under `tests/fixtures/` for tier-2/3 before 028 ships.

**Tests**: REQUIRED per plan.md § Acceptance coverage and research.md §8 — tier-2 unit, tier-3 integration, tier-5 e2e for US1 pause/resume. Write tests FIRST per constitution Principle III.

**Organization**: Phases follow spec user-story priority (US1 → US2 → US3 → US4). **Phase 4** implements FR-014/FR-015 (approval gates) — no separate user story in spec.md but on the critical path between US1 and US2 (US2 lands in Phase 5). Parallel streams per plan.md: **A** `cost_estimator.py` ∥ **B** `budget_guard.py` → **C** `cycle_runner.py` + **D** `cli/research*.py`.

**Terminology**: Stage names use **snake_case** (`note_writer`, not `note-writer`). Sidecar reads use **schema_version `"1.1"`** only under `agent-calls/*.json` (never legacy `1.0` flat paths).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Maps to spec.md user stories (US1–US4) where applicable
- Include exact file paths in descriptions

## Path Conventions

Single-project structure (per `plan.md` § Project Structure):

- Source: `src/research_framework/pipeline/`, `src/research_framework/cli/`, `src/research_framework/quality/metrics/`
- Tests: `tests/pipeline/`, `tests/e2e/`, `tests/fixtures/cost_enforcement/`
- Templates: `dist-templates/cost-estimates.yaml`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Module scaffolding, bundled ceilings, optional `[budget]` extra, test skeletons.

- T001 Create `src/research_framework/pipeline/cost_estimator.py` and `src/research_framework/pipeline/budget_guard.py` with module docstrings referencing `specs/033-cost-enforcement/contracts/*.contract.md`
- T002 [P] Add `dist-templates/cost-estimates.yaml` with `ceilings:` entries for `plan_narrator`, `scout`, `research`, `note_writer`, `verifier`, `probe_retrieval`, and `default` per `contracts/cost-estimator.contract.md` §5
- T003 [P] Add `[project.optional-dependencies] budget = ["tiktoken>=0.6"]` to `pyproject.toml` — **optional extra only**; core install MUST NOT require `tiktoken` (Principle V)
- T004 [P] Create test skeletons `tests/pipeline/test_cost_estimator.py`, `tests/pipeline/test_budget_guard.py`, `tests/pipeline/test_budget_markers.py`, `tests/e2e/test_budget_pause_resume.py` with appropriate pytest markers (tier-2/3/5)
- T005 [P] Create `tests/fixtures/cost_enforcement/agent-calls/` with minimal v1.1 sidecar JSON fixtures (`schema_version: "1.1"`, `agent`, `stage`, `cost_usd`, `tokens_in`, `tokens_out`, `status`) for tier-2/3 tests

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Typed settings, marker dataclasses, sidecar v1.1 reader, atomic marker I/O, TTY helper. **Blocks all user stories.**

**⚠️ CRITICAL**: No user-story work until this phase completes.

- T006 Extend `LimitsSettings` in `src/research_framework/pipeline/settings.py` with `cycle_budget_usd`, `codex_token_budget`, `cycle_wallclock_budget_minutes`, `cycle_budget_warn_at`, `tier_thresholds`, `estimator_calibration` per `data-model.md` § `LimitsSettings` (FR-001, FR-012, FR-017)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_settings.py::test_limits_settings_loads_cycle_budget_and_codex_fields`
    - Behavior: Load fixture settings with `limits.cycle_budget_usd`, `codex_token_budget`, `cycle_wallclock_budget_minutes`, `tier_thresholds`, `estimator_calibration`; assert typed `LimitsSettings` fields match `data-model.md`.
    - Tier: 2
    - Notes: FR-001, FR-012, FR-017

  **TDD discipline**: required
- T007 Add **top-level** `approval_gates: list[str]` on `VaultSettings` in `src/research_framework/pipeline/settings.py` — MUST NOT nest under `limits:` (FR-014, `data-model.md` § `ApprovalGatesSettings`)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_settings.py::test_approval_gates_loaded_from_top_level_not_limits`
    - Behavior: Fixture with root `approval_gates: [research]` and absent `limits.approval_gates`; assert `VaultSettings.approval_gates == ['research']`. MUST fail if nested under `limits:`.
    - Tier: 2
    - Notes: FR-014; top-level placement per PR #26

  **TDD discipline**: required
- T008 [P] Implement legacy alias migration `budget_usd` → `limits.cycle_budget_usd` in `settings.py` loader with one-time deprecation WARN (quickstart.md §1)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_settings.py::test_budget_usd_alias_migrates_to_cycle_budget_usd`
    - Behavior: Load legacy `limits.budget_usd`; assert value lands on `cycle_budget_usd` and deprecation WARN emitted once per quickstart §1.
    - Tier: 2
    - Notes: FR-001 migration

  **TDD discipline**: required
- T009 Define `CycleSpendTally` dataclass in `src/research_framework/pipeline/budget_guard.py` per `data-model.md` § `CycleSpendTally`

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_guard.py::test_cycle_spend_tally_initial_state`
    - Behavior: Construct fresh `CycleSpendTally`; assert `actual_usd == 0`, `actual_codex_tokens == 0`, `warn_emitted is False` per `data-model.md`.
    - Tier: 2

  **TDD discipline**: required
- T010 [P] Define `BudgetPausedMarker` dataclass + `to_json_dict()` / `from_path()` in `budget_guard.py` matching `contracts/budget-marker.contract.md` §2 (`pause_reason` enum only — never `approval_required`)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_markers.py::test_budget_paused_marker_roundtrip_json_dict`
    - Behavior: Build `BudgetPausedMarker` for each `pause_reason`; `to_json_dict()` then `from_path()` round-trip preserves required fields; `pause_reason` never `approval_required`.
    - Tier: 2
    - Notes: budget-marker.contract.md §2.2

  **TDD discipline**: required
- T011 [P] Define `ApprovalRequiredMarker` dataclass in `budget_guard.py` matching `contracts/approval-marker.contract.md` §3

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_markers.py::test_approval_required_marker_roundtrip_json_dict`
    - Behavior: Build `ApprovalRequiredMarker`; round-trip via temp file; all §3.1 required fields present.
    - Tier: 2
    - Notes: approval-marker.contract.md §3.1

  **TDD discipline**: required
- T012 Implement `list_sidecars_v11(vault_dir: Path, cycle_num: int) -> list[dict]` in `budget_guard.py` — glob `_pipeline/cycles/cycle-NNN/agent-calls/*.json`, require `schema_version == "1.1"`, ignore retired flat `cycle-NNN-*.cost.json` paths per `specs/028-dispatch-telemetry/contracts/sidecar-v1.contract.md` §0

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_guard.py::test_list_sidecars_v11_reads_agent_calls_only`
    - Behavior: Vault tree with `cycle-001/agent-calls/*.json` v1.1 fixtures AND legacy flat `cycle-001-scout.cost.json`; assert returned list length equals v1.1 count only and every dict has `schema_version == '1.1'`.
    - Tier: 2
    - Notes: 028 sidecar-v1.contract.md §0
  - **Test 2**: `tests/pipeline/test_budget_guard.py::test_list_sidecars_v11_ignores_non_1_1_schema`
    - Behavior: Drop a fixture with `schema_version: '1.0'` under `agent-calls/`; assert it is excluded from results.
    - Tier: 2
    - Notes: 028 §0 path discriminator

  **TDD discipline**: required
- T013 Implement `refresh_actuals(vault_dir, cycle_num, tally: CycleSpendTally) -> None` in `budget_guard.py` — sum all `cost_usd` (include `status: failed`), sum `tokens_in+tokens_out` where `agent == "codex"` (research.md §2, FR-013)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_guard.py::test_refresh_actuals_sums_multi_batch_and_retry_sidecars`
    - Behavior: Pre-written fixtures: `note_writer-batch-1.json`, `note_writer-batch-2.json`, `plan_narrator.json`, `plan_narrator-2.json` (quality retry), one `status: failed` row; hand-sum expected `cost_usd` and codex tokens; assert `CycleSpendTally` matches. MUST NOT invoke dispatch.
    - Tier: 2
    - Notes: 028 §1.1 batch + numeric-suffix families; quality-retry budget accounting

  **TDD discipline**: required
- T014 [P] Implement `atomic_write_json_marker(final_path: Path, payload: dict) -> None` via temp file + `os.replace` in `budget_guard.py` per `contracts/budget-marker.contract.md` §3

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_markers.py::test_atomic_write_json_marker_uses_os_replace`
    - Behavior: Mock or spy `os.replace`; write marker payload; assert temp file removed and final path contains valid JSON; reader never sees partial file (inject fault before replace to assert final unchanged).
    - Tier: 2
    - Notes: budget-marker.contract.md §3

  **TDD discipline**: required
- T015 [P] Implement `is_interactive_tty() -> bool` as `sys.stdin.isatty() and sys.stdout.isatty()` in `src/research_framework/cli/_tty.py` (FR-016)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/cli/test_tty.py::test_is_interactive_tty_requires_both_stdin_and_stdout`
    - Behavior: Patch `sys.stdin.isatty` / `sys.stdout.isatty` four combinations; only both True returns True (FR-016).
    - Tier: 2
    - Notes: FR-016

  **TDD discipline**: required
- T016 [P] Tier-2 tests for `BudgetPausedMarker` JSON Schema `allOf` conditionals (`dollar_cap_exceeded` → `cycle_budget_usd > 0`; wallclock/codex required fields) in `tests/pipeline/test_budget_markers.py`

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_markers.py::test_budget_marker_schema_dollar_cap_exceeded_positive_cycle_budget`
    - Behavior: Validate `BudgetPausedMarker.to_json_dict()` with `pause_reason: dollar_cap_exceeded` and `cycle_budget_usd: 0.01` against draft-2020-12 schema in contract §2.4; MUST pass. Same payload with `cycle_budget_usd: 0` MUST fail `allOf` conditional.
    - Tier: 2
    - Notes: budget-marker.contract.md §2.4 first `allOf` branch
  - **Test 2**: `tests/pipeline/test_budget_markers.py::test_budget_marker_schema_wallclock_exceeded_requires_elapsed_and_cap`
    - Behavior: `pause_reason: wallclock_exceeded` without `wallclock_elapsed_seconds`/`wallclock_cap_seconds` MUST fail; with both fields MUST pass.
    - Tier: 2
    - Notes: §2.4 second `allOf` branch
  - **Test 3**: `tests/pipeline/test_budget_markers.py::test_budget_marker_schema_codex_token_cap_exceeded_requires_token_fields`
    - Behavior: `pause_reason: codex_token_cap_exceeded` without `codex_tokens_cumulative`/`codex_token_budget` MUST fail; populated MUST pass.
    - Tier: 2
    - Notes: §2.4 third `allOf` branch
  - **Test 4**: `tests/pipeline/test_budget_markers.py::test_budget_marker_schema_rejects_approval_required_pause_reason`
    - Behavior: Any payload with `pause_reason: approval_required` MUST fail enum validation; approval uses `APPROVAL_REQUIRED` file only.
    - Tier: 2
    - Notes: §2.2 forbidden value

  **TDD discipline**: not required
- T017 [P] Tier-2 tests for `ApprovalRequiredMarker` schema (`prompt_preview` max 500 chars) in `tests/pipeline/test_budget_markers.py`

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_markers.py::test_approval_marker_schema_accepts_prompt_preview_500_chars`
    - Behavior: Marker with exactly 500-char `prompt_preview` validates against approval schema §3.3.
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_budget_markers.py::test_approval_marker_schema_rejects_prompt_preview_over_500_chars`
    - Behavior: 501-char `prompt_preview` MUST fail JSON Schema validation.
    - Tier: 2
    - Notes: approval-marker.contract.md §3.1

  **TDD discipline**: not required
- T018 [P] Tier-2 test `refresh_actuals` sums failed-call sidecars and codex token rows using `tests/fixtures/cost_enforcement/agent-calls/` in `tests/pipeline/test_budget_guard.py`

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_guard.py::test_refresh_actuals_includes_failed_sidecar_cost_usd`
    - Behavior: Fixture sidecar with `status: failed` and non-zero `cost_usd`; after `refresh_actuals`, `actual_usd` includes that row.
    - Tier: 2
    - Notes: 028 §4; FR-013 failed-call billing
  - **Test 2**: `tests/pipeline/test_budget_guard.py::test_refresh_actuals_sums_codex_tokens_only_for_codex_agent`
    - Behavior: Mix claude + codex fixtures; assert `actual_codex_tokens` equals sum of `tokens_in+tokens_out` on codex rows only.
    - Tier: 2
    - Notes: FR-017 tally

  **TDD discipline**: not required

**Checkpoint**: Foundation ready — Streams A/B can proceed; US1 implementation can start.

---

## Phase 3: User Story 1 — Cycle budget cap enforces graceful pause (Priority: P1) 🎯 MVP

**Goal**: Hard dollar cap, parallel codex token cap, wall-clock backstop — inclusive `<=` pre-check, strict `>` pause, `BUDGET_PAUSED` marker, `./vault research --resume` with TTY/headless `--force-budget` UX.

**Independent Test** (spec.md): Fixture crosses `$1.00` cap by stage 3 → pause before overshoot → `BUDGET_PAUSED` exists → partial state preserved → `--resume` after cap bump completes cycle.

### Tests for User Story 1 (write FIRST)

- T019 [P] [US1] Tier-2: inclusive `<=` allows dispatch when `actual_usd + estimate_usd == cycle_budget_usd` in `tests/pipeline/test_budget_guard.py` (FR-002, clarification Q5)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_guard.py::test_pre_dispatch_allows_dispatch_when_actual_plus_estimate_equals_cap`
    - Behavior: Tally at cap boundary with conservative estimate; `check_pre_dispatch` returns `None` (no pause). Inclusive `<=` per FR-002 Q5.
    - Tier: 2
    - Notes: FR-002

  **TDD discipline**: not required
- T020 [P] [US1] Tier-2: strict `>` returns `dollar_cap_exceeded` pause payload when estimate would exceed cap

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_guard.py::test_pre_dispatch_pauses_dollar_cap_on_strict_exceed`
    - Behavior: When `actual_usd + estimate_usd > cycle_budget_usd`, return pause result with `pause_reason: dollar_cap_exceeded` and fields for marker write.
    - Tier: 2
    - Notes: FR-002 strict `>`

  **TDD discipline**: not required
- T021 [P] [US1] Tier-2: `wallclock_exceeded` and `codex_token_cap_exceeded` branches with conditional marker fields (FR-012, FR-017)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_guard.py::test_pre_dispatch_wallclock_exceeded_marker_conditional_fields`
    - Behavior: Monotonic elapsed strictly over cap; pause payload includes `wallclock_elapsed_seconds` and `wallclock_cap_seconds` suitable for §2.3 schema branch.
    - Tier: 2
    - Notes: FR-012
  - **Test 2**: `tests/pipeline/test_budget_guard.py::test_pre_dispatch_codex_token_cap_exceeded_marker_conditional_fields`
    - Behavior: Codex tally + estimate strictly exceeds `codex_token_budget`; pause payload includes `codex_tokens_cumulative` and `codex_token_budget`.
    - Tier: 2
    - Notes: FR-017

  **TDD discipline**: not required
- T022 [P] [US1] Tier-2: local backend (`cost_usd: 0.0`) excluded from dollar-cap numerator; tokens still logged (FR-013)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_guard.py::test_pre_dispatch_excludes_local_zero_cost_from_dollar_increment`
    - Behavior: Dispatch estimate for `agent: local` / `cost_usd: 0` does not increase dollar-cap numerator; codex/claude paths still increment normally.
    - Tier: 2
    - Notes: FR-013

  **TDD discipline**: not required
- T023 [P] [US1] Tier-3: `BUDGET_PAUSED` written atomically and present before simulated exit in `tests/pipeline/test_budget_markers.py` (FR-004)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_markers.py::test_pause_for_budget_writes_marker_before_exit`
    - Behavior: Call `pause_for_budget` with pytest `raises(SystemExit)`; assert `_pipeline/BUDGET_PAUSED` exists and parses before exit; use atomic-write temp pattern.
    - Tier: 3
    - Notes: FR-004

  **TDD discipline**: not required
- T024 [US1] Tier-3: `research_resume.py` refuses resume when sidecar v1.1 sum still exceeds cap without `--force-budget` (FR-005)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/cli/test_research_resume_budget.py::test_resume_refuses_when_sidecar_sum_still_over_cap`
    - Behavior: Vault with `BUDGET_PAUSED` + pre-written sidecars summing over `cycle_budget_usd`; invoke resume CLI headless; exit non-zero without `--force-budget`. Re-sum sidecars per contract §4 step 3.
    - Tier: 3
    - Notes: FR-005; fake_agent not required

  **TDD discipline**: not required
- T025 [US1] Tier-5: `tests/e2e/test_budget_pause_resume.py` — mid-cycle pause at cap → operator bumps `cycle_budget_usd` → `--resume` completes remaining stages (SC-002)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/e2e/test_budget_pause_resume.py::test_mid_cycle_budget_pause_resume_completes_cycle`
    - Behavior: Fake-agent fixture vault with low `cycle_budget_usd`; run partial cycle until pause; bump cap in settings; `./vault research --resume` completes remaining stages. MUST use `tests/_helpers/fake_agent.py`; no live claude/codex.
    - Tier: 5
    - Notes: SC-002

  **TDD discipline**: not required

### Implementation for User Story 1

- T026 [P] [US1] Implement `estimate_dispatch()` in `src/research_framework/pipeline/cost_estimator.py` — `p95_history` (≥3 samples) and `default_ceiling` paths per `contracts/cost-estimator.contract.md` §2–5; log `estimation_method` (FR-003 default tier)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_cost_estimator.py::test_estimate_dispatch_p95_history_with_three_samples`
    - Behavior: Three+ pre-written historical sidecars for stage; method `p95_history`; estimate >= max historical cost (conservative).
    - Tier: 2
    - Notes: cost-estimator.contract.md §4
  - **Test 2**: `tests/pipeline/test_cost_estimator.py::test_estimate_dispatch_default_ceiling_without_history`
    - Behavior: <3 samples; returns bundled `cost-estimates.yaml` ceiling with `estimation_method: default_ceiling`.
    - Tier: 2
    - Notes: §5

  **TDD discipline**: required
- T027 [US1] Add import-gated `tiktoken` branch in `cost_estimator.py` — `cl100k_base` + `estimator_calibration.claude` (default 1.15), `o200k_base` for codex (1.0); output cost = `max_tokens × output_rate`; fail-closed to `default_ceiling` on any exception (FR-003 optional path — **never** mandatory import at package load)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_cost_estimator.py::test_estimate_dispatch_tiktoken_when_budget_extra_available`
    - Behavior: Simulate importable `tiktoken` (skip if extra not installed); assert `estimation_method: tiktoken` for claude/codex agents.
    - Tier: 2
    - Notes: FR-003 optional path
  - **Test 2**: `tests/pipeline/test_cost_estimator.py::test_estimate_dispatch_fail_closed_to_ceiling_on_tiktoken_error`
    - Behavior: Force exception inside tiktoken branch; estimate equals per-stage ceiling, never below historical p95.
    - Tier: 2
    - Notes: §2 fail-closed
  - **Test 3**: `tests/pipeline/test_cost_estimator.py::test_estimate_dispatch_claude_calibration_factor_default_115`
    - Behavior: Assert Claude token estimate multiplied by default calibration 1.15 from settings.
    - Tier: 2
    - Notes: §6

  **TDD discipline**: required
- T028 [US1] Implement `check_pre_dispatch(...)` in `budget_guard.py` — dollar (`>` strict exceed), wallclock (monotonic anchor), codex token parallel cap; return typed pause result or `None` (FR-002, FR-012, FR-017)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_budget_guard.py::test_pre_dispatch_allows_dispatch_when_actual_plus_estimate_equals_cap`
    - Behavior: Satisfies T019 — inclusive `<=` at cap boundary returns `None`.
    - Tier: 2
    - Notes: Implemented by T019; T028 must not regress
  - **Test 2**: `tests/pipeline/test_budget_guard.py::test_pre_dispatch_pauses_dollar_cap_on_strict_exceed`
    - Behavior: Satisfies T020 — strict `>` yields `dollar_cap_exceeded` pause payload.
    - Tier: 2
  - **Test 3**: `tests/pipeline/test_budget_guard.py::test_pre_dispatch_wallclock_exceeded_marker_conditional_fields`
    - Behavior: Satisfies T021 wallclock branch with §2.3 conditional fields.
    - Tier: 2
  - **Test 4**: `tests/pipeline/test_budget_guard.py::test_pre_dispatch_codex_token_cap_exceeded_marker_conditional_fields`
    - Behavior: Satisfies T021 codex branch with `codex_tokens_cumulative` and `codex_token_budget` populated.
    - Tier: 2

  **TDD discipline**: required
- T029 [US1] Implement `pause_for_budget(vault_dir, marker: BudgetPausedMarker) -> NoReturn` — atomic write `_pipeline/BUDGET_PAUSED`, stderr message with resume hint, `sys.exit(1)` (FR-004)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_markers.py::test_pause_for_budget_writes_marker_before_exit`
    - Behavior: Satisfies T023 — `_pipeline/BUDGET_PAUSED` exists before `SystemExit(1)`; atomic write via temp + `os.replace`.
    - Tier: 3
    - Notes: FR-004

  **TDD discipline**: required
- T030 [US1] Implement FR-008 soft warn: when `actual_usd >= cycle_budget_usd * cycle_budget_warn_at`, emit non-blocking log once per cycle (`warn_emitted` on tally)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_guard.py::test_soft_warn_emitted_once_at_cycle_budget_warn_threshold`
    - Behavior: Drive tally to `actual_usd >= cycle_budget_usd * cycle_budget_warn_at`; assert exactly one WARN log and `warn_emitted` latched True on second check.
    - Tier: 2
    - Notes: FR-008

  **TDD discipline**: required
- T031 [US1] Wire `check_pre_dispatch` before each LLM dispatch and `refresh_actuals` after each dispatch in `src/research_framework/pipeline/cycle_runner.py` (plan.md Stream C)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_guard.py::test_cycle_runner_invokes_pre_dispatch_and_refresh_hooks`
    - Behavior: Integration with `vault_factory` + fake_agent: partial cycle leaves new sidecar under `agent-calls/` and proves `refresh_actuals` ran post-dispatch and `check_pre_dispatch` ran pre-dispatch (spy or side-effect on tally).
    - Tier: 3
    - Notes: Stream C; Principle IV fake_agent

  **TDD discipline**: required
- T032 [US1] Extend `src/research_framework/cli/research_resume.py` — budget marker precedence first; re-sum sidecar v1.1 actuals; refuse or clear marker per `contracts/budget-marker.contract.md` §4 (FR-005)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/cli/test_research_resume_budget.py::test_resume_refuses_when_sidecar_sum_still_over_cap`
    - Behavior: Satisfies T024 — refuse resume when sidecar sum still over cap.
    - Tier: 3
  - **Test 2**: `tests/cli/test_research_resume_budget.py::test_resume_clears_budget_marker_when_cap_satisfied`
    - Behavior: Bump `cycle_budget_usd` above sidecar sum; resume succeeds and `BUDGET_PAUSED` removed per contract §5.
    - Tier: 3
    - Notes: budget-marker.contract.md §4

  **TDD discipline**: required
- T033 [US1] Wire `--force-budget` through `src/research_framework/cli/research_generate.py` and `src/research_framework/cli/research.py` — TTY interactive y/N via `is_interactive_tty()`; headless requires `RF_FORCE_BUDGET_ACK=1` (FR-006, FR-016)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/cli/test_research_budget_flags.py::test_force_budget_tty_requires_confirmation`
    - Behavior: Mock both TTY true; `--force-budget` prompts y/N and refuses without affirmative response.
    - Tier: 3
    - Notes: FR-006
  - **Test 2**: `tests/cli/test_research_budget_flags.py::test_force_budget_headless_requires_rf_force_budget_ack`
    - Behavior: Non-TTY resume with `--force-budget` exits non-zero unless `RF_FORCE_BUDGET_ACK=1` set.
    - Tier: 3
    - Notes: FR-016

  **TDD discipline**: required
- T034 [US1] Tier-3 SC-005: add `tests/pipeline/test_budget_guard_sandbox_loop.py` — replay sandbox-failure retry pattern with `cycle_budget_usd: 1.00`; assert halt within 60s (never unbounded burn)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_guard_sandbox_loop.py::test_sandbox_failure_retry_loop_halts_within_sixty_seconds`
    - Behavior: Replay pre-written sidecars simulating repeated failed dispatches (plan_narrator-2 pattern) with `cycle_budget_usd: 1.00`; loop invokes guard until pause; wall time < 60s; never unbounded iterations (SC-005).
    - Tier: 3
    - Notes: SC-005

  **TDD discipline**: not required
- T035 [US1] Update `specs/033-cost-enforcement/spec.md` **Acceptance coverage** US1 row → `tests/pipeline/test_budget_guard.py`, `tests/pipeline/test_budget_markers.py`, `tests/e2e/test_budget_pause_resume.py`

**Checkpoint**: US1 MVP — budget/token/wallclock pause and resume work with fake-agent fixtures and v1.1 sidecar fixtures.

---

## Phase 4: Manual approval gates (FR-014 / FR-015 / FR-016)

**Goal**: Opt-in `approval_gates` pause before listed stages; separate `APPROVAL_REQUIRED` marker; resume with TTY y/N or headless `--approve <stage>` + `RF_APPROVE_<STAGE>_ACK=1`.

**Independent Test**: Configure `approval_gates: [research]`; cycle pauses at research stage with `APPROVAL_REQUIRED`; TTY `y` resumes; headless without flags refuses.

### Tests for approval gates

- T036 [P] Tier-2: stage in `approval_gates` writes `APPROVAL_REQUIRED` only (never `BUDGET_PAUSED.pause_reason` approval) in `tests/pipeline/test_budget_markers.py`

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_markers.py::test_approval_gate_writes_approval_required_not_budget_marker`
    - Behavior: Stage in `approval_gates`; pause writes only `_pipeline/APPROVAL_REQUIRED`; `BUDGET_PAUSED` absent; no `pause_reason` approval semantics.
    - Tier: 2
    - Notes: FR-014; approval-marker §7

  **TDD discipline**: not required
- T037 [P] Tier-3: headless `./vault research --resume` without `--approve` exits non-zero JSON body (FR-015)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/cli/test_research_resume_approval.py::test_headless_resume_without_approve_exits_json_error`
    - Behavior: Non-TTY with `APPROVAL_REQUIRED` present; resume without `--approve` exits non-zero; stdout/stderr contains JSON `error: approval_required`.
    - Tier: 3
    - Notes: FR-015

  **TDD discipline**: not required
- T038 [P] Tier-3: headless `--approve note_writer` requires `RF_APPROVE_NOTE_WRITER_ACK=1` (underscore stage names per contract §5.2)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/cli/test_research_resume_approval.py::test_headless_approve_note_writer_requires_env_ack`
    - Behavior: `--approve note_writer` without `RF_APPROVE_NOTE_WRITER_ACK=1` MUST fail; with env set MUST proceed (fake_agent stub dispatch).
    - Tier: 3
    - Notes: approval-marker.contract.md §5.2

  **TDD discipline**: not required

### Implementation for approval gates

- T039 Implement `check_approval_gate(stage, ...)` in `budget_guard.py` — runs after budget pre-check passes; uses `estimate_dispatch` for `estimated_cost_usd` (FR-014)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_markers.py::test_approval_gate_writes_approval_required_not_budget_marker`
    - Behavior: Satisfies T036 — approval marker isolation.
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_budget_guard.py::test_check_approval_gate_runs_after_budget_pre_check_passes`
    - Behavior: Budget pre-check would pass; gated stage still returns approval pause before dispatch.
    - Tier: 2
    - Notes: FR-014 ordering

  **TDD discipline**: required
- T040 Implement `pause_for_approval(vault_dir, marker: ApprovalRequiredMarker) -> NoReturn` — atomic `_pipeline/APPROVAL_REQUIRED`, exit 1 with stage-named message (FR-014)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_markers.py::test_pause_for_approval_writes_marker_before_exit`
    - Behavior: Analogous to budget pause: `APPROVAL_REQUIRED` on disk before `SystemExit(1)`; stderr names stage.
    - Tier: 3
    - Notes: FR-014

  **TDD discipline**: required
- T041 Extend `src/research_framework/cli/research_resume.py` — `APPROVAL_REQUIRED` branch: TTY y/N with cost+tier; headless `--approve` / `--approve-all` + per-stage or `RF_APPROVE_ALL_ACK=1` env acks (FR-015, FR-016)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/cli/test_research_resume_approval.py::test_headless_resume_without_approve_exits_json_error`
    - Behavior: Satisfies T037 — headless resume without `--approve` exits non-zero with JSON `approval_required` body.
    - Tier: 3
  - **Test 2**: `tests/cli/test_research_resume_approval.py::test_tty_resume_approval_prompt_y_clears_marker`
    - Behavior: Mock TTY; operator `y` clears marker and allows dispatch for gated stage only.
    - Tier: 3
    - Notes: FR-015

  **TDD discipline**: required
- T042 Implement rejection path — TTY `n` or `--reject <stage>` retains marker, no silent retry, exit 1 (FR-015)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/cli/test_research_resume_approval.py::test_approval_reject_retains_marker_and_exits_nonzero`
    - Behavior: TTY `n` or `--reject research` leaves `APPROVAL_REQUIRED` in place; exit 1; no second dispatch attempt (no silent retry).
    - Tier: 3
    - Notes: FR-015

  **TDD discipline**: required
- T043 Wire `--approve`, `--approve-all`, `--reject` through `src/research_framework/cli/research_generate.py` and `src/research_framework/cli/research.py`

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/cli/test_research_resume_approval.py::test_headless_approve_note_writer_requires_env_ack`
    - Behavior: Satisfies T038.
    - Tier: 3
  - **Test 2**: `tests/cli/test_research_budget_flags.py::test_approve_all_headless_requires_rf_approve_all_ack`
    - Behavior: `--approve-all` in headless mode requires `RF_APPROVE_ALL_ACK=1` in addition to flag.
    - Tier: 3
    - Notes: FR-015

  **TDD discipline**: required
- T044 Wire `check_approval_gate` in `cycle_runner.py` for snake_case stages (e.g. `note_writer`, `verifier`) before dispatch

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_guard.py::test_cycle_runner_invokes_approval_gate_before_gated_dispatch`
    - Behavior: Configure `approval_gates: [note_writer]`; fake_agent partial cycle pauses before note_writer dispatch with approval marker.
    - Tier: 3
    - Notes: fake_agent; snake_case stage names

  **TDD discipline**: required
- T045 Append `approval_gates_fired` and `tty_mode: bool` fields to cycle report writer in `src/research_framework/pipeline/reporter.py` (FR-015, FR-016)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_reporter_cost.py::test_cycle_report_includes_approval_gates_fired_and_tty_mode`
    - Behavior: After approval resume decision, `_pipeline/cycles/cycle-NNN-report.md` (or writer output) contains `approval_gates_fired` list and `tty_mode: bool` per FR-015/FR-016.
    - Tier: 3
    - Notes: cycle-N-report.md

  **TDD discipline**: required

**Checkpoint**: Budget and approval pause kinds are independent files; resume checks budget marker before approval marker.

---

## Phase 5: User Story 2 — Per-tier cost guardrails detect prompt bloat (Priority: P2)

**Goal**: Post-cycle warnings when `tier: basic` (etc.) calls exceed `limits.tier_thresholds.<tier>`.

**Independent Test** (spec.md): `tier_thresholds.basic: 0.10` + $0.15 basic call → exactly one `tier_cost_warnings` row in cycle report with stage, cost, delta.

### Tests for User Story 2

- T046 [P] [US2] Tier-2: threshold compare emits one warning per offending sidecar in `tests/pipeline/test_budget_guard.py` (SC-003)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_guard.py::test_collect_tier_cost_warnings_one_row_per_offending_sidecar`
    - Behavior: Two basic-tier sidecars over `tier_thresholds.basic`; exactly two warnings with stage, cost, delta.
    - Tier: 2
    - Notes: SC-003

  **TDD discipline**: not required
- T047 [P] [US2] Tier-3: cycle report includes `tier_cost_warnings` with stage, tier, `cost_usd`, threshold, delta (FR-007)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_reporter_cost.py::test_cycle_report_includes_tier_cost_warnings_fields`
    - Behavior: Report row includes stage, tier, `cost_usd`, threshold, delta for FR-007 warning.
    - Tier: 3
    - Notes: FR-007

  **TDD discipline**: not required

### Implementation for User Story 2

- T048 [US2] Implement `collect_tier_cost_warnings(sidecars: list[dict], tier_thresholds: dict) -> list[dict]` in `budget_guard.py` using sidecar `tier` + `cost_usd` (FR-007)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_guard.py::test_collect_tier_cost_warnings_one_row_per_offending_sidecar`
    - Behavior: Satisfies T046 — one warning dict per offending sidecar with stage, cost, delta.
    - Tier: 2

  **TDD discipline**: required
- T049 [US2] Wire tier warnings + FR-011 per-stage/per-tier breakdown into `src/research_framework/pipeline/reporter.py` at cycle end

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_reporter_cost.py::test_cycle_report_includes_tier_cost_warnings_fields`
    - Behavior: Satisfies T047 — report includes stage, tier, `cost_usd`, threshold, delta.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_reporter_cost.py::test_cycle_report_fr011_per_stage_and_per_tier_breakdown`
    - Behavior: End-of-cycle report lists cumulative spend, per-stage and per-tier breakdown from pre-written multi-batch sidecars.
    - Tier: 3
    - Notes: FR-011

  **TDD discipline**: required
- T050 [US2] Update `specs/033-cost-enforcement/spec.md` **Acceptance coverage** US2 row → `tests/pipeline/test_budget_guard.py` tier-warning cases

**Checkpoint**: US2 complete — warnings are non-blocking; cap enforcement unchanged.

---

## Phase 6: User Story 3 — Cost-per-substantive-note quality-harness metric (Priority: P2)

**Goal**: New `./build.sh --quality` metric `cost_per_substantive_note` from sidecar v1.1 `cost_usd` ÷ substantive notes added; baseline + moderate gate (>15% FAIL).

**Independent Test** (spec.md): Harness report includes metric; $0.40 baseline vs $0.65 current → FAIL.

### Tests for User Story 3

- T051 [P] [US3] Tier-2 unit `tests/quality/unit/test_cost_efficiency_metric.py` — `compute_cost_per_substantive_note` deterministic on stub `CycleOutput` + sidecar cost sum

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/quality/unit/test_cost_efficiency_metric.py::test_compute_cost_per_substantive_note_deterministic`
    - Behavior: Stub `CycleOutput` + committed v1.1 sidecar cost sum; assert metric value matches hand calculation; reads only `agent-calls/*.json`.
    - Tier: 2
    - Notes: FR-009

  **TDD discipline**: not required
- T052 [P] [US3] Tier-2 regression gate: >15% increase vs baseline → `verdict: fail` (SC-004, FR-009)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/quality/unit/test_cost_efficiency_metric.py::test_cost_per_substantive_note_regression_gate_fails_over_15_percent`
    - Behavior: Baseline 0.40, current 0.65; moderate gate `verdict: fail` (>15%).
    - Tier: 2
    - Notes: SC-004

  **TDD discipline**: not required

### Implementation for User Story 3

- T053 [P] [US3] Implement `compute_cost_per_substantive_note(fixture, cycle_outputs) -> dict` in `src/research_framework/quality/metrics/cost_efficiency.py` — reads only `agent-calls/*.json` with `schema_version: "1.1"` (FR-009)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/quality/unit/test_cost_efficiency_metric.py::test_compute_cost_per_substantive_note_deterministic`
    - Behavior: Satisfies T051 — deterministic metric from pre-written v1.1 sidecars only.
    - Tier: 2

  **TDD discipline**: required
- T054 [US3] Register metric family in `src/research_framework/quality/metrics/__init__.py` and wire into `src/research_framework/quality/runner.py`

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/quality/unit/test_cost_efficiency_metric.py::test_cost_efficiency_metric_registered_in_quality_runner`
    - Behavior: Import quality runner registry; assert `cost_per_substantive_note` family collected in harness output shape.
    - Tier: 2
    - Notes: 022 harness wiring

  **TDD discipline**: required
- T055 [US3] Add `cost_per_substantive_note` baseline subset to each `tests/fixtures/quality/baselines/<fixture>.baseline.json` after first green harness run (document in PR; operator runs `./vault quality-baseline-update` per 022 flow)
- T056 [US3] Update `specs/033-cost-enforcement/spec.md` **Acceptance coverage** US3 row → `tests/quality/unit/test_cost_efficiency_metric.py`

**Checkpoint**: US3 metric registered; baselines updated in same PR as metric lands or follow-up commit before release.

---

## Phase 7: User Story 4 — Cache-hit-ratio gate (Priority: P3)

**Goal**: Warn when source-extraction cache hit ratio &lt; 80% after cycle 1 once spec 020 cache exists.

**Independent Test** (spec.md): When 020 cache metadata present and ratio &lt; 0.80 → warning fires; before 020 → graceful N/A.

### Tests for User Story 4

- T057 [P] [US4] Tier-2: stub returns `{"status": "na", "reason": "020_not_present"}` when no cache signals in `tests/quality/unit/test_cost_efficiency_metric.py`

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/quality/unit/test_cost_efficiency_metric.py::test_source_cache_hit_ratio_returns_na_without_020_cache`
    - Behavior: Fixture without `_pipeline/sources/<module>/` cache counters returns `{"status": "na", "reason": "020_not_present"}`.
    - Tier: 2
    - Notes: FR-010 pre-020

  **TDD discipline**: not required
- T058 [US4] Tier-3: when fixture includes `_pipeline/sources/<module>/` cache counters, ratio &lt; 0.80 emits warning (FR-010) — skip if 020 not merged

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/quality/unit/test_cost_efficiency_metric.py::test_source_cache_hit_ratio_warns_below_80_percent`
    - Behavior: Fixture with cache metadata showing ratio 0.75; metric emits warning path (skip entire test if 020 not merged — pytest skip, not xfail).
    - Tier: 3
    - Notes: FR-010

  **TDD discipline**: not required

### Implementation for User Story 4

- T059 [US4] Implement `compute_source_cache_hit_ratio(fixture, cycle_outputs) -> dict` in `src/research_framework/quality/metrics/cost_efficiency.py` with 020 feature gate (FR-010)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/quality/unit/test_cost_efficiency_metric.py::test_source_cache_hit_ratio_returns_na_without_020_cache`
    - Behavior: Satisfies T057 — returns `{"status": "na", "reason": "020_not_present"}` when cache metadata absent.
    - Tier: 2

  **TDD discipline**: required
- T060 [US4] Update `specs/033-cost-enforcement/spec.md` **Acceptance coverage** US4 row with test paths + `*(blocked on 020 cache metadata until Milestone B)*` note

**Checkpoint**: US4 stubbed safely pre-020; full ratio activates when 020 lands without rework of US1–US3.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Docs, CHANGELOG, security, performance, full cycle-report fields, ship gates.

- T061 [P] Append `[Unreleased]` entries to `CHANGELOG.md` for `./vault research --resume` budget/approval behavior, `--force-budget`, `--approve`, new `_pipeline` markers, `[budget]` extra
- T062 [P] Add example `limits:` + top-level `approval_gates:` block to `dist-templates/settings.yaml` (snake_case stages: `note_writer`, `research`, `verifier`)
- T063 [P] SECURITY audit: ensure `prompt_preview` / `blocked_dispatch_preview` never contain env secrets or API keys — add redaction helper in `budget_guard.py` if needed

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_guard.py::test_prompt_preview_redacts_api_key_patterns`
    - Behavior: Input prompt containing fake `sk-...` or `ANTHROPIC_API_KEY=` substring; `prompt_preview` / `blocked_dispatch_preview` MUST NOT contain raw secret material.
    - Tier: 2
    - Notes: SECURITY task

  **TDD discipline**: required
- T064 [P] PERF tier-2: `tests/pipeline/test_budget_guard_perf.py` asserts `check_pre_dispatch` &lt; 50 ms p95 on 100-iteration loop with fixture sidecars (plan.md performance goal)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_budget_guard_perf.py::test_check_pre_dispatch_p95_under_fifty_ms`
    - Behavior: 100-iteration loop with realistic multi-file sidecar fixture tree; assert p95 latency < 50 ms.
    - Tier: 2
    - Notes: plan.md performance goal

  **TDD discipline**: not required
- T065 Implement `estimation_methods_used: [{stage, method}]` and full FR-011 cost summary (cumulative, per-stage, per-tier, cache hits when 020 present) in `src/research_framework/pipeline/reporter.py`

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._
  - **Test 1**: `tests/pipeline/test_reporter_cost.py::test_cycle_report_includes_estimation_methods_used`
    - Behavior: Report contains `estimation_methods_used: [{stage, method}]` aggregated from pre-dispatch log, not from 028 sidecar extensions.
    - Tier: 3
    - Notes: FR-003 audit row
  - **Test 2**: `tests/pipeline/test_reporter_cost.py::test_cycle_report_fr011_full_cost_summary_sections`
    - Behavior: Cumulative, per-stage, per-tier, and cache-hit sections present when 020 cache fixture supplied.
    - Tier: 3
    - Notes: FR-011

  **TDD discipline**: required
- T066 Evaluate adding `tests/e2e/test_budget_pause_resume.py` to `build.sh::SMOKE_TESTS` — document decision in PR body (ADR-0007)
- T067 Run manual validation of `specs/033-cost-enforcement/quickstart.md` §1–7 in a fixture vault; capture any drift in PR test plan
- T068 [P] `ruff check` on all new/changed modules under `src/research_framework/pipeline/` and `tests/pipeline/`
- T069 Set `specs/033-cost-enforcement/spec.md` status header to `**Status:** SHIPPED <version>` when release merges (implementer)
- T070 Flip `docs/ROADMAP.md` queue item 033 `[ ]` → `[x]` in Completed block with ship version (implementer, same commit as T069)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — **BLOCKS** all user stories and Phase 4
- **US1 (Phase 3)**: Depends on Phase 2 — **MVP**; requires 028 sidecar writer on `main` for real cycles (fixtures suffice for tier-2/3)
- **Approval gates (Phase 4)**: Depends on Phase 2 + US1 resume infrastructure (T032–T033)
- **US2 (Phase 5)**: Depends on Phase 2 + sidecar reads (can parallel with Phase 4 after US1)
- **US3 (Phase 6)**: Depends on Phase 2 + 028 cost fields; soft-couples to US1 tally semantics
- **US4 (Phase 7)**: Soft-blocked on spec 020 cache metadata
- **Polish (Phase 8)**: Depends on desired user stories complete

### User Story Dependencies

| Story | Depends on | Can parallelize with |
|-------|------------|----------------------|
| US1 | Foundational | — (MVP first) |
| Approval (Phase 4) | US1 resume path | US2 after T032 |
| US2 | Foundational, sidecar reader | US3 metric work |
| US3 | Foundational, 028 telemetry | US2 |
| US4 | US3 metric module, 020 cache | — (defer full impl) |

### Within US1

1. Tests T019–T025 (fail first)
2. Stream A: T026–T027 (`cost_estimator.py`)
3. Stream B: T028–T030 (`budget_guard.py` + `cycle_runner.py`)
4. Stream D: T032–T033 (CLI)
5. Stream E: T025 e2e after integration

### Parallel Streams (plan.md)

| Stream | Task IDs | Owner focus |
|--------|----------|-------------|
| **A** — estimator | T026, T027 | `cost_estimator.py`, `cost-estimates.yaml` |
| **B** — guard + markers | T028–T030, T039–T040 | `budget_guard.py` |
| **C** — cycle integration | T031, T044 | `cycle_runner.py` |
| **D** — CLI UX | T032–T033, T041–T043 | `cli/research*.py`, `_tty.py` |
| **E** — tests + quality | T019–T025, T046–T060, T061–T068 | `tests/` |

**Conflict rule**: Do not duplicate sidecar parsing — single `list_sidecars_v11` / `refresh_actuals` in `budget_guard.py`.

---

## Parallel Example: User Story 1

```bash
# Tests first (parallel):
# Task T019: inclusive <= cap check in tests/pipeline/test_budget_guard.py
# Task T020: strict > pause payload in tests/pipeline/test_budget_guard.py
# Task T021: wallclock + codex token branches

# Streams A + B after T018 (parallel):
# Task T026: p95_history + default_ceiling in cost_estimator.py
# Task T028: check_pre_dispatch in budget_guard.py

# Then integration (sequential):
# Task T031: cycle_runner.py dispatch hooks
# Task T032: research_resume.py budget branch
```

---

## Parallel Example: Phase 4 approval gates

```bash
# Task T036: approval marker isolation test
# Task T039: check_approval_gate in budget_guard.py
# Task T041: research_resume.py approval branch (after T032)
```

---

## Implementation Strategy

### MVP First (US1 only)

1. Complete Phase 1 + Phase 2
2. Complete Phase 3 (US1) — stop at checkpoint
3. Validate: tier-2/3 green; tier-5 e2e green with fake-agent
4. Demo on revival vault only after **028** sidecar writer is on `main`

### Incremental Delivery

1. Setup + Foundational → shared APIs stable
2. US1 → budget pause/resume (unblocks codex cap urgency SC-005)
3. Phase 4 approval gates → operator Gap-1 workflow
4. US2 → tier warnings (non-blocking)
5. US3 → quality harness metric (SC-004)
6. US4 → cache ratio when 020 ready
7. Polish → ship

### Cross-spec coordination

| Spec | Relationship |
|------|----------------|
| **028** (dispatch telemetry) | **Hard** — `budget_guard` reads `agent-calls/*.json` v1.1 only. Implementation blocked on 028 code on `main`; dev-test with committed fixture sidecars until then. |
| **020** (source modules) | **Soft** — US4 `source_cache_hit_ratio`; FR-011 cache section when cache exists. |
| **031** (git boundary) | **Soft** — `BUDGET_PAUSED` is successful pause, not failure; align resume with constrained exit (no extra tasks until 031 tasks land). |
| **030** (quality v3) | **Soft** — US3 metric family naming aligns with 022 harness patterns. |

### Parallel team strategy

- Developer A: Stream A (T026–T027)
- Developer B: Stream B (T028–T030, T039–T040)
- Developer C: Stream D (T032–T033, T041–T043) after T015
- Integrator: T031, T044, T025 e2e

---

## Notes

- `tiktoken` MUST remain behind `pip install research-framework[budget]` — never add to core `dependencies` (Principle V).
- `approval_gates` is **top-level** in `settings.yaml`, not under `limits:`.
- Pre-dispatch estimates are conservative; post-dispatch actuals come **only** from 028 sidecars.
- Use `note_writer` (underscore) in examples, tests, and `approval_gates` entries.
- Marker `schema_version` for budget/approval markers is `"1.0"` (033-owned); sidecars use `"1.1"` (028-owned) — do not conflate.
- Zero-cost cache hits (`cost_usd == 0`) do not count toward dollar-cap **estimate** numerator; actuals still recorded post-dispatch.

---

## Acceptance coverage (tasks evidence)

| User Story / Area | Evidence (tests / modules) |
|-------------------|------------------------------|
| US1 — Cycle budget cap | `tests/pipeline/test_budget_guard.py`, `tests/pipeline/test_budget_markers.py`, `tests/e2e/test_budget_pause_resume.py`, `tests/pipeline/test_budget_guard_sandbox_loop.py`; `budget_guard.py`, `cost_estimator.py`, `cycle_runner.py`, `cli/research_resume.py` |
| Approval gates (FR-014/015) | `tests/pipeline/test_budget_markers.py` T036–T038; `cli/research_resume.py`, `cli/research_generate.py` |
| US2 — Per-tier guardrails | `tests/pipeline/test_budget_guard.py` T046–T047; `reporter.py` |
| US3 — cost_per_substantive_note | `tests/quality/unit/test_cost_efficiency_metric.py`; `quality/metrics/cost_efficiency.py` |
| US4 — source_cache_hit_ratio | `tests/quality/unit/test_cost_efficiency_metric.py` T057–T058; gated on 020 |
