# Quickstart: Cost enforcement (spec 033)

After spec 033 ships (requires spec 028 sidecar v1.1), vault operators can cap per-cycle spend, codex tokens, and wall-clock time — with optional manual approval before expensive stages.

## 1 — Configure limits

Edit `<vault>/settings.yaml`:

```yaml
limits:
  cycle_budget_usd: 5.00
  codex_token_budget: 500000        # parallel cap — codex subscription tokens
  cycle_wallclock_budget_minutes: 90  # optional universal backstop
  cycle_budget_warn_at: 0.80        # log at 80% (non-blocking)
  tier_thresholds:
    basic: 0.10
  estimator_calibration:
    claude: 1.15
    codex: 1.0

# Opt-in: pause before these stages until you approve
approval_gates:
  - research
  - verifier
```

Migrate legacy `budget_usd` keys to `limits.cycle_budget_usd` if present (tasks document alias).

## 2 — Optional precision estimates (tiktoken)

Default install uses p95 history + bundled ceilings — **no extra packages**.

For tighter pre-dispatch estimates on cloud backends:

```bash
pip install 'research-framework[budget]'
```

This installs `tiktoken>=0.6`. Without it, the framework stays on the zero-dep path.

## 3 — Run a cycle

```bash
cd ~/Documents/feeds-vault
./vault research
```

Before each dispatch the framework checks:

- `(spent + estimate) <= cycle_budget_usd` (pause only if **strictly over**)
- Codex token parallel cap (if configured)
- Wall-clock cap (if configured)
- Approval gates for listed stages

Honest **actuals** come from sidecars written by spec 028:

```text
_pipeline/cycles/cycle-007/agent-calls/plan_narrator.json
```

## 4 — When the cycle pauses (budget)

You'll see a non-zero exit and:

```text
_pipeline/BUDGET_PAUSED
```

Inspect:

```bash
cat _pipeline/BUDGET_PAUSED | python3 -m json.tool
```

Example:

```json
{
  "schema_version": "1.0",
  "pause_reason": "dollar_cap_exceeded",
  "cycle_number": 7,
  "paused_at": "2026-05-26T19:12:00.123Z",
  "paused_stage": "research",
  "cumulative_spend_usd": 4.9821,
  "cycle_budget_usd": 5.0,
  "dispatch_estimate_usd": 0.42
}
```

## 5 — Resume

Bump the cap in `settings.yaml` if needed, then:

```bash
./vault research --resume
```

If still over budget:

```text
still over budget; bump cycle_budget_usd or pass --force-budget
```

Force (TTY — interactive confirm):

```bash
./vault research --resume --force-budget
```

Headless / CI:

```bash
RF_FORCE_BUDGET_ACK=1 ./vault research --resume --force-budget
```

## 6 — Approval gate pause

When a gated stage is reached:

```text
_pipeline/APPROVAL_REQUIRED
```

Resume in terminal (y/N after cost summary):

```bash
./vault research --resume
```

Headless — explicit stage approval:

```bash
RF_APPROVE_RESEARCH_ACK=1 ./vault research --resume --approve research
```

## 7 — Operator checklist

| Goal | Action |
|------|--------|
| Cap Claude spend | `limits.cycle_budget_usd` |
| Cap Codex tokens (June quota) | `limits.codex_token_budget` |
| Cap local / runaway runtime | `limits.cycle_wallclock_budget_minutes` |
| Tighter estimates | `pip install research-framework[budget]` |
| Gate risky stages | `approval_gates: [...]` |
| Inspect spend | Sum `agent-calls/*.json` → `cost_usd` (028 quickstart) |

## 8 — Quality harness (after ship)

`./build.sh --quality` gains `cost_per_substantive_note` metric (US3) once baselines updated — compares dollars from 028 sidecars against substantive notes added per cycle.
