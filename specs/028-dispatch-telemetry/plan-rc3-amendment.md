# Implementation Plan (rc3 amendment): codex-runtime cost telemetry

**Parent spec**: [spec.md](./spec.md) (SHIPPED 0.4.0; this plans the **rc3 amendment**
section only) | **Branch**: rc3 wave | **Date**: 2026-06-05 | **Target**: 1.0.0rc3

> Scope: the "rc3 amendment" FRs added to the shipped spec 028 (codebase-vault rc1
> defect 3.5 — `$0` cost telemetry under the codex runtime). The original 028
> `plan.md` (in-process dispatch sidecars, sidecar collision, per-batch costs) is
> untouched and remains the source of truth for the shipped behaviour.

## Summary

Spec 028 captures real cost by parsing Claude's `stream-json` `result` event. Phase-0
confirmed there is **no codex equivalent** — `agent_call.py` parses cost only for
claude (`_claude_cmd` stream-json mode + `_apply_stream_event` reading
`total_cost_usd` / `usage.{input,output}_tokens`); a codex dispatch writes the sidecar
with `cost_usd = 0.0` (the `stream.cost_usd if stream else 0.0` fallback in
`_write_dispatch_sidecar_for_result`). That `$0` then flows into `total_cost_usd`,
defeating budget math + the spec-063 GA-005 telemetry gate.

The amendment makes codex cost **best-effort first-class, estimator-backed**: try to
parse codex's own cost/token signal; if none is available, fall back to the
spec-033 `cost_estimator` value; record which path produced the number via a new
`cost_source` discriminator. The sidecar schema bumps `1.1 → 1.2` for the new field.

| FR | What | Primary code target (verified path) |
| --- | --- | --- |
| A1 | Parse codex cost/tokens when codex emits a signal | `scripts/agent_call.py` (new `_codex_cost_from_output`, alongside `_apply_stream_event`) |
| A2 | Fall back to spec-033 estimator when codex emits none | `scripts/agent_call.py` ← `pipeline/cost_estimator.py` (`CostEstimate.cost_usd`/`codex_tokens`) |
| A3 | `cost_source` discriminator + schema 1.1→1.2 | `agent_call.py` `_build_sidecar_v11_payload`/`_SIDECAR_SCHEMA_VERSION` → v1.2; consumers tolerate the field |

**Clarify decisions baked in** (from the spec's amendment Clarifications): try
first-class parse → else estimate; `cost_source ∈ {"runtime","estimated","none"}` (spec
FR-028C literals — `"runtime"` is generic so it also fits cursor-agent/052; the earlier
`"codex"`/`"estimate"` draft is retired); bump schema to `1.2` (additive).

**Requirement map**: A1+A2 → FR-028A (capture) + FR-028B (no silent `$0`); A3 → FR-028C.

## Phase-0 findings (spec→code reconciliation)

- **F1** — cost capture is claude-only. `agent_call.py:372-376` (claude stream-json
  cmd), `:799-808` (`_apply_stream_event` reads `total_cost_usd` + usage). No codex
  path → `:852` `cost_usd = stream.cost_usd if stream else 0.0` yields `0.0` for codex.
- **F2** — the estimator already exists. `pipeline/cost_estimator.py` returns
  `CostEstimate{cost_usd, codex_tokens, estimation_method}` (spec-033, pre-dispatch,
  "never underestimates"). The amendment reuses it as the A2 fallback value (post-hoc:
  the same estimate that gated the call now backstops its telemetry).
- **F3** — the sidecar is versioned + centralised. `_SIDECAR_SCHEMA_VERSION` +
  `_build_sidecar_v11_payload` (`cost_usd`/`tokens_in`/`tokens_out`) +
  `_emit_sidecar_v11` are the single write path; adding `cost_source` + bumping to
  `1.2` is one localised change. The 028 batch-path + collision logic is unaffected.
- **F4 (residual unknown)** — *does codex emit a parseable per-call cost?* Unverified
  (mirrors the spec-052 cursor-agent Q1). The design is robust regardless: if yes →
  `cost_source: "runtime"`; if no → `cost_source: "estimated"`; only a total failure to
  estimate yields `cost_source: "none"` (and a WARNING). A1 is implemented as a
  best-effort parser that no-ops cleanly when codex output carries no cost.

## Constitution Check (v1.4.0)

- **IV. Agent-Script Separation** ✅ — cost capture is deterministic wrapper logic, no
  agent self-assessment.
- **V. Offline-First / no deps** ✅ — estimator is stdlib (`tiktoken` only via the
  existing optional `[budget]` extra; default path is the stdlib p95 history).
- **I/II/III** ✅ — no gate semantics change; tests-first; sidecar write unchanged in
  ordering.
- **Ask-First**: sidecar `schema_version` bump (`1.1→1.2`) is additive (consumers use
  `.get()`); flagged for the record, authorised by the amendment Clarifications.

**Gate: PASS.**

## Files touched

```text
scripts/agent_call.py                         # A1 _codex_cost_from_output; A2 estimator fallback; A3 cost_source + v1.2
src/research_framework/pipeline/cost_estimator.py  # (read-only) reused for A2 fallback value
tests/scripts/test_agent_call_codex_cost.py   # A1/A2/A3: parsed / estimated / none + cost_source + schema 1.2
tests/pipeline/test_dispatch_telemetry_cost_source.py  # total_cost_usd reflects estimated codex spend; field tolerated
```

> Sidecar contract: update the 028 sidecar schema reference to `1.2` (additive
> `cost_source`). No new contract file — extends the existing 028 sidecar shape.

## Sequencing

1. A3 first — add `cost_source` + bump `_SIDECAR_SCHEMA_VERSION` to `1.2` (the shape
   everything writes).
2. A2 — wire the `cost_estimator` fallback into `_write_dispatch_sidecar_for_result`
   for non-claude runtimes; `cost_source: "estimated"`.
3. A1 — best-effort `_codex_cost_from_output`; on success overwrite with
   `cost_source: "runtime"`. Tests for all three branches + the GA-005 (spec 063)
   consumer.
