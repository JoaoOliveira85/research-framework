---
description: "Task list — 069 source-relevance + declared-source validation"
---

# Tasks: Source-relevance + declared-source validation (069)

**Input**: Design documents from `/specs/069-source-relevance-tuning/`
**Prerequisites**: plan.md ✅, spec.md ✅ (clarified 4/4; FR4 split), research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: INCLUDED — Test-First (constitution Principle III) + foreman (ADR-0010).

**Organization**: Bug-fix/feature spec; "user stories" map to the dependency-ordered
FRs from plan.md §Phase Sequencing. US1=FR1, US2=FR2, US3=FR3/FR5. **FR4 is out of
scope** (deferred to a follow-up sub-spec, Q3) and is filed as a task in Polish.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable (different files, no incomplete deps)
- **[Story]**: US1–US3 (= FR group)
- All paths repo-root-relative.

---

## Phase 1: Setup (Shared Infrastructure)

- [x] T001 [P] Add a declared-source fixture builder to `tests/_helpers/` reproducing the rc7 shape: a spec with 4 `data_sources` — one with a concrete repo URL (matches a module trigger), three description-only ("Web", "Official Documentation", "Codebase Vault Seed") — plus a `modules/` dir containing a module whose `manifest.yaml` triggers match only the first.
- [x] T002 [P] Add a multi-cycle source-ledger fixture (a declared source cold for ≥2 consecutive cycles) for the stagnant-signal tests.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The schema field + the backing-resolution primitive everything consumes.

- [x] T003 Add the optional `kind` field to `DataSourceConfig` in `src/research_framework/spec/schema.py` (`module_backed` | `strategy_hint`; absent allowed) — additive, no `schema_version` bump (data-model Entity 1).
- [x] T004 Add `source_is_backed(source, registry) -> {backed|strategy_hint|unbacked}` (locator resolution per D2 + reuse `source_bridge/discovery.py::TriggerRegistry.match`). Place in `spec/validator.py` or a small shared helper importable by validator + preconditions (data-model Entity 3).
- [x] T005 [P] Add the `domain` trigger type to the manifest JSON-schema enum in `specs/020-code-bridge/contracts/manifest.schema.json` (code already supports it in `_matches`).

**Checkpoint**: A declared source can be classified backed / strategy_hint / unbacked deterministically.

---

## Phase 3: User Story 1 (FR1) — Backing validation at scaffold 🎯 MVP

**Goal**: Every declared source must trigger-match an installed module OR carry `kind: strategy_hint`; otherwise scaffolding errors with the source name.

**Independent Test**: rc7-shaped spec without `kind` → error naming the 3 unbacked sources; same spec with `strategy_hint` on those 3 → passes; the URL source stays backed.

### Tests for User Story 1 ⚠️ (write first, must fail)

- [x] T006 [P] [US1] In `tests/pipeline/test_trigger_matching.py`: a source whose `repos[].url` matches a module `url_pattern` trigger → `backed`; a no-locator source → not backed (contract C1-a).
- [x] T007 [P] [US1] In `tests/spec/test_validator_source_backing.py`: a description-only source with `kind: strategy_hint` → ok; without `kind` → `unbacked` error containing the source name (contracts C1-b, C1-c).
- [x] T008 [P] [US1] `scripts/validate_spec.py` surfaces a warning on the same unbacked source (contract C2-b); rc7's 4 sources resolve as expected (contract C3-b).

### Implementation for User Story 1

- [x] T009 [US1] Wire `source_is_backed` into `src/research_framework/spec/validator.py::validate` — `unbacked` ⇒ hard validation error (the `generate` gate) (contract C2-a).
- [x] T010 [US1] Wire the same rule (warn-level) into `scripts/validate_spec.py` (the vault-spec skill pre-scaffold gate).

**Checkpoint**: A vault can't be scaffolded with a silently-unbacked declared source.

---

## Phase 4: User Story 2 (FR2) — Runtime fail-closed at preflight

**Goal**: A declared source with no trigger-matching module and no `strategy_hint` FAILs preflight (never silently empty).

**Independent Test**: Preflight fails closed on an unbacked source with a clear message; passes on `strategy_hint`.

### Tests for User Story 2 ⚠️ (write first, must fail)

- [x] T011 [P] [US2] In `tests/pipeline/test_preflight_source_backing.py`: an unbacked source FAILs `preconditions.check` / preflight with a clear message (contract C3-a); a `strategy_hint` source passes.

### Implementation for User Story 2

- [x] T012 [US2] Add the backing check to `src/research_framework/pipeline/preconditions.py` check #6 (resume path), reusing `source_is_backed`.
- [x] T013 [US2] Report per-source backing status in `src/research_framework/pipeline/preflight.py::check_all` alongside connectivity; ensure the generate path also surfaces it (generate skips `preconditions.check` today — covered by the US1 validator gate).

**Checkpoint**: Runtime refuses to pretend an unbacked source is live.

---

## Phase 5: User Story 3 (FR3/FR5) — Stagnant-source WARN signal

**Goal**: A source yielding nothing for ≥2 consecutive cycles is surfaced as an advisory WARN (authority-weighted), in the cycle report + `./vault status`; never blocks the cycle.

**Independent Test**: A source cold ≥2 cycles → one WARN; cold 1 cycle → none; an authoritative cold source ranks first; the cycle gate is unchanged.

### Tests for User Story 3 ⚠️ (write first, must fail)

- [x] T014 [P] [US3] In `tests/pipeline/test_stagnant_source_signal.py`: cold ≥2 cycles → one WARN; cold 1 → none (contract C1-a); signal never changes the cycle verdict (contract C1-b).
- [x] T015 [P] [US3] Two cold sources, one authoritative → authoritative ranks first (contract C2-a, FR5).
- [x] T016 [P] [US3] In `tests/cli/test_status_stagnant.py`: `./vault status` surfaces the WARN, consistent with the quality report (contract C3-a).

### Implementation for User Story 3

- [x] T017 [US3] Compute ≥2-consecutive-cold per declared source from `scripts/source_ledger.py` (`load_declared_sources` + per-cycle verdicts incl. `SKIPPED_RELEVANCE`).
- [x] T018 [US3] Emit the signal into `src/research_framework/pipeline/quality_report.py` (`_degraded_sources` / `write_report` `degraded_sources`), weighted by `src/research_framework/pipeline/source_authority.py::build_source_role_index` (FR5).
- [x] T019 [US3] Surface the WARN via `src/research_framework/cli/status.py::build_status_json` (deferred-warnings pattern).

**Checkpoint**: Cold sources are visible to the operator without blocking cycles.

---

## Phase 6: Polish & Cross-Cutting

- [x] T020 Run `quickstart.md` against the rc7-shaped fixture; confirm all "Done-when" boxes (validation + fail-closed + WARN).
- [x] T021 [P] `ruff check .` + `ruff format --check .` clean for touched files.
- [x] T022 **Decided (analyze U3):** `kind` absent-inference semantics — when `kind` is omitted the source is classified **backed iff a module trigger matches, else `unbacked` → error**. No third "ambiguous" state. Encode this directly in `source_is_backed` (T004) and assert it in T006/T007; no operator confirmation needed.
- [ ] T023 **File the FR4 follow-up sub-spec** via `/speckit.specify` (relevance-classifier tuning; the `gh`-went-cold rc7 case) — DO NOT implement FR4 in this spec (Q3/D6). Add it to `docs/ROADMAP.md`.

---

## Dependencies & Execution Order

- **Setup (P1)** → **Foundational (P2, T003–T005)** blocks all stories (schema + backing primitive).
- **US1 (FR1)** MVP → **US2 (FR2)** depends on US1 (same `source_is_backed`).
- **US3 (FR3/FR5)** depends only on Foundational + the ledger; can run in parallel with US2.
- **Polish (P6)** last; T023 (FR4 sub-spec) is a doc/spec action, not implementation.

### Parallel Opportunities

- T001/T002 (Setup) and T005 (schema doc) in parallel; all `[P]` tests within a story together.
- US3 is independent of US2 → parallel after Foundational.

## Implementation Strategy

MVP = Setup + Foundational + US1 (scaffold honesty) + US2 (runtime fail-closed). Then
US3 (stagnant WARN). FR4 deferred to a sub-spec.

**Pre-`/speckit.implement`**: dispatch the test-design subagent (ADR-0010); implement;
foreman Arm A + Arm B before the PR.

## Notes

- ~23 tasks; ~35–45 tests. No new runtime dep; one additive optional field (no `schema_version` bump).
- Headline reuse: the already-shipped `TriggerRegistry` (currently discarded in the extraction orchestrator) is wired into validation (D1).
- Migration is operator-driven (Q2): warn + fail-closed; never rewrite `research.spec.md`.
