# Tasks: 026 Fixture Isolation Hardening

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Input**: `spec.md` (clarified 2026-06-03), `plan.md`, `research.md` (D1–D5), `quickstart.md`.
**Tests**: TDD per Principle III — the git-status-clean regression test lands RED before the FR-001 fix. **[P]** = parallelizable.
**Sequencing**: independent of other Wave-2/Wave-1 specs; **lands before (or with) spec 009's quality-gate CI step** (009 asserts the clean tree 026 produces).

---

## Phase 1 — Setup
- **T001** Confirm `resolve_fixture(name).vault_dir` + `run_cycle_steps(vault_dir, cycle)` are path-agnostic (audit says yes). Note the `build.sh::SMOKE_TESTS` list location for T012.

## Phase 2 — US1: Quality gate leaves the working tree pristine (P1) 🎯 MVP

**Goal**: the harness runs against a `tmp_path` copy; `git status` is clean after the gate.

**Independent test**: run one fixture cycle → `git status --porcelain tests/fixtures/quality/` empty.

### Tests first (TDD — RED)
- **T002** [P] Write `tests/quality/test_fixture_isolation.py::test_quality_cycle_leaves_tracked_tree_pristine`: capture `git status --porcelain tests/fixtures/quality/` (empty precondition), run one `tech-lite` cycle via `run_fixture_cycles`, assert it's **still** empty. **MUST FAIL today** (in-place mutation dirties `_pipeline/`). *(Also added a sibling `test_quality_runner_leaves_tracked_tree_pristine` for the `python -m …quality.runner` seam — the one `build.sh --quality` actually runs.)*

### Implementation
- **T003** Refactor `tests/quality/conftest.py::run_fixture_cycles` (D1): accept/derive a `tmp_path`, `shutil.copytree(resolve_fixture(name).vault_dir, tmp_path/name)`, then run `run_cycle_steps` + `fake_agent.install_shim` against the **copy**. Update all `tests/quality/` call sites to pass a `tmp_path`. *(Shared copy helper extracted to `quality.runner.isolate_fixture`; `run_fixture_cycles` now returns `(outputs, work_fixture)` so metric callers read the copy. The runner seam (`collect_fixture_current`) was isolated the same way — required for T005's build.sh check.)*
- **T004** Implement FR-006: on cycle failure, do NOT clean the `tmp_path`; surface its location in the test output (log/print). On success, let pytest's `tmp_path` GC it (FR-007). *(Runner path mirrors this: crash preserves `_pipeline/quality/work/<name>` + prints it; clean run rmtrees it.)*
- **T005** Run T002 → green. Manually confirm `./build.sh --quality` then `git status --porcelain` is empty. *(Verified: full runner → PASS 3/3, tracked tree pristine after deleting pre-fix leftovers.)*

**Checkpoint**: US1 shippable — the daily friction is gone.

---

## Phase 3 — FR-010: preserve baselines, untrack WAL, fix gitignore (P1, pairs with US1)
- **T006** `git rm --cached tests/fixtures/quality/*/_pipeline/sources.db-shm tests/fixtures/quality/*/_pipeline/sources.db-wal` (untrack the volatile WAL sidecars only).
- **T007** Edit `.gitignore`: replace the blanket `tests/fixtures/quality/**/_pipeline/` with narrow patterns (`tests/fixtures/quality/*/_pipeline/sources.db-shm`, `…-wal`, and the per-run `_pipeline/quality/` workspace). Verified `git check-ignore` no longer matches the tracked seed inputs, and DOES match the WAL sidecars.
- **T008** Verify the committed quality baselines (`tests/fixtures/quality/baselines/*.baseline.json`) are byte-unchanged after T003+T006 (runner verdict PASS, 0 regressions, no baseline diffs in `git status` — the preserved seed `.db` keeps cycles deterministic).

**Checkpoint**: the tracked-AND-ignored contradiction is resolved; `git status` clean for the right reasons.

---

## Phase 4 — US2: Lock committed shims machine-agnostic (P2, regression-lock)

### Tests first
- **T009** [P] `test_committed_shims_machine_agnostic` — `rg "/(Users|home|private/var/folders)/"` over `tests/fixtures/quality/*/scripts/agent_call.py` → 0 hits (passes today; locks it).
- **T010** [P] `test_tmp_path_shim_bakes_root_and_interception_holds` — `install_shim` into an out-of-repo `tmp_path`; assert the baked value == repo root (NOT `None`); in-repo install bakes `None`. The end-to-end interception remains guarded by `test_fake_agent_interception` (now runs through an out-of-repo `tmp_path` copy).

### Implementation
- **T011** In `tests/_helpers/fake_agent.py`, extracted the baked-root logic to a documented `_baked_root_for(target)` helper (guard comment explains WHY out-of-repo bakes the abs root — Strategy-3 / interception). `install_shim` behaviour unchanged.

**Checkpoint**: the already-fixed US2 invariant can't silently regress.

---

## Phase 5 — US3: `--force` gate on the bootstrap (P3)
- **T012** Add a `--force` flag (and a TTY `y/N` confirm) to `tests/fixtures/quality/_bootstrap_us3_fixtures.py`: default invocation is a dry-run printing what *would* change; tracked-file mutation requires `--force`. Added `test_bootstrap_refuses_without_force` to `test_fixture_isolation.py`.

---

## Phase 6 — Smoke gate + polish
- **T013** Add `tests/quality/test_fixture_isolation.py` to `build.sh::SMOKE_TESTS` (SC-005) so a future pollution regression hard-fails the build. (Also exempted the module in `test_marker_isolation.py` — it's a mixed fast-guard/one-e2e regression-lock, like `test_baseline_update_isolation.py`.)
- **T014** [P] SC-004 check: copytree is tiny (committed fixtures < 1 MB); fast `tests/quality/` loop stayed ~3s and the 4-test e2e harness ~23s — well within the <10% budget.
- **T015** [P] `CHANGELOG.md` `[Unreleased]` — Fixed: quality harness polluted the working tree (in-place fixture mutation); untracked SQLite WAL sidecars; bootstrap now `--force`-gated. Note: committed shims were already machine-agnostic (now locked).

---

## Dependencies & ordering
- TDD: T002→T003→T005 · T009/T010→T011.
- T006/T007/T008 (FR-010) pair with T003 — do together so the gate verification (T005) sees the cleaned gitignore.
- **US1 (Phase 2 + 3) is the MVP** and independently shippable. US2 (Phase 4) and US3 (Phase 5) are independent add-ons.
- Cross-spec: land before/with **009**'s quality-gate CI step; rides the same seam as **030** if 030 merges first.

## Parallel example
```
# RED tests up front:
T002 + T009 + T010
# Polish:
T014 + T015
```

## Acceptance coverage → spec.md
| User Story | Evidence (tasks.md) |
|---|---|
| US1 — pristine working tree | `test_quality_cycle_leaves_tracked_tree_pristine` (T002 → T003/T004 → T005) + FR-010 cleanup (T006-T008) |
| US2 — committed shims machine-agnostic (lock) | `test_committed_shims_machine_agnostic` + `test_tmp_path_shim_bakes_root_and_interception_holds` (T009/T010 → T011) |
| US3 — bootstrap `--force` gate | `test_bootstrap_refuses_without_force` (T012) |
