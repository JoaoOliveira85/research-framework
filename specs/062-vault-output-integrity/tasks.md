# Tasks: Vault output integrity on constrained exit

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Status (2026-06-06)**: ✅ **SHIPPED 1.0.0rc3** (PR #126, squash `2d217be`). FR1–FR3
implemented (rejected-note quarantine, dedupe + idempotent commit + no-untracked
guard, acronym alias/links); 23 tests; `ruff` clean + `build.sh --quality` green.

**Input**: Design documents from `specs/062-vault-output-integrity/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, quickstart.md ✅

**Tests**: INCLUDED — Principle III (Test-First) NON-NEGOTIABLE. (Foreman test-design
subagent enriches with `### Testing Requirements` before `/speckit.implement`, ADR-0010.)

**Organization**: grouped by **functional requirement** (FR1–FR3; independent). Each
extends an existing seam (research.md D1/D2/D3); no new modules.

## Format: `[ID] [P?] [FR] Description`

---

## Phase 1: Setup

- T001 Confirm a green baseline on `rc3-spec-drafts`: `pytest -m "not e2e"` + `ruff check .` pass before edits.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the shared duplicate detector used by FR2 (commit guard) and 063 §4.1 GA-002.
*(FR1/FR3 have no shared blocker; they extend independent seams.)*

- T002 [P] Add a reusable `find_duplicate_notes(data_vault)` helper to `scripts/validate_vault.py` detecting OS-style ` N.md` siblings AND byte-identical content duplicates; return structured findings (consumed by FR2 + spec 063 GA-002).

**Checkpoint**: the dup detector exists; FR2 + the harness can call it.

---

## Phase 3: FR1 — Quarantine verifier-rejected notes on any exit

**Goal**: on clean OR constrained exit, every `verifier_status: rejected` note is moved to `_pipeline/quarantine/` (uncited, unindexed) with a backlog pointer; the run report headlines the count.
**Independent Test**: a constrained exit with K rejected notes leaves 0 indexed rejected notes and records `rejected_unresolved: K`; clean-exit behaviour unchanged.

- T003 [P] [FR1] Write `tests/pipeline/test_rejected_note_handling.py` (RED): constrained exit with K rejected notes ⇒ 0 rejected in `data_vault/`, K in `_pipeline/quarantine/`, `rejected_unresolved==K`, backlog pointer present; `/ask`-style index scan cannot return a quarantined note; clean exit (rewrite loop clears first) ⇒ 0 quarantined.
- T004 [FR1] Add `_quarantine_rejected_notes(vault_dir)` to `src/research_framework/pipeline/orchestrator.py`, mirroring `_quarantine_out_of_scope_notes` (~:192): scan `data_vault/` for `verifier_status: rejected`, move each to `_pipeline/quarantine/`, append a pointer line to `_pipeline/research-backlog.md`. Return the count.
- T005 [FR1] Call `_quarantine_rejected_notes` from `_finalise` (~:556) so it runs on every exit; thread the count to the run report. Make T003 GREEN.
- T006 [FR1] In `src/research_framework/pipeline/run_report.py`: add `rejected_unresolved` (JSON) + a "Verifier: N notes ended rejected and were quarantined" headline line (the signal spec 063 GA-001 consumes).

**Checkpoint**: a rejected note can never be cited; constrained exits can't hide them.

---

## Phase 4: FR2 — No duplicate files; one commit/cycle; nothing untracked

**Goal**: a re-emit overwrites the canonical path (never ` N.md`); exactly one `research: cycle N` commit per cycle; zero untracked `data_vault/` at commit (fail-loud).
**Independent Test**: a same-cycle re-emit overwrites + produces one commit; a writing cycle leaves zero untracked `data_vault/`.

- T007 [P] [FR2] Write `tests/pipeline/test_no_duplicate_notes.py` (RED): re-emit of an existing note path overwrites it; no ` 2.md` sibling; a same-cycle re-run yields exactly one `research: cycle N` commit.
- T008 [P] [FR2] Write `tests/pipeline/test_vault_commit_no_untracked.py` (RED): a cycle that writes notes leaves zero untracked files under `data_vault/` after the cycle commit; a deliberately-forked ` 2.md` ⇒ constrained exit.
- T009 [FR2] In `src/research_framework/pipeline/vault_commit.py`: make `commit_cycle` (~:553) idempotent per cycle number — a same-cycle re-emit folds into the single `research: cycle N` commit (no second commit).
- T010 [FR2] In `vault_commit.py` `_stage_and_commit` (~:731) / `commit_cycle`: after the cycle commit, assert `git status --porcelain data_vault/` is empty; non-empty ⇒ constrained exit (reuse the existing rc=1 path; Principle X). Make T007 + T008 GREEN.
- T011 [P] [FR2] Wire the T002 `find_duplicate_notes` helper into `scripts/validate_vault.py`'s reported classes (so `validate_vault.py` flags ` N.md`/content-hash dups).

**Checkpoint**: the auto-commit invariant (spec 050 / Principle X) holds on re-emit/resume.

---

## Phase 5: FR3 — Acronym/alias links resolve

**Goal**: deterministic title-derived acronym map resolves `[[OECDH]]` → canonical stem AND generates a redirect stub per acronym; `validate_vault.py` returns 0 on the dead-acronym class.
**Independent Test**: a vault whose titles imply N acronyms yields N resolvable references; ambiguous acronyms are dropped (never wrong-linked).

- T012 [P] [FR3] Write `tests/pipeline/test_acronym_alias_coverage.py` (RED): N title-derived acronyms ⇒ N resolvable `[[ACRONYM]]` refs (rewritten or redirect-stub-resolved); two notes yielding the same acronym ⇒ that acronym dropped from the map + a WARNING (no wrong link); explicit note `aliases:` honoured additively.
- T013 [FR3] In `src/research_framework/pipeline/wikilinks.py`: build the `acronym_map` (initials of significant title words ∪ explicit note `aliases:`; ambiguity ⇒ drop), then extend the cycle-end pass to rewrite unresolved all-caps `[[TOKEN]]` to the mapped canonical stem.
- T014 [FR3] In `wikilinks.py`: generate an idempotent redirect stub `data_vault/<folder>/<ACRONYM>.md` (`note_type: alias`, `redirect_to: <stem>`, `verifier_status: exempt`) per mapped acronym. Make T012 GREEN.
- T015 [FR3] Classify `note_type: alias` OUT of coverage targets, spec-022 quality metrics, and Principle-VIII stub-as-fuel accounting (data-model.md Entity 4) — touch the coverage/quality/stub classifiers that enumerate notes.
- T016 [P] [FR3] Extend `scripts/validate_vault.py` so the dead-acronym-link class returns 0 on a vault whose titles imply acronyms; emit an ambiguity WARNING for dropped acronyms.

**Checkpoint**: `validate_vault.py` exit 0 on the acronym/dead-link class.

---

## Phase 6: Polish & Cross-Cutting

- T017 [P] Write `tests/scripts/test_validate_vault_integrity.py`: dup-note class + dead-acronym class verdicts + exit codes on fixtures.
- T018 [P] Run `ruff check .` + `ruff format --check .`; fix new findings.
- T019 Run `pytest -m "not e2e"` + `./build.sh --quality` (confirm alias stubs excluded from metrics ⇒ no baseline movement).
- T020 [P] CHANGELOG `[Unreleased]`/`[1.0.0rc3]`: note rejected-note quarantine, re-emit dedup + untracked guard, and acronym alias/redirect (user-visible vault-output changes).

---

## Dependencies & Execution Order

- **Setup (T001)** → **Foundational (T002, dup detector)** blocks FR2's T011 + GA-002.
- **FR1 (T003–T006)**, **FR2 (T007–T011)**, **FR3 (T012–T016)** are mutually independent
  (quarantine seam / commit path / wikilinks) — parallelizable after Foundational.
- **Polish (T017–T020)** last.

### Parallel opportunities

- T003 ∥ T007 ∥ T008 ∥ T012 (different test files).
- FR1, FR2, FR3 can be implemented by three workers in parallel after T002.

## Implementation Strategy

Each FR is an independently shippable correctness fix. Recommended order FR1 → FR2 →
FR3 (plan.md) but all three can land in parallel. FR1 + FR2 pair with spec 063's
GA-001/GA-002/GA-003 gates (062 *prevents*, 063 *detects*); ship 062 before/with 063.
