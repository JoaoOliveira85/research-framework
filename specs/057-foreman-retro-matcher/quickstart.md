# Quickstart: Foreman tolerant retro mode (057)

## Run tolerant verification

From the repo root (or any git worktree of this project):

```bash
python -m scripts.foreman.verify_test_coverage \
  --tasks specs/028-dispatch-telemetry/tasks.md \
  --workdir "$(pwd)" \
  --tolerant \
  --json
```

Expect `summary.matching_mode` = `"tolerant"` and per-requirement `test_id` values
that are **file paths only** (no `::function`).

Human-readable:

```bash
python -m scripts.foreman.verify_test_coverage \
  --tasks specs/028-dispatch-telemetry/tasks.md \
  --workdir "$(pwd)" \
  --tolerant
```

Look for `MODE: tolerant — file-level coverage only (not TDD-verified)`.

## Strict mode (default — unchanged)

Omit `--tolerant`. Strict blocks require `` `path::function` ``.

```bash
python -m scripts.foreman.verify_test_coverage \
  --tasks specs/029-source-manager-correctness/tasks.md \
  --workdir "$(pwd)" \
  --json
```

## Author a retro (file-only) block

Inside a task in `tasks.md`:

```markdown
- [ ] T010 Example task (retro coverage only)

  ### Testing Requirements

  _Authored for foreman retro (spec 057). File-level only._

  - **Test 1**: `tests/foreman/test_verify_test_coverage.py`
  - **Test 2**: `tests/observability/test_log_surfaces.py`
```

Do **not** add `**TDD discipline**: required` for retro blocks.

## Interpret results

| Outcome | Meaning |
|---------|---------|
| exit 0 + `matching_mode: tolerant` | Every listed file exists with ≥1 passing test — **insurance**, not TDD proof |
| exit 1 | At least one file missing or zero passing tests — see `reason` per row |
| exit 2 | Malformed `tasks.md` or bad paths |
| tasks with empty requirements | `NO_REQUIREMENTS` — tolerant mode does not invent lists |

## Retro rollout order (SC-001)

1. `specs/028-dispatch-telemetry/tasks.md` (reference: `fc24a43` strict enrichment → convert to file-only)
2. `specs/018-testing-strategy/tasks.md`
3. `specs/022-e2e-quality-harness/tasks.md`
4. `specs/_archive/025-simplify-pass/tasks.md`
