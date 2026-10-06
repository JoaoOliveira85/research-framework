# Tasks: 057 Foreman Retro Coverage — Tolerant Matching Mode

**Input**: `spec.md` (clarified 2026-06-03), `plan.md`, `research.md` (D1–D6), `contracts/tolerant-requirements.contract.md`, `contracts/verdict-report.contract.md`, `quickstart.md`.
**Tests**: TDD per Principle III — tolerant + strict-regression tests RED before verifier changes. **[P]** = parallelizable.

---

## Phase 1 — Setup

- [x] **T001** Read `contracts/*.contract.md` + current `scripts/foreman/verify_test_coverage.py` parser/verify/report paths; note insertion points for `matching_mode`, `--tolerant`, and `check_file_has_passing_test` in a short comment block at the top of `tests/foreman/test_verify_test_coverage.py` (FR-001 baseline).

---

## Phase 2 — Foundational parser (blocks US1–US3)

**Goal**: `parse_tasks_md(..., matching_mode="tolerant")` accepts file-only `**Test N**` lines; strict mode rejects them.

### Tests first (RED)

- [x] **T002** [P] [US1] In `tests/foreman/test_verify_test_coverage.py` add `TestTolerantParser`:
  - `test_file_only_line_parsed_in_tolerant_mode` — `` `tests/foo/test_bar.py` `` without `::function` → one `RequiredTest` with `function=""` or dedicated `RequiredFile` shape per implementation (FR-004).
  - `test_file_only_line_rejected_in_strict_mode` → `ParseError` (FR-005).
  - `test_strict_shaped_line_still_parsed_in_tolerant_mode` — `` `path::test_x` `` still accepted (FR-008 superset).
  - `test_tdd_discipline_line_ignored_in_tolerant_parse` — block with `**TDD discipline**: required` yields `tdd_required=False` for tolerant verify purposes (contract §4).

### Implementation

- [x] **T003** Extend `parse_tasks_md` with `matching_mode: Literal["strict","tolerant"]` + `_FILE_ONLY_TEST_RE`; wire strict vs tolerant grammar per `contracts/tolerant-requirements.contract.md` (FR-004, FR-005).
- [x] **T004** Run `TestTolerantParser` → green.

**Checkpoint**: Parser foundation ready.

---

## Phase 3 — US1: Retro file-level coverage verdict (P1) 🎯 MVP

**Goal**: `--tolerant` produces per-file PASS/FAIL from file existence + ≥1 PASSED test (FR-002, FR-006).

**Independent test**: file-only `tasks.md` + real test file in temp worktree → exit 0; missing file → exit 1 with reason.

### Tests first (RED)

- [x] **T005** [P] [US1] Add `TestFilePassingPrimitive`:
  - `test_file_with_one_passing_test` — tiny `test_ok.py` with `def test_ok(): assert True` → True.
  - `test_file_all_skipped_not_passing` — module-level `pytest.mark.skip` on all tests → False (edge case).
  - `test_missing_file_not_passing` → False (FR-006).

- [x] **T006** [P] [US1] Add `TestVerifyTolerantE2E` (temp git worktree helpers, mirror existing e2e patterns):
  - `test_tolerant_all_files_pass` — two files listed, both pass → `summary.matching_mode=="tolerant"`, exit 0 (FR-001/002).
  - `test_tolerant_missing_file_fails` — lists nonexistent path → exit 1, `reason` names file (FR-006).
  - `test_tolerant_empty_file_fails` — file exists, zero tests or all skipped → exit 1 (FR-006).
  - `test_no_requirements_still_skipped` — task without block → `NO_REQUIREMENTS` (edge case).

### Implementation

- [x] **T007** [US1] Implement `check_file_has_passing_test(workdir, path)` — `pytest -v <path>` + PASSED-line detection (reuse PR #29 discipline from `check_pytest_run`) (FR-002, FR-007).
- [x] **T008** [US1] Implement `_verify_file_requirement` + tolerant branch in `verify(..., matching_mode=...)`; set `test_id` to file path only (FR-002).
- [x] **T009** [US1] Add `--tolerant` to `_build_parser()` / `main()`; thread flag into `verify()` (FR-001).
- [x] **T010** [US1] Run `TestFilePassingPrimitive` + `TestVerifyTolerantE2E` → green.

**Checkpoint**: MVP — legacy specs can get a tolerant verdict when blocks exist.

---

## Phase 4 — US2: Mode-tagged verdict (P2)

**Goal**: Tolerant PASS is unambiguous vs strict/TDD PASS (FR-003, SC-002).

### Tests first (RED)

- [x] **T011** [P] [US2] Add `TestModeTaggedReport`:
  - `test_json_strict_mode_field` — default run → `summary.matching_mode == "strict"` (FR-003/005).
  - `test_json_tolerant_never_sets_tdd_timeline_true` — tolerant rows have `tdd_timeline_ok is None` (FR-003).
  - `test_human_banner_tolerant` — text output contains `MODE: tolerant` (FR-003).
  - `test_human_banner_strict` — text output contains `MODE: strict` (FR-003).

### Implementation

- [x] **T012** [US2] Stamp `summary.matching_mode` in `verify()` return dict (FR-003).
- [x] **T013** [US2] Update `_render_text()` with MODE banner per `contracts/verdict-report.contract.md` (FR-003).
- [x] **T014** [US2] Run `TestModeTaggedReport` → green.

**Checkpoint**: US2 — operators cannot confuse verdict tiers.

---

## Phase 5 — US3: Cheap retro authoring (P3)

**Goal**: File-only lists work without function names or TDD flag (FR-004).

- [x] **T015** [US3] Update `docs/foreman.md` — tolerant grammar section, `--tolerant` CLI table row, JSON `matching_mode` + tolerant row shape, cross-link to `specs/057-foreman-retro-matcher/contracts/` (FR-004; doc task).
- [x] **T016** [US3] Add `test_file_only_block_end_to_end` — minimal `tasks.md` with two file-only lines, no TDD line → tolerant PASS (US3 acceptance).

---

## Phase 6 — Strict regression & relaxation (FR-005, FR-008, SC-004, SC-005)

### Tests first (RED)

- [x] **T017** [P] Add `TestStrictModeUnchanged` — port existing strict parser + verify golden cases; assert per-node checks + TDD path still run when `matching_mode="strict"` (FR-005, SC-004).
- [x] **T018** [P] Add `test_strict_pass_implies_tolerant_pass` — one fixture `tasks.md` with strict `` `path::func` `` blocks that PASS under strict also PASS under `--tolerant` on same worktree (FR-008).
- [x] **T019** [P] Add `test_deterministic_tolerant_verdict` — run `verify(..., tolerant)` twice on unchanged tree → identical JSON (FR-007, SC-005).

### Implementation

- [x] **T020** Confirm default CLI (no flag) exercises only strict code paths; run full `tests/foreman/test_verify_test_coverage.py` → green (SC-004).

---

## Phase 7 — SC-001 retro rollout (file-only blocks)

**Goal**: Each retro target can run tolerant mode once blocks exist (sequenced 028 → 018 → 022 → 025).

- [ ] **T021** [P] Add file-only `### Testing Requirements` blocks to `specs/028-dispatch-telemetry/tasks.md` for shipped tasks (use `fc24a43` / codebase audit to pick test files; collapse strict `` `path::func` `` retro enrichment to file paths where practical) (SC-001 / retro #1).
- [ ] **T022** [P] Add file-only blocks to `specs/018-testing-strategy/tasks.md` (SC-001 / retro #2).
- [ ] **T023** [P] Add file-only blocks to `specs/022-e2e-quality-harness/tasks.md` (SC-001 / retro #3).
- [ ] **T024** [P] Add file-only blocks to `specs/_archive/025-simplify-pass/tasks.md` (SC-001 / retro #4).
- [ ] **T025** Run tolerant verifier against each retro `tasks.md` on `main` worktree; capture pass/fail in PR description (SC-001 acceptance evidence).

---

## Phase 8 — Polish

- [x] **T026** [P] `CHANGELOG.md` `[Unreleased]` — Added: foreman `--tolerant` file-level retro mode; `matching_mode` in JSON report.
- [x] **T027** [P] `pytest tests/foreman/test_verify_test_coverage.py -v` + `ruff check scripts/foreman/ tests/foreman/` + `ruff format --check` on touched paths → clean.

---

## Dependencies & ordering

- **T001** → parser (T002–T004) → tolerant verify (T005–T010) → mode report (T011–T014) → docs/US3 (T015–T016).
- **Strict regression (T017–T020)** after tolerant verify lands (same file; merge carefully).
- **Retro authoring (T021–T025)** can follow mechanism PR or land in same PR if scope allows; does not block T001–T020.
- TDD pairs: T002→T003→T004 · T005/T006→T007/T008/T009→T010 · T011→T012/T013→T014.

## Parallel example

```text
# RED tests (distinct classes):
T002 + T005 + T006 + T011 + T017 + T018 + T019
# Retro authoring (different spec dirs):
T021 + T022 + T023 + T024
# Polish:
T026 + T027
```

## Acceptance coverage → spec.md

| Requirement | Tasks |
|---|---|
| FR-001 opt-in tolerant | T009, T006 |
| FR-002 file + ≥1 PASSED | T005, T007, T008, T010 |
| FR-003 mode labelled | T011–T014 |
| FR-004 file-only shape | T002–T004, T016 |
| FR-005 strict unchanged | T017, T020 |
| FR-006 missing/empty FAIL | T006, T008 |
| FR-007 determinism | T019 |
| FR-008 relaxation | T018 |
| SC-001 retro targets | T021–T025 |
| SC-002 distinguishable | T011–T014 |
| SC-003 no false PASS | T006 (`test_tolerant_missing_file_fails`, `test_tolerant_empty_file_fails`) |
| SC-004 strict regression | T017, T020 |
| SC-005 determinism | T019 |
| US1 / US2 / US3 | Phases 3–5 |
