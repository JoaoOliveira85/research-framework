# Contract: `dispatch()` protocol (producer ↔ consumer)

**Status**: Locked at spec 028 plan time (2026-05-26)  
**Companion**: [`sidecar-v1.contract.md`](./sidecar-v1.contract.md) (persistence shape)  
**Base dispatch surface**: `specs/_archive/025-simplify-pass/contracts/llm-dispatch.contract.md` §1–2 (unchanged)

---

## 1 — Producer: `scripts/agent_call.py::dispatch()`

### 1.1 — Callsite invariants

Every programmatic LLM invocation MUST:

1. Pass `cycle_dir=<vault>/_pipeline/cycles/cycle-NNN` when sidecar emission is required (all production cycle stages).
2. Use an allowed `stage` value from llm-dispatch §2.
3. Route `claude`/`codex` through the shared stream-json consumer (extracted from `_run_claude_with_cost`) — **no** hard-coded zero cost on success (FR-001, FR-010).
4. Allocate the sidecar path via FR-005 allocator **before** write (never bare `{stage}.json` if that file already exists).
5. Populate `AgentCallResult` fields to match the sidecar numerics for the return path.

### 1.2 — Execution flow

```text
dispatch(stage, prompt, *, tier, agent, cycle_dir, timeout_s)
  ├─ resolve agent_name, executor, cmd
  ├─ started_mono = time.monotonic()
  ├─ started_at = f(agent_kind)           # real: wall ms; fake: sentinel[0]
  ├─ subprocess.run / stream parse
  │    ├─ on success: cost_usd, tokens_*, latency_ms from stream
  │    └─ on failure: partial stream values, status failed
  ├─ completed_at = g(agent_kind, ...)  # real: wall ms; fake: sentinel[1]
  ├─ path = allocate_sidecar(cycle_dir, stage)
  └─ write_sidecar_v1(path, payload)    # atomic replace
       └─ return AgentCallResult(...)
```

### 1.3 — Fake-agent producer rules

When the vault uses the fake-agent shim:

- `agent_kind: "fake"`, `agent: "fake"` (or resolved fake runtime name — tasks pin exact string).
- `cost_usd`, `tokens_in`, `tokens_out` = 0.
- Timestamps **exactly** `2000-01-01T00:00:00Z` / `2000-01-01T00:00:01Z` (FR-004).
- `status: "ok"`, `exit_code: 0` on successful stub completion.

### 1.4 — Real-agent producer rules

- `agent_kind: "real"`.
- Millisecond timestamps (§3 of sidecar contract).
- `status: "ok"` + `exit_code: 0` only when subprocess succeeds **and** stream terminal `result` parsed.
- Failed runs still emit sidecar (§4 of sidecar contract).

---

## 2 — Producer: CLI `agent_call.py` (`run()` / `--cost-sidecar`)

### 2.1 — Callsite invariants

Pipeline steps (`research.py`, `scout.py`, `_cycle_helpers.py`) invoke:

```bash
python scripts/agent_call.py --vault <vault> --stage <stage> \
  --prompt-file <path> --cost-sidecar <path>
```

After spec 028:

- `<path>` MUST be under `cycle-NNN/agent-calls/` per sidecar v1.0 §1.
- Batch loops MUST pass distinct `{stage}-batch-{B}.json` paths (FR-006). For the current batched note-writer call (`--stage note_writer`), this resolves to `note_writer-batch-{B}.json`.
- CLI MUST emit **sidecar v1.0** JSON (same required fields as `dispatch()`), including `cycle`, `agent_kind`, `status`.

### 2.2 — Shared parsing

CLI `claude` path and `dispatch()` MUST call the same stream-json extraction function (FR-001).

---

## 3 — Consumer: orchestrator cost math

### 3.1 — `_sum_sidecar_costs(vault_dir, cycle_num)`

**Input**: Vault root + cycle index.  
**Reads**: `agent-calls/*.json` for that cycle only.  
**Output**: `float` total USD or `None` if no sidecars.

**Invariants**:

- Includes all files matching `*.json` in `agent-calls/` (per-call, suffixed, batch).
- Includes `status: "failed"` files (FR-011).
- Ignores unreadable files with WARN (behaviour preserved).
- Does **not** read retired `cycle-*-*.cost.json`.

### 3.2 — `_cumulative_sidecar_cost` / budget cap

Uses `_sum_sidecar_costs` per cycle — no separate dispatch memory. Spec 033 adds enforcement; 028 only ensures inputs are complete and non-colliding.

### 3.3 — `_append_budget_log`

When sidecar total is authoritative, log row uses `_sum_sidecar_costs` result (precedence unchanged; source path changes).

---

## 4 — Consumer: `_write_cycle_quality_report`

**Does not parse sidecars directly** for cost (today). Quality report may reference cycle totals produced elsewhere.

**Retry interaction** (FR-012): `_quality_report_guard` may re-invoke stages; each re-dispatch is a **new producer call** → new suffixed sidecar via §1.2 allocator. Guard code unchanged.

---

## 5 — Consumer: `run_report.py`

`build_run_report` cost section MUST glob `agent-calls/*.json` (sidecar v1.0) instead of `cycle-*-*.cost.json`, summing `tokens_in` / `tokens_out` / `cost_usd` field names from this contract.

---

## 6 — Test enforcement matrix

| Invariant | Tier | Notes |
|-----------|------|-------|
| Sidecar schema required fields | 2 | Contract test against JSON Schema |
| Allocator suffix sequence | 2 | Unit |
| `dispatch()` populates `AgentCallResult` | 2–4 | Mock stream |
| No overwrite on double dispatch | 3 | Integration |
| Batch files sum in `_sum_sidecar_costs` | 3 | Integration |
| Fake timestamp bytes stable | 2 | Regression for tier-5/6 fixtures |
| Real cost ≈ CLI (SC-001) | 2/3 + `live_llm` | Opt-in |

---

## 7 — Forbidden patterns

- Writing cost telemetry outside `agent-calls/` for cycle-bound stages.
- Using `cost_usd == 0.0` to select timestamp mode.
- Overwriting an existing sidecar path on repeat dispatch.
- Direct `subprocess` of `claude`/`codex` outside `agent_call.py` (unchanged from spec 025 §4).
