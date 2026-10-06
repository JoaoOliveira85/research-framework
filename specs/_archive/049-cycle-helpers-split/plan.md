# Implementation Plan: `_cycle_helpers.py` God-Module Split

**Branch**: `049-cycle-helpers-split` | **Spec**: [spec.md](./spec.md)
**Status**: PLANNED 2026-06-03 | **Ship target**: 0.9.0 (Wave 1)

**Input**: Clarified spec (`## Clarifications — Session 2026-06-03`): 7-submodule
decomposition LOCKED, transitional shim deleted in the FINAL PR, `CycleRuntimeState`
migration IN SCOPE. Behaviour-preserving — byte-identical artifacts (FR-005).

> This is a structural refactor. The single most important property is **FR-005 /
> SC-006: byte-identical cycle artifacts before and after**. Every design choice
> below is subordinate to that.

## Technical Context

- **Language**: Python 3.11+ (per `pyproject.toml::requires-python`).
- **Dependencies**: none new. The module uses stdlib + `pyyaml` (already a dep). Principle V upheld.
- **Target file**: `src/research_framework/pipeline/_cycle_helpers.py` — **1428 LOC**
  (the spec's "1354" predates specs 048/050 hot-path additions; the real number is
  larger, which only strengthens the case). 39 module-level names: 37 functions/classes/
  constants + 2 process-global mutable flags.
- **New home**: `src/research_framework/pipeline/_helpers/` (private subpackage).
- **Testing**: `.venv/bin/python -m pytest -m "not e2e"` for the fast loop (per
  MEMORY.md — *not* pyenv base). Baseline collected count: **1934 fast-loop tests**
  (1960 total, 26 e2e deselected) measured 2026-06-03. SC-004 requires ≥ this count.
- **Lint**: `ruff check .` AND `ruff format --check .` — **two separate gates**, both
  zero-baseline (CLAUDE.md). Run both before every PR.
- **Smoke gate**: `./build.sh` (ADR-0007, mandatory, un-skippable) green on every PR (FR-009).
- **Quality harness**: `./build.sh --quality` (spec-022, 3 fixtures, regression diff)
  is the behaviour-preservation safety net — REQUIRED on every PR that moves pipeline code.

### The decisive discovery (drives the whole plan)

`cycle_runner.py` lines **67-106** already re-export **all 39** helper symbols as
module-level aliases (`MAX_SCOUT_VALIDATION_RETRIES = h.MAX_SCOUT_VALIDATION_RETRIES`,
`_run_script = h._run_script`, … `notify_required_source_degraded = h.notify_required_source_degraded`).
Production code in `pipeline/steps/{scout,research,postprocess}.py` reaches helpers via
`from .. import _cycle_helpers as h` then `h.<symbol>`. **Almost every test reaches helpers
through `cycle_runner.<symbol>`, not through `_cycle_helpers` directly** (see research.md
for the full enumeration — this is the spec's named "key risk", and the answer is
*reassuring*: only **3** test files import `_cycle_helpers` by path).

Consequence: the import surface tests depend on is `cycle_runner.*` and `steps/*.h.*`, not
`_cycle_helpers.*`. The migration strategy is therefore: **keep `cycle_runner`'s re-export
block as the stable test-facing surface throughout**, repoint each alias from `h.<x>` to
`_helpers.<submodule>.<x>` PR-by-PR, and only the FINAL PR touches the 3 direct test imports
when the shim is deleted.

## Constitution Check

The refactor is governed by behaviour-preservation, so most principles are *unaffected by
construction*; the relevant ones:

| Principle | Relevance | Verdict |
|---|---|---|
| I — Script-Validated Quality Gates | The SG-005/SG-006 gate logic (`_detect_cosmetic_only_correction`, `_synthetic_mid_batch_empty_sg005`) moves verbatim. Gate semantics unchanged. | ✅ no change |
| III — Test-First (TDD) | Each PR moves code under a test surface that already covers it (FR-006). No behaviour added, so no new tests *required*; a focused unit test MAY be added when a helper becomes isolable (Out of Scope: don't gate on it). | ✅ honoured |
| IV — Agent-Script Separation | Pure internal refactor; no agent/script boundary touched. | ✅ no change |
| V — Offline-First / No new deps | Zero new dependencies. | ✅ |
| X — Vault History is Append-Only Git | The `_quality_report_guard` / `_write_cycle_quality_report` exit-path machinery (spec-025 A6) moves verbatim; the "write report on every exit path" invariant is preserved byte-for-byte. | ✅ no change |
| ADR-0007 (smoke gate) | Every PR green on `./build.sh`. | ✅ gating |
| ADR-0008 (seven-tier pyramid) | No tier shape change; existing tests keep their tier. | ✅ preserved |
| ADR-0010 (foreman) | Opt-in per spec; this spec MAY carry Testing Requirements at `/tasks` time, but FR-005 means most tasks are "move + re-point, suite stays green" — foreman strict-naming applies only to the `CycleRuntimeState` task (the one genuinely new symbol). | ✅ compatible |

**CLAUDE.md hard rule** — *never monkeypatch `run_cycle_steps`*: this plan does not add
any such site. The `CycleRuntimeState` migration changes `run_cycle_steps`'s **internals**
(replaces two `h._flag = False` resets with one state-object construction) but its **public
signature is preserved** (see Phase 7). QW-9 (retire the 10 existing monkeypatch sites)
**follows** this spec — out of scope here.

**Gate result: PASS.** No principle conflict; no Complexity Tracking entry needed.

## Complete function → submodule map (the locked 7, with every orphan resolved)

The spec's Decomposition table names representative functions per submodule but does **not**
enumerate all 39 names. `/plan` resolves every one. **Genuine finding**: ~15 functions
(batch/plan/note-yield helpers) are not named in the spec table. They are *research/DFS
support* helpers, not a distinct concern — assigning them their own module would exceed the
locked 7. They fold into the nearest existing bucket; `script_runner` and `cosmetic_correction`
stay small, so the natural home for the batch/note-yield cluster is a thin extension of
`state.py` (per-cycle I/O) plus `scout_correction.py` (prompt rendering) and
`cosmetic_correction.py` (note-body scanning). No new top-level module is introduced —
the 7-module decomposition stays LOCKED. Final per-file LOC is re-checked in Phase 8 against
SC-001 (≤300 LOC each).

| Submodule | Names (verbatim from source) | Notes |
|---|---|---|
| `_helpers/cycle_state.py` | **`CycleRuntimeState`** (NEW) | replaces `_should_abort_current_cycle` + `_last_note_writer_cap_tripped` globals |
| `_helpers/script_runner.py` | `_subprocess`, `_StepError`, `_hms`, `_heartbeat_interval_s`, `_heartbeat_writer`, `_run_script` | + the `_run_script_orig` / `_budget_session` attribute slots the budget guard sets |
| `_helpers/state.py` | `_state_write`, `QualityReportState`, `_cycle_num_from_dir`, `_vault_dir_from_state`, `_cycle_num_from_state`, `_apply_exit_metadata`, `_merge_research_notes`, `_read_skipped_topics_from_research`, `_discover_new_markdown_files`, `_vault_notes_content_sha1`, `_stamp_lifecycle_cycle`, `_empty_batch_result_for_pace` | the per-cycle JSON/fs I/O cluster; `_vault_notes_content_sha1` is shared by `cosmetic_correction` + `source_signals` (import, don't duplicate) |
| `_helpers/quality_report_guard.py` | `_quality_report_guard`, `_write_cycle_quality_report` | spec-025 A6; reaches `_active_timings` via accessor (see below) |
| `_helpers/scout_correction.py` | `_read_correction_directive_block`, `_archive_applied_directive`, `_render_prompt`, `_render_batch_note_writer_prompt`, `MAX_SCOUT_VALIDATION_RETRIES`, `_retry_scout_with_validation_directive`, `_correction_prompt_text`, `_parse_priority_queue_from_plan_md` | the prompt-render + correction-directive cluster |
| `_helpers/cosmetic_correction.py` | `_FRONTMATTER_DELIM`, `_split_note_frontmatter`, `_snapshot_note_bodies`, `_detect_cosmetic_only_correction`, `_synthetic_mid_batch_empty_sg005` | SG-005/SG-006 gates |
| `_helpers/source_signals.py` | `notify_required_source_degraded`, `_load_yaml_settings`, `_pipeline_int_setting`, `_effective_note_writer_batch_size`, `_max_batches_per_cycle`, `_load_spec_for_scout_gates`, `_cycle_quota_for_gates`, `_unfilled_categories_for_gates`, `_probe_retrieval_enabled`, `_run_probe_retrieval_and_cache` | settings/threshold resolution + probe staging; `notify_required_source_degraded` is the only writer of the abort flag |

> If Phase-8 LOC re-count puts `state.py` or `source_signals.py` over 300, the documented
> escape hatch is a `_helpers/_io.py` private leaf for the pure-fs helpers (`_state_write`,
> `_discover_new_markdown_files`, `_vault_notes_content_sha1`) that several modules share —
> still inside the locked 7-concern decomposition (it would be a sub-leaf, not an 8th concern).
> `/tasks` decides only if the count forces it.

## Phase breakdown — one PR per submodule (FR-009)

Order is chosen so the leaf concerns (zero reach-back) move first and the
signature-touching concern (`CycleRuntimeState`) moves last-but-one, with shim deletion last.
The transitional shim — `_cycle_helpers.py` re-exporting `from ._helpers.<mod> import *` —
keeps imports resolving for the *whole* sequence (FR-002, SC-007). `cycle_runner.py`'s
re-export block is repointed alias-by-alias in the same PR that moves each submodule.

**Per-PR invariant (all phases):** fast suite ≥ 1934; both ruff gates clean; `./build.sh`
+ `./build.sh --quality` green; zero importer edits required outside the moved file +
`cycle_runner.py`'s alias block (SC-007). Each PR is independently revertable.

### Phase 1 — `cycle_state.py` (NEW symbol; no code moves yet)
- Add `_helpers/__init__.py` (empty) + `_helpers/cycle_state.py` with the
  `CycleRuntimeState` dataclass: `should_abort: bool = False`, `note_writer_cap_tripped: bool = False`.
- **No wiring yet** — this PR only introduces the type + its unit test. Globals stay live.
- Foreman: this is the one task with a genuinely new symbol → carries Testing Requirements
  (exact file `tests/pipeline/test_cycle_runtime_state.py`, asserts default-falsy + isolation).

### Phase 2 — `script_runner.py` (leaf: no reach-back into cycle_runner)
- Move `_subprocess`, `_StepError`, `_hms`, `_heartbeat_interval_s`, `_heartbeat_writer`,
  `_run_script` into `_helpers/script_runner.py`.
- `_subprocess()` keeps its **lazy** `from research_framework.pipeline import cycle_runner as _cr`
  (FR-007 — eager import here would cycle: `cycle_runner` → `_helpers.script_runner` → `cycle_runner`).
- The budget guard sets `h._run_script_orig` / `h._budget_session` as module attributes on
  `_cycle_helpers` (cycle_runner.py:168-170). **These attribute slots must resolve on the shim**
  → the shim's `from ._helpers.script_runner import *` re-export makes `h._run_script` the same
  object; the `_run_script_orig`/`_budget_session` *attributes* are set on the shim module object
  at runtime (not moved), so the wrap site is untouched this PR. Repoint
  `cycle_runner._install_budget_run_script_guard` to set the attrs on `script_runner` in Phase 7.
- Repoint the `script_runner`-owned aliases in `cycle_runner.py:67-106` from `h.X` to
  `script_runner.X`. `steps/*.py` keep `h.` (shim still resolves) — untouched until Phase 8.

### Phase 3 — `state.py` (leaf + shared `_vault_notes_content_sha1`)
- Move the per-cycle I/O cluster (12 names in the map). `_state_write` uses `atomic_write`
  (already a sibling import — no cycle).
- `cosmetic_correction` and `source_signals` will import `_vault_notes_content_sha1` from here
  in their phases; surface it as a normal within-package import.

### Phase 4 — `cosmetic_correction.py`
- Move `_FRONTMATTER_DELIM`, `_split_note_frontmatter`, `_snapshot_note_bodies`,
  `_detect_cosmetic_only_correction`, `_synthetic_mid_batch_empty_sg005`.
- Imports `GateResult` from `.gates` (sibling, no cycle).

### Phase 5 — `scout_correction.py`
- Move the prompt-render + correction-directive cluster (8 names).
- `_retry_scout_with_validation_directive` lazy-imports `correction.build_directive` +
  `gates.GateResult` — keep lazy (matches today; avoids `correction` ↔ pipeline cycle risk).
- Calls `_run_script` → import from `.script_runner` (Phase 2 must precede — it does).

### Phase 6 — `source_signals.py` + `quality_report_guard.py`
- **`source_signals.py`**: move the 10 settings/threshold/probe names.
  `notify_required_source_degraded` is the **sole writer** of the abort flag (line 788) —
  keep the global write *in this PR* and flip it to `CycleRuntimeState` atomically in Phase 7
  (recommended in `/tasks` so the flag migration is one self-contained diff).
  `_run_probe_retrieval_and_cache` lazy-imports `plan_narrator` + `probes` — keep lazy.
- **`quality_report_guard.py`**: move `_quality_report_guard`, `_write_cycle_quality_report`.
  Both reach `cycle_runner._active_timings` and `cycle_runner._write_cycle_quality_report`
  **lazily** today (lines 617, 647). **Spec-028 interaction (spec risk #4)**: `_active_timings`
  is a `dict[int, CycleTimings]` owned by `cycle_runner.py:36`. Do **not** move the cache.
  Replace the two lazy `_cr._active_timings.{get,pop}` calls with a stable accessor on
  `cycle_runner` — add `cycle_runner.pop_active_timing(cycle_num)` /
  `peek_active_timing(cycle_num)` (thin, lazy-called) so the guard never reaches a raw global.
  The `_quality_report_guard` `finally` block already routes through
  `cycle_runner._write_cycle_quality_report` by design (A6 single-patch-point) — preserve that.

### Phase 7 — `CycleRuntimeState` wiring (FR-003; the highest-risk PR)
- Construct `state = CycleRuntimeState()` at the top of `run_cycle_steps`, replacing the two
  `h._should_abort_current_cycle = False` / `h._last_note_writer_cap_tripped = False` resets
  (cycle_runner.py:246-247).
- **Thread the state object** to the two read/write sites in `steps/research.py`:
  - line 110 `if h._should_abort_current_cycle:` → `if state.should_abort:`
  - line 120 `h._last_note_writer_cap_tripped = True` → `state.note_writer_cap_tripped = True`
  - `run_research(...)` already receives a `CycleContext` (see data-model.md) — add
    `runtime_state` to `CycleContext` and pass it through. **`CycleContext` is the carrier; the
    `run_cycle_steps` public signature is unchanged** (Constitution/CLAUDE.md rule honoured).
- Rewrite `notify_required_source_degraded` (in `source_signals.py`) to accept the state object
  and set `state.should_abort = True` instead of `global _should_abort_current_cycle`. Verify
  and update its call site (orchestrator / source bridge) in `/tasks` to pass the cycle's state.
- Repoint the budget-guard attribute slots from the shim to `script_runner`.
- Delete the two globals and their two `cycle_runner.py` aliases.
- **SC-003 check**: `grep -rnE "^_[a-z_]+(: [a-zA-Z]+)? = (False|True|\{\}|\[\])$" src/research_framework/pipeline/_helpers/`
  returns **zero** module-level mutable globals.

### Phase 8 — delete the shim (FR-002 final PR; SC-002 end state)
- Repoint the 3 direct test imports (research.md enumerates them):
  - `tests/pipeline/test_stamp_lifecycle_cycle.py:15` →
    `from research_framework.pipeline._helpers.state import _stamp_lifecycle_cycle`
  - `tests/pipeline/test_cycle_helpers_tree_kill.py:26` →
    `from research_framework.pipeline._helpers.script_runner import _run_script`
  - `tests/pipeline/test_budget_guard.py:206` →
    `from research_framework.pipeline._helpers import script_runner as h`
    (it accesses `h._run_script` + the budget attrs — point at `script_runner`).
- Repoint `steps/{scout,research,postprocess}.py` from `from .. import _cycle_helpers as h`
  to explicit per-submodule imports (the `h.` prefix is replaced by the owning submodule alias).
- Repoint `cycle_runner.py`'s alias block to import each name from its submodule (the block
  may shrink to a handful of genuinely-re-exported test-facing names, or vanish).
- **Delete `src/research_framework/pipeline/_cycle_helpers.py`.**
- Update the stale **doc-comment** references (not imports) to `_cycle_helpers.py` in
  `quality_report.py:422`, `process_tree.py:22`, `test_smoke_gate_enforces_contract_tier.py:53`,
  `test_process_tree.py:3`, `test_cycle_helpers_tree_kill.py:1` — comment text only, no behaviour.
- LOC re-count: assert every `_helpers/*.py` ≤300 (SC-001); if any over, apply the `_io.py`
  escape hatch from the map note.
- **CHANGELOG** entry under `[Unreleased]` (FR-008): new private import paths +
  `_cycle_helpers.py` removed (no deprecation window; private module, no external consumers).

## Test approach (FR-005 / FR-006 / SC-006)

- **Behaviour-preservation is verified by the existing suite + the spec-022 harness, not by
  new tests.** Run `.venv/bin/python -m pytest -m "not e2e"` after every phase; the count must
  stay ≥ 1934 and no test may need editing for import resolution until Phase 8 (the shim
  guarantees this — SC-007).
- **Byte-identical artifacts (SC-006)**: validated by `./build.sh --quality` (3 fixtures,
  regression diff vs committed baselines) on every PR + a tier-5/6 e2e fixture cycle. See
  quickstart.md for the manual pre/post diff recipe.
- **The one new test**: `tests/pipeline/test_cycle_runtime_state.py` for `CycleRuntimeState`
  (Phase 1) — defaults falsy, two instances are independent (the isolation property US3 wants).
- **No `run_cycle_steps` monkeypatch added** (CLAUDE.md). The Phase-7 state threading rides on
  the existing `CycleContext`, which is already passed explicitly — no new patch seam.

## Risks carried from spec → resolution

| Spec risk | Resolution in this plan |
|---|---|
| Test-side private imports | Enumerated in research.md: **only 3** files import `_cycle_helpers` by path; the rest go through `cycle_runner.*`. Shim absorbs all of it until Phase 8. |
| Process-global migration (signature) | `run_cycle_steps` public signature **unchanged**; state rides on `CycleContext`. Phase 7, isolated PR. |
| Cyclic imports (FR-007) | All current lazy reach-backs into `cycle_runner` (lines 32, 617, 647) stay lazy. New cross-submodule imports are leaf→leaf (no cycle). Verified topology in research.md. |
| Spec-028 `_active_timings` | Cache stays in `cycle_runner.py`; guard reaches it via a new thin accessor, never a raw global. |

## NEEDS CLARIFICATION

None. The clarified spec + the import-topology analysis resolve every open question. The
one judgement call surfaced (`/tasks`-time decision on whether `state.py` / `source_signals.py`
need the `_io.py` sub-leaf to stay ≤300 LOC) is a mechanical LOC check, not a design unknown.
