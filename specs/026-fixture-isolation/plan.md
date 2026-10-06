# Implementation Plan: Fixture Isolation Hardening (026)

**Branch**: `026-fixture-isolation` | **Date**: 2026-06-03 | **Spec**: `specs/026-fixture-isolation/spec.md`
**Input**: Spec (clarified Session 2026-06-03) + an audit at the 053 base: read `tests/quality/conftest.py::run_fixture_cycles`, `tests/_helpers/fake_agent.py::install_shim` + `_SHIM_TEMPLATE`, `.gitignore`, `git ls-files tests/fixtures/quality/*/_pipeline/*` (36 tracked + ignored), `git grep /Users/ … → 0`.

## Summary

Stop the quality harness polluting the working tree. **US1**: `run_fixture_cycles` runs `run_cycle_steps` against the *tracked* `fixture.vault_dir`; migrate it to `shutil.copytree` the fixture into `tmp_path` first and point the cycle runner + `install_shim` at the copy (FR-001/002/003). **FR-010 (preserve+clean)**: keep the deterministic `_pipeline/` baselines as the copy source, `git rm --cached` the volatile SQLite WAL sidecars, and fix the contradictory `.gitignore` entry. **US2 (regression-lock)**: the baked-abs-path bug is already fixed by `install_shim`'s in-repo→`None` branch — add a test that locks committed shims machine-agnostic while *preserving* the `tmp_path`→abs-path branch that Strategy-3 import resolution (and the Principle-IV interception guard) depend on. **US3**: add a `--force` gate to `_bootstrap_us3_fixtures.py`. Net result: `git status --porcelain` is empty after `./build.sh --quality` (SC-001), and a smoke-gated regression test (FR-009/SC-005) keeps it that way.

## Technical Context

**Language/Version**: Python 3.11.
**Primary Dependencies**: stdlib (`shutil.copytree`, `pathlib`, `subprocess` for the git-status assertion) + `pytest`. **No new runtime dependency** (Principle V).
**Storage**: test-time `tmp_path` copies of `<10 MB` fixture vaults; the tracked `tests/fixtures/quality/<name>/` becomes read-only at runtime.
**Testing**: `pytest`; new `tests/quality/test_fixture_isolation.py` (smoke-gated). The git-status assertion shells `git status --porcelain tests/fixtures/quality/`.
**Target Platform**: macOS + Linux (this spec *feeds* spec 009's cross-platform CI).
**Project Type**: single project — test-harness + fixture hygiene; **no `src/` behaviour change**.
**Performance Goals**: copy adds I/O but fixtures are tiny; SC-004 caps the regression at <10% wall-clock vs baseline.
**Constraints**: MUST NOT break fake-agent interception (the `tmp_path` shim must keep baking the abs repo root); MUST NOT cold-start fixtures (preserve baselines); the regression test must FAIL before the FR-001 fix (TDD).
**Scale/Scope**: ~1 refactored function (`run_fixture_cycles`), 1 `.gitignore` edit, 2 `git rm --cached`, 1 bootstrap `--force` gate, 1 new test module (~4 tests). No contracts/data-model.

## Constitution Check

*GATE: must pass before Phase 0. Re-checked after Phase 1.*

| Principle | Assessment |
|---|---|
| **I. Script-Validated Quality Gates (NON-NEGOTIABLE)** | ✅ The git-status-clean regression test (FR-009) is itself a deterministic gate, smoke-gated (SC-005). |
| **III. Test-First (TDD — NON-NEGOTIABLE)** | ✅ `test_fixture_isolation.py` asserting a clean tree is written first and FAILS today (harness mutates in place) → passes after FR-001. |
| **IV. Agent-Script Separation** | ✅ Reinforces it — the whole point of preserving the `tmp_path`→abs-path baking is to keep the fake-agent shim intercepting so no real `claude`/`codex` is spawned in fixture cycles. |
| **V. Offline-First, No New Deps** | ✅ stdlib + pytest only. |
| **VIII. No Placeholders** | ✅ Real copy-to-tmp_path; the `--force` gate is functional. |
| **X. Vault History is Append-Only Git (NON-NEGOTIABLE)** | ✅ N/A to product code; thematically aligned (keeps the tracked tree pristine). |

**Result: PASS — no violations.**

## Project Structure

### Documentation (this feature)
```text
specs/026-fixture-isolation/
├── plan.md        # this file
├── research.md    # Phase 0 — decisions D1..D5 (incl. the audit + US2 reframe)
├── quickstart.md  # run the gate; verify clean tree; the WAL-untrack one-time step
└── tasks.md       # Phase 2 (/speckit.tasks)
```

### Source touched (repository root)
```text
tests/quality/conftest.py
  • run_fixture_cycles()  — FR-001/002/003: copytree fixture→tmp_path; run cycles + install_shim against the COPY
tests/_helpers/fake_agent.py
  • install_shim()        — FR-005: PRESERVE the in-repo→None / out-of-repo→repr(root) branch; add a guard comment + (optional) assertion helper
.gitignore
  • FR-010: replace the blanket `tests/fixtures/quality/**/_pipeline/` with narrow WAL-sidecar patterns (or drop it)
tests/fixtures/quality/_bootstrap_us3_fixtures.py
  • US3/FR-008: add `--force` / interactive-confirm gate before mutating tracked files
tests/fixtures/quality/*/_pipeline/sources.db-shm, *.db-wal
  • FR-010: `git rm --cached` (one-time; they become untracked + ignored)
tests/quality/test_fixture_isolation.py   — NEW: FR-004/009 git-status-clean + FR-005 committed-shim-grep + interception-intact
```

## Phase 0 — Research (→ research.md)
Decisions **D1–D5**: copy-to-`tmp_path` via `shutil.copytree` at the `run_fixture_cycles` seam (least-blast-radius); preserve baselines + untrack WAL + fix gitignore (FR-010); US2 reframe (lock committed shims, keep the tmp_path baking); the `--force` bootstrap gate; and the regression-test shape (one `tech-lite` cycle + `git status --porcelain` assertion, smoke-gated).

## Phase 1 — Design
- No `contracts/`/`data-model.md` — the invariants are "clean `git status` after the gate" (FR-004/SC-001) and the `install_shim` baking rule (FR-005), both fully specified in `spec.md`.
- `quickstart.md`: the one-time `git rm --cached` of the WAL sidecars, running `./build.sh --quality`, and verifying `git status --porcelain` is empty.

## Complexity / risks
- **`run_cycle_steps` writing outside the vault**: if any step writes to a repo-relative path instead of `vault_dir`-relative, the copy won't fully isolate it. Mitigation: the regression test asserts the *whole* tracked `tests/fixtures/quality/` is clean (catches stragglers), not just `_pipeline/`.
- **Baseline drift from untracking WAL**: `sources.db-shm/-wal` are SQLite-internal; untracking is safe (the `.db` carries committed state). Verify the quality baselines (`baselines/*.baseline.json`) are unchanged after the refactor (they should be — the seed `.db` is preserved).
- **030 ordering** (Wave 1): if 030's new fixtures land first, they ride the same `run_fixture_cycles` seam — covered automatically. Recorded in spec Dependencies.
- **Interception guard regression**: the biggest trap — "cleaning up absolute paths" too aggressively would break Strategy-3. Mitigation: US2 scenario 2 explicitly asserts the guard still passes with the tmp_path abs-path baking active.
