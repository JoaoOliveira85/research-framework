# Quickstart: Validating the `_cycle_helpers.py` Split

**Spec**: 049 | **Date**: 2026-06-03

The acceptance bar for this refactor is **behaviour preservation** (FR-005 / SC-006:
byte-identical cycle artifacts). This quickstart is the per-PR validation recipe. Run it after
**every** submodule PR — green here is the gate, not "it compiled".

> Use `.venv/bin/python`, **not** pyenv base (MEMORY.md — pyenv base has a stale editable
> install that produces ~34 false failures in subprocess tests).

---

## 1. Fast suite stays green at ≥ baseline (FR-006 / SC-004)

```bash
.venv/bin/python -m pytest -m "not e2e" -q
```

- **Baseline (2026-06-03): 1934 fast-loop tests.** The count must be **≥ 1934** after every PR
  (Phase 1 adds exactly one: `test_cycle_runtime_state.py` → 1935).
- **Phases 1-7**: zero test files should need editing for import resolution — the transitional
  `_cycle_helpers.py` shim + the `cycle_runner` alias block absorb every import (SC-007). If a
  test fails on an `ImportError` during these phases, the shim re-export for the just-moved
  submodule is incomplete — fix the shim, don't edit the test.
- **Phase 8 only**: the 3 direct-import test files are repointed in the *same* PR that deletes
  the shim (research.md §2.1). After that edit the suite must still be ≥ baseline.

## 2. Both ruff gates clean (FR-006 / SC-004) — they are SEPARATE

```bash
ruff check .            # gate 1
ruff format --check .   # gate 2 — passing gate 1 does NOT imply this
```
Zero errors on both (CLAUDE.md zero-baseline). A PR green on `check` but never run through
`format --check` fails the release workflow.

## 3. Smoke gate green (FR-009 / ADR-0007)

```bash
./build.sh
```
Mandatory, un-skippable. Every PR in the split must pass independently.

## 4. Byte-identical artifacts — the behaviour-preservation proof (SC-006)

### 4a. Quality harness (the primary signal, run on every pipeline-touching PR)

```bash
./build.sh --quality
```
Runs the spec-022 harness: 3 fixtures (tech-lite / source-poor / source-rich) × 3 metric
families, with a regression diff against committed baselines. **Zero regressions** = behaviour
preserved. This is the canonical FR-005 check.

### 4b. Manual pre/post artifact diff (use when in doubt on a risky PR, e.g. Phase 7)

Run a fixture cycle on the base ref and on the PR ref, then byte-diff the produced artifacts:

```bash
# 1. Build a minimal fixture vault (tier-5/6 e2e factory)
.venv/bin/python -m pytest -m e2e -k "full_cycle" -q   # confirms the e2e path is green both refs

# 2. Pre-refactor snapshot — on the base ref (e.g. the prior phase's merge commit)
git stash; git checkout <base-ref>
<run the fixture cycle, e.g. via the tier-6 e2e harness or vault_factory.build_minimal_vault>
cp -r <vault>/_pipeline/cycles/cycle-001 /tmp/049-pre

# 3. Post-refactor snapshot — back on the PR branch
git checkout 049-cycle-helpers-split; git stash pop
<run the same fixture cycle with the same seed/inputs>
cp -r <vault>/_pipeline/cycles/cycle-001 /tmp/049-post

# 4. Diff — must be empty (modulo timestamps, which the harness normalizes)
diff -r /tmp/049-pre /tmp/049-post
```
Expected: no differences in `cycle-NNN-quality-report.json`, research/scout/harvest JSON,
or note bodies. Timestamp-only diffs are acceptable (the spec-022 harness already strips them).

## 5. Structural acceptance checks (SC-001 / SC-002 / SC-003 / SC-005)

```bash
# SC-001: no submodule exceeds 300 LOC
wc -l src/research_framework/pipeline/_helpers/*.py | sort -n

# SC-002 (during split): shim ≤80 LOC … (after final PR): file is GONE
wc -l src/research_framework/pipeline/_cycle_helpers.py 2>/dev/null \
  || echo "shim deleted (expected end state)"

# SC-003: zero module-level mutable globals in the new subpackage
grep -rnE "^_[a-z_]+(: [a-zA-Z_]+)? = (False|True|\{\}|\[\])$" \
  src/research_framework/pipeline/_helpers/ \
  && echo "FAIL: mutable global found" || echo "PASS: no mutable globals"

# SC-005: each of the 7 concerns lives in exactly one file
ls src/research_framework/pipeline/_helpers/
```

## 6. Per-phase exit criteria (summary)

| Phase | Adds/Moves | Validation that must pass |
|---|---|---|
| 1 `cycle_state` | new `CycleRuntimeState` + 1 test | §1 (count→1935), §2, §3 |
| 2 `script_runner` | move 6 names | §1, §2, §3, §4a |
| 3 `state` | move 12 names | §1, §2, §3, §4a |
| 4 `cosmetic_correction` | move 5 names | §1, §2, §3, §4a |
| 5 `scout_correction` | move 8 names | §1, §2, §3, §4a |
| 6 `source_signals` + `quality_report_guard` | move 12 names + `_active_timings` accessor | §1, §2, §3, §4a, §4b (timings path is risky) |
| 7 `CycleRuntimeState` wiring | thread state, delete 2 globals | §1, §2, §3, §4a, **§4b (highest-risk)**, §5 SC-003 |
| 8 delete shim | repoint 3 imports + steps + cycle_runner aliases; delete `_cycle_helpers.py`; CHANGELOG | §1, §2, §3, §4a, §5 (all SC) |

## NEEDS CLARIFICATION

None.
