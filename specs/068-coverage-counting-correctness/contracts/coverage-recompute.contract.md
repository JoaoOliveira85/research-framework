# Contract — Coverage recompute-from-disk (068 FR1–FR5)

Owns the deterministic coverage recompute in `pipeline/coverage.py` and its
consumers (`digest/sections.py`, `cli/status.py`).

## C1 — `recompute_from_disk(vault_dir) -> CoverageTargets` (FR1)

- Walks `data_vault/**/*.md`. For each note: parse frontmatter; **skip**
  `note_type: alias`; require non-empty `type`; restrict candidate categories to
  those whose `note_type == note.type`; assign via the **existing**
  `classify_note_category`; `met_count += 1`.
- Resets all `met_count` to 0 before counting (full recount, not increment).
- **Frontmatter wins** over directory (Q2/D5); a `coverage_category`-vs-`NN - Title`
  disagreement is logged WARN, never silently re-bucketed by directory.
- Pure + idempotent: same tree ⇒ same counts; running twice is a no-op delta.
- Persists via the existing atomic `save_targets` (cache write).

## C2 — Cycle-end invariant (FR2)

- The orchestrator calls `recompute_from_disk` at cycle-end (the current
  `update_after_cycle` call site).
- It asserts the recount equals the written `met_count`; on divergence it logs a
  loud **WARN** and trusts the recount. **Severity: WARN-and-trust (decided, analyze
  U1)** — never a hard ERROR/block.

## C3 — One source of truth for consumers (FR3/FR4)

- `digest/sections.py` (`build_coverage_delta`, `_load_coverage_targets`) reflects the
  recomputed `met_count`; "stagnant" is a cycle-over-cycle delta, not `met_count == 0`.
- `cli/status.py::build_status_json` surfaces the **same** recomputed coverage as the
  digest. A test asserts `status coverage == digest coverage`.

## C4 — Quality fixture (FR5)

- A `tests/fixtures/quality/` fixture with N notes across M categories (mixed slug /
  `display_name` / `NN - Title` dirs) + committed baseline; `build.sh --quality`
  asserts non-zero coverage % (catches any `0% → 0%` regression).

## Test obligations

| ID | Assertion |
| --- | --- |
| C1-a | A fixture vault with 20 concept notes in `01 - Concepts/` recomputes `met_count == 20`. |
| C1-b | `note_type: alias` stubs are excluded from counts. |
| C1-c | A note whose `coverage_category` disagrees with its dir → counted by frontmatter + WARN logged. |
| C2-a | A cycle that writes N notes ends with `sum(met_count)` == N (invariant holds). |
| C3-a | Digest shows real % (not `0% → 0%`) on a populated vault; status coverage matches digest. |
| C4-a | The FR5 multi-category fixture's baseline asserts non-zero coverage. |
