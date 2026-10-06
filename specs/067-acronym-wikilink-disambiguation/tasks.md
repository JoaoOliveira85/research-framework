---
description: "Task list — 067 acronym-wikilink disambiguation"
---

# Tasks: Acronym-wikilink disambiguation (067)

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Input**: Design documents from `/specs/067-acronym-wikilink-disambiguation/`
**Prerequisites**: plan.md ✅, spec.md ✅ (clarified 5/5), research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: INCLUDED — the project mandates Test-First (constitution Principle III)
and foreman verification (ADR-0010). Write each story's tests first; they MUST fail
before implementation.

**Organization**: This is a bug-fix spec; "user stories" map to the
dependency-ordered functional requirements (FR1→FR2→FR3→FR4/FR5) from plan.md
§Phase Sequencing. US1=FR1, US2=FR2, US3=FR3, US4=FR4/FR5.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1–US4 (= FR group)
- All paths are repo-root-relative.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: A reusable test fixture reproducing the rc7 CAP corruption *timeline*.

- T001 [P] Add an acronym-timeline fixture builder to `tests/_helpers/vault_factory.py` (or a local helper in `tests/pipeline/`): cycle-A vault with only `cache-aside pattern` (C-A-P), then cycle-B adds `CAP Theorem` (also C-A-P) + a body `[[CAP]]` — the exact rc7 ambiguity-emergence sequence.
- T002 [P] Capture the rc7 baseline assertions as a docstring/constants in `tests/pipeline/test_acronym_alias_coverage.py` (corrupted body string + `cap.md → cache-aside pattern`) so regressions are self-documenting.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Make the acronym map expose the data FR2/FR4 need (claims + self-title).

- T003 Extend `build_acronym_map` in `src/research_framework/pipeline/wikilinks.py` to also return/retain the per-acronym `claims` set and a `self_stem` lookup (note-title-stem), without changing existing single-claim mapping behaviour. (data-model Entity 1)
- T004 Mirror the T003 structural change in the duplicate `_build_acronym_map`/`_derive_acronym` in `scripts/validate_vault.py` so the validator and pipeline stay in sync (research D3).

**Checkpoint**: The acronym map can answer "is this acronym ambiguous?" and "does this stem equal the containing note's own title?"

---

## Phase 3: User Story 1 (FR1) — Single-expansion-only mapping 🎯 MVP

**Goal**: Ambiguous acronyms (≥2 title claims) never auto-link and never get a stub; single-expansion acronyms still do.

**Independent Test**: An acronym claimed by 2 titles produces no `[[...]]` rewrite and no `note_type: alias` stub; a singly-claimed acronym still maps + stubs.

### Tests for User Story 1 ⚠️ (write first, must fail)

- T005 [P] [US1] In `tests/pipeline/test_acronym_alias_coverage.py`: assert an ambiguous acronym is absent from `mapping`, present in `ambiguous`, and that `_write_redirect_stub` is a no-op for it (contract C1-a).
- T006 [P] [US1] In `tests/scripts/test_validate_vault_integrity.py`: assert `scripts/validate_vault.py`'s map agrees with `wikilinks.py`'s map on the same fixture (contract C1-b).

### Implementation for User Story 1

- T007 [US1] In `src/research_framework/pipeline/wikilinks.py`: make `_write_redirect_stub(acronym, stem)` a no-op when `acronym ∈ ambiguous`; document the single-expansion-only invariant on `build_acronym_map`.
- T008 [US1] Mirror the stub-refusal rule in `scripts/validate_vault.py` (keep WARN-on-ambiguous behaviour).

**Checkpoint**: No new stub/body link is ever created for a currently-ambiguous acronym.

---

## Phase 4: User Story 2 (FR2) — Self-title protection + stale re-evaluation

**Goal**: A note never links its own title's acronym to a sibling expansion; when an acronym becomes ambiguous, stale stubs/links are re-evaluated.

**Independent Test**: The rc7 CAP timeline fixture produces `CAP Theorem.md` body that keeps "CAP" (no `[[cache-aside pattern]]`), and the stale `cap.md` is flagged orphaned.

### Tests for User Story 2 ⚠️ (write first, must fail)

- T009 [P] [US2] In `tests/pipeline/test_acronym_alias_coverage.py`: run the T001 timeline → `resolve_acronym_links` → assert `"[[cache-aside pattern]] Theorem"` NOT in `CAP Theorem.md` and `"The CAP Theorem"` present (contract C2-a).
- T010 [P] [US2] Assert a note whose own title-acronym had a single-claim sibling self-links or plain-texts, never sibling-links (contract C2-b).

### Implementation for User Story 2

- T011 [US2] In `src/research_framework/pipeline/wikilinks.py::_rewrite_acronym_body`: add self-title protection — never rewrite a `[[TOKEN]]` whose acronym is the containing note's own title-acronym to a stem ≠ `self_stem` (uses T003 data).
- T012 [US2] In `resolve_acronym_links`: add the stale re-evaluation pass — for any acronym now in `ambiguous` that previously mapped, convert its body links to plain text and mark its stub orphaned (data-model Entity 2 lifecycle).
- T013 [US2] Mirror the self-title + re-eval logic awareness in `scripts/validate_vault.py` WARN reporting (D3).

**Checkpoint**: The exact rc7 corruption cannot recur from the ambiguity-emergence timeline.

---

## Phase 5: User Story 3 (FR3) — Deterministic title-corruption FAIL rule

**Goal**: A note whose first body wikilink renames its own title is rejected by the verifier.

**Independent Test**: The CAP-class note is `rejected`; a clean note whose first link is a legitimately different concept is NOT rejected.

### Tests for User Story 3 ⚠️ (write first, must fail)

- T014 [P] [US3] In `tests/pipeline/test_verifier.py`: a note whose first body `[[...]]` is its own title-acronym resolving to a non-self stem → `deterministic_wikilink_violations` returns one violation and `run_verifier_stage` marks it `rejected` (contract C3-a).
- T015 [P] [US3] In `tests/pipeline/test_verifier.py`: a note whose first body link is a different concept → no violation, not rejected (contract C3-b).

### Implementation for User Story 3

- T016 [US3] Add `deterministic_wikilink_violations(vault_dir, note_rel, body) -> list[dict]` to `src/research_framework/pipeline/verifier.py` (predicate per data-model D2; mirrors `deterministic_credibility_violations`).
- T017 [US3] Wire it into `run_verifier_stage` before `_merge_verifier_verdict`; any violation forces `status="rejected"` (FAIL).
- T018 [P] [US3] Add the "wikilink title corruption" rule entry to `.agents/skills/verifier/SKILL.md` (the deterministic twin remains authoritative).

**Checkpoint**: Title-corruption is a hard gate; a regression can't ship.

---

## Phase 6: User Story 4 (FR4/FR5) — `./vault wikilinks --fix` sweep

**Goal**: A deterministic, idempotent one-off sweep repairs existing corrupted vaults: plain-text ambiguous body links, re-point fixable stubs, delete orphan/unfixable stubs.

**Independent Test**: On the rc7 fixture, `--fix` de-links `CAP Theorem.md` and re-points/deletes `cap.md`; a second `--fix` run is a no-op.

### Tests for User Story 4 ⚠️ (write first, must fail)

- T019 [P] [US4] In `tests/cli/test_wikilinks_verb.py`: dry-run reports actions and writes nothing (contract V-a).
- T020 [P] [US4] `--fix` on the rc7 fixture repairs body link + stub (contract V-b); second `--fix` run → zero actions / idempotent (V-c).
- T021 [P] [US4] `--json` emits well-formed `SweepActionRecord[]` (V-d); stub re-point vs delete classification (data-model Entity 4 / D5).
- T022 [P] [US4] Shim routing: `wikilinks)` case dispatches to `research_framework.cli wikilinks` (contract V-e) — extend `tests/cli/` shim test.

### Implementation for User Story 4

- T023 [US4] Create `src/research_framework/cli/wikilinks.py`: scan `data_vault/`, build ambiguity set, plain-text ambiguous/title-renaming body links, re-point fixable stubs (single valid expansion), delete orphan/unfixable stubs; `--vault`, `--fix` (default dry-run), `--json` (contract wikilinks-verb).
- T024 [US4] Register the `wikilinks` subparser in `src/research_framework/cli/_parser.py` (mirror `digest`, research D4).
- T025 [US4] Add the `wikilinks)` case + help line to `templates/vault-script.sh.j2` (mirror `digest)`).

**Checkpoint**: Operators can repair existing vaults (incl. rc7) deterministically.

---

## Phase 7: Polish & Cross-Cutting

- T026 [P] Confirm `ruff check .` and `ruff format --check .` are clean for all touched files.
- T027 [P] Run `quickstart.md` end-to-end against the rc7 fixture; confirm all "Done-when" boxes.
- T028 Resolve plan §Ask-First at implementation: FR4 commit policy (default: leave uncommitted) and D3 duplicate-map consolidation (default: keep synced) — confirm with maintainer or keep defaults.
- T029 [P] **Quality-fixture guard (analyze C1 — parity with 068 FR5):** add an acronym-corruption fixture under `tests/fixtures/quality/` (a CAP-Theorem-shaped note whose first body wikilink renames its own title) and wire a `build.sh --quality` assertion that `deterministic_wikilink_violations` flags it (and that a clean fixture is silent). Guards against a 067 regression re-introducing the rc7 corruption. Keep cost low — reuse an existing fixture vault if one already carries acronym notes.

---

## Dependencies & Execution Order

- **Setup (P1)** → **Foundational (P2, T003/T004)** blocks all stories (the map shape).
- **US1 (FR1)** is the MVP. **US2 (FR2)** depends on US1's map invariants + T003 data.
- **US3 (FR3)** is independent of US1/US2 (verifier) — can run in parallel after Foundational.
- **US4 (FR4/FR5)** depends on US1/US2 rules (applies the same disambiguation retroactively).
- **Polish (P7)** after all stories.

### Parallel Opportunities

- T001/T002 (Setup) in parallel.
- US3 (T014–T018) can proceed in parallel with US1/US2 (different file: `verifier.py`).
- All `[P]` test tasks within a story run together.

## Implementation Strategy

MVP = Setup + Foundational + US1 + US2 (kills the rc7 corruption + prevents recurrence).
Then US3 (hard gate) and US4 (existing-vault repair) as incremental increments.

**Pre-`/speckit.implement`**: dispatch the test-design subagent (ADR-0010) to enrich
this file with `### Testing Requirements` blocks; implement; foreman Arm A
(`verify_test_coverage.py`) + Arm B before the PR.

## Notes

- ~29 tasks; ~25–35 tests expected. No new runtime dep; no `schema_version` bump.
- Keep `scripts/validate_vault.py` in lockstep with `wikilinks.py` (D3) on every map change.
- **Cross-spec ordering (analyze X1):** 067's `--fix` sweep deletes orphan/unfixable
  **alias** stubs, and spec 068's coverage recompute skips `note_type: alias` notes —
  these are consistent and independent (a deleted stub can't be counted; a surviving
  alias stub is never counted). No sequencing dependency between 067 and 068; they can
  ship in either order within the rc8 wave.
