# Research & Decisions: Executor × Model Benchmarking Harness (Spec 056)

**Date**: 2026-06-03 · **Stage**: post-clarify (Q1–Q6), pre-implement
**Context**: Drafted from `docs/TODO.md` "Executor × model benchmarking harness".
Sibling to spec-022 quality harness; canonical `live_llm` eval surface (ADR-0008).

## Audit findings (spec ↔ code reconciliation)

| spec claim | reality (2026-06-03) | resolution |
|------------|----------------------|------------|
| Multiple executors | `_RUNTIME_ADAPTERS` = `claude`, `codex`, `python` in `scripts/agent_call.py` | matrix `runtime` must match keys; `cursor-agent` when 052 ships |
| Deterministic quality | spec-022 `REGISTERED_METRIC_FAMILIES` + verifier JSON parser exist | per-task adapters, not full 3-cycle harness |
| Cost telemetry | spec-028 sidecars v1.1 + spec-033 `cost_estimator` shipped | read sidecar after each cell dispatch |
| Principle IV | `tests/_helpers/test_llm_dispatch_guard.py` allowlist **empty** | benchmark script lives under `scripts/`, never imported from `src/` hot path |
| `live_llm` marker | `tests/conftest.py` skips unless `--live-llm` / `LIVE_LLM=1` | harness **script** is not pytest; optional one opt-in parity test only |
| Fake-agent for hermetic tests | `tests/_helpers/fake_agent.py` stage handlers for scout/note_writer/verifier | fixture uses fake-agent shim; scoring tests never call real CLIs |

**Net**: All hard dependencies (022 calculators, 028 sidecars, 033 estimator) are
shipped. Soft: 052 (cursor-agent), 047 (consumer only). No blockers for v1 on
claude+codex.

## Decisions

### D1 — v1 task catalog: scout + note-writer + verifier (Q1)
Three stages with frozen prompts under the committed fixture. **Why**: each has a
deterministic scorer today; `/ask` and `/write` lack a single-shot scored artifact
without new fixture work. **Rejected**: include unscored `/ask` in v1 (violates
FR-005 clarity — report would mix scored and unscored rows in the MVP matrix).

### D2 — One primary quality scalar per task (Q2)
Contract §4 pins the scalar; sub-metrics kept for audit. **Why**: FR-014
reproducibility + unambiguous ranking column. **Rejected**: multi-metric weighted
blend (non-reproducible bikeshed); full 022 3-cycle metrics (wrong granularity).

### D3 — Gitignored `_pipeline/benchmarks/<run-id>/` (Q3)
Mirrors spec-022 `_pipeline/quality/` pattern. **Why**: live-run artifacts must not
pollute git; Principle X applies to vault research, not eval scratch dirs.
**Rejected**: committed reports in-repo (would churn on every maintainer run).

### D4 — 033-aligned gating, benchmark-local CLI (Q4)
`RF_BENCHMARK_ACK=1` / `--yes` / TTY y/N / `--max-usd`. **Why**: operators already
learned 033 resume semantics; separate env prefix avoids accidental reuse of
`RF_FORCE_BUDGET_ACK`. **Rejected**: budget-cap-only without confirm (violates SC-003).

### D5 — Single sample per cell; `--repeat` → v1.1 (Q5)
Report carries `sample_count: 1`. **Why**: keeps v1 cost predictable; variance study
is a follow-up. **Rejected**: default N=3 (3× cost without user opt-in).

### D6 — Declared matrix YAML, registry-validated runtimes (Q6)
`benchmark-matrix.yaml` + load-time check against `_RUNTIME_ADAPTERS`. **Why**:
FR-010 "one-line edit"; probing vendor APIs is flaky and non-deterministic.
**Rejected**: runtime model discovery (breaks offline matrix review).

### D7 — Module placement
`src/research_framework/benchmark/` (matrix loader, cell runner, scorers, reporter)
+ thin `scripts/benchmark_executors.py` CLI. **Why**: hermetic tests import package
modules; script stays the `live_llm` entrypoint (like `agent_call.py`). No new dep.

### D8 — Hermetic vs live split
- **Fast loop**: matrix parse, scoring, report merge, cost-gate logic, fake-agent
  fixture cells — `tests/benchmark/unit/`.
- **Never CI**: `scripts/benchmark_executors.py` live sweep; optional
  `@pytest.mark.live_llm` smoke documented in quickstart only.

## Cross-spec interactions

| spec | role |
|------|------|
| **022** | `compute_note_quality_metric`, coverage/health patterns for adapters |
| **028** | per-cell `agent-calls/<task>.json` sidecar for cost + latency |
| **033** | `cost_estimator` pre-run estimate; cap semantics for `--max-usd` |
| **052** | optional `cursor-agent` runtime row when adapter lands |
| **047** | downstream consumer of benchmark reports (promotion gate); not a blocker |
| **ADR-0008** | `live_llm` opt-in; benchmark script outside pytest collection |

## Determinism / Principle check

- IV: deterministic scorers only ✅
- V: stdlib + existing deps ✅
- III: hermetic tests first ✅
- X: fixture is test data; benchmark dir gitignored — no vault commit requirement ✅
