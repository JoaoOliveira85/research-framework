---

description: "Task list for spec 022 — E2E Quality + Test Harness"
---

# Tasks: E2E Quality + Test Harness

**Input**: Design documents from `/specs/022-e2e-quality-harness/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: Tests are REQUIRED for this spec. Constitution Principle III (TDD-NON-NEGOTIABLE) and every user story's `Acceptance Scenarios` block in spec.md mandate test-first development. ADR-0008 § Regression discipline applies — every defect-fix during impl gains a `### Fixed` CHANGELOG entry with a `(regression test: <path>)` annotation.

**Organization**: Tasks are grouped by user story per the spec's `## User Scenarios & Testing` block. The three P1 stories together comprise the MVP (US1 depends on US2 + US3 outputs); within the P1 cluster the recommended implementation order is **US3 → US2 → US1** even though the task numbering follows spec-priority order.

**Terminology note** — "Phase 1" in this document refers to the **spec-kit Phase 1 (Setup / scaffolding)** below, NOT to the **vault-generation Phase 1 (infrastructure)** the constitution's "Always Do" #1 references (`pytest scripts/tests/` before vault Phase 2). The constitution's vault-phase numbering targets generated vaults, not the spec-kit's task-list phases. No conflict.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1 / US2 / US3 / US4 / US5 / US6)
- Include exact file paths in descriptions

## Path Conventions

Single-project structure (per `plan.md` § Project Structure). All paths are repo-root-relative:

- Source: `src/research_framework/`
- Tests: `tests/quality/` (new namespace, owned by 022 per ADR-0008)
- Fixtures: `tests/fixtures/quality/` (new namespace, owned by 022)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project scaffolding — directory tree, `.gitignore`, pytest-marker verification.

- [ ] T001 Create directory skeleton: `src/research_framework/quality/`, `src/research_framework/quality/metrics/`, `tests/quality/`, `tests/quality/unit/`, `tests/fixtures/quality/`, `tests/fixtures/quality/baselines/` (mkdir -p) per `plan.md` § Project Structure.
- [ ] T002 [P] Add `_pipeline/quality/` and `tests/fixtures/quality/**/_pipeline/` to `.gitignore` so harness-run artefacts and fixture-vault run artefacts never enter git.
- [ ] T003 [P] Verify `e2e` and `slow` pytest markers are already registered in `pyproject.toml`'s `[tool.pytest.ini_options].markers` (per ADR-0008). If missing, add them with one-line descriptions.
- [ ] T004 [P] Create empty `src/research_framework/quality/__init__.py` exposing `__version__` from package root (re-export `research_framework.__version__`).
- [ ] T005 [P] Create `tests/quality/__init__.py` and `tests/quality/unit/__init__.py` as empty markers so pytest collection treats them as packages.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared types, deterministic-write helpers, fixture-path resolution. These are imported by every metric family, every harness test, and the baseline-update CLI.

**⚠️ CRITICAL**: No user-story work can begin until this phase is complete.

- [ ] T006 [P] Define `Fixture` dataclass (`name`, `vault_dir`, `spec_path`, `settings_path`, `coverage_targets_path`, `fake_agent_responses_dir`, `note_count_target`, `failure_mode`) in `src/research_framework/quality/models.py` per `data-model.md` § 1.
- [ ] T007 [P] Define `MetricFamily`, `CycleOutput`, `BaselineJSON`, `CurrentJSON`, `RegressionReport` dataclasses in `src/research_framework/quality/models.py` per `data-model.md` § 2–6. All fields explicitly typed; all defaults frozen-dataclass-safe.
- [ ] T008 [P] Define `REGISTERED_FIXTURES` constant + `resolve_fixture(name) -> Fixture` helper in `src/research_framework/quality/runner.py`. Hard-coded mapping: `tech-lite → code-derived-topic-discovery`, `source-poor → gap-pursuit-substitution`, `source-rich → source-quality-pruning` (per FR-011).
- [ ] T009 Implement `canonical_json_dumps(payload) -> str` and `canonical_json_write(path, payload)` in `src/research_framework/quality/determinism.py` per `contracts/baseline-schema.contract.md` § 1 determinism rules (sort_keys=True, indent=2, separators=(',', ': '), ensure_ascii=False, trailing newline, 4-decimal float truncation, list-sort by documented key).
- [ ] T010 Implement `assert_deterministic(payload, label)` in `src/research_framework/quality/determinism.py` — re-serialises and compares, raising `DeterminismError` with a unified-diff on mismatch (per research.md § D2).
- [ ] T011 Implement `coverage_targets_hash(coverage_targets_path) -> str` in `src/research_framework/quality/baseline.py` — SHA-256 of the canonical-JSON of `categories[].{name, required_count, note_type}` triples only (per research.md § D3, OI-1). Returns `"sha256:<hex>"`.
- [ ] T012 [P] Tier-1 unit tests for `canonical_json_dumps` + `assert_deterministic` in `tests/quality/unit/test_determinism_guard.py`. Cover: nested dict ordering, list-sort by documented key, float truncation, divergence detection.
- [ ] T013 [P] Tier-1 unit tests for `coverage_targets_hash` in `tests/quality/unit/test_coverage_targets_hash.py`. Cover: stable hash across reorderings; mutating `categories[].current` does NOT change the hash; mutating `categories[].required_count` DOES change the hash.
- [ ] T014 Extend `tests/_helpers/vault_factory.py` with `build_quality_fixture(name, vault_dir, *, spec_yaml, note_count_target, fake_agent_responses_src) -> Path` per research.md § D6. Writes spec.md, settings.yaml, coverage-targets.json, `_templates/`, and copies fake_agent_responses tree. Idempotent: re-running on existing fixture is a no-op if hashes match.
- [ ] T015 [P] Contract test `tests/_helpers/test_build_quality_fixture_contract.py` verifies T014's function shape matches research.md § D6.

**Checkpoint**: Foundation ready — user-story work can now begin in parallel.

---

## Phase 3: User Story 1 — Baseline-driven regression gate on three fixtures (Priority: P1) 🎯 MVP

**Goal**: Wire the orchestrator that exercises 3 fixture vaults end-to-end, computes the 3 v1 metric families, writes per-fixture `current.json`, diffs against committed `baseline.json`, and exits 0 / 1 / 2 per the regression rules in `contracts/regression-report.contract.md` § 2.

**Independent Test** (from spec.md): Run `./build.sh --quality` twice on the same commit; both runs produce identical `current.json`; diff against `baseline.json` is empty; exit 0. Then deliberately regress one metric (lower a fixture's coverage target by 20%) and assert exit 1 with the regressed metric named.

**Note**: US1 integrates outputs from US2 (metrics) and US3 (fixtures). Per the recommended order (see Implementation Strategy), implement US3 + US2 first; then return here and complete US1.

### Tests for User Story 1 (write FIRST, ensure they FAIL before implementation)

- [ ] T016 [P] [US1] Tier-6 acceptance test `tests/quality/test_quality_harness_regression_gate.py::test_no_change_run_passes` for spec.md US1 scenario 1: no behaviour changes → exit 0, "0 regressions, 0 warnings".
- [ ] T017 [P] [US1] Tier-6 acceptance test `tests/quality/test_quality_harness_regression_gate.py::test_20pct_drop_fails` for spec.md US1 scenario 2: 20% coverage drop on `tech-lite` → exit 1, report names metric+magnitude+fixture.
- [ ] T018 [P] [US1] Tier-6 acceptance test `tests/quality/test_quality_harness_regression_gate.py::test_10pct_drop_warns` for spec.md US1 scenario 3: 10% drop → exit 0 + warning printed to stdout + per-metric `verdict == "warn"` in `_pipeline/quality/regression-report.json` for the affected metric (warns are encoded via the regression report, not a separate `quality-warnings.json` file).
- [ ] T019 [P] [US1] Tier-6 acceptance test `tests/quality/test_quality_harness_regression_gate.py::test_explicit_baseline_update_applies` for spec.md US1 scenario 4: after `./vault quality-baseline-update tech-lite` + confirmation, next run uses new baseline.

### Implementation for User Story 1

- [ ] T020 [US1] Implement `diff_against_baseline(current: CurrentJSON, baseline: BaselineJSON) -> RegressionReport` in `src/research_framework/quality/baseline.py` per `contracts/baseline-schema.contract.md` § 3 + `contracts/regression-report.contract.md` § 2. Encodes the moderate-gate thresholds (`fail` ≥ 15%, `warn` 5–15%, otherwise `pass`) as `REGRESSION_FAIL_PCT = 15.0` / `REGRESSION_WARN_PCT = 5.0` constants (resolves research.md OI-2).
- [ ] T021 [US1] Implement `write_regression_report(report: RegressionReport, output_dir: Path) -> Path` in `src/research_framework/quality/report.py` — calls `canonical_json_write` to `_pipeline/quality/regression-report.json`.
- [ ] T022 [US1] Implement `print_regression_summary(report: RegressionReport, stream, *, color: bool) -> None` in `src/research_framework/quality/report.py` per `contracts/regression-report.contract.md` § 3 stdout format. Auto-disable ANSI when `stream` is not a TTY.
- [ ] T023 [US1] Implement `run(fixtures: list[str] | None = None, *, output_dir: Path | None = None, color: bool | None = None) -> int` in `src/research_framework/quality/runner.py` — top-level orchestrator. Loops over fixtures, invokes `research_framework.pipeline.cycle_runner.run_cycle_steps` in-process per research.md § D4, collects `CycleOutput`s, calls metric-family compute_fns from US2, writes per-fixture `current.json`, diffs against baseline, calls T021+T022, returns exit code.
- [ ] T024 [US1] Implement coverage-targets-hash check at run-time in `runner.py::run` (FR-017): before computing metrics for a fixture, compare `coverage_targets_hash(fixture)` against the baseline's stored hash; on mismatch raise `BaselineStaleError`.
- [ ] T025 [US1] Implement the 6 failure-category messages in `src/research_framework/quality/runner.py` (`regression`, `baseline-missing`, `baseline-stale`, `fixture-not-initialised`, `cycle-runner-crash`, `determinism-violation`) per `contracts/regression-report.contract.md` § 5. Each is a sentinel exception class with a `format_stderr_line(fixture: str) -> str` method.
- [ ] T026 [US1] Implement `cycle-runner-crash` isolation in `runner.py::run` per research.md § D4 risk note: wrap each fixture's `run_cycle_steps` call in `try/except`, record crash as a `cycle_health` metric warning, continue with the next fixture; harness exits non-zero only if ALL fixtures crash OR any fixture has a real regression (resolves research.md OI-3).
- [ ] T027 [US1] Map exit codes per `contracts/regression-report.contract.md` § 2: `0` pass/warn; `1` regression fail; `2` harness crash (uncaught exception, baseline-missing, baseline-stale, fixture-not-initialised, determinism-violation).
- [ ] T028 [US1] Update `## Acceptance coverage` table in `specs/022-e2e-quality-harness/spec.md` US1 row → `tests/quality/test_quality_harness_regression_gate.py`.

**Checkpoint**: US1 fully wired. End-to-end harness run produces a regression report and exits with the correct code. Does NOT yet run from CI or from `./build.sh --quality` (those are US5).

---

## Phase 4: User Story 2 — Three v1 metric families produce stable, comparable scores (Priority: P1)

**Goal**: Implement the three v1 metric families (`coverage`, `cycle_health`, `note_quality`) as deterministic, byte-identical compute functions. Each family is independently unit-testable against a synthetic `CycleOutput` stub.

**Independent Test** (from spec.md): For each fixture, run the harness twice and assert `current_run_1.json == current_run_2.json` byte-for-byte (modulo `run_timestamp`). For each metric family in isolation, run with stub `CycleOutput` fixtures and assert byte-identical output across calls.

### Tests for User Story 2 (write FIRST)

- [ ] T029 [P] [US2] Tier-1 unit tests `tests/quality/unit/test_coverage_metric.py` covering spec.md US2 scenario 2 (`{coverage_pct, notes_per_category, spec_drift}` reproducible from a `CycleOutput` stub) and US2 scenario 1 (byte-identical across two calls).
- [ ] T030 [P] [US2] Tier-1 unit tests `tests/quality/unit/test_cycle_health_metric.py` covering spec.md US2 scenario 3 (SG-NNN trip counts + retry-once rate from synthetic `CycleOutput`) AND `verifier_reject_rate` computation (rejected / total verifier invocations; consumed by spec.md US3 scenario 3).
- [ ] T031 [P] [US2] Tier-1 unit tests `tests/quality/unit/test_note_quality_metric.py` covering spec.md US2 scenario 4 (per-template-section fill rates; binary filled / MISSING; no fuzzy partial states).
- [ ] T032 [P] [US2] Tier-6 determinism integration test `tests/quality/test_metric_determinism.py` — runs all three metric families on `tech-lite` twice and asserts `current.json` byte-identical (spec.md US2 scenario 1, in-the-harness variant).

### Implementation for User Story 2

- [ ] T033 [P] [US2] Implement `compute_coverage_metric(fixture: Fixture, cycle_outputs: list[CycleOutput]) -> dict` in `src/research_framework/quality/metrics/coverage.py` per `data-model.md` § 2 v1 inventory: `coverage_pct` (% of `coverage-targets.json` categories with `current >= required`), `notes_per_category` (dict[category → int]), `spec_drift` (# of vault categories not in spec / total). All values truncated to 4 decimals before return.
- [ ] T034 [P] [US2] Implement `compute_cycle_health_metric(fixture: Fixture, cycle_outputs: list[CycleOutput]) -> dict` in `src/research_framework/quality/metrics/cycle_health.py`: `cycles_pass` (count of cycle_outputs with exit_code == 0), `cycles_fail`, `sg002_trip_count` (sum of SG-002 firings across cycles from `cycle_outputs[i].sg_trips`), `retry_once_rate` (retries / total attempts; from cycle's quality report JSON), `verifier_reject_rate` (verifier-rejected notes / total verifier invocations across all cycles; asserted by spec.md US3 scenario 3). All values truncated to 4 decimals before return.
- [ ] T035 [P] [US2] Implement `compute_note_quality_metric(fixture: Fixture, cycle_outputs: list[CycleOutput]) -> dict` in `src/research_framework/quality/metrics/note_quality.py`: `template_compliance_pct` (% of written notes that match their template's section structure), `per_template_section_fill` (dict[section_heading → fill_pct]), `acronym_link_pct` (% of first-acronym occurrences wikilinked).
- [ ] T036 [US2] Register all three families in `src/research_framework/quality/metrics/__init__.py` as `REGISTERED_METRIC_FAMILIES = [MetricFamily(...)]` with `baseline_subset` declarations per `data-model.md` § 2.
- [ ] T037 [US2] Wire `runner.py::run` (from T023) to iterate over `REGISTERED_METRIC_FAMILIES` and merge their outputs into `CurrentJSON.metrics`. Confirm metric compute_fns are pure (no I/O beyond reading the cycle's already-written quality report JSON).
- [ ] T038 [US2] Verify SC-001 end-to-end: extend T032 to confirm running the full harness on `tech-lite` twice produces byte-identical `current.json`.
- [ ] T039 [US2] Update `## Acceptance coverage` table in spec.md US2 row → `tests/quality/unit/test_coverage_metric.py`, `tests/quality/unit/test_cycle_health_metric.py`, `tests/quality/unit/test_note_quality_metric.py`, `tests/quality/test_metric_determinism.py`.

**Checkpoint**: US2 complete. Metric calculators are byte-deterministic, unit-tested, and integrated with the orchestrator from US1.

---

## Phase 5: User Story 3 — Three fixture vaults exercise distinct failure modes (Priority: P1)

**Goal**: Author the three v1 fixture vaults (`tech-lite`, `source-poor`, `source-rich`) under `tests/fixtures/quality/`. Each fixture exercises a distinct failure mode (FR-011): `code-derived-topic-discovery`, `gap-pursuit-substitution`, `source-quality-pruning`. Each ships with ~15–20 vault-shaped notes per cycle and a canned `fake_agent_responses/` tree.

**Independent Test** (from spec.md): For each fixture, snapshot the cycle's `_pipeline/cycle-NNN-research.json` and confirm fixture-specific assertions (5+ code-derived topics on `tech-lite`; SG-002 trips on `source-poor`; ≥3 notes/category on `source-rich` for ≥80% of categories).

### Tests for User Story 3 (write FIRST)

- [ ] T040 [P] [US3] Tier-6 e2e test `tests/quality/test_quality_harness_tech_lite.py::test_code_derived_topic_count` for spec.md US3 scenario 1: `tech-lite` 3-cycle harness run produces `≥5` topics tagged `code-derived` and `notes_per_category[services] ≥ 3`.
- [ ] T041 [P] [US3] Tier-6 e2e test `tests/quality/test_quality_harness_source_poor.py::test_sg002_diversity_warning` for spec.md US3 scenario 2: at least one cycle in a 3-cycle `source-poor` run triggers SG-002 diversity-gate warning.
- [ ] T042 [P] [US3] Tier-6 e2e test `tests/quality/test_quality_harness_source_rich.py::test_no_overpruning` for spec.md US3 scenario 3: `source-rich` 3-cycle harness run produces `coverage_pct ≥ 0.80` and `verifier_reject_rate < 0.20`.
- [ ] T043 [P] [US3] Tier-6 fake-agent-interception test `tests/quality/test_fake_agent_interception.py` for spec.md US3 scenario 4: any LLM-bound call in a fixture's 3-cycle run is intercepted by fake_agent; no live `claude`/`codex` subprocess starts.

### Fixture authoring for User Story 3

- [ ] T044 [P] [US3] Author `tests/fixtures/quality/tech-lite/research.spec.md` — small Java service domain, 5+ services + 3+ flows + 4+ concepts in coverage targets (the failure-mode signal: code-derived topic discovery).
- [ ] T045 [P] [US3] Author `tests/fixtures/quality/tech-lite/settings.yaml` pointing `cycle.runner.fake_agent_responses_dir` at the fixture's `fake_agent_responses/`. `max_cycles: 3`.
- [ ] T046 [P] [US3] Author `tests/fixtures/quality/tech-lite/coverage-targets.json` matching the spec from T044.
- [ ] T047 [P] [US3] Author `tests/fixtures/quality/tech-lite/_templates/{service,flow,concept,decision}.md` mirroring production templates (or copy + truncate from `dist-templates/`).
- [ ] T048 [US3] Author `tests/fixtures/quality/tech-lite/fake_agent_responses/{scout,note_writer,verifier,narrator,probe_retrieval}/` static JSON trees producing ~15–20 vault-shaped notes per cycle (FR-009, clarify Q2 Option B). Synthetic content (lorem-ipsum-style); template-faithful structure.
- [ ] T049 [P] [US3] Author `tests/fixtures/quality/source-poor/{research.spec.md, settings.yaml, coverage-targets.json}` — deliberately under-resourced spec (few sources, ambitious targets) so the cycle hits SG-002 diversity gate.
- [ ] T050 [P] [US3] Author `tests/fixtures/quality/source-poor/_templates/` (same shape as tech-lite).
- [ ] T051 [US3] Author `tests/fixtures/quality/source-poor/fake_agent_responses/` producing the gap-pursuit-substitution failure-mode signal (scout flags missing sources, note_writer attempts substitution, verifier sometimes rejects).
- [ ] T052 [P] [US3] Author `tests/fixtures/quality/source-rich/{research.spec.md, settings.yaml, coverage-targets.json}` — curated high-quality source list, broad coverage targets that the fixture comfortably hits.
- [ ] T053 [P] [US3] Author `tests/fixtures/quality/source-rich/_templates/` (same shape).
- [ ] T054 [US3] Author `tests/fixtures/quality/source-rich/fake_agent_responses/` producing the source-quality-pruning failure-mode signal (high coverage_pct, low verifier reject rate, no over-pruning).
- [ ] T055 [US3] Smoke-run `python -m research_framework.quality.runner --fixture tech-lite` (after T023 lands) and confirm cycle output lands under `_pipeline/quality/tech-lite/`. Manually inspect ~3 generated notes to confirm vault-shaped output.
- [ ] T056 [US3] Repeat T055 for `source-poor` and `source-rich`.
- [ ] T057 [US3] Update `## Acceptance coverage` table in spec.md US3 row → `tests/quality/test_quality_harness_tech_lite.py`, `tests/quality/test_quality_harness_source_poor.py`, `tests/quality/test_quality_harness_source_rich.py`, `tests/quality/test_fake_agent_interception.py`.

**Checkpoint**: US3 complete. Three fixture vaults exist, are vault-shaped, exercise distinct failure modes, and produce expected metric signals. MVP (US1+US2+US3) is functionally complete pending baseline generation.

---

## Phase 6: User Story 4 — Baseline is human-updated, never harness-auto-updated (Priority: P2)

**Goal**: New `./vault quality-baseline-update <fixture>` CLI subcommand per `contracts/quality-cli.contract.md` § 2. Atomic write, interactive confirmation, `--dry-run`, `--reason` required. Guard test verifies only this codepath writes baselines.

**Independent Test** (from spec.md): No non-CLI codepath writes to `tests/fixtures/quality/baselines/*.baseline.json`. The CLI prompts the user; `n` declines and leaves the file unchanged; `y` overwrites atomically.

### Tests for User Story 4 (write FIRST)

- [ ] T058 [P] [US4] Tier-1 unit test `tests/quality/unit/test_baseline_update_cli.py::test_no_auto_update_on_improvement` for spec.md US4 scenario 1: improvement detected → harness does NOT overwrite baseline → exit 0 with improvement reported.
- [ ] T059 [P] [US4] Tier-1 unit test `tests/quality/unit/test_baseline_update_cli.py::test_confirmed_update_rewrites_file` for spec.md US4 scenario 2: confirm via stdin `y` → baseline overwritten with `last_updated`, `last_updated_by`, `last_updated_reason`.
- [ ] T060 [P] [US4] Tier-1 unit test `tests/quality/unit/test_baseline_update_cli.py::test_declined_update_preserves_file` for spec.md US4 scenario 3: `n` answer → baseline unchanged, stderr says "baseline not updated".
- [ ] T061 [P] [US4] Tier-1 unit test `tests/quality/unit/test_baseline_update_cli.py::test_dry_run_never_writes` confirms `--dry-run` prints diff but does NOT modify any file (Constitution Always-Do #2).
- [ ] T062 [P] [US4] Tier-2 guard test `tests/quality/test_baseline_update_isolation.py` — scans `src/`, `tests/`, `scripts/` for any `open(<baseline-path>, 'w'…)` or equivalent write to `tests/fixtures/quality/baselines/*.json`; allowlist contains only `src/research_framework/quality/baseline_update.py`. Fails per spec.md US4 scenario 4. **(satisfies FR-012)**

### Implementation for User Story 4

- [ ] T063 [US4] Implement `src/research_framework/quality/baseline_update.py::update_baseline(fixture: str, *, reason: str, actor: str, dry_run: bool, yes: bool) -> int` per `contracts/quality-cli.contract.md` § 2. Atomic write via tempfile + `os.replace`; interrupt-safe (no partial baseline on SIGINT).
- [ ] T064 [US4] Add `quality-baseline-update` subcommand to `src/research_framework/cli.py` calling `baseline_update.update_baseline`. Help text matches `contracts/quality-cli.contract.md` § 2 surface; rejects empty `--reason` unless `--dry-run`.
- [ ] T065 [US4] Wire `$CI` env-var check into `baseline_update.update_baseline`: `--yes` is rejected (exit 2) unless `$CI` is set (loose protection against accidental local non-interactive update).
- [ ] T066 [US4] Update `## Acceptance coverage` table in spec.md US4 row → `tests/quality/unit/test_baseline_update_cli.py`, `tests/quality/test_baseline_update_isolation.py`.

**Checkpoint**: US4 complete. Baseline mutation is human-only, single-codepath, atomic, dry-runnable.

---

## Phase 7: User Story 5 — Harness runs in CI, not in `pytest -m "not e2e"` (Priority: P2)

**Goal**: Wire the harness into `./build.sh --quality` (additive flag) and into `.github/workflows/quality.yml` (tag-push + `workflow_dispatch` only). Confirm the harness does NOT collect under `pytest -m "not e2e"`.

**Independent Test** (from spec.md): `pytest -m "not e2e"` collects 0 tests from `tests/quality/`; `pytest -m e2e tests/quality/` runs the full harness; `./build.sh` (no flag) does NOT run the harness; `./build.sh --quality` runs smoke gate + harness in sequence.

### Tests for User Story 5 (write FIRST)

- [ ] T067 [P] [US5] Tier-2 marker-isolation guard `tests/quality/unit/test_marker_isolation.py` for spec.md US5 scenarios 1+2: parses `tests/quality/*.py` AST, asserts every harness e2e test has both `@pytest.mark.e2e` and `@pytest.mark.slow` decorators (tier-2 per ADR-0008 because it does file I/O + AST analysis, not a pure function).
- [ ] T068 [P] [US5] Tier-6 build.sh integration test `tests/quality/test_build_script_quality_flag.py` for spec.md US5 scenarios 3+4: runs `./build.sh` (no flag) in a subprocess, asserts harness did not execute; runs `./build.sh --quality` and asserts smoke ran first then harness (subprocess transitively drives the multi-cycle harness, hence tier-6).

### Implementation for User Story 5

- [ ] T069 [US5] Modify `build.sh` to accept `--quality [--fixture <name>] [--no-color]` per `contracts/quality-cli.contract.md` § 1. Smoke gate runs first; on smoke green, invoke `python -m research_framework.quality.runner` with optional fixture filter; exit with runner's exit code.
- [ ] T070 [US5] Add `--help` text to `build.sh` listing all flags including `--quality`.
- [ ] T071 [US5] Create `.github/workflows/quality.yml` per `contracts/quality-workflow.contract.md` § 1–7. Triggers: `push: tags v[0-9]+.[0-9]+.[0-9]+*`, `workflow_dispatch` (with `fixture` choice input). `runs-on: ubuntu-latest`, `timeout-minutes: 20`, `permissions: contents: read`, `concurrency: quality-${{ github.ref }} cancel-in-progress: true`. Uploads `_pipeline/quality/regression-report.json` as artifact `if: always()`.
- [ ] T072 [US5] Add `__main__.py` to `src/research_framework/quality/` so `python -m research_framework.quality.runner` is invokable (entry point for `build.sh` and the CI workflow).
- [ ] T073 [US5] Add `quality-fixture-init` stub subcommand to CLI (rejects all input with "fixture init is a v2 feature; for v1 fixtures use `./vault quality-baseline-update` after editing the fixture by hand") per `contracts/quality-cli.contract.md` § 3 — reserves the v2 subcommand name.
- [ ] T074 [US5] Update `## Acceptance coverage` table in spec.md US5 row → `tests/quality/unit/test_marker_isolation.py`, `tests/quality/test_build_script_quality_flag.py`.

**Checkpoint**: US5 complete. CI and local-build surfaces wired; fast-loop isolation guaranteed.

---

## Phase 8: User Story 6 — Spec acceptance coverage proves the harness exists (Priority: P3)

**Goal**: Demonstrate the ADR-0008 spec-acceptance-coverage convention by filling spec.md's `## Acceptance coverage` table with concrete test references for every US1–US5 row.

**Independent Test** (from spec.md): Read spec.md `## Acceptance coverage` section; every US1–US5 row has a non-`(deferred)` entry; spec 024's acceptance-coverage lint guard passes without an allowlist entry.

### Tasks for User Story 6

- [ ] T075 [US6] Cross-check: every `## Acceptance coverage` row in spec.md now contains a concrete test path (T028, T039, T057, T066, T074 completed) and the row text matches the test file's actual path. Resolves spec.md US6 scenario 1.
- [ ] T076 [US6] Add a smoke entry to `docs/testing-strategy.md` tier-6 row referencing spec 022's tier-6 tests (`tests/quality/test_quality_harness_*.py`) so the testing-strategy doc accurately reflects where tier-6 lives. (Spec 024's acceptance-coverage lint guard is not yet written; T075 verifies the format manually for now.)
- [ ] T077 [US6] Update `## Acceptance coverage` table in spec.md US6 row → "This section itself, plus the spec-024 lint guard once it ships" (already present in v1 draft; confirm wording matches and leave in place).

**Checkpoint**: US6 complete. Spec demonstrates the ADR-0008 convention from day one.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Doc updates, baseline generation (ship-PR-blessed flow per FR-016), performance verification, CHANGELOG.

- [ ] T078 [P] Generate initial baselines per FR-016 + quickstart.md § 4. On the ship branch immediately before commit, run `./build.sh --quality` (T069); use `./vault quality-baseline-update tech-lite --reason "Initial baseline at spec 022 v1 ship" --actor "$(git config user.name)"`; repeat for `source-poor` and `source-rich`; commit the three baseline JSON files in a focused commit `fixtures(022): initial baseline JSONs for tech-lite, source-poor, source-rich`.
- [ ] T079 [P] Update `docs/testing-strategy.md` tier-6 row to reference spec 022's harness and the new `./build.sh --quality` flag. Update tier-1 row if metric-calculator unit tests need a new sub-bullet.
- [ ] T080 [P] Update `CONTRIBUTING.md` with the soft-recommendation per FR-015: contributors running PRs that touch `src/research_framework/`, `scripts/`, or `tests/_helpers/fake_agent.py` SHOULD run `./build.sh --quality` locally before merge. Documentation obligation, not enforcement.
- [ ] T081 [P] Add CHANGELOG entry under `[Unreleased]` for spec 022 v1 ship: list the new `./build.sh --quality` flag, the new `./vault quality-baseline-update` subcommand, the new `.github/workflows/quality.yml` workflow, the new `tests/fixtures/quality/` namespace, the three fixture vaults, the three metric families, and the moderate regression gate thresholds. Cross-reference ADR-0008 + spec 022.
- [ ] T082 [P] Update `docs/ROADMAP.md`: flip queue item #1 from `[~]` (drafted) to `[x]` (shipped) on the version bump; move to "Completed (recent)" block with the ship version and date. Update "Strategic sequencing" block if ordering shifted.
- [ ] T083 [P] Update `CLAUDE.md` "Recent Changes" section with the v0.2.34 (or next version) ship-of-022 entry; prune to last 3-5 ship cycles.
- [ ] T084 Set spec.md status header to `**Status:** SHIPPED <version>` at the top of `specs/022-e2e-quality-harness/spec.md` per CLAUDE.md per-stage doc-update checklist.
- [ ] T085 Performance check: run `time ./build.sh --quality` on a recent Mac three times; record results; verify SC-006 (< 12 min total, < 10 min harness). If exceeded, profile and optimize before declaring ship-ready.
- [ ] T086 Determinism dry-run: run `./build.sh --quality` twice back-to-back; diff the two `_pipeline/quality/<fixture>.current.json` files (one per fixture); verify they are byte-identical modulo `run_timestamp` (SC-001).
- [ ] T087 Run `quickstart.md` § 1–4 verbatim on a clean checkout; capture any drift or surprises; update quickstart if any step is wrong.
- [ ] T088 SC-003 detection-rate validation: implement `tests/quality/test_detection_rate.py::test_deliberate_regression_caught_10_trials` — parametrise the deliberate-regression scenario from T017 across 10 independent harness invocations; assert exit code 1 + correctly-named metric+fixture in 10/10 runs (100% detection rate per SC-003). Decorate with `@pytest.mark.e2e + @pytest.mark.slow` (tier-6). Budget: < 90 s total (the harness is deterministic so 10 trials add modest cost).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — can start immediately.
- **Phase 2 (Foundational)**: Depends on Phase 1 — BLOCKS all user-story phases.
- **Phase 3–8 (User Stories)**: All depend on Phase 2 completion.
  - **Within the P1 cluster (US1, US2, US3)**: implementation order is **US3 → US2 → US1**. US3 (fixtures) is required before US1 (orchestrator) can run; US2 (metrics) is required before US1 can compute outputs. US2 + US3 can run in parallel.
  - **US4 (P2)**: depends on US1 (needs the orchestrator + diff to wire `quality-baseline-update`).
  - **US5 (P2)**: depends on US1 (build.sh + CI need a working `python -m research_framework.quality.runner`).
  - **US6 (P3)**: depends on US1–US5 (fills the acceptance-coverage table with their concrete test paths).
- **Phase 9 (Polish)**: depends on all user stories.

### User Story Dependencies (recommended sequence)

```text
Phase 1 Setup   ─┐
                 ├──> Phase 2 Foundational ──┬──> US3 ─┐
                                              │         ├──> US1 ─┬──> US4 ─┐
                                              └──> US2 ─┘         ├──> US5 ─┤
                                                                  └──> US6 ─┴──> Phase 9 Polish
```

### Within Each User Story

- Tests MUST be written and FAIL before implementation (Constitution Principle III).
- Models / dataclasses (already in Foundational) → metric / orchestrator code → integration test passing → spec.md acceptance-coverage row updated.

### Parallel Opportunities

- **Phase 1 Setup**: T002, T003, T004, T005 all marked [P] — run together after T001.
- **Phase 2 Foundational**: T006, T007, T008 are [P]; T009 (D2 determinism helper) blocks T010; T010 blocks T011 (hashing uses determinism). T012, T013, T015 are [P] test-tasks. T014 + T015 are sequential (impl + contract test).
- **US2 + US3** can be developed in parallel by different developers.
- Within **US3**: T044, T045, T046, T047, T049, T050, T052, T053 are all [P] (different files within different fixtures); T048, T051, T054 are sequential per-fixture (depend on the spec/settings/templates within that fixture).
- Within **US4**: T058–T061 + T062 (5 test tasks) are all [P].
- Within **US5**: T067 + T068 are [P]; T069 + T071 are [P] (different files).
- **Phase 9 Polish**: T078–T083 are [P]; T084–T087 are sequential (status flip, perf check, determinism check, quickstart smoke).

---

## Parallel Example: User Story 2

```bash
# Phase 4 — write all metric-calculator unit tests in parallel:
Task: "T029 [US2] Tier-1 unit tests for coverage metric in tests/quality/unit/test_coverage_metric.py"
Task: "T030 [US2] Tier-1 unit tests for cycle_health metric in tests/quality/unit/test_cycle_health_metric.py"
Task: "T031 [US2] Tier-1 unit tests for note_quality metric in tests/quality/unit/test_note_quality_metric.py"

# Then implement all three metric families in parallel:
Task: "T033 [US2] Implement compute_coverage_metric in src/research_framework/quality/metrics/coverage.py"
Task: "T034 [US2] Implement compute_cycle_health_metric in src/research_framework/quality/metrics/cycle_health.py"
Task: "T035 [US2] Implement compute_note_quality_metric in src/research_framework/quality/metrics/note_quality.py"
```

---

## Parallel Example: User Story 3 (fixture authoring)

```bash
# Per-fixture scaffolding can run in parallel across fixtures:
Task: "T044 [US3] tech-lite/research.spec.md"
Task: "T049 [US3] source-poor/research.spec.md"
Task: "T052 [US3] source-rich/research.spec.md"

# Within each fixture, settings + coverage + templates can be parallel:
Task: "T045 [US3] tech-lite/settings.yaml"
Task: "T046 [US3] tech-lite/coverage-targets.json"
Task: "T047 [US3] tech-lite/_templates/"

# fake_agent_responses content authoring is the slowest task per fixture (sequential per fixture):
Task: "T048 [US3] tech-lite/fake_agent_responses/"  # depends on T044-T047
Task: "T051 [US3] source-poor/fake_agent_responses/"  # depends on T049+T050
Task: "T054 [US3] source-rich/fake_agent_responses/"  # depends on T052+T053
```

---

## Implementation Strategy

### MVP definition

Unlike a typical spec where US1 = MVP, in spec 022 the MVP is the **full P1 cluster (US1 + US2 + US3 combined)**. None of the three P1 stories ship alone:

- US1 (orchestrator) cannot be tested without US2 (metrics) and US3 (fixtures).
- US2 (metrics) can be unit-tested alone, but ships no user-visible behavior.
- US3 (fixtures) is test data, not a feature.

**Recommended MVP delivery sequence**:

1. Complete **Phase 1 (Setup)**.
2. Complete **Phase 2 (Foundational)** — types, determinism helpers, hash helper, factory extension.
3. Parallel-execute **US3 (fixtures)** and **US2 (metrics)** — different developers if available.
4. Complete **US1 (orchestrator)** — wires US2 + US3 together; the four acceptance tests now pass end-to-end.
5. **STOP and VALIDATE**: Run `./build.sh --quality` (after T069 lands as part of US5) or `python -m research_framework.quality.runner` directly; confirm all three fixtures produce a `current.json`; spot-check the generated notes for vault-shape.
6. Ship US1+US2+US3 as the MVP increment. Generate baselines (T078) only when the MVP is green.

### Incremental Delivery (post-MVP)

1. MVP green → add **US4 (baseline-update CLI)** — closes the auto-update-prevention loop and the FR-012 guard.
2. Add **US5 (CI workflow + build.sh flag)** — gets the harness running in CI.
3. Add **US6 (acceptance-coverage table fill)** — administrative; demonstrates ADR-0008 convention.
4. Polish (Phase 9) → generate baselines (T078) → ship.

### Parallel Team Strategy

With two developers (recommended given the 2026-06-01 deadline):

- **Day 0**: Both devs complete Phase 1 + Phase 2 together.
- **Days 1–2**: Dev A on US3 (fixture authoring); Dev B on US2 (metric calculators).
- **Day 3**: Both devs converge on US1 (orchestrator) — wire metrics + fixtures, write acceptance tests.
- **Day 4**: Dev A on US4 (CLI); Dev B on US5 (CI workflow + build.sh).
- **Day 5**: Dev A on US6 + Polish (docs, CHANGELOG, ROADMAP flip); Dev B on baseline generation (T078) + perf/determinism checks (T085, T086) + quickstart smoke (T087).

Total estimated effort: ~5 person-days for the MVP+P2+P3+polish; comfortably fits the 2026-06-01 deadline window.

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks.
- [Story] label maps task to specific user story for traceability.
- Each user story should be independently *implementable* (after Foundational); only US1 has a hard run-time dependency on US2+US3 outputs (called out in dependency graph).
- Verify tests fail before implementing (TDD per Constitution Principle III).
- Commit after each task or logical group; preserve git history.
- Stop at any checkpoint to validate the increment.
- Avoid: vague tasks, same-file conflicts (none in this list — verified), cross-story dependencies that break independence (only the intentional US1→US2+US3 integration).
- Open items deferred from Phase 0/1 (research.md OI-1, OI-2, OI-3 and data-model.md OI-D1, OI-D2, OI-D3) are resolved inline by the indicated tasks (T011 resolves OI-1, T020 resolves OI-2, T026 resolves OI-3, T035 resolves OI-D1 by using flat dict, T021 resolves OI-D2 by using package version, T033/T034/T035 keep per-key gating to roll-ups only resolving OI-D3).
