# Phase 0 — Research: Coverage counting correctness (068)

Grounded in (a) live rc7 evidence and (b) a code audit of
`pipeline/coverage.py`, `pipeline/digest/sections.py`, `cli/status.py`.

## rc7 evidence (the numbers)

| Category | on-disk notes | `coverage-targets.json::met_count` |
| --- | --- | --- |
| concepts (`01 - Concepts`) | 20 | 2 |
| algorithms (`02 - Algorithms`) | 5 | 2 |
| data-structures | 5 | 0 |
| patterns | 5 | 1 |
| frameworks | 8 | 2 |
| databases | 13 | (small) |
| infrastructure (`13 - Infrastructure`) | 33 | (small) |
| **total** | **~107** | **~14** |

A sample note (`01 - Concepts/ACID.md`) frontmatter: `type: concept`,
`coverage_category: concepts` — **exactly** the target slug. So the count is not
failing on a name mismatch; it is simply not counting most notes.

## D1 — Root cause: stale incremental count (candidate #2)

**Decision**: The bug is `update_after_cycle` accumulating `met_count` from each
cycle's `research_report['notes_created']` and never reconciling with disk.
**Rationale**: `update_after_cycle` (coverage.py:255–310) does
`targets = load_targets(...)`, iterates `notes_created`, rglobs each basename,
classifies, `met_count += 1`, saves. If a note isn't in `notes_created` (report
under-capture), or a cycle didn't call it, the count drifts below the true on-disk
total. `met_count` ≈14 vs ~107 confirms massive under-capture. **Candidate #1**
(frontmatter↔target name mismatch) is **ruled out** — `coverage_category: concepts`
matches `categories[].name: concepts`. **Candidate #3** (`NN - Title` dir vs slug) is
not the *cause* (the count uses frontmatter, not dir) but is a **fix constraint**: any
disk recompute must read `coverage_category` frontmatter, never infer category from the
directory name. **Alternatives considered**: patch the increment to be more reliable
(rejected — fragile, keeps the stale model); recount only in the digest (rejected — two
sources of truth, status would still lie).

## D2 — Reuse `classify_note_category`, change only the driver

**Decision**: Keep `classify_note_category` (coverage.py:185–252) unchanged; add
`recompute_from_disk(vault_dir)` that walks `data_vault/*.md`, parses frontmatter,
skips `note_type: alias` (already done in `update_after_cycle:290–293`), filters
categories by the note's `type`, calls `classify_note_category`, and tallies a fresh
`met_count` per category. **Rationale**: the resolution order (explicit
`coverage_category` → keyword overlap → largest-gap round-robin) is already correct;
only the *iteration source* is wrong. Minimal, behaviour-compatible change.
**Alternatives considered**: a brand-new classifier (rejected — needless churn + risk).

## D3 — `met_count` becomes a recomputed cache (no schema bump)

**Decision**: `coverage-targets.json` keeps its shape; `met_count` is now
authoritatively recomputed at cycle-end and at digest/status read time (derive-on-read,
Q3). **Rationale**: no migration verb needed — the next read self-heals any stale
vault, including rc7. **Caveat**: the digest's cross-cycle delta
(`build_coverage_delta` → `coverage_progress`, sections.py:348–363) reads per-cycle
snapshots; historical cycles already snapshotted with stale counts won't retroactively
correct, but every cycle from rc8 forward writes the correct recount, so deltas become
correct going forward and the *absolute* current coverage is correct immediately.
**Alternatives considered**: a `./vault recount` verb (rejected per Q3 — derive-on-read
removes the need; could be added later if a one-shot rewrite is ever wanted).

## D4 — Cycle-end invariant placement + severity (FR2)

**Decision**: Call `recompute_from_disk` at the existing cycle-end coverage-update
site in `orchestrator.py` (where `update_after_cycle` is invoked today), and assert the
recount equals any written value; on divergence, log loudly and **trust the recount**.
**Rationale**: the recount is the source of truth; a hard block would punish benign
states during transition. **Severity: loud WARN-and-trust (DECIDED at /analyze, U1).**
**Alternatives considered**: hard ERROR/block (rejected — too aggressive; the recount
already fixes the discrepancy).

## D5 — Frontmatter wins over directory (Q2)

**Decision**: When a note's `coverage_category` frontmatter disagrees with its on-disk
`NN - Title` directory, the frontmatter assigns the category; the mismatch is logged
as a WARN. **Rationale**: frontmatter is the explicit note-writer signal; the directory
is a rendering convenience. **Alternatives considered**: directory wins (rejected —
the directory naming is exactly what defeated naive counting).

## Summary of locked decisions

| ID | Decision |
| --- | --- |
| D1 | Root cause = stale incremental `met_count`; recompute from disk. Candidate #1 ruled out; #3 is a fix constraint (read frontmatter, not dir). |
| D2 | Reuse `classify_note_category`; change only the driver to a disk walk. |
| D3 | `met_count` = recomputed cache; derive-on-read; no schema bump, no migration verb. |
| D4 | Cycle-end invariant in `orchestrator.py`; trust recount; severity = loud WARN-and-trust (decided U1). |
| D5 | Frontmatter `coverage_category` wins over directory; WARN on mismatch. |
