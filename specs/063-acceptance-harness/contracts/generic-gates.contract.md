# Contract: §4.1 framework-generic acceptance gate set

**Spec**: [../spec.md](../spec.md) (US1 / FR-001) | **Date**: 2026-06-05
**Surface**: `./vault acceptance` (`cli/acceptance.py::_cmd_acceptance`)

Deterministic, **LLM-call-free** gates that run on any generated vault over artifacts
the framework already emits. Severity per clarify Q2: **FAIL** = non-zero exit (run/
build may gate on it); **WARN** = advisory (recorded, never blocks unless `--strict`).

## Gate inputs (all read-only)

- Run report: `_pipeline/run-report.md` + `_pipeline/run-report.json` (incl. spec-061
  `cycle_budget` provenance).
- Notes: `data_vault/**/*.md` frontmatter (`verifier_status`, `template_version`,
  `source_urls`, `role`/`priority`, `credibility`/`coi`).
- Git: `git -C <vault> status --porcelain` + `git log` (per-cycle commit topology).
- Ledger: `cycle-NNN-source-ledger.json` via `scripts/source_ledger.py`.
- Cost: per-call sidecars under `_pipeline/cycles/cycle-NNN/agent-calls/` (incl.
  spec-028-amendment codex `cost_usd`/tokens) + run-report `total_cost_usd`.
- Quarantine: `_pipeline/quarantine/` (spec-062 FR1 destination).

## The six gates

| # | Gate id | Checks | Severity | Pass when |
| --- | --- | --- | --- | --- |
| 1 | `GA-001` rejected-notes-in-corpus | no `data_vault/` note has `verifier_status: rejected` (they belong in `_pipeline/quarantine/`) | **FAIL** | zero rejected notes in the indexed corpus (catch 3.2; spec 062 FR1) |
| 2 | `GA-002` duplicate-notes | no OS-style ` N.md` siblings; no byte-identical content duplicates | **FAIL** | zero duplicates (catch 3.3; shares spec 062 FR2 detector) |
| 3 | `GA-003` git-integrity | zero untracked under `data_vault/`; exactly one `research: cycle N` commit per cycle; research branch squash-merged on clean exit | **FAIL** | git state clean per spec 050 / Principle X (catch 3.3) |
| 4 | `GA-004` run-completion | parse `cycle_budget`: a constrained exit (`exit_status != "complete"`) MUST NOT read as done; surface configured-vs-actual cycles + per-category % of target | **FAIL** | a constrained exit is reported as constrained, not done (catch 3.1 symptom; spec 061 FR4) |
| 5 | `GA-005` cost-telemetry | `total_cost_usd > 0`, tokens recorded, within budget | **FAIL** | non-zero cost + tokens present (catch 3.5; consumes spec 028 amendment; FAILs loud on `$0` even without it) |
| 6 | `GA-006` template-drift | every note's `template_version` matches the shipped templates | **WARN** | versions match (advisory) |

## Verdict + exit code

- Each gate yields `{gate_id, status: PASS|FAIL|WARN, metric, threshold, message,
  evidence_paths[]}`.
- Process exit: `0` if no FAIL gates; `1` if any FAIL gate; WARN never sets non-zero
  unless `--strict` is passed.
- All gate results are written to the scorecard (FR-006,
  `contracts/acceptance-scorecard.schema.json`).

## Edge cases (spec §Edge Cases — gates MUST handle)

- **Zero-cycle clean exit** (nothing to research) — `GA-004` distinguishes "nothing to
  do" (`configured≥actual==0`, complete) from "truncated" (constrained). Not a FAIL.
- **Journal-first vault** (no code sources) — gates are domain-agnostic; authority
  grading (US3, separate) uses the vault's *derived* trunk, never an assumed code trunk.
- **Unparseable cost** (pre-028-amendment codex) — `GA-005` FAILs loud on `$0`; it
  MUST NOT silently pass (the whole point of catch 3.5).

## Determinism guarantee

No gate dispatches an LLM (the tier-2 LLM-dispatch guard stays green). Same vault
state ⇒ same verdicts. Gates only *read*; they never mutate the vault (the scorecard
is the only write, and it lives under `_pipeline/acceptance/`).
