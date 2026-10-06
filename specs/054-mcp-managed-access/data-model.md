# Phase 1 Data Model: MCP-Managed Source Access

**Spec**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md) ·
**Research**: [research.md](./research.md) · Date: 2026-06-03

This feature adds **one manifest field** and **reuses two existing structures
verbatim** (no new persisted artifact, no schema-breaking change). The whole
point is that managed and unmanaged fetches are interchangeable downstream.

---

## 1. `managed` manifest field (NEW)

The spec-020 `manifest.yaml` gains an **optional boolean** `managed`.

### Python (`pipeline/source_bridge/discovery.py`)

`ModuleManifest` (dataclass) gains:

```python
managed: bool = False
```

`parse_manifest()` reads it defensively (anything but a real `True` is treated as
unmanaged — fail-safe toward the existing path):

```python
managed=bool(raw.get("managed", False))
```

- **Default `False`** → every existing in-tree module
  (`youtube/reddit/rss/oreilly/code`) and every existing vault manifest is
  **unmanaged with no behaviour change** (FR-001, FR-006, US3, SC-002).
- `managed: true` → the orchestrator routes this module's fetch through the
  managed-fetch seam instead of the subprocess extractor (FR-002).

### JSON Schema amendment (`specs/020-code-bridge/contracts/manifest.schema.json`)

Add to `properties` (NOT to `required` — backward-compatible, unlike the
spec-051 `preflight` amendment):

```json
"managed": {
  "type": "boolean",
  "default": false,
  "description": "spec 054 FR-001. When true, this module's fetch is delegated to an MCP-capable Claude Code subagent (via agent_call.dispatch, stage 'managed_fetch') instead of a subprocess extractor. The agent emits the same SignalPayload. Default false = subprocess (unchanged). MCP credentials live in the MCP server session; the framework never stores them."
}
```

`additionalProperties: false` stays — so the field must be explicitly listed.

### Routing precedence (validation, not a stored field)

`managed` is a **module property** (Clarifications Q3): the source is declarative
and the module declares spec-020 `triggers`; the pipeline routes source→module
and the module's `managed` flag decides the transport. There is **no per-source
`managed` field**. A **settings/CLI force-off override** can globally disable the
managed transport (treating a managed module as skipped or — design choice for
`/speckit.tasks` — as a hard-error so a misconfigured run fails loudly rather
than silently fetching nothing). Force-off lives in `settings.py`, not the
manifest.

---

## 2. `SignalPayload` — REUSED VERBATIM (no change)

`pipeline/source_bridge/signal.py::SignalPayload` is the output of both paths:

| field | managed value | unmanaged value |
|-------|---------------|-----------------|
| `module` | stamped by `managed_fetch` (== manifest.name) | stamped by `extract_source` |
| `source_id` | stamped by `managed_fetch` | stamped by `extract_source` |
| `source_version` | from agent stdout | from extractor stdout |
| `bridge_version` | stamped (== BRIDGE_VERSION) | stamped |
| `extracted_at` | stamped at write (`utc_now_iso`) | stamped at write |
| `verdict` | `ok`/`empty`/`error` | same enum |
| `truncated`, `partial` | from agent stdout | from extractor stdout |
| `facts` | module facts dict (or raw envelope, §3) | module facts dict |
| `notable[]` | `NotableObservation[]` | same |

**Invariant (FR-003, SC-001)**: a managed payload is **shape-identical** to an
unmanaged payload for the same source. Downstream (`validate_payload`,
consensus, signal cache, spec-048-v2 ledger, note-writing) requires **zero
managed-vs-unmanaged branching**. The only place that knows the transport is the
one routing branch in `_process_source`.

Parsing path is identical too: `managed_fetch` parses the agent's stdout with
the same `_extract_json_blob` + `SignalPayload.from_dict(...)` the extractor uses.

---

## 3. Raw-content-in-JSON envelope (opt-in, Clarifications Q2 / FR-003)

When raw mode is requested (a stage/settings-level flag — **not** per-source),
the managed agent wraps raw fetched content inside the existing `facts` dict:

```json
{
  "module": "confluence",
  "source_id": "SPACE/Page-Title",
  "source_version": "v42",
  "bridge_version": "...",
  "extracted_at": "2026-06-03T...Z",
  "verdict": "ok",
  "truncated": false,
  "partial": false,
  "facts": {
    "raw_mode": true,
    "raw": "<verbatim fetched content>"
  },
  "notable": []
}
```

- `facts` is already `dict[str, Any]` (open object) in the schema — `facts.raw` +
  `facts.raw_mode` carry raw content with **no schema change** and **no new
  top-level field** (a top-level field would break FR-003's no-special-casing
  guarantee).
- Facts-schema mode is the **default** (`raw_mode` absent/false); raw mode is the
  opt-in for "cases where the pipeline wants something specific the facts-schema
  would obscure" (FR-003 wording).
- A consumer that wants the raw content reads `facts.raw`; a consumer that does
  not is unaffected (it sees a normal, if sparse, facts dict).

---

## 4. Managed-fetch request (transient, not persisted)

The prompt the framework hands `agent_call.dispatch(stage="managed_fetch", ...)`.
Not a stored entity — documented for the contract:

| element | source |
|---------|--------|
| few-shot | the module's managed few-shot (`schema_examples` or a managed-specific `*.md`) |
| `source` record | the `sources.yaml` row routed to this module |
| `source_id` | the resolved per-source id (`source_id_from` mapping) |
| `raw_mode` flag | from settings/stage config |
| MCP tools | supplied by the dispatch executor's `args` (settings-driven, not in the prompt) |

---

## 5. O'Reilly credential (FR-009) — relocated, not a new entity

The O'Reilly bearer token moves from **env-only** to a **settings file** that
survives `./vault update` (joins the module's `user_owned` preserved set), with
env as a fallback:

- Precedence: **settings file → `OREILLY_API_KEY` env → error** (`verdict=error`,
  unchanged failure mode).
- Managed sources do NOT use this — they authenticate via the MCP server's own
  session; the framework stores **no** managed credentials (spec Key Entities).
- Exact file/key name is a `/speckit.tasks` pinning detail (research D6 unknown).

---

## Entity relationships

```
manifest.yaml
  ├─ managed: bool ───────────► orchestrator._process_source (routing branch)
  │        false ──────────────► extract_source()  ── subprocess ──► SignalPayload
  │        true  ──────────────► managed_fetch()
  │                                 ├─ _bespoke_for(manifest)  [v1: None]
  │                                 └─ _agent_dispatch_fetch() ─ dispatch(stage=managed_fetch) ─► SignalPayload
  ├─ preflight.entry_point ───► run_preflight() ── MCP probe (managed) ──► fatal_fail ⇒ skip-with-WARN (US2)
  └─ triggers[] ──────────────► source→module routing (unchanged; declarative)

SignalPayload (signal.py) ── identical for both transports ──► validate_payload ─► cache ─► ledger (048 v2) ─► note-writing
                              facts.raw / facts.raw_mode  ◄── opt-in raw envelope (no schema change)
```

## Backward compatibility

- `managed` absent ⇒ `False` ⇒ subprocess ⇒ **no change** for all five modules
  and every existing vault manifest (SC-002).
- Schema amendment is **additive** (new optional property; `required` unchanged).
- `SignalPayload` schema is **untouched** — raw mode rides inside the open
  `facts` object.
- FR-009 keeps env as a fallback ⇒ existing O'Reilly setups keep working.
