# Feature Specification: Rich Vault Reports + Delivery

**Feature Branch**: `040-vault-reports-delivery`
**Created**: 2026-05-27 (promoted from `docs/ROADMAP.md` Horizon 2 "Rich vault reports + delivery" during post-Wave-1 doc restructure).
**Status**: shipped(2026-06-04, PR #118) — SHIPPED 1.0.0rc1 (PR #118, 2026-06-04) — 3 fail-closed layers: richer `audit-report.md` (reuses 035 builders), opt-in `[reports]`/fpdf2 PDF, cloud-folder mirror + SMTP.

**Input**: Three-layer enrichment of the post-cycle reporting surface so unattended cycle output becomes something a human actually reads: (1) richer markdown content in `_pipeline/audit-report.md` + per-cycle reports (coverage delta, top-discovered sources, cost summary, flagged issues); (2) PDF rendering — opt-in via `pip install research-framework[reports]` *(this Input proposed `weasyprint`; **superseded at Q2 → `fpdf2`**, genuinely pure-Python — see Clarifications)*; (3) delivery channels — cloud-folder mirror first (zero secrets), then SMTP email (deferred until secrets path decided). Each layer ships independently — opt into PDF without email, or email without PDF.

## Clarifications

### Session 2026-06-03 (Q1-Q6 locked)

Q1-Q4 are the spec's original open questions; **Q5-Q6 were surfaced by a
2026-06-03 code audit** (overlap with the just-specified 035 digest; the
`sources.db` quality-score gap).

- **Q1 (FR-008) — Re-render cadence.** **Every cycle.** Audit reports are cheap;
  the prior render is retained in git history (spec 050). `./vault audit` may
  force an on-demand re-render.
- **Q2 (FR-009/011) — PDF approach.** **fpdf2** (pure-Python, no system libs)
  under a new `[reports]` extra — NOT weasyprint. Trades full HTML/CSS fidelity
  for zero install friction; **consistent with the established `[budget]`/tiktoken
  optional-extra precedent** (Principle V allows opt-in extras, forbids new
  *required* deps). Import-fail ⇒ graceful skip (FR-011).
- **Q3 (FR-016) — SMTP credentials.** **Env-var first** (universal, no new dep;
  mirrors spec 033's `RF_*_ACK` pattern), system-keychain second, `pass` third.
- **Q4 (FR-014) — Mirror scope.** **Yes** — the mirror includes `audit-report`,
  per-cycle reports, AND `_pipeline/digests/*` (spec 035 output).
- **Q5 (FR-001/003/006/007, audit) — Layer-1 ↔ 035 overlap.** **Reuse 035's
  `pipeline/digest/sections.py` builders + spec 022 metric calculators.** 040
  Layer 1 = wire those into `audit-report.md` + per-cycle reports and add the two
  NEW sections (Flagged Issues, Top Discovered Sources). **This makes spec 035 a
  HARD dependency** (one section engine, no duplication).
- **Q6 (FR-002, audit) — "Top Discovered Sources" ranking.** Rank by **real
  `sources.db` signals** (`notes_generated`/`notes_referencing` yield + recency)
  — same resolution as 035 Q4; no non-existent quality-score column. (055
  credibility is a future optional enrichment.)

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Cycle report includes coverage delta + top sources + cost (Priority: P1)

The operator finishes an unattended overnight cycle. In the morning, opens `_pipeline/audit-report.md` and sees:
- Coverage delta: which `coverage_targets` advanced (47% → 53%), which stagnated, which regressed.
- Top-discovered sources: 5 newly-discovered sources ranked by real `sources.db` yield + recency, with summaries.
- Cost summary: actual vs budgeted spend ($1.23 / $1.50 cap, 82% utilization), per-stage breakdown.
- Source quality drift: which sources are gaining/losing yield, which degraded this range (reused from spec 035 §7).
- Flagged issues: 2 source preflight warnings, 1 verifier rejection not auto-recovered.

**Why this priority**: Without this content depth, the report is a blank surface. The operator has to manually open the vault to know whether the cycle did anything useful. Layer 1 is the foundation — layers 2 and 3 are the delivery polish on top of it.

**Independent Test**: Run a cycle on a fixture with known coverage targets + source discoveries + cost telemetry. Verify: `audit-report.md` contains all 5 content sections, each with the expected content; sections render correctly even when sub-data is empty (e.g. "no flagged issues this cycle").

**Acceptance Scenarios**:

1. **Given** a cycle that advanced 2 coverage targets and regressed 1, **When** the operator opens `audit-report.md`, **Then** the Coverage Delta section shows all 3 with their delta + last-cycle-touched.
2. **Given** a cycle discovered 7 new sources, **When** the report renders, **Then** Top Sources lists the 5 highest by real `sources.db` yield + recency with rationale.
3. **Given** a cycle's cost is $1.23 of a $1.50 budget, **When** the report renders, **Then** Cost Summary shows "actual / budgeted", per-stage breakdown, and warns if any tier exceeded its threshold (per spec 033 FR-007).

---

### User Story 2 — PDF rendering via opt-in `[reports]` extra (Priority: P2)

The operator runs `pip install research-framework[reports]` once. After cycles complete, both `audit-report.md` AND `audit-report.pdf` exist; the PDF is hyperlink-preserved, has consistent visual style, and is suitable for printing or attaching to email.

**Why this priority**: PDF is a "look at" surface — the markdown is the "work with" surface. Both are valuable; markdown remains canonical (per Out-of-Scope: PDF doesn't replace markdown). P2 because the markdown enrichment from US1 must land first.

**Independent Test**: Install with the `[reports]` extra in a fresh venv. Run a cycle. Verify: both `.md` and `.pdf` files are produced; the PDF renders without errors; opening it shows the same content as the markdown.

**Acceptance Scenarios**:

1. **Given** `pip install research-framework[reports]` has been run, **When** the cycle completes, **Then** `audit-report.pdf` is produced alongside `audit-report.md`.
2. **Given** the base install (no `[reports]` extra), **When** the cycle completes, **Then** only `audit-report.md` is produced; no error fires, no spurious warning.
3. **Given** `[reports]` extra is installed but `fpdf2` fails to import (broken install), **When** PDF rendering is attempted, **Then** a clear error fires: `fpdf2 unavailable; install with pip install research-framework[reports]`; cycle does NOT fail — the markdown is still produced.

---

### User Story 3 — Cloud folder mirror delivers reports without secrets (Priority: P2)

The operator sets `settings.yaml::reports.mirror.target: /Users/me/iCloud Drive/feeds-vault-mirror`. At cycle end, both `.md` and `.pdf` (if enabled) are copied to that path. The cloud provider's desktop client (iCloud, Dropbox, Google Drive Desktop) syncs the path. The operator reads the report on iPad / phone / second laptop without setting up a server.

**Why this priority**: This delivery channel has ZERO secrets to manage and ZERO server infra. It's the cheapest way to get reports off the local machine. Ships before SMTP (US4) because SMTP requires solving the secrets-management question.

**Independent Test**: Set `mirror.target: /tmp/test-mirror`. Run a cycle. Verify: `/tmp/test-mirror/audit-report.md` exists after cycle end with the expected content; no read-back from the mirror affects the source vault.

**Acceptance Scenarios**:

1. **Given** `settings.yaml::reports.mirror.target` is set, **When** a cycle completes, **Then** both `.md` and `.pdf` (if PDF enabled) are copied to that path.
2. **Given** the mirror target is unreachable (e.g. mount point unavailable), **When** the cycle completes, **Then** the cycle exits successfully + logs a "mirror skipped: target unavailable" warning (non-blocking).
3. **Given** `mirror.target` is unset, **When** a cycle completes, **Then** no mirror attempt is made (silent noop, no warning).
4. **Given** the mirror includes `_pipeline/digests/` per Q4, **When** a digest is generated, **Then** it lands in the mirror on the next cycle (or immediately if `--mirror-now` flag is added).

---

### User Story 4 — SMTP email delivers PDF attachment (Priority: P3)

The operator configures SMTP credentials (per Q3's clarification). At cycle end, an email is sent with the PDF attached and a 5-line summary in the body. Failures (SMTP unreachable, credentials wrong) log a warning but don't fail the cycle.

**Why this priority**: P3 because SMTP secrets management is non-trivial. Mirror (US3) is the cheaper alternative for most users. SMTP is for operators who want push (not pull) delivery.

**Acceptance Scenarios**:

1. **Given** `settings.yaml::reports.smtp.enabled: true` + valid credentials, **When** a cycle completes, **Then** an email is sent with PDF attached + summary in body.
2. **Given** SMTP credentials are invalid, **When** the cycle completes, **Then** SMTP failure is logged + the cycle exits successfully (non-blocking).
3. **Given** SMTP is unconfigured (`reports.smtp.enabled: false` or absent), **When** the cycle completes, **Then** no SMTP attempt is made (silent noop).

---

### Edge Cases

- What if the markdown report references images / assets that PDF rendering needs? → fpdf2 has no automatic asset resolution; the report template emits text + tables + links only (no embedded images in v1). Document the convention.
- What if a Cloud-sync folder is mid-sync (file locked) when the mirror writes? → Retry up to 3 times with 1s backoff; if still locked, log warning + skip this cycle's mirror.
- What if system fonts are missing? → fpdf2 ships bundled core fonts (FR-012); rendering never depends on system fonts, so it can't crash on font availability.
- What if the operator changes `mirror.target` mid-vault-life? → Old target gets stale (no cleanup); new target starts fresh. Document but don't try to clean up the old target.
- What if both `mirror.target` AND `smtp.enabled: true` are set? → Both fire independently; failures don't cross-affect.
- What if a cycle is interrupted (Ctrl-C) mid-report-render? → No PDF; markdown may be partial; mirror/email skipped. Next cycle re-renders cleanly.

## Requirements *(mandatory)*

### Functional Requirements

#### Layer 1 — Markdown content enrichment

- **FR-001** *(Q5 — reuse)*: `_pipeline/audit-report.md` MUST include a "Coverage
  Delta" section **rendered by reusing spec 035's Coverage Delta section builder**
  (`pipeline/digest/sections.py`), scoped to the report's range. No reimplementation.
- **FR-002** *(Q6 — ranking reconciled)*: The report MUST include a "Top Discovered
  Sources" section listing the 5 newly-discovered sources in scope (or fewer if <5)
  ranked by **real `sources.db` signals** — `notes_generated`/`notes_referencing`
  yield + recency (NOT a non-existent "projected quality score"). Each entry has
  source identifier + 1-line summary + the ranking signal. (Reuses 035's Source
  Quality Drift data layer; 055 credibility is a future optional enrichment.)
- **FR-003** *(Q5 — reuse)*: The report MUST include a "Cost Summary" section
  **reusing spec 035's Cost Summary builder** (over spec 028 `agent-calls/`
  sidecars): actual cumulative spend, budgeted cap (spec 033), % utilization,
  per-stage breakdown, per-tier breakdown.
- **FR-003b** *(Q5 — reuse)*: The report MUST include a "Source Quality Drift"
  section **reusing spec 035's source-signal builder** (`pipeline/digest/sections.py`,
  035 §7 — `notes_generated`/`notes_referencing` deltas, `degraded` transitions,
  `consecutive_empty_cycles`), scoped to the range. This is the third
  reused-from-035 section (with Coverage Delta + Cost Summary); together with the
  two NEW sections (Top Discovered Sources, Flagged Issues) the report carries
  **5 content sections**.
- **FR-004**: The report MUST include a NEW "Flagged Issues" section (not in 035):
  source preflight failures, verifier rejections not auto-recovered, schema drift
  detections, retry exhaustion records. Each issue has stage + identifier +
  severity + suggested next step.
- **FR-005**: Layer 1 sections MUST render explicit "No data in scope" lines when
  their underlying data is empty, NEVER omitting the section silently.
- **FR-006** *(Q5 — reuse)*: Layer 1 MUST reuse spec 022's metric calculators AND
  spec 035's section builders wherever applicable — **no third implementation** of
  coverage/cost/source-signal rendering across harness + digest + reports.
- **FR-007**: The deterministic Layer-1 sections MUST also be available for the
  per-cycle surface scoped to a single cycle. Because `cycle-<N>-report.md` is the
  `cycle-report` LLM-skill artifact (narrative, not template-rendered), Layer 1
  renders a **deterministic per-cycle section block** that the cycle-report skill
  MAY include (or that is appended), rather than overwriting the skill's prose.
- **FR-008**: Per Q1's default, `audit-report.md` re-renders on EVERY cycle. The previous render is overwritten — git history retains the prior version.

#### Layer 2 — PDF rendering

- **FR-009** *(Q2 — fpdf2)*: A new `[reports]` extras group MUST be added to
  `pyproject.toml`: `pip install research-framework[reports]` installs **`fpdf2`**
  (pure-Python; **no system libraries** — unlike weasyprint). This follows the
  established `[budget]`/tiktoken optional-extra precedent (Principle V: opt-in
  extras are permitted; new *required* deps are not).
- **FR-010** *(Q2 — fpdf2)*: When `fpdf2` is importable, every Layer-1 markdown
  report MUST also render to PDF (`.pdf` beside the `.md`) via a small
  **deterministic markdown→PDF renderer** over fpdf2 covering the report element
  set (headings, paragraphs, tables, lists, links, code). Markdown stays canonical
  (Out-of-scope: PDF doesn't replace it). Lower CSS fidelity than weasyprint is the
  accepted Q2 trade-off.
- **FR-011** *(Q2 — fpdf2)*: When `fpdf2` is NOT importable (base install), PDF
  render MUST be silently skipped — NO error — unless the operator explicitly
  requests `--format pdf`, which then errors with "install with `pip install
  research-framework[reports]`". The markdown is always produced regardless.
- **FR-012** *(Q2 — fpdf2)*: PDF rendering MUST use fpdf2's bundled core fonts (no
  system-font dependency), so font availability can never crash the render.

#### Layer 3 — Delivery channels

- **FR-013**: A new `reports.mirror.target` setting (in `settings.yaml`) MAY be set to a filesystem path. At cycle end, the framework MUST copy all reports (md + pdf if enabled) to that path.
- **FR-014**: Per Q4's default, the mirror MUST also include `_pipeline/digests/*.md` (and `.pdf` if rendered) from spec 035.
- **FR-015**: Mirror failures MUST be logged but MUST NOT fail the cycle. The cycle exit code reflects only the cycle's own success.
- **FR-016**: A new `reports.smtp.enabled: bool` setting + `reports.smtp.recipient: <email>` setting MAY enable SMTP delivery. Credentials path follows Q3's clarification (default: env-var first, system-keychain second, `pass` third).
- **FR-017**: SMTP failures MUST be logged but MUST NOT fail the cycle.
- **FR-018**: SMTP body MUST contain a 5-line summary of the cycle (notes added, cost, top issue) extracted from the report.
- **FR-019**: Layer 3 settings MUST be optional / unset by default. Base configuration ships with no mirror + no SMTP — zero delivery friction.

### Key Entities

- **`audit-report.md` + `audit-report.pdf`**: The post-cycle artifact. Markdown is canonical; PDF is rendered via fpdf2 when the `[reports]` extra is installed.
- **Reused 035 section builders** *(Q5)*: `pipeline/digest/sections.py` (Coverage Delta, Cost Summary, source-signal data layer) + spec 022 metric calculators. 040 wires them into the report surface and adds Flagged Issues + Top Discovered Sources. No duplicate section code.
- **Jinja2 report template**: Lives at `src/research_framework/templates/audit-report.md.j2`. Renders the **markdown**; the PDF is produced by a separate deterministic markdown→PDF pass over fpdf2 (FR-010) — markdown is the single content source-of-truth.
- **`[reports]` extras group**: `pyproject.toml` `[project.optional-dependencies]` entry. Adds **`fpdf2`** (pure-Python, no system libs). Mirrors the existing `[budget]` extra.
- **`reports.mirror.target` setting**: Optional filesystem path. Determines where reports are mirrored.
- **`reports.smtp.*` settings**: Optional SMTP delivery config — `enabled`, `recipient`, `server`, `port`, `from`. Credentials per Q3.
- **Mirror copy operation**: A simple `cp` (or `shutil.copy2`) at cycle end. NOT rsync — single file copy; no delete semantics (mirror accumulates).
- **SMTP delivery worker**: A non-blocking POST-cycle worker that constructs the email + attaches PDF + sends. Failures are logged + swallowed.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After Layer 1 lands, `audit-report.md` includes all 5 content sections on every cycle of the feeds-vault fixture (100% rendering).
- **SC-002**: `pip install research-framework[reports]` adds <10MB and **zero system-library requirements** to the install footprint (fpdf2 is pure-Python; far smaller than weasyprint's Pango/cairo stack).
- **SC-003**: PDF rendering for a typical cycle report (~50 notes, 5 sections) completes in <10 seconds on commodity hardware.
- **SC-004**: When `mirror.target` is set, 100% of cycle reports land in the mirror within 5 seconds of cycle end.
- **SC-005**: SMTP delivery, when configured, sends the email within 30 seconds of cycle end (or fails gracefully without affecting the cycle).
- **SC-006**: 0 cycles fail because of report/mirror/SMTP errors (all delivery failures are logged + non-blocking).

## Assumptions

- **Spec 035 (cross-cycle digest) is shipped — HARD (Q5)**: 040 Layer 1 imports
  035's `pipeline/digest/sections.py` builders. 040 cannot ship before 035.
- Spec 022 (E2E quality harness v1) is shipped — metric calculators in FR-006 exist.
- Spec 033 (cost enforcement) is shipped — cost-summary section in FR-003 has honest cost data.
- Operators with cloud-sync workflows (iCloud, Dropbox, Google Drive Desktop) are the primary Layer-3 audience. Power users with SMTP setups are a smaller secondary audience.
- `fpdf2` (pure-Python, no system libs) is a viable PDF backend for the report's
  element set; full HTML/CSS fidelity is explicitly traded away (Q2).

## Dependencies

- **Hard — Spec 035 (cross-cycle digest)** *(elevated soft→hard by Q5)*: Layer 1
  reuses 035's `pipeline/digest/sections.py` builders. 040 sequences AFTER 035.
- **Hard — Spec 022 (E2E quality harness v1)**: metric calculators (reused via 035).
- **Hard — Spec 033 (cost enforcement)** + **Spec 028 (telemetry sidecars)**: the
  cost-summary's actual-vs-budget + per-stage breakdown. Both shipped.
- **Soft — Spec 055 (credibility)**: a future optional enrichment of Top Sources
  ranking (Q6 chose sources.db signals for v1).
- **Soft — Spec 039 (installer hardening)**: `install.sh` should advise that the
  `[reports]` extra exists (pip-managed).

## Acceptance coverage

Draft — evidence cells will be populated by `/speckit.tasks` for
this spec. Listed for the ADR-0008 guard so the spec is accepted
into the queue (the guard refuses any G/W/T-bearing spec without
this section).

| User Story | Evidence |
|------------|----------|
| US1 — Cycle report includes coverage delta + top sources + cost | `tests/pipeline/reports/test_layer1_reuse.py::test_compose_report_calls_035_builders` + `tests/pipeline/reports/test_audit_report_e2e.py::test_audit_report_e2e_all_sections` |
| US2 — PDF rendering via opt-in `[reports]` extra | `tests/pipeline/reports/test_reports_extra.py::test_reports_extra_lists_fpdf2_beside_budget` + `tests/pipeline/reports/test_pdf_import_guard.py` |
| US3 — Cloud folder mirror delivers reports without secrets | `tests/pipeline/reports/test_mirror_copy.py::test_mirror_copy_all_expected_files` |
| US4 — SMTP email delivers PDF attachment | `tests/pipeline/reports/test_smtp_send.py::test_smtp_send_one_message` |

## Out of Scope

- Replacing markdown as source-of-truth format. PDF is rendered; markdown is canonical.
- Interactive dashboards / live HTML reports. Obsidian Canvas covers that (spec 043).
- Real-time push notifications (Slack, Discord, webhooks). Out of v1; consider after file-based push to assistant-framework lands (spec 036 v2).
- LaTeX or headless-browser PDF rendering. We use **fpdf2** (pure-Python, no
  system libs) — full HTML/CSS-fidelity rendering (weasyprint) was considered and
  declined at Q2 in favour of zero install friction.
- Multi-recipient SMTP. Single recipient in v1; multi-recipient via mailing-list infra at the recipient's end.
- Encryption (PGP-signed reports, encrypted email body). Out of v1; layer-3-encrypted is a separate spec if requested.
- Cross-vault aggregated reports (one report covering multiple vaults). Per-vault only in v1.

---

*IMPLEMENT-READY (2026-06-03): Q1-Q6 locked; plan + research + contract + tasks +
analyze complete (siblings in this dir). Wave 3 / rc1. **Hard dep on spec 035**
(Layer 1 reuses 035's section builders — Q5) — sequence 040 AFTER 035. The three
layers ship independently (Layer 1 → Layer 2 PDF → Layer 3 mirror → Layer 3b SMTP).*
