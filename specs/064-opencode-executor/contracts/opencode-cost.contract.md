# Contract — opencode cost classification (`scripts/agent_call.py::_resolve_cost`)

opencode has **no static cost class**. Classification is per call, by resolved provider.

## Usage extraction (VERIFIED 2026-06-11 — live ollama run)

`opencode run --format json` emits **NDJSON**. Accumulate over every
`type: "step_finish"` event (one per agentic step = one real API call):

```
tokens_in  += part.tokens.input
tokens_out += part.tokens.output
cost_usd   += part.cost          # real $: 0 for local, models.dev pricing for metered
```

`usage` passed to the classifier below is `{tokens_in, tokens_out, cost_usd, n_steps}`
or `None` when zero `step_finish` events were seen (robust to a missing terminal event).

```
_opencode_cost_class(model: str, usage: dict | None)
    -> (cost_usd: float, tokens_in: int, tokens_out: int, cost_source: str)
```

## Rules (in order)

1. **Local provider** (`model` prefix in `local_providers`, default `{"ollama", "local"}`):
   - `cost_usd = 0.0` (measured), `tokens_in/out` = real from `usage`,
     `cost_source = "runtime"`.
   - tokens NOT added to the metered-token cap.
2. **Metered + real dollar** (`usage.cost_usd > 0` — the COMMON case; opencode
   derives it from its models.dev pricing catalog): `cost_usd` = that dollar, real
   tokens, `cost_source = "runtime"`.
3. **Metered + tokens but no/zero dollar** (fallback only): real tokens, `cost_usd`
   = spec-033 estimator, `cost_source = "runtime_tokens"`; tokens count toward the
   metered-token cap; dollar cap gates the estimate.
4. **No usage at all**: `tokens = 0`, `cost_usd` = estimator (prompt-based) or
   `0.0` with `cost_source = "none"` only if the estimator is unavailable — **never
   a silent `$0` with `cost_source = "runtime"`** (FR-007).

## Invariants

- Sidecar schema **unchanged** (1.2); `cost_source ∈ {runtime, runtime_tokens, estimated, none}` — no new literal.
- `executor: "opencode"`, `model: <resolved provider/model>` always populated (FR-008/011).
- `BUDGET_PAUSED` (spec 033) fires on the dollar cap for metered runs and on the
  wall-clock cap for $0 local runs (FR-012).
- `local_providers` is overridable in `settings.opencode.yaml`.

## Tests (tier-2 unit)

- local model → `(0.0, t_in>0, t_out>0, "runtime")`.
- metered, dollar present → `("runtime")` with that dollar.
- metered, tokens only → `("runtime_tokens")`, estimator dollar > 0.
- no usage → never `(0.0, …, "runtime")`; estimator or `"none"`.
- sidecar round-trip: budget guard sums opencode sidecars into the tally
  (regression of the rc3 schema-line footgun — `1.x` accepted).
