# Research: Spec 028 — Dispatch Telemetry

**Date**: 2026-05-26  
**Status**: All planning unknowns resolved (spec clarifications 2026-05-26 + codebase audit)

---

## R1 — Atomic-write semantics for sidecars (macOS + Linux)

**Decision**: Write to a temp file in the target directory, then `os.replace(tmp, final)`.

**Rationale**: POSIX `rename(2)` / `os.replace` is atomic when source and destination are on the same filesystem. Sidecars are small JSON blobs; a crash mid-write must not leave a half-valid file that breaks `_sum_sidecar_costs` or cap math. Current `_write_cost_sidecar` uses direct `path.write_text` — upgrade both dispatch and CLI paths for consistency.

**Alternatives considered**:
- *Direct write (status quo)* — rejected; torn reads possible under concurrent inspection (rare but cheap to fix).
- *fcntl file locking* — rejected; overkill for best-effort telemetry; constitution favors simplicity.
- *Append-only log* — rejected; FR-005/FR-006 require discrete per-call files for glob summation.

---

## R2 — Where per-call sidecars live in the cycle layout

**Decision**: All v1.0 cost telemetry under `<vault>/_pipeline/cycles/cycle-NNN/agent-calls/` with three filename families:

| Family | Pattern | Producer |
|--------|---------|----------|
| Per-call (first) | `{stage}.json` | `dispatch()` first invocation |
| Per-call (retry / repeat) | `{stage}-2.json`, `{stage}-3.json`, … | `dispatch()` FR-005 / FR-012 |
| Per-batch CLI | `{stage}-batch-{B}.json` (B 1-indexed) | `research.py` note-writer loop (FR-006) |

Legacy flat files `cycle-{NNN}-scout.cost.json`, `cycle-{NNN}-research.cost.json` are **retired** — not read by `_sum_sidecar_costs` after this spec ships.

**Rationale**: Spec 025 `llm-dispatch.contract.md` §3 already documents `agent-calls/{stage}.json`; FR-006 extends the same directory for batch entries so one glob + one parser serves cap math and spec 033.

**Alternatives considered**:
- *Keep flat `*.cost.json` for CLI, agent-calls for dispatch only* — rejected; dual paths caused the production overwrite bug and forked parsers.
- *Append-list in one JSON file* — rejected in clarification session 2026-05-26 (same schema + numeric/batch suffix files instead).

---

## R3 — Refactor `_cycle_helpers` cost summary vs sidecar reads

**Decision**: **No in-memory cost accumulator refactor required.** `_sum_sidecar_costs` and `_append_budget_log` already read filesystem sidecars post-cycle; implementation changes the glob from `cycle-{N}-*.cost.json` to `cycle-{N}/agent-calls/*.json` with v1.0 field names (`tokens_in` not `input_tokens`). `run_report.py` cost section must follow the same glob (currently mirrors old pattern at lines 163–164).

**Rationale**: Orchestrator never cached per-call costs in RAM — only sums on disk. The bug is write-path collision + zeroed dispatch fields, not a missing accumulator.

**Alternatives considered**:
- *Thread-local dispatch registry flushed at quality-report* — rejected; adds state coupling across steps; sidecars are already the contract for cross-process CLI + in-process dispatch.
- *Quality-report embeds full cost breakdown* — out of scope; quality report may reference totals only.

---

## R4 — Test-tier placement (ADR-0008)

**Decision**:

| Concern | Tier | Marker / location |
|---------|------|-------------------|
| Sidecar JSON schema + required fields | 2 — contract | `tests/scripts/test_agent_call_sidecar_v1.py` (new, name in tasks) |
| `_allocate_sidecar_path` monotonic suffix | 2 — unit | same module |
| Two `dispatch()` → two files | 3 — integration | mock subprocess / fake agent |
| Multi-batch `_sum_sidecar_costs` | 3 — integration | fixture vault with 2+ batch sidecars |
| `dispatch()` wired from plan_narrator | 4 — component | extend existing `test_plan_narrator.py` |
| Real claude cost within 5% of CLI | 2/3 + `live_llm` | opt-in only (SC-001) |
| Full cycle budget cap mid-batch (SC-005) | 3 — integration | fake-agent costs injected via sidecar fixtures |

**Rationale**: Matches decision tree in `docs/testing-strategy.md` — don't pay tier-5 wall-clock for pure path/schema logic. Tier-5/6 only if a full `run_cycle_steps` regression is needed for SC-005 (tasks to decide).

**Alternatives considered**:
- *Tier-5 e2e for every FR* — rejected; expensive; FR-008 satisfied by lower tiers + targeted integration.
- *Recorded stream-json fixtures at tier-2* — acceptable optional enhancement for dispatch parser; not mandatory if unit tests feed synthetic stdout.

---

## R5 — Stream-json reuse between CLI and `dispatch()`

**Decision**: Extract a shared internal function (e.g. `_consume_claude_stream(stdout_iterable) -> StreamCostResult`) from `_run_claude_with_cost` (lines 507–579). Both CLI and `dispatch()` call it; map fields to sidecar v1.0 (`tokens_in`/`tokens_out`, not CLI legacy `input_tokens`).

**Rationale**: FR-001 explicitly forbids re-implementation; SC-001 depends on identical parsing.

**Alternatives considered**:
- *Shell out to CLI `main()` from `dispatch()`* — rejected; double subprocess, breaks in-process fake-agent interception.
- *Duplicate parser in `dispatch()`* — rejected by FR-001.

---

## R6 — `agent_kind` detection (replaces `cost_usd == 0.0` heuristic)

**Decision**: Set `agent_kind: "fake"` when the resolved runtime is the vault fake-agent shim (`tests/_helpers/fake_agent.py` copy or `agent` field `fake` in sidecar); otherwise `"real"`. Timestamp branch keys off `agent_kind`, not cost.

**Rationale**: FR-002/FR-004; real claude runs can legitimately report `cost_usd: 0.0` on failure before `result` event (FR-011 partial telemetry).

**Alternatives considered**:
- *Environment flag `RESEARCH_FRAMEWORK_FAKE_AGENT=1`* — possible implementation detail; not part of contract.
- *Keep cost heuristic with exception for failures* — rejected; clarification explicitly removed it.

---

## R7 — Sidecar path allocator algorithm

**Decision**: On write, list `cycle_dir/agent-calls/{stage}.json` and `{stage}-*.json`; parse numeric suffix from `{stage}-(\d+)\.json` (exclude `-batch-` pattern); next path is `{stage}.json` if absent, else `{stage}-{max+1}.json` where first repeat is `-2` (FR-005: first call unsuffixed, second is `-2`).

**Rationale**: Matches spec 025 contract text and clarification Q3 (uniform suffix for quality-report retries).

**Alternatives considered**:
- *In-memory counter on `dispatch()`* — rejected; fails across CLI subprocess boundaries; filesystem is source of truth.
- *UUID filenames* — rejected; breaks human operability and spec 033 consumption.

---

## Open items for `/speckit.tasks` only

1. Exact fake-agent detection predicate in `agent_call.py` (binary name vs settings vs env).
2. Whether SC-005 needs a new tier-3 test or extends an existing budget-cap test.
3. Grandfather period: do we delete/read legacy `*.cost.json` for one release or hard-cut (recommend hard-cut + CHANGELOG breaking note in implementation PR).

---

## rc3 amendment — F4 finding: does codex emit a parseable per-call cost? (T008)

**Question** (plan-rc3-amendment F4 / mirrors spec-052 cursor-agent Q1): does the
`codex exec` runtime print a machine-parseable per-call cost/token signal the way
claude's `stream-json` emits a terminal `result` event with `total_cost_usd`?

**Finding (2026-06-05): No reliable, documented signal.** Unlike claude
(`--output-format stream-json` → terminal `{"type":"result","total_cost_usd":…,
"usage":{…}}`), `codex exec` writes its agent output to stdout as prose/JSON-the-model-
chose, with **no contractual cost envelope**. The enterprise codex subscription used
for the rc runs is flat-rate, so codex has no incentive to surface per-call dollars.
Any "cost line" would be model-emitted, not runtime-guaranteed — i.e. unreliable.

**Decision — best-effort parse, estimator-backed (implemented)**:
- **A1** `_codex_cost_from_output(stdout)` scans for the *robust, parseable* case
  only: a standalone JSON line carrying `total_cost_usd` (or `cost_usd`), optionally
  with `usage.{input,output}_tokens` / `tokens_in`/`tokens_out`. On a hit →
  `cost_source: "runtime"`. It **no-ops cleanly** on arbitrary prose (the common case).
- **A2** when A1 misses, the spec-033 `cost_estimator.estimate_dispatch(...)` value
  stands → `cost_source: "estimated"` (never a silent `$0`).
- **A3** total estimate failure (e.g. vault settings missing `pipeline.max_cycles`/
  `budget_usd`) → `cost_source: "none"` + a `WARN`.

This is forward-compatible: if a future codex (or cursor-agent, spec 052) ships a real
cost envelope, teaching A1 to read it upgrades those calls to `"runtime"` with no
schema change (the field already exists at v1.2).
