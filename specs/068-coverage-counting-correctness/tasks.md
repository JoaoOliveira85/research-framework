---
description: "Task list — 068 coverage counting correctness"
---

# Tasks: Coverage counting correctness (068)

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Input**: Design documents from `/specs/068-coverage-counting-correctness/`
**Prerequisites**: plan.md ✅, spec.md ✅ (clarified 4/4), research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: INCLUDED — Test-First (constitution Principle III) + foreman (ADR-0010).

**Organization**: Bug-fix spec; "user stories" map to the dependency-ordered FRs from
plan.md §Phase Sequencing. US1=FR1, US2=FR2, US3=FR3/FR4, US4=FR5.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable (different files, no incomplete deps)
- **[Story]**: US1–US4 (= FR group)
- All paths repo-root-relative.

---

## Phase 1: Setup (Shared Infrastructure)

- T001 [P] Coverage fixture builder — implemented as local `_write_note` / `_build_multi_category_vault` helpers in the new test modules (`NN - Title` dirs, N notes per category with `coverage_category` frontmatter, deliberately-stale `met_count`). Kept local rather than in `vault_factory.py` to keep the blast radius small.
- T002 [P] `note_type: alias` stub + frontmatter-vs-dir disagreement covered by `test_recompute_excludes_alias_stubs` and `test_recompute_frontmatter_wins_over_dir_with_warn`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The disk-recompute primitive everything else consumes.

- T003 Implemented `recompute_from_disk(vault_dir, *, persist=True) -> CoverageTargets` in `pipeline/coverage.py`: walks `data_vault/**/*.md`, parses frontmatter, skips `note_type: alias`, filters categories by `note.type`, reuses `classify_note_category`, tallies a fresh `met_count`; persists via `save_targets`. Frontmatter wins over directory with a WARN via `_dir_implied_category_name` (D5).

**Checkpoint**: `recompute_from_disk` returns correct counts from disk alone.

---

## Phase 3: User Story 1 (FR1) — Recompute from disk 🎯 MVP

**Goal**: Coverage counts reflect on-disk notes via frontmatter `coverage_category`, not a stale per-cycle increment.

**Independent Test**: A fixture with 20 concept notes in `01 - Concepts/` recomputes `met_count == 20`; alias stubs excluded; frontmatter-vs-dir mismatch counted by frontmatter + WARN.

### Tests for User Story 1 ⚠️ (write first, must fail)

- T004 [P] [US1] `tests/pipeline/test_coverage_recompute.py::test_recompute_counts_all_on_disk_concepts` — 20 notes → `met_count == 20` (C1-a).
- T005 [P] [US1] `test_recompute_excludes_alias_stubs` (C1-b).
- T006 [P] [US1] `test_recompute_frontmatter_wins_over_dir_with_warn` (C1-c).

### Implementation for User Story 1

- T007 [US1] `update_after_cycle` now delegates to `recompute_from_disk` (full disk recount, no increment) and adds the FR2 invariant cross-check.

**Checkpoint**: `met_count` equals the on-disk reality for every category.

---

## Phase 4: User Story 2 (FR2) — Cycle-end invariant

**Goal**: At cycle-end the recount is authoritative; a divergence surfaces loudly, never silently.

**Independent Test**: A cycle writing N notes ends with `sum(met_count) == N (+ prior)`; a forced divergence is surfaced.

### Tests for User Story 2 ⚠️ (write first, must fail)

- T008 [P] [US2] `tests/pipeline/test_coverage_invariant.py::test_cycle_end_recount_equals_notes_written` (C2-a) + `test_clean_cycle_does_not_warn` (no false positives).
- T009 [P] [US2] `test_divergent_written_value_is_surfaced_and_recount_trusted` — stale 99 → WARN + recount 3 trusted.

### Implementation for User Story 2

- T010 [US2] Orchestrator now calls `update_after_cycle` (= recompute + WARN-and-trust invariant) **before** `quality_report.write_report` so the snapshot the digest/status read reflects this cycle's notes (fixed the one-cycle snapshot lag). `_append_budget_log` kept after the report.

**Checkpoint**: Coverage is correct at cycle-end and divergence can't hide.

---

## Phase 5: User Story 3 (FR3/FR4) — Digest + status consume the recount

**Goal**: `./vault digest` shows real % (no `0% → 0%`) with delta-based "stagnant"; `./vault status` shows the same numbers.

**Independent Test**: A populated vault shows non-zero coverage % in the digest; status coverage == digest coverage.

### Tests for User Story 3 ⚠️ (write first, must fail)

- T011 [P] [US3] `tests/pipeline/test_coverage_digest_integration.py::test_digest_shows_real_coverage_not_zero` — non-zero delta, growing category not "stagnant" (C3-a).
- T012 [P] [US3] `tests/cli/test_status_coverage.py::test_status_coverage_matches_digest_snapshot_source` — status fill_pct == digest snapshot fill_pct (one source of truth).

### Implementation for User Story 3

- T013 [US3] Confirmed: `digest/sections.py` + `digest/ranker.py::detect_gaps` are already delta-based (`end == start and end < target`, not `met == 0`); they now consume the corrected snapshot via the T010 ordering fix — no code change needed in the digest itself.
- T014 [US3] `cli/status.py::build_status_json` now includes a `coverage` object via `_coverage_summary` (read-only `recompute_from_disk(persist=False)`, same fill formula as the snapshot).

**Checkpoint**: The digest and status both tell the truth and agree.

---

## Phase 6: User Story 4 (FR5) — Quality-harness regression fixture

**Goal**: `build.sh --quality` catches any future `0% → 0%` regression.

**Independent Test**: The multi-category fixture's baseline asserts non-zero coverage %.

### Tests / Fixture for User Story 4 ⚠️

- T015 [P] [US4] `tests/quality/test_coverage_recompute_regression.py` builds a multi-category vault (N notes × M categories, mixed slug/`display_name`, `NN - Title` dirs, rc7 stale-count shape) and asserts non-zero coverage in the digest snapshot AND the spec-022 harness metric. (Built in-test per the `test_metric_determinism.py` precedent rather than a committed full-vault snapshot — same regression guard, far smaller footprint; the assertion threshold replaces a committed baseline.)
- T016 [US4] Wired into `build.sh` SMOKE_TESTS; added to `test_marker_isolation.py` exemptions as a fast tier-2 guard. Fails if `0% → 0%` returns.

**Checkpoint**: Regression is gated at `build.sh --quality` time.

---

## Phase 7: Polish & Cross-Cutting

- T017 [P] Self-heal verified by `test_divergent_written_value_is_surfaced_and_recount_trusted` (stale stored count → recount on next read; derive-on-read, no migration verb).
- T018 [P] `ruff check` + `ruff format --check` clean for all touched files.
- T019 WARN-and-trust implemented and asserted in T009 (no maintainer confirmation needed).
- T020 [P] (perf, optional) **Skipped** — the ~107-note recompute is sub-second; no hot-path profiling signal. `recompute_from_disk` exposes `persist=False` so a future memo cache can wrap it without an API change.

---

## Dependencies & Execution Order

- **Setup (P1)** → **Foundational (P2, T003)** blocks everything (the recompute primitive).
- **US1 (FR1)** MVP → **US2 (FR2)** depends on US1 (invariant uses the recount).
- **US3 (FR3/FR4)** depends on US1 (consumers read the recomputed value); can run alongside US2.
- **US4 (FR5)** depends on US1 (fixture asserts the corrected count).
- **Polish (P7)** last.

### Parallel Opportunities

- T001/T002 (Setup) in parallel; all `[P]` tests within a story together.
- US3's two consumer edits (digest vs status) are different files → parallel.

## Implementation Strategy

MVP = Setup + Foundational + US1 (correct counts) + US2 (invariant). Then US3 (honest
digest/status) and US4 (regression gate).

**Pre-`/speckit.implement`**: dispatch the test-design subagent (ADR-0010); implement;
foreman Arm A + Arm B before the PR.

## Notes

- ~20 tasks; ~20–30 tests + 1 quality fixture/baseline. No new runtime dep; no `schema_version` bump (derive-on-read cache).
- Reuse `classify_note_category` unchanged (D2) — only the driver changes.
