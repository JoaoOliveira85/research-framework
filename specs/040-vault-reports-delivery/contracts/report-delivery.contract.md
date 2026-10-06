# Contract: Rich Vault Reports + Delivery

**Spec**: 040 · **Status**: authored 2026-06-03 (post-clarify Q1-Q6). Authoritative
for the report layout, the 035-reuse map, the markdown→PDF mapping, and the
mirror/SMTP contracts. Layer 1 is deterministic; delivery is non-blocking.

---

## 1. Layer 1 — `audit-report.md` layout

Header + sections (reuse vs new marked):

| # | section | source |
|---|---------|--------|
| H | Header (rendered-at, range, vault identity) | local |
| 1 | Coverage Delta | **REUSE** `pipeline/digest/sections.py` (spec 035 §5/§8) |
| 2 | Top Discovered Sources | **NEW** (this spec) — see §2 |
| 3 | Cost Summary | **REUSE** 035 Cost Summary (spec 035 §9; 028 sidecars; 033 budget) |
| 4 | Source Quality Drift | **REUSE** 035 §7 (sources.db signals) |
| 5 | Flagged Issues | **NEW** (this spec) — see §3 |

- Every section renders an explicit "No data in scope." line when empty (FR-005).
- The per-cycle surface (FR-007) emits the SAME sections scoped to one cycle as a
  **deterministic block**; it does NOT overwrite the `cycle-report` LLM-skill prose
  (it is appended / included by the skill).
- Markdown is the canonical content source-of-truth. Template:
  `templates/audit-report.md.j2`.

## 2. Top Discovered Sources (NEW, FR-002, Q6)

- "Newly-discovered in scope" = source first appears in `sources.db` (`sources`
  table) within the range.
- **Rank by real signals** (no quality-score column exists): primary key =
  Σ`notes_referencing` (yield), secondary = Σ`notes_generated`, tertiary =
  recency (most-recent cycle touched). Top 5 (or fewer); **tiebreaker = source
  name ascending** (determinism).
- Each entry: source identifier + 1-line summary + the ranking signal
  (e.g. `12 refs / 4 notes / cycle 7`). *(055 credibility = future enrichment.)*

## 3. Flagged Issues (NEW, FR-004)

Aggregate, in scope: source preflight failures (spec 051 preflight verdicts),
verifier rejections not auto-recovered, schema-drift detections, retry-exhaustion
records. Each row: stage + identifier + severity + suggested next step. Sorted by
severity desc, then stage. Empty ⇒ "No flagged issues this cycle."

## 4. Layer 2 — PDF via fpdf2 (Q2, FR-009..012)

- `pyproject.toml`: `[project.optional-dependencies] reports = ["fpdf2>=2.7"]`
  (mirrors `budget = ["tiktoken>=0.6"]`). fpdf2 is pure-Python; **no system libs**.
- **markdown→PDF mapping** (deterministic; the element set the template emits):

  | markdown element | fpdf2 rendering |
  |------------------|-----------------|
  | `#`/`##`/`###` headings | sized/bold cells |
  | paragraphs | `multi_cell` wrapped text |
  | tables (GFM pipe) | gridded cells, header row bold |
  | `-`/`1.` lists | indented bullets/numbers |
  | `[text](url)` links | `link=` on the text run (preserved/clickable) |
  | fenced code | mono font block |

- Import-guarded: `fpdf2` missing ⇒ **silent skip** (no error, no warning) UNLESS
  `--format pdf` was requested, which then errors: `fpdf2 unavailable; install
  with pip install research-framework[reports]`. Markdown is always produced.
- Bundled core fonts only (no system-font dependency; FR-012). Never crash on fonts.
- PDF determinism: assert structural facts in tests (page count > 0; section
  headings present; text extractable) — NOT byte-identity (PDF carries timestamps).

## 5. Layer 3 — Cloud-folder mirror (FR-013..015, Q4)

- Setting: `reports.mirror.target: <filesystem path>` (optional; unset ⇒ silent
  noop, FR-019/US3.3).
- At cycle end, copy (`shutil.copy2`, NOT rsync; accumulate, no deletes): the
  `audit-report.{md,pdf?}`, the per-cycle reports, AND `_pipeline/digests/*.{md,pdf?}`
  (Q4/FR-014).
- Target unreachable/locked ⇒ retry ≤3× @1s backoff; still failing ⇒ log
  "mirror skipped: target unavailable" + **continue** (non-blocking; FR-015). Cycle
  exit code reflects only the cycle.

## 6. Layer 3b — SMTP (FR-016..018, Q3) — P3, opt-in

- Settings: `reports.smtp.{enabled:bool, recipient, server, port, from}` (all
  optional; `enabled:false`/absent ⇒ silent noop, US4.3).
- **Credentials (Q3): env-var first** — e.g. `RF_SMTP_PASSWORD` (+ `RF_SMTP_USER`);
  documented. (Keychain/`pass` are deferred per-OS niceties, not v1.)
- On cycle end (when enabled + creds present): send one email, PDF attached (if
  rendered), body = a **5-line summary** (notes added, cost actual/budget, top
  flagged issue) extracted from the report (FR-018).
- Any failure (unreachable, bad creds) ⇒ log + **continue** (non-blocking; FR-017).
- Single recipient v1. No encryption. (Out-of-scope.)

## 7. Layer independence & determinism (FR-005, FR-015/017; SC-006)

- Each layer ships + fails independently: Layer 1 (always) → Layer 2 (if fpdf2) →
  Layer 3 mirror (if target) → Layer 3b SMTP (if enabled). A failure in any
  delivery layer NEVER fails the cycle (SC-006).
- Layer 1 is fully deterministic (reuses 035's deterministic builders + 022
  calculators). No LLM dispatch anywhere in 040 (Principle IV).

## 8. Out of scope (this contract)
Real-time push (Slack/webhooks → 036 v2); encryption/PGP; multi-recipient;
interactive HTML dashboards (→ 043); cross-vault aggregation; LaTeX/headless-browser
PDF.
