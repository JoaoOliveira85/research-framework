# Tasks: Cross-Cycle Digest (Spec 035)

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Branch**: `035-cross-cycle-digest` · **Wave 3 / rc1**
**Inputs**: [spec.md](./spec.md), [plan.md](./plan.md), [research.md](./research.md), [contracts/digest-format.contract.md](./contracts/digest-format.contract.md)

**Format**: `[ID] [P?] [Story] Description` — `[P]` = parallelizable.

> **No external sequencing gate**: all hard deps (028 sidecars, 050 git topology,
> 051 inbound-link index, 022 quality reports) are **shipped on `main`**. 030/055
> are optional future enrichments, not blockers.
>
> **TDD discipline**: each story's "Tests" precede its implementation and MUST
> fail first. Structured for foreman `### Testing Requirements` enrichment (ADR-0010).

## Phase 0 — Spec-kit artifacts ✅ (this pass)
- T001 spec.md reconciled to shipped reality + Q1-Q5 clarified.
- T002 contracts/digest-format.contract.md (layout + ranker/gap/drift formulas + determinism).
- T003 research.md (D1–D6 + audit table) + plan.md + checklist.

## Phase 1 — Setup
- [ ] T004 [P] Build the digest fixture under `tests/fixtures/digest/` — a vault
  with 3 cycles across a 1-week window: `_pipeline/cycles/cycle-00{1,2,3}/` +
  matching `cycle-NNN-quality-report.json`, two `cycle-<N>-report.md`, a small
  `sources.db` (`source_cycles` rows), `coverage-targets.json` (vault root), 028
  cost sidecars. Engineer: one note to top Strongest Signals, one coverage
  category to regress, one source to drift. `tmp_path`-isolated (spec 026). Data only.
- [ ] T005 Scaffold `src/research_framework/pipeline/digest/` (`__init__`, `scope`,
  `sections`, `ranker`, `render`) + `templates/digest.md.j2` stub + a `cli` `digest`
  verb stub (argparse, no logic yet).

## Phase 2 — US2: determinism + idempotency foundation (P2, written first)
### Tests (MUST fail)
- [ ] T006 [P] [US2] `tests/pipeline/test_digest.py::test_repeat_run_byte_identical`
  — two runs on the same fixture produce byte-identical output excluding the
  `_rendered-at` header line (contract §11 / SC-002).
- [ ] T007 [P] [US2] `...::test_digest_offline` — runs with no network access
  (monkeypatch/socket guard) and completes (contract §1; SC: no external dep).

## Phase 3 — US3: Strongest Signals ranker (P2)
### Tests (MUST fail)
- [ ] T008 [P] [US3] `tests/pipeline/test_digest_ranker.py::test_composite_score`
  — table-driven over contract §4: `inbound + source_drift_bonus +
  freshness_points`; **note-path-asc tiebreaker** on equal scores.
### Implementation
- [ ] T013 [US3] `ranker.py` composite scorer (reusing
  `vault/indexer.inbound_link_counts`) + the Strongest Signals renderer (wikilink,
  score-breakdown rationale, 1-line summary). Make T008 pass.
- [ ] T020 [P] [US3] `...::test_strongest_signals_top5_deterministic` — top-5
  ordering is stable across repeat runs on the fixture (incl. <5-notes case).

## Phase 4 — US4: Gaps detector (P2)
### Tests (MUST fail)
- [ ] T009 [P] [US4] `tests/pipeline/test_digest_gaps.py::test_gap_detection`
  — regressed (`end < start`), stagnant (`flat AND < target`), healthy
  (→ "No regressions or stagnations in scope") per contract §5.
### Implementation
- [ ] T014 [US4] Gaps renderer over `coverage-targets.json` (vault root) ×
  `cycle-NNN-quality-report.json` progress; non-empty healthy line. Make T009 pass.

## Phase 5 — US1: the verb + remaining sections (P1)
- [ ] T010 [US1] Wire the `./vault digest` verb: `--since` + `--last-week/-month/-quarter`
  desugar; `--output`; default `_pipeline/digests/digest-<start>--<end>.md`;
  no-cycles-in-scope ⇒ exit 0 + message + no file (contract §2). Tests:
  `test_last_week_desugars`, `test_no_cycles_exit_zero_no_file`, `test_future_since_nonzero`.
- [ ] T011 [US1] `scope.py` — enumerate in-range cycles from the **filesystem**
  (cycle dirs carrying the quality-report completion marker) + resolve the git
  run-level range/dates (Q5). Test: `test_scope_filesystem_enumeration` +
  `test_scope_clamps_pre_vault_since`.
- [ ] T012 [US1] Source Quality Drift renderer (FR-006/Q4): `notes_generated`/
  `notes_referencing` deltas + degraded transitions + `consecutive_empty_cycles`
  crossings from `sources.db`; flat sources omitted. Test:
  `test_drift_from_sources_db` + `test_drift_db_locked_omits_section` (contract §12).
- [ ] T015 [US1] New Notes by Category renderer (group by note `type`, declared order).
- [ ] T016 [US1] Coverage Delta renderer (full per-category table; distinct from Gaps).
- [ ] T017 [US1] Cost Summary renderer over 028 `cycle-NNN/agent-calls/*.json`
  (per-stage + per-cycle ASCII sparkline; missing sidecars ⇒ 0 + footer note).
- [ ] T018 [US1] Cycle Index renderer (filesystem cycles; ship SHA = run squash
  commit per 050; 1-line summary from `cycle-<N>-report.md` H1 or "(no report)").
- [ ] T019 [US1] `tests/pipeline/test_digest.py::test_end_to_end_fixture` — full
  render: file at expected path; Header + 7 sections present AND populated;
  acceptance scenarios US1.1–US1.3.

## Phase 6 — Robustness + performance
- [ ] T021 [P] Robustness tests: missing/malformed `cycle-<N>-report.md` ⇒ skip +
  footer warning, run succeeds (FR-015); **LLM-call-free assertion** (no
  `agent_call` dispatch in the window — SC-004); schema-migrated annotation.
- [ ] T022 [P] `...::test_digest_under_5s` — fixture digest renders well under the
  SC-001 budget (pure-local guard).

## Phase 7 — Docs / polish
- [ ] T023 [P] README: the `./vault digest` verb + the cron/launchd one-liner (FR-013);
  `docs` pointer.
- [ ] T024 `ruff check .` + `ruff format --check .` clean; `pytest -m "not e2e"` green;
  the tier-5 verb e2e green.
- [ ] T025 Doc-sync (CLAUDE.md checklist): spec → SHIPPED; ROADMAP flip; CHANGELOG
  `[Unreleased]` (new `./vault digest` verb); issue close + master-tracker flip.

## Dependencies & ordering
- US3 (ranker) + US4 (gaps) pure functions land before US1 renderers that embed
  them (T013→ used by T019; T014→ used by T019).
- T011 (scope) precedes the section renderers (they iterate in-range cycles).
- US2 determinism tests (T006/T007) validate the whole once sections exist —
  run them in CI after Phase 5; write them first as failing specs.

## Acceptance coverage
| Story | Tasks |
|-------|-------|
| US1 — weekly digest replaces git-log spelunking | T010, T011, T012, T015, T016, T017, T018, T019 |
| US2 — deterministic + idempotent | T006, T007, T021 |
| US3 — Strongest Signals | T008, T013, T020 |
| US4 — Gaps | T009, T014 |
| FR-001..003 (verb/flags/output) | T010 |
| FR-004 (Header + 7 sections) | T012–T018, T019 |
| FR-006 (drift, Q4) | T012 |
| FR-007 (ranker, Q2) | T008, T013, T020 |
| FR-008 (gaps, path-fixed) | T009, T014 |
| FR-009 (cost) | T017 |
| FR-010/011 (filesystem cycle index, Q5; determinism) | T011, T018, T006 |
| FR-012/SC-004 (LLM-free) | T021 |
| FR-014/SC-001 (<5s) | T022 |
| FR-015 (robustness) | T021 |
