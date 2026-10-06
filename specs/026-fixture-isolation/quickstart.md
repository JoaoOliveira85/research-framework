# Quickstart: 026 Fixture Isolation Hardening

## The one-time cleanup (FR-010)

```bash
# Untrack the volatile SQLite WAL sidecars (they should never have been committed):
git rm --cached tests/fixtures/quality/*/_pipeline/sources.db-shm \
                tests/fixtures/quality/*/_pipeline/sources.db-wal
# .gitignore is fixed in the same PR so they stay ignored going forward.
```

## Verify the working tree stays pristine (the whole point — SC-001)

```bash
git status --porcelain            # clean
./build.sh --quality              # runs the 3-fixture quality gate
git status --porcelain            # STILL clean  ← was 6 modified + 4 untracked before 026
```

## Run the regression test (fast loop + smoke gate — FR-009/SC-005)

```bash
pytest tests/quality/test_fixture_isolation.py -v
#   test_quality_cycle_leaves_tracked_tree_pristine   (one tech-lite cycle → git status clean)
#   test_committed_shims_machine_agnostic             (rg committed shims → 0 abs paths)
#   test_tmp_path_shim_bakes_root_and_interception_holds
```

## What changed for fixture authors

- The quality harness now runs each cycle against a **`tmp_path` copy** of the fixture, not the
  tracked tree. To inspect a failed run, look at the `tmp_path` the test reports (FR-006).
- The committed fixture under `tests/fixtures/quality/<name>/` is **read-only at runtime**. The
  ONLY way to (re)generate it is the bootstrap, now gated:

```bash
python tests/fixtures/quality/_bootstrap_us3_fixtures.py            # dry-run: prints what WOULD change
python tests/fixtures/quality/_bootstrap_us3_fixtures.py --force    # actually regenerate (intentional)
```

## Shim baking — what's correct (US2 reframe)

- **Committed** shims (`tests/fixtures/quality/*/scripts/agent_call.py`) → baked repo root is `None`
  (machine-agnostic). Locked by `test_committed_shims_machine_agnostic`.
- **`tmp_path`** shims (installed at runtime, never committed) → bake the abs repo root **on
  purpose**, so the shim's Strategy-3 import finds `tests/_helpers/fake_agent` and the Principle-IV
  interception guard keeps working. Do NOT "fix" this.
