# Contract: Benchmark Matrix Configuration & CLI

**Spec**: 056 — Executor × Model Benchmarking Harness · **Status**: authored 2026-06-03
(post-clarify Q1, Q4, Q6). Normative for matrix YAML, CLI surface, cost gating, and
runtime validation.

---

## 1. Matrix file

**Path (default)**: `tests/fixtures/benchmark/benchmark-matrix.yaml` (override via
`--matrix <path>`).

```yaml
schema_version: "1.0"
tasks:                          # v1: MUST be subset of §2
  - scout
  - note-writer
  - verifier
executors:
  - runtime: claude             # MUST ∈ agent_call._RUNTIME_ADAPTERS keys
    models:
      - sonnet
      - haiku
  - runtime: codex
    models:
      - default
```

- **`tasks`**: optional override of the default v1 trio; unknown task id ⇒ load error.
- **`executors[].runtime`**: validated at **load** against `_RUNTIME_ADAPTERS` keys.
  Unknown runtime string ⇒ **load error** (typo guard). At **run** time, a registered
  runtime that cannot dispatch (missing API key, binary absent, model rejected) ⇒
  cell `status: skipped` with `reason` (FR-011) — sweep continues.
- **`executors[].models[]`**: opaque strings passed through to the executor config
  (`settings.yaml`-style model field); **not** probed from vendor APIs (Q6).
- Adding a model ⇒ append one string under `models`. Adding an executor ⇒ one block
  after the adapter exists (FR-010).

## 2. v1 task ids (FR-016)

| task id | stage name for `agent_call` | frozen input |
|---------|----------------------------|--------------|
| `scout` | `scout` | `tasks/scout-prompt.txt` |
| `note-writer` | `note_writer` | `tasks/note-writer-prompt.txt` |
| `verifier` | `verifier` | `tasks/verifier-prompt.txt` + `tasks/verifier-draft.md` |

Task ids **not** in v1: `topic-classifier`, `model-router`, `dfs-research`, `ask`,
`write` — rejected at load until a future schema bump.

## 3. CLI surface & cost gating (FR-007, FR-019, SC-003)

```
python scripts/benchmark_executors.py \
  [--fixture <path>]  [--matrix <path>] \
  [--task <id>] [--executor <runtime>] [--model <name>] \
  [--yes] [--max-usd <float>] [--json] [--dry-run]
```

| `--dry-run` | Hermetic path: fake-agent + recorded sidecars only; **no** live LLM (default for unit tests / CI-safe local check). |

| flag / env | behaviour |
|------------|-----------|
| *(default)* | fixture = `tests/fixtures/benchmark/` |
| `--task` / `--executor` / `--model` | scope matrix to subset (FR-002); repeatable |
| pre-run | print matrix cell count + **cost estimate** (033 `cost_estimator` + ceilings) |
| TTY confirm | if `stdin.isatty() AND stdout.isatty()` and not `--yes` ⇒ prompt y/N; **no dispatch on 'n'** |
| headless | if not TTY ⇒ **must** pass `--yes` OR `RF_BENCHMARK_ACK=1` |
| `--max-usd` | after each cell, if `accumulated_usd > max` ⇒ stop; partial report (FR-007) |
| `--json` | stdout summary JSON on completion (machine hook) |

Inclusive cap semantics match spec-033: equality allowed, strict exceed stops.

## 4. Live dispatch rules (FR-001, FR-011, FR-012)

- Invokes `python scripts/agent_call.py` with `--vault <fixture>` per cell; installs
  no fake-agent shim on the live path.
- **Unavailable** runtime/model (adapter error, missing API key): cell
  `status: skipped`, `reason` set; sweep continues.
- **Error / timeout**: `status: failed`, `error` captured; sweep continues.
- Writes 028 sidecar under `<fixture>/_pipeline/cycles/cycle-001/agent-calls/<stage>.json`
  (benchmark uses a fixed `cycle-001` workspace per run).

## 5. Hermetic / CI exclusion (FR-001, SC-007, SC-010)

- This script MUST NOT be invoked from `build.sh`, `release.yml`, or default pytest.
- `src/research_framework/` MUST NOT import the benchmark package on pipeline paths.
- `tests/_helpers/llm_dispatch_allowlist.yaml` MUST remain **empty** — benchmark is
  not an allowlisted exception inside `src/`.
