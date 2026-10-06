# Tasks: Rich Vault Reports + Delivery (Spec 040)

**Input**: [spec.md](./spec.md) · [plan.md](./plan.md) · [research.md](./research.md) · [contracts/report-delivery.contract.md](./contracts/report-delivery.contract.md)
**Status**: ready for `/speckit.implement` — **AFTER spec 035 merges** (Layer 1 hard-depends on `pipeline/digest/sections.py`).
**Tests**: TDD per layer. `[P]` = parallelizable (distinct files, no ordering dep).

## Sequencing gate (READ FIRST)

> **Layer 1 (T006-T010) is BLOCKED until spec 035 ships** `pipeline/digest/sections.py`.
> Layers 2/3 (PDF/mirror/SMTP, T011-T020) only need a report artifact to act on and
> MAY be built in parallel against a stub report. T006's first action is to confirm
> `from research_framework.pipeline.digest import sections` imports; if not, STOP and
> finish 035 first. No LLM dispatch anywhere in this spec (Principle IV).

---

## Phase 1 — Setup

- [ ] **T001** Create `src/research_framework/pipeline/reports/__init__.py` +
  `tests/pipeline/reports/__init__.py`. Package skeleton only (no logic yet).
- [ ] **T002** `[P]` Add the `[reports]` extra to `pyproject.toml`:
  `[project.optional-dependencies] reports = ["fpdf2>=2.7"]` — placed beside the
  existing `budget = ["tiktoken>=0.6"]`. (FR-009; covered for real by T011's test.)

## Phase 2 — Foundational (blocking prerequisites)

- [ ] **T003** Settings keys in `pipeline/settings.py` (canonical loader, spec 025
  B7): `reports.mirror.target` (str|None), `reports.smtp.{enabled:bool=False,
  recipient,server,port:int,from}` — ALL optional, default unset/false (FR-013,
  FR-016, FR-019). **Test first**: `tests/pipeline/test_settings_reports.py` —
  absent block ⇒ all defaults; partial block ⇒ unset fields default; types coerced.
- [ ] **T004** `[P]` Build the test fixture: extend the spec-035 digest fixture
  (cycles + coverage + cost + sources already present) under
  `tests/fixtures/reports/` with (a) ≥1 flagged issue (a verifier rejection record +
  a spec-051 preflight fail), (b) ≥2 newly-discovered `sources.db` rows with
  differing yield/recency. `tmp_path`-copied in tests (spec 026 — never mutate the
  committed fixture).
- [ ] **T005** `templates/audit-report.md.j2` skeleton (Jinja2) — header + the 5
  section slots (Coverage Delta, Top Sources, Cost Summary, Source Quality Drift,
  Flagged Issues), each rendering a "No data in scope." line when its context is
  empty (FR-005). Markdown is canonical (Key Entities).

---

## Phase 3 — User Story 1: Layer-1 markdown enrichment (P1) 🎯 MVP

**Goal**: `audit-report.md` carries the reused 035 sections + 2 new sections.
**Independent test**: render against T004's fixture; assert the 5 sections + "no data" behaviour.

- [ ] **T006** *(BLOCKED on 035)* `pipeline/reports/layer1.py::compose_report()` —
  import + call spec 035's `pipeline/digest/sections.py` builders (Coverage Delta,
  Cost Summary, Source Quality Drift) for the report range; feed the template
  (T005). **Test first**: `tests/pipeline/reports/test_layer1_reuse.py` — asserts the
  035 builders are invoked (no reimplementation) and their output appears in the
  rendered markdown (FR-001, FR-003, FR-006). First line of the test confirms the
  035 import (sequencing gate).
- [ ] **T007** Top Discovered Sources section (NEW, FR-002, Q6) — query `sources.db`
  for rows first-seen in range; rank by Σ`notes_referencing`, then Σ`notes_generated`,
  then recency; **name-ascending tiebreaker**; top 5. **Test first**:
  `test_top_sources_ranking.py` — fixed fixture ⇒ exact order incl. the tiebreaker;
  <5 sources ⇒ shorter list; 0 ⇒ "No data in scope."
- [ ] **T008** `[P]` Flagged Issues section (NEW, FR-004) — aggregate preflight
  fails + un-recovered verifier rejections + schema-drift + retry-exhaustion in
  scope; row = stage + id + severity + suggested step; sort severity desc, stage
  asc. **Test first**: `test_flagged_issues.py` — fixture issues render sorted;
  empty ⇒ "No flagged issues this cycle."
- [ ] **T009** `[P]` Per-cycle deterministic block (FR-007) —
  `compose_cycle_block(cycle_n)` renders the same sections scoped to one cycle as a
  standalone markdown block the `cycle-report` skill can include (does NOT overwrite
  skill prose). **Test first**: `test_cycle_block.py` — block is self-contained +
  scoped to the single cycle.
- [ ] **T010** End-to-end Layer-1 render (US1 acceptance) —
  `test_audit_report_e2e.py`: full `audit-report.md` against T004's fixture shows all
  5 sections with expected content (coverage advanced/stagnated/regressed; top
  sources; cost actual/budget; drift; flagged issues) AND the "No data in scope."
  lines fire for empty sub-data (FR-005, SC-001). Wire the render into the reporter /
  `cycle_runner` cycle-end path; re-renders every cycle, overwriting prior (FR-008).

**Checkpoint**: Layer 1 independently shippable. Markdown report is enriched.

---

## Phase 4 — User Story 2: PDF via opt-in `[reports]` extra (P2)

**Goal**: `audit-report.pdf` beside the `.md` when fpdf2 is installed; graceful otherwise.
**Independent test**: with fpdf2 → PDF exists + parseable; base install → only `.md`, no error.

- [ ] **T011** Confirm `[reports]`=fpdf2 (FR-009) — `test_reports_extra.py`: parse
  `pyproject.toml`, assert `reports` extra lists `fpdf2` and sits beside `budget`.
- [ ] **T012** `pipeline/reports/pdf.py::render_pdf(markdown_path) -> pdf_path` — a
  deterministic markdown→fpdf2 pass covering the template's element set
  (headings/paragraphs/GFM tables/lists/links/code) per contract §4, bundled core
  fonts only (FR-010, FR-012). **Test first** (gated `@pytest.mark.skipif` on fpdf2
  import): `test_pdf_render.py` — assert STRUCTURAL facts (page count > 0; section
  headings present in extracted text; link runs preserved), NOT byte-identity.
- [ ] **T013** Import-guard behaviour (FR-011) — `test_pdf_import_guard.py`: fpdf2
  absent ⇒ silent skip, `.md` still produced, no warning; but `--format pdf`
  explicitly requested ⇒ error `fpdf2 unavailable; install with pip install
  research-framework[reports]`. (Simulate absence by monkeypatching the import.)
- [ ] **T014** `[P]` Bundled-font no-crash (FR-012) — `test_pdf_fonts.py`: render
  succeeds with only fpdf2 core fonts available (no system-font lookup path taken).

**Checkpoint**: PDF ships independently of delivery.

---

## Phase 5 — User Story 3: Cloud-folder mirror (P2)

**Goal**: reports (incl. digests, Q4) copied to `reports.mirror.target`; non-blocking.
**Independent test**: set target to `tmp_path`; cycle end ⇒ files present; unreachable ⇒ warn, cycle ok.

- [ ] **T015** `pipeline/reports/mirror.py::mirror_reports()` — `shutil.copy2`
  `audit-report.{md,pdf?}` + per-cycle reports + `_pipeline/digests/*.{md,pdf?}`
  (Q4) to `target`; accumulate (no deletes). **Test first**: `test_mirror_copy.py`
  (`tmp_path` target) — all expected files incl. a digest land; source vault
  untouched (FR-013, FR-014, SC-004).
- [ ] **T016** Failure handling (FR-015) — `test_mirror_failure.py`: unreachable /
  locked target ⇒ retry ≤3×@1s ⇒ log "mirror skipped: target unavailable" + cycle
  exits 0 (non-blocking; SC-006). (Backoff patched to 0 in test.)
- [ ] **T017** `[P]` Unset target (FR-019) — `test_mirror_noop.py`: `mirror.target`
  unset ⇒ no copy attempt, no warning (silent noop).

**Checkpoint**: secret-free delivery works.

---

## Phase 6 — User Story 4: SMTP email (P3)

**Goal**: opt-in email w/ PDF attachment + 5-line summary; env-var creds; non-blocking.
**Independent test**: fake SMTP captures one message w/ attachment; bad creds ⇒ warn, cycle ok.

- [ ] **T018** `pipeline/reports/smtp.py::send_report()` — when
  `reports.smtp.enabled` + creds present (env-var first, Q3: `RF_SMTP_USER` /
  `RF_SMTP_PASSWORD`), build a `email.message.EmailMessage`, attach the PDF (if
  rendered), body = 5-line summary (notes added / cost actual-vs-budget / top
  flagged issue) per FR-018; send via `smtplib`. **Test first**:
  `test_smtp_send.py` — monkeypatched/`aiosmtpd` capture asserts one message,
  correct recipient, attachment present, 5-line body (SC-005).
- [ ] **T019** Failure handling (FR-017) — `test_smtp_failure.py`: SMTP raises
  (unreachable / bad creds) ⇒ log + cycle exits 0 (non-blocking; SC-006).
- [ ] **T020** `[P]` Unconfigured (FR-019) — `test_smtp_noop.py`:
  `smtp.enabled:false`/absent ⇒ no send attempt (silent noop).

**Checkpoint**: all four user stories independently shippable.

---

## Phase 7 — Polish & cross-cutting

- [ ] **T021** `[P]` Layer-independence integration test
  (`test_layer_independence.py`, SC-006): a forced PDF failure + a forced mirror
  failure + a forced SMTP failure in one cycle ⇒ cycle still exits 0 and Layer-1
  markdown is intact.
- [ ] **T022** `[P]` Docs: `settings.yaml` reference gains `reports.*` keys; README /
  installer note advises `pip install research-framework[reports]` (FR / Soft-dep on
  039); document env-var SMTP creds + the mirror-includes-digests behaviour.
- [ ] **T023** `[P]` CHANGELOG `[Unreleased]` + spec status header → SHIPPED on merge;
  ROADMAP queue tick (per CLAUDE.md doc-sync checklist).
- [ ] **T024** `ruff check .` + `ruff format --check .` clean; full `pytest -m "not
  e2e"` green; `build.sh --quality` if the reporter path changed (CLAUDE.md gate).

---

## Dependencies & ordering

- **External gate**: spec 035 merged ⇒ unblocks T006-T010 (Layer 1). T011-T020
  (Layers 2/3) need only a report artifact and may proceed in parallel.
- **Within 040**: Setup (T001-T002) → Foundational (T003-T005) → US1 (T006-T010,
  the MVP, blocked on 035) ∥ US2 (T011-T014) ∥ US3 (T015-T017) ∥ US4 (T018-T020) →
  Polish (T021-T024).
- US2/US3/US4 are mutually independent (distinct files) — parallelizable once a
  report artifact exists.

## Parallel example

```
# After T005, with 035 merged:
T006 (Layer-1 reuse wiring)            # blocked-on-035 critical path
# In parallel against a stub/real report:
T011 [P] reports-extra test
T012     md→PDF renderer
T015     mirror copy
T018     SMTP send
```

## Implementation strategy

**MVP = Phase 1-3 (Layer 1).** That alone makes the report readable — the headline
value. Ship it, then add PDF (Phase 4), mirror (Phase 5), SMTP (Phase 6)
independently. Each layer fails closed and non-blocking (SC-006): no delivery
concern can ever fail a research cycle.
