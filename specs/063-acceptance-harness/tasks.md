# Tasks: Acceptance harness (framework-generic gates + ledger reconciliation + grading)

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Status (2026-06-05)**: SHIPPED 1.0.0rc3 (framework side). Foundational + US1–US5
landed in `src/research_framework/cli/acceptance.py` (+ parser/shim wiring + the
orchestrator clean-exit auto-run hook); 41 tests across
`tests/cli/test_acceptance_{scorecard,gates,ledger_recon,grading,probes,autorun}.py`.
US4/US5 in-vault tasks (T017, T019) are *vault data* (authored per-vault under
`<vault>/_pipeline/acceptance/`), not framework-repo code — the framework
**discovers** the pack (T018 test green) but never imports it (D5).

**Input**: Design documents from `specs/063-acceptance-harness/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, quickstart.md ✅,
contracts/ (generic-gates.contract.md, acceptance-scorecard.schema.json) ✅

**Tests**: INCLUDED — Principle III (Test-First) NON-NEGOTIABLE; the SC-001 snapshot
fixture is the headline RED target. (Foreman test-design subagent enriches with
`### Testing Requirements` before `/speckit.implement`, ADR-0010.)

**Organization**: grouped by **user story** (US1–US5, priorities P1/P1/P2/P2/P3).
Sequenced **last in the rc3 wave** — consumes 061 FR4, 062 FR1/FR2, the 028 + 048
amendments.

## Format: `[ID] [P?] [Story] Description`

⚠️ **Wave dependency**: do NOT start US1 gates GA-001/GA-002/GA-004/GA-005 or US2 until
specs 062 (FR1/FR2), 061 (FR4), 028-amendment, and 048-amendment are merged — those
gates *consume* their signals. The fixture + scorecard + verb plumbing have no such
dependency and can start immediately.

---

## Phase 1: Setup

- T001 Confirm green baseline on `rc3-spec-drafts`: `pytest -m "not e2e"` + `ruff check .` pass (and 061/062/028/048 amendments merged — see wave dependency).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the RED target + the command surface + the output shape every story fills.
**⚠️ CRITICAL**: no US can be implemented until these exist.

- T002 Build the SC-001 snapshot fixture `tests/fixtures/acceptance/rc1-codebase-snapshot/` reproducing the rc1 defects deterministically: ≥1 `verifier_status: rejected` note in `data_vault/`, a `… 2.md` duplicate, a run-report with `total_cost_usd: 0`, a `cycle_budget` showing 6/12 constrained, and a source cited by notes yet ledger-verdicted `ACCESS_FAIL`. Add a clean-twin fixture that PASSes all gates.
- T003 [P] Register the `acceptance` verb: add the subparser to `src/research_framework/cli/_parser.py` (mirror `status`/`digest` at :381/:386) + a `_cmd_acceptance` skeleton in new `src/research_framework/cli/acceptance.py` (returns an empty scorecard) + an `acceptance)` case in `templates/vault-script.sh.j2` (mirror `status)` at :117).
- T004 Implement `GateResult` + `Scorecard` (reuse `pipeline.gates.GateResult` shape; data-model.md Entities 1–2) and the `report-<date>.{json,md}` writer in `cli/acceptance.py`, conforming to `contracts/acceptance-scorecard.schema.json` (`schema_version: "1.0"`, `kind: "acceptance-scorecard"`). Add `tests/cli/test_acceptance_scorecard.py` asserting the artifact validates against the schema (FR-006).

**Checkpoint**: `./vault acceptance` runs end-to-end (empty scorecard); fixtures exist.

---

## Phase 3: US1 — Framework-generic gates (Priority: P1) 🎯 MVP

**Goal**: the six §4.1 deterministic, LLM-call-free gates (`generic-gates.contract.md`).
**Independent Test**: against the snapshot fixture the gates FAIL on the real defects; against the clean twin they all PASS (SC-001).

- T005 [P] [US1] Write `tests/cli/test_acceptance_gates.py` (RED): GA-001…GA-006 each FAIL/WARN on the seeded defect in the snapshot and PASS on the clean twin; verify the tier-2 LLM-dispatch guard stays green (zero dispatch).
- T006 [US1] GA-001 rejected-notes-in-corpus: zero `data_vault/` notes with `verifier_status: rejected` (consumes spec 062 FR1 quarantine + run-report `rejected_unresolved`). FAIL.
- T007 [US1] GA-002 duplicate-notes: reuse spec 062's `find_duplicate_notes` (` N.md` + content-hash). FAIL.
- T008 [US1] GA-003 git-integrity: `git -C <vault> status --porcelain data_vault/` empty; exactly one `research: cycle N` commit per cycle; research branch squash-merged on clean exit (Principle X). FAIL.
- T009 [US1] GA-004 run-completion: parse spec-061 FR4 `cycle_budget`; a `exit_status != "complete"` MUST read constrained (never "done"); surface configured-vs-actual cycles + per-category % of target; the zero-cycle clean exit is NOT a FAIL (edge case). FAIL.
- T010 [US1] GA-005 cost-telemetry: `total_cost_usd > 0` + tokens recorded + within budget (consumes spec-028 amendment; FAIL-loud on `$0` even pre-amendment — edge case). FAIL.
- T011 [P] [US1] GA-006 template-drift: every note's `template_version` matches the shipped templates. WARN (advisory).
- T012 [US1] Exit-code aggregation: process exits `1` iff any FAIL gate; WARN never blocks unless `--strict`; all results written to the scorecard. Make T005 GREEN.

**Checkpoint**: the MVP — the rc1 off-script findings are now deterministic FAILs.

---

## Phase 4: US2 — Phase-2B reads the shipped ledger + cross-checks citations (Priority: P1)

**Goal**: stop hand-joining; read `scripts/source_ledger.py`; report ledger↔citation disagreement as the finding (not a wall of ACCESS_FAIL).
**Independent Test**: on the snapshot, the cited-but-`ACCESS_FAIL` source is reported as a disagreement; SA-3/SA-4 re-graded against the reconciled view.

- T013 [P] [US2] Write `tests/cli/test_acceptance_ledger_recon.py` (RED): a source with collapsed ledger verdict ∈ {ACCESS_FAIL, PIPELINE_DROP} but `citation_rate > 0` ⇒ reported as a **disagreement**, not a source failure; SA-3/SA-4 read the reconciled view.
- T014 [US2] In `cli/acceptance.py`: invoke `scripts/source_ledger.py` (per-cycle `collapse_verdict`), build the ledger-reconciliation view (data-model Entity 3) by overlaying note `source_urls` citation rates, and surface `LEDGER_DISAGREEMENT` (emitted by the 048-v2 amendment; computed defensively even against a pre-amendment ledger). Make T013 GREEN.

**Checkpoint**: the eval lens no longer false-fails on the dominant evidence path.

---

## Phase 5: US3 — Authority (053) + credibility (055) citation grading (Priority: P2)

**Goal**: grade authority/trunk correctness + credibility tiers/COI, not just two-tier presence.
**Independent Test**: a note citing against its vault's *derived* trunk is FLAGGED; a correctly-grounded note passes; a journal-first vault is graded vs its own derived trunk (edge case).

- T015 [P] [US3] Write `tests/cli/test_acceptance_grading.py` (RED): authority-inversion note flagged; credibility tier + `coi` graded (surfaced, not auto-failed); journal-first fixture graded against derived trunk (not assumed code).
- T016 [US3] In `cli/acceptance.py`: per-citation grading (data-model Entity 4) via `pipeline/source_authority.build_source_role_index` (derived trunk) + `vault/credibility.{citation_credibility,citation_coi,resolve_role}`; record `authority_inversions`, `credibility_ungraded`, `coi_flagged`, and `derived_trunk_role`. Make T015 GREEN.

**Checkpoint**: the "code is the map; US→PR→code" model is machine-checkable per-vault.

---

## Phase 6: US4 — Domain probes rebalanced for breadth (Priority: P2)

**Goal**: retain GOLD anchors verbatim; add breadth probes so a vault covering a different valid slice isn't scored as a total miss.
**Independent Test**: a vault covering products B/C (not GOLD-anchored product A) scores partial-breadth credit, not zero.

- [~] T017 [P] [US4] In the codebase-vault `_pipeline/acceptance/` pack (in-vault, data not framework code): retain GOLD anchors P1 (fingerprint `variantId` trap) + P12 (convergence confidence) **verbatim**; add breadth probes across ≥N declared products/flows beyond the GOLD anchors.
- T018 [US4] Add a probe-pack test (in-vault fixture): a B/C-covering vault scores partial-breadth credit; assert P1 + P12 are byte-identical to the originals (no regression of the high-signal anchors).

**Checkpoint**: the domain grade is fair across declared products, not over-indexed on one.

---

## Phase 7: US5 — Generic/domain split; generic gates framework-resident + auto-run (Priority: P3)

**Goal**: generic gates live in the framework (US1/US2 already do); the domain pack shrinks to domain probes; the verb auto-runs at clean exit (Q4).
**Independent Test**: the generic gates run via the framework on any vault (not copy-pasted); the domain pack contains only domain probes; a clean run records a scorecard without changing its own exit code.

- [~] T019 [P] [US5] Shrink `codebase-vault-acceptance-probes.md` to **domain probes only**; reference the framework generic gates (`./vault acceptance`) rather than restating them.
- T020 [US5] Q4 auto-run: invoke `_cmd_acceptance` at `pipeline/orchestrator.py` clean-exit finalise (~:556) to record `_pipeline/acceptance/report-<date>.{json,md}`; it MUST NOT change the run's own 0/1/2 exit code (the acceptance verdict is a separate recorded signal — Constitution Check ask-first item 2).
- T021 [P] [US5] Write `tests/cli/test_acceptance_autorun.py`: a clean run writes the scorecard at finalise and the run exit code is unchanged; only FAIL gates would set the *scorecard* exit, never the run's. Confirm `./vault regenerate-shim` re-renders existing vault shims to expose the verb.

**Checkpoint**: every generated vault inherits the generic gates; SC-002 (reuse) holds.

---

## Phase 8: Polish & Cross-Cutting

- T022 [P] Run `ruff check .` + `ruff format --check .`; fix new findings.
- T023 Run the quickstart.md SC-001 repro on the snapshot; confirm SC-003 (constrained never "done"; `$0` never passes telemetry) + the tier-2 LLM-dispatch guard stays green (determinism guarantee).
- T024 [P] CHANGELOG `[1.0.0rc3]`: new `./vault acceptance` verb + auto-run-at-clean-exit + `_pipeline/acceptance/` scorecard (user-visible surface); note the domain pack shrank to domain probes.

---

## Dependencies & Execution Order

- **Setup (T001)** → **Foundational (T002–T004: fixture, verb plumbing, scorecard writer)** blocks ALL stories.
- **US1 (T005–T012)** is the MVP; gates GA-001/002/004/005 require the merged 062/061/028 siblings (wave dependency).
- **US2 (T013–T014)** depends on Foundational; pairs with the merged 048-v2 amendment.
- **US3 (T015–T016)** depends on US1's plumbing (scorecard + per-note read loop).
- **US4 (T017–T018)** is in-vault data; orthogonal to the framework gates — parallelizable.
- **US5 (T019–T021)** depends on US1/US2 existing (it factors + auto-runs them).
- **Polish (T022–T024)** last.

### Parallel opportunities

- T003 (verb plumbing) ∥ T002 (fixture) once Setup is green.
- Within US1: T011 (template-drift, WARN) ∥ the FAIL gates; the test (T005) is authored first.
- US4 (T017–T018, in-vault) can proceed entirely in parallel with US1–US3.

## Implementation Strategy

**MVP = Foundational + US1 + US2** (the load-bearing protection: deterministic generic
gates + trustworthy ledger lens). This is what guards the imminent tech-/feeds-vault runs.
US3 (grading depth) + US4 (domain breadth) + US5 (split + auto-run) complete the full §4
scope the operator approved. Ship the whole spec as the last item of 1.0.0rc3, after the
sibling signals (062/061/028/048) it consumes are merged.
