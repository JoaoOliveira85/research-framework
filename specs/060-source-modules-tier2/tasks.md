# Tasks: Source-Module Tier 2+ Port Wave (Spec 060)

**Branch**: `060-source-modules-tier2`
**Inputs**: [spec.md](./spec.md), [plan.md](./plan.md), [research.md](./research.md), [contracts/](./contracts/)

**Format**: `[ID] [P?] [Story] Description` — `[P]` = parallelizable.

> **Governance-first**: Phases 1–5 deliver docs/contracts only (no `src/` umbrella module).
> Phase 6 is the **hackernews** kickoff port under the spec-020 five-file template — not a
> speckit sub-spec. Every port PR copies `contracts/module-port-acceptance-bar.contract.md` §9
> checklist.

## Phase 0 — Spec-kit artifacts ✅ (this pass)

- [x] T001 spec.md clarified (Q1–Q5) + FR/SC refined; status IMPLEMENT-READY.
- [x] T002 [P] `research.md` — rubric weights, Tier-2 ranking, dependency table, 038 note.
- [x] T003 [P] `contracts/module-port-acceptance-bar.contract.md` — fixed pass/fail bar.
- [x] T004 [P] `contracts/020-amendment-gate.contract.md` — amend vs defer vs optional-extra.
- [x] T005 [P] `contracts/tier-ladder.contract.md` — authoritative ladder + statuses.
- [x] T006 `plan.md` + `checklists/requirements.md` + `analyze-2026-06-03.md`.

## Phase 1 — US1: prioritization rubric + Tier-2 ranking (P1)

**Goal**: Reproducible module ordering with one-line rationales (SC-001).

- [ ] T007 [US1] Verify `research.md` §D1–D2: weights 40/25/20/15 documented; all six Tier-2
  modules ranked with rationale; batch-1 kickoff = `hackernews` only.
- [ ] T008 [P] [US1] Add a maintainer **scoring worksheet** (optional table stub) at the bottom
  of `research.md` for re-ranking when Milestone A/B/C demand signals update — same weights,
  no acceptance-bar edits.

**Checkpoint**: Independent test — two maintainers apply worksheet → same Tier-2 order.

## Phase 2 — US2: acceptance bar contract (P1)

**Goal**: Single objective pass/fail bar for every port (SC-002, SC-004).

- [ ] T009 [US2] Review `contracts/module-port-acceptance-bar.contract.md` against shipped
  Tier-1 modules (`youtube`, `reddit`, `rss`, `oreilly`) — confirm Tier-1 ports would PASS;
  note any gap as 020-amendment, not 060 bar change.
- [ ] T010 [P] [US2] Add PR template snippet to `contracts/module-port-acceptance-bar.contract.md`
  §9 (or `README` stub in spec dir) pointing reviewers at §2–§7 — no new runtime code.

**Checkpoint**: Independent test — dry-run checklist on `reddit` module → PASS.

## Phase 3 — US3: 020-amendment gate (P2)

**Goal**: No per-module workarounds (SC-003).

- [ ] T011 [US3] Walk `contracts/020-amendment-gate.contract.md` triggers T1–T5 against Tier-2
  candidates; record expected path (implement / defer) for `newsletters` and `github_extras`
  in `research.md` § "Gate dry-run" (2–3 lines each).
- [ ] T012 [P] [US3] Cross-link amendment gate ↔ acceptance bar §10 verdicts in both contracts
  (one-line "see also" at top).

**Checkpoint**: Independent test — hypothetical "extractor needs non-JSON stdout" → routes to
Path A or C, not local hack.

## Phase 4 — US4: tier ladder source of truth (P3)

**Goal**: One authoritative coverage list (SC-005).

- [ ] T013 [US4] Validate `contracts/tier-ladder.contract.md` lists every ROADMAP module with
  status; Tier 1 = `shipped`/`subsumed`; Tier 2 rank 1 = `next`; Tier 3+ = `not_prioritized`
  or `parked`/`future` per clarify Q4.
- [ ] T014 [P] [US4] Document ladder maintenance rules in `research.md` §D4 pointer (one paragraph)
  — ship event, defer event, re-rank event.

**Checkpoint**: Independent test — no second module list in spec dir contradicts ladder contract.

## Phase 5 — FR-008: spec 038 handoff (sequencing)

- [ ] T015 [P] Add `research.md` § "038 handoff" bullet: after first Tier-2 ship, schedule
  `/speckit.clarify` on spec 038; 038 FRs MUST NOT be copied into acceptance bar.

## Phase 6 — Kickoff port: `hackernews` (batch-1 #1)

**Goal**: Validate the bar on a real port; satisfies SC-002/SC-004 for one module.

> References: spec-020 five-file template (`src/research_framework/modules/youtube/`);
> spec-051 mandatory `preflight()`; acceptance contract §2–§7; **no** speckit spec 060-sub.

### Tests (MUST fail first)

- [ ] T016 [P] `tests/modules/test_hackernews_contract.py` — hermetic tests: happy path,
  empty feed, HTTP error, truncation boundary; env fixture override per reddit/rss precedent.
  MUST fail before `extractor.py` exists.

### Implementation

- [ ] T017 `src/research_framework/modules/hackernews/manifest.yaml` + `preflight.py` +
  `sources.yaml.template` + `few-shot.md` + `README.md` (stdlib-only declaration).
- [ ] T018 `src/research_framework/modules/hackernews/extractor.py` — subprocess JSON contract;
  Algolia HN API or RSS-equivalent fetch; no live network in CI.
- [ ] T019 Make T016 pass; `./vault refresh-sources` preflight path smoke on fixture vault optional.

### Ship gate

- [ ] T020 `bash build.sh --quality` hold-or-improve; paste result in port PR; acceptance
  contract §4 checklist complete.
- [ ] T021 Update `contracts/tier-ladder.contract.md`: `hackernews` → `shipped`; `wikipedia`
  → `next` (bar validated).

## Phase 7 — Polish & doc-sync

- [ ] T022 [P] `ruff check .` + `ruff format --check .` + `pytest -m "not e2e"` green after
  kickoff port (framework repo only).
- [ ] T023 Doc-sync (separate PR per project convention): `docs/ROADMAP.md` § Source Modules
  mirror `tier-ladder.contract.md`; spec header → SHIPPED; CHANGELOG `[Unreleased]` governance
  entry; GitHub issue close — **outside** spec dir edits in implement session.
- [ ] T024 Spec 038 clarify queued (comment on 038 issue or ROADMAP note) — FR-008 satisfied.

---

## Dependencies & ordering

```text
T007–T008 (US1) ─┬─► T013–T014 (US4)
T009–T010 (US2) ─┤
T011–T012 (US3) ─┘
        │
        ▼
T016 (tests) → T017–T018 → T019 → T020 → T021
T015 ∥ T007–T014 (parallel governance)
T022–T024 after T020
```

- **Governance phases (1–5)** block kickoff only when acceptance contract is incomplete
  (T009 must pass Tier-1 dry-run before T017).
- **No parallel Tier-2 ports** until T021 marks first ship (`wikipedia` is `next`, not
  `in_progress`, until then).

---

## Acceptance coverage

| Requirement | Tasks |
|-------------|-------|
| FR-001 prioritization criteria | T002, T007, T008 |
| FR-002 acceptance bar | T003, T009, T010, T016–T020 |
| FR-003 amendment gate | T004, T011, T012 |
| FR-004 deps / credentials | T002, T003 §6–7, T017–T018 |
| FR-005 tier ladder | T005, T013, T014, T021 |
| FR-006 no 020 re-spec | T011, T012 (gate only) |
| FR-007 022 regression gate | T020 |
| FR-008 038 sequencing | T015, T024 |
| SC-001 rationales on ladder | T007, T013 |
| SC-002 100% ports pass bar | T009, T016–T020 |
| SC-003 zero workarounds | T011, T012 |
| SC-004 zero harness regressions | T020 |
| SC-005 single authoritative list | T005, T013, T023 |
| US1 prioritization | T007, T008 |
| US2 acceptance bar | T009, T010, T016–T020 |
| US3 amendment gate | T011, T012 |
| US4 ladder truth | T013, T014, T021, T023 |

**Task count**: 24 (T001–T024; T001–T006 complete in spec-kit pass).
