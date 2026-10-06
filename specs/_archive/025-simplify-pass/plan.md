# Implementation Plan: Code Simplification Pass (Tier A + B Refactor)

**Branch**: `025-simplify-pass` (worktree:
`~/src/research-framework-025/`) | **Date**:
2026-05-21 | **Spec**: `specs/_archive/025-simplify-pass/spec.md`
**Input**: Feature specification at
`specs/_archive/025-simplify-pass/spec.md` (status: Clarified
2026-05-21; 9 decisions locked in Clarifications block).

## Summary

Spec 025 is a **behaviour-preserving refactor pass** across the
research-framework codebase. It bundles 9 separate refactor items
into two tiers with different ship gates:

- **Tier A (pre-022-v1 ship)**: route the two known LLM dispatch
  bypasses (`pipeline/plan_narrator.py` and the probe-retrieval
  block in `pipeline/cycle_runner.py`) through `scripts/agent_call.py`
  (US1 A1, US2 A2); auto-detect resume cycle (US4 A4); sync stale
  docs about `run_cycle.sh` / QW-2 / `build.sh` (US5 A5); add the
  quality-report context-manager guard so `_write_cycle_quality_report`
  runs exactly once per `run_cycle_steps` invocation regardless of
  exit path (US3 A6, replacing 32 scattered call sites).
- **Tier B (post-022-v1 ship)**: extract `cycle_runner.py` steps
  into `pipeline/steps/<step>.py` modules (US6 B3, in a long-lived
  sub-branch `025-b3-step-extraction`); unify the 12+ frontmatter
  parsers into one canonical `vault/frontmatter.py` (US7 B4); split
  the 1.1k-line `cli.py` into a `cli/` subpackage (US8 B5); unify
  settings loaders into `pipeline/settings.py` (US9 B7).

The single top-level success criterion (US10 meta, SC-003) is that
the LLM dispatch guard allowlist — owned by spec 024 — contains
**zero entries** after Tier A ships. This proves A1 + A2 fully
removed the two known production bypasses.

**Technical approach** (from research.md design decisions D1–D9):

1. A1/A2 reuse `scripts/agent_call.py`'s existing stage-tag dispatch
   mechanism with new stage names `plan_narrator` and `probe_retrieval`.
   No schema changes to the cost-sidecar JSON contract; only new
   stage values added to the enumeration.
2. A6 wraps `run_cycle_steps`' body in a `contextlib.contextmanager`
   helper (`_quality_report_guard`) whose `__exit__` always writes
   the report exactly once. Existing call sites collapse to a
   single yield point plus at most one optional mid-cycle progress
   log call.
3. A4 reads `_pipeline/state.json::in_progress_cycle` written by
   the existing cycle-start hook; resume with `--cycle` flag still
   wins; multiple-in-progress is a hard error.
4. B3 (long-lived sub-branch per Q3a) extracts three step modules
   (`scout.py`, `research.py`, `postprocess.py`) with a stable
   functional signature `run_<step>(ctx: CycleContext) -> StepResult`.
   `cycle_runner.py` becomes a thin orchestrator.
5. B4/B7 introduce canonical parsers as pure functions with explicit
   typed return values; existing call sites migrate in batches,
   holdouts carry inline comments.
6. B5 reorganises `cli.py` into a `cli/<group>.py` subpackage; the
   `build_parser()` public function is re-exported unchanged from
   `cli/__init__.py`.

The refactor introduces **zero new runtime dependencies** (Principle
V), **zero new external surface** (FR-015), and **at most one new
internal package** (`pipeline/steps/`). Every Tier A item is
covered by tests written before or alongside the change (Principle
III); every Tier B item additionally clears `./build.sh --quality`
post-022-v1 (FR-016 + SC-014).

## Technical Context

**Language/Version**: Python 3.11+ (per `pyproject.toml`'s
`requires-python = ">=3.11"` and constitution Technology Constraints).

**Primary Dependencies**: Existing only — `jinja2 ≥ 3.1`,
`pyyaml ≥ 6.0`, `sqlite3` (stdlib). **No new runtime dependencies**
— Principle V is non-negotiable. Test-time dependencies (`pytest`,
`ruff`) are already declared.

**Storage**: Filesystem under vault root — unchanged. New
artifacts:
- A1/A2: cost-sidecar JSON written by `scripts/agent_call.py`
  under `_pipeline/cycles/cycle-NNN/agent-calls/<stage>.json`
  with new stage values `plan_narrator` and `probe_retrieval`.
- A4: relies on existing `_pipeline/state.json` (added in a prior
  cycle-runner change; if absent, A4's implementation adds the
  write-side).
- A6: existing `_pipeline/cycles/cycle-NNN-quality-report.json`
  contract preserved; the wrapper change is internal.
- B3/B4/B5/B7: zero filesystem changes — pure code reshape.

**Testing**: pytest. The current sweep is 1156 tests across
unit/integration/e2e. Spec 025 PRs must keep that sweep green
(SC-001) plus the smoke gate (SC-002, `./build.sh`). Tier B PRs
additionally must clear `./build.sh --quality` once spec 022 v1
ships (SC-014). New tests required per user story:
- US1 A1: `tests/pipeline/test_plan_narrator.py` — assert
  subprocess identity (`claude` vs `codex` per env), cost-sidecar
  JSON content.
- US2 A2: `tests/pipeline/test_cycle_runner_probe.py` — assert
  same for probe-retrieval.
- US3 A6: `tests/pipeline/test_cycle_runner_quality_report.py` —
  parametrised across happy/sad/exception/interrupt exit paths.
- US4 A4: `tests/cli/test_research_resume.py` — auto-detect,
  override, multiple-in-progress error.
- US5 A5: `tests/docs/test_doc_sync.py` — grep-based assertion
  for zero `run_cycle.sh` references and accurate QW-2 text.
- US6 B3: `tests/pipeline/steps/test_<step>.py` per module +
  preserve all existing `tests/pipeline/test_cycle_runner.py`
  tests unchanged.
- US7 B4: `tests/vault/test_frontmatter.py` — canonical parser
  edge cases (empty, malformed, multi-doc, nested keys).
- US8 B5: `tests/cli/test_build_parser_stable.py` — golden-file
  `./vault --help` byte-identical check + import-stability test.
- US9 B7: `tests/pipeline/test_settings_loader.py` — invalid-input
  consistency.
- US10 meta: `tests/_helpers/test_llm_dispatch_allowlist.py` —
  assert allowlist file is empty after spec ships (the test
  itself ships with spec 024 US1; spec 025 just makes the
  assertion pass).

**Target Platform**: macOS (developer) + Linux (CI
`ubuntu-latest` per spec 009 Linux validation). No Windows support
per ROADMAP queue #2. The refactor introduces no platform-specific
code; existing platform-agnostic stdlib usage is preserved.

**Project Type**: CLI tool refactor. No new web service, library
artifact, or external API. The user-facing surface (`./vault
<command>`, settings.yaml keys, `_pipeline/` artifact format) is
**byte-identical** before/after — SC-009 verifies `./vault --help`
specifically. The Python public API (`build_parser`,
`run_cycle_steps`) is also preserved.

**Performance Goals**: No performance regression target — this
is a refactor, not an optimisation. Cycle execution time MUST be
within ±5% of pre-refactor baseline (informal, measured per-PR by
the reviewer running `time ./vault research --dry-run` against the
`tech-lite` fixture). For Tier B PRs post-022-v1, the regression
gate is per-metric (whatever the 022 harness reports). For Tier A
PRs pre-022-v1, no formal performance gate — informal smoke only.

**Constraints**:
- Behaviour-preserving (FR-015): `./vault --help`, `build_parser()`
  export, `run_cycle_steps` signature, settings YAML keys all
  unchanged.
- No new runtime deps (FR-014, Principle V).
- A1/A2 must produce valid cost-sidecar JSON for every routed call
  (FR-003) — schema unchanged from existing `agent_call.py` output.
- A6 must guarantee `_write_cycle_quality_report` runs exactly once
  per `run_cycle_steps` invocation regardless of exit path
  (FR-006) — at most 2 call sites after refactor (FR-007).
- B3 must reduce `pipeline/cycle_runner.py` to **< 1500 lines**
  (FR-008, SC-004) from the current 2,195.
- B5 must reduce `cli.py` to **< 200 lines** (FR-011, SC-005).
- B4 must migrate **≥ 8 of 12+** frontmatter parser call sites
  (FR-010, SC-007); B7 must migrate **≥ 6** settings loader call
  sites (FR-012, SC-008).
- Tier B PRs cannot merge until 022 v1 ships and produces
  baselines (FR-016 + R3 carve-out: Tier A is exempt and ships
  pre-022-v1).
- B3 sub-branch lifetime ≤ 5 days target, hard escalation at 7
  days (SC-015).

**Scale/Scope**:
- **Tier A** touches: `pipeline/plan_narrator.py` (~150 LOC), the
  probe-retrieval block in `pipeline/cycle_runner.py` (~115 LOC of
  the 2,195 total), `cli.py` resume-handling (~50 LOC), three docs
  (`constitution.md`, `docs/ROADMAP.md`, `build.sh`).
- **Tier B** touches: `pipeline/cycle_runner.py` (-~700 LOC, +3
  new modules of ~200–400 LOC each); `cli.py` (1,100 LOC → split
  into `cli/__init__.py` + 6–8 group modules); creates
  `vault/frontmatter.py` (~80 LOC canonical parser) and migrates
  ≥ 8 call sites; creates `pipeline/settings.py` (~100 LOC
  canonical loader) and migrates ≥ 6 call sites.
- **Test surface**: ~12 new test files / ~50 new test functions;
  every existing `tests/pipeline/test_cycle_runner.py` test
  preserved unchanged (proof of behaviour preservation).
- **Calendar (per `docs/SIMPLIFY-PASS.md` § 7 + Q3b MVP fallback)**:
  Tier A target = 2–3 days, ships pre-022-v1. Tier B target =
  3–4 days, ships post-022-v1 (with B3 in long-lived sub-branch).
  MVP fallback if 2026-05-29 slip review activates = Tier A only.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1
design (clean — no deviations introduced).*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Script-Validated Quality Gates (NON-NEG.) | ✅ | A6 strengthens this principle — `_write_cycle_quality_report` will run exactly once per cycle exit, including exceptions/interrupts, ensuring the quality gate's existence regardless of code path. |
| II. Phase Sequencing (NON-NEG.) | ✅ | Phase 1/2/3 boundaries unchanged. B3 step extraction preserves the BFS → DFS → Repeat model; the new step modules are internal organisation, not phase changes. |
| III. Test-First TDD (NON-NEG.) | ✅ | Every user story ships with new tests (see Testing section above); existing tests preserved unchanged proves behaviour preservation. |
| IV. Agent-Script Separation of Concerns | ✅ | **This is the top-level acceptance criterion** (SC-003). A1/A2 explicitly satisfy Principle IV by routing LLM dispatch through `scripts/agent_call.py` (the script layer); zero allowlist entries after ship proves no agent self-dispatches. |
| V. Offline-First, No External Data Persistence | ✅ | Zero new runtime dependencies (FR-014). All refactors use stdlib + existing deps only. |
| VI. No Duplicate Notes | N/A | Refactor doesn't touch note creation. |
| VII. External Sources Mandatory | N/A | Refactor doesn't touch source policy. |
| VIII. No Placeholders in Deliverables | ✅ | Every refactored module ships with full working implementation. New modules in `pipeline/steps/` are extracted, not stubbed. |
| IX. Vault-First Citation (NON-NEG.) | N/A | Refactor doesn't touch citation logic. |

**Boundary System (`Ask First` items)**:
- "Adding external dependencies" — Confirmed NO (FR-014).
- "Changing the naming convention for vault note files" — Confirmed
  NO (refactor doesn't touch naming).
- "Modifying validation exit codes (0/1/2) or their semantics" —
  Confirmed NO (existing exit codes preserved).
- "Changing the Phase 1/2/3 execution sequence" — Confirmed NO
  (B3 preserves phase boundaries; the new step modules are
  internal organisation within Phase 2).

**No constitutional violations**. No items require justification
in the Complexity Tracking section.

## Project Structure

### Documentation (this feature)

```text
specs/_archive/025-simplify-pass/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output — design decisions D1–D9
├── data-model.md        # Phase 1 output — preserved + new API surfaces
├── quickstart.md        # Phase 1 output — developer onboarding to refactored code
├── contracts/           # Phase 1 output — pinned API contracts
│   ├── llm-dispatch.contract.md          # A1/A2 stage-tag dispatch + cost-sidecar JSON
│   ├── step-module-api.contract.md       # B3 pipeline/steps/<step>.py signatures
│   ├── frontmatter-parser.contract.md    # B4 vault/frontmatter.py canonical parser
│   ├── settings-loader.contract.md       # B7 pipeline/settings.py canonical loader
│   ├── cli-subpackage.contract.md        # B5 cli/<group>.py organisation
│   └── cycle-runner-edit-lock.contract.md # B3 sub-branch coordination protocol
├── spec.md              # Feature spec (Clarified 2026-05-21)
└── tasks.md             # Phase 2 output (NOT created by /speckit.plan — comes from /speckit.tasks)
```

### Source Code (repository root)

The refactor touches existing directories; only `pipeline/steps/`
(B3) and `cli/` (B5) are new packages. Everything else is
in-place edits.

```text
src/research_framework/
├── pipeline/
│   ├── plan_narrator.py            # US1 A1: rewire to scripts/agent_call.py
│   ├── cycle_runner.py             # US2 A2 (probe), US3 A6 (context mgr), US6 B3 (-~700 LOC)
│   ├── steps/                      # NEW (US6 B3) — extracted step modules
│   │   ├── __init__.py             # exports run_scout, run_research, run_postprocess
│   │   ├── scout.py                # ~250 LOC extracted from cycle_runner.py
│   │   ├── research.py             # ~350 LOC extracted
│   │   └── postprocess.py          # ~200 LOC extracted
│   └── settings.py                 # NEW (US9 B7) — canonical load_vault_settings
├── vault/
│   └── frontmatter.py              # NEW (US7 B4) — canonical parse_frontmatter
├── cli/                            # NEW (US8 B5) — replaces cli.py monolith
│   ├── __init__.py                 # re-exports build_parser unchanged
│   ├── research.py                 # ./vault research, --resume (US4 A4 touches resume handler)
│   ├── audit.py                    # ./vault audit
│   ├── vault.py                    # ./vault write, update, onboard, etc.
│   ├── quality.py                  # ./vault quality-baseline-update (spec 022 owns)
│   └── _common.py                  # shared parser helpers
├── cli.py                          # POST-B5: thin entry that re-exports cli/__init__.py
└── (other unchanged directories)

tests/
├── pipeline/
│   ├── test_plan_narrator.py       # US1 A1 (new file or extended)
│   ├── test_cycle_runner_probe.py  # US2 A2 (new file)
│   ├── test_cycle_runner_quality_report.py  # US3 A6 (new file)
│   ├── test_cycle_runner.py        # PRESERVED unchanged (behaviour proof)
│   ├── steps/
│   │   ├── test_scout.py           # US6 B3 (new)
│   │   ├── test_research.py        # US6 B3 (new)
│   │   └── test_postprocess.py     # US6 B3 (new)
│   └── test_settings_loader.py     # US9 B7 (new)
├── cli/
│   ├── test_research_resume.py     # US4 A4 (new)
│   └── test_build_parser_stable.py # US8 B5 — golden-file --help test
├── vault/
│   └── test_frontmatter.py         # US7 B4 (new)
├── docs/
│   └── test_doc_sync.py            # US5 A5 (new — grep assertions)
└── _helpers/
    └── test_llm_dispatch_allowlist.py  # US10 meta — written by spec 024 US1

scripts/
└── agent_call.py                   # UNCHANGED — A1/A2 use existing stage dispatch
```

**Structure Decision**: Single-project Python CLI (Option 1 from
the template). The refactor preserves the existing project layout
(`src/research_framework/` package + `tests/` mirror + `scripts/`
for shell entry points + per-vault validators) and adds two new
internal packages (`pipeline/steps/`, `cli/`). No restructuring of
the project type or test framework.

## Complexity Tracking

The Constitution Check above is clean — no violations. The single
non-default architectural choice captured here for transparency is
the B3 long-lived sub-branch decision (Q3a locked 2026-05-21).

| Choice | Why Needed | Simpler Alternative Rejected Because |
|--------|------------|--------------------------------------|
| B3 long-lived sub-branch `025-b3-step-extraction` (single big PR) | Architect (`docs/SIMPLIFY-PASS.md` § 6) recommended incremental step-by-step PRs to `main`; user chose long-lived branch for revert simplicity (one `git revert` undoes all of B3 vs. three reverts for three step PRs). | Incremental per-step PRs rejected because: (a) intermediate states of `cycle_runner.py` between extractions are awkward to test (the orchestrator has been partially de-monolithised but new step modules don't yet have all their tests); (b) reviewer cognitive load is similar either way (the diff size is the same); (c) revert simplicity matters more given the post-022-v1 quality-gate window is tight. Trade-off accepted with mitigations: cycle-runner edit lock during the window (R1 mitigation 1), weekly rebase cadence (SC-015), 5-day ship target / 7-day escalation (SC-015), by-step PR description for review (R1 mitigation 4). |

No other architectural deviations from defaults. The remaining
items in spec.md Risks & Mitigations (R2 B4/B5/B7 behaviour-
preservation gap, R3 022 v1 ship slip) are operational risks
managed via the FR-016 ship sequencing and the SC-014/SC-015
gates — not architectural choices requiring complexity tracking.
