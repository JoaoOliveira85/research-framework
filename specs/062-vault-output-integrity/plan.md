# Implementation Plan: Vault output integrity on constrained exit

**Branch**: `062-vault-output-integrity` | **Date**: 2026-06-05 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/062-vault-output-integrity/spec.md`
**Target ship**: **1.0.0rc3** (rc3 hardening wave; runs before the remaining validation runs)

## Summary

Three independent correctness fixes that each *uphold* an existing principle
(IX / VI / X), surfaced by the codebase-vault rc1 constrained-exit run. Phase-0
found that two of the three have an existing seam to extend rather than build:

- **FR1 (rejected-note quarantine)** — the orchestrator **already** quarantines
  notes (`_quarantine_orphan_note` / `_quarantine_out_of_scope_notes` →
  `<vault>/_pipeline/quarantine/`, research.md **D1**). Since indexing only scans
  `data_vault/` (`steps/research.py:171`, `_helpers/_io.py:43`), moving a note into
  `_pipeline/quarantine/` makes it uncitable/unindexed for free. FR1 = a new
  `_quarantine_rejected_notes()` sweep in `_finalise` (runs on ANY exit) that mirrors
  the out-of-scope sweep + records the count in the run report.
- **FR2 (no dup files / no dup commits / no untracked)** — `commit_cycle` →
  `_stage_and_commit` already does `git add -A` (D2), so untracked `… 2.md` files
  imply either a **post-commit write** or a **second `commit_cycle` for the same
  cycle** (the two `research: cycle 6` commits). FR2 = per-cycle commit idempotency +
  a post-commit untracked-under-`data_vault/` assertion + a `validate_vault.py`
  ` N.md`/content-hash duplicate detector.
- **FR3 (acronym links resolve)** — `wikilinks.py` only fixes **case** mismatch
  today (D3); there is **no** acronym→full-title resolution and notes carry **no**
  `aliases` frontmatter. FR3 adds a deterministic **title-derived acronym map** that
  (a) extends `wikilinks.py` to resolve `[[OECDH]]` → canonical stem and (b) generates
  a redirect stub per acronym. Source = the note titles (deterministic), **not** the
  spec (no acronyms field exists — research.md D4 overrides the spec's "declared in the
  spec" wording per the spec's own Phase-0 escape hatch).

No new runtime dependency (Principle V); no ADR (correctness within existing
principles, cf. ADR-0005 for cycle-time wikilink normalisation).

| FR | What | Primary code target (verified path) |
| --- | --- | --- |
| **FR1** | Quarantine still-`rejected` notes on any exit; headline the count | `pipeline/orchestrator.py` (`_quarantine_rejected_notes` in `_finalise`, mirror `:192`) + `pipeline/verifier.py` (status source) + `pipeline/run_report.py` (`rejected_unresolved`) |
| **FR2** | No ` N.md` fork; one commit/cycle; zero untracked `data_vault/` at commit | `pipeline/vault_commit.py` (`commit_cycle:553` idempotency + untracked assertion in `_stage_and_commit:731`) + `scripts/validate_vault.py` (dup detector) |
| **FR3** | Acronym wikilinks resolve for every note acronym (deterministic) | `pipeline/wikilinks.py` (acronym-map resolution + redirect-stub generation) + `scripts/validate_vault.py` (dead-acronym-link class → 0) |

## Technical Context

**Language/Version**: Python 3.11+ (per `pyproject.toml`).
**Primary Dependencies**: stdlib + existing only — `pyyaml ≥ 6.0` (frontmatter),
`subprocess`/`git` (vault_commit). **No new runtime dependencies** (Principle V).
**Storage**: filesystem under vault root. FR1 moves files into the **existing**
`_pipeline/quarantine/` dir (no new artifact) + appends a research-backlog pointer
(`_pipeline/research-backlog.md`, existing). FR2 touches git state only. FR3 may
create redirect stub notes under `data_vault/` (counted, not fuel — see Principle
VIII note below).
**Testing**: pytest, seven-tier pyramid (ADR-0008). New tier-3 pipeline suites +
`validate_vault.py` exit-code tests on fixtures.
**Target Platform**: macOS / Linux dev + CI.
**Project Type**: single-project Python CLI + Jinja2-templated vault scaffold.
**Performance Goals**: FR1 sweep + FR3 acronym map are O(notes) once at finalise/
cycle-end; no per-call hot-path cost. FR2 untracked check is one `git status
--porcelain` per cycle commit.
**Constraints**: FR1 clean-exit behaviour MUST be unchanged (the correction/rewrite
loop still clears rejections first; the sweep then finds 0). FR3 redirect stubs MUST
NOT trip the spec-022 quality harness or Principle-VIII stub-as-fuel accounting
(they are graph-resolution aids, classified distinctly from research stubs).
**Scale/Scope**: ~6 source files + `validate_vault.py`, ~1 day. Adds ~25 tests.

### Resolved unknowns (full detail in research.md)

- **D1** — quarantine seam exists (`orchestrator._quarantine_out_of_scope_notes:192`);
  indexing scans only `data_vault/`, so quarantine = move out of corpus, no indexer
  change. Rejection data already collected (`steps/research.py:353 notes_rejected`).
- **D2** — `commit_cycle` → `_stage_and_commit` does `git add -A`; the `… 2.md`
  untracked files therefore came from a post-commit write or a duplicate
  `commit_cycle` call (the second `research: cycle 6`). Fix = idempotent per-cycle
  commit + post-commit untracked assertion (fail-loud, not silent).
- **D3** — `wikilinks.py::auto_fix_moved_wikilinks` handles **case** only; no acronym
  path. Extend it (same cycle-time hook, ADR-0005 lineage).
- **D4** — there is **no** acronyms/aliases field in `spec/schema.py` and no `aliases`
  note frontmatter. Authoritative deterministic source = **title-derived acronym
  extraction** (∪ optional explicit note `aliases:` if a note declares one). This
  overrides the spec's "declared in the spec" phrasing (the spec authorises Phase-0
  to win on path/source).

## Constitution Check

*GATE: evaluated against constitution v1.4.0.*

| Principle | Verdict | Notes |
| --- | --- | --- |
| **I. Script-Validated Quality Gates** | ✅ PASS | FR2 adds a *new* gate (untracked-under-data_vault → constrained); FR3 makes `validate_vault.py` return 0 on the acronym class. No existing gate semantics changed. |
| **II. Phase Sequencing** | ✅ PASS | FR1 sweep runs at finalise (cycle/run boundary); FR3 at the existing cycle-end wikilink hook. No reordering. |
| **III. Test-First (TDD)** | ✅ PASS | Each FR ships its test file with/before impl. |
| **IV. Agent-Script Separation** | ✅ PASS | All three are deterministic script-side fixes; FR3 is explicitly *not* LLM-driven (D4). |
| **V. Offline-First, No External Persistence** | ✅ PASS | No new deps; quarantine + backlog are local files. |
| **VI. No Duplicate Notes** | ✅ PASS (reinforces) | FR2 *enforces* VI (no ` N.md` fork; dedup detector). FR3 redirect stubs are single-purpose alias nodes, not content duplicates. |
| **VII. External Sources Mandatory** | ✅ N/A | Untouched. |
| **VIII. No Placeholders / Stub-as-Fuel** | ✅ PASS | FR1 quarantined notes leave a backlog pointer (fuel, not silent drop). FR3 redirect stubs are graph-resolution nodes, classified distinctly from research stubs (must not be counted as research fuel or coverage). |
| **IX. Vault-First Citation** | ✅ PASS (reinforces) | FR1 *enforces* IX — a rejected note can no longer be cited by `/ask` / `/write`. |
| **X. Vault History is Append-Only Git** | ✅ PASS (reinforces) | FR2 *enforces* X — zero untracked `data_vault/` content; one commit/cycle. Extends spec-050 coverage. |

**Ask-First items:**
1. **FR2 new gate** (untracked-under-`data_vault/` → constrained exit) — adds a
   validation exit path. Authorised by the spec (FR2 #2) + upholds Principle X; no new
   exit *code* (reuses constrained=1).

**Gate result: PASS.** Complexity Tracking empty.

### Post-Design Re-check (after Phase 1)

No new dependency, no new principle. FR3's redirect-stub classification is the one
design subtlety — recorded in data-model.md so the spec-022 harness + Principle-VIII
accounting treat alias nodes correctly. Verdict remains **PASS**.

## Project Structure

### Documentation (this feature)

```text
specs/062-vault-output-integrity/
├── plan.md          # This file
├── spec.md          # Feature spec (clarified 2026-06-05)
├── research.md      # Phase 0 — decisions D1–D4
├── data-model.md    # Phase 1 — quarantine record, rejected_unresolved, acronym map, redirect stub
├── quickstart.md    # Phase 1 — reproduce each defect; prove the fix
└── tasks.md         # Phase 2 (/speckit.tasks — NOT created here)
```

### Source Code (repository root) — files touched, by FR

```text
src/research_framework/
├── pipeline/
│   ├── orchestrator.py     # FR1: _quarantine_rejected_notes() in _finalise (mirror :192); backlog pointer
│   ├── verifier.py         # FR1: (read-only) verifier_status is the rejection source
│   ├── run_report.py       # FR1: rejected_unresolved count headlined
│   ├── vault_commit.py     # FR2: commit_cycle idempotency (:553) + untracked-data_vault assertion (:731)
│   └── wikilinks.py        # FR3: acronym-map resolution + redirect-stub generation (extends auto_fix_moved_wikilinks)
└── (no new modules)

scripts/
└── validate_vault.py       # FR2: ` N.md`/content-hash dup detector; FR3: dead-acronym-link class → 0
                            #      (vault-side copies regenerate from this maintainer source)

tests/
├── pipeline/
│   ├── test_rejected_note_handling.py     # FR1: constrained exit → 0 indexed rejected; rejected_unresolved=K
│   ├── test_no_duplicate_notes.py         # FR2: re-emit overwrites; no ` 2.md`; one commit/cycle
│   ├── test_vault_commit_no_untracked.py  # FR2: zero untracked data_vault/ after a writing cycle
│   └── test_acronym_alias_coverage.py     # FR3: N acronyms → N resolvable refs; deterministic
└── scripts/
    └── test_validate_vault_integrity.py   # FR2/FR3: dup + dead-acronym classes; exit codes
```

**Structure Decision**: single-project layout, all changes in-place — no new modules.
FR1/FR2/FR3 each extend an existing seam (quarantine, commit, wikilink-fix).

## Phase Sequencing for implementation (dependency-ordered)

FRs are independent. Recommended `/speckit.tasks` ordering:

1. **FR1** (≈0.4d) — `_quarantine_rejected_notes` mirroring `_quarantine_out_of_scope_notes`;
   wire into `_finalise` (runs on every exit); `run_report.rejected_unresolved`; backlog
   pointer; tests. Confirm clean-exit unchanged.
2. **FR2** (≈0.4d) — per-cycle `commit_cycle` idempotency; post-commit untracked
   assertion; `validate_vault.py` dup detector; commit + untracked + validate tests.
3. **FR3** (≈0.4d) — title-derived acronym map in `wikilinks.py`; redirect-stub
   generation (classified per data-model.md); `validate_vault.py` acronym class → 0;
   acronym-coverage tests on a fixture whose titles imply acronyms.

## Complexity Tracking

> No Constitution Check violations require justification. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
