# Phase 1 — Data Model: Coverage counting correctness (068)

No persisted schema change. `coverage-targets.json` keeps its shape; `met_count`
changes meaning from "incrementally accumulated state" to "recomputed cache".

## Entity 1 — CoverageCategory (existing — `met_count` semantics change)

From `spec/schema.py::CoverageCategory`. Fields unchanged
(`name`, `note_type`, `target_count`, `met_count`, `required`, `display_name`,
`expected_filenames`, `gap`, `is_met`). **Change:** `met_count` is now the count of
on-disk notes assigned to this category by `recompute_from_disk`, not a running total.

| Field | Source after 068 |
| --- | --- |
| `met_count` | `recompute_from_disk(vault_dir)` — count of `data_vault/**/*.md` (excluding `note_type: alias`) whose `classify_note_category` resolves to this category, filtered by `note_type == note.type`. |
| `gap` / `is_met` | derived from `target_count` + the recomputed `met_count` (unchanged formula). |

## Entity 2 — recompute_from_disk (new function, pure)

`recompute_from_disk(vault_dir: Path) -> CoverageTargets`

```
targets = load_targets(vault_dir)            # for category defs + target_count
for cat in targets.categories: cat.met_count = 0
for note in (vault_dir/"data_vault").rglob("*.md"):
    fm = parse_frontmatter(note)
    if fm.note_type == "alias": continue      # spec-062 FR3
    ntype = fm.type;  if not ntype: continue
    eligible = [c for c in targets.categories if c.note_type == ntype]
    chosen = classify_note_category(fm, note.name, eligible)   # reused unchanged
    if chosen: chosen.met_count += 1
    if fm.coverage_category and dir_category(note) and they_disagree: log WARN  # D5
save_targets(vault_dir, targets)              # cache write (atomic, existing)
return targets
```

- **Pure** w.r.t. inputs: same `data_vault/` ⇒ same counts (determinism, Principle IV).
- **Idempotent**: running it twice yields identical `met_count`.

## Entity 3 — RecomputeCache (optional, perf)

If profiling shows a hot-path read (digest/status), memoize the result keyed by
`(vault_dir, max-mtime of data_vault tree)`. Out of locked scope unless needed; the
~107-note rc7 vault recomputes in well under a second.

## Entity 4 — CoverageInvariant (FR2, transient)

At cycle-end, after notes land:

```
recount = recompute_from_disk(vault_dir)
# invariant: recount == the value that would be written
# on divergence during transition: log loud WARN (WARN-and-trust, decided U1), trust recount
```

## Validation rules

- **FR1** — every non-alias `data_vault` note with a non-empty `type` is counted in
  exactly one category (the round-robin fallback guarantees "somewhere").
- **FR2** — post-recompute, `sum(met_count)` equals the count of counted notes on
  disk; divergence is surfaced, never silent.
- **FR3** — the digest "stagnant" classification is a **cycle-over-cycle delta** of
  recomputed counts, not `met_count == 0`.
- **FR5** — a fixture with N notes across M categories yields non-zero coverage % in
  the digest (no `0% → 0%`).

## Migration

**None.** Derive-on-read: the next cycle-end / digest / status read recomputes from
disk, so stale vaults (incl. rc7) self-heal. No `./vault recount` verb, no
`schema_version` bump. The digest's historical per-cycle snapshots stay as-recorded
(D3 caveat) but current coverage and forward deltas are correct.
