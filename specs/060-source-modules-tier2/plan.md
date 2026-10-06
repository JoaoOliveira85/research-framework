# Implementation Plan: Source-Module Tier 2+ Port Wave (Spec 060)

**Branch**: `060-source-modules-tier2` · **Date**: 2026-06-03
**Spec**: [spec.md](./spec.md) · **Research**: [research.md](./research.md) · **Contracts**: [contracts/](./contracts/)
**Status**: planned (post-clarify Q1–Q5). Governance umbrella — **no new `src/` package**.

## Summary

Formalize the post–Tier-1 source-module port wave as **governance artifacts** only: a
weighted prioritization rubric, a normative per-module acceptance-bar contract, a
020-amendment decision procedure, and an authoritative tier ladder. Then execute **one
kickoff port** (`hackernews`) under the spec-020 five-file template with spec-051
`preflight()`, hermetic contract tests, and the spec-022 hold-or-improve gate. Individual
ports do **not** get speckit sub-specs; spec 038 resilience polish sequences after the bar
is validated on the first Tier-2 ship.

## Technical Context

- **Language**: N/A for governance phases (Markdown contracts). Kickoff port: Python 3.11+
  per constitution.
- **Primary Dependencies**: **None new** for governance. Kickoff port: stdlib only
  (Principle V — Tier 2 hard gate). Existing: `pyyaml`, `jinja2` (framework; unchanged).
- **Storage**: Authoritative ladder + rubric live under `specs/060-source-modules-tier2/`;
  shipped modules under `src/research_framework/modules/<name>/` (Tier-1 precedent).
- **Testing**: Governance = checklist review + analyze pass. Each port = hermetic contract
  tests + `build.sh --quality` (spec 022 / Principle I).
- **Target Platform**: Maintainer workflow + vault `modules/` sync from stock templates.
- **Project Type**: Governance docs + one reference module port (not a framework feature flag).
- **Constraints**: No speckit per module; no 020 re-spec; Tier 4/Parked ladder-only;
  Tier 3 defer-by-default on deps.
- **Scale/Scope**: 6 Tier-2 candidates ranked; 1 kickoff port in this spec's implement scope;
  remaining Tier-2 ports repeat the same bar without new speckit specs.

## Constitution Check

| Principle | Status | Note |
|-----------|--------|------|
| **I — Script-Validated Quality Gates** | ✅ PASS | FR-007 / acceptance bar §3: every port runs `build.sh --quality`; hold-or-improve is the ship gate. |
| **III — Test-First** | ✅ PLANNED | Kickoff port: contract tests before extractor logic (Tier-1 precedent). |
| **IV — Agent-Script Separation** | ✅ PASS | Unchanged — subprocess-isolated extractors per 020. |
| **V — Offline-First / no new runtime deps** | ✅ PASS | Tier 2 = stdlib-only; Tier 3+ optional-extra only via amendment gate (documented in research.md). |
| **VI — No Duplicate Notes** | N/A | Not touched. |
| **VII — External Sources Mandatory** | ✅ PASS | Acceptance bar requires modules to emit consultable signals; skip reasons logged per 020. |
| **IX — Vault-First Citation** | N/A | Port modules feed sources; citation rules unchanged. |
| **X — Vault History Git** | N/A | Port PRs are framework repo commits, not vault mutations. |

**Verdict**: PASS — no violations; no Complexity-Tracking entries.

## Project Structure

### Documentation (this feature)

```text
specs/060-source-modules-tier2/
├── spec.md                                          # IMPLEMENT-READY
├── plan.md                                          # this file
├── research.md                                      # rubric + dependency table + Tier-2 ranking
├── contracts/
│   ├── module-port-acceptance-bar.contract.md       # fixed pass/fail bar (FR-002, FR-007)
│   ├── 020-amendment-gate.contract.md               # amend-020 vs defer (FR-003, FR-004 deps)
│   └── tier-ladder.contract.md                      # authoritative coverage list (FR-005)
├── checklists/requirements.md
├── tasks.md
└── analyze-2026-06-03.md
```

### Source code (kickoff port only — not owned by governance phases)

```text
src/research_framework/modules/hackernews/   # five-file template (new)
tests/modules/test_hackernews_contract.py    # hermetic contract tests (new)
```

**Structure decision**: Governance stays in the spec dir; the kickoff module follows the
shipped Tier-1 layout (`manifest.yaml`, `extractor.py`, `preflight.py`, `few-shot.md`,
`README.md`, `sources.yaml.template`).

## Phase 0 — Research ✅

[research.md](./research.md): Q1–Q5 locked; Tier-2 ranking table; dependency-exception
decision matrix per tier; 038 sequencing note.

## Phase 1 — Design ✅

| Contract | Owns |
|----------|------|
| [module-port-acceptance-bar.contract.md](./contracts/module-port-acceptance-bar.contract.md) | Five-file template, hermetic tests, 022 gate, 051 preflight, auth/dep rules |
| [020-amendment-gate.contract.md](./contracts/020-amendment-gate.contract.md) | Trigger conditions, amend-020 vs defer vs optional-extra path |
| [tier-ladder.contract.md](./contracts/tier-ladder.contract.md) | Module inventory + status enum + Tier-2 rationales |

## Phase 2 — Task strategy (for `/speckit.implement`)

1. **Governance first** (parallelizable): rubric → acceptance contract → amendment gate →
   ladder (source of truth).
2. **Kickoff port** (`hackernews`): contract tests (fail first) → five-file module →
   preflight → `build.sh --quality` green.
3. **Doc-sync** (separate PR convention): mirror ladder into `docs/ROADMAP.md` — out of scope
   for this spec dir edit but listed in tasks as post-ship hygiene.
4. **038 handoff**: after first Tier-2 ship, open/schedule spec 038 clarify — not blocking 060.

## Complexity & Risks

| Risk | Mitigation |
|------|------------|
| Per-port bar drift | Single normative contract; PR template references contract § checklist |
| Quiet 020 erosion | Amendment gate forbids local workarounds; defer explicitly |
| Tier-3 dep pressure | Defer-by-default + optional-extra gate; no core dep creep |
| 038 scope creep into 060 | FR-008 + analyze cross-check; 038 items explicitly out of acceptance bar |
| ROADMAP / ladder drift | `tier-ladder.contract.md` is authoritative; doc-sync task flips ROADMAP mirror |
