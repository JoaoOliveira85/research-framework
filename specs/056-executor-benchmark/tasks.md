# Tasks: Executor × Model Benchmarking Harness (Spec 056)

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Branch**: `056-executor-benchmark` · **Eval tooling**
**Inputs**: [spec.md](./spec.md), [plan.md](./plan.md), [research.md](./research.md), [contracts/](./contracts/)

**Format**: `[ID] [P?] [Story] Description` — `[P]` = parallelizable.

> **Hard deps shipped on `main`**: spec 022 metric calculators, 028 sidecars v1.1,
> 033 cost estimator. **Soft**: spec 052 (`cursor-agent` row optional).
>
> **TDD discipline**: hermetic tests precede implementation; live sweep is manual
> only (FR-001). Structured for foreman `### Testing Requirements` enrichment (ADR-0010).

## Phase 0 — Spec-kit artifacts ✅ (this pass)

- T001 spec.md clarified (Q1–Q6) + FR-016..FR-019 + SC-009..SC-010.
- T002 [contracts/benchmark-matrix.contract.md](./contracts/benchmark-matrix.contract.md) + [contracts/benchmark-report.contract.md](./contracts/benchmark-report.contract.md).
- T003 research.md + plan.md + checklist + analyze-2026-06-03.md.

## Phase 1 — Setup

- T004 [P] Create committed fixture `tests/fixtures/benchmark/` — minimal vault
  (`research.spec.md`, `settings.yaml`), `benchmark-matrix.yaml` (2×2 default),
  `tasks/{scout-prompt,note-writer-prompt,verifier-prompt}.txt`,
  `tasks/verifier-draft.md`, `manifest.json` (`topics_expected` for scout), and
  `fake_agent_responses/responses.json` for hermetic replay. Data only. Also added
  `benchmark-matrix.full.yaml` (claude+codex+cursor-agent+ollama sweep).
- T005 [P] Add `.gitignore` entries for `tests/fixtures/benchmark/_pipeline/` and
  document in contract §1 (FR-018).
- T006 Scaffold `src/research_framework/benchmark/` (`__init__.py`, `matrix.py`,
  `scoring.py`, `reporter.py`, `gating.py`, `runner.py`) + `scripts/benchmark_executors.py`.

## Phase 2 — Foundational (blocking)

### Tests (MUST fail first)

- T007 [P] `tests/benchmark/unit/test_matrix_contract.py::test_load_default_matrix_three_tasks`
  — loads fixture YAML; asserts tasks = scout/note-writer/verifier (FR-016, SC-009).
- T008 [P] `...::test_unknown_task_rejected` — `tasks: [ask]` ⇒ load error.
- T009 [P] `...::test_unknown_runtime_rejected` — invalid `runtime` ⇒ load error.
  (+ `test_ollama_runtime_is_valid` — HTTP runtimes from spec 047 are dispatchable.)
- T010 [P] `...::test_scope_filters_cells` — `--task scout --model haiku` reduces
  cell count (FR-002).

### Implementation

- T011 Implement `matrix.py` — load YAML, validate v1 task ids + runtime keys
  against `_RUNTIME_ADAPTERS` **∪ `_HTTP_RUNTIMES`** (so spec-047 ollama + spec-052
  cursor-agent are valid), expand `{task×executor×model}` cells, apply CLI scope.
  Make T007–T010 pass.

## Phase 3 — US1: Matrix sweep + report (P1) 🎯 MVP

### Tests (MUST fail first)

- T012 [P] [US1] `tests/benchmark/unit/test_scoring_contract.py::test_scout_quality_scalar`
  — table-driven scout JSON → `quality` + `quality_detail` per contract §4.
- T013 [P] [US1] `...::test_note_writer_quality_scalar` — synthetic note artifact →
  022 `template_compliance_pct` mapping (FR-005, FR-017). NOTE: the 022 metric is already
  a 0..1 ratio, used directly as `quality` (contract's historical `/100` corrected in
  scoring.py docstring).
- T014 [P] [US1] `...::test_verifier_quality_scalar` — accept/reject JSON → 1.0/0.0.
- T015 [P] [US1] `tests/benchmark/unit/test_scoring_contract.py::test_rescore_identical`
  — re-run scorer on `scored.json` ⇒ same `quality` (FR-014, SC-002).
- T016 [P] [US1] `tests/benchmark/unit/test_reporter_contract.py::test_report_json_schema`
  — golden `report.json` shape from fake-agent run dir (FR-008).
- T017 [P] [US1] `...::test_report_md_per_task_tables` — three task sections, no
  cross-task aggregate score (FR-015, SC-008 layout).

### Implementation

- T018 [US1] `scoring.py` — per-task scorers + `scored.json` writer (contract §4).
- T019 [US1] `reporter.py` — merge cells → `report.json` + `report.md`; monotonic
  `run-id` directory creation (FR-008, FR-009, FR-018).
- T020 [US1] `runner.py` — **hermetic path**: drive cells via recorded
  `fake_agent_responses/responses.json` (no live LLM); recorded latency + cost from the
  fixture. Wired `scripts/benchmark_executors.py --dry-run` to this path.
- T021 [US1] `tests/benchmark/unit/test_runner_hermetic.py::test_full_matrix_fake_agent`
  — 2×2×3 dry-run produces 12 `ok` cells + report files (SC-001 hermetic variant).
- T022 [US1] `...::test_per_task_ranking_differs` — fixture engineered so best
  executor differs (scout→claude, note-writer→codex) (SC-008).

## Phase 4 — US2: Cost-safe live path (P2)

### Tests (MUST fail first)

- T023 [P] [US2] `tests/benchmark/unit/test_gating.py::test_headless_refuses_without_ack`
  — no `--yes` / env ⇒ exit non-zero, zero subprocess dispatch (SC-003).
- T024 [P] [US2] `...::test_tty_requires_confirm` — mock isatty + stdin 'n' ⇒ no dispatch.
- T025 [P] [US2] `...::test_max_usd_stops_with_partial_report` — cap below estimate ⇒
  partial `cells` preserved (FR-007).
- T026 [P] [US2] `...::test_cost_na_when_sidecar_missing_cost` — FR-013.

### Implementation

- T027 [US2] `gating.py` — pre-run estimate (cell × ceiling), TTY/headless ack
  (FR-019), inclusive `--max-usd` cap; integrated into CLI live path.
- T028 [US2] `runner.py` live path — subprocess `agent_call.py` per cell against a
  per-cell vault pinning runtime+model; read 028 sidecar `cost_usd` + latency; skip/fail
  isolation (FR-011, FR-012, SC-005).
- T029 [US2] Document live invocation in `specs/056-executor-benchmark/quickstart.md`
  (API keys, `--yes`, expected spend).

## Phase 5 — US3: One-line matrix edits (P3)

- T030 [P] [US3] `tests/benchmark/unit/test_matrix_contract.py::test_add_model_expands_cells`
  — append one model string ⇒ +N cells, no code change (FR-010, SC-004).
- T031 [US3] `tests/benchmark/unit/test_runner_hermetic.py::test_dispatch_unavailable_skipped`
  — mock `agent_call` failure (exit 2 / missing key) ⇒ `status: skipped`, sweep
  continues (FR-011). *(cursor-agent + ollama both ship now, so both load cleanly in
  `benchmark-matrix.full.yaml`.)*

## Phase 6 — US4: Retained dated reports (P3)

- T032 [P] [US4] `tests/benchmark/unit/test_reporter_contract.py::test_second_run_preserves_first`
  — two `run-id` dirs coexist; deltas derivable (FR-009, SC-006).
- T033 [US4] `reporter.py` — refuse clobber if `run-id` exists (defensive); `--list-runs`
  in CLI.

## Phase 7 — Guards & polish

- T034 [P] `tests/benchmark/unit/test_marker_isolation.py` — AST scan: no benchmark
  test imports `subprocess` or calls `live_dispatch` without `@pytest.mark.live_llm`
  (SC-007, SC-010).
- T035 [P] `tests/benchmark/unit/test_build_exclusion.py` — benchmark script + package
  absent from `build.sh`/`release.yml`; no src hot-path imports the package; dispatch
  allowlist stays empty (FR-001, SC-007, SC-010).
- T036 [P] Optional `tests/benchmark/test_benchmark_live_smoke.py` with
  `@pytest.mark.live_llm` — single scoped cell; documented as manual only.
- T037 `ruff check .` + `ruff format --check .` + benchmark suite green (32 passed,
  1 live_llm skipped).
- [ ] T038 Doc-sync on ship: spec → SHIPPED; ROADMAP; CHANGELOG; issue close (per
  CLAUDE.md checklist) — **out of implementer scope until merge**.

## Dependencies & ordering

- T011 blocks T020/T028 (matrix expansion).
- T018 blocks T019/T020 (scoring before report).
- T027 blocks live T028 (gating before dispatch).
- US1 hermetic (T020–T022) before US2 live (T028) is the recommended MVP stop.

## Acceptance coverage

| Requirement | Tasks |
|-------------|-------|
| FR-001 / SC-007 / SC-010 | T034, T035, T036 (optional) |
| FR-002 | T010, T020, T028 |
| FR-003 | T004, T020, T028 |
| FR-004 | T018, T020, T028 |
| FR-005 / FR-014 / FR-017 | T012–T015, T018 |
| FR-006 | T020, T026, T028 |
| FR-007 / FR-019 / SC-003 | T023–T025, T027 |
| FR-008 | T016, T017, T019 |
| FR-009 / FR-018 / SC-006 | T005, T019, T032, T033 |
| FR-010 / SC-004 | T030 |
| FR-011 / FR-012 / SC-005 | T028, T031 |
| FR-013 | T026 |
| FR-015 / SC-008 | T017, T022 |
| FR-016 / SC-009 | T007, T008 |
| SC-001 | T021 (hermetic); T029 (live doc) |
| SC-002 | T015 |

| User story | Tasks |
|------------|-------|
| US1 — compare matrix | T012–T022 |
| US2 — cost-safe live | T023–T029 |
| US3 — one-line edits | T030, T031 |
| US4 — trending | T032, T033 |
