# Phase 1 — Data Model: Source-relevance + declared-source validation (069)

One additive optional field on `DataSourceConfig`; everything else reuses existing
structures (manifest `triggers[]`, the trigger registry, the cycle quality report).

## Entity 1 — DataSourceConfig.kind (existing dataclass — NEW optional field)

`spec/schema.py::DataSourceConfig` (today: `name`, `type`, `description`, `required`,
`access_method`, `priority`, `role`, `default_credibility`, `repos[]`, `phases[]`).

| New field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `kind` | `str?` | absent | `module_backed` (must trigger-match an installed module) \| `strategy_hint` (LLM-fetch, no module required). **Absent ⇒ inferred (D3, locked U3): backed iff a trigger matches, else `unbacked` → error** (no third "ambiguous" state). |

Additive + optional ⇒ existing specs whose sources trigger-match stay valid with no
edit ⇒ **no `schema_version` bump**.

## Entity 2 — ModuleManifest.triggers (existing — now used for binding)

From `source_bridge/discovery.py::ModuleManifest.triggers: list[dict]`. Each trigger:
`{type, pattern}` where `type ∈ {url_pattern, path_pattern, path_exists, domain}`
(`domain` exists in `_matches` but not yet in the JSON-schema enum — FR1 adds it).
Compiled by `build_trigger_registry` into `TriggerEntry{module, trigger_type, pattern}`;
matched by `TriggerRegistry.match(target)` (currently built but unused at
`orchestrator.py:60`).

## Entity 3 — SourceBacking (computed, transient)

`source_is_backed(source: DataSourceConfig, registry: TriggerRegistry) -> Backing`

| Result | Condition |
| --- | --- |
| `backed` | `kind == module_backed` (or absent) AND the source's locator (D2) matches ≥1 module trigger |
| `strategy_hint` | `kind == strategy_hint` (valid, no module required) |
| `unbacked` | neither — **scaffold-time error / preflight FAIL** |

Locator resolution (D2, **locked at analyze U2**): first non-empty of the existing
fields `repos[].url`, `repos[].local_path`, `local_path`; else `None` ⇒ cannot match
⇒ must be `strategy_hint` or `unbacked`. **v1 adds no new `locator`/`url` field** —
the existing fields cover every rc7 source; a dedicated hint is deferred until a real
source requires it.

## Entity 4 — StagnantSourceSignal (FR3/FR5, transient)

Computed at cycle-end from `source_ledger` per-cycle verdicts.

| Field | Type | Notes |
| --- | --- | --- |
| `source` | `str` | declared source name |
| `cold_cycles` | `int` | consecutive cycles with zero facts/signals |
| `authority` | `str` | from `source_authority.build_source_role_index` (FR5 weighting) |
| `severity` | `"warn"` | always advisory (Q4); authoritative-cold ranked first |

Surfaced in `quality_report.degraded_sources` + `status.build_status_json`
deferred-warnings. Triggers when `cold_cycles >= 2`.

## Validation rules

- **FR1** — every declared source resolves to `backed` or `strategy_hint`; `unbacked`
  is a scaffold-time error with a clear, source-named message.
- **FR2** — preflight repeats the check and fails closed at runtime; never silently
  emits empty signals for an unbacked source.
- **FR3** — a source cold ≥2 consecutive cycles emits exactly one WARN per cycle;
  never blocks the cycle.
- **FR5** — an authoritative source (053) going cold ranks above a low-authority one
  in the WARN ordering.

## Migration

**Operator-driven (Q2).** Existing vaults with unbacked sources (incl. rc7): the
framework WARNs on `./vault update` and fails closed at preflight; the operator adds a
trigger-matching module **or** annotates `kind: strategy_hint`. The framework **never**
rewrites `research.spec.md`. No `schema_version` bump (absent `kind` is inferred). FR4
(relevance tuning) is a separate sub-spec.
