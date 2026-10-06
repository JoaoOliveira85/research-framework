# Specification Quality Checklist: Cross-Cycle Digest

**Purpose**: Validate specification completeness/quality before implementation
**Created**: 2026-06-03 · **Feature**: [spec.md](../spec.md)
**State**: post-clarify (Q1-Q5) + plan + research + contract + tasks + analyze.
**IMPLEMENT-READY** — no external sequencing gate (all hard deps shipped on main).

## Content Quality
- [x] No implementation details in the requirements (the *what*; formulas live in `contracts/`)
- [x] Focused on operator value (sub-5-minute weekly briefing; engagement)
- [x] 4 user stories with independent tests + acceptance scenarios
- [x] All mandatory sections present

## Requirement Completeness
- [x] **No `[NEEDS CLARIFICATION]` markers remain** — Q1-Q5 resolved (2026-06-03):
  - Q1 → `--since` primitive + `--last-*` sugar
  - Q2 → deterministic integer composite ranker (no LLM; 055 excluded from v1)
  - Q3 → no auto-run; documented cron
  - Q4 → Source Quality Drift from REAL sources.db signals (not a non-existent score column)
  - Q5 → filesystem-authoritative cycle index; ship SHA = 050 run squash commit
- [x] Requirements testable + unambiguous (every FR → ≥1 task + a contract rule)
- [x] Success criteria measurable (byte-identical repeat; <5s; 0 LLM calls)
- [x] Determinism explicit (integer scoring + total-order tiebreakers; LLM-free)
- [x] Out-of-scope explicit (PDF/email → 040; charts → 043; cross-vault; auto-publish)

## Cross-spec consistency (from /analyze + 2026-06-03 audit)
- [x] **FR-006 reconciled** — drift derives from shipped `source_cycles` /
      `consecutive_empty_cycles` / incidents, NOT an imaginary quality-score column
- [x] **FR-010/011 reconciled to spec 050** — squash topology; filesystem authoritative;
      no per-cycle `git log` assumption
- [x] **FR-008 path fixed** — `<vault>/coverage-targets.json` (root), not `_pipeline/`
- [x] **FR-004 section count fixed** — Header + exactly 7 content sections
- [x] Ranker reuses real `vault/indexer.inbound_link_counts` (spec 051)
- [x] Cost reuses real 028 sidecars; cycle-report is a soft (skill-produced) input
- [x] 030/055 are optional future enrichments, explicitly NOT v1 gates
- [x] Principle IV (LLM-free), V (no new dep: jinja2+stdlib+sqlite3), X (read-only on git)
- [x] New fixtures `tmp_path`-isolated (spec 026)

## Notes
- **HIGH-readiness, no blocker.** Unlike 055 (gated on 053), 035's hard deps
  (028/050/051/022) are all on `main` — implementable immediately in Wave 3.
- The 2026-05-27 draft was structurally sound; the audit corrected its data
  plumbing (it predated 050/030/051). No user story changed.
- `/analyze`: no contradictions among spec ↔ contract ↔ plan ↔ tasks. Acceptance
  table task IDs verified against tasks.md (the earlier `T012` double-reference
  was corrected — LLM-free moved to T021).
- Two implement-time validations flagged in plan Complexity: the exact
  `cycle-NNN-quality-report.json` coverage-progress field, and the
  `inbound_link_counts` key shape — both have graceful-degrade fallbacks.
