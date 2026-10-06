# Implementation Plan: Testing Infrastructure v2 — Phase 2 + Discipline Layer

**Branch**: `024-testing-infrastructure-v2` | **Date**: 2026-05-21 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/024-testing-infrastructure-v2/spec.md`

## Summary

Ship the Phase 2 testing-discipline layer that ADR-0008 introduced.
Seven user stories, three workstreams that share one exit criterion
(full sweep green + smoke green + LLM-dispatch allowlist contains
exactly two entries):

1. **Guards** — LLM dispatch guard (tier-2, two-entry allowlist),
   spec-acceptance-coverage lint guard (strict, no allowlist), and
   CHANGELOG regression-link lint guard (strict, no allowlist). The
   latter two are paired with one-shot backfills: 3 existing specs
   (`015a`, `017`, `018`) gain a `## Acceptance coverage` section, and
   every `### Fixed` bullet across the 15 released-version blocks of
   `CHANGELOG.md` gains a `(test: …)`, `(regression test: …)`, or
   `(no test: …)` annotation.
2. **Fake-agent stage extensions** — implement the v2 contract for
   `verifier` (accept / reject / malformed_json), `narrator` (happy),
   and `probe_retrieval` (happy) per
   `specs/018-testing-strategy/contracts/fake-agent.contract.md`.
   Wire the resulting stages into a tier-5 cycle e2e covering
   `oos_topic`, `partial_yield`, and `verifier_reject`.
3. **Smoke meta-tests restored** — uncomment the two
   `tests/build/test_*.py` entries in `build.sh` (lines 74-75; the
   files already exist on disk).

A targeted cleanup deletes `tests/pipeline/test_e2e_synthetic_vault.py`
outright (Q6); historical coverage flows into the tier-5 e2e
scenarios from US6 and the CHANGELOG `(test: …)` annotations from
FR-014/FR-015 are re-pointed accordingly.

**Pre-requisite for 022 implementation.** Spec 025 (Tier A
LLM-dispatch consolidation) shrinks the 024-ship two-entry allowlist
to zero immediately after 024 ships.

## Technical Context

**Language/Version**: Python 3.11+ (per `pyproject.toml`'s `requires-python = ">=3.11"` and constitution Technology Constraints).
**Primary Dependencies**: existing only — `pytest ≥ 7.4` (already in `[dev]`), `pyyaml ≥ 6.0` (already a runtime dep, reused for allowlist YAML and CHANGELOG parsing helpers), `jinja2 ≥ 3.1` (unchanged). Stdlib for `ast`, `re`, `pathlib`, `argparse`, `dataclasses`, `subprocess`, `json`. **No new runtime dependencies** — Principle V is non-negotiable. **No new test dependencies either** — `pytest`, `hypothesis`, `black`, `ruff` are sufficient.
**Storage**: filesystem only. New files committed: `tests/_helpers/llm_dispatch_allowlist.yaml`, `tests/_helpers/fake_agent_scenarios/<stage>/<scenario>.json` (verifier ×3, narrator ×1, probe_retrieval ×1), `tests/spec/test_acceptance_coverage_guard.py`, `tests/spec/test_changelog_regression_links.py`, `tests/_helpers/test_llm_dispatch_guard.py`, `tests/integration/test_cycle_e2e.py` (new scenarios appended), backfilled `## Acceptance coverage` sections in 3 spec files, ~30–50 in-place CHANGELOG annotations. No databases, no caches, no per-run sidecars beyond what fake-agent already writes.
**Testing**: pytest. Lint guards run at **tier 2** (fast local loop, `pytest -m "not e2e"`). Fake-agent contract test stays at tier 2. Tier-5 cycle e2e additions live at `tests/integration/test_cycle_e2e.py` with `@pytest.mark.e2e`. Smoke meta-tests run inside `build.sh`'s `SMOKE_TESTS` set (tier 6 per ADR-0008). The lint guards self-validate: the dogfood `## Acceptance coverage` table in `specs/024-testing-infrastructure-v2/spec.md` must pass the FR-006 guard against itself (SC-009).
**Target Platform**: macOS (developer primary) + Linux (planned GitHub Actions). Lint guards are pure-Python, no platform-specific assumptions. Smoke gate runs `./build.sh` which currently macOS-only (spec 009 will fix this; orthogonal to 024).
**Project Type**: Library/CLI extension within an existing single-project layout. No new top-level package; new test modules + helper data files only.
**Performance Goals**: Each new lint guard MUST complete in < 5 s individually (Assumptions). Net fast-loop runtime delta from ship < 30 s (SC-002, currently ~ 240 s on a recent Mac per the baseline run). Tier-5 e2e additions stay within the existing `@pytest.mark.e2e` budget — three new scenarios at ~ 5–10 s each = ≤ 30 s added to e2e gate.
**Constraints**: Deterministic everywhere (no `datetime.now()`, no `uuid`, no `random` — same rules the existing fake_agent already enforces). Lint guards MUST be cheap parsers (markdown regex / state machine + AST scan for LLM dispatch) — no spawning subprocesses, no network. **Both new lint guards ship strict at launch with NO allowlist** (Q4 + Q5 ratifications). Two-entry allowlist for the LLM dispatch guard is the ONLY exception, and shrinks to zero in spec 025 Tier A.
**Scale/Scope**: +6 new test files (3 guards + 3 e2e scenarios in one file), +5 fake-agent scenario JSON files, +3 spec backfills, ~30–50 CHANGELOG bullet annotations, 1 file deletion. ~1158 existing tests stay green. Estimated lift: 3–4 focused sessions per the spec's session-count estimate.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Each principle evaluated against this spec; no items flagged ⚠️.

| Principle | Status | Notes |
|---|---|---|
| I — Script-Validated Quality Gates (NON-NEGOTIABLE) | ✅ Aligned | This spec **adds** new script-validated gates (3 lint guards + 1 fake-agent contract + 1 smoke meta-test set). All run via `pytest` exit codes — no agent judgment anywhere. |
| II — Phase Sequencing (NON-NEGOTIABLE) | ✅ N/A | Spec adds test infrastructure; does not alter the framework's three-phase contract. |
| III — Test-First (TDD — NON-NEGOTIABLE) | ✅ Aligned | The work IS test-first by construction — the new lint guards ARE tests, the fake-agent extensions ship alongside contract test updates, and the tier-5 scenarios assert against snapshots. |
| IV — Agent-Script Separation of Concerns | ✅ Reinforced | US1's LLM dispatch guard exists specifically to **enforce** Principle IV. Adding it strengthens, not weakens, the principle. |
| V — Offline-First, No External Data Persistence | ✅ Aligned | Zero new runtime deps. All new files are local + version-controlled. No telemetry, no network. |
| VI — No Duplicate Notes | ✅ N/A | Spec touches tests + lint guards + CHANGELOG, not vault notes. |
| VII — External Sources Are Mandatory | ✅ N/A | Same as VI. |
| VIII — No Placeholders in Deliverables | ✅ Aligned | The `_(deferred to tasks.md)_` strings inside the dogfood `## Acceptance coverage` table are spec-metadata placeholders, NOT vault-note placeholders — outside Principle VIII's scope (which targets `data_vault/` content). FR-013's backfill mandates real evidence pointers (test path or `_(historical — see …)_`), not bare TODOs. |
| IX — Vault-First Citation (NON-NEGOTIABLE) | ✅ N/A | Spec produces test infrastructure, not vault content consumed by users. |

### Boundary checks

- **Always Do** items: TDD (Principle III) is naturally honored — every new lint guard is itself a test, and adding fake-agent stages is paired with updating `tests/_helpers/test_fake_agent_contract.py`. No `--dry-run` flag needed (no vault-mutating scripts).
- **Ask First** items: none triggered. No phase-sequencing changes, no exit-code semantic changes, no frontmatter changes, no naming convention changes, no new external deps, no `validate_cycle.py` condition-B changes.
- **Never Do** items: none triggered. `pytest` gating is unchanged. No agent self-assessment introduced. No external-source skipping. No placeholder scripts.

**Constitution gate: PASS** (pre-Phase-0). No Complexity Tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/024-testing-infrastructure-v2/
├── plan.md                                       # This file (/speckit.plan command output)
├── spec.md                                       # SPECIFY+CLARIFY output (670 lines, 6 clarify Q/A locked)
├── research.md                                   # Phase 0 output — 6 implementation decisions
├── data-model.md                                 # Phase 1 output — allowlist YAML + scenario JSON shapes + dogfood-row shape
├── quickstart.md                                 # Phase 1 output — dev-facing iteration loop per workstream
├── contracts/                                    # Phase 1 output
│   ├── acceptance-coverage-guard.contract.md     # tier-2 lint guard for `## Acceptance coverage` sections
│   ├── changelog-regression-guard.contract.md    # tier-2 lint guard for `### Fixed` annotations
│   └── fake-agent-v2-stage-extensions.contract.md # implementation tracker — what 024 ships against the 018 v2 contract
└── tasks.md                                      # Phase 2 output (NOT created by /speckit.plan)
```

**Re-used contracts (consumed, not duplicated):**

- `specs/018-testing-strategy/contracts/llm-dispatch-guard.contract.md` — US1's guard implements this contract verbatim.
- `specs/018-testing-strategy/contracts/fake-agent.contract.md` (v2) — US2's stage extensions match § Stages and § Scenarios verbatim.
- `specs/018-testing-strategy/contracts/vault-factory.contract.md` — US6's tier-5 e2e scenarios consume `vault_factory.build_minimal_vault` unchanged.

### Source Code (repository root)

```text
tests/_helpers/
├── fake_agent.py                                 # EXTEND: add verifier / narrator / probe_retrieval stages
├── test_fake_agent_contract.py                   # EXTEND: assert the 3 new stages × scenarios
├── test_llm_dispatch_guard.py                    # NEW: tier-2 AST guard (US1)
├── llm_dispatch_allowlist.yaml                   # NEW: 2-entry allowlist (US1; shrinks to 0 in spec 025)
└── fake_agent_scenarios/                         # NEW: scenario response payloads
    ├── verifier/
    │   ├── accept.json
    │   ├── reject.json
    │   └── malformed_json.json                   # deliberately invalid JSON — exercises ADR-0004 parser
    ├── narrator/
    │   └── happy.json
    └── probe_retrieval/
        └── happy.json

tests/spec/
├── test_acceptance_coverage_guard.py             # NEW: tier-2 lint (US4)
└── test_changelog_regression_links.py            # NEW: tier-2 lint (US5)

tests/integration/
└── test_cycle_e2e.py                             # EXTEND: add oos_topic / partial_yield / verifier_reject scenarios (US6)

tests/pipeline/
└── test_e2e_synthetic_vault.py                   # DELETE (US7 / Q6)

tests/build/
├── test_install_wizard_skip_redundant_questions.py   # UNCHANGED file; re-enabled in build.sh (US3)
└── test_smoke_gate_enforces_contract_tier.py         # UNCHANGED file; re-enabled in build.sh (US3)

specs/_archive/015a-corpus-folder-name/spec.md             # BACKFILL: add `## Acceptance coverage` section (FR-013)
specs/017-vault-quality-fix/spec.md          # BACKFILL: add `## Acceptance coverage` section (FR-013)
specs/018-testing-strategy/spec.md                # BACKFILL: add `## Acceptance coverage` section (FR-013)

CHANGELOG.md                                      # BACKFILL: annotate every `### Fixed` bullet (FR-014; 15 sections)

build.sh                                          # EDIT: uncomment lines 74-75 (US3 / QW-2)

docs/testing-strategy.md                          # EDIT: line 38 branch name correction + Phase 2 checkbox ticks (FR-011, FR-012)
```

**Structure Decision**: Single-project Python layout (Option 1) is already in place. All changes are additive within `tests/` plus three in-place file edits (`build.sh`, `CHANGELOG.md`, `docs/testing-strategy.md`) and one in-place deletion (`tests/pipeline/test_e2e_synthetic_vault.py`). No new top-level directories, no `src/research_framework/` changes — the production code path is untouched by this spec by design (spec 025 owns production refactors).

## Complexity Tracking

No constitution violations and no off-template structural choices. Section intentionally empty.
