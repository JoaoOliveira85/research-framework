# Tasks: 029 Source Manager Correctness

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Input**: `spec.md` (clarified 2026-06-03), `plan.md`, `research.md` (D1–D6), `contracts/source-attribution.contract.md`, `quickstart.md`.
**Tests**: TDD per Principle III — each bug gets a RED test before its fix. **[P]** = parallelizable.
**Sequencing**: implement **after spec 049 merges** (the `_cycle_helpers` split); FR-001's function + the FR-005 test import from the post-049 module path. All other tasks are 049-independent.

---

## Phase 1 — Setup
- **T001** Confirmed: 049 merged; `notify_required_source_degraded` lives in `pipeline/_helpers/source_signals.py`. Recorded in the test module docstring; the FR-005 threshold test imports it via the existing `cycle_runner` re-export.

## Phase 2 — US1: Source degradation incidents are durably recorded (P1) 🎯 MVP

**Goal**: `source-incidents.md` is actually written (Bug 1 fixed) while the working JSON sidecar is preserved; recovery appends a resolved line.

**Independent test**: drive a required-source degradation on a `tmp_path` vault → both `source-incidents.md` (with a `degraded` line) and `cycle-NNN-source-incidents.json` exist.

### Tests first (TDD — RED)
- **T002** [P] Added `TestSourceIncidentsDurability` (4 tests) to `tests/pipeline/test_source_manager_correctness.py`: `test_notify_writes_markdown_and_sidecar`, `test_enrichment_role_not_counted`, `test_resolved_line_appended_on_recovery`, `test_arity_bug_surfaces_not_swallowed`. Committed RED before T003/T004.

### Implementation
- **T003** Fixed the call site in `_helpers/source_signals.py`: `md(source_name, reason, vault_dir)`; narrowed `except Exception` → `except OSError` so a `TypeError`/signature mismatch propagates (FR-001).
- **T004** Added `mark_resolved(name, vault_dir)` + `_has_unresolved_incident` + shared `_append_incident_line`/`_incidents_path` helpers to `source_manager.py`; wired recovery into `record_cycle` Step 4 (append a `resolved` line when a previously-degraded source produces citations again). (FR-007)
- **T005** `TestSourceIncidentsDurability` green; the `cycle-NNN-source-incidents.json` sidecar path is untouched (still asserted by `test_notify_writes_markdown_and_sidecar`).

**Checkpoint**: US1 shippable — operators get the durable markdown incident log back.

---

## Phase 3 — US2: Source quality metrics accurately reflect note attribution (P1)

**Goal**: `record_cycle` counts `notes_generated` from frontmatter `source_urls` (Bug 2 fixed); one shared predicate feeds both metrics; `consecutive_empty_cycles` becomes correct.

**Independent test**: 3 sources A/B/C + 5 notes (cite A; B; C; A+B; none) → `sources.db` `notes_generated` = A:2, B:2, C:1.

### Tests first (TDD — RED)
- **T006** [P] Added `TestNormalizeSourceUrl` (7-case parametrize + `test_none_is_empty`). Committed RED.
- **T007** [P] Added `TestNoteCitesSource` (8-case parametrize + `test_missing_field_is_false`). Committed RED.
- **T008** [P] Added `TestRecordCycleAttribution`: `test_notes_generated_from_frontmatter` (A:2/B:2/C:1, mixed bare-filename + vault-relative shapes), `test_empty_streak_increments_then_resets`, `test_placeholder_note_counts_for_no_source`. Committed RED.

### Implementation
- **T009** Added `normalize_source_url(url)` to `source_manager.py` (stdlib `urlsplit`/`urlunsplit`; host-lowercase, single trailing-slash strip, fragment drop, query preserved, bare-name lowercased).
- **T010** Extracted `_note_cites_source(fm, name, url)` + `_read_frontmatter_lenient`; refactored `_count_notes_referencing` to route through the shared predicate (skip-don't-raise preserved via the lenient reader).
- **T011** Rewrote `record_cycle` Step 2: resolve each `notes_created` entry via `Path(name).name` + `rglob` under `data_vault/` (`_resolve_note_frontmatter`), count via `_note_cites_source`. Per-cycle scope; Step 4 SQL unchanged (FR-004).
- **T012** `TestNormalizeSourceUrl` + `TestNoteCitesSource` + `TestRecordCycleAttribution` green.

**Checkpoint**: US2 shippable — metrics + archival decisions are correct going forward.

---

## Phase 4 — US3: Existing test coverage no longer hides production bugs (P2)
- **T013** Found the strict 2-arg offender `_mark(name, reason)` in `tests/pipeline/test_source_failure_threshold.py::test_one_required_degraded_warns_and_continues`; updated it to the real 3-arg `_mark(name, reason, vault_dir)` so an arity regression now breaks it loudly (the other sites use permissive `lambda *_a, **_k` and tolerate the correct 3-arg call). No remaining test shields the arity (FR-005).

---

## Phase 5 — FR-008: Reconciliation script for already-corrupted vaults

### Tests first (TDD — RED)
- **T014** [P] Added `tests/scripts/test_reconcile_source_metrics.py` (5 tests): `test_dryrun_reports_wrongful_archival`, `test_apply_unarchives_and_resets_db_only` (tree-digest byte-identity), `test_uncited_source_left_untouched`, `test_clean_vault_zero_false_positives`, `test_idempotent`. Committed RED (script missing).

### Implementation
- **T015** Implemented `scripts/reconcile_source_metrics.py` (FR-008): `--vault`, `--apply` (default dry-run); `reconcile(vault, *, apply)` computes `cited_now` per source via `source_manager._count_notes_referencing`; (a) un-archives `status='archived' AND cited_now>0`; (b) resets `consecutive_empty_cycles=0` where `cited_now>0`; (c) leaves `cited_now==0` untouched. Writes only `sources.db`; idempotent. (Did not touch `source_cycles` history — the optional reporting correction; cumulative `total_notes_generated` is a derived SUM.)
- **T016** `test_reconcile_source_metrics.py` green (5/5).

---

## Phase 6 — Polish
- **T017** SC-004 is proven self-contained by `test_arity_bug_surfaces_not_swallowed` (monkeypatches a 2-arg `mark_degraded` under the 3-arg call site and asserts `pytest.raises(TypeError)`) — no manual revert needed; the narrowed `except OSError` lets the `TypeError` propagate.
- **T018** [P] Full sweep clean: targeted suites 44/44; full fast loop `2106 passed` (with `PYTHONPATH=src` for subprocess-import tests — a pre-existing local env quirk that also affects `main`, fixed by CI's editable install); `ruff check` + `ruff format --check` clean on all touched files.
- **T019** [P] `CHANGELOG.md` `[Unreleased]` updated (Fixed + Added entries).

---

## Dependencies & ordering
- **049 merge** gates T001/T003 (import path) — the only cross-spec gate. Everything in Phase 3/5 is 049-independent and can be built in parallel with the rebase.
- TDD pairs: T002→T003/T004→T005 · T006/T007/T008→T009/T010/T011→T012 · T014→T015→T016.
- US1 (Phase 2) is the **MVP** and independently shippable. US2 (Phase 3) is independently shippable. US3 (T013) depends on T003 landing (so the real path exists to test against).

## Parallel example
```
# RED tests up front (distinct test classes / files):
T002 + T006 + T007 + T008 + T014
# Polish:
T018 + T019
```

## Acceptance coverage → spec.md
| User Story | Evidence (tasks.md) |
|---|---|
| US1 — incidents durably recorded | `TestSourceIncidentsDurability` (T002 → T003/T004 → T005); SC-004 revert-proof (T017) |
| US2 — accurate attribution | `TestNormalizeSourceUrl`+`TestNoteCitesSource`+`TestRecordCycleAttribution` (T006-T008 → T009-T011 → T012) |
| US3 — tests stop hiding bugs | monkeypatch retirement (T013) |
| FR-008 — reconciliation | `test_reconcile_source_metrics.py` (T014 → T015 → T016) |
