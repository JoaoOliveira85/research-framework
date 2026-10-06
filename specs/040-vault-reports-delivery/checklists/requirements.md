# Specification Quality Checklist: Rich Vault Reports + Delivery

**Purpose**: Validate specification completeness/quality before implementation
**Created**: 2026-06-03 · **Feature**: [spec.md](../spec.md)
**State**: post-clarify (Q1-Q6) + plan + research + contract + tasks + analyze.
**IMPLEMENT-READY** — gated only by **spec 035** (Layer 1 reuses 035's section builders).

## Content Quality
- [x] No implementation details in the requirements (the *what*; the md→PDF mapping + ranking formula live in `contracts/`)
- [x] Focused on operator value (a report a human actually reads; off-box delivery)
- [x] 4 user stories (P1 markdown → P2 PDF → P2 mirror → P3 SMTP), each with an independent test + acceptance scenarios
- [x] All mandatory sections present

## Requirement Completeness
- [x] **No `[NEEDS CLARIFICATION]` markers remain** — Q1-Q6 resolved (2026-06-03):
  - Q1 → re-render the audit report **every cycle**
  - Q2 → **fpdf2** (pure-Python) under a `[reports]` extra, **not** weasyprint
  - Q3 → **env-var-first** SMTP credentials
  - Q4 → mirror includes `_pipeline/digests/*`
  - Q5 → **reuse 035's `pipeline/digest/sections.py` builders** (035 → HARD dep)
  - Q6 → Top Sources ranked by real `sources.db` yield + recency (no quality-score column)
- [x] Requirements testable + unambiguous (every FR → ≥1 task + a contract rule)
- [x] Success criteria measurable (<10MB / zero system libs; PDF <10s; mirror <5s; **0 cycles fail from delivery**)
- [x] Determinism explicit (Layer 1 reuses 035's deterministic builders; PDF/mirror are mechanical; SMTP is the only side effect — opt-in, non-blocking)
- [x] Out-of-scope explicit (HTML dashboards → 043; Slack/webhooks → 036 v2; encryption; multi-recipient; cross-vault; weasyprint/LaTeX)

## Cross-spec consistency (from /analyze + 2026-06-03 audit)
- [x] **Q2 PDF backend reconciled** — weasyprint (needs Pango/cairo system libs) → **fpdf2** (pure-Python); stray weasyprint refs in US2 acceptance + Edge Cases swept to fpdf2; the historical **Input** line annotated *superseded → fpdf2*; Out-of-scope keeps weasyprint as the *declined* option (correct)
- [x] **Q5 reuse reconciled** — Layer 1 calls 035's `sections.py`; FR-001/003/006 say "reuse, no third impl"; **035 elevated soft → HARD dep** in Assumptions + Dependencies + the tasks sequencing gate (T006 confirms the import first)
- [x] **Section count reconciled 4 → 5** — reusing 035 naturally yields a 3rd reused section (**Source Quality Drift**, 035 §7) alongside Coverage Delta + Cost Summary. Spec **FR-003b added**; US1 narrative + Independent Test + acceptance scenario + SC-001 + acceptance-coverage table all moved 4 → 5 to match contract §1 + tasks T005/T010 (which already said 5)
- [x] **Q6 ranking reconciled** — Top Sources by real `sources.db` yield + recency; stale "source-quality projection" wording in US1 narrative + acceptance scenario 2 swept
- [x] **FR ↔ task mapping complete** — FR-001..FR-019 each land on ≥1 task (T002-T020); acceptance table US1-US4 → T006-T020 verified against `tasks.md`
- [x] Principle IV (no LLM — deterministic builders + verifier; no agent dispatch), V (fpdf2 opt-in extra — the `[budget]`/tiktoken precedent; base install unchanged), X (reports under `_pipeline/`; mirror copies OUTSIDE the vault)
- [x] Test fixtures `tmp_path`-isolated (spec 026); SMTP/mirror tests hermetic (fake SMTP, `tmp_path` target — no real network/real paths)

## Notes
- **Sequenced AFTER 035** — the lone external gate (Layer 1 imports `pipeline/digest/sections.py`). Layers 2/3 (PDF/mirror/SMTP, T011-T020) need only a report artifact and can be built in parallel against a stub, so 040 is not fully blocked.
- The 2026-05-27 draft was structurally sound; the audit (a) swapped the PDF backend to a genuinely pure-Python lib, (b) collapsed the Layer-1 ↔ 035 duplication into reuse, (c) reconciled source ranking to real `sources.db` data. No user story was removed.
- `/analyze`: after the 5-section + fpdf2 + ranking sweeps, **no contradictions** among spec ↔ contract ↔ plan ↔ tasks. One implement-time validation flagged in plan Complexity — 035's `sections.py` builder signatures (the reuse seam) — confirmed at the T006 sequencing gate.
