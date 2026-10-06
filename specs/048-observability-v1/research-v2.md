# Phase 0 Research: Source-Consideration Ledger (v2 MVP)

**Spec**: `/specs/048-observability-v1/spec.md` § v2 scope + Clarifications 2026-06-03
**Plan**: `plan-v2.md`
**Date**: 2026-06-03

The binding decisions (ledger granularity, failure-uniform silence, routing-derived MCP) were settled in `/speckit.clarify` (Session 2026-06-03). Phase 0's job is narrower: **confirm every join input exists and is addressable read-only**, and pin the handful of design micro-decisions the script's `resolve_verdict` needs. Nothing below requires a pipeline change.

## 1. Join-source audit (verified 2026-06-02 in the spec; re-confirmed against source 2026-06-03)

Each of the four diagnosis causes (a/b/c/d) maps to at least one existing artifact. The script reads them; it writes none of them.

| Cause | Signal | Artifact / source-of-truth | Verified location |
|---|---|---|---|
| (a) genuinely not relevant | per-source `{name, searched: bool, reason}` agent self-report | scout report `sources_consulted` at `cycle-NNN-scout.json` | prompt contract `pipeline/_cycle_helpers.py:437-449`; report written by `pipeline/steps/scout.py` (`cycle-NNN-scout.json`); validated by `validate_sources_v2` |
| contribution (USED) | `notes_generated`, `notes_referencing` (= citations) per (source, cycle) | `_pipeline/sources.db` table `source_cycles` | schema `pipeline/source_manager.py:31-41`; upsert `record_cycle` `:178-234`; citation count `_count_notes_referencing` `:138-176` |
| (b) access / technical failure (required sources) | degradation count + abort threshold | `cycle-NNN-source-incidents.json` + `_pipeline/source-incidents.md` | written by `notify_required_source_degraded` `pipeline/_cycle_helpers.py:706-797`; `:774` writes the per-cycle JSON, `source_manager.mark_degraded` appends the `.md` |
| (b) access / technical failure (web fetch) | grouped `(host, reason)` incl. `JS_SHELL` / `THIN` / 404 | aggregated from capture-failure items | `pipeline/cycle_summary.py:_aggregate_capture_failures` `:89-108`; reasons originate in `scripts/raw_capture.py` payload classification |
| (d) fetched but quality-rejected | per-gate verdict + verifier status | `cycle-NNN-quality-report.json` `gates` | read by `pipeline/cycle_summary.py:_gate_lines` `:111-133` |
| declared set + role/required/priority | the source declaration | `research.spec.md` -> `spec.data_sources` | schema `DataSourceConfig` `spec/schema.py:163-212` (`role`, `required`, `priority`, `type`) |

**Conclusion**: all six inputs are present and read-only-addressable today. The ledger is a *join*, exactly as the spec's "the data is present but fragmented" framing claims. No artifact needs a schema change for the MVP.

## 2. Design micro-decisions

### D1 — `SKIPPED_RELEVANCE` trusts the agent's stated reason (including on required sources)

The scout's `sources_consulted` row is the only per-source "(a) not relevant" signal. A non-empty `reason` yields `SKIPPED_RELEVANCE` for **any** declared source, including `required: true` — a non-failure under FR-019 (exit `0`). The ledger does **not** second-guess whether the reason is legitimate; that is by design for this read-only diagnostic.

**Decision**: when `reason` is a non-empty string and higher-precedence verdicts (`USED`, `QUALITY_REJECT`, `ACCESS_FAIL`) do not apply, `resolve_verdict` assigns `SKIPPED_RELEVANCE` and carries the reason through. Detecting bad-faith trunk-skips (e.g. a required trunk source skipped with a plausible but false reason) is **not** this ledger's job — spec 053's trunk-inversion gate consumes the per-cycle ledger JSON and owns that enforcement. Unexplained silence (`PIPELINE_DROP`, no reason) remains the ledger's loud (c) signal; access and quality failures are handled by their own verdicts.

- *Rejected*: cross-checking required sources against contribution/access signals before honouring a stated `reason`. Rejected for this MVP — it contradicted the clarified SKIPPED_RELEVANCE rule and duplicated spec 053's trunk-inversion scope.

### D2 — Verdict precedence (total order over conflicting per-cycle signals)

A source accumulates signals across cycles (e.g. cycle 1 `ACCESS_FAIL`, cycle 3 `USED`). The spec requires **exactly one verdict per source** in the roll-up. The per-cycle ledger records the per-cycle verdict; the run roll-up collapses them with a documented precedence:

```
USED  >  QUALITY_REJECT  >  ACCESS_FAIL  >  SKIPPED_RELEVANCE  >  PIPELINE_DROP  >  NOT_REACHED
```

Rationale: a single cycle that *used* the source proves it works and contributes -> `USED` dominates (the source is fine, period). Absent any `USED`, `QUALITY_REJECT` (fetched, produced notes, all rejected) is a stronger, more specific signal than `ACCESS_FAIL`; a recorded relevance skip beats an unexplained drop; `NOT_REACHED` is the weakest (the stage never got to it). The per-cycle JSON keeps the full per-cycle history so the collapse is auditable, never lossy.

- *Rejected*: "most recent cycle wins". Rejected — a transient cycle-5 access blip would mask four cycles of healthy `USED`, producing a false alarm.

### D3 — Zero pipeline change is structural, not just behavioural

The script lives in `scripts/`, not `pipeline/`. A `scripts/` file is not on any cycle import path, so "zero pipeline change" can't regress by accident in a later refactor. The verdict state machine is nonetheless written as a **pure importable function** (`resolve_verdict(signals) -> Verdict`) with zero filesystem coupling, so the deferred FR-020-in-pipeline promotion is a *lift* (import the function) rather than a rewrite.

- *Rejected*: adding a `source_ledger` table to `sources.db`, or a `cycle_runner` write step. Both are pipeline changes -> out of binding scope, and a new store violates the spec's "no new parallel logging system / it's a join" constraint (and brushes Principle V's no-new-persistence spirit even though sqlite is stdlib).

### D4 — Partial / aborted runs degrade to `NOT_REACHED`, never crash

Live runs abort (budget cap, source-quorum loss, manual interrupt). A cycle may be missing its scout, research, or quality artifact. The reader for each input is defensive: a missing/`malformed` artifact contributes *no* signal for that cycle, and a source with no signal in any reached cycle resolves to `NOT_REACHED` (or `PIPELINE_DROP` if the stage demonstrably ran but produced no per-source row — see the state machine in `data-model-v2.md`). The script must run cleanly on a half-finished `_pipeline/` tree — that is the common case during the live runs.

- *Rejected*: requiring a complete run. Rejected — the diagnostic is most valuable precisely on the runs that *didn't* finish cleanly.

### D5 — FR-019 uniform-failure surface + non-zero exit (Clarifications SL-Q2)

Per the clarification, "unexplained silence" is **not** a special category. Any *required* source whose collapsed verdict is a failure (`ACCESS_FAIL`, `PIPELINE_DROP`, `QUALITY_REJECT`) is surfaced the same way as a dead service or a wrong key: a WARN line in the roll-up + a **non-zero script exit code**. `SKIPPED_RELEVANCE` with a recorded reason on a required source is *not* a failure (it's a legitimate, explained skip). Optional (`required: false`) sources never drive the exit code. The opt-in hard-fail (spec-033 `approval_gates`) is a later promotion.

## 3. Cross-spec dependency: FR-018 is hard-blocked on spec 054 (`managed`)

Per Clarifications SL-Q3, MCP-backed-ness is **routing-derived**: a source is MCP-backed iff the module that handled it (matched via the module's `manifest.triggers`, spec 020) is `managed: true` (spec 054). Verified 2026-06-03: `discovery.ModuleManifest` (`pipeline/source_bridge/discovery.py:39-53`) carries `triggers` and `preflight` but **no `managed` field** — spec 054 has not shipped. Therefore FR-018 cannot be implemented in this MVP without taking a dependency on unshipped spec 054.

**This is a sequencing dependency, not an unresolved decision** — the spec already routes FR-018 explicitly to spec 054 + the spec-020 trigger registry. So it is documented as out-of-MVP-scope (in `plan-v2.md` and the contract) rather than raised as `[NEEDS CLARIFICATION]`. The MVP's known blind spot: an MCP-backed source that returns nothing and for which the agent recorded no reason resolves to `PIPELINE_DROP` (loud, correct enough — it *is* unexplained), and one with an agent reason resolves to `SKIPPED_RELEVANCE` (the v1 false-negative the spec names). The contract states this limitation plainly so the live-run operators read the MCP rows with the right caveat.

## 4. Alternatives considered and rejected (summary)

| Alternative | Rejected because |
|---|---|
| `structlog` / a richer reporting lib | Principle V — no new dep; stdlib `json`/`sqlite3` suffice |
| New `source_ledger` SQLite table | Pipeline change + new store; the spec mandates a *join*, not a parallel surface |
| Recompute by re-running cycles | Violates zero-pipeline-change and is wasteful; all signals are already persisted |
| Agent self-report as verdict authority | Principle IV violation + reintroduces the (c)-as-(a) ambiguity the ledger exists to kill |
| Most-recent-cycle-wins collapse | Masks healthy history with transient blips (D2) |
| Edit `run_report.py` to embed the ledger | Pipeline change; the MVP writes its own roll-up block read-only. Embedding is part of the FR-021 promotion |

## 5. Open questions

None blocking the MVP. FR-018 is a documented cross-spec sequencing dependency (§3), not an open decision. No `[NEEDS CLARIFICATION]` markers are warranted for the MVP scope.
