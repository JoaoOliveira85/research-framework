# Feature Specification: Executor × Model Benchmarking Harness

**Feature Branch**: `056-executor-benchmark`
**Created**: 2026-06-03
**Status**: shipped(2026-06-08, PR #139) — SHIPPED [Unreleased] (PR #139, squash `88504cd`, 2026-06-08). All impl
tasks (T004–T037) done; 41 hermetic tests + 1 opt-in `live_llm` smoke;
`scripts/benchmark_executors.py` + `src/research_framework/benchmark/` package
(`matrix`/`scoring`/`reporter`/`gating`/`runner`). Outside every CI gate (FR-001);
runtimes validated against `agent_call`'s `_RUNTIME_ADAPTERS ∪ _HTTP_RUNTIMES` so
spec-047 `ollama` + spec-052 `cursor-agent` are dispatchable. Three Copilot review
rounds addressed (cost-provenance fidelity, failure-path stdout capture, per-cell
budget bound). Full doc-sync (CHANGELOG/ROADMAP/CLAUDE.md/issues) batched into the
rc5 release sync.
**Input**: User description: "With these developments I think we have all we need to benchmark multiple different clients and models to see which is better and which is better at which job. Since vendors are always coming up with new models and model versions it'd be nice to have a couple of tests focused only on comparing different clients (claude code, cursor agent, codex, local instance of Ollama, etc) and different models per client (sonnet, opus, haiku, etc) at the different tasks the research framework [does] so that we can compare how they stack against each other. Preferably also including a cost comparison. It'd be nice if this was an isolated script (that would be incrementally updated with new releases) that could be run at any time by the user."

> **Origin**: `docs/TODO.md` → "Open ideas (un-triaged)" → *Executor × model
> benchmarking harness* (added 2026-06-03). This spec is the live home; the
> TODO entry is annotated `(now spec 056)` and should be deleted when 056 ships.

## Overview

The framework can now dispatch pipeline work to multiple **executors** (clients
such as claude-code, codex, and — per spec 052 — cursor-agent, plus a future
local Ollama runtime), each able to run multiple **models** (e.g. sonnet / opus /
haiku, codex effort tiers, local models). It already captures honest **cost**
telemetry per call (spec 028 sidecars + spec 033 estimator) and can score output
**quality deterministically** (spec 022 metric calculators + the deterministic
verifier). What is missing is a way to point all of that at the same fixed inputs
and ask: **which executor/model is best — and best at *which* job?**

This feature is a standalone, user-runnable **evaluation harness** (a sibling to
the spec-022 quality harness, *not* a hermetic test) that sweeps a
`{task × executor × model}` matrix against a frozen fixture and emits a dated
comparison report of **quality + cost + latency** per cell. Results accumulate
over time so that when a vendor ships a new model, the user can re-run and see how
it stacks up against prior baselines, and the hand-tuned `model-router` heuristics
can be replaced with evidence.

## Clarifications

### Session 2026-06-03

- **Q1 (v1 task set)** → **A**: v1 ships three **scored** tasks — `scout`, `note-writer`, `verifier` — each with a frozen per-task input under the committed fixture. `topic-classifier`, `model-router`, `dfs-research`, `/ask`, and `/write` are **out of v1** (add as v1.1 rows once inputs + deterministic scorers exist); enabling an unsupported task id in config is a config error at load time.
- **Q2 (per-task quality)** → **A**: One primary **quality scalar** per scored task, all deterministic (Principle IV): `scout` → valid scout-report v2 JSON + `topics_proposed` count; `note-writer` → `note_quality.template_compliance_pct` from spec-022 on the produced note; `verifier` → `verifier_pass` (1.0 pass / 0.0 fail) from the deterministic verifier JSON parser on the cell output. Report also carries the raw metric sub-object and `scoring_mode: "deterministic"`; no LLM judge.
- **Q3 (report location & retention)** → **A**: Each run writes under `<fixture>/_pipeline/benchmarks/<run-id>/` (`run-id` = UTC `YYYYMMDDTHHMMSSZ`; never overwrite). Artifacts: `report.json` (machine) + `report.md` (human) + `cells/<task>-<executor>-<model>/` raw outputs. Directory is **gitignored** (like spec-022 `_pipeline/quality/`); operators may manually archive copies. No committed benchmark reports in v1.
- **Q4 (cost gating UX)** → **A**: Reuse spec-033 **semantics**, benchmark-local flags: pre-run estimate + matrix summary; **TTY** (`stdin`+`stdout` isatty) prompts y/N; **headless** requires `--yes` or `RF_BENCHMARK_ACK=1`; optional `--max-usd` cap stops mid-sweep with partial report (inclusive `<=` like 033). No live call before ack.
- **Q5 (repetitions / variance)** → **A**: v1 = **exactly one** live invocation per cell; quality labelled `sample_count: 1`. `--repeat N` deferred to v1.1.
- **Q6 (executor/model enumeration)** → **A**: **Declared** `benchmark-matrix.yaml`: `executors[].runtime` must be a key in `agent_call._RUNTIME_ADAPTERS` (today `claude`, `codex`, `python`; `cursor-agent` when spec 052 lands); `executors[].models[]` is an explicit list per runtime — **not** probed from vendors. Adding a model = one YAML string; adding a runtime = one executor block once the adapter exists.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Compare executors/models across framework tasks (Priority: P1)

As a maintainer, I want to run one command that sweeps a chosen set of framework
tasks across a chosen set of executors and models against a fixed fixture, and
produces a single dated report showing each cell's quality, cost, and latency, so
I can see at a glance which executor/model is best for each task.

**Why this priority**: This is the core value — the comparison itself. Without it
nothing else matters; with just this, the user can already make evidence-based
executor/model choices. It is the MVP.

**Independent Test**: Run the harness over a 2-executor × 2-model × 3-task matrix
against the committed fixture; confirm a report is produced with one row per
(task × executor × model) carrying a quality score, a cost figure, and a latency
figure, plus the inputs needed to reproduce it.

**Acceptance Scenarios**:

1. **Given** a frozen benchmark fixture and a matrix of two executors, two models,
   and three tasks, **When** the user runs the harness, **Then** it produces a
   dated report (human-readable + machine-readable) with exactly one result row
   per matrix cell, each carrying quality, cost, and latency.
2. **Given** a completed run, **When** the user opens the report, **Then** for any
   single task they can rank the executor/model combinations by each of quality,
   cost, and latency independently.
3. **Given** two tasks that favour different models, **When** the user inspects the
   report, **Then** the per-task breakdown makes the "best at which job" answer
   visible (i.e. the winner can differ per task), not collapsed into one aggregate
   score.

---

### User Story 2 - Run safely against real, paid LLM calls (Priority: P2)

As a maintainer, I want the harness to show me an estimated cost and require my
confirmation (or honour a budget cap) before it makes any live calls, and I want to
be able to scope the run to a single task / executor / model for cheap iteration,
so a benchmark sweep never surprises me with a large bill.

**Why this priority**: The harness makes *real, paid* LLM calls. Cost safety and
scoping are what make it usable repeatedly without fear; without them the tool is
too dangerous to run casually. Second only to the comparison itself.

**Independent Test**: Invoke the harness without a confirmation flag and confirm it
prints an estimate and refuses to dispatch; invoke it scoped to a single cell and
confirm only that cell runs; set a budget cap below the estimate and confirm it
stops with partial results preserved.

**Acceptance Scenarios**:

1. **Given** any matrix, **When** the user starts a run without explicit
   confirmation, **Then** the harness prints a cost estimate and a description of
   the matrix and does **not** make any live call until the user confirms.
2. **Given** a scoping selection (one task and/or one executor and/or one model),
   **When** the user runs the harness, **Then** only the selected cells execute.
3. **Given** a budget cap, **When** projected or accumulated spend would exceed it,
   **Then** the harness stops before exceeding the cap and the report still contains
   every cell that completed.

---

### User Story 3 - Keep the matrix current with one-line edits (Priority: P3)

As a maintainer, when a vendor ships a new model or a new client becomes available,
I want to add it to the benchmark by editing a single configuration entry — not by
rewriting the harness — so keeping the comparison current is cheap.

**Why this priority**: The whole motivation is "vendors keep shipping new
models/versions". If extending the matrix is expensive, the table goes stale and
the tool loses its point. Important but only after the harness exists and is safe.

**Independent Test**: Add one new model (or executor) entry to the benchmark
configuration, re-run, and confirm the new combination appears in the report with no
other code change required.

**Acceptance Scenarios**:

1. **Given** a runtime/executor already known to the framework's dispatch layer,
   **When** the user adds one model entry for it to the benchmark configuration,
   **Then** the next run includes that executor/model with no further code change.
2. **Given** a newly added executor that the framework's dispatch layer supports,
   **When** the user enables it in the benchmark configuration, **Then** the next
   run sweeps it across the selected tasks.

---

### User Story 4 - Trend results across model releases over time (Priority: P3)

As a maintainer, I want each run's report retained and dated so I can compare a new
model release against the results captured before it existed, so I can see whether
an upgrade actually improved quality/cost/latency for a given task.

**Why this priority**: Trending is the long-term payoff (regression / improvement
detection across vendor releases), but a single point-in-time comparison already
delivers value, so this rides on top of US1.

**Independent Test**: Run the harness on two different dates (or simulate by
preserving an earlier report), then confirm both reports are retained and a later
run does not overwrite the earlier one, enabling a before/after comparison.

**Acceptance Scenarios**:

1. **Given** a prior dated report exists, **When** the user runs the harness again,
   **Then** a new dated report is created and the prior one is preserved.
2. **Given** two dated reports for overlapping cells, **When** the user compares
   them, **Then** the per-cell quality/cost/latency deltas are derivable.

---

### Edge Cases

- **Executor/model unavailable** (no API key, local runtime not running, model not
  supported by that client): the cell is skipped with a recorded reason; the rest of
  the sweep still completes.
- **Live call errors or times out** for one cell: that cell is recorded as failed
  (with the error) and the sweep continues.
- **Quality cannot be scored deterministically** for a task (no spec-022 calculator
  and no verifier verdict applies): the harness surfaces the raw output artifact and
  flags the cell as *unscored* — it never fabricates a quality number.
- **No cost signal** from a runtime (e.g. a local/free Ollama model, or a client that
  does not report spend): cost is reported as *n/a* (optionally with a token-based
  estimate) rather than crashing or implying zero spend.
- **Budget cap reached mid-sweep**: the harness stops cleanly with all completed
  cells preserved in the report.
- **Non-deterministic model output across repeats**: the report reflects the run(s)
  actually performed and labels quality as a single-sample measurement unless the
  user opted into repetitions (see Assumptions).
- **An executor/model produces output in an unexpected shape** (e.g. malformed):
  treated as a failed-or-unscored cell with the artifact retained, never a crash.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The framework MUST provide a standalone, manually-invoked benchmark
  harness that is **excluded from the automated test suite, the fast loop, the smoke
  gate, and CI**. It is the canonical opt-in live-LLM evaluation surface and MUST NOT
  be reachable by the hermetic test tiers or trip the LLM-dispatch guard.
- **FR-002**: The harness MUST sweep a configurable matrix of
  `{task × executor × model}` and MUST let the user **scope** a run to any subset
  (a single task, a single executor, a single model, or any combination) for cheap
  iteration.
- **FR-003**: Each matrix cell MUST run against a **frozen, committed benchmark
  fixture** (a small fixed vault plus the per-task inputs) so that results are
  comparable across dates and model releases.
- **FR-004**: For each cell the harness MUST capture and report **three measurement
  families**: (a) **quality**, (b) **cost**, and (c) **latency** (wall-clock).
- **FR-005**: Quality MUST be measured **deterministically** — reusing the existing
  spec-022 metric calculators and the deterministic verifier — with **no LLM grading
  the output**. If a task has no deterministic quality measure, the harness MUST
  surface the raw output artifact and mark the cell *unscored*; it MUST NOT fabricate
  a score. (Principle IV.)
- **FR-006**: Cost MUST be derived from the framework's existing per-call cost
  telemetry and estimator (spec 028 / spec 033), not a new parallel accounting system.
- **FR-007**: Before making **any** live call, the harness MUST present a cost
  estimate and the matrix to be run, and MUST require explicit user confirmation
  and/or honour a user-supplied budget cap. A cap breach MUST stop the run with
  partial results preserved.
- **FR-008**: The harness MUST emit a **dated comparison report** in both a
  human-readable form and a machine-readable form, with one entry per
  (task × executor × model) carrying its quality, cost, latency, and status
  (ok / skipped / failed + reason).
- **FR-009**: Reports MUST **accumulate** — a new run MUST NOT overwrite a prior
  dated report — so that results can be trended across model releases.
- **FR-010**: Adding a new executor/runtime or a new model to the matrix MUST be a
  **single configuration edit** that the harness picks up by iterating the
  framework's existing runtime/dispatch registry plus a declared model list — not a
  code rewrite.
- **FR-011**: A cell whose executor/model is **unavailable** MUST be **skipped with a
  recorded reason** and MUST NOT abort the remainder of the sweep.
- **FR-012**: A cell whose live call **errors or times out** MUST be recorded as a
  **failed cell** (with the error captured) and MUST NOT abort the remainder of the
  sweep.
- **FR-013**: A runtime that emits **no cost signal** MUST be reported with cost
  *n/a* (optionally a token-based estimate), never crashing and never implying zero
  spend.
- **FR-014**: Every reported quality number MUST be **reproducible** from the
  captured output artifact — re-scoring the same artifact yields the same score (the
  scoring step is deterministic and separable from the live call).
- **FR-015**: Reported results MUST preserve the **per-task** breakdown (the winner
  may differ per task); the harness MUST NOT collapse tasks into a single aggregate
  score that hides per-job differences. A roll-up MAY be offered in addition.
- **FR-016**: v1 MUST implement exactly the three scored tasks declared in
  [contracts/benchmark-matrix.contract.md](./contracts/benchmark-matrix.contract.md)
  (`scout`, `note-writer`, `verifier`). Other task ids MUST be rejected at matrix
  load time until a future spec revision adds them.
- **FR-017**: Per-task quality MUST follow the scoring table in
  [contracts/benchmark-report.contract.md](./contracts/benchmark-report.contract.md)
  §4 — one primary scalar per task, derived only from deterministic parsers and
  spec-022 calculators; no composite "overall quality" across tasks in v1.
- **FR-018**: Each run MUST write to `<fixture>/_pipeline/benchmarks/<run-id>/`
  with monotonic `run-id`; prior run directories MUST remain untouched (FR-009).
- **FR-019**: Cost gating MUST follow [contracts/benchmark-matrix.contract.md](./contracts/benchmark-matrix.contract.md)
  §3 — estimate before dispatch; TTY confirm or headless `--yes` / `RF_BENCHMARK_ACK=1`;
  optional `--max-usd` mid-sweep halt with partial results.

### Key Entities *(include if feature involves data)*

- **Benchmark matrix cell**: the unit of measurement — a `(task, executor, model)`
  triple that produces one result.
- **Benchmark fixture**: the frozen, committed vault + per-task input set every cell
  runs against; the thing that makes runs comparable over time.
- **Task definition**: a framework pipeline **stage** (v1: `scout`, `note-writer`,
  `verifier`) paired with a frozen prompt/input artifact and a deterministic quality
  measure per FR-017 / contract §4.
- **Executor / runtime**: a dispatch target known to the framework (claude-code,
  codex, cursor-agent, local Ollama, …); enumerable from the existing registry.
- **Model**: a model/effort tier offered by an executor (sonnet / opus / haiku,
  codex effort tiers, a local model name, …).
- **Cell result**: quality score(s) or *unscored* flag, verifier pass/fail, cost
  ($ and/or tokens or *n/a*), latency, and status (ok / skipped / failed + reason),
  plus a pointer to the raw output artifact.
- **Comparison report**: the dated collection of cell results (human-readable +
  machine-readable), retained alongside prior reports.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can produce a side-by-side comparison of at least 2 executors ×
  2 models across at least 3 framework tasks from a single command invocation.
- **SC-002**: Every quality number in a report is reproducible — re-scoring the same
  captured output yields an identical score (100% reproducibility of the scoring
  step).
- **SC-003**: 100% of runs that make live calls are cost-gated: no live call occurs
  without the user having seen an estimate and confirmed, or set a cap.
- **SC-004**: Adding a new model or executor to the sweep requires editing exactly
  one configuration entry and zero other code, verified by adding one and re-running.
- **SC-005**: A sweep in which one cell's executor/model is unavailable or fails
  still completes and reports every other cell (0 sweeps aborted by a single
  unavailable/failed cell).
- **SC-006**: Reports from two different dates are both retained and their per-cell
  deltas are derivable (a later run never overwrites an earlier report).
- **SC-007**: The harness appears 0 times in the fast-loop and smoke-gate runs — it
  is strictly an opt-in evaluation surface.
- **SC-008**: For at least one task, the report demonstrates the per-job thesis —
  the top-ranked executor/model for that task differs from the top-ranked one for
  another task (the tool can surface "best at which job", not just "best overall").
- **SC-009**: v1 matrix runs include all three scored tasks (`scout`, `note-writer`,
  `verifier`) when the user does not scope tasks (FR-016).
- **SC-010**: Hermetic unit/contract tests for the harness modules collect under
  `pytest -m "not e2e"`; zero tests invoke live LLM dispatch without
  `@pytest.mark.live_llm` (ADR-0008).

## Assumptions

- **Eval surface, not a test**: The harness makes *real, paid* LLM calls and is run
  manually by the user at any time. It is a sibling to the spec-022 quality harness,
  never hermetic, and never part of the fast loop, smoke gate, or CI — the canonical
  `live_llm` opt-in surface (ADR-0008).
- **Deterministic quality only** (Principle IV): quality reuses the spec-022 metric
  calculators + the deterministic verifier. No new LLM-judge is introduced; tasks
  without a deterministic measure are reported *unscored*, not graded.
- **Reuse cost infrastructure**: cost reuses spec-028 per-call telemetry sidecars +
  the spec-033 estimator; no new cost-accounting system is built.
- **Matrix axes come from existing surfaces**: executors are enumerated from the
  framework's existing runtime/dispatch registry; the interesting set grows as spec
  052 (cursor-agent) and a future local-Ollama adapter land. With today's runtimes
  (claude + codex) the harness is already runnable.
- **No new runtime dependency** (Principle V): built on the standard library plus
  dependencies the framework already declares.
- **Repetitions**: v1 = one live invocation per cell (`sample_count: 1` in report);
  `--repeat N` is deferred to v1.1 (Q5).
- **Artifact retention**: committed fixture under `tests/fixtures/benchmark/`;
  per-run outputs under `<fixture>/_pipeline/benchmarks/<run-id>/` (gitignored);
  operators archive manually if they want version-controlled history (Q3).
- **Entrypoint**: standalone `scripts/benchmark_executors.py` (not `./vault`); not
  collected by pytest except hermetic tests of parsers/scorers/reporters.
- **Dependencies / build-on**: spec 022 (quality calculators), spec 028 (telemetry),
  spec 033 (cost estimator), spec 052 (cursor-agent runtime — soft dependency for a
  richer matrix), the `model-router` skill (the downstream consumer of the resulting
  table), and spec 047 (backend-agnostic agent layer — would consume this benchmark
  as promotion-gate signal; currently blocked).

## Out of Scope

- Building any new LLM-as-judge or otherwise scoring quality with a model.
- Adding new runtimes/adapters themselves (e.g. the Ollama adapter or cursor-agent
  wiring) — those are separate specs (052 and a future Ollama spec); this harness
  only *consumes* whatever runtimes exist.
- Automatically tuning or rewriting the `model-router` heuristics from the results
  (the harness produces the evidence; acting on it is a follow-up).
- Running in CI or any automated gate, or producing a pass/fail build verdict.
- Continuous/scheduled benchmarking or a hosted dashboard; this is a manual,
  on-demand local tool.
- v1.1 task rows (`topic-classifier`, `model-router`, `dfs-research`, `/ask`,
  `/write`) and `--repeat N` variance mode.

## Acceptance coverage

| User Story | Evidence |
|------------|----------|
| US1 — Compare executors/models across framework tasks | _(deferred to tasks.md — implement-ready 2026-06-03; tests land with /speckit.implement)_ |
| US2 — Run safely against real, paid LLM calls | _(deferred to tasks.md — implement-ready 2026-06-03; tests land with /speckit.implement)_ |
| US3 — Keep the matrix current with one-line edits | _(deferred to tasks.md — implement-ready 2026-06-03; tests land with /speckit.implement)_ |
| US4 — Trend results across model releases over time | _(deferred to tasks.md — implement-ready 2026-06-03; tests land with /speckit.implement)_ |
