# Phase 1 Data Model — opencode Executor

This feature is dispatch plumbing, not a data subsystem. "Entities" here are the
config/runtime shapes the adapter reads and the telemetry it writes. No DB, no
persistent schema beyond the (unchanged) spec-028 sidecar.

---

## E1 — opencode executor block (settings)

The `default_executor` / `stages.*` executor mapping `agent_call.py` already
consumes, with opencode-specific values. **No new keys vs the cursor profile** —
opencode reuses the existing executor schema.

| Field | Type | Notes |
|---|---|---|
| `type` | `"cli"` | opencode is a CLI runtime (not `script`, not `api`). |
| `runtime` | `"opencode"` | NEW allowed value; selects `_opencode_cmd`. |
| `model` | `str` | opencode `provider/model` id, e.g. `ollama/qwen2.5:7b`, `anthropic/claude-sonnet-4-6`. |
| `variant` | `str?` | OPTIONAL reasoning effort → `--variant high\|max\|minimal`. Absent ⇒ no flag. |
| `agent` | `str?` | OPTIONAL opencode agent name → `--agent`. Absent ⇒ default. |
| `args` | `list[str]` | Appended verbatim (e.g. the unattended-approval flag). `--dir` is auto-injected, not here. |
| `skill` | `str?` | per-stage skill (unchanged semantics). |
| `timeout_s`, `retry`, `on_fail` | as today | runtime-agnostic. |

**Validation**: `runtime: opencode` requires a non-empty `model` containing a
`provider/model` shape; invalid `variant` (not in opencode's allowed set) is
passed through (opencode validates) but SHOULD be range-checked with a clear
error at settings-load (mirrors the cursor profile's strictness).

---

## E2 — opencode invocation (derived, not stored)

Built by `_opencode_cmd(executor, vault_dir)`; never persisted.

```
opencode run --format json --model <model> --dir <vault>
             [--variant <variant>] [--agent <agent>] <args…>
# prompt on stdin/positional
```

Rules:
- `--dir <vault>` injected iff `vault_dir` is set AND the operator did not already
  pass `--dir` in `args` (reuse `_has_workspace_flag`-style guard).
- cost-capture: same command — `--format json` emits **NDJSON** events; no separate
  stream mode (VERIFIED 2026-06-11). Parse `step_finish` events for tokens + cost (E3).

---

## E3 — Cost classification result (per call)

Produced by `_opencode_cost_class(model, usage)`, consumed by `_resolve_cost`,
written into the spec-028 sidecar. **No schema change** — reuses existing fields.
`usage` is accumulated from the NDJSON `step_finish` events: `part.tokens.input/output`
summed, `part.cost` summed (VERIFIED 2026-06-11: local ollama ⇒ `cost: 0` + real tokens).

| Field | Type | Local model | Metered (tokens, no $) | Metered (tokens + $) | No usage |
|---|---|---|---|---|---|
| `cost_usd` | `float` | `0.0` (measured) | estimator | real $ | estimator |
| `tokens_in/out` | `int` | real | real | real | `0` |
| `cost_source` | enum | `"runtime"` | `"runtime_tokens"` | `"runtime"` | `"estimated"` |
| `executor` | `str` | `"opencode"` | `"opencode"` | `"opencode"` | `"opencode"` |
| `model` | `str` | resolved `provider/model` | … | … | … |

`cost_source` enum is the **existing** `{runtime, runtime_tokens, estimated, none}`
(sidecar schema 1.2). Local-provider detection: prefix of `model` in a
configurable local-provider set (default `{ollama, local}`).

---

## E4 — Benchmark `Executor` (FR-020 label)

`src/research_framework/benchmark/matrix.py`.

| Field | Type | Change |
|---|---|---|
| `runtime` | `str` | unchanged |
| `models` | `tuple[str, ...]` | unchanged |
| `label` | `str \| None` | **NEW**, optional. Default `None`. |

`Cell.key`:
- `label is None` → `f"{task}__{executor}__{model}"` (unchanged).
- `label` set → `f"{task}__{label}__{model}"` (label replaces the runtime token).

`Cell` gains nothing structurally; the key derivation reads the owning executor's
label (carried onto the cell at build time, or the cell stores an extra
`label: str | None` populated from the executor — implementation choice at tasks).
Reporter uses the same display token.

**Invariant (SC-008)**: with no `label` anywhere, every cell key + report row is
byte-identical to pre-064.

---

## State / lifecycle

None. Each opencode call is stateless from the framework's view (one subprocess,
one sidecar). opencode's own session state is internal and not consumed here
(v1 does not use `--continue`/`--session`).
