# Quickstart — running a vault (and the benchmark) on opencode

> Audience: the vault operator. Assumes `opencode` (v1.16+) is installed and that
> its providers are configured/authenticated out-of-band (`opencode auth`,
> `opencode.json`, or env keys), exactly like `cursor-agent` / `gh`.

## 1. Run a vault on a local Ollama model ($0)

```bash
# generate (or re-point) a vault onto the opencode profile
rv generate --spec research.spec.md --output ~/my-vault \
            --settings settings.opencode.yaml

# the profile's default model is a local Ollama model — a full cycle costs $0
cd ~/my-vault
./vault research
```

What you get:
- A normal cycle — scout/note-writer/verifier all write their stage files (opencode
  is agentic; this is what the 047 HTTP primitive could not do).
- Per-call sidecars under `_pipeline/cycles/cycle-NNN/agent-calls/` with
  `executor: opencode`, the resolved `model`, **real** tokens, `cost_usd: 0.0`,
  `cost_source: runtime`.
- The **wall-clock** budget cap is the operative guardrail (dollar cost stays 0).

## 2. Switch to any other provider — config only

Edit `~/my-vault/settings.yaml` (`default_executor.model`, or per-stage
`stages.*.model`):

```yaml
default_executor:
  runtime: opencode
  model: anthropic/claude-sonnet-4-6   # or openai/gpt-…, google/…, openrouter/…
  variant: high                        # optional reasoning effort
```

No framework change. Metered providers re-arm the **dollar** cap; sidecars record
real tokens + an estimator dollar (`cost_source: runtime_tokens`), so you are never
billed blind.

## 3. Containment

Every opencode call runs with `--dir <vault>` — writes stay inside the vault, no
full-disk-access mode. (Override only by passing your own `--dir` in
`default_executor.args`.)

## 4. Benchmark models through opencode (spec 056)

```yaml
# benchmark matrix YAML
tasks: [scout, note_writer]
executors:
  - runtime: opencode
    label: opencode-local-qwen     # optional, for readable reports
    models: [ollama/qwen2.5:7b]
  - runtime: opencode
    label: opencode-sonnet
    models: [anthropic/claude-sonnet-4-6]
```

```bash
python scripts/benchmark_executors.py --matrix my-matrix.yaml
```

Sweeps `{opencode × each model × each task}`, scoring quality (022 calculators) +
cost (028/033) + latency per cell. This is the `live_llm` opt-in surface (never in
CI / the fast loop). Use `--executor`, `--task`, `--model` to scope a cheap subset.

## 5. Verify it's wired (no live calls)

```bash
pytest tests/scripts/test_agent_call.py -k opencode      # adapter + cost class
pytest tests/benchmark/unit/test_matrix.py -k opencode   # guard + label cells
```
