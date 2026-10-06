# Implementation Plan: Rich Vault Reports + Delivery (Spec 040)

**Branch**: `040-vault-reports-delivery` · **Date**: 2026-06-03
**Spec**: [spec.md](./spec.md) · **Contract**: [contracts/report-delivery.contract.md](./contracts/report-delivery.contract.md) · **Research**: [research.md](./research.md)
**Status**: planned (post-clarify Q1-Q6). Wave 3 / rc1. **Sequenced after spec 035.**

## Summary

Three independently-shippable layers on the post-cycle reporting surface:
- **Layer 1 (markdown)** — enrich `audit-report.md` (+ a per-cycle deterministic
  block) by **reusing spec 035's `pipeline/digest/sections.py` builders** (Coverage
  Delta, Cost Summary, source-signal layer) and adding two NEW sections (Flagged
  Issues; Top Discovered Sources ranked by real `sources.db` yield+recency).
- **Layer 2 (PDF)** — opt-in `[reports]` extra installing **fpdf2** (pure-Python);
  a deterministic markdown→PDF pass; graceful skip when not installed.
- **Layer 3 (delivery)** — `reports.mirror.target` file copy (incl. digests, Q4);
  then opt-in `reports.smtp.*` (env-var creds, Q3). All delivery failures logged +
  non-blocking.

## Technical Context

- **Language**: Python 3.11+. **Required deps**: jinja2 + pyyaml + stdlib
  (`smtplib`, `email`, `shutil`) — unchanged. **Optional dep**: `fpdf2` via the new
  `[reports]` extra (Principle V: opt-in only — the `[budget]`/tiktoken precedent).
- **New code**:
  - `pipeline/reports/` — `layer1.py` (compose the report by calling 035's
    section builders + the 2 new sections), `pdf.py` (md→fpdf2 renderer, import-
    guarded), `mirror.py` (copy incl. digests), `smtp.py` (env-var creds, non-
    blocking send).
  - `templates/audit-report.md.j2` — the markdown template (markdown is canonical).
  - settings keys: `reports.mirror.target`, `reports.smtp.{enabled,recipient,server,port,from}`
    in `pipeline/settings.py` (canonical loader, spec 025 B7); all optional/unset.
  - cycle-end hook in `cycle_runner.py` / the reporter path to render + deliver.
  - `pyproject.toml` `[project.optional-dependencies] reports = ["fpdf2>=2.7"]`.
- **Reused (do NOT reimplement)**: `pipeline/digest/sections.py` (spec 035), spec
  022 metric calculators, spec 028 sidecar reader, spec 033 budget data.
- **Testing**: deterministic Layer-1 section tests (via 035 builders); fpdf2 render
  test gated on import (+ a base-install skip test); mirror/SMTP tests with
  `tmp_path` + a fake SMTP (`smtpd`/monkeypatch). `tmp_path`-isolated (spec 026).

## Constitution Check

| Principle | Status | Note |
|-----------|--------|------|
| V — no new *required* runtime dependency | ✅ PASS | fpdf2 is opt-in under `[reports]`, exactly like `[budget]`/tiktoken. Base install unchanged. |
| IV — deterministic / no LLM | ✅ PASS | Layer 1 reuses 035's deterministic builders; PDF/mirror/SMTP are mechanical. No agent dispatch. |
| X — vault history append-only git | ✅ PASS | Reports under `_pipeline/`; mirror copies OUTSIDE the vault; no vault-history mutation. |
| VIII — fixtures are test data | ✅ PASS | |
| DRY (audit) | ✅ ENFORCED | Q5 reuse — no third copy of coverage/cost rendering. |
| TDD | ✅ PLANNED | section + render + delivery tests first. |

No violations. The only dependency change is an opt-in extra with a shipped
precedent — no Complexity-Tracking entry needed.

## Project Structure (artifacts this spec produces)

```
specs/040-vault-reports-delivery/
├── spec.md                                # IMPLEMENT-READY
├── plan.md                                # this file
├── research.md                            # D1–D7 + audit table
├── contracts/report-delivery.contract.md  # layout + reuse map + PDF/mirror/SMTP contracts
├── checklists/requirements.md
└── tasks.md
```

## Phase 0 — Research ✅  ·  Phase 1 — Design ✅
[research.md](./research.md) (audit table + D1–D7) and
[contracts/report-delivery.contract.md](./contracts/report-delivery.contract.md)
(the section reuse map, the markdown→PDF element mapping, the mirror copy + SMTP
contracts, and the layer-independence/failure rules).

## Phase 2 — Task strategy (for `/speckit.tasks`)
- **TDD order**: Layer 1 (reuse-wiring + 2 new sections + tests) → Layer 2 (pyproject
  extra + md→PDF renderer + import-guard tests) → Layer 3 mirror (copy + failure
  tests) → Layer 3b SMTP (env-var creds + non-blocking + fake-SMTP tests) →
  end-to-end + docs.
- **Reuse-first**: the first Layer-1 task imports 035's builders; if 035 isn't
  merged yet, the task is BLOCKED (sequencing). Flagged in tasks.md.
- **Fixture**: extend the 035 digest fixture (it already has cycles/coverage/cost/
  sources) — engineer a flagged-issue (a verifier rejection + a preflight fail) and
  a couple newly-discovered sources. `tmp_path`-isolated.

## Complexity & Risks
- **035 not-yet-merged** — Layer 1 hard-depends on `pipeline/digest/sections.py`.
  *Mitigation*: sequencing gate in tasks.md; Layers 2/3 (PDF/mirror/SMTP) can be
  built against a stub report in parallel.
- **fpdf2 markdown fidelity** — fpdf2 is low-level (no CSS); the md→PDF renderer
  must handle the report's element set explicitly. *Mitigation*: scope the renderer
  to exactly the elements the template emits (headings/para/table/list/link/code);
  golden-PDF byte tests are brittle, so assert structural facts (page count > 0,
  text extractable, section headings present) not byte-identity.
- **SMTP test hermeticity** — never hit a real server. *Mitigation*: a local
  `aiosmtpd`/`smtpd` capture or monkeypatched `smtplib.SMTP`; the LLM-dispatch-guard
  ethos (no real network in tests).
- **Scope creep** — Slack/webhooks, encryption, multi-recipient, dashboards are all
  explicit Out-of-scope (→ 036 v2 / 043 / separate specs).
