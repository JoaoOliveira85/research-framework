# Research & Decisions: 026 Fixture Isolation Hardening

Phase 0 decisions. Inputs: clarify Session 2026-06-03 + a code audit at the 053 base
(`tests/quality/conftest.py`, `tests/_helpers/fake_agent.py`, `.gitignore`, `git ls-files`).

## The audit

| Claim (2026-05-22) | Reality at 053 base | Verdict |
|---|---|---|
| Harness mutates tracked fixtures | `run_fixture_cycles` runs `run_cycle_steps(fixture.vault_dir, …)` against the tracked tree (conftest.py:48-60) | **CONFIRMED** |
| ~6 modified + 4 untracked in `git status` | 36 files under `tests/fixtures/quality/*/_pipeline/` are **tracked** AND matched by `.gitignore:79` | **CONFIRMED + root cause found** |
| Committed shims bake `/Users/<name>…` at `:33` | `install_shim` bakes `None` in-repo, abs-root only out-of-repo; `rg /Users/ … → 0 hits` | **STALE** — already fixed |

## D1 — Isolate at the `run_fixture_cycles` seam via `shutil.copytree` (least blast radius)
**Decision**: `run_fixture_cycles(name, *, tmp_path, ...)` (or an internal `tmp_path_factory`)
copies `resolve_fixture(name).vault_dir` → `tmp_path/<name>` with `shutil.copytree`, then runs
`run_cycle_steps` + `install_shim` against the **copy**. All call sites in `tests/quality/` pass a
`tmp_path`.
**Why**: this is the single choke-point every quality test funnels through; fixing it isolates
the entire harness without touching `run_cycle_steps` or per-test code. `run_cycle_steps` already
takes `vault_dir` first and is path-agnostic (audit), so it's a drop-in.
**Rejected**: copying inside `run_cycle_steps` (pollutes production code with test concerns);
a session-scoped copy (breaks per-test isolation + xdist); symlinking (cycles write through symlinks).

## D2 — FR-010: preserve baselines, untrack WAL sidecars, fix the gitignore
**Decision** (Q1 → PRESERVE + CLEAN): keep the deterministic `_pipeline/` baselines tracked
(they're the copy source + pin the committed `baselines/*.baseline.json`); `git rm --cached` the
`sources.db-shm`/`sources.db-wal` sidecars; rewrite `.gitignore:79` to stop ignoring the tracked
baselines (narrow it to the WAL sidecars + the per-run `_pipeline/quality/` workspace, or drop it
since FR-001 ends in-place mutation).
**Why**: the noise has two sources — (a) in-place mutation (fixed by D1) and (b) the
tracked-AND-ignored WAL sidecars that SQLite rewrites. (a) is gone after D1; (b) needs the
one-time untrack. Removing *all* baselines (the rejected Q1 option) would cold-start cycles and
likely shift the quality baselines — a much bigger, riskier change for no extra cleanliness.
**Rejected**: `git rm --cached` everything under `_pipeline/` (cold-start + baseline drift);
leaving the gitignore as-is (keeps lying about what's tracked → confuses the next maintainer).

## D3 — US2 reframe: lock committed shims, KEEP the tmp_path abs-path baking
**Decision**: FR-005 becomes a regression-lock (`rg` committed shims → 0 machine paths) + an
explicit test that the `tmp_path` shim *does* bake the abs repo root and interception still works.
Preserve `install_shim`'s `inside_repo` branch (fake_agent.py:1162-1166) verbatim.
**Why**: the bug is already fixed, and the "obvious" fix (strip all abs paths) would break the
Strategy-3 import the fake-agent shim uses to find `tests/_helpers/fake_agent` — which is what
keeps `test_fake_agent_interception` (Principle IV) green. Post-US1, *every* runtime shim is a
`tmp_path` shim, so the abs-path branch is the hot path; committed shims are only touched by the
bootstrap (→ `None`). Locking the invariant is the right residual work.
**Rejected**: "remove the absolute-path fallback" as literally written (regresses interception +
Principle IV); deleting the `inside_repo` logic (re-bakes abs paths into committed shims).

## D4 — US3: `--force` gate on `_bootstrap_us3_fixtures.py`
**Decision**: the bootstrap refuses to mutate tracked files unless invoked with `--force` (or an
interactive `y/N` confirm when run on a TTY). Default invocation is a dry-run that prints what it
*would* regenerate.
**Why**: it's the only legitimate writer of the tracked fixture tree; an accidental run (or a
muscle-memory `python _bootstrap_us3_fixtures.py`) currently dirties `git status` silently. A
`--force` gate cleanly separates "bootstrap regeneration" (intentional) from "runtime mutation"
(now impossible after D1).
**Rejected**: removing the bootstrap (it's the canonical fixture-regeneration path); making it
always-prompt even in CI (breaks any scripted regeneration — `--force` covers that).

## D5 — Regression test shape (FR-009/SC-005)
**Decision**: `tests/quality/test_fixture_isolation.py`:
- `test_quality_cycle_leaves_tracked_tree_pristine` — run **one** `tech-lite` fixture cycle through
  the (post-D1) `run_fixture_cycles`, then assert `git status --porcelain tests/fixtures/quality/`
  is empty. **Smoke-gated** (added to `build.sh::SMOKE_TESTS`). FAILS today (in-place mutation).
- `test_committed_shims_machine_agnostic` — `rg "/(Users|home|private/var/folders)/"` over committed
  shims → 0 (FR-005).
- `test_tmp_path_shim_bakes_root_and_interception_holds` — install a shim into an out-of-repo
  `tmp_path`, assert the baked value is the repo root AND a dispatch through it routes to
  `tests/_helpers/fake_agent` (interception intact).
**Why**: one cheap cycle (tech-lite is the fastest fixture) gives a real end-to-end signal; the
shim tests are pure-static/fast. Smoke-gating makes any future regression hard-fail the build —
the exact gap the spec exists to close.
**Rejected**: asserting clean tree only via the full 3-fixture `--quality` run (too slow for the
fast loop; the one-cycle test is sufficient + the full run still happens in `build.sh --quality`).

## Cross-spec
- **009 (Wave 2)** consumes 026's outcome — its CI's "git status clean after the gate" check only
  passes once 026 lands. Sequencing recorded in the spec.
- **030 (Wave 1)** extends `run_fixture_cycles`; if it lands first its fixtures ride the same
  D1 seam for free.
