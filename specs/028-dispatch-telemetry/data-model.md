# Data Model: Sidecar v1.0 (Spec 028)

**Canonical contract**: [`contracts/sidecar-v1.contract.md`](./contracts/sidecar-v1.contract.md)  
**Supersedes (path + fields only)**: `specs/_archive/025-simplify-pass/contracts/llm-dispatch.contract.md` §3 for new writes; 025 remains the dispatch-surface contract.

---

## Entities

### `AgentCallSidecar` (per-call or per-batch file)

One JSON document per LLM invocation (programmatic `dispatch()` or CLI `--cost-sidecar`). Stored at:

```text
<vault>/_pipeline/cycles/cycle-<NNN>/agent-calls/<filename>.json
```

**Filename rules** (see contract for normative detail):

| Call pattern | Filename |
|--------------|----------|
| First dispatch for `stage` in cycle | `{stage}.json` |
| Nth repeat dispatch (same `stage`) | `{stage}-2.json` … `{stage}-N.json` |
| Note-writer batch B (CLI path) | `{stage}-batch-{B}.json` |

**Identity**: Uniqueness is `(cycle_dir, filename)`. No database row.

**Lifecycle**: Created at end of invocation (success, failure, or timeout). Immutable after write except manual operator edits. Read by `_sum_sidecar_costs`, `run_report.py`, future spec 033 cost enforcement.

### `AgentCallResult` (in-process only)

Existing frozen dataclass in `scripts/agent_call.py`. Not persisted except via the sidecar mirror fields.

| Field | Type | Source |
|-------|------|--------|
| `stdout` | `str` | subprocess |
| `stderr` | `str` | subprocess |
| `exit_code` | `int` | subprocess |
| `cost_usd` | `float` | stream-json `total_cost_usd` (real) or `0.0` (fake) |
| `tokens_in` | `int` | stream-json `usage.input_tokens` |
| `tokens_out` | `int` | stream-json `usage.output_tokens` |
| `latency_ms` | `int` | wall-clock monotonic delta |

FR-010: all numeric fields populated for real-agent success paths.

### `SidecarIndex` (derived, not stored)

Ephemeral view built by globbing `agent-calls/*.json` for a cycle. Used by orchestrator summation and operator tooling.

| Derived field | Computation |
|---------------|-------------|
| `total_cost_usd` | Σ `cost_usd` over all readable sidecars (includes `status: failed`) |
| `per_stage_cost` | Group by `stage` field |
| `batch_entries` | Filter `batch_index IS NOT NULL` |

---

## Field catalog (sidecar v1.0)

| Field | Required | Type | Notes |
|-------|----------|------|-------|
| `schema_version` | yes | string | Always `"1.1"` (bump from spec 025's `"1.0"` reflects the new required fields `agent_kind`, `status`, `cycle`; see `contracts/sidecar-v1.contract.md` §0) |
| `stage` | yes | string | Dispatch `stage` param (e.g. `plan_narrator`, `research`) |
| `agent` | yes | string | Resolved runtime: `claude`, `codex`, `fake`, … |
| `agent_kind` | yes | string | `"fake"` \| `"real"` — drives timestamp rules (FR-002) |
| `tier` | yes | string | `basic` \| `standard` \| `expert` |
| `status` | yes | string | `"ok"` \| `"failed"` (FR-011) |
| `exit_code` | yes | int | `0` on success; subprocess code or sentinel `-1` |
| `cost_usd` | yes | number | ≥ 0, 4 decimal places max |
| `tokens_in` | yes | integer | ≥ 0 |
| `tokens_out` | yes | integer | ≥ 0 |
| `latency_ms` | yes | integer | ≥ 0; wall-clock for dispatch path |
| `started_at` | yes | string | ISO-8601 UTC (see precision rules) |
| `completed_at` | yes | string | ISO-8601 UTC; ≥ `started_at` |
| `cycle` | yes | integer | 1-based cycle number (FR-006 consumer convenience) |
| `stderr_excerpt` | no | string | Max 500 chars when `status != ok` |
| `batch_index` | no | integer | 1-indexed; batch sidecars only |
| `topic_count` | no | integer | Topics in batch; batch sidecars only |
| `duration_ms` | no | integer | CLI legacy mirror of stream `duration_ms` (optional) |
| `timed_out` | no | boolean | CLI timeout sentinel (optional) |

**Retired CLI-only keys** (do not emit on new writes): `runtime`, `input_tokens`, `output_tokens` as top-level names — map to `agent`, `tokens_in`, `tokens_out`.

---

## Timestamp precision rules

| `agent_kind` | `started_at` / `completed_at` format | Example |
|--------------|--------------------------------------|---------|
| `fake` | Second precision, fixed sentinels | `2000-01-01T00:00:00Z`, `2000-01-01T00:00:01Z` |
| `real` | Millisecond precision | `2026-05-26T17:40:35.123Z` |

**Invariant (real)**: `latency_ms ≈ round((completed_at - started_at).total_seconds() * 1000)` within ±1 ms (FR-003).

**Writer (real)**: `datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")`

---

## State transitions (`status`)

```text
invocation_start
    → stream/subprocess running
        → success (exit 0, parse ok)     → status: "ok",     exit_code: 0
        → failure (non-zero exit)        → status: "failed", exit_code: N, partial telemetry
        → timeout / crash / parse error  → status: "failed", exit_code: 2 or -1, partial telemetry
```

Failed invocations **still write a sidecar** (FR-011). `_sum_sidecar_costs` **includes** `cost_usd` from failed sidecars in cap math.

---

## JSON Schema (sidecar v1.0)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://research-framework.local/schemas/agent-call-sidecar-1.0.json",
  "title": "AgentCallSidecar",
  "type": "object",
  "additionalProperties": true,
  "required": [
    "schema_version",
    "stage",
    "agent",
    "agent_kind",
    "tier",
    "status",
    "exit_code",
    "cost_usd",
    "tokens_in",
    "tokens_out",
    "latency_ms",
    "started_at",
    "completed_at",
    "cycle"
  ],
  "properties": {
    "schema_version": { "const": "1.1" },
    "stage": { "type": "string", "minLength": 1 },
    "agent": { "type": "string", "minLength": 1 },
    "agent_kind": { "enum": ["fake", "real"] },
    "tier": { "type": "string" },
    "status": { "enum": ["ok", "failed"] },
    "exit_code": { "type": "integer" },
    "cost_usd": { "type": "number", "minimum": 0 },
    "tokens_in": { "type": "integer", "minimum": 0 },
    "tokens_out": { "type": "integer", "minimum": 0 },
    "latency_ms": { "type": "integer", "minimum": 0 },
    "started_at": { "type": "string", "format": "date-time" },
    "completed_at": { "type": "string", "format": "date-time" },
    "cycle": { "type": "integer", "minimum": 1 },
    "stderr_excerpt": { "type": "string", "maxLength": 500 },
    "batch_index": { "type": "integer", "minimum": 1 },
    "topic_count": { "type": "integer", "minimum": 0 },
    "duration_ms": { "type": "integer", "minimum": 0 },
    "timed_out": { "type": "boolean" }
  }
}
```

---

## Relationships

```text
dispatch(stage, cycle_dir) ──writes──► AgentCallSidecar (per-call path)
agent_call.py CLI --cost-sidecar ──writes──► AgentCallSidecar (per-batch or scout)
         │
         ▼
_sum_sidecar_costs(cycle) ──reads glob agent-calls/*.json──► float | None
         │
         ▼
_append_budget_log / cumulative cap (spec 033 extends)
```
