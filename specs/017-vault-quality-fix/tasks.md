---

description: "Implementation task list for 017-vault-quality-fix"
---

# Tasks: Vault Quality Fix

**Input**: Design documents from `/specs/017-vault-quality-fix/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓, quickstart.md ✓
**Tests**: REQUIRED — Constitution Principle III (Test-First TDD) is NON-NEGOTIABLE for the `research_vault` codebase. Every implementation task is preceded by its failing tests.

**Organization**: Tasks are grouped by user story (US1..US9 from spec.md) so each can be implemented and tested independently. Stories are listed in priority order (P0 → P3); MVP = US1 + US2 + US9 (the three P0 stories — without all three, the whole feature is structurally incomplete because they together form the "shared plan + abstraction + gates" tripod).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story (US1..US9). Setup/Foundational/Polish phases have no story label.
- All file paths are repository-relative.

## Path Conventions

Single-project Python layout (per plan.md "Structure Decision"):

- Source: `src/research_vault/`
- Top-level helper scripts: `scripts/`
- Agent skills: `.agents/skills/`
- Tests: `tests/pipeline/` (NEW dir) and `tests/scripts/` (existing)
- Settings & defaults: `settings.yaml`, `settings.codex.yaml`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Repo plumbing for the new modules — directories, default settings, test layout.

- [X] T001 Create `tests/pipeline/` directory with `__init__.py` and add a docstring `"""Tests for src/research_vault/pipeline/ modules — feature 017."""` to keep `pyproject.toml`'s `pythonpath = ["src"]` discovery clean
- [X] T002 [P] Add the new feature-017 settings keys to `settings.yaml` and `settings.codex.yaml` (per quickstart.md §6 and research.md R-003/R-004): `pipeline.note_writer_batch_size: 6`, `pipeline.source_failure_thresholds.required_quorum_loss: 2`, `pipeline.source_failure_thresholds.enrichment_max_failures: 0`, `pipeline.queryability_score_regression_pp: 5`, and the `gates.cg_*`/`gates.sg_*` threshold block. Defaults match the spec's Story 9 thresholds.
- [X] T003 [P] Add `_pipeline/corrections/` and `_pipeline/cycles/` to the scaffold's `_pipeline/` directory creation list in `src/research_vault/generator/scaffold.py` so new vaults pre-create the dirs the gate framework writes into. Do NOT remove existing `_pipeline/` subdirs.
- [X] T004 [P] Bump `pyproject.toml` `[project] version = "0.2.18"` (additive feature — minor bump per SemVer-for-PATCH) and confirm `ruff` + `black` configs already cover the new module paths (no config change expected).

**Checkpoint**: `pytest tests/ -q` still green; new `tests/pipeline/` collected with 0 tests.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Schema extensions, gate framework primitive, and shared dataclasses every user story depends on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete. The `GateResult` and `SpecConfig` field additions are imported by every subsequent module.

### Tests first (TDD per Principle III)

- [X] T005 [P] Write failing schema tests in `tests/scripts/test_validate_spec.py` (extend existing file, don't replace) covering: `forbidden_filename_prefixes` accepts list of strings ending in `_` or `-`; rejects bare strings; default empty list passes validation; `priority` accepts int 0..100; rejects negative and >100; missing `priority` defaults to 0. (Target file already exists; add a new `class TestSpecExtension017` at the bottom.)
- [X] T006 [P] Write failing dataclass round-trip tests in `tests/pipeline/test_schema_roundtrip.py` (NEW): `SpecConfig.to_dict()` omits empty `forbidden_filename_prefixes` and `priority == 0` (per `contracts/spec-extension.schema.md` round-trip rules), but losslessly preserves both when present.
- [X] T007 [P] Write failing `GateResult` framework tests in `tests/pipeline/test_gates.py` (NEW): construction with each `status` value (`PASS`/`WARN`/`FAIL`/`NA`); validation that `status == "FAIL"` MUST have non-empty `correction_hint`; `gate_id` regex `^[CS]G-\d{3}$`; JSON round-trip matches `contracts/cycle-quality-report.schema.json#/$defs/gate_result`.

### Implementation

- [X] T008 Modify `src/research_vault/spec/schema.py`: add `forbidden_filename_prefixes: list[str] = field(default_factory=list)` to `SpecConfig`; add `priority: int = 0` to `CoverageCategory`. Implement `to_dict()` omission rules per contract. (Tests T005/T006 turn green here.)
- [X] T009 Modify `src/research_vault/spec/validator.py`: add `_validate_forbidden_filename_prefixes` and `_validate_priority` helpers per `contracts/spec-extension.schema.md`. Wire into the existing top-level validation flow. Backwards-compat: missing fields produce no warning.
- [X] T010 Modify `src/research_vault/spec/parser.py`: round-trip the two new fields per the contract's omission rules.
- [X] T011 Create `src/research_vault/pipeline/gates.py` (NEW) with `GateStatus` literal type, `GateResult` dataclass (per data-model.md E-004), and a `run_gate(gate_callable, *args) -> GateResult` runner that catches exceptions and converts them to `status="FAIL"` with `correction_hint="<exception class>: <message>"`. (Test T007 turns green here.)

**Checkpoint**: `pytest tests/scripts/test_validate_spec.py tests/pipeline/test_schema_roundtrip.py tests/pipeline/test_gates.py -v` all green. No other code yet imports the new fields, so existing tests still pass unchanged.

---

## Phase 3: User Story 1 — Persistent research plan drives all agents (Priority: P0) 🎯 MVP-PART-1

**Goal**: A `_pipeline/research-plan.md` is generated before each cycle by deterministic Python (priority queue, focus list, exclusions) with an optional ≤200-word agent narrator on top. Both scout and note-writer prompts get it injected so agents have shared context.

**Independent Test (from spec.md)**: After 3 cycles, notes are distributed across ≥ 8 categories (not concentrated in 4–5).

### Tests for User Story 1 (TDD)

- [X] T012 [P] [US1] Write contract test `tests/pipeline/test_research_plan_contract.py` (NEW) parsing a fixture plan against `contracts/research-plan.schema.md`: 5-section ordering enforced; YAML frontmatter required fields present; `## Focus rationale` MAY be empty; consumer parser refuses files missing any of the latter four sections.
- [X] T013 [P] [US1] Write unit tests `tests/pipeline/test_research_plan.py` (NEW) for the deterministic generator: priority queue ordering = `priority * fill_gap`; harvest-orphan citation weighting `0.3 + 0.1 * citation_count` capped at 1.0 (per research.md R-009); `cycle_focus` contains the 3 lowest-fill-percentage high-priority categories; `exclusions` deduplicates across already-covered + persistent rejects + spec.out_of_scope; `cycle_quota = ceil(remaining/remaining_cycles)`; raises `ValueError` if no priority-queue topics meet the cycle quota.
- [X] T014 [P] [US1] Write narrator tests `tests/pipeline/test_plan_narrator.py` (NEW) using a mocked `claude` CLI binary (per research.md R-011): success path produces a header ≤200 words; failure/timeout path falls back to canned `"Cycle N priority: <top-3 categories from focus list>"` header; narrator MUST NOT modify any section other than `## Focus rationale` (parse before/after, assert all other sections byte-identical).
- [X] T015 [P] [US1] Write integration test `tests/pipeline/test_research_plan_integration.py` (NEW): end-to-end with a synthetic vault containing 13 categories at 0% fill — generated plan has `cycle_focus` ⊇ the top-3 priority categories; priority queue length ≥ `cycle_quota`; written file parses against the contract.
- [X] T016 [P] [US1] Write `_render.py` injection test `tests/pipeline/test_render_plan_injection.py` (NEW): given a fixture `_pipeline/research-plan.md`, the rendered scout and note-writer prompts both contain the priority queue, focus list, and exclusion list verbatim.

### Implementation for User Story 1

- [X] T017 [US1] Create `src/research_vault/pipeline/research_plan.py` (NEW) implementing `ResearchPlan`, `CategoryFillState`, `PrioritizedTopic` dataclasses (per data-model.md E-002) and the deterministic `generate_plan(vault_dir, spec, cycle_number) -> ResearchPlan` function. Inputs (per research.md R-009): `coverage-targets.json`, `_pipeline/research-backlog.md` (from existing `topic_harvest.py`), per-cycle quality reports for persistent-rejects derivation. (Tests T012/T013/T015 green.)
- [X] T018 [US1] Add CLI entry point in `research_plan.py`: `python -m research_vault.pipeline.research_plan <vault_dir> --cycle N` writes the deterministic body to `_pipeline/research-plan.md` and an archived copy at `_pipeline/cycles/cycle-NNN-research-plan.md`. Exit 0 success, 2 structural error (per Script Exit Code Model).
- [X] T019 [US1] Create `src/research_vault/pipeline/plan_narrator.py` (NEW): `prepend_narrative(vault_dir, cycle_number) -> None` reads the deterministic body, invokes the new `research-plan-narrator` skill via the existing `agents/_render.py` + `claude` CLI bridge, validates the response is ≤200 words, and prepends as `## Focus rationale`. Failure/timeout path: write canned header and log to `_pipeline/narrator-incidents.md`. (Test T014 green.)
- [X] T020 [US1] Create `.agents/skills/research-plan-narrator/SKILL.md` (NEW) per research.md R-005: input contract = the deterministic plan body excerpt + spec scope summary; output contract = ≤200 words of focus rationale; explicit refusal to modify any other section; cap enforced by token-budget instruction.
- [X] T021 [US195] Modify `src/research_vault/agents/_render.py`: inject the contents of `_pipeline/research-plan.md` (if present) into the scout and note-writer prompt templates as a `## Research Plan` block placed *before* the existing instructions. Renders gracefully when the file is absent (cycle 0 / fresh scaffold). (Test T016 green.)
- [X] T022 [US1] Modify `.agents/skills/scout/SKILL.md`: add Step 0 ("Read `_pipeline/research-plan.md`") and Step 0.5 (focus-list adherence ≥70%) per research.md R-010. Do NOT yet add the topics_found.new MUST clause — that lands in US2 to keep stories independent.
- [X] T023 [US1] Modify `.agents/skills/note-writer/SKILL.md`: add Step 0 ("Read `_pipeline/research-plan.md` for narrative header and exclusion list"). Do NOT yet add batch-input schema — that lands in US4.
- [X] T024 [US1] Wire plan generation into the orchestrator: in `src/research_vault/pipeline/orchestrator.py:run_single_cycle`, call `research_plan.generate_plan` then `plan_narrator.prepend_narrative` before the `_render_cycle_scout_prompt` call. Plan generation runs every cycle (not just resume).
- [X] T025 [US1] Add `--regenerate-plan-only` flag to the existing `research-vault` CLI (`src/research_vault/cli.py`) that runs the plan generator + narrator without entering Phase 2. Useful for the quickstart §4 manual-regenerate path.

**Checkpoint**: `pytest tests/pipeline/test_research_plan*.py tests/pipeline/test_plan_narrator.py tests/pipeline/test_render_plan_injection.py -v` all green. The orchestrator generates `_pipeline/research-plan.md` at every cycle start. Independent test from spec.md (≥8 categories after 3 cycles) is now testable end-to-end.

---

## Phase 4: User Story 2 — Scout extracts generalizable knowledge (Priority: P0) 🎯 MVP-PART-2

**Goal**: The scout populates `topics_found.new` with generalized engineering-concept titles (e.g., "Component Testing with Testcontainers"), not internal artifact names (e.g., `oms_cassandra_component_test_harness`). When categories lack code exemplars, the scout falls back to spec scope + curriculum references.

**Independent Test (from spec.md)**: After cycle 1's scout runs, fewer than 20% of `topics_found.new` entries match any prefix in the spec's `forbidden_filename_prefixes` field.

### Tests for User Story 2 (TDD)

- [X] T026 [P] [US2] Write tests `tests/pipeline/test_gates_step_sg001_002.py` (NEW): SG-001 fails when scout's `topics_found.new` is empty; passes when ≥ `cycle_quota`; warns when `0 < count < cycle_quota`. SG-002 (category diversity): fails when all topics share a single category; passes when `len(set(categories)) >= min(5, unfilled_categories)`.
- [X] T027 [P] [US2] Write tests `tests/pipeline/test_gates_step_sg003.py` (NEW) for the abstraction gate: returns `NA` when spec has empty `forbidden_filename_prefixes` (R-007 backwards-compat); returns `WARN` when 20% < ratio ≤ 60%; returns `FAIL` with non-empty `correction_hint` when ratio > 60%; reads prefixes from spec at runtime, never hardcodes.
- [X] T028 [P] [US2] Write tests `tests/scripts/test_check_abstraction.py` (NEW) for the standalone CLI wrapper: exits 0 PASS/WARN/NA, 1 FAIL, 2 structural; output JSON conforms to `contracts/cycle-quality-report.schema.json#/$defs/gate_result`.
- [X] T029 [P] [US2] Write integration test `tests/pipeline/test_scout_skill_integration.py` (NEW): given a fixture scout report with all `topics_found.new` matching forbidden prefixes, SG-003 returns FAIL with a correction directive containing the exact violating prefixes.

### Implementation for User Story 2

- [X] T030 [US2] Create `src/research_vault/pipeline/gates_step.py` (NEW) implementing `SG001_topics_new_nonempty`, `SG002_topic_category_diversity`, `SG003_topic_abstraction_check` per data-model.md E-004 and the spec's Story 9b table. Each returns `GateResult`. SG-003 reads `spec.forbidden_filename_prefixes` at runtime (never hardcodes); returns `NA` when empty. (Tests T026/T027 green.)
- [X] T031 [P] [US2] Create `scripts/check_abstraction.py` (NEW) — CLI wrapper that loads spec, reads scout report or vault note filenames, calls `pipeline.gates_step.SG003_topic_abstraction_check` (for scout output) or a sibling `CG003_filename_abstraction_check` (for vault state), and prints `GateResult` JSON. Exit codes per Script Exit Code Model. (Test T028 green.)
- [X] T032 [US2] Modify `.agents/skills/scout/SKILL.md`: replace the "extract the service it describes, every ADR file, every Kafka topic, every domain term referenced in 2+ files" instruction with the FR-003 rewrite from research.md R-010 ("for each code artifact, name the engineering concept, pattern, or technique it exemplifies"). Add the explicit MUST: "Populate `topics_found.new` with generalizable topic titles. If empty, the SG-001 gate will fail your output and the cycle will not proceed."
- [X] T033 [US2] Modify the scout prompt rendering path so `spec.forbidden_filename_prefixes` is injected into the scout's prompt as an explicit "do NOT propose topics whose canonical filename matches these prefixes" block. Implementation: in `src/research_vault/agents/_render.py`, splice the prefix list into the rendered prompt. Skip the block if the spec's list is empty.
- [X] T034 [US2] Wire SG-001/SG-002/SG-003 into `src/research_vault/pipeline/cycle_runner.py`: after the scout step completes, run all three gates against `cycle-NNN-research.json`'s scout output. On SG-001 FAIL or SG-002 FAIL, return non-zero (cycle aborts before note-writer). On SG-003 FAIL, build a correction directive (placeholder for now — full retry loop lands in US9) and re-prompt the scout once. (Integration test T029 green.)
- [ ] T035 [US2] **(USER ACTION — vault lives outside this repo.)** Update `reference_vault_v3/research.spec.md` per `contracts/spec-extension.schema.md`: add the eight known `forbidden_filename_prefixes` (`oms_`, `wms_`, `pim_`, `erp_`, `oebh_`, `oecdh_`, `oehk_`, `cms_`). The file is at `~/Documents/research-vault-0.2.17/reference_vault_v3/research.spec.md` (or wherever the user keeps the v3 vault). This is a documentation/spec edit task in the user's vault — NOT a code change in this repo. Track via the migration path in the contract. Re-run `python scripts/validate_spec.py <vault>/research.spec.md --strict` after editing to confirm zero new warnings.

**Checkpoint**: `pytest tests/pipeline/test_gates_step_*.py tests/scripts/test_check_abstraction.py tests/pipeline/test_scout_skill_integration.py -v` all green. Running scout against a real codebase produces generalized topic titles in `topics_found.new`. SG-003 catches abstraction violations and triggers a single re-prompt.

---

## Phase 5: User Story 9 — Deterministic quality gates between steps and cycles (Priority: P0) 🎯 MVP-PART-3

**Goal**: Code-enforced gates run between every scout/note-writer step (SG-004, SG-005) and after every cycle (CG-001..CG-007). On FAIL, the orchestrator does not advance — it builds a correction directive and retries (incremental, per Q3) up to 2 times before ABORT. A `cycle-NNN-quality-report.json` summarises every gate result deterministically.

**Independent Test (from spec.md, Story 9)**: Artificially create a cycle that produces 0 notes (mock the note-writer); confirm CG-001 catches it, logs the failure, and prevents the orchestrator from moving to the next cycle.

### Tests for User Story 9 (TDD)

- [X] T036 [P] [US9] Write tests `tests/pipeline/test_gates_step_sg004_005.py` (NEW): SG-004 wraps `validate_vault.py` and translates exit codes (0 → PASS; non-zero → WARN with violation summary); SG-005 (frontmatter completeness) FAILs when any note in the batch lacks `coverage_category`, `source_urls`, or `summary`.
- [X] T037 [P] [US9] Write tests `tests/pipeline/test_gates_cycle.py` (NEW) covering CG-001..CG-007 individually with hand-crafted fixture cycle reports + coverage states. Property-based test (using `hypothesis`, already a dev dep per research.md R-011) for CG-001's `ceil(remaining / remaining_cycles)` arithmetic — invariants: yield monotonically non-decreasing as cycles consume budget; never returns 0 if `remaining > 0`.
- [X] T038 [P] [US9] Write tests `tests/pipeline/test_quality_report.py` (NEW): generates a fixture cycle, computes the quality report, validates the output against `contracts/cycle-quality-report.schema.json` (use `jsonschema` test-only — but it's NOT in deps, so write a hand-rolled validator that checks required keys, status enums, and the `aborted == true ⟹ retry_count == 2` invariant from data-model.md E-005).
- [X] T039 [P] [US9] Write tests `tests/pipeline/test_correction.py` (NEW): `CorrectionDirective` construction validates `failing_gate_ids` non-empty, `required_actions` non-empty; `to_prompt_block()` produces injectable Markdown; expired directives are filtered out.
- [X] T040 [P] [US9] Write integration test `tests/pipeline/test_orchestrator_retry.py` (NEW): mock-cycle 1 produces 0 notes — orchestrator detects CG-001 FAIL, builds correction directive, retries; if retry produces ≥ minimum, cycle ACCEPTED; if retry also fails, second retry; if third also fails, ABORT with `aborted=true`, `retry_count=2`, `abort_reason` non-empty. Verify accepted batches from earlier in the failed cycle are NOT deleted (Q3 incremental retry).
- [X] T041 [P] [US9] Write tests `tests/scripts/test_quality_report.py` (NEW) for the standalone CLI: `--cycle N` prints a human-formatted summary; `--all` aggregates across cycles; exit 0 always (read-only inspection tool).

### Implementation for User Story 9

- [X] T042 [US9] Add the remaining SG gates to `src/research_vault/pipeline/gates_step.py`: `SG004_validate_vault_wrapper` (subprocess call to `scripts/validate_vault.py`, exit-code translation), `SG005_frontmatter_completeness`. (Tests T036 green.)
- [X] T043 [US9] Create `src/research_vault/pipeline/gates_cycle.py` (NEW) implementing CG-001..CG-007 per spec.md Story 9a table. CG-001 uses the `coverage.py:remaining_yield(cycle_number, max_cycles)` helper (T044). CG-003 reads `spec.forbidden_filename_prefixes`, returns `NA` when empty (consistent with SG-003). CG-005 (cumulative coverage trajectory) projects current rate forward. (Test T037 green.)
- [X] T044 [US9] Modify `src/research_vault/pipeline/coverage.py`: add a public `remaining_yield(vault_dir, cycle_number, max_cycles) -> int` helper that returns `ceil(unmet_targets / max(1, max_cycles - (cycle_number - 1)))`. Pure function; covered by the property test in T037.
- [X] T045 [US9] Create `src/research_vault/pipeline/correction.py` (NEW) implementing `CorrectionDirective` (data-model.md E-006), `build_directive(failing_gates: list[GateResult], cycle: int, batch: int | None) -> CorrectionDirective`, `to_prompt_block()`, and a garbage-collect-expired pass. Persists directives to `_pipeline/corrections/cycle-NNN-batch-MMM.json` (or `_pipeline/corrections/cycle-NNN.json` for cycle-wide). (Test T039 green.)
- [X] T046 [US9] Create `src/research_vault/pipeline/quality_report.py` (NEW) implementing `CycleQualityReport` (data-model.md E-005) and `write_report(vault_dir, cycle_number) -> Path`. Aggregates: all SG GateResults from per-batch reports, all CG GateResults computed inline, `coverage_snapshot` (delta vs cycle-start), `notes_written`/`accepted`/`rejected` counts, `degraded_sources` from the source incidents log, `retry_count`/`aborted`/`abort_reason`. `queryability_score` and `queryability_trajectory` are filled by US7 (queryability) — for now stub to `0` and `"stable"` so the schema validates. (Test T038 green; T041 green for the CLI part once T047 lands.)
- [X] T047 [P] [US9] Create `scripts/quality_report.py` (NEW) — CLI to print/inspect cycle quality reports per quickstart.md §3. Modes: `--cycle N` (one report), `--all` (aggregate). Read-only; exit 0 always. (Test T041 green.)
- [X] T048 [US9] Modify `src/research_vault/pipeline/orchestrator.py:run_single_cycle` to wire the gate suite: after `cycle_runner.run_cycle_steps` returns, run all CG gates → if any FAIL and `retry_count < 2`, build correction directive, increment retry counter, re-render prompts, re-run cycle (incremental — per Q3, `coverage.py:update_after_cycle` is NOT rolled back for accepted batches). On `retry_count == 2` AND any CG FAIL, mark `aborted=true`, write the quality report with `abort_reason`, return non-zero. (Test T040 green.)
- [X] T049 [US9] Modify `src/research_vault/pipeline/cycle_runner.py` to call `quality_report.write_report` at every cycle end (success, retry, or abort) so the JSON artifact always exists for inspection.
- [X] T050 [US9] Modify `src/research_vault/pipeline/reporter.py` to embed the cycle quality report path into the existing per-cycle report so `vault_audit.py` and downstream tooling can find it.

**Checkpoint**: `pytest tests/pipeline/test_gates_*.py tests/pipeline/test_quality_report.py tests/pipeline/test_correction.py tests/pipeline/test_orchestrator_retry.py tests/scripts/test_quality_report.py -v` all green. Mocking a 0-note cycle produces a quality report with `CG-001: FAIL`, the orchestrator retries up to 2x, and ABORTs cleanly with diagnostic.

🛑 **MVP STOP-AND-VALIDATE POINT**

US1 + US2 + US9 together = the MVP. At this checkpoint:

- A real cycle against `reference_vault_v3` should produce `_pipeline/research-plan.md`, generalized topic titles, and `cycle-NNN-quality-report.json` with all 12 gates evaluated.
- Spec.md success criteria SC-008 (research-plan exists), SC-009 (forbidden-prefix gate works), SC-010 (quality report per cycle), SC-013 (SG-001 catches empty topics) are now testable end-to-end.
- Without these three together, the feature has no value: the plan needs the abstraction enforcement to be useful, and the abstraction enforcement needs the gate framework to bite. Stop here, run the spec.md User Story 1/2/9 independent tests, only then continue.

---

## Phase 6: User Story 4 — Notes-per-cycle throughput reaches 25+ (Priority: P1)

**Goal**: The orchestrator drives ≥25 notes per cycle by issuing **multiple sequential note-writer invocations** (Q2 hybrid: orchestrator-enforced quota, batches of 5–8 topics each, mid-cycle gates between batches). The agent does not self-limit; the orchestrator continues invoking until quota met or topic list exhausted.

**Independent Test (from spec.md)**: Run 3 cycles and confirm ≥ 75 total notes created.

### Tests for User Story 4 (TDD)

- [X] T051 [P] [US4] Write tests `tests/pipeline/test_batch.py` (NEW) for the batch scheduler: `BatchAssignment` clamping (3..10) per research.md R-004; quota arithmetic (`ceil(quota / batch_size)` batches); priority-order topic slicing (highest-score topics in earliest batches); `BatchResult.accepted` deterministically computed from `sg_gate_results`. Also covers the **mid-cycle pace check** (spec Story 9c, FR-006): mock a 5-batch cycle where batch 3 has 30% completion → assert `check_pace_at_midpoint` returns a pace-correction directive; mock a 5-batch cycle with 60% completion at midpoint → assert no directive; assert the midpoint is computed as the batch boundary closest to 50% of `topics_assigned_so_far`, not 50% of the original quota.
- [X] T052 [P] [US4] Write contract test `tests/pipeline/test_batch_report_contract.py` (NEW) validating sample batch reports against `contracts/batch-report.schema.json`: `topics` length ∈ [3, 10]; `notes_written` filenames match the `^[a-z0-9_-]+\.md$` pattern; `accepted: true` ⟺ no SG gate FAIL.
- [X] T053 [P] [US4] Write integration test `tests/pipeline/test_batch_orchestration.py` (NEW): mock note-writer that produces 4 notes per invocation regardless of topics; assert orchestrator issues 5 invocations to hit a quota of 20; mid-cycle SG-005 fails on batch 3 → orchestrator builds correction directive → batch 4 receives the directive in its prompt; accepted batches 1+2 are NOT discarded when batch 3 FAILs (Q3 incremental commit boundary).
- [X] T054 [P] [US4] Write resume test `tests/pipeline/test_batch_resume.py` (NEW) for R-001 idempotent replay: orchestrator dies between batch 2's notes hitting disk and `cycle-NNN-batch-002.json` being written; on resume, the orphan notes are detected via frontmatter `created_at_cycle`, accepted through SG-005, and the missing batch report is written. No duplicates, no lost work. End-to-end resume coverage (FR-014): kill orchestrator at three distinct points (mid-batch, between batches, after CG gate FAIL on retry 1) → resume in each case → assert (a) no duplicate notes in `data_vault/`, (b) `retry_count` is preserved (NOT bumped on resume), (c) accepted batches stay accepted, (d) `cycle-NNN-quality-report.json` reflects pre-crash gate results when the report was already written.

### Implementation for User Story 4

- [X] T055 [US4] Create `src/research_vault/pipeline/batch.py` (NEW) implementing `BatchAssignment`, `BatchResult` (data-model.md E-003), `slice_topics_into_batches(plan: ResearchPlan, batch_size: int) -> list[BatchAssignment]` with [3, 10] clamping and WARN logging. Reads `pipeline.note_writer_batch_size` from `settings.yaml` (default 6).
- [X] T056 [US4] Modify `src/research_vault/pipeline/cycle_runner.py`'s DFS step: replace the single note-writer invocation with the batch loop. For each `BatchAssignment`: render note-writer prompt with `batch_topics` + `correction_directive`; invoke note-writer; capture written filenames; run SG-004 + SG-005; write `cycle-NNN-batch-MMM.json`; if FAIL → build correction directive for next batch (do NOT delete accepted batches); continue until quota met or topics exhausted.
- [X] T057 [US4] Modify `.agents/skills/note-writer/SKILL.md`: add the `batch_topics` input contract (list of 5–8 `PrioritizedTopic` shapes); add the explicit "MUST attempt every assigned topic before stopping; report skipped topics with a reason in the batch report's `skipped_topics` field" instruction per research.md R-010. Replace the generic "scan the report for topics" step with "the orchestrator hands you exactly the topics for this batch."
- [X] T058 [US4] Add resume-safe orphan-note detection to `src/research_vault/pipeline/orchestrator.py` per research.md R-001: at cycle start, walk `data_vault/` for notes whose frontmatter `lifecycle.created_at_cycle == current_cycle` AND filename not in any existing batch report's `notes_written` → treat as un-acknowledged batch from a prior crash, run SG-005 on them, and either accept (write a synthetic batch report) or quarantine. (Test T054 green.)
- [X] T058b [US4] Implement `pipeline.batch.check_pace_at_midpoint(plan, completed_batches, current_batch) -> CorrectionDirective | None` per spec Story 9c "Mid-Cycle Progress Tracking" (FR-006). At the batch boundary closest to 50% of the cycle's assigned topic list, compute `completion_ratio = notes_written_so_far / topics_assigned_so_far`; if `completion_ratio < 0.40`, build a pace-correction directive with diagnosis "you're behind pace at midpoint (X% complete vs ≥40% expected) — prioritize breadth over depth for remaining topics" and return it for the orchestrator to inject into the next batch's prompt. Wire into `pipeline/cycle_runner.py`'s batch loop (extends T056) so the check runs exactly once per cycle, at the midpoint batch boundary. The directive is informational (not a gate FAIL); it does NOT trigger the retry path. Also tracks per-cycle skipped topics whose `reason == "agent_chose_alternative"` (the enum value in `contracts/batch-report.schema.json` that maps to spec Story 9c's "skipped: decided to write a different topic instead") — any occurrence of that reason in `skipped_topics` is upgraded to a per-batch SG gate violation per spec Story 9c. (Test extension in T051 covers it.)
- [X] T059 [P] [US4] Add a settings-driven cap on the total batches per cycle (`pipeline.max_batches_per_cycle` default 10) so a runaway loop can't consume the entire budget on one cycle. WARN-and-stop when the cap trips; do NOT FAIL the cycle on cap-trip alone (the cap is a safety net, not a quality gate).

**Checkpoint**: `pytest tests/pipeline/test_batch*.py -v` all green. A cycle assigned 30 topics and quota 25 produces 5 batches × 6 topics, runs SG gates between each, builds corrections on failures, and never re-writes accepted notes. `cycle-NNN-batch-MMM.json` files conform to the contract.

---

## Phase 7: User Story 3 — Regenerate a usable reference vault from the existing spec (Priority: P1)

**Goal**: Running `research-vault generate reference_vault_v3` end-to-end produces a vault that passes the existing 7-gate quality audit (SC-001..SC-007). This is the integration test for everything from Phases 3–6 working together against a real spec.

**Independent Test (from spec.md)**: Run the vault quality audit protocol (all 7 gates) against the regenerated vault.

### Tests for User Story 3 (TDD)

- [X] T060 [P] [US3] Write end-to-end pipeline test `tests/pipeline/test_e2e_synthetic_vault.py` (NEW) using a small synthetic spec (3 categories, 30 targets, 3-cycle budget, 1 declared `out_of_scope` entry) — exercises the full orchestrator path with mocked agent calls returning canned responses. Asserts: (a) research plan generated each cycle; (b) ≥75% of notes belong to high-priority categories; (c) quality report exists for each cycle; (d) SC-009 abstraction ratio < 20%; (e) SC-008 plan accuracy (post-cycle plan reflects actual cycle outcome); (f) **SC-006 zero out-of-scope**: no generated note's `coverage_category`, filename, or topic title matches any `spec.scope.out_of_scope` entry; (g) **SC-005 priority adherence**: the top-2 priority categories each reach ≥ 50% of their `target_count` after 3 cycles (3 categories total in the synthetic spec → "top 2" stands in for the spec's "top 5" criterion at this scale).
- [X] T061 [P] [US3] Write quickstart-validation test `tests/pipeline/test_quickstart_smoke.py` (NEW) that runs the smoke commands from quickstart.md §8 against a fresh tmp_path vault. Read-only assertions on the produced JSON shapes — does not require a real LLM.

### Implementation for User Story 3

- [X] T062 [US3] Modify `src/research_vault/cli.py` `generate` command: ensure the new pipeline (plan → scout → SG gates → batched note-writer → SG gates per batch → CG gates → quality report → next cycle) is the default execution path. Old single-invocation note-writer path remains accessible only via `--legacy-cycle-runner` flag for safety; flag prints a DEPRECATION warning.
- [X] T063 [US3] Update `scripts/vault_audit.py` to surface the new artifacts in its summary: count of cycle quality reports, abstraction-gate status (or N/A), queryability-score history, abort/retry counts. Don't change exit-code semantics — this is read-only enrichment of the existing audit output.
- [X] T064 [US3] Update `scripts/validate_vault.py` to additionally check: every note has `lifecycle.created_at_cycle` integer ≥ 1 (used by R-001 orphan-note detection). Backwards compat: notes without the field WARN (don't FAIL) so existing vaults from old framework versions still pass.
- [X] T065 [US3] Add a regeneration runbook section to `docs/` cross-linking quickstart.md §5. Include the exact commands, expected SC-001..SC-007 thresholds, and the "what to do if X gate fails" troubleshooting from quickstart.md §7.

**Checkpoint**: Synthetic-vault end-to-end test passes deterministically (no real LLM). The runbook gives the user a clear regeneration path. Real `reference_vault_v3` regeneration is a USER action (not automatable in CI), guided by the runbook.

---

## Phase 8: User Story 5 — Source preflight prevents wasted runs (Priority: P2)

**Goal**: Before any cycle starts, validate that all required data sources are reachable. Fail fast (exit 1) on missing required sources; warn-only on enrichment failures. Same `pipeline/preflight.py` module is consumed by both the standalone CLI and `pipeline/preconditions.py` as the 6th precondition (R-008).

**Independent Test (from spec.md)**: Run the preflight check with a deliberately broken source (e.g., non-existent repo path) and confirm it fails with a clear error before any generation starts.

### Tests for User Story 5 (TDD)

- [X] T066 [P] [US5] Write tests `tests/pipeline/test_preflight.py` (NEW): each source type (`local_repo`, `github_pr`, `web`, `rss`, `oreilly`) has a checker; missing local repo → `unreachable`; reachable URL → `ok`; degraded GitHub auth → `degraded`; role-based aggregation per `contracts/preflight.schema.json` (`fail` if any required `unreachable`; `warn` if only enrichment failures; `pass` otherwise).
- [X] T067 [P] [US5] Write tests `tests/scripts/test_preflight_sources.py` (NEW) for the CLI: exit codes 0/1/2 per `contracts/preflight.schema.json`'s `overall_status` mapping; `--json` flag prints schema-valid JSON; `--vault PATH` writes to `_pipeline/preflight.json`.
- [X] T068 [P] [US5] Write integration test `tests/pipeline/test_preconditions_with_preflight.py` (NEW): preflight registered as the 6th precondition; existing 5 unchanged; preflight FAIL prevents Phase 2 entry.
- [X] T069 [P] [US5] Write tests for the mid-run source-failure threshold path in `tests/pipeline/test_source_failure_threshold.py` (NEW): per research.md R-003, 1 required source going degraded mid-cycle = WARN; 2 required = ABORT cycle; enrichment failures unlimited; thresholds configurable via `settings.yaml`.

### Implementation for User Story 5

- [X] T070 [US5] Create `src/research_vault/pipeline/preflight.py` (NEW) implementing `SourceCheck`, `PreflightResult` (data-model.md E-008) and per-type checkers. `check_all(spec, vault_dir) -> PreflightResult`. Reuses existing `_pipeline/sources.db` for history; writes `_pipeline/preflight.json` per the contract.
- [X] T071 [P] [US5] Create `scripts/preflight_sources.py` (NEW) — thin CLI wrapper (no duplicate logic) that calls `pipeline.preflight.check_all` and emits the result to stdout (human-readable) and `_pipeline/preflight.json` (machine-readable). Exit codes per Script Exit Code Model.
- [X] T072 [US5] Modify `src/research_vault/pipeline/preconditions.py:check`: add precondition #6 (source preflight). Reuses `pipeline.preflight.check_all`. Existing 5 preconditions unchanged in semantics or order.
- [X] T073 [US5] Modify `src/research_vault/pipeline/source_manager.py` to expose mid-run source-degradation events. The existing `consecutive_empty_cycles` counter stays; add a `mark_degraded(name: str, reason: str)` helper that writes to `_pipeline/source-incidents.md` (append-only). Used by the cycle_runner per research.md R-003.
- [X] T074 [US5] Modify `src/research_vault/pipeline/cycle_runner.py` to apply the role-based mid-run thresholds: 2+ required-source degradations in one cycle → ABORT cycle (exit 2); enrichment-only degradations → log + continue.

**Checkpoint**: `pytest tests/pipeline/test_preflight.py tests/scripts/test_preflight_sources.py tests/pipeline/test_preconditions_with_preflight.py tests/pipeline/test_source_failure_threshold.py -v` all green. Standalone CLI catches a missing repo path and exits 1 in < 30 seconds (per User Story 5 perf target). Phase 2 won't start with required sources unreachable.

---

## Phase 9: User Story 6 — Post-generation reindex populates index files (Priority: P2)

**Goal**: After every cycle, `_index.md`, `_concepts.md`, and `_graph.md` are populated from current vault content. Empty index files no longer slip through to Phase 3.

**Independent Test (from spec.md)**: Generate a vault with 10+ notes and confirm all three index files contain entries referencing those notes.

### Tests for User Story 6 (TDD)

- [X] T075 [P] [US6] Write tests `tests/pipeline/test_indexer.py` (NEW or extend existing if present): given a fixture `data_vault/` with notes across multiple categories, `indexer.rebuild_all(vault_dir)` produces non-empty `_index.md` (grouped by folder, title + summary), `_concepts.md` (lookup definitions), and `_graph.md` (cross-link map). Re-running is idempotent (same input → byte-identical output, via deterministic ordering).
- [X] T076 [P] [US6] Write integration test `tests/pipeline/test_reindex_at_cycle_end.py` (NEW): orchestrator calls `indexer.rebuild_all` after every cycle; on a synthetic 10-note vault, all three index files exist and reference all 10 notes after cycle end.

### Implementation for User Story 6

- [X] T077 [US6] Modify `src/research_vault/vault/indexer.py`: implement (or extend) `rebuild_all(vault_dir: Path) -> dict[str, Path]` that writes `_index.md`, `_concepts.md`, `_graph.md` into `data_vault/` (NOT vault root — see US7). Deterministic ordering: notes alphabetical within folder; folders alphabetical. Each entry has title + ≤120-char summary from frontmatter.
- [X] T078 [US6] Modify `src/research_vault/pipeline/orchestrator.py:run_single_cycle` to call `indexer.rebuild_all(vault_dir / "data_vault")` after the quality report write but before returning. On rebuild failure, log a WARN but do NOT FAIL the cycle (indexes are derived state — can be regenerated manually).

**Checkpoint**: `pytest tests/pipeline/test_indexer.py tests/pipeline/test_reindex_at_cycle_end.py -v` green. Cycles produce populated index files; a vault with 10+ notes has every note listed in `_index.md`.

---

## Phase 10: User Story 7 — Index files live inside data_vault (Priority: P3)

**Goal**: `_index.md`, `_concepts.md`, and `_graph.md` are written inside `data_vault/`, not at the vault root. The corpus directory is self-contained as a single Obsidian vault.

**Independent Test (from spec.md)**: After generation, confirm index files are inside `data_vault/` and not at the vault root.

### Tests for User Story 7 (TDD)

- [X] T079 [P] [US7] Write tests `tests/pipeline/test_indexer_path.py` (NEW): `indexer.rebuild_all(vault_dir)` writes to `vault_dir / "data_vault"`, never to `vault_dir` directly. Existing index files at vault root are migrated (moved into `data_vault/`) on first rebuild and the root copies removed.
- [X] T080 [P] [US7] Write tests `tests/pipeline/test_scaffold_index_paths.py` (NEW): `generator.scaffold` creates `data_vault/_index.md`, `data_vault/_concepts.md`, `data_vault/_graph.md` placeholders — never `<vault_root>/_index.md`.

### Implementation for User Story 7

- [X] T081 [US7] Update `src/research_vault/generator/scaffold.py` to emit the three index placeholders inside `data_vault/`. Remove any code path that writes them at the vault root.
- [X] T082 [US7] Add a one-shot migration helper `pipeline/indexer.py:migrate_root_indexes(vault_dir) -> bool` that detects `<vault_root>/_index.md` etc. and moves them into `data_vault/` (with content preservation). Called on first cycle of an existing vault. Idempotent.

**Checkpoint**: `pytest tests/pipeline/test_indexer_path.py tests/pipeline/test_scaffold_index_paths.py -v` green. Fresh vaults scaffold indexes inside `data_vault/`. Old vaults with root-level indexes get migrated cleanly on next cycle.

---

## Phase 11: User Story 8 — Template directory is generated for compliance checking (Priority: P3)

**Goal**: The vault scaffold writes `data_vault/_templates/` containing one template per note type defined in the spec, so `check_template_compliance.py` works.

**Independent Test (from spec.md)**: Run `check_template_compliance.py data_vault/` and confirm it does not error with "template directory not found".

### Tests for User Story 8 (TDD)

- [X] T083 [P] [US8] Write tests `tests/pipeline/test_scaffold_templates.py` (NEW): scaffolding a vault with N note types produces exactly N files in `data_vault/_templates/`, each named `{note_type}.md`, each containing the type's `required_sections` as Markdown headings. Re-scaffolding is idempotent.
- [X] T084 [P] [US8] Write tests `tests/scripts/test_check_template_compliance_with_dir.py` (NEW or extend existing): `check_template_compliance.py` resolves templates from `data_vault/_templates/` first; falls back to repo-bundled defaults only if the per-vault dir is missing; emits a clear error (not a Python traceback) when both are missing.

### Implementation for User Story 8

- [X] T085 [US8] Modify `src/research_vault/generator/scaffold.py` to create `data_vault/_templates/` and emit a per-note-type template file. Template content derived from `NoteTypeConfig.required_sections` and `contextual_questions`.
- [X] T086 [US8] Modify `scripts/check_template_compliance.py` to prefer `data_vault/_templates/` over repo-bundled templates when present; clear error when both absent.

**Checkpoint**: `pytest tests/pipeline/test_scaffold_templates.py tests/scripts/test_check_template_compliance_with_dir.py -v` green. New vaults have a `_templates/` dir; compliance checking works without manual file copying.

---

## Phase 12: Queryability Probes (NEW — supports SC-007, SC-011, FR-020)

**Goal**: The deterministic queryability score that fills in `CycleQualityReport.queryability_score` and `queryability_trajectory` (which were stubbed in T046). Per research.md R-006: agent retrieves candidate notes, Python scores them via a 3-rule rubric.

This phase is technically cross-cutting — every priority bucket benefits from it — but it's grouped here because no single user story claims it. SC-007 and SC-011 from spec.md are the success criteria.

### Tests (TDD)

- [X] T087 [P] Write tests `tests/pipeline/test_probes.py` (NEW): probe generation is deterministic (same spec → same probes by stable hash); rubric scoring per research.md R-006 (3 binary checks); per-cycle score = `answered / total * 100`; trajectory bucketing per research.md R-002 (improving / stable / regressing with 5pp tolerance).
- [X] T088 [P] Write tests `tests/scripts/test_probe_runner.py` (NEW): CLI exit 0 always (read-only); writes `_pipeline/cycles/cycle-NNN-probe-results.json` conforming to `contracts/probe-result.schema.json`; mocked agent retrieval step returns canned candidate lists.

### Implementation

- [X] T089 Create `src/research_vault/pipeline/probes.py` (NEW) implementing `QueryabilityProbe`, `CandidateNote`, `ProbeResult` (data-model.md E-007). Functions: `generate_probes(spec) -> list[QueryabilityProbe]` (deterministic); `score_candidates(probe, candidates, vault_dir) -> ProbeResult` (Python 3-rule rubric — agent never scores); `run_cycle_probes(vault_dir, spec, cycle_number) -> tuple[int, str]` returning `(score, trajectory)`.
- [X] T090 [P] Create `scripts/probe_runner.py` (NEW) — CLI wrapping `pipeline.probes.run_cycle_probes`. Reads agent-retrieval evidence from a side-channel JSON file (orchestrator stages this between the agent step and the scorer); writes `_pipeline/cycles/cycle-NNN-probe-results.json`.
- [X] T091 Modify `src/research_vault/pipeline/quality_report.py` (created in T046) to call `probes.run_cycle_probes` and replace the stubbed `queryability_score`/`queryability_trajectory` values with the real ones.
- [X] T092 Modify the cycle_runner to invoke the probe-retrieval agent step once per cycle (after notes are written, before quality report assembly). Use the existing `claude` CLI bridge per research.md R-006. Cache probe results by `(probe_id, vault_content_hash)` so unchanged vaults don't re-invoke the agent (perf optimization, not correctness).

**Checkpoint**: `pytest tests/pipeline/test_probes.py tests/scripts/test_probe_runner.py -v` green. Cycle quality reports now have real queryability scores; trajectory transitions on synthetic regressions match research.md R-002 (5pp tolerance).

---

## Phase 13: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, performance, audit, repo hygiene.

- [X] T093 [P] Documentation pass: update `README.md` with a brief mention of feature 017 (research plan, gates, batches, preflight, reindex). Cross-link to `specs/017-vault-quality-fix/quickstart.md`. Do NOT duplicate quickstart content.
- [X] T094 [P] Update `docs/ROADMAP.md` (if present) marking the items 017 covers as DONE; do not touch the deferred `research_framework` rename roadmap item (constitution v1.3.1 keeps it separate).
- [X] T095 [P] Performance check: time the full gate suite on `reference_vault_v3` (or the synthetic vault if real one isn't available); confirm CG suite < 5s, plan generator < 2s, preflight < 30s, reindex < 5s per plan.md Performance Goals. If any exceeds, file a follow-up issue rather than blocking.
- [X] T096 [P] Run `ruff check src/research_vault scripts tests` and `black --check src/research_vault scripts tests` on the entire feature delta; fix any new violations introduced by 017.
- [X] T097 [P] Run the existing full test suite (`pytest tests/ -v`) — confirm zero regressions in `tests/scripts/` (existing 405-tests-and-counting baseline per `CLAUDE.md`).
- [X] T098 Run `python scripts/vault_audit.py` against a freshly regenerated synthetic vault; confirm the new sections (cycle quality reports, abstraction status, queryability history) render correctly.
- [X] T099 [P] Add a `CHANGELOG.md` entry (or extend if existing) for `0.2.18` summarizing 017's user-facing changes: research plan file, quality reports, preflight, batched note-writer, populated indexes inside `data_vault/`, optional `forbidden_filename_prefixes` spec field.
- [X] T100 Run quickstart.md §1 (verify) end-to-end on a clean checkout to confirm the document is accurate; fix any drift.
- [X] T101 [P] Verify FR-015 fix is committed: confirm `scripts/collect_oreilly.py` (or whatever the current name is — search `scripts/` for `oreilly`) uses the MCP tool name `search_oreilly_content` (underscore form) and exits non-zero when the MCP tool is missing. If either condition is false, fix the script. Add regression test `tests/scripts/test_collect_oreilly_tool_name.py` asserting (a) the literal string `"search_oreilly_content"` appears in the script, (b) running the script with a mocked MCP environment that lacks the tool exits with a non-zero code and a clear error message (not a Python traceback). Closes FR-015's spec assumption "(the fix) is already committed or will be committed as part of this spec's implementation" by making it verifiable.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately. Tasks T001..T004 are independent (all `[P]`-eligible; only T001 has no `[P]` because directory creation is a single action).
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS every user story. T005..T011 must all complete before any US task runs.
- **MVP (Phases 3 + 4 + 5)**: All three are P0 and depend only on Phase 2. Within Phases 3 + 4 + 5, internal task ordering is per-phase (tests → impl). The three phases CAN proceed in parallel by different developers because they touch different modules — but **integration meaningfully begins** only when all three reach their checkpoint, hence the MVP STOP-AND-VALIDATE at the end of Phase 5.
- **Phase 6 (US4 batching)**: Depends on Phase 5 (uses `gates_step.py` from US9 to run between batches). Cannot start before US9's checkpoint.
- **Phase 7 (US3 regenerate)**: Depends on Phases 3 + 4 + 5 + 6 — it's the integration test of everything above it.
- **Phase 8 (US5 preflight)**: Depends only on Phase 2. Can run in parallel with Phases 3–7.
- **Phase 9 (US6 reindex)**: Depends only on Phase 2. Can run in parallel with Phases 3–8.
- **Phase 10 (US7 index location)**: Depends on Phase 9 (changes the `indexer` module that US6 implements). Sequential after US6.
- **Phase 11 (US8 template dir)**: Depends only on Phase 2 (touches `scaffold.py`). Can run in parallel with anything else.
- **Phase 12 (Probes)**: Depends on Phase 5 (extends `quality_report.py` from US9). Sequential after US9.
- **Phase 13 (Polish)**: Depends on every preceding phase. Final.

### Within Each User Story

- Tests MUST be written and FAIL before implementation (Constitution III).
- Schema/contract tests before unit tests before integration tests.
- Pipeline modules before CLI wrappers (CLI is a thin wrapper per existing convention).
- Skill edits (`.agents/skills/*/SKILL.md`) AFTER the gate that enforces the skill's new behavior — otherwise the skill ships without enforcement.

### User Story Dependencies (real)

- US1 (research plan) is independent.
- US2 (scout abstraction) reads `forbidden_filename_prefixes` from spec — schema lands in Phase 2 (T008), so US2 unblocked at Phase 2 checkpoint.
- US9 (gates) is independent of US1/US2 logically but depends on T011 (`gates.py` framework). Within US9, CG-003 reuses the SG-003 abstraction logic from US2 — but they're different functions on different inputs, so cross-story coupling is loose; if US9 lands first, CG-003 is stubbed `NA` until US2 ships SG-003.
- US3 (regenerate) integrates US1+US2+US4+US9. Cannot meaningfully ship before all four.
- US4 (batching) needs US9's `gates_step.py` to run between batches.
- US5 (preflight) is fully independent.
- US6 (reindex) is independent.
- US7 (index location) needs US6's indexer.
- US8 (template dir) is independent.

### Parallel Opportunities

- **All Phase 1 setup tasks**: T002, T003, T004 in parallel (T001 is the only sequential one — directory creation).
- **All Phase 2 tests** (T005, T006, T007) in parallel — different files. Implementation T008..T011 then sequential because they share `schema.py` (T008 + T010 touch it; T009 touches a sibling file).
- **All US1 tests** (T012, T013, T014, T015, T016) in parallel — different files.
- **All US2 tests** (T026, T027, T028, T029) in parallel.
- **All US9 tests** (T036, T037, T038, T039, T040, T041) in parallel.
- **Phase 8 (US5), Phase 9 (US6), Phase 11 (US8)**: all three can run completely in parallel by different developers — they touch disjoint files.
- **Polish phase tasks marked [P]** (T093, T094, T095, T096, T097, T099) all in parallel.

---

## Parallel Example: Phase 2 (Foundational)

```bash
# Launch all foundational tests together (different files):
Task: "Schema validation tests in tests/scripts/test_validate_spec.py"
Task: "Dataclass round-trip tests in tests/pipeline/test_schema_roundtrip.py"
Task: "GateResult framework tests in tests/pipeline/test_gates.py"

# After tests fail, sequential implementation:
Task T008: Modify src/research_vault/spec/schema.py
Task T009: Modify src/research_vault/spec/validator.py   # different file from T008 — could parallel
Task T010: Modify src/research_vault/spec/parser.py      # different file again — could parallel
Task T011: Create src/research_vault/pipeline/gates.py   # fully independent
```

T008/T009/T010 are sequential as listed because they share the same logical schema (changes to one drive expectations in the others); doing them in one developer's hands keeps the change atomic. T011 is fully independent and can run in parallel with T008..T010 by a different developer.

## Parallel Example: MVP-time team split (3 developers)

```bash
# Once Phase 2 checkpoint is met, three developers split the MVP:
Developer A: Phase 3 (US1 — research plan)         tasks T012..T025
Developer B: Phase 4 (US2 — scout abstraction)     tasks T026..T035
Developer C: Phase 5 (US9 — gates framework)       tasks T036..T050

# These three phases touch disjoint modules:
#   A: pipeline/research_plan.py, pipeline/plan_narrator.py, agents/_render.py
#   B: pipeline/gates_step.py (SG-001..SG-003), .agents/skills/scout/SKILL.md
#   C: pipeline/gates_cycle.py, pipeline/correction.py, pipeline/quality_report.py,
#      pipeline/coverage.py, pipeline/orchestrator.py
# Only orchestrator.py (touched by A's T024 and C's T048) needs coordination —
# resolve by C landing first, then A rebases. Or both pair on orchestrator.
```

---

## Implementation Strategy

### MVP First (US1 + US2 + US9 — the three P0 stories)

1. Complete Phase 1: Setup (≤ half a day).
2. Complete Phase 2: Foundational (1 day).
3. Complete Phases 3 + 4 + 5 (US1 + US2 + US9) in parallel if 3 devs available, else sequential P0 order: US1 → US9 → US2 (US9 before US2 lets US2 immediately wire its SG-003 into the gate framework instead of stubbing).
4. **MVP STOP-AND-VALIDATE**: Run quickstart.md §5 (regenerate `reference_vault_v3`) — even though US3/US4 aren't complete, the MVP should produce a research plan, fire abstraction gates, and write quality reports. The note throughput will still be ~10/cycle (US4 not done yet) and reindex won't run (US6 not done) — that's expected; the MVP is the gate-and-plan tripod.
5. Demo if ready.

### Incremental Delivery After MVP

1. **+ US4 (Phase 6)**: throughput jumps from ~10 to ≥25 notes/cycle. Demo `reference_vault_v3` reaching ≥75 notes after 3 cycles.
2. **+ US3 (Phase 7)**: end-to-end regeneration is now the default `research-vault generate` path. Demo full SC-001..SC-007 audit.
3. **+ US5 (Phase 8)**: preflight catches misconfigured vaults in 30s. Demo broken-source path.
4. **+ US6 + US7 (Phases 9–10)**: index files populated and inside `data_vault/`. Demo Obsidian-opening the corpus directly.
5. **+ US8 (Phase 11)**: template-compliance gate works end-to-end.
6. **+ Probes (Phase 12)**: queryability score is real (was stubbed in MVP).
7. **+ Polish (Phase 13)**: docs, perf, lint, full audit.

### Parallel Team Strategy

Three-dev team can land the MVP in ~3 working days after Phase 2:

- Day 1: Phases 1 + 2 together (whole team).
- Days 2–3: A/B/C split per the MVP-time example above.
- Day 4: Integration day — orchestrator wiring + MVP STOP-AND-VALIDATE.
- Day 5+: Phases 6–13 distributed by independence (US4 → C; US5 + US6 + US8 in parallel by A/B; US7 sequential after US6; US3 + Probes integration after; Polish last).

---

## Notes

- `[P]` tasks = different files, no dependencies on incomplete tasks.
- `[Story]` label maps task to specific user story for traceability — **omitted on Setup, Foundational, Probes (cross-cutting), and Polish phases** per the SKILL's task-ID rules.
- Every user story is independently completable after Phase 2; the MVP boundary is U1+U2+U9 only because they together form the *minimum* viable improvement (alone, neither one fixes the trial-run failure).
- Verify tests fail before implementing (Constitution Principle III non-negotiable).
- Commit after each task or logical group (the `before_implement` hook in `.specify/extensions.yml` will prompt you).
- Stop at any checkpoint to validate independently — the spec.md "Independent Test" lines for each story are runnable as written.
- The `reference_vault_v3` spec edit (T035) is the only task in this list that lives **outside** the `research-framework` repo — it edits the user's vault, not the framework code.
- Polish phase performance budget validation (T095) is best-effort: if numbers exceed targets, file a follow-up rather than blocking — perf optimization is its own work.
