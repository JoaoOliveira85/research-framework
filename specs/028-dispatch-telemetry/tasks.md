# Tasks: Dispatch Telemetry (Spec 028)

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Input**: Design documents from `/specs/028-dispatch-telemetry/`  
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md  
**Branch**: `028-dispatch-telemetry-tasks` (implementation branch TBD after tasks merge)

**Tests**: FR-008 mandates a regression test per FR; plan Acceptance coverage maps tiers 2–4 (+ optional `live_llm` for SC-001). Test tasks are included and should FAIL before implementation (Principle III).

**Organization**: Phases follow user-story priority. US1 and US3 are both P1; US1 is MVP (dispatch path). US3 depends on sidecar v1.1 writers (foundational + US1 dispatch schema). US2 (P2) layers on the foundational allocator wired in US1/US2.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1–US4 labels map to spec.md user stories

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm implementation scope, contract pins, and template sync targets before code changes.

- T001 Verify feature branch and read contracts in `specs/028-dispatch-telemetry/contracts/sidecar-v1.contract.md` and `specs/028-dispatch-telemetry/contracts/dispatch-protocol.contract.md` (no edits — implementation must match `schema_version: "1.1"`)
- T002 [P] Add committed JSON Schema fixture at `tests/fixtures/contracts/agent-call-sidecar-1.1.schema.json` copied from `specs/028-dispatch-telemetry/data-model.md` § JSON Schema (const `"1.1"`, required fields per contract)
- T003 [P] Audit `dist-templates/` and `tests/fixtures/quality/*/scripts/agent_call.py` for post-ship sync targets; record paths in implementation PR notes (no code change in tasks stage)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared sidecar v1.1 helpers, stream-json extraction, path allocator, and tier-2 contract tests. **No user story work until this phase completes.**

**⚠️ CRITICAL**: Wave 1A (`scripts/agent_call.py`) depends on these landing first.

- T004 [P] Create tier-2 contract module `tests/scripts/test_agent_call_sidecar_v1.py` with parametrized schema validation against `tests/fixtures/contracts/agent-call-sidecar-1.1.schema.json` (valid ok/failed payloads, reject missing `agent_kind`/`status`/`cycle`)
- T005 Extract shared `_consume_claude_stream(stdout_iterable) -> StreamCostResult` from `_run_claude_with_cost` in `scripts/agent_call.py` (lines ~507–579 per FR-001; single parser for CLI + `dispatch()`)
- T006 Implement `_detect_agent_kind(agent_name, vault_context) -> Literal["fake","real"]` in `scripts/agent_call.py` (replace `cost_usd == 0.0` heuristic per FR-002 / research R6)
- T007 Refactor `_sidecar_timestamps(agent_kind, *, started_mono, completed_mono)` in `scripts/agent_call.py` — real: ms ISO-8601 per FR-003; fake: exact `2000-01-01T00:00:00Z` / `2000-01-01T00:00:01Z` per FR-004
- T008 Implement `_write_sidecar_v11(path: Path, payload: dict)` in `scripts/agent_call.py` using temp file + `os.replace` in `agent-calls/` per research R1 and contract §1.3
- T009 Implement `_allocate_sidecar_path(cycle_dir: Path, stage: str) -> Path` in `scripts/agent_call.py` per FR-005 / research R7 (`{stage}.json` first, then `{stage}-2.json`, exclude `-batch-` from numeric sequence)
- T010 [P] Add tier-2 unit tests for `_allocate_sidecar_path` in `tests/scripts/test_agent_call_sidecar_v1.py` (empty dir → `{stage}.json`; existing `{stage}.json` → `{stage}-2.json`; batch files do not advance per-call suffix)
- T011 [P] Add tier-2 unit tests for fake vs real timestamp bytes in `tests/scripts/test_agent_call_sidecar_v1.py` (FR-003/FR-004; assert exact fake sentinel strings)

**Checkpoint**: Contract tests + allocator + shared parser exist; `dispatch()` not yet rewired.

---

## Phase 3: User Story 1 — Per-call cost telemetry survives in-process dispatch (Priority: P1) 🎯 MVP

**Goal**: `dispatch()` captures real `cost_usd` / token counts for claude runs, uses explicit `agent_kind`, writes sidecar v1.1 under `agent-calls/`, and populates `AgentCallResult`.

**Independent Test**: After a fake-agent cycle, `agent-calls/plan_narrator.json` has `schema_version: "1.1"`, `agent_kind: "fake"`, zero costs, sentinel timestamps. With `@pytest.mark.live_llm`, same path shows `agent_kind: "real"`, `cost_usd > 0`, `completed_at > started_at` (ms precision).

### Tests for User Story 1

- T012 [P] [US1] Add tier-2 unit test: `_consume_claude_stream` maps synthetic stream-json lines to `cost_usd`, `tokens_in`, `tokens_out` in `tests/scripts/test_agent_call_sidecar_v1.py`
- T013 [P] [US1] Add tier-2 unit test: `dispatch()` populates `AgentCallResult` fields from stream mock in `tests/scripts/test_agent_call.py`
- T014 [US1] Extend `tests/pipeline/test_plan_narrator.py` to assert sidecar v1.1 fields (`agent_kind`, `status`, `cycle`, `tokens_in`/`tokens_out` keys) at `agent-calls/plan_narrator.json`
- T015 [US1] Extend `tests/pipeline/test_cycle_runner_probe.py` to assert sidecar v1.1 at `agent-calls/probe_retrieval.json`
- T016 [P] [US1] Add opt-in SC-001 test `tests/scripts/test_agent_call_dispatch_live.py` with `@pytest.mark.live_llm` comparing `dispatch()` vs CLI `--cost-sidecar` cost within 5%

### Implementation for User Story 1

- T017 [US1] Rewire `dispatch()` in `scripts/agent_call.py` to call `_consume_claude_stream` on success (FR-001); remove hard-coded zero cost/token fields
- T018 [US1] Populate `AgentCallResult` (`cost_usd`, `tokens_in`, `tokens_out`, `latency_ms`) from stream + monotonic clock in `scripts/agent_call.py` (FR-010)
- T019 [US1] On every `dispatch()` completion, allocate path via T009 and write sidecar v1.1 via T008 with required fields including `cycle` parsed from `cycle_dir` (FR-006 path family for per-call)
- T020 [US1] Set `status: "ok"` / `exit_code: 0` on success; on failure write `status: "failed"`, subprocess `exit_code`, best-effort partial telemetry, optional `stderr_excerpt` in `scripts/agent_call.py` (FR-011)
- T021 [US1] Mirror `tests/_helpers/fake_agent.py::dispatch()` sidecar emission to v1.1 + `agent_kind: "fake"` so tier-5/6 interception stays consistent with `scripts/agent_call.py`

**Checkpoint**: US1 independently verifiable via `test_plan_narrator.py` + `test_agent_call_sidecar_v1.py` without US3 batch path changes.

---

## Phase 4: User Story 2 — Sidecar paths don't collide for repeated stages (Priority: P2)

**Goal**: Multiple `dispatch()` calls for the same `stage` in one cycle produce distinct suffixed files; single dispatch keeps `{stage}.json`.

**Independent Test**: Two mocked `dispatch(stage="plan_narrator", ...)` calls in one `cycle_dir` yield `plan_narrator.json` and `plan_narrator-2.json` with distinct payloads (no overwrite).

### Tests for User Story 2

- T022 [P] [US2] Add tier-3 integration `tests/scripts/test_dispatch_sidecar_collision.py`: two in-process `dispatch()` calls → distinct files, both readable (FR-005, SC-003)
- T023 [US2] Add tier-3 test in `tests/scripts/test_dispatch_sidecar_collision.py`: single dispatch leaves only `{stage}.json` (FR-009 back-compat)
- T024 [P] [US2] Add tier-3 test `tests/pipeline/test_quality_report_retry_sidecar.py`: simulate second `dispatch()` after first sidecar exists → `plan_narrator-2.json` (FR-012; `_quality_report_guard` unchanged in `src/research_framework/pipeline/orchestrator.py`)

### Implementation for User Story 2

- T025 [US2] Ensure `dispatch()` always calls `_allocate_sidecar_path` before `_write_sidecar_v11` (never bare overwrite of existing path) in `scripts/agent_call.py`
- T026 [US2] Add inline comment at `_quality_report_guard` call sites in `src/research_framework/pipeline/orchestrator.py` documenting FR-012 delegation to allocator (no logic change)

**Checkpoint**: SC-003 satisfied; FR-012 verified by suffix test only.

---

## Phase 5: User Story 3 — Per-batch note-writer cost sidecars don't overwrite (Priority: P1)

**Goal**: Multi-batch cycles write `agent-calls/note_writer-batch-{B}.json` (stage=`note_writer` per `research.py`), CLI emits v1.1, `_sum_sidecar_costs` glob-sums all files.

**Independent Test**: Fixture vault with two batch sidecars under `cycle-NNN/agent-calls/` returns sum within 0.01 USD of manual Σ `cost_usd` (SC-004).

### Tests for User Story 3

- T027 [P] [US3] Add tier-3 integration `tests/pipeline/test_sum_sidecar_costs_batches.py` with hand-crafted `agent-calls/note_writer-batch-1.json` + `note_writer-batch-2.json` (FR-007, SC-004)
- T028 [US3] Add tier-3 test `tests/pipeline/test_budget_cap_multi_batch.py` injecting sidecars to assert cumulative cap halts mid-cycle when enabled (SC-005; fake-agent costs)
- T029 [P] [US3] Extend or add CLI contract test in `tests/scripts/test_agent_call.py` asserting `--cost-sidecar` writes v1.1 (`tokens_in` not `input_tokens`, `schema_version: "1.1"`)

### Implementation for User Story 3

- T030 [US3] Retarget `_sum_sidecar_costs` in `src/research_framework/pipeline/orchestrator.py` to glob `cycles/cycle-{NNN}/agent-calls/*.json`, sum `cost_usd`, include `status: "failed"`, stop reading `cycle-{N}-*.cost.json` (FR-007, FR-011 summation)
- T031 [US3] Update `_cumulative_sidecar_cost` / `_append_budget_log` callers in `src/research_framework/pipeline/orchestrator.py` if they assume legacy field names (`input_tokens` → `tokens_in`)
- T032 [US3] Retarget cost rollup in `src/research_framework/pipeline/run_report.py` to `agent-calls/*.json` with v1.1 field names (dispatch-protocol §5)
- T033 [US3] Change note-writer batch loop in `src/research_framework/pipeline/steps/research.py` to pass `--cost-sidecar` → `agent-calls/note_writer-batch-{B}.json` with `batch_index` and `topic_count` (FR-006; retire `cycle-{N}-research.cost.json` writes)
- T034 [US3] Retarget scout `--cost-sidecar` path in `src/research_framework/pipeline/steps/scout.py` to `agent-calls/scout.json` (FR-006)
- T035 [US3] Audit and retarget `--cost-sidecar` paths in `src/research_framework/pipeline/_cycle_helpers.py` (probe/scout call sites per plan audit)
- T036 [US3] Upgrade CLI `run()` / `--cost-sidecar` writer in `scripts/agent_call.py` to emit sidecar v1.1 (shared `_write_sidecar_v11` + field map; no legacy `runtime`/`input_tokens` top-level keys)
- T037 [P] [US3] Sync generated shim template at `dist-templates/vault/scripts/agent_call.py.j2` (or equivalent template path under `dist-templates/`) with `scripts/agent_call.py` changes

**Checkpoint**: Multi-batch summation and scout/research paths unified under `agent-calls/`.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: FR-008 closure, docs, ship hygiene, fixture determinism audit.

- T038 [P] Add FR-008 traceability table to this file § Acceptance coverage (map each FR-001–FR-012 and SC-001–SC-005 to test task IDs above)
- T039 Run `quickstart.md` operator commands against a `tests/_helpers/vault_factory.build_minimal_vault` cycle output and fix only implementation bugs found (document results in PR)
- T040 [P] Update `CHANGELOG.md` `[Unreleased]` with breaking note: legacy `cycle-*-*.cost.json` retired; sidecar v1.1 under `agent-calls/`
- T041 [P] Set `**Status:** SHIPPED <version>` in `specs/028-dispatch-telemetry/spec.md` header and flip `docs/ROADMAP.md` queue entry in implementation PR (not in tasks-only PR)
- T042 Run `./build.sh` smoke gate; add new tier-2 module to `build.sh::SMOKE_TESTS` only if `tests/scripts/test_agent_call_sidecar_v1.py` is not already covered
- T043 [P] Audit committed quality baselines under `tests/fixtures/quality/baselines/` for fake timestamp strings; run `./build.sh --quality` if any baseline sidecar paths change
- T044 Run `ruff check .` from repo root and fix any new violations in touched files

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — **blocks all user stories**
- **US1 (Phase 3)**: Depends on Foundational — MVP; enables real sidecar payloads from `dispatch()`
- **US2 (Phase 4)**: Depends on US1 T019 (dispatch writes via allocator); can overlap US3 consumer work only after T009 exists
- **US3 (Phase 5)**: Depends on Foundational T008–T009 and US1 sidecar field shape; orchestrator (T030) can parallel CLI path (T033–T036) after schema tests green
- **Polish (Phase 6)**: Depends on US1–US3 complete

### User Story Dependencies

| Story | Depends on | Blocks |
|-------|------------|--------|
| US1 (P1) | Foundational | US2 (allocator wiring), US3 (schema reference) |
| US2 (P2) | US1 dispatch write path | — |
| US3 (P1) | Foundational + US1 v1.1 shape | Spec 033 cost enforcement reader |

### Within-Story Ordering

1. Tests before implementation (T012–T016 before T017–T021; T022–T024 before T025–T026; T027–T029 before T030–T037)
2. `scripts/agent_call.py` helpers (Phase 2) before `dispatch()` rewire (US1)
3. `_sum_sidecar_costs` retarget (US3) after v1.1 writer tests exist
4. `dist-templates` sync last in US3

### Parallel Opportunities

- **Phase 1**: T002 ∥ T003
- **Phase 2**: T004 ∥ T010 ∥ T011 after T002 schema fixture
- **Phase 3 US1**: T012 ∥ T013 ∥ T016; T014 ∥ T015 after T017 starts
- **Plan Wave 1 (post-Foundational)**:
  - **Stream A** (`scripts/agent_call.py`): T017–T021, T025 (US1 + US2)
  - **Stream B** (`orchestrator.py` + `run_report.py`): T030–T032 (US3) — after T008 schema stable
  - **Stream C** (`research.py` + `scout.py` + `_cycle_helpers.py`): T033–T035 (US3) — after T036 CLI contract defined
- **Phase 6**: T040 ∥ T043 ∥ T044

---

## Parallel Example: User Story 1

```bash
# After Phase 2 completes — tests in parallel:
# Task T012: tests/scripts/test_agent_call_sidecar_v1.py stream parser cases
# Task T013: tests/scripts/test_agent_call.py AgentCallResult mock
# Task T016: tests/scripts/test_agent_call_dispatch_live.py (skip unless -m live_llm)

# Then serialize implementation T017 → T018 → T019 → T020 → T021
```

## Parallel Example: User Story 3

```bash
# After US1 T019 lands sidecar v1.1 shape:
# Stream B (orchestrator):
#   T030 src/research_framework/pipeline/orchestrator.py &
# Stream C (call sites):
#   T033 src/research_framework/pipeline/steps/research.py &
#   T034 src/research_framework/pipeline/steps/scout.py &
wait
# Then T036 scripts/agent_call.py CLI writer (feeds both streams)
```

## Parallel Example: Plan Wave 1A / 1B / 1C

| Track | Tasks | Files |
|-------|-------|-------|
| **1A dispatch core** | T005–T011, T017–T021, T025 | `scripts/agent_call.py`, `tests/_helpers/fake_agent.py` |
| **1B consumers** | T030–T032 | `orchestrator.py`, `run_report.py` |
| **1C CLI call sites** | T033–T035, T036–T037 | `steps/research.py`, `steps/scout.py`, `_cycle_helpers.py` |

**Serialize**: 1A stream-json extract (T005) before 1C; 1B after v1.1 test fixtures (T004); Wave 2 = T038–T044 integration.

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1–2 (schema + parser + allocator + contract tests)
2. Complete Phase 3 (US1) — honest `dispatch()` telemetry
3. **STOP and VALIDATE**: `pytest tests/pipeline/test_plan_narrator.py tests/scripts/test_agent_call_sidecar_v1.py -m "not live_llm"`
4. Demo: inspect `agent-calls/plan_narrator.json` on a minimal vault cycle

### Incremental Delivery

1. Foundation → US1 (MVP) → US3 (production batch cost fix) → US2 (collision hardening) → Polish  
   *Rationale*: US3 fixes live multi-batch under-reporting; US2 is forward-compat for future stage migrations but allocator ships in US1/US2.

### Parallel Team Strategy

- **Dev A**: Phase 2 + US1 + US2 (`scripts/agent_call.py` + dispatch tests)
- **Dev B**: US3 orchestrator + run_report (after T004 schema fixture)
- **Dev C**: US3 pipeline steps + CLI `--cost-sidecar` (after T036 interface agreed)

---

## Acceptance coverage

| User Story | Evidence (test tasks) |
|------------|-------------------------|
| US1 — Per-call cost telemetry | T004, T011–T016, T017–T021 (`test_plan_narrator.py`, `test_cycle_runner_probe.py`, `test_agent_call_dispatch_live.py`) |
| US2 — Sidecar non-collision | T010, T022–T025 (`test_dispatch_sidecar_collision.py`, `test_quality_report_retry_sidecar.py`) |
| US3 — Per-batch note-writer costs | T027–T037 (`test_sum_sidecar_costs_batches.py`, `test_budget_cap_multi_batch.py`, `test_agent_call.py` CLI) |

| FR/SC | Task IDs |
|-------|----------|
| FR-001 | T005, T012, T017 |
| FR-002 | T006, T007, T011 |
| FR-003 | T007, T011, T020 |
| FR-004 | T007, T011, T021 |
| FR-005 | T009, T010, T022, T025 |
| FR-006 | T033–T037 |
| FR-007 | T027, T030 |
| FR-008 | T004–T029, T038 (matrix) |
| FR-009 | T023 |
| FR-010 | T013, T018 |
| FR-011 | T004, T020, T027, T030 |
| FR-012 | T024, T026 |
| SC-001 | T016 |
| SC-002 | T011, T014, T015 |
| SC-003 | T022 |
| SC-004 | T027 |
| SC-005 | T028 |

---

## Notes

- **Principle V**: No new pip dependencies; JSON Schema validation uses stdlib `json` + existing test patterns (or lightweight manual required-field asserts if schema lib absent).
- **Principle IV**: All LLM subprocesses remain in `scripts/agent_call.py`; pipeline steps only pass `--cost-sidecar` paths.
- **Filename convention**: Per-batch files are `note_writer-batch-{B}.json` (not `research-batch-*`) — `research.py` passes `--stage note_writer` per `contracts/sidecar-v1.contract.md` §1.1 note.
- **Legacy paths**: Hard-cut read/write retirement of `cycle-{N}-scout.cost.json` / `cycle-{N}-research.cost.json` per research R3 open item #3.
- **Fake-agent**: Sentinel timestamp strings are byte-stable; quality harness may need baseline refresh (T043).
- **Spec 033**: This spec's `sidecar-v1.contract.md` is load-bearing for cost enforcement — ship 028 before 033 implementation.
