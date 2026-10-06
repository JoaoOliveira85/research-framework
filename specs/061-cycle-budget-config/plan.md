# Implementation Plan: Cycle-budget configuration consolidation

**Branch**: `061-cycle-budget-config` | **Date**: 2026-06-05 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/061-cycle-budget-config/spec.md`
**Target ship**: **1.0.0rc3** (rc3 hardening wave; gates the remaining reference-vault validation run — see spec SC-003)

## Summary

Collapse the per-cycle budget (and, per Q3, the dollar cap) onto a single
canonical settings key + a last-word CLI flag, remove both from the research-spec
schema, and make every override loud + recorded. The root cause of the
codebase-vault rc1 truncation (`12 cycles asked → 6 run`) is **silent precedence**:
`cli/research_generate.py:106-114` reads `cycles.initial_max` and mutates
`spec.budget.max_cycles`/`spec.max_cycles` with a single bare `print`, while the
generous, typed `pipeline.max_cycles` is never consulted at generate time.

The decisive Phase-0 finding (research.md **D1**): **`pipeline.max_cycles` is
already the typed canonical field** — `pipeline/settings.py:227` reads
`pipeline.get("max_cycles")` into `VaultSettings.max_cycles` (a required positive
int, listed in `_PIPELINE_TYPED_KEYS`). So "one canonical key" is **adoption of an
existing field**, not a new surface; the work is making the generate/resume CLI
*use* it, deprecating the `cycles:` extras path, deleting the spec fields, and
threading the resolved values into the orchestrator as explicit params. No new
runtime dependency (Principle V); one **new ADR (0011)** because the
reclassification reverses an explicit prior design intent.

| FR | What | Primary code target (verified path) |
| --- | --- | --- |
| **FR1** | One canonical settings key; deprecate `cycles.initial_max`/`update_max` (warn-and-honour) | `pipeline/settings.py` (`VaultSettings.max_cycles` already typed; add deprecation shim in the `cycles`-extras consumer) + `_assets.load_cycle_limits_from_settings` (emit WARNING, redirect to canonical) |
| **FR2** | Remove `max_cycles` + `max_usd` from the spec schema (silent-ignore leftovers) | `spec/schema.py` (`BudgetConfig.max_cycles`/`max_usd` + top-level `SpecConfig.max_cycles`), `spec/simple.py`, `examples/*.spec.md`, `cli/research_generate.py` (stop mutating spec) |
| **FR3** | `--max-cycles N` last-word flag | `cli/research_generate.py` + `cli/research_resume.py` + `cli/research_phase3.py` (shared resolver helper) |
| **FR4** | Loud + recorded overrides; constrained-exit first-class in run report | `cli/*` (WARNING via `_LOG`, not `print`) + `pipeline/run_report.py` (`cycle_budget` provenance block) + `pipeline/orchestrator.py:806` (reword hint) |
| **FR5** | Sane shipped default; the two seeds agree | `settings.yaml` + `settings.codex.yaml` (canonical key value/comment) + `dist-templates/scaffold-manifest.json` (sha) |

**Critical reconciliation (read research.md before implementing):** the spec
names `pipeline.max_cycles`, `cycles.initial_max`, `spec.budget.*` and the
generate CLI by their real homes — all verified 2026-06-05. The one design choice
the plan locks is the **precedence resolver lives in one shared helper** consumed
by all three CLI entry points (D3), so the ladder (flag > settings > default) is
implemented exactly once.

## Technical Context

**Language/Version**: Python 3.11+ (per `pyproject.toml` `requires-python`).
**Primary Dependencies**: stdlib + existing only — `pyyaml ≥ 6.0` (settings/spec
frontmatter). **No new runtime dependencies** — Principle V is non-negotiable.
**Storage**: filesystem under vault root. Touched artifact: `_pipeline/run-report.md`
+ the run-report JSON (FR4 `cycle_budget` provenance block, additive). No new
sidecar. Seeds changed: `settings.yaml`, `settings.codex.yaml` (canonical-key value),
`dist-templates/scaffold-manifest.json` (sha refresh).
**Testing**: pytest, seven-tier pyramid (ADR-0008). New tier-2/3 unit suites for the
resolver, settings deprecation, schema removal, the flag, and run-report provenance.
**Target Platform**: macOS / Linux dev + CI.
**Project Type**: single-project Python CLI + Jinja2-templated vault scaffold.
**Performance Goals**: none affected — this is a config-resolution + reporting change
on the cold path (generate/resume entry, run finalisation).
**Constraints**: FR5 default MUST preserve the spec-022 quality-harness baselines
(the fixtures must not silently change cycle count); if a baseline re-cut is needed
it is intentional and noted. FR2 is a **breaking schema change**, authorised by
ADR-0011 + clarify Q2/Q3 — but harmless in practice because `from_dict` silently
drops unknown keys (D2), so existing specs keep parsing.
**Scale/Scope**: ~10 source files + 2 seeds + examples, ~1 day. Adds ~25–30 tests.

### Resolved unknowns (full detail in research.md)

All five clarify questions are resolved in the spec's Clarifications block; Phase-0
resolved the remaining spec→code mapping. No open unknowns entering Phase 1.

- **D1 — canonical field already exists.** `VaultSettings.max_cycles` ←
  `pipeline.get("max_cycles")` (`pipeline/settings.py:137,227`). FR1 adopts it; the
  `cycles:` block stays in `.extras` and becomes the deprecated alias path.
- **D2 — unknown-key behaviour is silent-drop.** `SpecConfig.from_dict` /
  `BudgetConfig.from_dict` read via `.get()`; a leftover `max_cycles:`/`max_usd:` is
  dropped at parse time, never reaching the validator. FR2's "silent ignore" needs
  **no new code** — only field deletion + a test pinning the behaviour.
- **D3 — one resolver, three callers.** generate/resume/phase3 each have their own
  override hooks today; the ladder is implemented once in a shared
  `resolve_cycle_budget(settings, flag)` helper and called from all three.
- **D4 — orchestrator already param-driven.** `run_cycles(..., max_cycles=...)`
  (`orchestrator.py:368`) takes the cap as a param; only the internal
  `budget_cap = spec.budget.max_usd` / `max_cycles = spec.budget.max_cycles`
  (`:517-518`) reads off the spec. FR2/FR4 thread the resolved values in and delete
  those two reads; the user hint at `:806` is reworded to point at settings/flag.
- **D5 — run-report provenance home.** `pipeline/run_report.py` already records the
  final exit code/reason; FR4 adds an additive `cycle_budget` object (no schema bump
  needed for the markdown; the JSON gains one nested object).

## Constitution Check

*GATE: evaluated against constitution v1.4.0. Re-checked post-design below.*

| Principle | Verdict | Notes |
| --- | --- | --- |
| **I. Script-Validated Quality Gates** | ✅ PASS | No gate semantics change. FR4 makes the *existing* constrained exit first-class in the report; exit codes unchanged (`vault_commit.py:445` map intact). |
| **II. Phase Sequencing** | ✅ PASS | Budget resolution moves earlier (CLI entry) but no phase reordering; the cap is still a cycle-boundary check. |
| **III. Test-First (TDD)** | ✅ PASS | Every FR ships its test file with/before impl. |
| **IV. Agent-Script Separation** | ✅ PASS | Pure deterministic config resolution + reporting; no agent self-assessment. |
| **V. Offline-First, No External Persistence** | ✅ PASS | No new deps; provenance is local-only. |
| **VI–IX** | ✅ N/A | No note-creation, sourcing, or citation path touched. |
| **X. Vault History is Append-Only Git** | ✅ PASS | Run-report provenance rides the existing per-run commit; the constrained-exit branch-retention behaviour (spec 050) is unchanged. |

**Ask-First items (both pre-authorised, flagged for the record):**
1. **FR2 schema removal** (`max_cycles`/`max_usd`) — a breaking spec-schema change.
   Authorised by **ADR-0011** + clarify Q2/Q3. Harmless in practice (D2 silent-drop).
2. **FR1 deprecation of `cycles.initial_max`/`update_max`** — settings-surface change.
   Authorised by clarify Q1/Q5; honoured-with-WARNING for a grace period (no silent
   behaviour change).

**Gate result: PASS.** No unjustified violations; Complexity Tracking empty.

### Post-Design Re-check (after Phase 1)

Re-evaluated after `data-model.md`: no new runtime dependency, no new principle
(constitution stays v1.4.0), no Ask-First item beyond the two flagged. ADR-0011
records the reclassification. Verdict remains **PASS**.

## Project Structure

### Documentation (this feature)

```text
specs/061-cycle-budget-config/
├── plan.md          # This file (/speckit.plan output)
├── spec.md          # Feature spec (clarified 2026-06-05)
├── research.md      # Phase 0 — decisions D1–D5 (spec→code reconciliation)
├── data-model.md    # Phase 1 — precedence ladder + run-report cycle_budget entity
├── quickstart.md    # Phase 1 — reproduce the rc1 truncation; prove it's now loud
└── tasks.md         # Phase 2 (/speckit.tasks — NOT created here)
```

> ADR-0011 (`docs/adr/0011-operational-config-in-settings.md`) already exists
> (Proposed); it transitions to Accepted when 061 ships.

### Source Code (repository root) — files touched, by FR

```text
src/research_framework/
├── _assets.py                      # FR1: load_cycle_limits_from_settings → WARNING + redirect to canonical
├── pipeline/
│   ├── settings.py                 # FR1: VaultSettings.max_cycles stays canonical; deprecation note on cycles-extras
│   ├── run_report.py               # FR4: cycle_budget {configured, source, actual, exit_status}
│   └── orchestrator.py             # FR2/FR4: drop spec.budget.* reads (:517-518); reword hint (:806)
├── spec/
│   ├── schema.py                   # FR2: remove BudgetConfig.max_cycles/max_usd + SpecConfig.max_cycles
│   └── simple.py                   # FR2: stop emitting a budget block
└── cli/
    ├── _budget_resolve.py          # FR3 (new): resolve_cycle_budget(settings, flag) shared resolver
    ├── research_generate.py        # FR2/FR3/FR4: stop mutating spec; add --max-cycles; WARNING not print
    ├── research_resume.py          # FR3: --max-cycles; use shared resolver
    └── research_phase3.py          # FR3: --max-cycles; use shared resolver

settings.yaml                       # FR5: canonical pipeline.max_cycles value + comment; drop seed disagreement
settings.codex.yaml                 # FR5: same
dist-templates/scaffold-manifest.json  # FR5: sha refresh for the changed seeds
examples/*.spec.md                  # FR2: drop budget/max_cycles from example + reference specs

tests/
├── pipeline/
│   ├── test_cycle_budget_settings.py        # FR1: canonical-only / deprecated-only(+warn) / both(+warn) / neither
│   └── test_run_report_budget_provenance.py # FR4: cycle_budget block; constrained != complete
├── spec/
│   └── test_schema_budget_removed.py        # FR2: fields gone; stray max_cycles/max_usd silently ignored
└── cli/
    ├── test_max_cycles_flag.py              # FR3: flag>settings>default; invalid N → exit 2
    └── test_budget_resolver.py              # FR3/D3: shared resolver ladder unit tests
```

**Structure Decision**: single-project layout. One **new** module
(`cli/_budget_resolve.py`) so the precedence ladder exists exactly once (D3); every
other change is in-place. No new top-level directories.

## Phase Sequencing for implementation (dependency-ordered)

Recommended `/speckit.tasks` ordering (FR1→FR5 share the resolver; build it first):

1. **FR3 resolver core** (`cli/_budget_resolve.py` + `test_budget_resolver.py`) —
   the ladder, in isolation. Everything else consumes it.
2. **FR1** — `VaultSettings.max_cycles` canonical confirm + `load_cycle_limits…`
   deprecation WARNING/redirect; settings tests.
3. **FR2** — delete schema fields + `simple.py` budget + example-spec budgets; stop
   the generate CLI mutation; pin silent-ignore with `test_schema_budget_removed.py`.
4. **FR3 wiring** — add `--max-cycles` to generate/resume/phase3; thread resolved
   values into `run_cycles`; flag tests.
5. **FR4** — WARNING-not-print at resolution; `run_report.cycle_budget` provenance;
   reword `orchestrator.py:806`; provenance tests. (This is the signal 063 §4.1 gates.)
6. **FR5** — set the agreed canonical default in both seeds, refresh the
   scaffold-manifest sha, confirm spec-022 baselines don't move (`./build.sh --quality`).

## Complexity Tracking

> No Constitution Check violations require justification. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
