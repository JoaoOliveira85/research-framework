# Contract: Agent-call sidecar v1.1

**Status**: Locked at spec 028 plan time (2026-05-26)  
**Owners**: Spec 028 (producer + consumer migration); **Spec 033 Wave 2** (cost enforcement reader — LOAD-BEARING)  
**Supersedes for new writes**: `specs/_archive/025-simplify-pass/contracts/llm-dispatch.contract.md` §3 field set and flat `cycle-*-*.cost.json` paths

## 0 — Version & compatibility

This contract defines **schema_version `"1.1"` / `"1.2"`**. The bump from `1.0` (defined in `specs/_archive/025-simplify-pass/contracts/llm-dispatch.contract.md` §3 and currently shipping at flat `_pipeline/cycles/cycle-NNN-*.cost.json` paths) reflects three additive-but-required field additions: `agent_kind`, `status`, and `cycle`. Spec 025's `1.0` writers never used the new `agent-calls/` directory, so the path discriminator is unambiguous:

| `schema_version` | File location | Producer | Status |
|------------------|---------------|----------|--------|
| `"1.0"` | `_pipeline/cycles/cycle-NNN-{stage}.cost.json` (flat) | Pre-028 `agent_call.py --cost-sidecar` | Retired for new writes after spec 028 ships; legacy on-disk artifacts may persist on older vaults |
| `"1.1"` | `_pipeline/cycles/cycle-NNN/agent-calls/*.json` (this contract) | Spec 028 producer | Read-compatible; lacks `cost_source` |
| `"1.2"` | `_pipeline/cycles/cycle-NNN/agent-calls/*.json` (this contract) | Spec 028 **rc3 amendment** producer | Required for all new dispatches |

Consumers SHOULD branch on path, not parse both schemas from the same directory. Spec 033's `cost_estimator` MUST read only `"1.1"`/`"1.2"` sidecars from the `agent-calls/` directory (no fallback to legacy `1.0` paths).

### 0.1 — v1.2 amendment: `cost_source` (rc3, FR-028C)

`"1.2"` adds a single **additive** field, `cost_source`, recording the provenance of `cost_usd`:

| `cost_source` | Meaning |
|---------------|---------|
| `"runtime"` | Both tokens **and** dollar measured from the runtime's own signal — claude `stream-json` `total_cost_usd`, or a parsed codex per-call cost. |
| `"runtime_tokens"` | **Flat-rate runtime (spec 052, cursor-agent):** real token counts come from the runtime's `usage` block, but the runtime emits **no dollar figure** (subscription-billed). The `cost_usd` is therefore the spec-033 estimator value applied to the *real* tokens. Distinct from `"estimated"`, where the tokens are also estimated. |
| `"estimated"` | The spec-033 `cost_estimator` value (tokens **and** dollar both estimated), used when a non-claude runtime emits no parseable cost (never a silent `$0`). |
| `"none"` | Neither a runtime signal nor an estimate was available (estimator unavailable / settings missing). Emits a `WARN` on stderr. |

The field is **additive**: `"1.1"` readers ignore it (`.get()`-based), and a v1.2 sidecar that omits `cost_source` (e.g. the fake-agent shim) still validates. The retired draft literals `"codex"` / `"estimate"` MUST NOT be written.

---

## 1 — File location

All sidecars for cycle `N` (three-digit `NNN` in directory name) live under:

```text
<vault>/_pipeline/cycles/cycle-NNN/agent-calls/<filename>.json
```

The `agent-calls/` directory is created on first write (`mkdir -p`, i.e. `pathlib.Path.mkdir(parents=True, exist_ok=True)`). Writes are **best-effort** (failure logs WARN, does not fail the LLM call).

### 1.1 — Filename families

| Family | Filename pattern | When |
|--------|------------------|------|
| **Per-call, first** | `{stage}.json` | First `dispatch()` or first CLI call for that `stage` in the cycle |
| **Per-call, repeat** | `{stage}-2.json`, `{stage}-3.json`, … | Second and subsequent dispatches for the same `stage` in the same cycle (FR-005, FR-012) |
| **Per-batch** | `{stage}-batch-{B}.json` | CLI `--cost-sidecar` from note-writer batch loop; `B` is **1-indexed** (FR-006) |

**Examples** (cycle 7):

```text
agent-calls/plan_narrator.json
agent-calls/probe_retrieval.json
agent-calls/plan_narrator-2.json            # quality-report retry
agent-calls/note_writer-batch-1.json        # note-writer batch 1 (stage="note_writer")
agent-calls/note_writer-batch-2.json
agent-calls/scout.json                      # scout stage (after CLI migration)
```

> **Note on `{stage}` value.** Per `src/research_framework/pipeline/steps/research.py`, the batched note-writer is invoked with `--stage note_writer`. The `{stage}` token in `{stage}-batch-{B}.json` therefore resolves to `note_writer`, not `research`. If a future cycle step renames the batched call's `--stage` argument, batch filenames will follow that rename automatically.

**Retired paths** (MUST NOT be written after spec 028 ships):

```text
_pipeline/cycles/cycle-NNN-scout.cost.json
_pipeline/cycles/cycle-NNN-research.cost.json
```

### 1.2 — Collision semantics

- **Uniform numeric suffix** for all repeat dispatches of the same `stage`, including `_quality_report_guard` retries (clarification 2026-05-26 Q3). The guard does not choose filenames; `dispatch()` / allocator does.
- **No overwrite**: if `{stage}.json` exists, the next call uses `{stage}-2.json`, then `{stage}-3.json`, monotonically.
- **Batch files are independent**: `note_writer-batch-1.json` does not participate in the `{stage}-N` sequence for `note_writer` per-call files (different filename pattern). A hypothetical second per-call dispatch of `note_writer` in the same cycle would produce `note_writer-2.json`, distinct from any `note_writer-batch-*.json`.
- **Allocator** MUST be filesystem-backed (list existing files before write) so CLI subprocesses and in-process `dispatch()` calls see the same sequence.

### 1.3 — Atomic write

Producers MUST write via temp file in `agent-calls/` + `os.replace` to the final name so readers never observe partial JSON.

---

## 2 — JSON document schema

### 2.1 — Required fields (every sidecar)

| Field | Type | Constraints |
|-------|------|-------------|
| `schema_version` | string | Must be `"1.1"` |
| `stage` | string | Matches dispatcher `stage` argument |
| `agent` | string | Resolved runtime (`claude`, `codex`, `fake`, …) |
| `agent_kind` | string | `"fake"` or `"real"` — **not** inferred from `cost_usd` |
| `tier` | string | Tier used for this call |
| `status` | string | `"ok"` or `"failed"` |
| `exit_code` | integer | `0` when `status` is `"ok"` |
| `cost_usd` | number | ≥ 0, rounded to 4 decimal places |
| `tokens_in` | integer | ≥ 0 |
| `tokens_out` | integer | ≥ 0 |
| `latency_ms` | integer | ≥ 0, wall-clock milliseconds |
| `started_at` | string | ISO-8601 UTC (see §3) |
| `completed_at` | string | ISO-8601 UTC; must be ≥ `started_at` |
| `cycle` | integer | Cycle number (same as directory `cycle-NNN`) |

### 2.2 — Optional fields

| Field | Type | When present |
|-------|------|--------------|
| `stderr_excerpt` | string | `status == "failed"` or non-zero exit; max 500 chars |
| `batch_index` | integer | Per-batch sidecars only; 1-indexed batch id |
| `topic_count` | integer | Per-batch sidecars only; topics in batch |
| `duration_ms` | integer | Optional CLI mirror of stream-json `duration_ms` |
| `timed_out` | boolean | CLI timeout path |

### 2.3 — JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://research-framework.local/schemas/agent-call-sidecar-1.1.json",
  "title": "AgentCallSidecarV1_1",
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

## 3 — Timestamp formats

| `agent_kind` | Format | Examples |
|--------------|--------|----------|
| `fake` | Second precision; **exact** sentinel strings | `2000-01-01T00:00:00Z`, `2000-01-01T00:00:01Z` |
| `real` | Millisecond precision UTC | `2026-05-26T17:40:35.123Z` |

**Real-agent writer**:

```python
datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
```

**Invariant (real)**: `latency_ms` equals rounded delta between parsed timestamps within ±1 ms.

Consumers (including spec 033) MUST branch on `agent_kind`, not on timestamp string shape alone.

---

## 4 — Failure semantics

When a call fails (non-zero exit, timeout, missing binary, stream parse error):

1. **Still write** a sidecar at the allocated path.
2. Set `status: "failed"` and `exit_code` to the subprocess code (or `-1` / `2` for synthetic cases per implementation).
3. Populate **best-effort** `cost_usd`, `tokens_in`, `tokens_out` from stream events seen before failure; missing → `0`.
4. Set `started_at` / `completed_at` from captured wall clock (real) or sentinels (fake).
5. Include `stderr_excerpt` when stderr is available (truncated).

Successful calls: `status: "ok"`, `exit_code: 0`.

**Summation**: `_sum_sidecar_costs` and spec 033 cap math **include** failed sidecars' `cost_usd` (partial spend still bills).

---

## 5 — Consumer rules

### 5.1 — `_sum_sidecar_costs`

- Glob: `<vault>/_pipeline/cycles/cycle-NNN/agent-calls/*.json`
- Parse single schema (this contract).
- Sum `cost_usd` (treat missing as 0).
- Return `None` if directory missing or zero JSON files (legacy fallback behaviour preserved at caller).

### 5.2 — Discriminators

- **Per-call vs per-batch**: presence of `batch_index` (optional field only on batch files).
- **Retry index**: infer from filename suffix `-2`, `-3`, not from a dedicated JSON field.

### 5.3 — Spec 033

Cost enforcement MUST read this contract path only — not legacy `*.cost.json`. Field names `tokens_in` / `tokens_out` / `cost_usd` are stable billing inputs.

---

## 6 — Producer checklist

- [ ] Allocate path via filesystem-backed suffix rules (§1.2)
- [ ] Set `agent_kind` explicitly (§2.1)
- [ ] Reuse shared stream-json parser for `claude` (FR-001)
- [ ] Write `status` + `exit_code` on every path (FR-011)
- [ ] Atomic `os.replace` write (§1.3)
- [ ] CLI `--cost-sidecar` emits this schema (not legacy `{runtime, input_tokens}`)
