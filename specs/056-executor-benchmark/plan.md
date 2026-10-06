# Implementation Plan: Executor × Model Benchmarking Harness (Spec 056)

**Branch**: `056-executor-benchmark` · **Date**: 2026-06-03
**Spec**: [spec.md](./spec.md) · **Contracts**: [contracts/](./contracts/) · **Research**: [research.md](./research.md)
**Status**: planned (post-clarify Q1–Q6). Eval tooling / Horizon.

## Summary

Deliver `scripts/benchmark_executors.py` — a standalone, manually invoked sweep over
a `{task × executor × model}` matrix against a frozen vault fixture under
`tests/fixtures/benchmark/`. Each cell dispatches one real `agent_call.py` invocation
(opt-in `live_llm`), captures 028 sidecar cost + wall-clock latency, scores quality
deterministically (022 note-quality + scout JSON validation + verifier pass bit), and
writes a dated, non-destructive report under
`<fixture>/_pipeline/benchmarks/<run-id>/`. Hermetic tests cover matrix load,
scoring, gating, and report merge without live LLMs.

## Technical Context

- **Language**: Python 3.11+. **Deps**: stdlib + existing (`pyyaml`, `jinja2` if
  report template). **No new runtime dependency** (Principle V).
- **Entrypoint**: `scripts/benchmark_executors.py` — **never** imported from
  `src/research_framework/` pipeline hot paths; **never** collected by default pytest.
- **Package**: `src/research_framework/benchmark/` — `matrix.py`, `runner.py`,
  `scoring.py`, `reporter.py`, `gating.py`.
- **Fixture**: `tests/fixtures/benchmark/` — minimal vault + `benchmark-matrix.yaml`
  + per-task prompts under `tasks/` + `fake_agent_responses/` for hermetic replay.
- **Reuse**: `quality.metrics.note_quality.compute_note_quality_metric`;
  verifier JSON tolerance (ADR-0004); `pipeline.cost_estimator` + 028 sidecar read;
  `scripts/agent_call.py` dispatch subprocess (live path only).
- **Testing**:
  - **Fast loop** (`pytest -m "not e2e"`): `tests/benchmark/unit/*` — matrix,
    scoring, reporter, gating (fake-agent / recorded artifacts).
  - **Excluded**: live matrix sweep (run script manually with API keys).
  - **Optional**: one `@pytest.mark.live_llm` parity test (documented, not in
    `build.sh` / smoke gate).
  - **Guard**: tier-2 test asserts no `tests/` module invokes real dispatch without
    `live_llm` marker (complements existing LLM dispatch guard on `src/`).
- **CI / gates**: **0** references in `build.sh`, `release.yml`, or `pytest -m "not e2e"`
  collection — canonical opt-in eval surface (ADR-0008, FR-001, SC-007).

## Constitution Check

| Principle | Status | Note |
|-----------|--------|------|
| **I** — Script-validated quality | ✅ PASS | Quality from 022 calculators + verifier parser only. |
| **III** — TDD | ✅ PLANNED | Hermetic tests precede `benchmark/` package implementation. |
| **IV** — No LLM self-grading | ✅ PASS | FR-005/FR-017; unscored = explicit flag, never fabricated. |
| **V** — No new runtime dep | ✅ PASS | stdlib + pyyaml (+ optional jinja2 for `report.md`). |
| **X** — Vault git append-only | ✅ PASS | Benchmark fixture `_pipeline/` is gitignored eval workspace; script does not mutate user vaults unless operator passes `--vault` override (default = fixture only). |
| **VIII** — Fixtures are test data | ✅ PASS | `tests/fixtures/benchmark/` committed; run dirs gitignored. |

**Verdict**: PASS — no violations; no Complexity-Tracking entries.

## Project Structure (artifacts this spec produces)

```text
specs/056-executor-benchmark/
├── spec.md
├── plan.md
├── research.md
├── contracts/
│   ├── benchmark-matrix.contract.md
│   └── benchmark-report.contract.md
├── checklists/requirements.md
├── tasks.md
└── analyze-2026-06-03.md

scripts/benchmark_executors.py          # live entrypoint (implementer)
src/research_framework/benchmark/     # testable core
tests/fixtures/benchmark/             # frozen vault + matrix + task inputs
tests/benchmark/unit/                 # hermetic fast-loop tests
```

## Phase 0 — Research ✅

[research.md](./research.md): Q1–Q6 locked; code audit confirms 022/028/033 on
`main`; script placement and hermetic/live split decided (D7–D8).

## Phase 1 — Design ✅

- [contracts/benchmark-matrix.contract.md](./contracts/benchmark-matrix.contract.md):
  YAML schema, v1 task ids, CLI flags, gating rules, runtime validation.
- [contracts/benchmark-report.contract.md](./contracts/benchmark-report.contract.md):
  `report.json` schema, per-task quality §4, cell status enum, retention paths.

## Phase 2 — Task strategy (for `/speckit.tasks`)

**TDD order**: contract fixture tests → matrix loader → per-task scorers → reporter
→ gating → cell runner (fake-agent hermetic) → CLI wiring → marker-isolation guard
→ optional `live_llm` doc test → doc-sync on ship.

**MVP checkpoint**: US1 — 2×2×3 matrix against fixture with fake-agent produces
valid `report.json` + `report.md` (no live spend). US2 adds cost gate tests; US3/US4
are config + retention tests.

## Complexity & Risks

- **Sidecar path drift** — must use `cycle-001/agent-calls/<task>.json` (028 §1).
  *Mitigation*: contract test pins path from a recorded fake sidecar.
- **Note-quality adapter** — 022 metric expects `CycleOutput` list. *Mitigation*:
  thin `SyntheticCycleOutput` builder in `scoring.py` (one note, one cycle).
- **052 cursor-agent** — matrix may list runtime before adapter exists. *Mitigation*:
  load-time skip with `status: skipped`, reason `runtime_unavailable` (FR-011).
- **Cost estimate without history** — first benchmark on a machine. *Mitigation*:
  `dist-templates/cost-estimates.yaml` ceilings per stage (033 FR-003 fallback).
