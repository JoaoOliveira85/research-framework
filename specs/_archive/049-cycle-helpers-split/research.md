# Research: `_cycle_helpers.py` God-Module Split

**Spec**: 049 | **Date**: 2026-06-03 | **Source file**: 1428 LOC, 39 module-level names.

This document is the empirical backbone of the plan. It answers the spec's two named "key
risks" — (1) enumerate every test-side private import, and (2) verify the import topology has
no cycles — with grep-verified facts, not speculation.

---

## 1. Import topology (current)

### 1.1 Who imports `_cycle_helpers` (production)

```
src/research_framework/pipeline/cycle_runner.py:25        from . import _cycle_helpers as h
src/research_framework/pipeline/steps/scout.py:11         from .. import _cycle_helpers as h
src/research_framework/pipeline/steps/postprocess.py:9    from .. import _cycle_helpers as h
src/research_framework/pipeline/steps/research.py:12      from .. import _cycle_helpers as h
```

Plus two **doc-comment-only** mentions (no import, no behaviour):
`quality_report.py:422`, `process_tree.py:22`.

### 1.2 The hidden second shim: `cycle_runner.py` already re-exports all 39 symbols

`cycle_runner.py:67-106` is a verbatim alias block:

```python
# Re-export helpers for backward compatibility (tests patch cycle_runner.subprocess).
MAX_SCOUT_VALIDATION_RETRIES = h.MAX_SCOUT_VALIDATION_RETRIES
QualityReportState           = h.QualityReportState
_StepError                   = h._StepError
... (35 more) ...
notify_required_source_degraded = h.notify_required_source_degraded
```

**This is the single most important fact for the migration.** Tests and code that go through
`cycle_runner.<symbol>` are insulated from where the symbol physically lives. The `_helpers/`
split only has to keep `cycle_runner`'s alias block pointing at the right objects — which it
does PR-by-PR — and the transitional `_cycle_helpers.py` shim covers the four `from … import
_cycle_helpers as h` sites until the final PR.

### 1.3 Lazy reach-backs from `_cycle_helpers` INTO the rest of the pipeline

These are the cyclic-import landmines the spec (risk #3) warns about. **Every one is already
lazy (function-local import)**, so the split inherits an acyclic shape *as long as we keep
them lazy*:

| Line | Lazy import | Lands in submodule | Cycle if made eager? |
|---|---|---|---|
| 32 | `from research_framework.pipeline import cycle_runner as _cr` (`_subprocess`) | `script_runner` | **YES** — `cycle_runner`→`script_runner`→`cycle_runner`. Keep lazy. |
| 401 | `from …correction import build_directive` + `…gates import GateResult` | `scout_correction` | Possible (`correction` imports pipeline). Keep lazy. |
| 617 | `from …pipeline import cycle_runner as _cr` (`_quality_report_guard`) | `quality_report_guard` | **YES**. Keep lazy. |
| 638 | `from …pipeline import quality_report` | `quality_report_guard` | Possible. Keep lazy. |
| 647 | `from …pipeline import cycle_runner as _cr` (`_active_timings` access) | `quality_report_guard` | **YES** → replace with accessor (plan Phase 6). |
| 661 | `from …spec.schema import SpecConfig` | `source_signals` | No (spec pkg is leaf-ish). Lazy fine. |
| 675 | `from …spec.simple import load` | `source_signals` | No. Lazy fine. |
| 687 | `from .research_plan import ResearchPlan` | `scout_correction`/`source_signals` | No. |
| 698 | `from .coverage import load_targets` | `source_signals` | No. |
| 722 | `from …pipeline import source_manager as _sm` | `source_signals` | Possible. Keep lazy. |
| 752/821 | `from …_assets import default_settings_path` | `source_signals` | No. |
| 783/1093/1413 | `from .atomic_write import write_json` | `state`/`source_signals` | No — `atomic_write` is a leaf. Can be top-of-module. |
| 1027 | `from .research_plan import PrioritizedTopic` | `scout_correction` | No. |
| 1243 | `from .batch import BatchResult` | `state` | No. |
| 1261 | `from …pipeline.correction import …` | `scout_correction` | Possible. Keep lazy. |
| 1313 | `from …pipeline.probes import generate_probes` | `source_signals` | Possible. Keep lazy. |
| 1357 | `from .plan_narrator import _bootstrap_scripts_agent_call, _load_vault_tier` | `source_signals` | Possible. Keep lazy. |
| 1422 | `from …pipeline import probes as _probes_mod` | `source_signals` | Possible. Keep lazy. |
| 590 | `from .atomic_write import write_json` | `state` | No — leaf. |

**Topology conclusion (FR-007 satisfied):** The new submodule graph is a DAG. Cross-submodule
edges introduced by the split are leaf→leaf and acyclic:
`script_runner` (leaf, only lazy `cycle_runner`) ← `scout_correction` (needs `_run_script`,
`_render_prompt`) and `quality_report_guard`; `state._vault_notes_content_sha1` ←
`cosmetic_correction`, `source_signals`. **The four reach-backs into `cycle_runner` must stay
lazy** (lines 32, 617, 647 + the `correction`/`probes`/`plan_narrator` ones). The `_active_timings`
reach-back (647) is the only one upgraded — to a thin accessor on `cycle_runner` — so the guard
never reaches a raw module global.

### 1.4 Module-level top-of-file imports (always-safe leaves)

`_cycle_helpers.py:21-23` imports only:
```python
from . import atomic_write          # leaf
from .gates import GateResult       # leaf
from .process_tree import popen_session, terminate_process_tree  # leaf
```
None of these import `cycle_runner`, so they may become eager top-of-module imports in any
submodule that needs them (`script_runner` ← `process_tree`; `cosmetic_correction`/`state` ←
`gates`, `atomic_write`).

---

## 2. Test-side private imports (the spec's "key risk")

**Finding: only THREE test files import `_cycle_helpers` by path.** The risk is far smaller
than the spec feared, because the dominant test access pattern is via `cycle_runner.<symbol>`
(insulated by the 1.2 alias block) and via the shared `_patch_cycle_runner_subprocess` helper
in `test_cycle_runner.py` (which patches `cycle_runner.subprocess.{run,Popen}`, *not* helpers).

### 2.1 Direct `_cycle_helpers` imports — must be repointed in the FINAL PR (Phase 8)

| File:line | Statement | Symbol | Repoint target |
|---|---|---|---|
| `tests/pipeline/test_stamp_lifecycle_cycle.py:15` | `from research_framework.pipeline._cycle_helpers import _stamp_lifecycle_cycle` | `_stamp_lifecycle_cycle` | `_helpers.state` |
| `tests/pipeline/test_cycle_helpers_tree_kill.py:26` | `from research_framework.pipeline._cycle_helpers import _run_script` | `_run_script` | `_helpers.script_runner` |
| `tests/pipeline/test_budget_guard.py:206` | `from research_framework.pipeline import _cycle_helpers as h` (then `h._run_script`, budget attrs) | module + attrs | `from …_helpers import script_runner as h` |

Two more files mention `_cycle_helpers` in **docstrings/comments only** (no import — no repoint
needed, but update the prose in Phase 8 for accuracy):
`tests/pipeline/test_process_tree.py:3`, `tests/build/test_smoke_gate_enforces_contract_tier.py:53`,
and the module docstring of `test_cycle_helpers_tree_kill.py:1,10`.

### 2.2 Indirect access via `cycle_runner.<symbol>` — NOT broken by the split

These reach helper symbols through the `cycle_runner` alias block, so the split is transparent
to them (no edit needed at any phase, including final):

```
2×  cycle_runner._retry_scout_with_validation_directive
1×  cycle_runner.notify_required_source_degraded
1×  cycle_runner._write_cycle_quality_report
1×  cycle_runner._run_script
1×  cycle_runner._render_prompt
1×  cycle_runner._render_batch_note_writer_prompt
```
Plus the `MAX_SCOUT_VALIDATION_RETRIES` import in
`test_cycle_runner_scout_correction.py:161` (`from …cycle_runner import MAX_SCOUT_VALIDATION_RETRIES`).

The five `test_cycle_runner_*.py` files the spec names
(`test_cycle_runner{,_directive_injection,_probe,_quality_report,_scout_correction,_source_extraction}.py`)
drive `run_cycle_steps` end-to-end via `_patch_cycle_runner_subprocess` and assert on artifacts
— they exercise the helpers **through behaviour**, which is exactly what makes them the
byte-identical-artifact safety net for FR-005/SC-006.

### 2.3 The budget-guard runtime-attribute coupling (subtle, Phase 2/7)

`cycle_runner._install_budget_run_script_guard` (cycle_runner.py:165-) sets **runtime
attributes** on the helpers module object:
```python
h._run_script_orig = h._run_script   # save original
h._budget_session  = session         # stash session
```
and `test_budget_guard.py:206` reaches these via `_cycle_helpers as h`. After Phase 2 the
`_run_script` object lives in `script_runner`; the shim re-exports it so `h._run_script`
still resolves *during* the split. In Phase 7 the wrap is repointed to set the attrs on
`script_runner`, and in Phase 8 the test's `h` is rebound to `script_runner`. This is the one
place where "set an attribute on the module" rather than "call a function" matters — flagged so
`/tasks` writes the move + repoint as one unit.

---

## 3. Global mutable state inventory (FR-003 / SC-003)

Exactly **two** module-level mutable globals, both `bool`:

| Global | Declared | Read | Written | Reset |
|---|---|---|---|---|
| `_should_abort_current_cycle` | `_cycle_helpers.py:27` | `steps/research.py:110` (`h._should_abort_current_cycle`) | `_cycle_helpers.py:788` (inside `notify_required_source_degraded`, `global` stmt L710) | `cycle_runner.py:246` (`h._… = False`) |
| `_last_note_writer_cap_tripped` | `_cycle_helpers.py:28` | (alias only) | `steps/research.py:120` (`h._last_note_writer_cap_tripped = True`) | `cycle_runner.py:247` |

**Migration surface (3 files, not just the entry point):** `cycle_runner.run_cycle_steps`
(reset → construct state), `steps/research.py` (read+write → `state.*`),
`source_signals.notify_required_source_degraded` (write → `state.should_abort = True`). The
carrier is the existing `CycleContext` (data-model.md) — `run_cycle_steps`'s public signature
does not change, satisfying the CLAUDE.md "never change/monkeypatch `run_cycle_steps`" rule.

`_active_timings` (cycle_runner.py:36, `dict[int, CycleTimings]`) is a global **cache**, not a
per-cycle flag, and is **owned by `cycle_runner`** — it stays there; the guard reaches it via a
new accessor (plan Phase 6). It is out of scope for the `CycleRuntimeState` migration.

---

## 4. Baseline metrics (for SC-001 / SC-004)

- **Fast-loop test count (SC-004 floor)**: `1934` collected (1960 total − 26 e2e deselected),
  via `.venv/bin/python -m pytest -m "not e2e" --co -q`, 2026-06-03.
- **Source file LOC (SC-001 / SC-002 starting point)**: `_cycle_helpers.py` = **1428 LOC**.
- **Largest sibling pipeline file**: `orchestrator.py` (per spec, ~1047 LOC) — out of scope.
- **`cycle_runner.py`**: 435 LOC (will shrink slightly as the alias block is repointed/trimmed).

---

## 5. Decisions captured

1. **Migration vehicle = `cycle_runner`'s existing alias block + a transitional `_cycle_helpers`
   shim.** Both stay stable through Phases 1-7; only Phase 8 touches the 3 direct test imports
   and deletes the shim. (Resolves the spec's "enumerate every test-side import" demand: the
   list is exactly the 3 in §2.1.)
2. **Keep all four `cycle_runner` reach-backs lazy; upgrade only `_active_timings` to an
   accessor.** (Resolves FR-007 with zero new eager edges into `cycle_runner`.)
3. **`CycleRuntimeState` rides on `CycleContext`, not on `run_cycle_steps`'s signature.**
   (Resolves the spec's signature-change risk while honouring the CLAUDE.md rule.)
4. **No new top-level submodule beyond the locked 7.** The ~15 spec-unnamed helpers fold into
   `state` / `scout_correction` / `cosmetic_correction` / `source_signals`; an optional `_io.py`
   sub-leaf is the only escape hatch if a file exceeds 300 LOC (decided at `/tasks` by LOC count).

## NEEDS CLARIFICATION

None. All risks resolved by grep-verified evidence above.
