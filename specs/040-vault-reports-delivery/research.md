# Research & Decisions: Rich Vault Reports + Delivery (Spec 040)

**Date**: 2026-06-03 · **Stage**: post-clarify (Q1-Q6), pre-plan
**Context**: 040 drafted 2026-05-27. A 2026-06-03 audit reconciled it against the
shipped `[budget]` extras precedent, the existing `audit-report` surface, and the
just-specified spec 035 digest (overlapping sections).

## Audit findings (spec ↔ code reconciliation)

| spec claim | reality (2026-06-03) | resolution |
|------------|----------------------|------------|
| `[reports]` extra under Principle V (Q2) | `pyproject.toml` already ships `[project.optional-dependencies] budget = ["tiktoken>=0.6"]` (spec 033) | **precedent**: opt-in extras are permitted; `[reports]` follows it |
| weasyprint "pure Python, no LaTeX" | weasyprint needs **system libs** (Pango/cairo/GDK-PixBuf) — not friction-free | **Q2**: use **fpdf2** (genuinely pure-Python, no system libs) |
| `audit-report.md` surface | exists (referenced in `cli/research_phase3.py`, `cycle_runner.py`, the reporter path) | Layer 1 enriches a real artifact |
| Layer-1 sections (coverage/cost/sources) | **identical** to the just-specified 035 digest sections | **Q5**: reuse 035's `pipeline/digest/sections.py` + 022 calculators (no 3rd impl) |
| FR-002 "projected quality score" | no quality-score column in `sources.db` (same gap as 035 Q4) | **Q6**: rank by real `sources.db` yield + recency |
| FR-007 per-cycle "same enrichment" | `cycle-<N>-report.md` is the `cycle-report` **LLM-skill** artifact (narrative) | render a deterministic per-cycle *block*; don't overwrite skill prose |
| templates location | `templates/` is force-included into the wheel (`pyproject.toml`) | `templates/audit-report.md.j2` is the right home |

**Net**: the 3-layer shape is sound; the audit (a) swapped the PDF backend to a
genuinely pure-Python lib, (b) collapsed the Layer-1 ↔ 035 duplication into reuse
(035 → hard dep), and (c) reconciled the source-ranking signal to real data.

## Decisions

### D1 — Re-render every cycle (Q1)
Cheap; prior render retained by spec 050 git history; `./vault audit` forces
on-demand. **Rejected**: on-demand-only (staleness for unattended runs).

### D2 — fpdf2 under `[reports]` extra, not weasyprint (Q2)
Pure-Python, no system libs, tiny footprint; follows the `[budget]`/tiktoken
precedent. A small deterministic **markdown→PDF renderer** maps the report element
set (headings/paragraphs/tables/lists/links/code) to fpdf2 primitives. **Trade-off
accepted**: lower CSS fidelity than weasyprint. **Rejected**: weasyprint (system
libs — contradicts the "zero friction" goal); HTML-only (loses the printable PDF
artifact the legacy report had); defer-PDF (Layer 2 is the headline "look-at"
surface).

### D3 — Env-var-first SMTP credentials (Q3)
Universal, no new dep, mirrors spec 033's `RF_*_ACK` env pattern; keychain/`pass`
are later per-OS niceties. SMTP itself is P3 (US4) — mirror (US3) is the
secret-free primary channel. **Rejected**: keychain-first (per-OS branch upfront);
`pass`-first (advanced-user-only).

### D4 — Mirror includes digests (Q4)
`reports.mirror` copies audit-report + per-cycle reports + `_pipeline/digests/*`.
**Rejected**: reports-only (the digest is exactly what an operator wants off-box);
configurable-list (over-engineered for v1 — revisit if asked).

### D5 — Reuse 035 section builders; 035 becomes a HARD dep (Q5)
040 Layer 1 = wire `pipeline/digest/sections.py` (Coverage Delta, Cost Summary,
source-signal layer) into `audit-report.md` + the per-cycle block, and add the two
NEW sections (Flagged Issues, Top Discovered Sources). **Why**: a third copy of
coverage/cost rendering across harness + digest + reports is exactly the
duplication Principle "DRY gate" discipline warns against. **Rejected**:
independent rendering (duplication + drift); full-merge-engine (larger refactor
than warranted — a shared `sections.py` consumed by both is enough).

### D6 — Top Sources ranked by real sources.db signals (Q6)
notes_generated/referencing yield + recency. Same resolution as 035 Q4; ships now
without gating on 030/055. **Rejected**: gate-on-055 (cross-wave block);
recency-only (loses the yield signal operators care about).

### D7 — Layer independence
Layer 1 (markdown) → Layer 2 (PDF, opt-in extra) → Layer 3 (mirror) → Layer 3b
(SMTP) each ship + fail independently; all delivery failures are logged +
non-blocking (the cycle exit code reflects only the cycle). Confirmed against the
spec's US2.2/US3.2/US4.2 acceptance scenarios.

## Cross-spec interactions
- **035 (HARD)** — section builders. Sequence 040 after 035.
- **022 (HARD)** — metric calculators (via 035).
- **033 + 028 (HARD)** — cost actual-vs-budget + sidecars. Shipped.
- **050 (relevant)** — re-render-every-cycle relies on 050 retaining prior renders.
- **055 (soft/future)** — credibility-weighted Top Sources enrichment.
- **039 (soft)** — installer advises the `[reports]` extra.
- **026 (test isolation)** — report/mirror fixtures use `tmp_path`.

## Determinism / Principle check
Layer 1 deterministic (reuses 035's deterministic builders); PDF is a deterministic
md→PDF pass; mirror is a file copy; SMTP is the only side-effecting channel (opt-in,
non-blocking). Principle V upheld via the opt-in `[reports]` extra (fpdf2) — the
`[budget]` precedent. Principle X: reports land under `_pipeline/`; the mirror copies
OUTSIDE the vault (no vault-history mutation). ✅
