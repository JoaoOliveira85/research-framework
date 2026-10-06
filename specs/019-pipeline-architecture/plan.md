# Implementation Plan: Pipeline Architecture & Seam-Bug Elimination

**Branch**: `019-pipeline-architecture` | **Date**: 2026-05-17 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/019-pipeline-architecture/spec.md`

## Summary

Two surgical changes for 0.2.28:

1. **Extend `./build.sh` smoke gate** to enforce a curated set of tier-1
   and tier-2 contract tests as a shipping precondition (US1). This is
   purely build-system: no runtime code changes, no new dependencies.
2. **Fix four HIGH-severity latent seams** discovered during the
   code-review for spec-019 (US2 / H1–H4): DFS budget cap field
   resolution, v2 `sources_consulted` validation, DFS termination field
   aliasing, and `_resume` Phase 3 completion.

US3–US6 are captured in this spec but deferred — they require a daylight
design pass with the user before implementation.

## Technical Context

**Language/Version**: Python 3.11+ (per `pyproject.toml requires-python = ">=3.11"` and constitution Technology Constraints)
**Primary Dependencies**: Existing only — `jinja2 ≥ 3.1` (prompt templates), `pyyaml ≥ 6.0` (settings + spec frontmatter), `sqlite3` (stdlib, used by `pipeline/source_manager.py`), `pytest` (test runner). **No new runtime dependencies** — Principle V (no new dependencies without justification) is non-negotiable.
**Storage**: Filesystem under vault root. New artifacts: none for 0.2.28. (`_pipeline/vault-blueprint.json` and `_pipeline/consensus/<...>.json` deferred with US3 / US6.)
**Testing**: pytest with `tests/_helpers/fake_agent.py` for deterministic agent stubbing; new contract tests added to `tests/scripts/` and `tests/pipeline/`. Smoke gate (US1) extended via `build.sh`.
**Target Platform**: macOS + Linux dev hosts. CI: GitHub Actions (existing).
**Project Type**: CLI library — single Python project, `src/research_vault/` + `scripts/` + `templates/` + `tests/`. No web/mobile.
**Performance Goals**: Full test sweep stays under 6 min after US1 adds tests to the smoke gate (current: ~5 min, target: ≤ 5.5 min).
**Constraints**: Backwards compat with v0.2.27 vaults (no schema migrations). All new behaviour opt-in via `settings.yaml` keys default-OFF.
**Scale/Scope**: 1128 tests today → ~1145 after US1+US2 (estimate +12 contract tests for the four H-bugs, +5 parameterised spec-shape variants).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution (per `CLAUDE.md`) requires:
- **Principle V (no new runtime deps)**: ✓ Satisfied. No new packages.
- **Code-first / intent-first ordering**: NOT modified in 0.2.28 scope.
  US4 (intent-first) is deferred.
- **Quality gates SG-001..SG-005, CG-001..CG-006**: NOT relaxed. US5's
  optional `sg004.mode: hard` is opt-in; default behaviour preserved.
- **Test-pyramid (018)**: extended, not weakened. New tests go in the
  appropriate tier directory.
- **Naming convention**: snake_case for Python; vault notes follow
  spec's `naming_convention` field.

No constitutional violations.

## Project Structure

### Documentation (this feature)

```text
specs/019-pipeline-architecture/
├── plan.md              # This file
├── spec.md              # Feature specification
└── tasks.md             # /speckit.tasks output (next)
```

Other artifacts (`research.md`, `data-model.md`, `contracts/`) are not
needed: this feature surgically modifies existing modules, doesn't
introduce a new sub-system.

### Source Code (repository root)

```text
src/research_vault/
├── pipeline/
│   ├── preconditions.py          # MODIFIED (already done in 0.2.26)
│   └── ... (no other changes for 0.2.28)
├── cli.py                         # MODIFIED — H4 fix: _resume runs Phase 3
└── ... (no other changes for 0.2.28)

scripts/
└── validate_cycle.py              # MODIFIED — H1 (budget alias resolution),
                                   #            H2 (sources_consulted v2),
                                   #            H3 (termination field aliasing)

templates/prompts/
└── dfs-prompt.md.j2               # MODIFIED — H3 prompt convergence on
                                   #            termination_condition

build.sh                            # MODIFIED — US1: extended smoke gate

tests/
├── scripts/
│   ├── test_validate_cycle_budget_aliases.py     # NEW — H1
│   ├── test_validate_cycle_sources_consulted.py  # NEW — H2
│   └── test_validate_cycle_termination_fields.py # NEW — H3
├── pipeline/
│   └── test_resume_phase3_completion.py          # NEW — H4
├── build/
│   └── test_smoke_gate_enforces_contract_tier.py # NEW — US1
└── _helpers/
    └── vault_factory.py            # MODIFIED — adds dual-shape repo
                                   # variants for parameterised tests
```

## Implementation Phases

### Phase 0 — Research

Not applicable. All four H-bugs were diagnosed during the spec-019 code
review; root causes are known.

### Phase 1 — Design (this document + spec.md)

Done. Spec frozen via clarify session 2026-05-17.

### Phase 2 — Setup (foundational)

- T001: Branch + spec dir already created.
- T002: Skeleton `tests/build/test_smoke_gate_enforces_contract_tier.py`
  (RED).
- T003: Skeleton per-H-bug regression test file (RED × 4).

### Phase 3 — Implementation

US1 (smoke gate extension) and US2 (four H-bug fixes) can be implemented
**in parallel** by separate workers — they touch different files. Within
US2 the four H-bugs are independent.

### Phase 4 — Verification

- T020: full `pytest tests/` sweep — must show ≥ 1128 + 12 passing.
- T021: `./build.sh` runs end-to-end and produces a wheel.
- T022: Smoke gate intentional regression test — delete one of the H
  fixes locally, verify `./build.sh` aborts at the gate (deliberately
  break test scenario; revert before commit).

### Phase 5 — Release

- T030: Bump 0.2.28 in `__init__.py` + `pyproject.toml`.
- T031: CHANGELOG entry under `[Unreleased]` (with explicit pointer to
  spec-019 + the four H-bugs + the gate-extension rationale).
- T032: `./build.sh` to package.

## Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| H1/H2/H3 fix subtly changes validator semantics for an existing vault | HIGH | Each fix has its own regression test that locks the new behaviour AND the backwards-compat behaviour (e.g., H1 accepts both old and new field names) |
| H4 fix (Phase 3 on resume) runs cost-incurring code that wasn't running before | MEDIUM | Phase 3 is read-only (coverage gate, reindex, report) — no agent calls. Cost delta is sub-cent per resume. |
| Extended smoke gate adds tests that are flaky → false-positive aborts | MEDIUM | Only include tests that have been GREEN for ≥ 3 sweeps before adding to the gate. Reject tests requiring network or filesystem locks. |
| US3-US6 deferral leaves user's architectural concerns unaddressed | HIGH | Spec-019 explicitly captures them with full acceptance scenarios; user can drive any of them as separate features in daylight. |

## Out of Scope for 0.2.28

US3 (Vault Blueprint), US4 (intent-first scout), US5 (SG-004 hard
mode), US6 (multi-agent consensus). All in spec-019 but deferred —
see Clarifications session 2026-05-17.
