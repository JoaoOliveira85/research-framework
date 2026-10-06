# Implementation Plan: Acceptance harness

**Branch**: `063-acceptance-harness` | **Date**: 2026-06-05 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/063-acceptance-harness/spec.md`
**Target ship**: **1.0.0rc3** (rc3 hardening wave; full §4 scope per operator decision 2026-06-05)

## Summary

Turn "the evaluator caught the rc1 defects by going off-script" into "the framework
fails the build." Ship a deterministic, LLM-call-free **`./vault acceptance`** verb
(US5/Q1) that runs a generic §4.1 gate set over artifacts the framework already
emits, reconciles the shipped source-ledger against note citations (US2), grades
spec-053 authority + spec-055 credibility (US3), and emits a per-vault scorecard
(FR-006). Domain probes move in-vault (US4/Q3); the domain pack shrinks to domain
checks.

Phase-0 found that **every primitive this needs already exists** — the work is
composition, not new infrastructure:

| FR | What | Primary code target (verified path) |
| --- | --- | --- |
| **FR-001** | §4.1 generic gate set (6 gates) behind `./vault acceptance` | `cli/acceptance.py` (new `_cmd_acceptance`) + `cli/_parser.py` verb (mirror `status`/`digest`, :381/:386) + `templates/vault-script.sh.j2` shim case (:117 `status)`) |
| **FR-002** | Phase-2B reads shipped ledger + cross-checks vs citations | `cli/acceptance.py` consumes `scripts/source_ledger.py` (Verdict state machine, `sources.db`/scout/research/quality joins) + note `source_urls`; pairs with the **048-v2 amendment** |
| **FR-003** | Grade 053 authority/trunk + 055 credibility/coi | `cli/acceptance.py` uses `pipeline/source_authority.build_source_role_index` + `vault/credibility.{citation_credibility,citation_coi,resolve_role}` |
| **FR-004** | Domain probes rebalanced (GOLD anchors + breadth) | in-vault `_pipeline/acceptance/` probe pack (data, domain-owned) + shrunk `codebase-vault-acceptance-probes.md` |
| **FR-005** | Generic/domain split; generic gates framework-resident | generic = `cli/acceptance.py`; domain = in-vault `_pipeline/acceptance/` (Q3) |
| **FR-006** | Per-vault scorecard artifact | `_pipeline/acceptance/REPORT-<date>.md` + `report-<date>.json` (contract) |

Three gates **consume sibling rc3 work** (the dependency that orders this spec last):
gate 1 (no rejected notes) + gate 2 (no dup files) reuse spec **062**'s invariant +
detector; gate 4 (run-completion) consumes spec **061** FR4's run-report `cycle_budget`
provenance; gate 5 (cost) consumes the spec **028 amendment**'s codex telemetry (and
FAILs loud on `$0` even without it). US2 pairs with the **048-v2 amendment**.

## Technical Context

**Language/Version**: Python 3.11+ (per `pyproject.toml`); Bash for the shim verb.
**Primary Dependencies**: stdlib + existing only — `pyyaml ≥ 6.0`, `sqlite3` (stdlib,
read `sources.db`). **No new runtime dependencies** (Principle V). **Zero LLM calls**
— the generic gates are deterministic (Principle IV alignment is the whole point).
**Storage**: filesystem under vault root. New artifact: `_pipeline/acceptance/
REPORT-<date>.md` + `report-<date>.json` (FR-006, `schema_version: "1.0"`). Domain
probe pack lives in-vault under `_pipeline/acceptance/` (FR-004/005). Reads existing:
run-report, `cycle-NNN-source-ledger.json` (via `scripts/source_ledger.py`),
`sources.db`, note frontmatter, git state.
**Testing**: pytest, seven-tier pyramid (ADR-0008). The headline test reproduces the
rc1 off-script findings deterministically against a snapshot fixture (SC-001).
**Target Platform**: macOS / Linux dev + CI.
**Project Type**: single-project Python CLI + Jinja2-templated vault scaffold.
**Performance Goals**: the gate run is O(notes + cycles); a few file reads + one
`sqlite3` query + one `git status`. Sub-second on a typical vault; bounded by the
ledger join (already used in `scripts/source_ledger.py`).
**Constraints**: 063 is **post-run acceptance over a real vault**; it does **not**
touch the spec-022 build-time fixture baselines (they are complementary — see spec
§"Relationship to existing specs"). FR-001 gates must run with zero LLM dispatch
(tier-2 dispatch guard stays green). Auto-run at clean exit (Q4) must not turn a
clean run into a failing one for a WARN-level finding (only FAIL gates set non-zero).
**Scale/Scope**: ~4 new source files + verb wiring + a snapshot fixture, ~1.5 days
(the long pole of the wave). Adds ~30–40 tests.

### Resolved unknowns (full detail in research.md)

- **D1 — verb surface.** New `acceptance` subparser in `cli/_parser.py` + handler in
  new `cli/acceptance.py`, mirroring the recently-added `status`/`digest` verbs; the
  shim `case` (:68) gets an `acceptance)` entry mirroring `status)` (:117). `./vault
  regenerate-shim` re-renders existing vault shims to pick it up.
- **D2 — the ledger is real + first-class.** `scripts/source_ledger.py` exists (048-v2
  MVP): `Verdict` enum (USED/ACCESS_FAIL/PIPELINE_DROP/QUALITY_REJECT/NOT_REACHED/
  SKIPPED_RELEVANCE), `resolve_verdict`/`collapse_verdict`, joins scout + `sources.db`
  + research + quality. US2 imports/invokes it instead of hand-joining.
- **D3 — citation join is the missing piece.** `source_ledger.py` has `_source_urls()`
  (spec sources → host map) but does **not** join the *notes'* cited `source_urls`.
  That join is the 048-v2 amendment; US2 (harness side) cross-checks the result. The
  amendment emits `LEDGER_DISAGREEMENT`; US2 reports it as the finding.
- **D4 — authority/credibility primitives exist.** `source_authority.build_source_role_index`
  gives role/priority/derived-trunk (053); `credibility.citation_credibility` /
  `citation_coi` / `resolve_role` give tier + COI (055). US3 calls them per citation;
  no new model code.
- **D5 — generic vs domain boundary.** Generic gates are pure framework code
  (`cli/acceptance.py`); domain probes are vault-resident data under
  `_pipeline/acceptance/` that the verb discovers + runs (or references). The split is
  expressed by *location*, satisfying "framework owns generic, vault owns domain".

## Constitution Check

*GATE: evaluated against constitution v1.4.0.*

| Principle | Verdict | Notes |
| --- | --- | --- |
| **I. Script-Validated Quality Gates** | ✅ PASS (reinforces) | 063 *is* a script-validated gate surface. FAIL gates → non-zero exit (Q2). No existing gate semantics changed; the spec-022 baselines are untouched. |
| **II. Phase Sequencing** | ✅ PASS | The acceptance run is a post-cycle/post-run step (Q4 auto-run at clean exit); on-demand otherwise. No phase reordering. |
| **III. Test-First (TDD)** | ✅ PASS | Each gate ships with a test; the SC-001 snapshot fixture drives the headline RED→GREEN. |
| **IV. Agent-Script Separation** | ✅ PASS (reinforces) | The generic gates are deterministic + **LLM-call-free** by design; the tier-2 dispatch guard stays green. |
| **V. Offline-First, No External Persistence** | ✅ PASS | No new deps; `sqlite3` is stdlib; scorecard is local-only. |
| **VI / VIII / IX / X** | ✅ PASS (reinforces) | The gates *detect* violations of VI (dup notes), IX (rejected-note citation), X (untracked/dup commits). 063 detects; 062 prevents. |
| **VII. External Sources Mandatory** | ✅ N/A | Untouched (US3 grades sourcing but doesn't change the mandate). |

**Ask-First items:**
1. **New `./vault acceptance` verb** — a new CLI surface. Authorised by clarify Q1.
2. **Auto-run at clean exit** (Q4) — adds a finalise-time step that can set a non-zero
   acceptance status. Authorised by Q4; scoped so only FAIL gates block, WARN is
   advisory (Q2). Does not change the run's own exit-code model (0/1/2); the scorecard
   verdict is recorded separately.

**Gate result: PASS.** Complexity Tracking empty.

### Post-Design Re-check (after Phase 1)

After `contracts/` + `data-model.md`: no new dependency, no new principle. The
scorecard JSON carries `schema_version` per spec-036 cross-boundary discipline. The
one design subtlety — generic gates must not import vault domain probe code at run
time (D5; they only *discover* in-vault probe data) — is recorded so the
framework/vault boundary stays clean. Verdict remains **PASS**.

## Project Structure

### Documentation (this feature)

```text
specs/063-acceptance-harness/
├── plan.md          # This file
├── spec.md          # Feature spec (clarified 2026-06-05, full §4)
├── research.md      # Phase 0 — decisions D1–D5
├── data-model.md    # Phase 1 — GateResult, Scorecard, ledger-reconciliation view
├── quickstart.md    # Phase 1 — run the gates on the rc1 snapshot; reproduce findings
├── contracts/
│   ├── generic-gates.contract.md        # the §4.1 six-gate set (inputs, severity, pass/fail)
│   └── acceptance-scorecard.schema.json # FR-006 report-<date>.json schema
└── tasks.md         # Phase 2 (/speckit.tasks — NOT created here)
```

### Source Code (repository root) — files touched, by FR

```text
src/research_framework/
├── cli/
│   ├── acceptance.py        # FR-001/002/003/006 (new): _cmd_acceptance — the 6 gates,
│   │                        #   ledger reconciliation, authority/credibility grading, scorecard
│   └── _parser.py           # FR-001: `acceptance` subparser (mirror status/digest)
├── pipeline/
│   ├── source_authority.py  # FR-003: (read-only) build_source_role_index — role/priority/trunk
│   └── orchestrator.py      # FR-001/Q4: invoke acceptance at clean-exit finalise (record scorecard)
├── vault/
│   └── credibility.py       # FR-003: (read-only) citation_credibility / citation_coi / resolve_role
└── (US2 imports scripts/source_ledger.py — see note)

scripts/
└── source_ledger.py         # FR-002: (consumed; the 048-v2 amendment adds the citation join)

templates/
└── vault-script.sh.j2       # FR-001: `acceptance)` shim case (mirror status))

tests/
├── cli/
│   ├── test_acceptance_gates.py          # FR-001: each of the 6 gates pass/FAIL
│   ├── test_acceptance_ledger_recon.py   # FR-002: ledger↔citation disagreement is the finding
│   ├── test_acceptance_grading.py        # FR-003: authority/trunk + credibility/coi grading
│   └── test_acceptance_scorecard.py      # FR-006: scorecard artifact shape (contract)
└── fixtures/acceptance/
    └── rc1-codebase-snapshot/            # SC-001 snapshot: reproduces 3.2–3.5 deterministically
```

> **Boundary note (D5):** `cli/acceptance.py` is in `research_framework` (installed
> package) but imports `scripts/source_ledger.py` — the same maintainer-script import
> pattern the pipeline already uses (`source_bridge` lookup prefers `<vault>/scripts/`).
> The plan keeps the ledger logic in `scripts/` (its 048-v2 home) and the harness
> *invokes* it, so the two stay in lockstep.

## Phase Sequencing for implementation (dependency-ordered)

063 lands **after** 061/062/028-amendment exist (it consumes their signals).
Recommended `/speckit.tasks` ordering:

1. **Snapshot fixture** (`tests/fixtures/acceptance/rc1-codebase-snapshot/`) — the
   SC-001 RED target: rejected notes, ` 2.md` dups, $0 telemetry, 6/12 truncation,
   ledger/citation mismatch. Build it first so every gate has a failing case.
2. **FR-006 scorecard contract + writer** (`contracts/acceptance-scorecard.schema.json`
   + the `report-<date>.{md,json}` writer) — the output shape everything fills.
3. **FR-001 generic gates** (`cli/acceptance.py` + verb + shim) — gates 1–6, reusing
   062's detector (gate 1/2), 061's `cycle_budget` (gate 4), 028-amendment telemetry
   (gate 5). Gate 5 FAILs loud on `$0` even pre-028-amendment.
4. **FR-002 ledger reconciliation** — invoke `scripts/source_ledger.py`; cross-check
   vs note `source_urls`; report `LEDGER_DISAGREEMENT` as the finding (pairs with the
   048-v2 amendment).
5. **FR-003 authority/credibility grading** — per-citation grading via
   `source_authority` + `credibility`; flag authority inversions + credibility tiers.
6. **FR-004/FR-005 split** — move domain probes in-vault (`_pipeline/acceptance/`);
   shrink the domain pack to domain probes; wire Q4 auto-run at clean exit.

## Complexity Tracking

> No Constitution Check violations require justification. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
