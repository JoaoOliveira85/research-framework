---
spec_number: 068
title: Coverage counting correctness — digest must reflect note-writer output
status: SHIPPED 1.0.0rc9 (2026-06-15, PR #171, squash 4f467d1) — rc8-wave umbrella #152 (CLOSED). recompute_from_disk + update_after_cycle delegation (FR1), cycle-end WARN-and-trust invariant moved before write_report (FR2), digest/status read the recount (FR3/FR4), build.sh-gated regression guard (FR5). ~14 new tests green; ruff clean. Re-validated on reference-vault-rc7 (status counts 108 notes, no longer 0%).
target_version: 1.0.0rc9 / 1.0.0
created: 2026-06-14
source_input: |
  2026-06-13 rc7 reference-vault validation run (`~/Documents/reference-vault-rc7/`,
  GitHub issue #156, umbrella #152). The run drafted 107 substantive notes
  across 13 numbered categories (concepts/20, databases/13, infrastructure/33,
  etc.), but `./vault digest` reports `0% → 0% (+0%)` for every category
  and lists each as "stagnant" in the Gaps section. The digest — one of
  the v1.0.0 deliverables — is unusable: it tells operators "your vault
  has 0% coverage" no matter how many notes the framework wrote.
---

**Status:** shipped(2026-06-15, PR #171) — **SHIPPED 1.0.0rc9** (2026-06-15, PR #171, squash `4f467d1`; rc8-wave umbrella #152 CLOSED) —
rc8-wave umbrella #152. Coverage recomputed from disk (`recompute_from_disk` +
`update_after_cycle` delegation, FR1); cycle-end WARN-and-trust invariant moved
before `write_report` (FR2); `digest` / `status` read the recount (FR3/FR4);
build-gated regression guard (FR5). ~14 new tests; ruff clean.

# Feature Specification: Coverage counting correctness

**Feature Branch**: `068-coverage-counting-correctness`
**Created**: 2026-06-14

## Clarifications

### Round 1 (resolved 2026-06-15)

**Root cause confirmed by code audit** (`pipeline/coverage.py::update_after_cycle`)
+ live rc7 evidence: `met_count` is **incrementally accumulated from each
cycle's `research_report['notes_created']`** list and **never reconciled with
the on-disk `data_vault/` tree**. The rc7 vault has ~107 notes on disk but
`met_count` sums to ~14 (concepts 2 vs 20 on disk). Crucially the notes'
frontmatter already carries `coverage_category: concepts` matching the target
slug `concepts` exactly — so candidate #1 (frontmatter↔target naming mismatch)
is **ruled out**; the bug is the stale incremental model (candidate #2), with
the `NN - Title` directory vs slug being why any naive disk-walk-by-dir-name
would also miss (candidate #3 is a fix constraint, not the cause).

| Q | Decision | Notes |
| --- | --- | --- |
| **Q1 — root cause + fix direction** | **Recompute coverage by scanning the on-disk `data_vault/` tree and reading each note's `coverage_category` frontmatter** (skipping `note_type: alias` stubs per 062 FR3). The stale per-cycle incremental count is the root cause; the recompute becomes the source of truth. | Makes the undercount structurally impossible. The existing `classify_note_category` resolution (explicit `coverage_category` → keyword overlap → largest-gap round-robin) is reused; only the *driver* changes from "iterate notes_created" to "walk the disk tree". |
| **Q2 — frontmatter vs directory authority** | **Frontmatter `coverage_category` wins**; a disagreement with the on-disk `NN - Title` directory is logged as a WARN (never silently dropped). | Frontmatter is the explicit signal the note-writer set intentionally; the directory is a rendering convenience. Matches 066's "explicit signal wins" stance. |
| **Q3 — migration / source of truth** | **Derive-on-read** — coverage is recomputed from disk at cycle-end AND whenever the digest (035) / `./vault status` (048 v1.1) read it; `coverage-targets.json::met_count` becomes a recomputed cache, not authoritative stored state. Stale existing vaults self-heal on the next read; **no migration verb needed**. | Simplest + eliminates the entire class of "stale stored count" bugs. No new CLI surface. The one cross-check invariant (FR2) still fails loudly if a written count ever diverges from the disk recount. |
| **Q4 — scope** | **Standalone spec 068.** | The bug lives in the shared `pipeline/coverage.py` counter, which 035 (digest) and 048 v1.1 (`status`) both consume. Fixing the counter + adding the cycle-end invariant (FR2) + the multi-category quality fixture (FR5) is its own surface; 035/048 are consumers, not the owner. Consistent with 066/067 staying standalone. |

All four resolved (code-audit + live-evidence grounded). Locked shape:
disk-scan recompute driven by frontmatter `coverage_category` (FR1), a
cycle-end invariant that fails loudly on divergence (FR2), digest +
`./vault status` read the same recomputed count (FR3/FR4), and a
multi-category quality fixture that catches `0% → 0%` regressions at
`build.sh --quality` time (FR5). Derive-on-read means no migration verb.
Ready for `/speckit.plan`.

## Why this spec exists

The rc7 reference-vault validation run wrote 107 substantive notes; the cross-cycle
digest reports `0% → 0%` for **every** category and lists each as **stagnant**.
The digest is the operator-facing answer to "are we making progress?" — it
must reflect the actual notes that landed. Currently it lies.

Three candidate root causes (need investigation):

1. **Counting bug** — `coverage-targets.json` counts notes by their
   `coverage_category` frontmatter; the notes were written with a different
   category key than the targets expect (e.g. frontmatter says
   `coverage_category: infrastructure`, targets file expects
   `coverage_category: Infrastructure` or `infrastructure-notes`).
2. **Refresh-after-write bug** — counts are computed at cycle-START and
   never recomputed after notes land; the digest reads the stale counts.
3. **Category-mapping bug** — notes are in `data_vault/13 - Infrastructure/`
   (directory name with spaces and numeric prefix) but the counter walks
   `data_vault/infrastructure/` (slug). Likely the strongest candidate.

## Suggested approach (for the clarify stage)

1. **Reproduce** with a minimal fixture (one note, one coverage target,
   assert the counter sees it). The rc7 evidence is fully reproducible
   from the live vault: `~/Documents/reference-vault-rc7/_pipeline/` artifacts +
   `data_vault/` notes give every piece of input the digest needs.
2. **Identify which of the 3 candidates** is the real cause (likely #3 —
   directory-name vs slug mismatch). Could be more than one.
3. **Add invariant**: at cycle-end, the count of notes in `data_vault/*X*/`
   matching `coverage_category: X` MUST equal
   `coverage-targets.json::met_count[X]`. This is the cross-check the
   framework should fail loudly on.
4. **Quality-harness fixture** that asserts the invariant across the 022
   quality fixtures — pre-rc8 regressions get caught at `build.sh --quality`
   time, not at live-validation time.

## Functional requirements (sketch)

- **FR1** — Coverage counter walks the actual on-disk `data_vault/` tree
  AND reads each note's `coverage_category` frontmatter; mismatches between
  directory and frontmatter are logged but the **frontmatter wins** (it's
  the explicit signal).
- **FR2** — At cycle-end, the orchestrator recomputes coverage counts and
  fails loudly if the on-disk count doesn't match the `coverage-targets.json::met_count`.
- **FR3** — `./vault digest` Coverage Delta reflects measured count, not a
  stale snapshot. The Gaps section's "stagnant" classification is based
  on cycle-over-cycle DELTA, not absolute zero.
- **FR4** — `./vault status` (spec 048 v1.1) surfaces the same count
  consistently — one source of truth.
- **FR5** — Regression: tests/quality/ fixtures include a multi-category
  fixture where N notes write to each of M categories; digest reports
  `+N% (start 0% / end met)`, not `0% → 0%`.

## Cross-references

- Issue #156 (this spec's tracking issue)
- Issue umbrella #152 (rc7 validation findings → rc8 wave)
- Spec 035 (cross-cycle digest — owns the Coverage Delta + Gaps sections)
- Spec 048 v1.1 (`./vault status` — must stay consistent with digest)
- Possibly an amendment to spec 035 rather than standalone; clarify Q3.

## Open questions (for /speckit.clarify)

- Q1: Which of the 3 candidate root causes is the real bug? (Almost
  certainly #3 — directory vs slug — but rc7 evidence will prove it.)
- Q2: Frontmatter vs directory — when they disagree, which wins?
  (Recommended: frontmatter, since it's the explicit signal the
  note-writer set intentionally.)
- Q3: Scope — amendment to spec 035, or standalone? Spec 035's surface
  is the digest; this fix touches the counter that 035 reads.
- Q4: Migration: existing vaults with stale `coverage-targets.json::met_count`
  need a re-count pass. Is that `./vault recount` or a one-off script?

## Deferred to plan/tasks

Full plan + tasks + foreman test-design enrichment happens after clarify.
This stub exists so the rc8-wave umbrella has a concrete spec dir to point
at; full spec-kit work lives in a dedicated session.
