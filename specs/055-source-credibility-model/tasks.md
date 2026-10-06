# Tasks: Source Credibility Model (Spec 055)

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Branch**: `055-source-credibility-model` · **Wave 2 / 0.10.0**
**Inputs**: [spec.md](./spec.md), [plan.md](./plan.md), [research.md](./research.md), [contracts/credibility-model.contract.md](./contracts/credibility-model.contract.md)

**Format**: `[ID] [P?] [Story] Description` — `[P]` = parallelizable (different
files, no ordering dep).

> **SEQUENCING GATE (hard)**: 055 implementation MUST NOT start before **spec 053
> ships** — the `off_field` predicate (FR-005) reuses 053's `source_id → role`
> resolution (`sources_loader.py`) and the `note_type → authoritative role`
> declaration. 053 is Wave 1. Until then, only the spec/plan/contract artifacts
> (this pass) are produced. *(research.md D6, plan.md Complexity.)*
>
> **TDD discipline**: tests in each story's "Tests" block are written first and
> MUST fail before the implementation task in the same story. Foreman test-design
> (ADR-0010) is eligible — this tasks.md is structured for `### Testing
> Requirements` enrichment.

## Phase 0 — Spec-kit artifacts ✅ (this pass)
- T001 spec.md fleshed to house-style + CL-1..CL-6 clarified.
- T002 contract authored (enum, schema, resolution fn, validator/calculator contracts).
- T003 research.md (D1–D6) + plan.md + this tasks.md + checklist.

## Phase 1 — Setup (Wave 2, after 053 ships)
- [ ] T004 Confirm 053 merged: `sources_loader.py` exposes `source_id → role`
  and `note_type → authoritative_role` resolution importable from
  `src/research_framework/`. If absent → STOP (sequencing gate).
- [ ] T005 [P] Add a credibility fixture skeleton under
  `tests/fixtures/quality/credibility/` (notes with known levels/COI/off-field;
  reuse the 022/030 fixture shape; `tmp_path`-isolated per spec 026). Data only.

## Phase 2 — US1: per-citation level recorded + resolver (P1) — the foundation

### Tests (write first — MUST fail)
- [ ] T006 [P] [US1] `tests/vault/test_credibility.py::test_level_enum_order` —
  the 4 enum values exist with the contract's ordinal ranks (`primary`=3 …
  `unvetted`=0); `downgrade_one_step` + `min_rank` behave per contract §1/§4.
- [ ] T007 [P] [US1] `tests/vault/test_credibility.py::test_effective_level_matrix`
  — table-driven over the **contract §4 worked-example matrix** (all 6 rows):
  declared → coi-cap → off_field-downgrade → effective. Includes the
  COI-before-topic ordering case (`primary`+coi+off_field → `unvetted`).
- [ ] T008 [P] [US1] `tests/vault/test_credibility.py::test_resolution_order` —
  explicit citation value wins over source default; source default used when
  citation omits; **neither present ⇒ `CredibilityUnresolved` raised** (FR-001,
  no silent default).
- [ ] T009 [P] [US1] `tests/vault/test_credibility.py::test_off_field_missing_role_is_not_off_field`
  — unresolved role ⇒ `off_field` false (contract §3; no double-penalty).

### Implementation
- [ ] T010 [US1] Create `src/research_framework/vault/credibility.py`:
  `Level` enum (+ ranks), `min_rank`, `downgrade_one_step`, `off_field(citation,
  note, sources)`, `effective_level(citation, note, sources)`, `CredibilityUnresolved`.
  Pure functions; reuses 053 `sources_loader` for role resolution. Make T006–T009 pass.
- [ ] T011 [US1] Surface `default_credibility` parsing on `data_sources[]` /
  module `sources.yaml` via the canonical settings/sources loader (validate it's
  one of the 4 enum values; ignore-with-warn on unknown). Unit test:
  `test_default_credibility_loaded` + `test_invalid_default_warns`.

## Phase 3 — US1 (cont.): verifier shape validation (P1)

### Tests (write first — MUST fail)
- [ ] T012 [P] [US1] `tests/pipeline/test_verifier.py::test_credibility_wellformed_passes`
  — note whose Tier-2 `source_urls` object entries carry valid `credibility`/`coi`
  passes.
- [ ] T013 [P] [US1] `tests/pipeline/test_verifier.py::test_credibility_unresolved_fails`
  — citation with no value and no source default ⇒ `rule_id: IX-credibility-unresolved`.
- [ ] T014 [P] [US1] `tests/pipeline/test_verifier.py::test_credibility_bad_enum_fails`
  + `test_coi_non_boolean_fails` — malformed shapes ⇒ `IX-credibility-malformed`.

### Implementation
- [ ] T015 [US1] Wire the verifier deterministic check to emit `IX-credibility-*`
  rules (presence + enum + boolean shape ONLY — never re-judge the value;
  contract §5). Make T012–T014 pass.

## Phase 4 — US2: `tier2_source_ratio` calculator (P1) — the motivating consumer

### Tests (write first — MUST fail)
- [ ] T016 [P] [US2] `tests/quality/unit/test_source_quality.py::test_tier2_source_ratio_deterministic`
  — fixed fixture notes ⇒ stable truncated float; tier-2 = `{commentary,
  unvetted}` (contract §1/§6); 0 citations ⇒ degenerate `0.0`.
- [ ] T017 [P] [US2] `...::test_tier2_ratio_moves_on_level_flip` — flipping one
  citation `primary→commentary` raises the ratio as expected.

### Implementation
- [ ] T018 [US2] Add `tier2_source_ratio` to `quality/metrics/source_quality.py`
  (now **4** keys), computing via `vault/credibility.py` over cycle frontmatter.
  Update the 030 `source-quality-metric.contract.md` 3-key→4-key note + register
  in `REGISTERED_METRIC_FAMILIES`. Make T016–T017 pass.
- [ ] T019 [US2] Re-bless affected baselines
  (`tests/fixtures/quality/baselines/*.baseline.json`) with the
  `metrics.source_quality.tier2_source_ratio` value via
  `research_framework.quality.baseline_update` with a "Spec 055" reason.

## Phase 5 — US3 + US4: COI cap + topic downgrade end-to-end (P2)
- [ ] T020 [P] [US3] Fixture + test: a COI citation (`coi: true`) caps to
  `commentary` end-to-end through the resolver and the 030 metric (the OpenAI-paper
  case from contract §4).
- [ ] T021 [P] [US4] Fixture + test: an off-field citation downgrades one step
  end-to-end (the industry-leader-off-topic case); and the combined COI+off-field
  → `unvetted` case.

## Phase 6 — US5: ledger annotation (P3, optional/light)
- [ ] T022 [P] [US5] If spec 048 v2's ledger has shipped: annotate `USED` rows
  with the recorded level (read-only join; missing ⇒ unannotated, never error;
  contract §7). Test: `test_ledger_credibility_annotation` + a missing-data
  degrade test. Else: file as a 048 v2 follow-up and mark T022 N/A.

## Phase 7 — Authoring guidance + docs (FR-009)
- [ ] T023 [P] Write `docs/source-credibility.md` — the author-facing guidelines:
  the 4 levels with decision rules, the COI rule, the off-field rule, worked
  examples (mirror `docs/observability-strategy.md` register). This is the
  "draw the line consistently" deliverable (Success Criterion 1).
- [ ] T024 [P] Update `.agents/skills/note-writer/SKILL.md` +
  `.agents/skills/source-relevance/SKILL.md` + `.agents/skills/verifier/SKILL.md`
  to apply the guidelines at authoring time (emit `credibility`/`coi`/rationale;
  verifier references the shape rules). Pointer to `docs/source-credibility.md`.

## Phase 8 — Polish / docs-sync
- [ ] T025 `ruff check .` + `ruff format --check .` clean; full `pytest -m "not e2e"`.
- [ ] T026 `bash build.sh --quality` — 4-metric `source_quality` family, 0
  regressions vs re-blessed baselines.
- [ ] T027 Doc-sync (per CLAUDE.md checklist): spec status → SHIPPED; ROADMAP
  flip; CHANGELOG `[Unreleased]` entry; `tier2_source_ratio` references in 030
  updated from "deferred to 055" → "shipped". Issue close + master-tracker flip.

## Dependencies & ordering
- **Hard gate**: 053 ships before T004+ (sequencing gate above).
- US1 (T006–T015) before US2 (T016–T019): the calculator imports the resolver.
- US3/US4 (T020–T021) after US1 resolver lands (they exercise it end-to-end).
- US5 (T022) gated on 048 v2; optional.
- Phase 7 docs can parallel implementation; Phase 8 last.

## Acceptance coverage
| Spec item | Tasks |
|-----------|-------|
| FR-001 (enum + per-citation + default + no-silent-default) | T006, T008, T010, T011 |
| FR-002 (declared + frozen + shape-validated) | T012–T015 |
| FR-003 (`source_id` resolution, no new identity) | T009, T010 |
| FR-004 (COI cap) | T007, T020 |
| FR-005 (topic downgrade via 053 role) | T007, T009, T021 |
| FR-006 (030 `tier2_source_ratio`) | T016–T019 |
| FR-007 (verifier shape rules) | T012–T015 |
| FR-008 (048 v2 annotation, optional) | T022 |
| FR-009 (guidelines doc + skills) | T023, T024 |
| SC: two authors → same level | T023 (guidelines) + T007 (deterministic resolver) |
| SC: deterministic metric | T016, T026 |
| SC: no LLM at gate time | T010, T015, T018 (pure-function design) |
