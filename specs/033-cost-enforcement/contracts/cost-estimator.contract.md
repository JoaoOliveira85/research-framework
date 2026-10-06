# Contract: Pre-dispatch cost estimator (two-tier)

**Status**: Locked at spec 033 plan time (2026-05-26)  
**Post-dispatch actuals**: [`specs/028-dispatch-telemetry/contracts/sidecar-v1.contract.md`](../../028-dispatch-telemetry/contracts/sidecar-v1.contract.md) — field `cost_usd`  
**Implementation module**: `src/research_framework/pipeline/cost_estimator.py`

---

## 1 — API surface

```python
@dataclass(frozen=True)
class DispatchEstimate:
    cost_usd: float           # Conservative USD estimate
    codex_tokens: int         # tokens_in + tokens_out estimate for codex dispatches
    estimation_method: str    # "p95_history" | "tiktoken" | "default_ceiling"
    vendor: str               # "claude" | "codex" | "local"

def estimate_dispatch(
    *,
    vault_dir: Path,
    cycle_num: int,
    stage: str,
    prompt_text: str,
    agent: str,
    tier: str,
    max_tokens: int,
    limits: LimitsSettings,
) -> DispatchEstimate:
    """Return conservative pre-dispatch estimate. Never underestimates."""
```

---

## 2 — Method selection (priority)

| Priority | Method | Condition |
|----------|--------|-----------|
| 1 | `tiktoken` | `import tiktoken` succeeds (optional `[budget]` extra installed) AND `agent` in (`claude`, `codex`) |
| 2 | `p95_history` | ≥ 3 prior sidecars for `(stage, agent)` in `agent-calls/` across recent cycles (tasks pin window) |
| 3 | `default_ceiling` | Read `cost-estimates.yaml` ceiling for `stage` |
| Fail-closed | `default_ceiling` | Any exception in paths 1–2 |

Log chosen `estimation_method` per dispatch (FR-003 audit).

---

## 3 — `tiktoken` path (optional)

**Dependency**: `pip install research-framework[budget]` → `tiktoken>=0.6`

| Agent | Encoding | Token count | USD conversion |
|-------|----------|-------------|----------------|
| `codex` | `o200k_base` or model-specific (tasks pin) | Exact input tokens from prompt | rate table from settings / agent_call |
| `claude` | `cl100k_base` proxy | Input tokens × `limits.estimator_calibration.claude` (default **1.15**) | same |
| `local` | N/A | Return `cost_usd=0`, `codex_tokens=0` | wallclock cap only |

**Output tokens**: ALWAYS `max_tokens` × configured `output_rate` per tier/agent (dominant cost; intentionally overestimates).

**Codex token cap**: `codex_tokens = tokens_in_est + max_tokens` (conservative).

---

## 4 — `p95_history` path (zero-dep default)

1. Glob historical sidecars: `cycles/cycle-*/agent-calls/{stage}*.json` (tasks define lookback, e.g. last 10 cycles).
2. Collect `cost_usd` where `stage` matches and `status` any.
3. Compute p95; multiply by **1.0** (already historical — tasks may add 1.1 safety factor if needed).
4. For codex token cap: p95 of `(tokens_in + tokens_out)` on codex rows.

If &lt; 3 samples → fall through to `default_ceiling`.

---

## 5 — `default_ceiling` path

Load merged ceilings:

1. `dist-templates/cost-estimates.yaml` (bundled)
2. `<vault>/cost-estimates.yaml` override if present

Return `ceilings[stage]` or global `ceilings.default` or hardcoded framework maximum (tasks pin fallback constant).

---

## 6 — Calibration factor surface

```yaml
# settings.yaml
limits:
  estimator_calibration:
    claude: 1.15
    codex: 1.0
```

Applied **only** on `tiktoken` path for Claude proxy. Documented error band: ~5–15% tokenization mismatch before calibration; factor targets conservative overestimate.

Code defaults: `DEFAULT_ESTIMATOR_CALIBRATION = {"claude": 1.15, "codex": 1.0}`.

---

## 7 — Vendor coverage summary

| Backend | Dollar estimate | Codex token estimate | Operative cap if USD=0 |
|---------|-----------------|----------------------|-------------------------|
| Claude cloud | tiktoken+p95+ceiling | N/A | `cycle_budget_usd` |
| Codex | tiktoken+p95+ceiling | tiktoken+p95+ceiling | `codex_token_budget` + USD |
| Local / `cost_usd: 0` | 0 (excluded from dollar increment) | N/A | `cycle_wallclock_budget_minutes` |

---

## 8 — Integration with `budget_guard`

Pre-dispatch:

```text
estimate = estimate_dispatch(...)
if tally.actual_usd + estimate.cost_usd > cycle_budget_usd: PAUSE dollar
if tally.codex_tokens + estimate.codex_tokens > codex_token_budget: PAUSE codex
if monotonic_elapsed > wallclock_cap: PAUSE wallclock
```

Inclusive rule: equality on dollar/token caps **does not** pause; only strict `>` (research.md §5).

---

## 9 — Test matrix

| Case | Tier |
|------|------|
| tiktoken absent → p95/ceiling | 2 |
| tiktoken present → method tiktoken | 2 |
| calibration merge | 2 |
| fail-closed on tiktoken exception | 2 |
| codex vs claude encoding branch | 2 |

---

## 10 — Forbidden patterns

- Returning estimate below historical p95 without ceiling fallback.
- Mandatory import of `tiktoken` at package import time.
- Anthropic SDK roundtrip for token counting.
- Using agent-reported cost for pre-dispatch check (actuals only post-dispatch via 028 sidecars).

---

## 11 — Whole-cycle projection *(added 2026-09-07 — issue #238)*

`pipeline/budget_preflight.estimate_cycle` asks this estimator for a whole
cycle, before anything dispatches, so `--estimate-only` can answer "is this
safe to leave running unattended". It is a CALLER of §§1-8, not a second
estimator, and the rules that make it trustworthy are:

1. **Same estimator, same inputs.** `estimate_dispatch`, the same
   `cost-estimates.yaml` ceilings and the same p95 history floor. Each stage's
   agent and `max_tokens` resolve through `budget_guard.resolve_dispatch_agent`
   / `resolve_max_tokens` — the precedence the dispatch hook itself uses, moved
   into `budget_guard` from `cycle_runner` for exactly this reason. Two copies
   of an executor precedence become two answers.
2. **Only guard-visible stages.** `scout`, `note_writer`, `verifier` — the
   stages the in-process guard wraps. Pricing a stage the guard never observes
   would put money in the total that nothing would ever stop.
3. **Dispatches, not stages.** `note_writer` runs once per batch,
   `verifier` once per note. Counts come from `coverage.compute_yield_target`
   and `pipeline.note_writer_batch_size` — the inputs the cycle itself uses —
   and are floored at `cycle_yield.min_floor`, because a fully-covered vault
   has no mandatory yield yet can still write notes. §1's conservatism rule
   applies to the projection as a whole: it may overstate, never understate.
4. **The prompt is absent, and that is stated.** Prompts are rendered by the
   cycle that has not run. `prompt_text=""` omits the prompt's own token cost
   — the smallest term, floored by the stage ceiling anyway — and the rendered
   report says so. The terms that decide a pause are identical.
5. **Nothing is dispatched and nothing is written.** No marker, no sidecar, no
   vault mutation; the estimate exists only in the process that printed it.

Forbidden here as elsewhere: a second ceiling table, a second executor
precedence, or a projection that assumes one dispatch per stage.
