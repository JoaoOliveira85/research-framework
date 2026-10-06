# Implementation Plan: Source Manager Correctness (029)

**Branch**: `029-source-manager-correctness` | **Date**: 2026-06-03 | **Spec**: `specs/029-source-manager-correctness/spec.md`
**Input**: Spec (clarified Session 2026-06-03) + a code audit at the 053 base that re-verified both bugs present and read `pipeline/source_manager.py` (`record_cycle`, `_count_notes_referencing`, `mark_degraded`) + `pipeline/_cycle_helpers.py` (`notify_required_source_degraded`).

## Summary

Fix two confirmed silent correctness bugs in the source-manager + tighten the test that hides one of them. **Bug 1**: `notify_required_source_degraded` calls `mark_degraded` with 2 args (needs 3 — `vault_dir` is already in scope) inside a too-broad `try/except`, so `source-incidents.md` is never written. **Bug 2**: `record_cycle` counts `notes_generated` by substring-matching a source URL/name against note **file paths** instead of reading each note's frontmatter `source_urls`, corrupting `sources.db` metrics and inflating `consecutive_empty_cycles` → premature auto-archival. Fixes: a one-line arity correction + narrowed except (FR-001); route both `notes_generated` and `notes_referencing` through one frontmatter predicate using a new `normalize_source_url()` (FR-002/003); keep the working JSON sidecar AND fix the markdown log, append-only with resolution lines (FR-001a/006/007); a cumulative, idempotent reconciliation script for already-corrupted vaults (FR-008); and a regression test that exercises the real 3-arg path with **no arity monkeypatch** (FR-005).

## Technical Context

**Language/Version**: Python 3.11.
**Primary Dependencies**: stdlib (`sqlite3`, `pathlib`, `urllib.parse` for normalization, `datetime`) + `pyyaml` (already a dep, for frontmatter). **No new runtime dependency** (Principle V).
**Storage**: existing `<vault>/_pipeline/sources.db` (SQLite) + `<vault>/_pipeline/source-incidents.md` (markdown) + the existing `cycle-NNN-source-incidents.json` sidecar.
**Testing**: `pytest` with `tmp_path` vault fixtures (build_minimal_vault). New `tests/pipeline/test_source_manager_correctness.py`.
**Target Platform**: macOS/Linux (per spec 009 portability).
**Project Type**: single project — surgical edits to two existing pipeline modules + one new script + one new test module.
**Performance Goals**: attribution scan is per-cycle over `notes_created` (small N); no hot-path concern. Reconciliation script is one-shot.
**Constraints**: must NOT regress the working JSON sidecar; must preserve `_count_notes_referencing`'s skip-don't-raise behaviour on malformed notes; the FR-005 test must FAIL if the FR-001 fix is reverted (SC-004).
**Scale/Scope**: ~2 edited modules (~40 changed LOC), 1 new ~120-LOC script, 1 new test module (~8 tests). No schema change to `sources.db`.

## Constitution Check

*GATE: must pass before Phase 0. Re-checked after Phase 1.*

| Principle | Assessment |
|---|---|
| **I. Script-Validated Quality Gates (NON-NEGOTIABLE)** | ✅ FR-008 reconciliation script has `--dry-run`/`--apply` + zero-false-positive acceptance; all fixes land behind deterministic pytest. |
| **III. Test-First (TDD — NON-NEGOTIABLE)** | ✅ Both bugs get a RED test first: (a) FR-005 asserts `source-incidents.md` is created end-to-end (fails today); (b) the attribution test asserts exact per-source counts (fails today). SC-004 mandates the revert-proves-it check. |
| **IV. Agent-Script Separation** | ✅ Pure pipeline/script correctness — no agent dispatch involved. |
| **V. Offline-First, No New Deps** | ✅ stdlib + existing pyyaml only. |
| **VI. Two-Tier Citation / IX. Vault-First** | ✅ Reinforces Principle IX — `notes_generated` now honours the `source_urls` Tier-2 citations that are the citation system's backbone. |
| **VIII. No Placeholders in Deliverables** | ✅ Real fixes; the reconciliation script is functional, not a stub. |
| **X. Vault History is Append-Only Git (NON-NEGOTIABLE)** | ✅ N/A to code; note that `source-incidents.md` being append-only (FR-007) is thematically aligned but is a vault artifact written under the normal cycle commit. |

**Result: PASS — no violations.**

## Project Structure

### Documentation (this feature)
```text
specs/029-source-manager-correctness/
├── plan.md          # this file
├── research.md      # Phase 0 — decisions D1..D6 (incl. the audit)
├── contracts/
│   └── source-attribution.contract.md   # normalize_source_url() + source-incidents.md format
├── quickstart.md    # reproduce both bugs; run the reconcile script
└── tasks.md         # Phase 2 (/speckit.tasks)
```

### Source touched (repository root)
```text
src/research_framework/pipeline/source_manager.py
  • record_cycle()            — FR-002: replace path-substring count with frontmatter predicate (per-cycle, notes_created)
  • _count_notes_referencing  — FR-003: refactor matching into shared _note_cites_source(fm, name, url)
  • normalize_source_url()    — FR-003: NEW stdlib helper (urllib.parse)
  • mark_degraded()           — FR-007: add resolved-line append support (new mark_resolved() or reason-typed)
src/research_framework/pipeline/_cycle_helpers.py   (or pipeline/_helpers/* after 049)
  • notify_required_source_degraded — FR-001: 3-arg call + narrowed except; emit a Resolved line on recovery
scripts/reconcile_source_metrics.py                 — FR-008: NEW one-shot reconciler — un-archive still-cited sources + reset empty-streak (--dry-run/--apply)
tests/pipeline/test_source_manager_correctness.py   — FR-005: NEW regression module (no arity monkeypatch)
# Update any existing test that monkeypatches a 2-arg mark_degraded lambda.
```

## Phase 0 — Research (→ research.md)
Decisions **D1–D6**: the audit (both bugs confirmed + the JSON-sidecar discovery); the one-line arity fix + except-narrowing rationale; the shared `_note_cites_source` predicate (reuse over duplicate); `normalize_source_url()` canonicalization rules (strip fragment/trailing-slash, keep query); the append-only incidents log + recovery line; the cumulative (not per-cycle-rebuild) reconciliation; and the 049 import-path sequencing.

## Phase 1 — Design
- `contracts/source-attribution.contract.md`: the exact `normalize_source_url()` input→output table, the `_note_cites_source` truth table (URL-match / name-fallback / malformed-skip), and the `source-incidents.md` line grammar (degraded + resolved).
- `quickstart.md`: how to reproduce each bug on a `tmp_path` vault before the fix, and run `reconcile_source_metrics.py --dry-run` against a corrupted fixture.

## Complexity / risks
- **049 import-path drift** (the only cross-spec coupling). Mitigation: rebase onto post-049 `main`; the test imports the function from its final module. Recorded in spec Dependencies.
- **Narrowing the `try/except` (FR-001)** could surface a previously-swallowed *runtime* error in the field. Mitigation: catch `OSError` (markdown write) narrowly; let `TypeError` propagate (it's the bug). Unit-test both branches.
- **Tightening attribution changes counts** on existing vaults (some sources may have been over-counted by path coincidence). This is the *point*, but it shifts archival decisions — hence FR-008 reconciliation + the zero-false-positive dry-run acceptance (SC-005).
- **`record_cycle` has two call shapes** (`notes_dir` optional). The FR-002 count needs each note's frontmatter, so it requires resolving `notes_created` paths to readable files; confirm callers pass resolvable paths (research D3).
