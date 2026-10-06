# Phase 0 — Research: Source-relevance + declared-source validation (069)

Grounded in (a) a live audit of `~/Documents/reference-vault-rc7/` and (b) a code audit of
`source_bridge/discovery.py`, `spec/schema.py`, `spec/validator.py`,
`pipeline/preconditions.py`, `pipeline/quality_report.py`, `cli/status.py`,
`scripts/source_ledger.py`, `pipeline/source_authority.py`.

## rc7 evidence (the silent-empty)

- `research.spec.md::data_sources`: "Codebase Vault Seed" (`access_method: local
  filesystem`), "GitHub" (`access_method: GitHub MCP`, has repos), "Official
  Documentation" (`access_method: web fetch`), "Web" (`access_method: web fetch`). All
  `required: true`.
- The vault has **no `modules/` directory at all** (`vault` is the shim *file*; no
  top-level `modules/`).
- Across 4 cycles, only the framework-side rc5 modules `code` + `github` yielded; the 4
  declared sources contributed essentially nothing. Three declared sources are
  descriptive LLM-fetch hints with no module → silent empties.

## D1 — The binding mechanism already exists (and is under-used)

**Decision**: Use the existing manifest `triggers[]` + `TriggerRegistry` for the
backing check. **Rationale**: `source_bridge/discovery.py` defines `ModuleManifest`
(triggers), `build_trigger_registry`, `TriggerRegistry`, and `_matches` (url_pattern →
`re.search`; path_pattern → `re.search`; path_exists → `Path.exists`; `domain` →
substring). The orchestrator already builds the registry (`orchestrator.py:60`) but
**discards `match()`** — modules run by `settings.modules` + filesystem walk, not by
matching declared sources. So the operator's "manifest declares its triggers" model is
already the shipped data shape; 069 just wires it into validation. **Alternatives
considered**: invent a new module↔source binding (rejected — duplicates an existing,
tested registry); keep the name-slug convention (rejected — it's exactly what let
unbacked sources pass silently).

## D2 — A declared source's "locator" for trigger matching

**Decision**: Match a source against module triggers using any **concrete locator** it
carries: `repos[].url` / `repos[].local_path`, `local_path`, or an optional new
`locator`/`url` hint. A source with **no** concrete locator (pure description like
"Web" / "Official Documentation") cannot match a `url_pattern`/`path_*` trigger and is
therefore **required to be `kind: strategy_hint`**. **Rationale**: this is the honest
outcome — those three rc7 sources are LLM-fetch directives with no implementation, so
they must be named as strategy hints (or get a module). "GitHub" has repo URLs that
match the `github` module's `url_pattern` trigger → backed. **Alternatives
considered**: match by source `name` slug (rejected — brittle, the current bug); force
every source to carry a URL (rejected — "Web" legitimately has none; that's what
`strategy_hint` is for).

## D3 — `kind` enum + absent-`kind` inference

**Decision**: `DataSourceConfig.kind ∈ {module_backed, strategy_hint}`, optional.
Resolution: if `kind == strategy_hint` → OK (LLM-fetch, no module needed). Else
(`module_backed` or absent) the source MUST trigger-match an installed module; if it
does → OK; if not → **scaffold-time error** ("source X declared but has no
implementation; add a module whose manifest triggers match, or annotate `kind:
strategy_hint`"). **Rationale**: existing specs whose sources DO match keep working
with zero edits (absent `kind` infers `module_backed` and passes); only genuinely
unbacked sources must be annotated — minimal churn, maximal honesty.
`schema.py::DataSourceConfig` has no `kind` today, so this is purely additive.
**Alternatives considered**: require explicit `kind` on every source (rejected — breaks
every existing spec); auto-generate stub modules (Q1 option c, rejected by the operator).

## D4 — Validation gates (scaffold + runtime)

**Decision**: Two scaffold gates — `spec/validator.py::validate` (the `generate` path,
called from `cli/research_generate.py`) and `scripts/validate_spec.py` (the vault-spec
skill pre-scaffold gate, warn-level there, hard error at generate). Runtime fail-closed
at `pipeline/preconditions.py` check #6 (resume) — and add the backing check to the
generate path, since fresh `generate` does **not** call `preconditions.check` today
(only `--resume` does). **Rationale**: catch the problem as early as scaffold, with a
runtime backstop. **Alternatives considered**: runtime-only (rejected — the operator
should learn at scaffold, not after a wasted cycle).

## D5 — Stagnant-source signal reuses existing surfaces

**Decision**: Compute ≥2-consecutive-cold from `scripts/source_ledger.py`
(`load_declared_sources` + per-cycle verdicts incl. the existing `SKIPPED_RELEVANCE`
placeholder); emit a WARN through the existing `quality_report._degraded_sources` /
`_pipeline/source-incidents.md` surface and `status.build_status_json`'s
`deferred_warnings` pattern. **Rationale**: a `degraded_sources` field already exists in
the cycle quality report — extend it rather than inventing a parallel channel.
**Alternatives considered**: a brand-new `_pipeline/stagnant-sources.json` (rejected —
duplicates `degraded_sources`).

## D6 — FR4 (relevance-classifier tuning) is deferred (Q3)

**Decision**: 069 ships FR1/FR2/FR3/FR5 only. The `gh`-went-cold relevance-classifier
tuning (FR4) needs live data + investigation and becomes a **follow-up sub-spec** filed
at `/speckit.specify`. **Rationale**: keeps the honest-coverage structural fix
shippable for rc8 without blocking on a tuning study. The source-relevance classifier
is **agent-only today** (settings stage + `.agents/skills/source-relevance/SKILL.md`);
its only structured framework consumption is `source_ledger.SKIPPED_RELEVANCE` — a thin
seam the sub-spec can build on. **Alternatives considered**: tune now (rejected — Q3).

## Summary of locked decisions

| ID | Decision |
| --- | --- |
| D1 | Reuse existing manifest `triggers[]` + `TriggerRegistry.match` (currently discarded) for backing. |
| D2 | Source locator = its concrete URL/path; no-locator sources MUST be `strategy_hint`. |
| D3 | `kind ∈ {module_backed, strategy_hint}`, optional; absent infers backed-if-matches else scaffold error. Additive, no schema bump. |
| D4 | Scaffold gates in `spec/validator.py` + `scripts/validate_spec.py`; runtime fail-closed in `preconditions.py` (+ generate path). |
| D5 | Stagnant signal reuses `degraded_sources` + `source_ledger` + `status` deferred-warnings; ≥2-cold = WARN. |
| D6 | FR4 relevance tuning deferred to a follow-up sub-spec. |
