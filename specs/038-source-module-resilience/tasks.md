---
description: "Task list for spec 038 — Source-Module Resilience Polish"
---

# Tasks: Source-Module Resilience Polish

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Feature**: Source-Module Resilience Polish | **Branch**: `038-source-module-resilience` | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Design**: [research.md](./research.md), [data-model.md](./data-model.md), [quickstart.md](./quickstart.md), [contracts/manifest-extensions.md](./contracts/manifest-extensions.md), [contracts/raw-capture-batch.contract.md](./contracts/raw-capture-batch.contract.md), [contracts/archive-snapshots.schema.json](./contracts/archive-snapshots.schema.json)

**Input**: Design documents from `/specs/038-source-module-resilience/`
**Prerequisites**: plan.md ✅, spec.md ✅ (CLARIFIED 2026-06-03), research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅
**Builds on**: shipped spec-051 `preflight()` subprocess contract (0.8.0) — 038 adds probe *content*, not a new harness
**Target ship**: 0.9.0 (Wave 1)

**Tests**: REQUIRED. TDD is mandatory — tests written and seen to FAIL before implementation (Constitution Principle III). Run tests/lint via `.venv/bin/python -m pytest` / `.venv/bin/python -m ruff` (NOT bare `python` — base env has a stale editable install).

**Organization**: One phase per user story (P1 → P2 → P3). Foundational manifest schema lands before US2; US1 is independently shippable after Foundational checkpoint (watermark/gate/report deltas reuse shipped `empty`/`error` enum — do NOT rename).

**Resolved at /tasks** (plan NEEDS CLARIFICATION):
- **FR-003 rate_limits**: v1 ships **declaration + schema only**; client-side token-bucket enforcement in module `extractor.py` is **deferred** until real rate-limit incidents are observed.
- **`raw_capture_batch` byte layout**: manifest-index over the shipped `capture()` `year/month` layout (no `target_dir=` fork); index lives at `<vault>/raw_data/captures/<YYYY-MM-DD>/manifest.json`.
- **FR-014 (`DataSourceConfig.kind`)**: **tombstone only** — no implementation task (ADR-0009 still PROPOSED).

| Story | Priority | FRs | What |
| --- | --- | --- | --- |
| US1 | P1 🎯 MVP | FR-005 | Surface `empty` vs `error`; rolling 3-cycle verdict window; >50% sustained-error gate; cycle-report line |
| US2 | P1 | FR-001/002/003/004/010/013 | Manifest blocks + module `check()` probe content on shipped 051 harness |
| US3 | P2 | FR-006/007 | `scripts/raw_capture_batch.py` batch driver over shipped `raw_capture.capture()` |
| US4 | P2 | FR-009/011/012/015 | Install path confirm; host sweep checks; validator regression-lock; O'Reilly opt-in |
| US5 | P3 | FR-008 | archive.org fail-and-defer pass in `vault_health --apply` |

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no incomplete-task dependency)
- **[USn]**: Maps to spec.md user stories US1–US5
- Exact file paths and FR references included per task

## Path Conventions

Single-project layout (per `plan.md` § Project Structure):

- Package: `src/research_framework/pipeline/source_bridge/`, `src/research_framework/quality/`, `src/research_framework/cli/`, `src/research_framework/modules/<name>/`
- Scripts: `scripts/raw_capture_batch.py`, `scripts/vault_health.py`, `scripts/raw_capture.py` (reuse only)
- Tests: `tests/modules/`, `tests/scripts/`, `tests/source_bridge/`, `tests/pipeline/`, `tests/quality/`
- Schema: `specs/020-code-bridge/contracts/manifest.schema.json`
- Scaffold: `dist-templates/install.sh`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm a green baseline on the feature branch before any delta.

- T001 Confirm on branch `038-source-module-resilience` with a clean working tree (`git status`); capture baseline via `.venv/bin/python -m pytest -m "not e2e"` and `.venv/bin/python -m ruff check .` + `.venv/bin/python -m ruff format --check .` (deps: none; FR: baseline)
- T002 [P] Create empty test-module stubs where absent: `tests/source_bridge/test_manifest_extensions.py`, `tests/source_bridge/test_watermark_verdict_history.py`, `tests/scripts/test_raw_capture_batch.py`, `tests/scripts/test_vault_health_archive.py`, `tests/pipeline/test_validator_detailed_spec.py`, `tests/quality/test_source_health_gate.py` — `pytest` collection succeeds with zero tests (deps: T001)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Amend the spec-020 manifest schema and `discovery.parse_manifest` so US2 (and manifest declarations for US1 policy fields) can land. **Blocks US2**; US1 may start after T006 checkpoint without waiting for US2 implementation.

**⚠️ CRITICAL**: No US2 work until T006 is green.

- T003 Amend `specs/020-code-bridge/contracts/manifest.schema.json` — add OPTIONAL `authentication`, `rate_limits`, `failure_policy` blocks per `contracts/manifest-extensions.md` §1–3 (`additionalProperties: false` preserved; absent blocks ⇒ today's behaviour) (deps: T001; FR-001, FR-003, FR-004, FR-013)
- T004 Extend `src/research_framework/pipeline/source_bridge/discovery.py::parse_manifest` to parse + validate the three new blocks; unknown `failure_policy` enum ⇒ `ValueError` fail-fast per contract §5 (deps: T003; FR-001, FR-003, FR-004, FR-013)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_manifest_extensions.py::test_legacy_manifest_without_new_blocks_validates`
    - Behavior: Feed a pre-038 manifest (no `authentication`/`rate_limits`/`failure_policy`); assert `parse_manifest` succeeds and returned object omits or defaults the new fields per contract §5.
    - Tier: 2
  - **Test 2**: `tests/source_bridge/test_manifest_extensions.py::test_full_manifest_blocks_round_trip`
    - Behavior: Manifest with all three optional blocks; assert parsed values match YAML for `authentication.env_vars`, `rate_limits`, and `failure_policy`.
    - Tier: 2
  - **Test 3**: `tests/source_bridge/test_manifest_extensions.py::test_invalid_failure_policy_raises_value_error`
    - Behavior: Manifest with `failure_policy: not_a_real_policy`; assert `parse_manifest` raises `ValueError` fail-fast per contract §5.
    - Tier: 2

  **TDD discipline**: required

### Tests (write first — must FAIL)

- T005 [P] Write `tests/source_bridge/test_manifest_extensions.py`: (a) legacy manifests without new blocks still validate; (b) full blocks round-trip; (c) invalid `failure_policy` raises; (d) `rate_limits` declaration-only accepted without enforcement hooks (deps: T002, T004; FR-001, FR-003, FR-004)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_manifest_extensions.py::test_legacy_manifest_without_new_blocks_validates`
    - Behavior: Legacy manifest without new blocks; assert pytest collection + parse succeeds (contract §5 acceptance).
    - Tier: 2
  - **Test 2**: `tests/source_bridge/test_manifest_extensions.py::test_full_manifest_blocks_round_trip`
    - Behavior: Full `authentication`/`rate_limits`/`failure_policy` blocks round-trip through parse; include explicit `authentication: none` variant per contract §1.
    - Tier: 2
  - **Test 3**: `tests/source_bridge/test_manifest_extensions.py::test_invalid_failure_policy_raises_value_error`
    - Behavior: Unknown `failure_policy` enum; assert `ValueError` (contract §5).
    - Tier: 2
  - **Test 4**: `tests/source_bridge/test_manifest_extensions.py::test_rate_limits_declaration_only_no_enforcement`
    - Behavior: Manifest declares `rate_limits`; assert parse accepts without any token-bucket or extractor enforcement hook — FR-003 v1 is declare-only.
    - Tier: 2

  **TDD discipline**: required

### Implementation

- T006 Extend `src/research_framework/modules/_template/manifest.yaml` with documented example `authentication` / `rate_limits` / `failure_policy` blocks (commented defaults) as the porting reference (deps: T003; FR-001, FR-003, FR-004)

**Checkpoint**: Foundational ready — US1 and US2 phases may begin (serialize `discovery.py` if both touch it).

---

## Phase 3: User Story 1 — EMPTY vs FAILED distinction (Priority: P1) 🎯 MVP

**Goal**: Surface the shipped `empty`/`error` verdict distinction in the cycle report and quality harness via a rolling 3-cycle verdict window + sustained-error gate (>50% `error` over last 3 cycles). Spec `EMPTY`/`FAILED` are aliases of lowercase `empty`/`error` — do NOT rename the enum.

**Independent Test**: Fixture with one module returning valid empty results and one returning auth errors; after a cycle assert watermarks record `empty` vs `error`, cycle report lists only the error module (`source health: youtube FAILED with HTTP 401`), and the moderate gate FAILs only when sustained `error` rate >50% over a rolling 3-cycle window.

### Tests (write first — must FAIL)

- T007 [P] [US1] Write `tests/source_bridge/test_watermark_verdict_history.py`: append cycle verdict to `recent_cycle_verdicts`, cap at 3 (oldest dropped); back-compat load defaults missing field to `[]`; atomic write round-trip via `cache.py` (deps: T006; FR-005)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_watermark_verdict_history.py::test_append_verdict_retains_only_last_three`
    - Behavior: Append four cycle verdicts; assert `recent_cycle_verdicts` length is 3 and oldest entry dropped (data-model §2).
    - Tier: 2
  - **Test 2**: `tests/source_bridge/test_watermark_verdict_history.py::test_load_back_compat_missing_recent_cycle_verdicts`
    - Behavior: Load pre-038 watermarks JSON without `recent_cycle_verdicts`; assert defaults to `[]` (data-model §2 back-compat).
    - Tier: 2
  - **Test 3**: `tests/source_bridge/test_watermark_verdict_history.py::test_save_watermarks_atomic_round_trip`
    - Behavior: Save/load cycle via `cache.py`; assert `recent_cycle_verdicts` survives atomic write round-trip.
    - Tier: 2

  **TDD discipline**: required

- T008 [P] [US1] Write `tests/quality/test_source_health_gate.py`: sustained `error` rate >50% over rolling 3-cycle window for one module ⇒ FAIL; `empty` never counts; per-module breakdown in message; window with <3 cycles does not FAIL (deps: T006; FR-005, SC-004)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/quality/test_source_health_gate.py::test_sustained_error_over_fifty_percent_fails`
    - Behavior: Module with `recent_cycle_verdicts` of three `error` entries (100% error rate); assert gate FAIL with per-module breakdown (US1 #3, >50% over rolling 3-cycle window).
    - Tier: 2
  - **Test 2**: `tests/quality/test_source_health_gate.py::test_empty_never_counts_toward_error_rate`
    - Behavior: Window mixing `empty` and `ok` verdicts with ≤50% `error`; assert gate PASS — `empty` never counts (data-model §3).
    - Tier: 2
  - **Test 3**: `tests/quality/test_source_health_gate.py::test_fewer_than_three_cycles_does_not_fail`
    - Behavior: Window with 1–2 cycles including `error`; assert gate does NOT FAIL until len(window) ≥ 3.
    - Tier: 2

  **TDD discipline**: required

### Implementation

- T009 [US1] Extend `WatermarkEntry` in `src/research_framework/pipeline/source_bridge/cache.py` with `recent_cycle_verdicts: list[str] = field(default_factory=list)`; `load_watermarks`/`save_watermarks` back-compat per `data-model.md` §2 (deps: T007; FR-005)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_watermark_verdict_history.py::test_append_verdict_retains_only_last_three`
    - Behavior: T007 tests MUST pass against `cache.py` implementation.
    - Tier: 2
  - **Test 2**: `tests/source_bridge/test_watermark_verdict_history.py::test_load_back_compat_missing_recent_cycle_verdicts`
    - Behavior: Back-compat load path MUST default missing field to `[]`.
    - Tier: 2

  **TDD discipline**: required

- T010 [US1] In `src/research_framework/pipeline/source_bridge/orchestrator.py`: after each source cycle, append the verdict to `recent_cycle_verdicts` and retain only the last 3 entries; persist via existing watermark write path (deps: T009; FR-005)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_orchestrator.py::test_orchestrator_appends_verdict_after_source_cycle`
    - Behavior: Run one source cycle with stubbed extractor; assert watermark `recent_cycle_verdicts` gains the cycle verdict and persists.
    - Tier: 3
  - **Test 2**: `tests/source_bridge/test_orchestrator.py::test_orchestrator_retains_only_last_three_verdicts`
    - Behavior: Run four consecutive cycles; assert persisted window length is 3 (data-model §2 cap).
    - Tier: 3

  **TDD discipline**: required

- T011 [US1] In `src/research_framework/pipeline/source_bridge/orchestrator.py` (+ cycle reporter if separated): emit per-cycle **"source health"** lines `source health: <module> FAILED with <underlying error>` for modules whose verdict was `error`; omit modules with `empty`/`ok` (deps: T010; FR-005)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_orchestrator.py::test_orchestrator_emits_source_health_line_for_error_verdict`
    - Behavior: Module returns `error` with underlying message; assert cycle output contains `source health: <module> FAILED with <underlying error>` (data-model §6, US1 #2).
    - Tier: 3
  - **Test 2**: `tests/source_bridge/test_orchestrator.py::test_orchestrator_omits_empty_and_ok_from_source_health`
    - Behavior: Modules with `empty`/`ok` verdicts; assert NO source-health line for those modules (FR-005 distinction).
    - Tier: 3

  **TDD discipline**: required

- T012 [US1] Implement sustained-error gate in `src/research_framework/quality/source_health.py` (new module or extend existing metric family): read per-module `recent_cycle_verdicts`, compute rolling `error` rate over the last 3 cycles, FAIL when rate >50% for any module (overridable via `settings.yaml`), return deterministic pass/fail for spec-022 harness (deps: T008, T010; FR-005, SC-004)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/quality/test_source_health_gate.py::test_sustained_error_over_fifty_percent_fails`
    - Behavior: T008 tests MUST pass against `source_health.py` gate implementation.
    - Tier: 2
  - **Test 2**: `tests/quality/test_source_health_gate.py::test_empty_never_counts_toward_error_rate`
    - Behavior: Gate MUST NOT count `empty` toward error rate (only `error` counts).
    - Tier: 2
  - **Test 3**: `tests/quality/test_source_health_gate.py::test_fewer_than_three_cycles_does_not_fail`
    - Behavior: Gate MUST NOT FAIL until rolling window length ≥ 3 cycles (>50% over 3-cycle window).
    - Tier: 2

  **TDD discipline**: required

- T013 [US1] Wire `source_health` gate into the spec-022 quality harness entry point (quality metric registration / moderate gate) so SC-004 is enforceable via `build.sh --quality` (deps: T012; FR-005, SC-004)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/quality/test_source_health_gate.py::test_source_health_gate_registered_in_quality_harness`
    - Behavior: Assert moderate-gate registry includes `source_health` metric family and invokes gate with fixture watermarks (SC-004 enforceable path).
    - Tier: 3

  **TDD discipline**: required
- T014 [US1] Run `.venv/bin/python -m pytest tests/source_bridge/test_watermark_verdict_history.py tests/quality/test_source_health_gate.py`; confirm green (deps: T011, T013; FR-005)

**Checkpoint**: US1 complete — EMPTY-vs-FAILED is surfaced and gated; shippable MVP increment.

---

## Phase 4: User Story 2 — Per-module auth probe fails fast at preflight (Priority: P1)

**Goal**: Add env-var presence + connectivity probe *content* inside each module's existing `preflight.py::check()` on top of the shipped spec-051 spawn harness. Missing MANDATORY vars ⇒ `fatal_fail` in <2 s; connectivity issues ⇒ `warning`.

**Independent Test**: Fixture vault with `YOUTUBE_API_KEY` unset; `./vault refresh-sources` or orchestrator preflight exits non-zero naming the module + var; zero extractor API calls issued.

### Tests (write first — must FAIL)

- T015 [P] [US2] Extend `tests/modules/youtube/test_preflight.py`: missing env var ⇒ `fatal_fail` message; `<MODULE>_PREFLIGHT_FAKE_ENV` override for hermetic env presence (deps: T006; FR-002, FR-013)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/modules/youtube/test_preflight.py::test_missing_youtube_api_key_fatal_fail`
    - Behavior: Unset `YOUTUBE_API_KEY`; assert `check()` returns `verdict=fatal_fail` naming module + missing var (contract §1, FR-013 MANDATORY).
    - Tier: 2
  - **Test 2**: `tests/modules/youtube/test_preflight.py::test_youtube_preflight_fake_env_override`
    - Behavior: Use `YOUTUBE_PREFLIGHT_FAKE_ENV` fixture override; assert hermetic env-presence probe without real credentials.
    - Tier: 2

  **TDD discipline**: required

- T016 [P] [US2] Extend `tests/modules/oreilly/test_preflight.py`: missing `OREILLY_API_KEY` ⇒ `fatal_fail`; unreachable API with `failure_policy: block_cycle` surfaces loud error (deps: T006; FR-002, FR-010, FR-013)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/modules/oreilly/test_preflight.py::test_missing_oreilly_api_key_fatal_fail`
    - Behavior: Unset `OREILLY_API_KEY`; assert `fatal_fail` with clear missing-var message (contract §1, US2 #1).
    - Tier: 2
  - **Test 2**: `tests/modules/oreilly/test_preflight.py::test_unreachable_api_with_block_cycle_fatal_fail`
    - Behavior: Fixture unreachable API + `failure_policy: block_cycle`; assert loud `fatal_fail` naming module + underlying error (FR-010).
    - Tier: 2

  **TDD discipline**: required

- T017 [P] [US2] Extend `tests/modules/rss/test_preflight.py`: connectivity HEAD probe failure ⇒ `warning` not `fatal_fail`; fixture override mirrors shipped `RSS_FIXTURE` pattern (deps: T006; FR-002, FR-013)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/modules/rss/test_preflight.py::test_connectivity_failure_warning_not_fatal_fail`
    - Behavior: HEAD probe failure via `RSS_FIXTURE` override; assert `warning` verdict, NOT `fatal_fail` (external connectivity = WARN posture).
    - Tier: 2

  **TDD discipline**: required

- T018 [P] [US2] Extend `tests/modules/reddit/test_preflight.py` and `tests/modules/code/test_preflight.py` with env-var + connectivity cases using fixture overrides (deps: T006; FR-002, FR-013)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/modules/reddit/test_preflight.py::test_reddit_env_var_and_connectivity_probes`
    - Behavior: Env-var presence + optional connectivity probe via fixture overrides; assert MANDATORY vars `fatal_fail`, connectivity issues `warning`.
    - Tier: 2
  - **Test 2**: `tests/modules/code/test_preflight.py::test_code_env_var_and_local_repo_sanity`
    - Behavior: Env-var presence + local-repo-path sanity via fixture overrides; assert missing path surfaces appropriate verdict.
    - Tier: 2

  **TDD discipline**: required

### Implementation

- T019 [P] [US2] Add `authentication` / `rate_limits` (declare-only) / `failure_policy` blocks to `src/research_framework/modules/{youtube,reddit,rss,oreilly,code}/manifest.yaml` per `contracts/manifest-extensions.md` and module needs (deps: T003; FR-001, FR-003, FR-004, FR-010, FR-013)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_manifest_extensions.py::test_tier1_module_manifests_parse_with_new_blocks`
    - Behavior: Load each Tier-1 module `manifest.yaml`; assert `parse_manifest` accepts declared `authentication`/`rate_limits`/`failure_policy` (SC-001, FR-003 declare-only).
    - Tier: 2

  **TDD discipline**: required

- T020 [P] [US2] Extend `src/research_framework/modules/youtube/preflight.py::check()`: read `authentication.env_vars` from manifest (passed via stdin context or local manifest read), env-var presence probe via `os.environ` + `YOUTUBE_PREFLIGHT_FAKE_ENV` test override (deps: T015, T019; FR-002, FR-013)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/modules/youtube/test_preflight.py::test_missing_youtube_api_key_fatal_fail`
    - Behavior: T015 tests MUST pass against extended `check()` implementation.
    - Tier: 2

  **TDD discipline**: required

- T021 [P] [US2] Extend `src/research_framework/modules/reddit/preflight.py::check()` with env-var presence + optional connectivity probe (WARN on failure) (deps: T018, T019; FR-002, FR-013)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/modules/reddit/test_preflight.py::test_reddit_env_var_and_connectivity_probes`
    - Behavior: T018 reddit tests MUST pass against extended `check()` implementation.
    - Tier: 2

  **TDD discipline**: required

- T022 [P] [US2] Extend `src/research_framework/modules/rss/preflight.py::check()` — retain existing HEAD probe; add env-var presence if declared (deps: T017, T019; FR-002, FR-013)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/modules/rss/test_preflight.py::test_connectivity_failure_warning_not_fatal_fail`
    - Behavior: T017 tests MUST pass against extended `check()` implementation.
    - Tier: 2

  **TDD discipline**: required

- T023 [P] [US2] Extend `src/research_framework/modules/oreilly/preflight.py::check()`: mandatory `OREILLY_API_KEY` check + connectivity probe; unreachable API ⇒ `fatal_fail` when `failure_policy: block_cycle` (deps: T016, T019; FR-002, FR-010, FR-013)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/modules/oreilly/test_preflight.py::test_missing_oreilly_api_key_fatal_fail`
    - Behavior: T016 missing-key test MUST pass against extended `check()`.
    - Tier: 2
  - **Test 2**: `tests/modules/oreilly/test_preflight.py::test_unreachable_api_with_block_cycle_fatal_fail`
    - Behavior: T016 unreachable-API test MUST pass with `failure_policy: block_cycle`.
    - Tier: 2

  **TDD discipline**: required

- T024 [P] [US2] Extend `src/research_framework/modules/code/preflight.py::check()` with env-var + local-repo-path sanity (deps: T018, T019; FR-002, FR-013)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/modules/code/test_preflight.py::test_code_env_var_and_local_repo_sanity`
    - Behavior: T018 code tests MUST pass against extended `check()` implementation.
    - Tier: 2

  **TDD discipline**: required

- T025 [US2] Update `src/research_framework/modules/_template/preflight.py` + `manifest.yaml` to document the probe pattern for future module ports (deps: T020–T024; FR-002)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/modules/_template/test_preflight.py::test_template_preflight_documents_probe_pattern`
    - Behavior: Template `check()` subprocess JSON-in/JSON-out contract unchanged; manifest includes documented `authentication` example blocks.
    - Tier: 2

  **TDD discipline**: required

- T026 [US2] In `src/research_framework/pipeline/source_bridge/orchestrator.py`: implement net-new `failure_policy` branches `degrade_gracefully` (warn + skip module contribution) and `defer` (mark retry next cycle, continue) per FR-004; default absent policy remains `block_cycle` (deps: T004; FR-004)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_orchestrator.py::test_degrade_gracefully_warns_and_skips_module`
    - Behavior: Module with `failure_policy: degrade_gracefully` and probe failure; assert WARN + module skipped, cycle continues (contract §3).
    - Tier: 3
  - **Test 2**: `tests/source_bridge/test_orchestrator.py::test_defer_marks_retry_and_continues`
    - Behavior: Module with `failure_policy: defer`; assert retry marker set and cycle continues without abort.
    - Tier: 3
  - **Test 3**: `tests/source_bridge/test_orchestrator.py::test_default_block_cycle_skips_on_fatal_fail`
    - Behavior: Absent `failure_policy` (default `block_cycle`); assert `fatal_fail` skips module per shipped verdict table.
    - Tier: 3

  **TDD discipline**: required

- T027 [US2] In `src/research_framework/pipeline/source_bridge/preflight_runner.py` (or orchestrator preflight aggregation): persist per-module probe telemetry to `_pipeline/preflight.json` `module_probes[]` with `{module, auth_probe_status, auth_probe_ms, connectivity_status, connectivity_ms, errors}` per FR-002 / US2 AC#3 / Key Entities (deps: T020–T024; FR-002)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_preflight_runner.py::test_preflight_json_records_module_probes_telemetry`
    - Behavior: Successful probe run; assert `_pipeline/preflight.json` contains `module_probes[]` entry with `{module, auth_probe_status, auth_probe_ms, connectivity_status, connectivity_ms, errors}` (US2 AC#3, data-model Key Entities).
    - Tier: 3

  **TDD discipline**: required
- T028 [US2] Run `.venv/bin/python -m pytest tests/modules/` preflight suites; confirm subprocess JSON-in/JSON-out contract unchanged (reuse shipped `preflight_runner.py` verbatim) (deps: T025, T026, T027; FR-002, FR-010)

**Checkpoint**: US2 complete — misconfiguration surfaces in <2 s at preflight; US1+US2 close headline pain.

---

## Phase 5: User Story 3 — Raw URLs survive sandbox network blocks (Priority: P2)

**Goal**: New `scripts/raw_capture_batch.py` enumerates new-note `source_urls` via canonical frontmatter parser, de-dups by `sha256(url)`, calls shipped `raw_capture.capture()` per unique URL outside the agent loop.

**Independent Test**: Vault with 3 notes / 10 unique URLs; stub `capture()`; assert manifest shape, dedup, idempotent resume, exit 0 even when all URLs fail.

### Tests (write first — must FAIL)

- T029 [P] [US3] Write `tests/scripts/test_raw_capture_batch.py` per `contracts/raw-capture-batch.contract.md`: dedup by `sha256(url)`; manifest schema v1.0; idempotent skip on `OK`; re-attempt `FAILED`/`PENDING`; incremental manifest on interrupt; exit 0 on all-failed; `--dry-run` writes nothing; stub `capture()` (no real network) (deps: T002; FR-006, FR-007, SC-002)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_raw_capture_batch.py::test_dedup_by_sha256_single_capture_for_duplicate_urls`
    - Behavior: 50 notes citing same URL; assert one `capture()` call and `citing_notes` lists all paths (contract §5, edge case).
    - Tier: 2
  - **Test 2**: `tests/scripts/test_raw_capture_batch.py::test_manifest_schema_and_status_enum`
    - Behavior: Assert manifest has `schema_version: "1.0"` and entries use `OK`/`FAILED`/`PENDING` statuses (contract §4).
    - Tier: 2
  - **Test 3**: `tests/scripts/test_raw_capture_batch.py::test_idempotent_and_incremental_resume`
    - Behavior: Pre-seed `OK`/`FAILED`/`PENDING`; assert skip/re-attempt (FR-007) AND interrupt mid-batch leaves incremental manifest for resume (contract §5 edge case).
    - Tier: 2
  - **Test 4**: `tests/scripts/test_raw_capture_batch.py::test_exit_zero_dry_run_and_bad_args_exit_two`
    - Behavior: All URLs fail ⇒ exit 0; `--dry-run` writes nothing; bad args/unreadable vault ⇒ exit 2 (contract §5–6, SC-002).
    - Tier: 2

  **TDD discipline**: required

### Implementation

- T030 [US3] Implement `scripts/raw_capture_batch.py` CLI (`--vault`, `--cycle`, `--since`, `--dry-run`) per contract §2; import `vault/frontmatter.py` for `source_urls` enumeration (FR-011 reuse) (deps: T029; FR-006, FR-007)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_raw_capture_batch.py::test_dedup_by_sha256_single_capture_for_duplicate_urls`
    - Behavior: T029 dedup test MUST pass against CLI implementation (contract §3).
    - Tier: 2
  - **Test 2**: `tests/scripts/test_raw_capture_batch.py::test_manifest_schema_and_status_enum`
    - Behavior: T029 manifest schema test MUST pass against CLI `--vault`/`--cycle`/`--since`/`--dry-run` flags (contract §2).
    - Tier: 2
  - **Test 3**: `tests/scripts/test_raw_capture_batch.py::test_exit_zero_dry_run_and_bad_args_exit_two`
    - Behavior: T029 exit-code tests MUST pass against CLI implementation.
    - Tier: 2

  **TDD discipline**: required

- T031 [US3] Wire per-URL loop: call `scripts/raw_capture.py::capture()` (existing `year/month` byte layout); record `captured_path`, `payload_kind`, `citing_notes[]` in `<vault>/raw_data/captures/<YYYY-MM-DD>/manifest.json` index (manifest-index approach — no `target_dir=` fork) (deps: T030; FR-006, FR-007)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_raw_capture_batch.py::test_manifest_schema_and_status_enum`
    - Behavior: Assert manifest records `captured_path`, `payload_kind`, `citing_notes[]` per contract §4 after stubbed `capture()`.
    - Tier: 2

  **TDD discipline**: required

- T032 [US3] Implement incremental atomic manifest writes + partial-run resume (only non-`OK` entries re-fetched) and exit-code semantics (0 completed / 2 bad args) per contract §5–6 (deps: T031; FR-007, SC-002)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_raw_capture_batch.py::test_idempotent_and_incremental_resume`
    - Behavior: T029 idempotent/incremental test MUST pass against incremental atomic manifest writes (FR-007).
    - Tier: 2
  - **Test 2**: `tests/scripts/test_raw_capture_batch.py::test_exit_zero_dry_run_and_bad_args_exit_two`
    - Behavior: T029 exit-code tests MUST pass (contract §6).
    - Tier: 2

  **TDD discipline**: required
- T033 [US3] Run `.venv/bin/python -m pytest tests/scripts/test_raw_capture_batch.py`; confirm green (deps: T032; FR-006, FR-007)

**Checkpoint**: US3 complete — citation durability survives sandbox blocks.

---

## Phase 6: User Story 4 — Install preflight catches misconfigurations LOUDLY (Priority: P2)

**Goal**: Thin wiring for the five trial-run failure modes: install path confirm, host-level sweep checks, validator regression-lock, O'Reilly opt-in tiers.

**Independent Test**: `install.sh` echoes absolute path + `[Y/n]`; headless requires `--accept-path`; `refresh-sources` sweep WARNs on `gh auth status`; validator detailed-spec traversal regression test green.

### Tests (write first — must FAIL)

- T034 [P] [US4] Write `tests/pipeline/test_validator_detailed_spec.py`: assert validator summaries traverse detailed-spec frontmatter fields via canonical `vault/frontmatter.py` (regression-lock pre-spec-025-B4 bug; fields should already parse — test locks behaviour) (deps: T002; FR-011)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_validator_detailed_spec.py::test_validator_traverses_detailed_spec_frontmatter_fields`
    - Behavior: Fixture vault with detailed-spec frontmatter; assert validator summary includes all canonical fields parsed by `vault/frontmatter.py` (FR-011 regression-lock).
    - Tier: 2

  **TDD discipline**: required

- T035 [P] [US4] Write install-path confirm tests in `tests/scripts/test_install_sh_tty_handling.py` (or sibling): TTY `[Y/n]` echo of absolute path; headless refuses without `--accept-path` (deps: T002; FR-009, SC-003)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_install_sh_tty_handling.py::test_tty_echoes_absolute_path_and_prompts_yn`
    - Behavior: Mock TTY; assert install echoes `Installing into: <ABSOLUTE_PATH>` and prompts `[Y/n]` (FR-009, US4 #1).
    - Tier: 2
  - **Test 2**: `tests/scripts/test_install_sh_tty_handling.py::test_headless_refuses_without_accept_path`
    - Behavior: Non-interactive mode without `--accept-path`; assert install refuses to proceed (FR-009).
    - Tier: 2

  **TDD discipline**: required

- T036 [P] [US4]

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_refresh_sources_host_checks.py::test_gh_auth_unauthenticated_warns`
    - Behavior: Mock `gh auth status` failure when GitHub sources configured; assert WARN status (FR-012, US4 #4).
    - Tier: 2
  - **Test 2**: `tests/cli/test_refresh_sources_host_checks.py::test_connectivity_probe_warns_on_failure`
    - Behavior: Mock connectivity probe failure; assert WARN, not cycle-blocker (FR-012 external checks = WARN).
    - Tier: 2
  - **Test 3**: `tests/cli/test_refresh_sources_host_checks.py::test_missing_local_repo_path_warns`
    - Behavior: Code-bridge module with missing local clone path; assert WARN with path context (FR-012).
    - Tier: 2

  **TDD discipline**: required

### Implementation

- T037 [US4] Extend `dist-templates/install.sh`: echo `Installing into: <ABSOLUTE_PATH>` + `[Y/n]` in TTY mode; add `--accept-path <PATH>` headless gate; refuse proceed without explicit accept in non-interactive mode (deps: T035; FR-009, SC-003)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_install_sh_tty_handling.py::test_tty_echoes_absolute_path_and_prompts_yn`
    - Behavior: T035 TTY test MUST pass against updated `install.sh`.
    - Tier: 2
  - **Test 2**: `tests/scripts/test_install_sh_tty_handling.py::test_headless_refuses_without_accept_path`
    - Behavior: T035 headless test MUST pass (SC-003 time-to-failure < 5 s path).
    - Tier: 2

  **TDD discipline**: required

- T038 [US4]

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_refresh_sources_host_checks.py::test_gh_auth_unauthenticated_warns`
    - Behavior: T036 gh-auth test MUST pass against sweep implementation.
    - Tier: 2
  - **Test 2**: `tests/cli/test_refresh_sources_host_checks.py::test_connectivity_probe_warns_on_failure`
    - Behavior: T036 connectivity test MUST pass.
    - Tier: 2
  - **Test 3**: `tests/cli/test_refresh_sources_host_checks.py::test_missing_local_repo_path_warns`
    - Behavior: T036 local-repo test MUST pass.
    - Tier: 2

  **TDD discipline**: required

- T039 [US4] Update `src/research_framework/modules/oreilly/sources.yaml.template`: default O'Reilly to opt-in via explicit `tier:` block (not broad-query default) per FR-015 (deps: T019; FR-015)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/modules/oreilly/test_sources_template.py::test_oreilly_template_requires_explicit_tier_for_broad_queries`
    - Behavior: Parse template; assert no broad-query default without explicit `tiers:` block (FR-015, US4 #5).
    - Tier: 2

  **TDD discipline**: required
- T040 [US4] Run `.venv/bin/python -m pytest tests/pipeline/test_validator_detailed_spec.py tests/scripts/test_install_sh_tty_handling.py tests/cli/` refresh-sources coverage; confirm green (deps: T037, T038, T039; FR-009, FR-011, FR-012, FR-015)

**Checkpoint**: US4 complete — install/cycle-start misconfigs surface loudly in <5 s.

---

## Phase 7: User Story 5 — archive.org fallback for fragile URLs (Priority: P3)

**Goal**: Fail-and-defer archive.org snapshot pass under `scripts/vault_health.py --apply`; persist `_pipeline/archive-snapshots.json`; exit 0 even when deferred.

**Independent Test**: Stub snapshot POST; assert `archived` / `deferred` / `unarchivable` statuses, schema v1.0, exit 0 on rate-limit.

### Tests (write first — must FAIL)

- T041 [P] [US5] Write `tests/scripts/test_vault_health_archive.py`: snapshot success ⇒ `archived`; rate-limit ⇒ `deferred` + exit 0; robots/paywall ⇒ `unarchivable`; fixture-override network (no real archive.org); JSON validates against `contracts/archive-snapshots.schema.json` (deps: T002; FR-008, SC-005)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_vault_health_archive.py::test_snapshot_success_marks_archived`
    - Behavior: Stub successful archive.org POST; assert `status: archived` with `snapshot_url` and `created_at` populated (schema `$defs/Snapshot`).
    - Tier: 2
  - **Test 2**: `tests/scripts/test_vault_health_archive.py::test_rate_limit_marks_deferred_exit_zero`
    - Behavior: Stub rate-limit response; assert `status: deferred`, reason recorded, process exit 0 (FR-008 fail-and-defer, Q2).
    - Tier: 2
  - **Test 3**: `tests/scripts/test_vault_health_archive.py::test_robots_paywall_marks_unarchivable`
    - Behavior: Stub robots/paywall block; assert `status: unarchivable` with reason (schema enum).
    - Tier: 2
  - **Test 4**: `tests/scripts/test_vault_health_archive.py::test_deferred_urls_accumulate_across_runs`
    - Behavior: Two `--apply` passes; assert deferred URLs persist in `snapshots` map and output validates against `archive-snapshots.schema.json` (`schema_version: "1.0"`).
    - Tier: 2

  **TDD discipline**: required

### Implementation

- T042 [US5] Extend `scripts/vault_health.py --apply`: enumerate fragile/frontmatter URLs; POST `https://web.archive.org/save/<url>` via stdlib `urllib`; env-override for hermetic tests; fail-and-defer per Q2 (deps: T041; FR-008)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_vault_health_archive.py::test_snapshot_success_marks_archived`
    - Behavior: T041 archived test MUST pass against `--apply` implementation.
    - Tier: 2
  - **Test 2**: `tests/scripts/test_vault_health_archive.py::test_rate_limit_marks_deferred_exit_zero`
    - Behavior: T041 deferred + exit-0 test MUST pass (US5 non-fatal).
    - Tier: 2

  **TDD discipline**: required

- T043 [US5] Atomic-write `_pipeline/archive-snapshots.json` per `contracts/archive-snapshots.schema.json` (`schema_version: "1.0"`, `snapshots` map, `updated_at`); accumulate deferred URLs across runs (deps: T042; FR-008)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_vault_health_archive.py::test_deferred_urls_accumulate_across_runs`
    - Behavior: T041 accumulate test MUST pass after atomic write (data-model §5).
    - Tier: 2
  - **Test 2**: `tests/scripts/test_vault_health_archive.py::test_snapshot_success_marks_archived`
    - Behavior: Snapshot record fields (`snapshot_url`, `created_at`, `status`) validate against schema on each write.
    - Tier: 2

  **TDD discipline**: required
- T044 [US5] Run `.venv/bin/python -m pytest tests/scripts/test_vault_health_archive.py`; confirm green (deps: T043; FR-008, SC-005)

**Checkpoint**: US5 complete — archive fallback is non-blocking and durable.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Lint gates, full test sweep, quality harness, operator docs, spec acceptance table.

- T045 [P] Validate operator walkthrough in `specs/038-source-module-resilience/quickstart.md` against implemented surfaces (update quickstart only if drift found) (deps: T014, T028, T033, T040, T044; FR: all) — **DONE 2026-06-03**: reviewed §1–6 (manifest auth, refresh-sources sweep + host checks, EMPTY/FAILED gate, raw_capture_batch, archive pass, install `--accept-path`) + "what did NOT change" / FR-014-deferred — all match shipped surfaces. No drift.
- T046 Run `.venv/bin/python -m ruff check .` — lint baseline MUST stay at zero (deps: all impl; gate: separate from format) — **DONE**: zero errors.
- T047 Run `.venv/bin/python -m ruff format --check .` — format baseline MUST stay at zero (deps: all impl; gate: **separate** from `ruff check`) — **DONE**: caught + fixed a drift in `tests/scripts/test_install_sh_tty_handling.py` (the US4 edit in 78dbbbf missed the format gate — the exact Wave-2 lesson); now 541 files all formatted.
- T048 Run `.venv/bin/python -m pytest -m "not e2e"` — full fast-loop green (deps: T046, T047) — **DONE**: green at rebase onto main (incl. the 2 rebase-surfaced regression fixes: source_health unit-test relocation + oreilly template restore).
- T049 Run `PYTHON_BIN=.venv/bin/python bash build.sh --quality` — SC-004: 0 EMPTY-vs-FAILED conflations across 3 spec-022 fixtures (deps: T048; SC-004) — **DONE 2026-06-03**: `PYTHONPATH=$wt/src PYTHON_BIN=.venv/bin/python bash build.sh --quality` → smoke gate passed, **quality harness Verdict PASS (3 fixtures: 3 pass / 0 warn / 0 fail, 0 regressions)**, wheel built. SC-004 satisfied.
- T050 Update `specs/038-source-module-resilience/spec.md` **Acceptance coverage** evidence cells + status header prep for ship; document FR-014 tombstone (no code) (deps: T049; FR-014 tombstone) — **DONE**: cells populated (US1–US5 → real test modules); FR-014 tombstone noted in the acceptance preamble (deferred until ADR-0009 ACCEPTED; no code).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — **blocks US2** manifest/probe work; US1 may proceed after T006 checkpoint
- **User Stories (Phases 3–7)**: US1 after Foundational checkpoint; US2 after Foundational; US3–US5 after their respective story tests fail RED
  - Recommended sequence: **US1 → US2** (both P1, shared orchestrator.py — serialize or rebase) → **US3 ∥ US4** (independent files) → **US5**
- **Polish (Phase 8)**: Depends on all desired user stories complete

### User Story Dependencies

- **US1 (P1 🎯 MVP)**: After Phase 2 checkpoint; no dependency on US2–US5
- **US2 (P1)**: After Phase 2; integrates with shipped 051 `preflight_runner.py`; touches same `orchestrator.py` as US1 — coordinate merges
- **US3 (P2)**: Independent after Phase 2; reuses `raw_capture.py` + `vault/frontmatter.py` only
- **US4 (P2)**: Independent after Phase 2; bash + CLI sweep only
- **US5 (P3)**: Independent after Phase 2; no pipeline hot-path changes

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Foundational schema before module manifest edits
- `cache.py` / watermark fields before orchestrator bump
- Gate logic before harness wiring
- Batch/archive scripts after their contract tests exist

### FR Coverage Matrix

| FR | Story | Tasks |
| --- | --- | --- |
| FR-001 | US2 | T003–T006, T019 |
| FR-002 | US2 | T015–T028 |
| FR-003 | Foundational + US2 | T003–T006, T019 (declare-only; enforcement deferred) |
| FR-004 | Foundational + US2 | T003–T004, T026 |
| FR-005 | US1 | T007–T014 |
| FR-006 | US3 | T029–T033 |
| FR-007 | US3 | T029–T033 |
| FR-008 | US5 | T041–T044 |
| FR-009 | US4 | T035, T037 |
| FR-010 | US2 | T016, T023 |
| FR-011 | US3 + US4 | T030 (frontmatter reuse), T034 |
| FR-012 | US4 | T036, T038 |
| FR-013 | US2 | T015–T024 |
| FR-014 | — | **DEFERRED** (tombstone in T050 only) |
| FR-015 | US4 | T039 |

---

## Parallel Opportunities

- **Phase 1**: T002 parallel with T001 (after baseline captured)
- **Phase 2**: T005 parallel with T006 once T004 lands
- **US1 tests**: T007 ∥ T008
- **US2 tests**: T015–T018 in parallel; module impl T020–T024 in parallel after manifests (T019)
- **US3–US5**: Independent stories — different owners after Foundational
- **Polish**: T045 parallel with T046/T047 once code complete

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (minimal — T003–T006)
3. Complete Phase 3: User Story 1 (T007–T014)
4. **STOP and VALIDATE**: `pytest tests/source_bridge/test_watermark_verdict_history.py tests/quality/test_source_health_gate.py` + spot-check cycle report output
5. Optional early ship of US1-only increment

### Incremental Delivery

1. Setup + Foundational → manifest schema ready
2. US1 → sustained-error gate + cycle report (MVP)
3. US2 → auth/connectivity probes (headline preflight pain)
4. US3 → raw URL mirroring (citation durability)
5. US4 → install/sweep hardening
6. US5 → archive.org defer pass
7. Polish → `build.sh --quality` SC-004 gate

### Parallel Team Strategy

With two developers after Foundational:

- **Dev A**: US1 then US2 (orchestrator.py owner)
- **Dev B**: US3 + US4 in parallel, then US5
- Rejoin for Polish + quality harness

---

## Notes

- Reuse shipped spec-051 `preflight_types.py`, `preflight_runner.py`, and verdict table **verbatim** — 038 adds probe content inside module `check()` only
- Modules MUST NOT import from `src/research_framework/` — duplicate probe helpers module-side (Principle VIII)
- Network access in tests: fixture/env overrides only (`RSS_FIXTURE`, `YT_DLP_BIN`, `<MODULE>_PREFLIGHT_FAKE_ENV`, archive snapshot stub)
- LLM dispatch guard allowlist stays **EMPTY** — no new `claude`/`codex` subprocess paths
- Commit after each task or logical group; stop at any **Checkpoint** to validate story independence
