# Research & Decisions: Cross-Cycle Digest (Spec 035)

**Date**: 2026-06-03 · **Stage**: post-clarify (Q1-Q5), pre-plan
**Context**: 035 was drafted 2026-05-27. A 2026-06-03 audit reconciled it against
artifacts that shipped since (050 append-only git; 028 telemetry; 051
inbound-link index; 030/055 source signals in-flight).

## Audit findings (spec ↔ code reconciliation)

| spec claim | reality (2026-06-03) | resolution |
|------------|----------------------|------------|
| `./vault digest` verb | **absent** — no `digest` in `cli/` | net-new (FR-001); clean |
| FR-009 cost data | spec 028 sidecars `cycle-NNN/agent-calls/*.json` **shipped (0.4.0)** | read them directly |
| `cycle-<N>-report.md` "primary input from 022" | produced by the **`cycle-report` LLM skill**, not 022; may be absent | demote to soft input; FR-015 covers absence |
| FR-006 "source quality score >10%" | `sources.db` has **no quality-score column** — only `source_cycles.notes_generated/notes_referencing`, `consecutive_empty_cycles`, degraded incidents, `source_quality_summary()` aggregate | **Q4**: derive drift from those real signals |
| FR-010/011 "per-cycle ship commit SHA from git log" | spec 050 **squash-merges per-cycle commits into one run commit on main** (`_squash_merge`); per-cycle SHAs transient on `research/<ts>` | **Q5**: filesystem authoritative; ship SHA = run squash |
| FR-008 "from `_pipeline/coverage-targets.json`" | targets live at **`<vault>/coverage-targets.json`** (vault root; `quality/runner.py` reads `vault_dir/"coverage-targets.json"`) | fix path; progress from `cycle-NNN-quality-report.json` |
| FR-004 "exactly 7 sections" then lists 8 | Header was miscounted as a section | Header + **7 content sections** |
| ranker "citation count" | `vault/indexer.inbound_link_counts()` **exists (spec 051 FR3)** | use it directly |

**Net**: the digest's *shape* (4 stories, 7 sections, deterministic, LLM-free) was
sound; its *data plumbing* was written against a pre-050/pre-030 world and is now
corrected. No story was dropped.

## Decisions

### D1 — `--since` primitive + `--last-*` sugar (Q1)
One range source; convenience flags desugar to a date. Avoids two code paths.

### D2 — Integer composite ranker, path tiebreaker (Q2)
`inbound_links + source_drift_bonus + freshness_points`, all integers; top-5 by
score desc, **note-path asc** tiebreaker. **Why integer**: float weights are a
bikeshed + a determinism hazard; integer points give a defensible, reproducible
order. 055 credibility deliberately **excluded** from v1 (keeps 035 un-gated on a
Wave-2 spec). **Alternatives rejected**: float-weighted composite (non-reproducible
bikeshed); citations-only (loses the freshness/yield nuance the user values).

### D3 — No auto-run; documented cron (Q3)
Explicit `./vault digest` only. **Why**: avoids coupling the digest into the
cycle lifecycle (and into spec 050's commit dance); a cron/launchd one-liner
covers the scheduling want without new surface. **Rejected**: cycle-end hook
(couples digest failure into the research run); built-in scheduler (daemon scope
creep).

### D4 — Source Quality Drift from real sources.db signals (Q4)
notes_generated/referencing deltas + degraded transitions + consecutive_empty
crossings. **Why**: it's what actually exists and ships today; honest signal
without inventing a score. **030's `source_quality` metrics** are a clean future
enrichment but are unmerged Wave-1 — gating FR-006 on them would block a Wave-3
spec on a Wave-1/2 one. **Rejected**: gate-on-030 (cross-wave block);
defer-to-v2 (loses a section the legacy report had).

### D5 — Filesystem-authoritative cycle model (Q5)
Enumerate cycles from `cycle-NNN/` + quality-report marker; git only for run
range/dates; ship SHA = run squash commit. **Why**: 050 squashes per-cycle
commits, so the filesystem (not `git log`) is the durable, deterministic per-cycle
record. **Rejected**: parse-squash-body (fragile string parsing of a commit
message); require-unsquashed-vaults (excludes the default 050 config).

### D6 — Module placement
A new `scripts/vault_digest.py` (vault-local, like other `scripts/`) OR a
`cli/digest.py` subcommand calling a `pipeline/digest/` package. *Plan picks*:
`pipeline/digest/` (renderer + section builders + ranker) imported by a thin
`cli` verb — testable units, one Jinja2 template. No new dependency (Jinja2 +
stdlib + sqlite3, all present).

## Cross-spec interactions
- **050 (hard)** — commit topology defines FR-010/011. Shipped.
- **028 (hard)** — cost sidecars. Shipped.
- **051 (helper)** — `inbound_link_counts`. Shipped.
- **022 (helper)** — `cycle-NNN-quality-report.json` for coverage progress. Shipped.
- **030 / 055 (optional future enrichment)** — richer drift / credibility-weighted
  signals; explicitly NOT v1 gates.
- **040 (downstream)** — digest output is a candidate artifact for 040 delivery.
- **026 (test isolation)** — digest fixtures use `tmp_path` (no git-status pollution).

## Determinism / Principle check
LLM-call-free (SC-004); integer scoring with total-order tiebreakers; local-only
inputs; one Jinja2 render. No new runtime dep (Principle V). ✅
