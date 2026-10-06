---
description: "Task list for spec 032 — Pipeline Reliability Hardening"
---

# Tasks: Pipeline Reliability Hardening

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Feature**: Pipeline Reliability Hardening | **Branch**: `032-pipeline-reliability` | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Design**: [research.md](./research.md), [quickstart.md](./quickstart.md), [checklists/requirements.md](./checklists/requirements.md)

**Target ship**: 0.9.0 (Wave 1)

**Tests**: REQUIRED. Principle III (Test-First) is NON-NEGOTIABLE. **TDD is mandatory — tests written and seen to FAIL before impl.** Run tests/lint via `.venv/bin/python -m ...` (NOT bare `python` — base env has a stale editable install).

**Organization**: rc1 gate first (US4 / FR-007), then transitional legacy hardening (US1–US3 demoted to P3 per research.md usage audit — see plan Phase 0). One phase per user story after foundational setup.

| Story | FR | Priority (plan) | What |
| --- | --- | --- | --- |
| US4 | FR-007 | **P1 — rc1 gate** 🎯 MVP | Migrate `extract.py` → `agent_call.dispatch()`; remove guard exclusion |
| US1 | FR-001, FR-002 | P3 (transitional) | Sandbox detection, fail-closed (ZERO stubs) |
| US2 | FR-003, FR-004 | P3 (transitional) | `extraction-failed` stub auto-retry on resume |
| US3 | FR-005, FR-006 | P3 (transitional) | Sonnet synthesis timeout ladder + chunk reconciliation |

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no incomplete-task dependency)
- **[USn]**: User story label (US1–US4)
- Exact file paths and FR references included per task

## Path Conventions

Single-project layout: package source under `src/research_framework/`, scripts under `scripts/`, tests under `tests/`. Primary touch surface: `src/research_framework/processors/extract.py` (~777 LOC legacy raw_data processor, reached only by `./vault pipeline {full,extract}` → `pipeline/runner.py::_drive_extract` — see research.md §1).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm a clean baseline and the Principle-IV invariants this spec must preserve.

- T001 Confirm on branch `032-pipeline-reliability` with a clean working tree (`git status`); capture baseline via `.venv/bin/python -m pytest -m "not e2e"` and `ruff check .` + `ruff format --check .` (both gates — they are SEPARATE).
- T002 [P] Verify `tests/_helpers/llm_dispatch_allowlist.yaml` is EMPTY and document the current guard exclusion in `tests/_helpers/test_llm_dispatch_guard.py::_SCAN_SKIP_REL` (expect `{"processors/extract.py"}` pre-migration) — FR-007 invariant check.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/_helpers/test_llm_dispatch_guard.py::test_allowlist_yaml_is_empty`
    - Behavior: Load `tests/_helpers/llm_dispatch_allowlist.yaml`; assert it parses to an empty list (no entries). Principle IV invariant — allowlist MUST stay EMPTY pre- and post-migration.
    - Tier: 2

  **TDD discipline**: not required

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Resolve planning unknowns before user-story work. Phase 0 usage audit is **complete** (research.md §1 — no target vault exercises `extract.py`; only the FR-007 migration is rc1-blocking). Remaining open item: pin the primary sandbox stderr signature.

- T003 [P] **Sandbox signature probe (optional but recommended):** one-off live or fixture-backed capture of sandboxed `claude -p` auth failure via the migrated `agent_call.dispatch()` surface; record the canonical stderr substring(s) in a comment block at the top of the US1 classifier in `src/research_framework/processors/extract.py` (or a dedicated `_sandbox_detect.py` helper if extract.py is already crowded). If probe is skipped, the tolerant pattern set from research.md §2 + time-based fallback remains authoritative — FR-001, SC-005 prep.
- T004 Checkpoint: T001 baseline green (modulo any environmental skips) → user-story phases may begin.

**Checkpoint**: Foundation ready — proceed to US4 (rc1 gate) first.

---

## Phase 3: User Story 4 — Migrate `extract.py` through `agent_call.dispatch()` (Priority: P1) 🎯 MVP

**Goal**: Eliminate the codebase's only Principle-IV exception by routing LLM calls through `scripts/agent_call.py::dispatch()` and removing the guard's `processors/extract.py` skip. Allowlist stays EMPTY.

**Independent Test**: `.venv/bin/python -m pytest tests/_helpers/test_llm_dispatch_guard.py tests/processors/test_extract.py -v` green; `grep 'subprocess.run(\["claude"' src/research_framework/processors/extract.py` returns no matches; `_SCAN_SKIP_REL` no longer contains `processors/extract.py`.

### Tests (write first — must FAIL)

- T005 [US4] Update `tests/_helpers/test_llm_dispatch_guard.py` (FR-007, SC-004): remove `"processors/extract.py"` from `_SCAN_SKIP_REL`; rewrite `test_scan_root_excludes_contract_paths` (lines ~257–267) to assert (a) `extract.py` is **not** in `_SCAN_SKIP_REL`, and (b) `scan_for_violations` returns **zero** hits for `processors/extract.py`; update the module docstring (lines 1–13) to drop the explicit extract.py skip note. **Must FAIL** against current `extract.py` (still has direct `subprocess.run(["claude", ...])`).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/_helpers/test_llm_dispatch_guard.py::test_scan_root_excludes_contract_paths`
    - Behavior: Assert `"processors/extract.py"` is **absent** from `_SCAN_SKIP_REL` (inverted from pre-migration). Assert `scan_for_violations` over `src/research_framework/processors/extract.py` returns an **empty** violation list. Exercises FR-007 / SC-004 guard boundary. **Must FAIL red** against unmigrated `extract.py` (direct `subprocess.run(["claude", ...])` still present).
    - Tier: 2
    - Notes: FR-007, SC-004 — rc1 gate; allowlist stays EMPTY.
  - **Test 2**: `tests/_helpers/test_llm_dispatch_guard.py::test_allowlist_yaml_is_empty`
    - Behavior: Assert `tests/_helpers/llm_dispatch_allowlist.yaml` remains empty after guard rewrite. No new allowlist entries for the migration path.
    - Tier: 2
    - Notes: Principle IV — EMPTY allowlist invariant.

  **TDD discipline**: required

### Implementation

- T006 [US4] Migrate `src/research_framework/processors/extract.py::_default_call_claude` (FR-007): replace `subprocess.run(["claude", ...])` with dynamically imported `agent_call.dispatch()` via `pipeline/plan_narrator.py::_bootstrap_scripts_agent_call(vault_dir=...)` (same seam as `plan_narrator` + `_cycle_helpers` probe path); map `AgentCallResult.stdout` → body, `.stderr`/`.exit_code` → error handling, `.tokens_in/.tokens_out/.cost_usd` → existing `usage` dict consumed by `_extract_one` / `_synthesize_context_tree`; drop unused `import subprocess` and the `claude`-on-PATH pre-check in `_cli_main`; keep module-level `_call_claude = _default_call_claude` seam for tests (deps: T005 red).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/_helpers/test_llm_dispatch_guard.py::test_scan_root_excludes_contract_paths`
    - Behavior: T005 guard test MUST pass green after migration — zero violations for `processors/extract.py`, file absent from `_SCAN_SKIP_REL`.
    - Tier: 2
    - Notes: FR-007 rc1 gate — implementation is not complete until this passes.
  - **Test 2**: `tests/processors/test_extract.py::test_call_claude_maps_dispatch_result_to_usage`
    - Behavior: Mock `_bootstrap_scripts_agent_call` / dispatch to return a shaped `AgentCallResult`; invoke `_default_call_claude` (or `_call_claude` seam); assert returned body + `usage` dict carry `tokens_in`, `tokens_out`, `cost_usd` from the dispatch result. MUST NOT call real `claude`/`codex` — use `tests/_helpers/fake_agent.py` or monkeypatch the dispatch seam.
    - Tier: 2
    - Notes: FR-007 — telemetry field mapping per spec 028 dispatch protocol.

  **TDD discipline**: required

- T007 [US4] Update `tests/processors/test_extract.py` (FR-007): repoint existing LLM mocks to the dispatch-backed `_call_claude` seam; add a unit test that patches `subprocess.run` and asserts it is **never** called with `["claude", ...]` during `extract()` (or equivalently asserts `_call_claude` / dispatch is hit instead) (deps: T006).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/processors/test_extract.py::test_extract_never_subprocess_claude`
    - Behavior: Patch `subprocess.run`; drive `extract()` (or `_default_call_claude`) on a minimal fixture vault; assert **no** call where `args[0] == "claude"` (or equivalent `["claude", ...]` argv). Proves direct CLI bypass is gone. MUST use fake dispatch via `_call_claude` seam mock — no live LLM.
    - Tier: 2
    - Notes: FR-007, SC-004 — complements guard static scan.
  - **Test 2**: `tests/processors/test_extract.py::test_existing_extract_suite_uses_call_claude_seam`
    - Behavior: Repoint existing LLM mocks to `_call_claude`; run pre-existing extract tests that exercise extraction/synthesis paths; assert they still pass through the seam (mock hit count or return-value injection). MUST NOT monkey-patch `run_cycle_steps`.
    - Tier: 2

  **TDD discipline**: required

**Checkpoint**

- T008 [US4] rc1 gate (FR-007, SC-004): `.venv/bin/python -m pytest tests/_helpers/test_llm_dispatch_guard.py tests/processors/test_extract.py -v`; `ruff check .`; `ruff format --check .` — all green. Per quickstart.md "rc1 GATE" section.

**Checkpoint**: US4 complete — Principle IV exception closed; US1–US3 may stack on the migrated dispatch surface.

---

## Phase 4: User Story 1 — Sandboxed `extract.py` runs detect their environment and fail loudly (Priority: P3)

**Goal**: On sandboxed auth failure, **hard-exit non-zero having written ZERO stubs** within ~30s of first failure cluster — not minutes of silent `extraction-failed` stub corruption.

**Independent Test**: `.venv/bin/python -m pytest tests/processors/test_extract.py -k sandbox -v` — simulated sandbox dispatch → exit 1, zero files under `<vault>/_pipeline/extracted/`; override env restores normal path.

### Tests (write first — must FAIL)

- T009 [P] [US1] Add sandbox-detection tests to `tests/processors/test_extract.py` (class e.g. `TestSandboxDetection`) — **must FAIL** before impl (FR-001, FR-002, FR-009, SC-001, SC-005):
  - stderr auth-failure signature on `AgentCallResult` → `extract()` raises / exits non-zero, **zero** stub files written (SC-001 timing bound asserted in test or via mock clock);
  - time-based fallback: first ≥3 extractions each `latency_ms < 1000` AND failed → same hard-exit even without signature match;
  - `RV_DISABLE_SANDBOX_DETECT=1` (exact name — `RV_` prefix fixed by Clarifications Q2) → detection suppressed, normal stub path reachable;
  - non-sandboxed successful dispatch → behaviour unchanged (Acceptance #2);
  - error message contains (a) what was detected, (b) `dangerouslyDisableSandbox: true` OR autonomous-mode pre-auth workaround, (c) a doc link (FR-002).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/processors/test_extract.py::test_sandbox_stderr_signature_hard_exits_zero_stubs`
    - Behavior: Mock dispatch/`_call_claude` to return `AgentCallResult` with auth-failure stderr signature (e.g. `"please run /login"`); run `extract()` on minimal vault; assert non-zero exit/raise AND **zero** files under `<vault>/_pipeline/extracted/`. MUST use fake dispatch — no live CLI.
    - Tier: 2
    - Notes: FR-001, FR-002, SC-001 — primary signature path.
  - **Test 2**: `tests/processors/test_extract.py::test_sandbox_time_fallback_three_fast_failures`
    - Behavior: Three consecutive mock dispatch results each `exit_code != 0`, `latency_ms < 1000`, stderr without signature match; assert same hard-exit + zero stubs (time-based fallback per Clarifications Q2).
    - Tier: 2
    - Notes: FR-001 — fallback layer when stderr drifts.
  - **Test 3**: `tests/processors/test_extract.py::test_sandbox_detection_suppressed_by_rv_override`
    - Behavior: Set `RV_DISABLE_SANDBOX_DETECT=1`; inject sandbox-shaped failures; assert detection suppressed and normal stub/extraction path reachable (not hard-exit). Clear env in teardown.
    - Tier: 2
    - Notes: SC-005 override; exact env name fixed by Clarifications Q2.
  - **Test 4**: `tests/processors/test_extract.py::test_non_sandbox_successful_dispatch_unchanged`
    - Behavior: Mock successful dispatch; run extract path; assert behaviour matches pre-US1 baseline (stubs written or success path unchanged). Acceptance #2 regression lock.
    - Tier: 2

  **TDD discipline**: required

### Implementation

- T010 [US1] Implement layered sandbox classifier in `src/research_framework/processors/extract.py` (FR-001): helper fed each extraction's `AgentCallResult` — primary stderr pattern set (research.md §2 + T003 probe if run), time-based fallback counter, `RV_DISABLE_SANDBOX_DETECT` override; expose `SandboxDetectedError` or equivalent for testability (deps: T009 red).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/processors/test_extract.py::test_sandbox_classifier_matches_stderr_patterns`
    - Behavior: Unit-test the classifier helper in isolation with crafted `AgentCallResult` fixtures; assert primary signature set triggers detection; assert benign stderr does not.
    - Tier: 2
    - Notes: FR-001 primary layer — tolerant pattern set from research.md §2.
  - **Test 2**: `tests/processors/test_extract.py::test_sandbox_classifier_time_fallback_counter`
    - Behavior: Feed ≥3 failed results each `latency_ms < 1000` without signature; assert classifier trips on third. Assert counter resets or does not trip on slow failures mixed in per spec intent.
    - Tier: 2
  - **Test 3**: `tests/processors/test_extract.py::test_sandbox_classifier_honors_rv_disable_env`
    - Behavior: With `RV_DISABLE_SANDBOX_DETECT=1`, feed signature-matching failure; assert classifier returns not-detected.
    - Tier: 2

  **TDD discipline**: required

- T011 [US1] Wire fail-closed policy in `extract.py::extract` / `_extract_one` fan-out (FR-001, FR-002): on classifier trip, abort `ThreadPoolExecutor` before any `_write_extraction` with `status=extraction-failed`; exit non-zero with actionable FR-002 message; **ZERO stubs on disk** (deps: T010).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/processors/test_extract.py::test_extract_aborts_before_writing_stubs_on_sandbox`
    - Behavior: Multi-target extract fan-out with sandbox trip on first failure; assert executor aborts; list `<vault>/_pipeline/extracted/` — **zero** new stub files. SC-001 timing: use mock clock or assert trip on first cluster without minutes of stub writes.
    - Tier: 2
    - Notes: FR-001 fail-closed — distinct from 048-v2 WARN posture.
  - **Test 2**: `tests/processors/test_extract.py::test_sandbox_error_message_includes_remediation_and_doc_link`
    - Behavior: Capture raised error / stderr on sandbox trip; assert message contains (a) what was detected, (b) `dangerouslyDisableSandbox: true` OR autonomous-mode pre-auth wording, (c) a documentation URL/path (FR-002).
    - Tier: 2

  **TDD discipline**: required
- T012 [US1] Update `src/research_framework/processors/extract.py` module docstring to declare sandbox-incompat for nested CLI calls (FR-008 partial) (deps: T011).

**Checkpoint**

- T013 [US1] `.venv/bin/python -m pytest tests/processors/test_extract.py -k sandbox -v` green (FR-001, FR-002, SC-001, SC-005).

**Checkpoint**: US1 complete — env-broken dispatch fails closed.

---

## Phase 5: User Story 2 — `extraction-failed` stubs auto-retry on resume (Priority: P3)

**Goal**: Transient extraction failures auto-retry on resume; exhaustion marks `extraction-failed-permanent`; `--force` re-attempts permanent stubs.

**Independent Test**: `.venv/bin/python -m pytest tests/processors/test_extract.py -k "retry or permanent" -v` — 3 pre-existing failed stubs retried without flags (SC-002).

### Tests (write first — must FAIL)

- T014 [P] [US2] Add stub-retry tests to `tests/processors/test_extract.py` (FR-003, FR-004, FR-009, SC-002) — **must FAIL** before impl:
  - vault fixture with 3 existing stubs `status: extraction-failed` → re-run `extract()` (no flags) re-queues all 3;
  - after `max_retry_attempts` (default 3 via `processor_config`) still failing → stub rewritten to `status: extraction-failed-permanent`;
  - `--force` re-attempts even `extraction-failed-permanent` stubs.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/processors/test_extract.py::test_resume_auto_retries_extraction_failed_stubs`
    - Behavior: Fixture vault with 3 existing stubs `status: extraction-failed`; run `extract()` with no flags; assert all 3 targets re-queued (mock `_call_claude` hit count or target list inspection). SC-002.
    - Tier: 2
    - Notes: FR-003, Acceptance #1.
  - **Test 2**: `tests/processors/test_extract.py::test_retry_exhaustion_marks_extraction_failed_permanent`
    - Behavior: Stub fails through `max_retry_attempts` (default 3); assert frontmatter rewritten to `status: extraction-failed-permanent`. FR-004.
    - Tier: 2
  - **Test 3**: `tests/processors/test_extract.py::test_force_reattempts_permanent_stubs`
    - Behavior: Vault with `extraction-failed-permanent` stub; run `extract(force=True)`; assert target re-queued. Acceptance #3.
    - Tier: 2

  **TDD discipline**: required

### Implementation

- T015 [US2] Extend `src/research_framework/processors/extract.py::_find_extraction_targets` (FR-003): parse existing extraction frontmatter; re-queue targets with `status: extraction-failed` (not permanent) up to configurable `max_retry_attempts` (default 3 in `processor_config`); track attempt count in stub frontmatter (deps: T014 red).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/processors/test_extract.py::test_find_targets_requeues_failed_stubs_within_max_attempts`
    - Behavior: Unit-test `_find_extraction_targets` with stubs at attempt counts 0, 1, 2 below `max_retry_attempts`; assert failed stubs included; permanent stubs excluded unless `--force`.
    - Tier: 2
    - Notes: FR-003 target-selection logic.
  - **Test 2**: `tests/processors/test_extract.py::test_find_targets_increments_retry_count_in_frontmatter`
    - Behavior: After re-queue + failed retry, assert stub frontmatter records incremented attempt count.
    - Tier: 2

  **TDD discipline**: required

- T016 [US2] On retry exhaustion in `extract.py`, rewrite stub `status` → `extraction-failed-permanent`; ensure `--force` bypasses the permanent skip (FR-004) (deps: T015).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/processors/test_extract.py::test_exhausted_retry_rewrites_stub_to_permanent`
    - Behavior: Drive extraction failure until attempt count reaches `max_retry_attempts`; assert on-disk stub frontmatter `status: extraction-failed-permanent`.
    - Tier: 2
    - Notes: FR-004 permanent marker — new Key Entity variant.
  - **Test 2**: `tests/processors/test_extract.py::test_force_flag_bypasses_permanent_skip_in_find_targets`
    - Behavior: `_find_extraction_targets(..., force=True)` with permanent stub; assert target included in queue.
    - Tier: 2

  **TDD discipline**: required

**Checkpoint**

- T017 [US2] `.venv/bin/python -m pytest tests/processors/test_extract.py -k "retry or permanent" -v` green (FR-003, FR-004, SC-002).

**Checkpoint**: US2 complete — automatic recovery from transient extraction failures.

---

## Phase 6: User Story 3 — Sonnet synthesis falls back gracefully on timeout (Priority: P3)

**Goal**: Large synthesis bundles that hit the 300s × N retry wall auto-walk the ladder: full bundle → `--filter <today>` → chunked batches → fail with diagnostic.

**Independent Test**: `.venv/bin/python -m pytest tests/processors/test_extract.py -k "timeout or chunk or ladder" -v` — synthetic over-budget bundle completes via fallback (SC-003); chunked output matches full-bundle equivalence (FR-006).

### Tests (write first — must FAIL)

- T018 [P] [US3] Add synthesis-ladder tests to `tests/processors/test_extract.py` (FR-005, FR-006, FR-009, SC-003) — **must FAIL** before impl:
  - mock `_call_claude` / dispatch to return timeout sentinel (`exit_code` non-zero + `stderr=="timed out"` per `scripts/agent_call.py` timeout path) on full bundle, then succeed on date-filtered or chunked path → `context-tree.md` produced;
  - chunked reconciliation: merged output equivalent to hypothetical successful full run (assert key sections / source coverage, not byte-identical if ordering differs);
  - all ladder steps exhausted → failure message lists attempted strategies + missing sources (Acceptance #3).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/processors/test_extract.py::test_synthesis_ladder_falls_back_to_date_filter_on_timeout`
    - Behavior: Mock `_call_claude`/dispatch: timeout sentinel (`exit_code != 0`, `stderr == "timed out"`) on full bundle, success on date-filtered regather; assert `context-tree.md` produced. FR-005.
    - Tier: 2
    - Notes: MUST mock dispatch — no live LLM; timeout sentinel per agent_call timeout path.
  - **Test 2**: `tests/processors/test_extract.py::test_synthesis_ladder_chunks_after_date_filter_timeout`
    - Behavior: Timeout on full + date-filter paths; success on chunked batch path; assert `context-tree.md` produced and chunk manifest sidecar written. FR-005, FR-006.
    - Tier: 2
  - **Test 3**: `tests/processors/test_extract.py::test_synthesis_ladder_exhausted_lists_attempted_strategies`
    - Behavior: All ladder steps fail; assert terminal error/failure message enumerates attempted strategies and missing sources. Acceptance #3, SC-003 negative path.
    - Tier: 2
  - **Test 4**: `tests/processors/test_extract.py::test_chunked_synthesis_semantic_equivalence`
    - Behavior: Compare chunked reconciliation output vs mocked successful full-bundle output on same fixture sources; assert key sections / source coverage equivalent (not byte-identical). FR-006.
    - Tier: 2

  **TDD discipline**: required

### Implementation

- T019 [US3] Implement timeout ladder in `src/research_framework/processors/extract.py::_synthesize_context_tree` (FR-005): catch dispatch timeout; walk full bundle → `--filter <today>` re-gather → chunked batches → terminal fail; configurable retry budget via `processor_config` (deps: T018 red).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/processors/test_extract.py::test_synthesize_walks_ladder_in_order`
    - Behavior: Instrument mock dispatch to record call sequence; inject timeouts at each stage; assert order is full bundle → date-filter regather → chunked batches → terminal fail. FR-005 ladder ordering per Clarifications Q4.
    - Tier: 2
  - **Test 2**: `tests/processors/test_extract.py::test_synthesis_ladder_respects_processor_config_budget`
    - Behavior: Set reduced retry budget in `processor_config`; assert ladder stops after configured limit.
    - Tier: 2

  **TDD discipline**: required

- T020 [US3] Chunked path: write manifest `<vault>/_pipeline/extracted/context-tree-chunks.json` recording attempted/succeeded chunks; reconcile into `<vault>/_pipeline/extracted/context-tree.md` with no data loss vs successful full run (FR-006) (deps: T019).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/processors/test_extract.py::test_chunk_manifest_records_attempted_and_succeeded_chunks`
    - Behavior: Run chunked synthesis path; assert `context-tree-chunks.json` exists with attempted/succeeded chunk entries matching mock inputs.
    - Tier: 2
    - Notes: Key Entity — chunked synthesis manifest.
  - **Test 2**: `tests/processors/test_extract.py::test_chunk_reconciliation_preserves_source_coverage`
    - Behavior: Assert reconciled `context-tree.md` includes all source identifiers from fixture that a successful full run would cover. FR-006 semantic equivalence.
    - Tier: 2

  **TDD discipline**: required

**Checkpoint**

- T021 [US3] `.venv/bin/python -m pytest tests/processors/test_extract.py -k "timeout or chunk or ladder" -v` green (FR-005, FR-006, SC-003).

**Checkpoint**: US3 complete — synthesis timeout no longer kills the whole legacy pipeline run.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Documentation (SC-005, FR-008), full gates, acceptance evidence.

- T022 [P] Add sandbox-detection documentation: new ADR under `docs/adr/` **or** page under `docs/` explaining the layered heuristic (primary signature, time fallback, `RV_DISABLE_SANDBOX_DETECT` override, fail-closed rationale vs 048-v2 WARN posture) — SC-005, FR-008; link from FR-002 error message target. — **DONE 2026-06-03**: `docs/sandbox-detection.md` (two layers, override truthy set, fail-closed-vs-048v2-WARN rationale, remediation). Added an `<a id="sandbox-detection">` anchor + link in `quickstart.md` so the `SandboxDetectedError` doc link (`_SANDBOX_DOC_LINK`) resolves.
- T023 [P] Run quickstart.md verification steps for rc1 gate + US1–US3 (`specs/032-pipeline-reliability/quickstart.md`). — **DONE**: US1–US3 + rc1 steps reviewed against shipped `extract.py` behaviour; no drift.
- T024 `ruff check .` — lint gate (must be zero errors). — **DONE**: green (Phase-7 edits are docs-only; no `.py` touched since rebase).
- T025 `ruff format --check .` — format gate (SEPARATE from T024; both required per ADR-0007 / CLAUDE.md). — **DONE**: green.
- T026 Full fast loop: `.venv/bin/python -m pytest -m "not e2e"`. — **DONE**: green at rebase onto main (extract.py US1–US4 cases pass); acceptance-coverage guard re-verified after the spec.md edit.
- T027 Optional smoke gate: `bash build.sh` (no `--quality` unless unrelated pipeline/quality fixtures were touched — this spec touches `processors/` only). — **DONE**: no SMOKE_TESTS edit needed (processors-only); `build.sh` green at rebase.

---

## Acceptance Coverage

Evidence cells for spec.md §Acceptance coverage (populated here — do not edit spec.md in this stage):

| User Story | Evidence (test module / marker) |
| --- | --- |
| US4 — Principle IV migration | `tests/_helpers/test_llm_dispatch_guard.py` (updated boundary test); `tests/processors/test_extract.py` (no direct subprocess) |
| US1 — Sandbox fail-closed | `tests/processors/test_extract.py -k sandbox` (SC-001, SC-005, FR-001/002) |
| US2 — Stub auto-retry | `tests/processors/test_extract.py -k "retry or permanent"` (SC-002, FR-003/004) |
| US3 — Synthesis timeout ladder | `tests/processors/test_extract.py -k "timeout or chunk or ladder"` (SC-003, FR-005/006) |

Any `@pytest.mark.live_llm` real-CLI tests (FR-009) MUST stay opt-in (`--live-llm`); static/unit tests cover detection, retry, and ladder logic in the fast loop.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS user stories (T003 probe optional).
- **US4 (Phase 3)**: Depends on Foundational — **rc1 gate; lands before US1–US3** even though all are independently testable after migration.
- **US1 (Phase 4)**: Depends on US4 checkpoint (needs dispatch-backed `_call_claude` / `AgentCallResult` surface).
- **US2 (Phase 5)**: Depends on US4; stacks cleanly on US1 (shared `extract.py` — serialize if same session to avoid merge pain).
- **US3 (Phase 6)**: Depends on US4; independent of US1/US2 logic but shares `_synthesize_context_tree` in `extract.py` — serialize with US2 if one developer.
- **Polish (Phase 7)**: Depends on desired user stories complete (minimum ship: US4 only for rc1; full spec: US4 + US1 + US2 + US3 + docs).

### User Story Dependencies

- **US4 (P1 / rc1)**: No dependency on US1–US3. **Ship alone for rc1.**
- **US1 (P3)**: Requires US4 migration (dispatch result shape).
- **US2 (P3)**: Requires US4; benefits from US1 fail-closed (no conflicting stub writes on sandbox) but independently testable with mocked dispatch.
- **US3 (P3)**: Requires US4; independent of US1/US2.

### Within Each User Story

- Tests MUST be written and FAIL before implementation (TDD).
- US4: guard test red → migrate extract.py → extract tests green → rc1 checkpoint.
- US1: classifier → fail-closed wiring → docstring.
- US2: `_find_extraction_targets` retry logic → permanent marker.
- US3: ladder state machine → chunk manifest + reconciliation.

### FR Coverage

| FR | Story | Tasks |
| --- | --- | --- |
| FR-001 | US1 | T009–T013 |
| FR-002 | US1 | T009–T013 |
| FR-003 | US2 | T014–T017 |
| FR-004 | US2 | T014–T017 |
| FR-005 | US3 | T018–T021 |
| FR-006 | US3 | T018–T021 |
| FR-007 | US4 | T005–T008 |
| FR-008 | US1 + Polish | T012, T022 |
| FR-009 | US1–US3 | T009, T014, T018 (+ live_llm opt-in note) |

---

## Parallel Opportunities

- **T002** [P] alongside T001 baseline capture.
- **T003** [P] probe can run in parallel with T001/T002 (different concern — documents signature for US1).
- **After US4 checkpoint**: US1, US2, US3 are logically independent but **share `extract.py`** — parallelize test authoring (T009, T014, T018 marked [P]) across developers, then serialize implementation merges.
- **Polish**: T022, T023 [P] in parallel; T024/T025 are sequential lint gates.

---

## Implementation Strategy

### MVP-first (rc1)

1. Phase 1 Setup → Phase 2 checkpoint.
2. **Phase 3 US4 only** — migrate + guard inversion + rc1 checkpoint (T005–T008).
3. **STOP and VALIDATE** per quickstart.md rc1 GATE section.
4. Ship rc1 if scope-constrained; US1–US3 are transitional legacy hardening (research.md: no target vault hits this path on live runs).

### Incremental Delivery (full spec)

1. Setup + Foundational → US4 (rc1) → validate.
2. US1 sandbox fail-closed → validate (`-k sandbox`).
3. US2 stub retry → validate (`-k "retry or permanent"`).
4. US3 synthesis ladder → validate (`-k "timeout or chunk or ladder"`).
5. Polish (docs + full pytest + ruff × 2) → PR.

### Assumptions & Ambiguities

- **Usage audit (resolved):** research.md confirms `./vault research` → spec-020 modules never call `extract.py`; only `./vault pipeline` does. US1–US3 are P3 transitional; FR-007 migration is rc1-blocking on EMPTY-allowlist grounds alone.
- **Primary stderr signature stability:** unknown across claude CLI versions — layered detection (signature → time fallback → `RV_DISABLE_SANDBOX_DETECT`) is intentional; T003 probe pins best-effort strings.
- **`RV_` override exact name:** `RV_DISABLE_SANDBOX_DETECT` chosen here (prefix fixed by Clarifications Q2); adjust in T010 if probe/docs prefer a different suffix.
- **Chunk equivalence (FR-006):** tests assert semantic equivalence (coverage/sections), not necessarily byte-identical merge order.
- **No `data-model.md` / `contracts/`:** stub `extraction-failed-permanent` status + `context-tree-chunks.json` sidecar described inline in spec Key Entities; migration consumes existing `dispatch()` protocol (spec 028).
- **Foreman `### Testing Requirements` blocks:** added by test-design agent (ADR-0010 pre-implement step) — see per-task blocks below.
- **Doc-sync** (ROADMAP, CHANGELOG, spec status header, version bump): ship-time per CLAUDE.md — not in this task list.

---

## Notes

- [P] = different files, no incomplete-task dependency.
- Do **not** monkey-patch `run_cycle_steps` (CLAUDE.md ban) — `extract.py` is off the cycle-runner path.
- Reuse `pipeline/process_tree.py` tree-kill behaviour only where subprocess spawns remain outside dispatch (post-migration, extract.py should not spawn claude directly).
- `scripts/agent_call.py` is loaded via `importlib` — `src/` cannot package-import it; reuse `_bootstrap_scripts_agent_call` only.
