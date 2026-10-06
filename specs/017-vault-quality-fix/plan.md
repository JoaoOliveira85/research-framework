# Implementation Plan: Vault Quality Fix

**Branch**: `017-vault-quality-fix` | **Date**: 2026-05-15 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/017-vault-quality-fix/spec.md`

## Summary

The reference_vault_v3 trial run produced 52 internal-artifact-named notes across 4 of 13 categories in 6 cycles — agents drifted unsupervised because the framework had no shared plan, no abstraction enforcement, no per-cycle quotas, and no deterministic gates between steps and cycles. This plan adds those four missing layers to the existing `research_vault` Python pipeline:

1. **Hybrid Research Plan** (`_pipeline/research-plan.md`) — a deterministic Python generator builds the priority queue, focus list, and exclusion list from coverage state + spec + harvest backlog + persistent rejects; an agent narrator step prepends a short "focus rationale" header. Single source of truth injected into both scout and note-writer prompts.
2. **Deterministic Quality Gate Framework** — pure-Python PASS/WARN/FAIL gates between scout/note-writer (SG-001..SG-005) and between cycles (CG-001..CG-007); per-cycle minimum yield computed as `ceil(remaining/remaining_cycles)`; correction directives injected into next batch on FAIL; incremental retry preserves accepted batches.
3. **Sequential Note-Writer Batching** — orchestrator-driven 5-8 topic batches per invocation; mid-cycle gates run between batches; cycle quota (≥25) enforced by code, not the agent.
4. **Source Preflight + Post-Generation Reindex** — fail-fast source validation before any generation; deterministic reindex of `_index.md`/`_concepts.md`/`_graph.md` inside `data_vault/` after every cycle.

The plan extends but does not break the existing `pipeline/orchestrator.py`, `pipeline/cycle_runner.py`, `pipeline/coverage.py`, `pipeline/preconditions.py`, and `scripts/topic_harvest.py`. The hardcoded service-prefix list from the trial run is replaced by a vault-configurable `forbidden_filename_prefixes` field on `SpecConfig` so the abstraction gate is portable.

## Technical Context

**Language/Version**: Python 3.11+ (per `pyproject.toml`'s `requires-python = ">=3.11"` and constitution Technology Constraints)
**Primary Dependencies**: existing — `jinja2 ≥ 3.1` (prompt templates), `pyyaml ≥ 6.0` (settings + spec frontmatter), `sqlite3` (stdlib, used by `pipeline/source_manager.py`). **No new runtime dependencies** — Principle V is non-negotiable.
**Storage**: filesystem under vault root. New artifacts: `_pipeline/research-plan.md`, `_pipeline/cycles/cycle-NNN-quality-report.json`, `_pipeline/cycles/cycle-NNN-batch-NNN.json`, `_pipeline/preflight.json`, `_pipeline/probe-results-NNN.json`. Existing `_pipeline/sources.db` (SQLite) is reused for source preflight history. Existing `coverage-targets.json`, `research-backlog.md`, `cycle-NNN-research.json`, `cycle-NNN-harvest.json` are unchanged in schema (only consumed).
**Testing**: pytest (existing), `addopts = "-v --tb=short"`, `testpaths = ["tests"]`, `pythonpath = ["src"]`. New tests mirror existing layout: `tests/pipeline/test_*.py` for new pipeline modules, `tests/scripts/test_*.py` for new top-level scripts. Hypothesis is already a dev dep — usable for property-style tests on the per-cycle-yield arithmetic and gate threshold logic.
**Target Platform**: macOS / Linux developer workstation. Offline-capable per Principle V — all gate logic, plan generation, preflight, and probe scoring run locally on Python 3.11+ with stdlib + jinja2/pyyaml. No new network calls in framework code; agent invocations remain the only network egress and go through the existing `claude` CLI orchestration path (constitution: Technology Constraints).
**Project Type**: Single project — Python CLI (`research-vault`) with bundled scripts/templates/skills. No frontend, no service. Existing layout (`src/research_vault/` package + `scripts/` top-level + `.agents/` skill bundle + `tests/`) is preserved; new modules slot into the existing structure.
**Performance Goals**:
- Plan generator (deterministic step) `< 2 s` for vaults up to 500 notes (file walk + coverage diff + ranking — pure Python, no I/O beyond local fs).
- Plan narrator (agent step) `< 30 s` per cycle (single short LLM call generating ≤ 200 words).
- Each gate (SG-xxx, CG-xxx) `< 1 s` evaluation; full cycle gate suite `< 5 s` total.
- Source preflight `< 30 s` total (per spec User Story 5: a 30-second preflight would have caught the trial-run failure).
- Reindex step `< 5 s` for vaults up to 500 notes.
**Constraints**:
- Standard library + `jinja2` + `pyyaml` only. No new dependencies.
- All new code Python 3.11+ with type hints, formatted with `black` (88 cols), linted with `ruff` per existing config.
- Backwards compatible with existing vaults: vaults whose spec lacks `forbidden_filename_prefixes` MUST treat the abstraction gate as `N/A` (assumption recorded in spec).
- No agent self-assessment of validation output (Principle IV / VIII). The agent narrator MUST NOT alter the deterministic plan body. Probe scoring MUST be a deterministic Python score over agent-collected evidence, not a free-form agent judgment.
- Incremental retry (clarification Q3) MUST preserve filesystem state from accepted batches; retries MUST NOT re-write or delete accepted notes.
**Scale/Scope**:
- Target vaults: ≤ 500 notes, ≤ 30 categories, ≤ 10 cycles per run, 25–40 notes per cycle, 4–8 batches per cycle (5–8 topics each).
- reference_vault_v3 specifically: 292 targets, 13 categories, 10-cycle budget — the canonical reference vault for this feature.
- New artifacts per cycle: 1 quality report + N batch reports + 1 probe report ≈ ≤ 100 KB JSON per cycle. Negligible.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution version: **1.3.1** (`.specify/memory/constitution.md`). Each principle evaluated against the spec + clarifications:

| Principle | Status | Justification |
|---|---|---|
| **I. Script-Validated Quality Gates (NON-NEGOTIABLE)** | PASS | The whole feature is *adding more* deterministic Python gates (FR-016 through FR-023). Hybrid plan generator (Q1) keeps prioritization in code; the agent header is advisory. Probe scoring (FR-020) is a deterministic Python computation over collected probe evidence — no agent self-assessment. |
| **II. Phase Sequencing (NON-NEGOTIABLE)** | PASS | All new gates and batching live *inside* Phase 2 between scout and note-writer. Phase 0/1/2/3 sequencing is preserved. CG-005 / coverage gating still controls Phase 3 entry. ABORT path on gate failure (FR-018) honors "the orchestrator MUST NOT proceed" — it terminates the cycle, writes diagnostics, and surfaces resume metadata. The orchestrator-owned continuation rule (Principle II) is reinforced, not weakened. |
| **III. Test-First (TDD — NON-NEGOTIABLE)** | PASS | Plan declares contract tests before implementation in Phase 0/1 deliverables. Every new script (preflight, quality_report, check_abstraction, probe_runner) and every new pipeline module (research_plan, gates, gates_cycle, gates_step, batch, correction, probes) gets a paired `tests/.../test_*.py` written first. New `--dry-run` flag on every script that writes to `_pipeline/`. |
| **IV. Agent-Script Separation of Concerns** | PASS | Plan generator splits work cleanly: deterministic Python (script) writes the priority queue + focus list + exclusions; agent (narrator skill) writes only an advisory text header that downstream code MUST NOT parse for control flow. Gates are pure scripts. Probes are deterministically generated; agent only collects evidence (which note matched which probe); scoring is Python arithmetic. No principle-IV inversion. |
| **V. Offline-First, No External Data Persistence** | PASS | All new code uses stdlib + already-declared `jinja2`/`pyyaml`. SQLite via stdlib. No new package dependencies. No network calls in framework code; the only network egress remains the existing `claude` CLI orchestration path. |
| **VI. No Duplicate Notes** | PASS | Plan does not change the `proposed_filenames` coordination mechanism. The per-cycle topic assignment passes through the existing dedup boundary before reaching the note-writer. Sequential batches (Q2) make duplicate suppression *easier*, not harder, because batches are visible to each other through filesystem state. |
| **VII. External Sources Are Mandatory** | PASS | FR-007 (preflight) directly reinforces this — it surfaces unreachable external sources at run start instead of silently skipping them. Skipped-source detection is logged so Condition B sub-conditions remain truthful. |
| **VIII. No Placeholders / Stub-as-Fuel** | PASS | No script is a placeholder. Stub-as-fuel termination logic is preserved at the cycle boundary; new per-cycle gates run *after* notes are written and *before* the orchestrator's continuation decision, so they don't conflict with the "loop refuses to declare done while fuel remains" rule. Incremental retry (Q3) keeps accepted notes on disk — they remain fuel for subsequent cycles per Principle VIII. |
| **IX. Vault-First Citation (NON-NEGOTIABLE)** | PASS | Out of scope for this plan. The verifier already enforces Tier 1 + Tier 2 citations. SG-005 (frontmatter completeness) reinforces Principle IX by failing the cycle if `source_urls` is missing. |
| **Two-Layer Vault Architecture** | PASS | FR-008/FR-009/FR-010 (reindex inside `data_vault/`, `_templates/` dir, populated index files) directly support Layer 1 being a projection of Layer 2. The spec scaffolding fix is essentially making the framework comply with this principle for the first time on real vaults. |
| **BFS → DFS → Repeat Research Model** | PASS | Plan introduces *batches within* the DFS step, not parallelism between BFS/DFS. Validation gates between phases remain mandatory. |
| **Five Search Dimensions** | PASS | Not affected. Scout abstraction work (FR-003) operates on the topic *level*, not on the dimension model. Existing `validate_cycle.py` dimension check is preserved. |
| **Coverage Targets as Phase Completion Gate** | PASS | Plan extends — not replaces — the coverage system. `coverage-targets.json` remains the source of truth for "Phase 3 may begin." Dynamic-extension via `topic_harvest.py` auto-promotion is preserved (Q4: harvester remains as upstream feeder to the plan generator). FR-005 (priority field) is an additive dataclass field on `CoverageCategory`. |
| **Script Exit Code Model (0/1/2)** | PASS | All new scripts use the documented exit code model. Plan generator: 0 on success, 2 on structural error (e.g., malformed coverage state). Gate scripts: 0 PASS / WARN, 1 FAIL (cycle stops), 2 ABORT (structural). Preflight: 0 all sources reachable, 1 some unreachable but non-fatal warnings, 2 critical sources unreachable. |
| **Note Quality Bar** | PASS | SG-005 (frontmatter completeness) and the existing `validate_vault.py` continue to enforce the Note Quality Bar. CG-006 (word count compliance) explicitly enforces the `min_word_count` field per note type. |

**Result: All gates PASS. No Complexity Tracking entries required.**

The plan does not introduce any patterns that would require a Constitution amendment. The single schema change — adding `forbidden_filename_prefixes: list[str] = field(default_factory=list)` to `SpecConfig` — is additive (default empty), backwards compatible, and is the spec-driven mechanism that the constitution explicitly endorses ("Out of Scope for This Constitution: The vault spec file format").

## Project Structure

### Documentation (this feature)

```text
specs/017-vault-quality-fix/
├── plan.md                               # This file (/speckit.plan output)
├── spec.md                               # Feature spec with Clarifications session 2026-05-15
├── research.md                           # Phase 0 output (/speckit.plan)
├── data-model.md                         # Phase 1 output (/speckit.plan)
├── quickstart.md                         # Phase 1 output (/speckit.plan)
├── contracts/                            # Phase 1 output (/speckit.plan)
│   ├── research-plan.schema.md           # Markdown structure + frontmatter
│   ├── cycle-quality-report.schema.json  # FR-019 deterministic JSON
│   ├── batch-report.schema.json          # Per-batch artifact (Q2)
│   ├── correction-directive.schema.json  # FR-018 retry payload
│   ├── probe-result.schema.json          # FR-020 queryability score evidence
│   ├── preflight.schema.json             # FR-007 source check result
│   └── spec-extension.schema.md          # `forbidden_filename_prefixes` + `priority` field additions
├── checklists/
│   └── requirements.md                   # Existing (from /speckit.specify)
└── tasks.md                              # Phase 2 output (/speckit.tasks — NOT created by /speckit.plan)
```

### Source Code (repository root)

The repository uses the existing `research_vault` package layout. (The constitution v1.3.1 Sync Impact Report notes a deferred `research_vault → research_framework` package rename; this feature **does not** undertake that rename — it only ships under the existing package name. The rename remains its own roadmap item.)

```text
src/research_vault/
├── pipeline/
│   ├── orchestrator.py                   # MODIFIED — wire research-plan, gates, batches, retry
│   ├── cycle_runner.py                   # MODIFIED — call gates between scout/note-writer; loop batches
│   ├── coverage.py                       # MODIFIED — read priority field; expose remaining-yield helper
│   ├── preconditions.py                  # MODIFIED — call preflight as 6th precondition
│   ├── source_manager.py                 # MODIFIED — preflight integration (reuse sources.db)
│   ├── stubs.py                          # UNCHANGED
│   ├── verifier.py                       # UNCHANGED
│   ├── reporter.py                       # MODIFIED — embed cycle-quality-report into cycle report
│   ├── research_plan.py                  # NEW — deterministic plan body generator (Q1 hybrid)
│   ├── plan_narrator.py                  # NEW — invokes research-plan-narrator skill (Q1 hybrid)
│   ├── gates.py                          # NEW — gate framework: GateResult, Gate base, runner
│   ├── gates_cycle.py                    # NEW — CG-001..CG-007 implementations
│   ├── gates_step.py                     # NEW — SG-001..SG-005 implementations
│   ├── batch.py                          # NEW — per-cycle batch scheduler (5–8 topics)
│   ├── correction.py                     # NEW — correction directive builder + retry loop
│   ├── preflight.py                      # NEW — source preflight (FR-007)
│   ├── probes.py                         # NEW — probe generator + scorer (FR-020)
│   └── quality_report.py                 # NEW — cycle-NNN-quality-report.json writer (FR-019)
├── spec/
│   ├── schema.py                         # MODIFIED — add `forbidden_filename_prefixes`, `priority`
│   ├── validator.py                      # MODIFIED — accept new fields; warn on deprecated forms
│   └── parser.py                         # MODIFIED — round-trip new fields
├── vault/
│   └── indexer.py                        # MODIFIED — reindex into data_vault/ (FR-008/FR-010)
├── generator/
│   └── scaffold.py                       # MODIFIED — emit data_vault/_templates/ (FR-009)
├── agents/
│   └── _render.py                        # MODIFIED — inject research-plan into scout + note-writer prompts
└── cli.py                                # MODIFIED — `research-vault preflight`, `research-vault gate-report`

scripts/                                  # Top-level helper scripts (existing convention)
├── preflight_sources.py                  # NEW — CLI for FR-007 (wraps pipeline.preflight)
├── quality_report.py                     # NEW — CLI to print/inspect cycle-NNN-quality-report.json
├── check_abstraction.py                  # NEW — wrapper used by SG-003/CG-003/SC-009
├── probe_runner.py                       # NEW — execute queryability probes; emit probe-result.json
├── topic_harvest.py                      # UNCHANGED — kept as upstream feeder (clarification Q4)
├── topic_propose.py                      # UNCHANGED
├── validate_vault.py                     # UNCHANGED — used by SG-004
├── validate_cycle.py                     # UNCHANGED
├── vault_metrics.py                      # UNCHANGED
└── vault_audit.py                        # MODIFIED — surface new gate reports + abstraction metric

.agents/skills/
├── scout/SKILL.md                        # MODIFIED — FR-003/FR-004: generalize topics, populate topics_found.new, consume research-plan
├── note-writer/SKILL.md                  # MODIFIED — FR-006: accept batch input; consume research-plan
├── research-plan-narrator/SKILL.md       # NEW — Q1 hybrid: short narrative header on top of deterministic body
└── ... (other skills unchanged)

tests/
├── pipeline/                             # NEW dir mirroring src/research_vault/pipeline/
│   ├── test_research_plan.py             # NEW
│   ├── test_plan_narrator.py             # NEW (mocks the LLM call)
│   ├── test_gates.py                     # NEW — framework
│   ├── test_gates_cycle.py               # NEW — CG-001..CG-007
│   ├── test_gates_step.py                # NEW — SG-001..SG-005
│   ├── test_batch.py                     # NEW
│   ├── test_correction.py                # NEW
│   ├── test_preflight.py                 # NEW
│   ├── test_probes.py                    # NEW
│   ├── test_quality_report.py            # NEW
│   └── test_orchestrator_retry.py        # NEW — incremental retry (Q3)
└── scripts/
    ├── test_preflight_sources.py         # NEW
    ├── test_quality_report.py            # NEW
    ├── test_check_abstraction.py         # NEW
    └── test_probe_runner.py              # NEW
```

**Structure Decision**: Single-project layout (existing `src/research_vault/` package + top-level `scripts/`). Rationale:

- The codebase is already a single Python CLI distributing scripts + `.agents/` skills bundled into the wheel via `tool.hatch.build.targets.wheel.force-include`. There is no frontend/backend split, no mobile target, no separate API service.
- All new code falls under `src/research_vault/pipeline/` (where `orchestrator.py`, `cycle_runner.py`, `coverage.py`, `preconditions.py`, `source_manager.py` already live) or `scripts/` (where `topic_harvest.py`, `validate_vault.py`, `vault_audit.py` already live). The new modules are siblings of existing modules, following established naming and import patterns.
- Tests follow the existing split: pipeline-internal logic in `tests/pipeline/` (new directory mirroring the pipeline package), top-level CLI scripts in `tests/scripts/` (existing convention).
- The package rename to `research_framework` is intentionally **not** included in this feature — the constitution v1.3.1 Sync Impact Report keeps it deferred to its own roadmap PR.

## Complexity Tracking

> Constitution Check passed without violations. No entries required.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| _none_    | _n/a_      | _n/a_                               |
