# Implementation Plan: Pipeline Reliability Hardening

**Branch**: `032-pipeline-reliability` | **Date**: 2026-06-03 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/032-pipeline-reliability/spec.md` (Clarified 2026-06-03)

## Summary

Spec 032 hardens the legacy `extract.py` raw-data processor against three
production failure modes observed on the 2026-05-13 `/pipeline full` run on
`~/Documents/feeds-vault`, and closes the codebase's only Principle-IV exception.

The work splits cleanly into **one rc1-gating migration** and **three
transitional bug-fix user stories**:

- **rc1 GATE (FR-007 / US4) — migrate `extract.py` to `agent_call.dispatch()`.**
  `processors/extract.py` is the single file the LLM-dispatch guard
  (`tests/_helpers/test_llm_dispatch_guard.py`) explicitly excludes
  (`_SCAN_SKIP_REL = {"processors/extract.py"}`) because it shells
  `subprocess.run(["claude", ...])` directly. The migration routes its two
  call sites through `agent_call.dispatch()` — using the *exact* dynamic-import
  seam `plan_narrator._bootstrap_scripts_agent_call` already established — then
  **removes the guard exclusion and inverts the guard's boundary test** so the
  allowlist stays EMPTY (a hard CLAUDE.md invariant). No constitutional
  exception is added; spec 028's telemetry (shipped 0.4.0) makes the
  principled choice now also the tractable one.

- **Transitional legacy (US1/US2/US3 — P3 per Clarifications Q5).** A usage
  audit (Phase 0, **complete** — see research.md) confirms NO target vault
  exercises `extract.py`'s raw_data path: the three live runs use
  `./vault research` → `cycle_runner.run_cycle_steps` → spec-020 subprocess
  modules, never the `runner.py` PHASES chain that `./vault pipeline` drives.
  US1-3 are therefore demoted to P3 and are NOT rc1-blocking. They ship as
  bug-fix hardening on top of the migrated dispatch surface:
  - **US1 / FR-001-002** — sandbox-failure detection: stderr auth-failure
    signature (primary) + time-based fallback (≥3 extractions each <1s AND
    failed) + `RV_`-prefixed override env var → **hard-exit non-zero, ZERO
    stubs written** (fail-closed; explicitly NOT 048-v2's WARN-on-silence).
  - **US2 / FR-003-004** — `extraction-failed` stubs auto-retry on resume
    (configurable max-attempts, default 3); exhaustion →
    `extraction-failed-permanent`; `--force` re-attempts permanent stubs.
  - **US3 / FR-005-006** — Sonnet synthesis timeout ladder:
    `--filter <today>` → chunked batches → fail, retry budget configurable;
    chunked output equivalent to a full-bundle run (no data loss).

**Technical approach**: incremental, test-first. Phase 1 (migration) is the
gate and lands first as a focused commit. Phases 2-4 (US1, US2, US3) are
independent and stack on the migrated surface. No new runtime dependencies
(Principle V). Stdlib + the existing `agent_call.dispatch()` seam only.

## Technical Context

**Language/Version**: Python 3.11+ (per `pyproject.toml` `requires-python`)
**Primary Dependencies**: stdlib + PyYAML (already a dep) + the
`scripts/agent_call.py` `dispatch()` seam (loaded via `importlib`, not a
package import — `src/` cannot import `scripts/`). **No new runtime deps.**
**Storage**: filesystem under vault root. Touched artifacts:
`<vault>/_pipeline/extracted/{excerpts,extracted}/<source_type>/*.md`
(extraction outputs + stubs), `<vault>/_pipeline/extracted/context-tree.md`
(Sonnet synthesis), new (US3) chunked-synthesis manifest at
`<vault>/_pipeline/extracted/context-tree-chunks.json`.
**Testing**: pytest, seven-tier pyramid (ADR-0008). Existing
`tests/processors/test_extract.py` mocks the LLM via
`monkeypatch(extract, "_call_claude", ...)`; the migration repoints this seam
to a mockable `dispatch` callable. The dispatch-guard test
(`tests/_helpers/test_llm_dispatch_guard.py`) is itself updated and is a
required gate.
**Target Platform**: macOS (primary) + Linux (CI; spec 009 pending). The
sandbox-failure signature (FR-001) is the macOS-keychain case observed in
production; cross-CLI sandbox detection is explicitly Out of Scope (spec).
**Project Type**: single-project CLI / library (research-framework package).
**Performance Goals**: SC-001 — detect + hard-exit within 30s of first failed
extraction (vs. today's minutes-of-silent-stub-writing).
**Constraints**: offline-capable (Principle V); fail-closed on env-broken
dispatch (Q3); the dispatch-guard allowlist MUST remain EMPTY.
**Scale/Scope**: ~777-LOC `extract.py` + the guard test + ~3 focused test
modules. The 2026-05-13 incident bundle was 176 sources (US3 sizing input).

## Constitution Check

*GATE: passed before Phase 0 research; re-checked after design.*

| Principle | Relevance | Verdict |
|-----------|-----------|---------|
| **IV — Agent-Script Separation (CENTRAL)** | The migration's whole point. `extract.py` is an agent-dispatch site living in `src/`; routing it through `agent_call.dispatch()` makes it obey the same separation every other dispatch site obeys. Removing the guard exclusion *strengthens* the invariant — the guard now fires on any future bypass in `extract.py`. | **PASS — net improvement.** The one standing exception is eliminated; allowlist stays EMPTY. |
| **III — Test-First (NON-NEGOTIABLE)** | Each FR ships with tests written alongside. Migration: dispatch-guard boundary test inverted + a unit test asserting `extract` calls `dispatch` (not `subprocess`). US1-3: detection / retry / fallback unit tests. `--live-llm` opt-in for any real-CLI test. | **PASS.** |
| **V — Offline-First, No External Persistence** | No new runtime dep. `dispatch()` is the same stdlib+PyYAML surface `extract.py` already reaches indirectly. | **PASS.** |
| **VIII — No Placeholders / Stub-as-Fuel** | FR-001 deliberately writes **ZERO** stubs on env-broken dispatch (fail-closed). This is consistent: a sandbox-broken environment is not "research found a gap" (fuel) — it is a broken tool, and a broken tool must fail loudly, not seed the loop with corrupt stubs. The `extraction-failed-permanent` marker (FR-004) is a *transient-vs-permanent* distinction within the existing stub schema, not a new placeholder class. | **PASS.** |
| **I — Script-Validated Quality Gates** | The dispatch-guard test is a script gate; it remains the enforcement mechanism for Principle IV after the exclusion is removed. | **PASS.** |
| **Ask-First: "changing validation exit codes (0/1/2)"** | FR-001 introduces a hard non-zero exit on detected sandbox failure. `extract.py`'s CLI already returns 1 on errors; the new path returns non-zero (1) on detected-sandbox before any work. This is *additive* (a new fail-fast branch), not a redefinition of existing 0/1/2 semantics. | **PASS — additive, noted for `/speckit.tasks`.** |

**No Complexity Tracking entries** — no constitutional violations to justify.

## Project Structure

### Documentation (this feature)

```text
specs/032-pipeline-reliability/
├── spec.md              # Clarified 2026-06-03
├── plan.md              # This file
├── research.md          # Phase 0: usage audit + sandbox-failure signature
├── quickstart.md        # Phase 1: how to exercise + verify each FR
├── checklists/
│   └── requirements.md  # pre-existing
└── tasks.md             # /speckit.tasks output — NOT created here
```

No `data-model.md` and no `contracts/` — see "Why no data-model / contracts"
below.

### Source Code (repository root)

```text
src/research_framework/
├── processors/
│   ├── extract.py                 # MIGRATED (FR-007) + US1/US2/US3 logic
│   └── _common.py                 # unchanged (excerpt/raw/extracted dir helpers)
└── pipeline/
    ├── plan_narrator.py           # source of the _bootstrap_scripts_agent_call seam (reference only)
    └── runner.py                  # _drive_extract — legacy /pipeline path (unchanged behaviour)

scripts/
└── agent_call.py                  # dispatch() — the migration target (unchanged)

tests/
├── _helpers/
│   ├── test_llm_dispatch_guard.py # UPDATED — remove extract.py exclusion + invert boundary test (rc1 gate)
│   └── llm_dispatch_allowlist.yaml# stays EMPTY (invariant)
└── processors/
    └── test_extract.py            # UPDATED — repoint LLM mock seam to dispatch; new US1/US2/US3 tests
```

**Structure Decision**: Single-project. All implementation lands in the
existing `src/research_framework/processors/extract.py`; the only cross-cutting
edit is the guard test + its assertion that `extract.py` is no longer excluded.
The dynamic-import dispatch seam is reused verbatim from `plan_narrator.py` (a
proven pattern that the fake-agent shim already intercepts, preserving e2e
Principle-IV interception).

### Why no data-model / contracts

- **No `data-model.md`**: the only schema change is one new stub status value
  (`extraction-failed-permanent`) layered onto the *existing*
  extraction-stub frontmatter, plus a small US3 chunk-manifest JSON. Both are
  described inline in the spec's Key Entities. There is no new entity graph
  to model.
- **No `contracts/`**: the migration *consumes* an existing contract
  (`specs/028-dispatch-telemetry/contracts/dispatch-protocol.contract.md` —
  the `dispatch()` protocol) rather than defining a new one. No new
  cross-process JSON contract is introduced. (The US3 chunk manifest is an
  internal sidecar, not an inter-process contract.)

## Phases

### Phase 0 — Usage audit + signature probe (COMPLETE; see research.md)

The two planning unknowns the spec flagged are resolved in research.md:

1. **Usage audit (Clarifications Q5 — gating).** **Result: NO target vault
   exercises `extract.py`.** Reached only by `./vault pipeline {full,extract}`
   (legacy `runner.py` PHASES = `[collect, extract, scout, ...]`). The three
   live runs use `./vault research` → `cycle_runner.run_cycle_steps` →
   spec-020 modules. **⇒ US1-3 drop to P3; only the FR-007 migration is
   rc1-blocking.**
2. **Sandbox-failure stderr signature.** Documented in research.md with the
   primary signature, the time-based fallback rule, and the `RV_` override.
   One genuine unknown (exact stderr string stability across CLI versions)
   remains and drives the layered-detection design — see NEEDS CLARIFICATION
   at the foot of this plan.

### Phase 1 — Migrate `extract.py` → `agent_call.dispatch()` (rc1 GATE, FR-007 / US4)

**Lands first, as a focused commit.** Test-first.

1. **Test (red):** Update `tests/_helpers/test_llm_dispatch_guard.py`:
   - Remove `"processors/extract.py"` from `_SCAN_SKIP_REL`.
   - Invert `test_scan_root_excludes_contract_paths`: it currently *asserts*
     `extract.py` still contains a claude subprocess and is skipped (lines
     257-267). Rewrite so it asserts (a) `extract.py` is no longer in
     `_SCAN_SKIP_REL`, and (b) `extract.py` surfaces ZERO violations from
     `scan_for_violations` (proving the migration removed the direct call).
   - Update the module docstring (lines 1-13) — drop the
     `processors/extract.py` "explicit skip" line.
   This goes red against current `extract.py` (still has the direct call).
2. **Implementation (green):** In `processors/extract.py`:
   - Replace `_default_call_claude`'s `subprocess.run(["claude", ...])` body
     with a call through the dynamically-imported `agent_call.dispatch()`,
     reusing the `plan_narrator._bootstrap_scripts_agent_call(vault_dir=...)`
     pattern (factor a shared `_bootstrap_agent_call` helper or import the
     existing one). Map: `model` → dispatch `tier`/executor via the stage's
     settings; `system_prompt` + `user_prompt` → the single `prompt` arg
     (concatenated, matching how stdin prompts are framed); read
     `AgentCallResult.stdout` for the body and `.stderr`/`.exit_code` for
     error handling; map `.tokens_in/.tokens_out/.cost_usd` into the existing
     `usage` dict that `_extract_one`/`_synthesize_context_tree` consume.
   - Drop the now-unused `import subprocess` and the `claude`-not-on-PATH
     pre-check in `_cli_main` (dispatch resolves the binary).
   - Keep `_call_claude = _default_call_claude` module-level seam so existing
     tests' mock point still works (now it mocks a dispatch-backed callable).
3. **Test (green):** Update `tests/processors/test_extract.py` — its mock
   factory now substitutes a `dispatch`-shaped return (or keeps mocking
   `_call_claude` at the same seam). Add a unit test asserting `extract` makes
   NO direct `subprocess.run(["claude", ...])` call (e.g. patch `subprocess`
   and assert un-called, or assert the dispatch seam is hit).
4. **Gate:** `.venv/bin/python -m pytest tests/_helpers/test_llm_dispatch_guard.py
   tests/processors/test_extract.py` green; `ruff check .` + `ruff format
   --check .` clean. **This is the rc1 gate.**

### Phase 2 — US1: sandbox detection, fail-closed (FR-001, FR-002; P3)

Test-first. On top of the migrated dispatch surface.

1. **Detection helper** in `extract.py`: a small classifier fed the
   `AgentCallResult` (exit_code + stderr) of each extraction:
   - **Primary:** stderr matches the auth-failure signature (research.md).
   - **Fallback:** track first-N extractions; if the first ≥3 each completed
     <1s wall AND failed → declare sandbox.
   - **Override:** `RV_DISABLE_SANDBOX_DETECT` (exact name a `/speckit.tasks`
     concern; `RV_`-prefixed per Q2) suppresses both, for documented mis-fire.
2. **Fail-closed policy:** on detection, **hard-exit non-zero, write ZERO
   stubs** — the detection must fire BEFORE `_write_extraction`'s
   `status=extraction-failed` branch runs, and must abort the
   `ThreadPoolExecutor` fan-out without persisting any partial output.
   Actionable message per FR-002: (a) what was detected, (b) the
   `dangerouslyDisableSandbox: true` / autonomous-mode-pre-auth workaround,
   (c) a doc link.
3. **Tests:** simulated-sandbox dispatch (stderr signature) → exit non-zero,
   zero files on disk; time-based fallback path; `RV_` override restores
   normal behaviour (SC-005); non-sandboxed run unchanged (Acceptance #2).

### Phase 3 — US2: stub auto-retry on resume (FR-003, FR-004; P3)

Test-first.

1. `_find_extraction_targets` currently skips any existing `out_path` unless
   `--force`. Extend it to *also* re-queue targets whose existing extraction
   has `status: extraction-failed` (parse frontmatter), up to a configurable
   `max_retry_attempts` (default 3; via `processor_config`). Track attempt
   count in stub frontmatter.
2. On exhaustion, rewrite stub `status` → `extraction-failed-permanent`.
   `--force` re-attempts even permanent stubs.
3. **Tests:** 3 pre-existing `extraction-failed` stubs auto-retried with no
   flags (SC-002); exhaustion → `permanent`; `--force` re-attempts permanent.

### Phase 4 — US3: Sonnet synthesis timeout ladder (FR-005, FR-006; P3)

Test-first.

1. In `_synthesize_context_tree`, catch the dispatch timeout
   (`AgentCallResult.exit_code` timeout sentinel / `stderr=="timed out"` — see
   dispatch's timeout return at agent_call.py:970) and walk the ladder:
   full bundle → `--filter <today>` (date-scoped re-gather) → chunked batches
   → fail. Retry budget configurable via `processor_config`.
2. Chunked path writes a chunk manifest
   (`context-tree-chunks.json`) recording attempted/succeeded chunks and
   reconciles into the same `context-tree.md` so output is equivalent to a
   successful full run (FR-006, SC-003). Final failure lists what was attempted
   + what's missing (Acceptance #3).
3. **Tests:** synthetic over-budget bundle → auto-fallback completes; chunked
   output equivalence; all-retries-exhausted failure message content.

### Phase 5 — Docs (SC-005)

- ADR or `docs/` page documenting the sandbox-detection heuristic: what
  triggers it, the layered primary/fallback/override design, and how to
  disable it (`RV_` env var). Update `extract.py`'s module docstring to
  declare its sandbox-incompat (FR-008). (Doc-sync of ROADMAP/CHANGELOG/
  CLAUDE.md is a ship-time concern per the doc discipline checklist, not part
  of this plan's scope.)

## Test Approach (summary)

- **Lowest tier that catches the bug** (ADR-0008). Most logic is pure unit
  (detection classifier, target re-queue, ladder state machine) → Tier 1/2.
- **The dispatch-guard test is the rc1 gate** and a Tier-2 static lint; it is
  updated in Phase 1 and must stay green with an EMPTY allowlist.
- **LLM mocking via the existing `_call_claude` seam** (now dispatch-backed) —
  no real CLI in the fast loop. Any real-CLI test is `@pytest.mark.live_llm`
  (skipped by default; `--live-llm` opt-in).
- **No `run_cycle_steps` monkeypatch** (CLAUDE.md ban). `extract.py` is off
  the cycle-runner path entirely, so this does not arise.
- **Fail-fast verification:** `.venv/bin/python -m pytest` (per MEMORY — use
  `.venv`, not pyenv) + `ruff check .` + `ruff format --check .`.

## Complexity Tracking

No entries — Constitution Check passed with no violations to justify.

## NEEDS CLARIFICATION

1. **Exact sandbox-failure stderr string + its cross-version stability**
   (the spec's own Assumption + Edge Case). The layered design (signature →
   time-fallback → override) is specifically chosen to be robust to this
   unknown, but the *primary* signature string needs a one-off live probe in a
   real sandboxed `claude -p` to pin (or confirm `dispatch()` surfaces a
   stable `exit_code`/`stderr` we can match). Resolved sufficiently for
   planning; flagged for `/speckit.tasks` to schedule the probe task.
2. **`RV_` override env var exact name** (e.g. `RV_DISABLE_SANDBOX_DETECT`) —
   naming is a `/speckit.tasks`-level decision; the `RV_` prefix is fixed by
   Clarifications Q2.

No other unknowns. The rc1 migration path is fully grounded (the dispatch
seam, the guard test, and the call sites are all read and mapped above).
