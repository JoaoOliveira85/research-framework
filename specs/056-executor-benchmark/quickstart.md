# Quickstart: Executor × Model Benchmarking Harness (Spec 056)

A standalone, manually invoked sweep that answers *"which client/model is best at
which research-framework job, and at what cost?"* It is **not** part of any CI gate
(FR-001) — it costs real money on the live path, so it is opt-in only.

## TL;DR

```bash
# 1. Hermetic dry-run — no live LLM, no spend, fully deterministic (CI-safe).
python scripts/benchmark_executors.py --dry-run

# 2. Live sweep — real API calls. Requires an explicit acknowledgement.
python scripts/benchmark_executors.py --yes --max-usd 2.00

# 3. Full cross-vendor sweep (claude + codex + cursor-agent + ollama).
python scripts/benchmark_executors.py \
  --matrix tests/fixtures/benchmark/benchmark-matrix.full.yaml \
  --yes --max-usd 5.00
```

Reports land under `tests/fixtures/benchmark/_pipeline/benchmarks/<run-id>/`
(`report.json` + `report.md` + per-cell `cells/<task>__<executor>__<model>/`). The
directory is gitignored; prior runs are never clobbered, so deltas are derivable.

## What gets measured

For every `{task × executor × model}` cell:

| dimension | source |
|-----------|--------|
| **quality** | deterministic scorer per task (Principle IV — no LLM judge): scout = `topics_proposed / topics_expected`; note-writer = spec-022 `template_compliance_pct`; verifier = `accept` → 1.0 |
| **cost_usd** | spec-028 sidecar. Measured dollars → `cost_source: sidecar` (ollama is a real **local $0.0**, still `sidecar`). spec-033 fallback → `estimated`. When the runtime emits NO signal and the estimator also fails (sidecar `cost_source: none`) → `null` + `n/a` (never a fabricated $0 — FR-013). |
| **latency_ms** | wall-clock around the `agent_call.py` dispatch |

v1 scores three tasks: `scout`, `note-writer`, `verifier` (contract §2).

## Prerequisites for the live path

- **claude / codex / cursor-agent**: the same CLI binaries + auth the pipeline uses
  (`CLAUDE_BIN` / `CODEX_BIN` / `CURSOR_BIN` env overrides honoured).
- **ollama** (spec 047): a reachable server. Override the endpoint with
  `OLLAMA_BASE_URL=http://localhost:11434` and edit the model tags in
  `benchmark-matrix.full.yaml` to match what your server has pulled.
- A registered-but-undispatchable runtime (missing key, binary absent) ⇒ cell
  `status: skipped` with a reason; an error/timeout ⇒ `status: failed`. The sweep
  always continues (FR-011 / FR-012).

## Cost safety (FR-007 / FR-019 / SC-003)

- **Pre-run**: prints the cell count + an upper-bound cost estimate.
- **TTY**: prompts `y/N` unless `--yes`. Answering `n` dispatches nothing.
- **Headless** (no TTY): refuses unless `--yes` **or** `RF_BENCHMARK_ACK=1`.
- **`--max-usd <float>`**: inclusive cap (spec-033 semantics — equality allowed,
  strict exceed stops). On exceed the sweep stops mid-matrix and still writes a
  **partial** report.

## Scoping a run

```bash
# Just the scout task, just the haiku model:
python scripts/benchmark_executors.py --dry-run --task scout --model haiku

# List prior runs:
python scripts/benchmark_executors.py --list-runs
```

`--task` / `--executor` / `--model` are repeatable and intersect (FR-002).

## Editing the matrix (FR-010)

Add a model ⇒ append one string under `models:`. Add an executor ⇒ add one block
(the runtime must already be dispatchable by `agent_call.py` — i.e. in
`_RUNTIME_ADAPTERS` or `_HTTP_RUNTIMES`, else it's a load error). No code change.

## Determinism (SC-002)

Re-scoring a cell's recorded `stdout.txt` reproduces its `quality` scalar exactly —
the scorers are pure functions of the recorded output (`scoring.rescore_from_artifacts`).
