# Implementation Plan: E2E Quality + Test Harness

**Branch**: `022-e2e-quality-harness` | **Date**: 2026-05-21 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/022-e2e-quality-harness/spec.md`

## Summary

Ship a deterministic, fake-agent-only quality-regression harness that
exercises 3 fixture vaults (`tech-lite`, `source-poor`, `source-rich`)
end-to-end, computes 3 metric families (coverage, cycle health,
note-quality template-compliance), and compares the result against a
committed baseline JSON per fixture. The harness is invoked via a new
`./build.sh --quality` flag and via direct `pytest -m e2e tests/quality/`;
CI fires only on `v*` tag push or `workflow_dispatch`. The first
baselines are committed in the same PR that ships the harness code
(ship-PR-blessed flow, locked in clarify Q5). Total runtime target:
< 12 min on a recent Mac (smoke ~2 min + harness < 10 min).

Foundation work for spec 022 implementation lives in **specs 024** (LLM
dispatch guard, fake_agent verifier/narrator/probe stubs, smoke
meta-tests, ADR-0008 lint guards) and **025** (LLM dispatch
consolidation, cycle-step extraction). 022 v2 (the 4th metric family,
the missing 3 fixtures, and the with-vault-vs-without `/ask` comparison)
queues immediately after v1 ships.

## Technical Context

**Language/Version**: Python 3.11+ (per `pyproject.toml`'s `requires-python = ">=3.11"` and constitution Technology Constraints).
**Primary Dependencies**: existing only — `jinja2 ≥ 3.1`, `pyyaml ≥ 6.0`, `sqlite3` (stdlib). Stdlib for `json`, `pathlib`, `hashlib`, `subprocess`, `argparse`, `dataclasses`. **No new runtime dependencies** — Principle V is non-negotiable.
**Storage**: filesystem under `tests/fixtures/quality/` (committed) + `_pipeline/quality/` per-run workspace (gitignored). New artifacts: `tests/fixtures/quality/baselines/<fixture>.baseline.json` (committed), `tests/fixtures/quality/<fixture>/{research.spec.md, settings.yaml, fake_agent_responses/}` (committed), `_pipeline/quality/<fixture>.current.json` (gitignored), `_pipeline/quality/regression-report.json` (gitignored).
**Testing**: pytest with `@pytest.mark.e2e + @pytest.mark.slow` per ADR-0008 tier-6 (multi-cycle e2e). The harness IS a tier-6 test; unit tests for metric calculators live at tier-1 (`tests/quality/unit/test_*.py`).
**Target Platform**: macOS (developer) + Linux (GitHub Actions `ubuntu-latest`). No Windows support (per ROADMAP queue #2 — WSL2 only if ever).
**Project Type**: CLI tool extension — adds `./build.sh --quality` shell flag, `./vault quality-baseline-update <fixture>` CLI subcommand, and `.github/workflows/quality.yml` GitHub Actions workflow. No new web service, library, or external interface.
**Performance Goals**: harness-only runtime < 10 min on a recent Mac (SC-006, locked clarify Q3). Per-fixture harness invocation < 3.5 min. Cycle-runner per-fixture cycles capped at **`max_cycles: 3`** (set in each fixture's `settings.yaml` — see tasks.md T045, T049, T052). The ≤ 3 cap is tight enough to fit the perf budget and wide enough to surface multi-cycle phenomena (SG-002 trips in `source-poor`, gap-pursuit substitution).
**Constraints**: byte-deterministic JSON output (SC-001, FR-003) — no `datetime.now()`, no random ordering, no platform-dependent floats. No live LLM (v1 fake-agent only — FR-001). No auto-baseline-write (FR-007) — only the explicit `./vault quality-baseline-update` CLI subcommand may modify baseline files.
**Scale/Scope**: 3 fixtures × ~15–20 notes/cycle × 3 metric families × ≤ 3 cycles/fixture in a harness run. Baselines ~5–15 KB each. Cycle-runner ~ 3.5 min per fixture × 3 fixtures + report aggregation ~ 30 s = harness target ~ 11 min (under the 12 min SC-006 ceiling).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Each principle evaluated against this spec; ⚠️ items have justifications below.

| Principle | Status | Notes |
|---|---|---|
| I — Script-Validated Quality Gates (NON-NEGOTIABLE) | ✅ Aligned | The harness IS the new script-validated gate. `./build.sh --quality` exits 0/1 per FR-004; CI gates on exit code. |
| II — Phase Sequencing (NON-NEGOTIABLE) | ✅ N/A | Harness orchestrates *test* phases of fixture vaults via fake_agent; does not alter the framework's three-phase contract. |
| III — Test-First (TDD — NON-NEGOTIABLE) | ✅ Aligned | Unit tests for metric calculators land before implementation; harness's fixture vaults *are* end-to-end tests; ship-PR includes both. |
| IV — Agent-Script Separation of Concerns | ✅ Aligned | Harness is pure script. Fake-agent responses are static JSON fixtures (no agent runtime). CI is script-invoked. |
| V — Offline-First, No External Data Persistence | ✅ Aligned | Fixture vaults are local; baselines committed in repo; no telemetry; fake-agent only (no network at runtime). |
| VI — No Duplicate Notes | ✅ N/A | Fixture vault notes are intentionally distinct; canned fake-agent responses produce template-faithful unique titles. |
| VII — External Sources Are Mandatory | ✅ N/A | Fixture vaults declare synthetic source URLs in their `research.spec.md`; harness measures structural compliance, not actual external reachability. |
| VIII — No Placeholders in Deliverables | ⚠️ See justification | Vault-shaped fixture content (clarify Q2 — Option B, lorem-ipsum-style) is **not** placeholder in the constitutional sense. See Complexity Tracking below. |
| IX — Vault-First Citation (NON-NEGOTIABLE) | ✅ N/A | Harness does not produce vault content consumed by users. Fixture vaults' citations exercise the *metric* layer's structural counting, not the runtime citation contract. |

### Boundary checks

- **Always Do** items: harness will run `pytest scripts/tests/` as part of its own unit-test layer before tier-6 runs. Coverage targets in each fixture vault drive the metric calculation. Fixture templates and frontmatter are read from each fixture's `_templates/` (no hardcoded structure).
- **Ask First** items: none triggered. The harness does NOT change phase sequencing, exit-code semantics, frontmatter schema, naming convention, or `coverage-targets.json` structure. It READS those structures from each fixture; it doesn't modify them.
- **Never Do** items: none triggered. The harness adds no external dependency. It does not create duplicate notes; it does not skip Phase 2's external-source contract (it *measures* compliance, doesn't bypass).

**Constitution gate: PASS** (pre-Phase-0).

## Project Structure

### Documentation (this feature)

```text
specs/022-e2e-quality-harness/
├── plan.md              # This file (/speckit.plan command output)
├── spec.md              # SPECIFY+CLARIFY output (605 lines, 5 clarify Q/A locked)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output — baseline JSON schema + report schema
├── quickstart.md        # Phase 1 output — dev-facing usage walkthrough
├── contracts/           # Phase 1 output
│   ├── baseline-schema.contract.md      # baseline JSON schema
│   ├── regression-report.contract.md    # harness output / report schema
│   ├── quality-cli.contract.md          # ./vault quality-baseline-update + ./build.sh --quality
│   └── quality-workflow.contract.md     # .github/workflows/quality.yml triggers + jobs
└── tasks.md             # Phase 2 output (NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
src/research_framework/
├── cli.py                                    # extend: add `quality-baseline-update` subcommand
└── quality/                                  # NEW: harness implementation
    ├── __init__.py
    ├── runner.py                             # tier-6 orchestrator (per-fixture cycle exec + metric collection)
    ├── metrics/                              # one module per metric family
    │   ├── __init__.py
    │   ├── coverage.py                       # % coverage_targets met; notes per category; spec-vs-vault drift
    │   ├── cycle_health.py                   # pass/fail count, SG-NNN trip count, retry-once rate
    │   └── note_quality.py                   # template-compliance subset (per 2026-05-20 triage #26; see docs/TODO.md#restoration-notes)
    ├── baseline.py                           # diff + report (no auto-write — FR-007)
    ├── baseline_update.py                    # backs the `quality-baseline-update` CLI (with --dry-run)
    └── report.py                             # regression-report.json shape + stdout pretty-printer

tests/quality/                                # NEW: harness tier-6 + unit layer
├── __init__.py
├── unit/                                     # tier-1 unit tests for metric calculators
│   ├── test_coverage_metric.py
│   ├── test_cycle_health_metric.py
│   ├── test_note_quality_metric.py
│   ├── test_baseline_diff.py
│   ├── test_baseline_update_cli.py
│   └── test_determinism_guard.py
├── test_quality_harness_tech_lite.py         # tier-6 — per-fixture e2e
├── test_quality_harness_source_poor.py
├── test_quality_harness_source_rich.py
└── test_baseline_update_isolation.py         # guard test — only CLI may write baselines (FR-012)

tests/fixtures/quality/                       # NEW: fixture vault namespace (owned by 022)
├── baselines/
│   ├── tech-lite.baseline.json               # committed; ship-PR-blessed
│   ├── source-poor.baseline.json
│   └── source-rich.baseline.json
├── tech-lite/                                # vault-shaped fixture (FR-009, clarify Q2 Option B)
│   ├── research.spec.md
│   ├── settings.yaml
│   ├── coverage-targets.json
│   ├── _templates/
│   └── fake_agent_responses/
│       ├── scout/scenario-1.json
│       ├── note_writer/scenario-1.json
│       ├── verifier/scenario-1.json
│       ├── narrator/happy.json
│       └── probe_retrieval/happy.json
├── source-poor/                              # same structure; under-resourced spec
└── source-rich/                              # same structure; curated source list

build.sh                                      # extend: add `--quality` flag dispatch
.github/workflows/quality.yml                 # NEW: tag-push + workflow_dispatch triggers (FR-014)
docs/testing-strategy.md                      # update: tier-6 row gains harness reference
CONTRIBUTING.md                               # extend: soft-recommend local `./build.sh --quality` for high-risk PRs (FR-015)
```

**Structure Decision**: Single-project structure (Option 1 of the template) — the framework is one Python package + one CLI binary + ancillary shell scripts. The harness slots into the existing layout (`src/research_framework/<package>/` + `tests/<area>/` + `tests/fixtures/<area>/`) with **no new top-level directories**. No frontend, no service, no mobile component.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Vault-shaped fixture content with synthetic body text (lorem-ipsum-style topic names) is acceptable per clarify Q2 Option B — *not* Constitution Principle VIII's "stub/placeholder" definition | Realistic content (Option C) would require hand-authoring of citation-quality prose per fixture; effort estimate jumps from ~2–3 days to ~5–7 days and produces zero added value for the metric families v1 measures (coverage counts, cycle-health gate trips, template-compliance — none rely on prose quality) | Hand-authored realistic fixtures would push v1 past the 2026-06-01 codex token window. The constitutional placeholder rule targets *deliverable* notes (notes the user reads), not *test-fixture* notes (notes the harness compares against committed baselines) — the failure modes Principle VIII addresses (F2: scripts listed but not implemented; F4: summary overflow not caught) are about user-facing artifacts, not regression-test fixtures. The harness's role is structural-regression detection, not content-quality validation; content-quality validation is the v2 with-vault-vs-without `/ask` comparison |
