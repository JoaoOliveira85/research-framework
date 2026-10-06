# Tasks: 058 Vault Control-File Git-Tracking Health Warning

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Input**: `spec.md` (clarified 2026-06-03), `plan.md`, `research.md` (D1–D6), `contracts/control-file-tracking.contract.md`, `quickstart.md`.
**Tests**: TDD per Principle III — RED in `tests/scripts/test_vault_health.py` before `scan_control_file_git_tracking()` lands. **[P]** = parallelizable.

---

## Phase 1 — Setup

- **T001** Read `contracts/control-file-tracking.contract.md` §1–3; add `CONTROL_FILE_PATHS` tuple at top of `scripts/vault_health.py` (four vault-relative strings, contract order).

---

## Phase 2 — US1: Warn when a control file isn't in git (P1) 🎯 MVP

**Goal**: Git-backed vault + present untracked/ignored control file → WARN lines; all tracked → none.

**Independent test**: `research.spec.md` untracked → one warning; `git add` → clear (SC-001).

### Tests first (TDD — RED)

- **T002** [P] In `tests/scripts/test_vault_health.py` add helper `_git_init_vault(tmp_path)` — minimal vault scaffold + four control files + `git init` (no add).
- **T003** [P] Add `TestControlFileGitTracking`:
  - `test_untracked_research_spec_warns` — present `research.spec.md` not in index → exactly one warning `{rel_path: "research.spec.md", reason: "untracked"}` (FR-001/005, SC-001). **FAILS today**.
  - `test_ignored_settings_warns` — `.gitignore` lists `settings.yaml`, file committed or present → warning `reason: "ignored"` (SC-004). **FAILS today**.
  - `test_all_tracked_no_warnings` — `git add` all four paths → `scan_*` returns `[]` (FR-006, SC-001). **FAILS today**.
  - `test_absent_file_skipped` — only `research.spec.md` on disk, tracked; other three missing → zero warnings (FR-002a). **FAILS today**.

### Implementation

- **T004** Add `ControlFileTrackingWarning` dataclass + `scan_control_file_git_tracking(vault: Path) -> list[...]` per contract §2–3 (`subprocess`, sorted output).
- **T005** Extend `HealthReport` with `control_file_tracking`; wire `run()` to populate it; extend `render_report()` with `## Control-file git tracking` section (contract §5). Confirm `unresolved_count` **excludes** this list (FR-004).
- **T006** Run `TestControlFileGitTracking` (T003 subset) → green.

**Checkpoint**: US1 shippable — operators see per-file untracked/ignored warnings in `./vault health` output + report.

---

## Phase 3 — US2: Stay silent on non-git vaults (P2)

**Goal**: Directory without `.git` → no warnings, no errors.

### Tests first (TDD — RED)

- **T007** [P] Add to `TestControlFileGitTracking`:
  - `test_non_git_vault_silent` — vault with four files, no `git init` → `[]` (FR-003, SC-002). **FAILS today**.

### Implementation

- **T008** Verify `rev-parse --is-inside-work-tree` guard returns `[]` on non-git; `render_report` shows `skipped (not a git work tree)` when applicable (contract §5). Re-run T007 → green.

**Checkpoint**: US2 shippable — no spurious warnings on non-git vaults.

---

## Phase 4 — US3: Advisory, never blocking (P3)

**Goal**: Tracking warnings never flip exit code.

### Tests first (TDD — RED)

- **T009** [P] Add to `TestControlFileGitTracking`:
  - `test_run_exit_zero_despite_tracking_warnings` — untracked `research.spec.md`, otherwise clean vault (`offline=True`) → `vh.run(...).unresolved_count == 0` AND `vh.main([str(vault), "--offline"]) == 0` (FR-004, SC-003). **FAILS today**.
  - `test_multiple_warnings_list_each_file` — untracked spec + ignored settings → two warnings, distinct reasons (FR-005). **FAILS today**.

### Implementation

- **T010** Audit `main()` — ensure only `report.unresolved_count` drives `return 1`; add inline comment at `unresolved_count` property documenting advisory exclusion (FR-004).
- **T011** [P] Add `test_deterministic_repeat_run` — two consecutive `scan_*` calls, same tree → identical list (FR-007, SC-005). Run T009–T011 → green.

**Checkpoint**: US3 shippable — safe to run in spec 027 post-update smoke.

---

## Phase 5 — Polish

- **T012** [P] Full module sweep: `pytest tests/scripts/test_vault_health.py -v` — all pre-existing tests still pass (no `unresolved_count` regression).
- **T013** [P] `ruff check scripts/vault_health.py tests/scripts/test_vault_health.py` + `ruff format --check` on touched paths → clean.
- **T014** `CHANGELOG.md` `[Unreleased]` — Added: `./vault health` warns when critical control files are untracked or git-ignored (spec 058, advisory only).
- **T015** Update `scripts/vault_health.py` module docstring sub-checks list (fourth bullet: control-file git tracking).

---

## Dependencies & ordering

- T001 before T004.
- TDD pairs: T003→T004/T005→T006 · T007→T008 · T009→T010→T011.
- US2/US3 can proceed after T006 (same module).
- Polish (T012–T015) after all story tests green.

## Parallel example

```text
# RED tests (distinct cases):
T003 + T007 + T009 + T011
# Polish:
T012 + T013
```

## Acceptance coverage → spec.md

| Requirement / SC | Evidence (tasks.md) |
|---|---|
| FR-001, FR-005, SC-001, SC-004 | `test_untracked_*`, `test_ignored_*`, `test_all_tracked_*` (T003 → T006) |
| FR-002, FR-002a | `CONTROL_FILE_PATHS` (T001); `test_absent_file_skipped` (T003) |
| FR-003, SC-002 | `test_non_git_vault_silent` (T007 → T008) |
| FR-004, SC-003 | `test_run_exit_zero_despite_tracking_warnings` (T009 → T010) |
| FR-006 | `test_all_tracked_no_warnings` (T003) |
| FR-007, SC-005 | `test_deterministic_repeat_run` (T011) |
| US1 | T003–T006 |
| US2 | T007–T008 |
| US3 | T009–T011 |
