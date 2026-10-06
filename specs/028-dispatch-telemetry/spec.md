# Feature Specification: `dispatch()` Telemetry Capture + Sidecar Collision Fix

**Feature Branch**: `028-dispatch-telemetry`
**Created**: 2026-05-22
**Status**: shipped(2026-05-27, PR #28) — SHIPPED 0.4.0 (2026-05-27, impl PR #28 squash `255671c` on main; released as part of the Revival-sprint Wave 1 recovery bump via PR #34). Copilot review fix-up commit `4885f8b` addressed 6 inline findings — `started_at` capture timing, stream-read timeout enforcement, orphan-process kill on `TimeoutExpired`, incremental stream parsing in `_run_claude_with_cost`, per-batch `--batch-index` / `--topic-count` flag plumbing in `pipeline/steps/research.py`, and `status: "ok"` requiring `saw_result` on the stream path. **rc3 amendment SHIPPED 1.0.0rc3 (2026-06-06, PR #126)**: extends telemetry capture to the **codex** runtime (FR-028A..C, defect 3.5; `cost_source` + sidecar schema 1.2) — see "rc3 amendment" section at end of file.
**Input**: User description: "Three Copilot-flagged + audit-confirmed issues in `scripts/agent_call.py::dispatch()`. (#1) `_sidecar_timestamps()` uses cost_usd==0.0 as 'stub call' heuristic, so real claude runs get deterministic timestamps with completed_at == started_at. (#2) `dispatch()` hard-codes cost_usd=0.0, tokens_in=0, tokens_out=0 for successful runs — never populates telemetry. (#7) Sidecar collision: `dispatch()` always writes `agent-calls/{stage}.json`, overwrites if same stage dispatched twice in one cycle. Plus an own-discovery item: per-batch note-writer cost sidecar overwrites — multi-batch cycles under-report spend so the budget cap may fire late or not at all."

## Clarifications

### Session 2026-05-26

- Q: Per-batch sidecar schema — same as per-call sidecar, new batch-summary shape, or append-list? → A: Same schema as per-call sidecar **plus two optional discriminator fields** (`batch_index: int`, `topic_count: int`) populated only for batch sidecars. One schema, one parser; batch entries stay queryable via the discriminator.
- Q: Dispatch failure semantics — write partial telemetry, skip the sidecar, or write a minimal failure marker? → A: **Write the sidecar with `status: "failed"` + `exit_code` + best-effort partial telemetry** (whatever stream data was captured before failure; missing fields default to 0). Observability + correct cap math beats schema purity — a stage that tried-and-crashed-mid-stream still consumed tokens at the Anthropic billing layer and silently dropping that record makes cumulative cost cap fire late.
- Q: Sidecar collision interaction with `_quality_report_guard` retry-after-report — uniform numeric suffix, overwrite, distinct retry family, or sibling retries array? → A: **Uniform numeric suffix.** Each retry triggered by `_quality_report_guard` produces the next `{stage}-N.json` sidecar exactly the same way any other re-dispatch would (FR-005). Retries are real new calls (Anthropic bills them) so they must appear in `_sum_sidecar_costs`. `_quality_report_guard` doesn't change — sidecar naming is `dispatch()`'s concern one layer down.
- Q: Timestamp precision — seconds (status quo), milliseconds (matches `latency_ms`), microseconds, or workaround? → A: **Milliseconds** for real-agent calls — `2026-05-26T17:40:35.123Z`. Aligns `completed_at - started_at` with `latency_ms` for short calls (eliminates the existing internal inconsistency where sub-second calls record `completed_at == started_at` but `latency_ms > 0`). Fake-agent's deterministic sentinels (`2000-01-01T00:00:00Z`, `2000-01-01T00:00:01Z`) keep second-precision form for replay-determinism back-compat — already-committed fixture data depends on the exact string.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Per-call cost telemetry survives the in-process dispatch path (Priority: P1)

The framework's cost-tracking story rests on `agent_call.py`. Today, the CLI path (`main()` in `agent_call.py`) does stream-json parsing to capture `cost_usd`, `tokens_in`, `tokens_out`. The new programmatic `dispatch()` path (added in spec 025 A1/A2 for `plan_narrator` + `probe_retrieval`) hard-codes these to zero. Real-world cycles silently under-report spend on the dispatched stages.

**Why this priority**: Cost tracking is the foundation of the entire cost-efficiency phase (ROADMAP H3). Codex token cap hits 2026-06-01 — within 10 days. Without honest telemetry, budget caps fire late or not at all.

**Independent Test**: Run one fake-agent-backed cycle, then re-run with a real-claude-backed `dispatch()` call (gated by `live_llm` marker). Assert `<vault>/_pipeline/cycles/cycle-NNN/agent-calls/plan_narrator.json` (note the canonical path matches `sidecar-v1.contract.md` — `agent-calls/` is a child of `cycle-NNN/`, NOT a hyphen-joined `cycle-NNN-agent-calls/`; matches Acceptance Scenario 1 below) has non-zero `cost_usd`, `tokens_in`, `tokens_out` after the real run.

**Acceptance Scenarios**:

1. **Given** a vault running a cycle where `plan_narrator` dispatches via `claude`, **When** the cycle completes, **Then** `<vault>/_pipeline/cycles/cycle-NNN/agent-calls/plan_narrator.json` has `cost_usd > 0`, `tokens_in > 0`, `tokens_out > 0`, real ISO timestamps with `completed_at > started_at`.
2. **Given** a fake-agent backed cycle, **When** `plan_narrator` dispatches, **Then** the sidecar has `cost_usd = 0.0`, `tokens_in = 0`, `tokens_out = 0`, deterministic timestamps (preserved for replay determinism).
3. **Given** a cycle's run-summary, **When** the operator reads it, **Then** `total_cost_usd` reflects all dispatched stages' real spend (not just the CLI-path stages).

---

### User Story 2 — Sidecar paths don't collide for batched stages (Priority: P2)

`dispatch()` writes `agent-calls/{stage}.json`. If the same stage dispatches twice in one cycle (e.g., `note_writer` running multiple batches, or a verifier retry on rejection), the second write overwrites the first. The contract text in spec-025 already mentions numeric suffixes (`note_writer-2.json`) but the implementation doesn't honor them.

**Why this priority**: Doesn't bite today because only single-shot stages route through `dispatch()`. Becomes load-bearing the moment `note_writer` or `verifier` migrate. Folding the fix into this spec avoids a "remember to fix this when migrating note_writer" footgun.

**Acceptance Scenarios**:

1. **Given** the same stage is dispatched N times in one cycle, **When** the cycle completes, **Then** the cycle has sidecars `agent-calls/{stage}.json`, `agent-calls/{stage}-2.json`, ..., `agent-calls/{stage}-N.json`, none overwritten.
2. **Given** a single dispatch (most common case today), **When** the cycle completes, **Then** the sidecar filename is just `agent-calls/{stage}.json` (no suffix) — back-compat preserved.

---

### User Story 3 — Per-batch note-writer cost sidecars don't overwrite (Priority: P1)

Separate from `dispatch()`, the CLI-path note-writer batch invocations all write the same `cycle-{N}-research.cost.json`. Multi-batch cycles silently retain only the last batch's cost. The cumulative budget cap can fire late or not at all.

**Why this priority**: Production cost-blindness bug. Affects every cycle that runs multiple note-writer batches (large topics, source-rich fixtures). Combined with US1, this is what truly fixes the cost-tracking story.

**Acceptance Scenarios**:

1. **Given** a cycle with N note-writer batches, **When** the cycle completes, **Then** the cycle output has N per-batch cost sidecars (or an appended-list sidecar) — not one overwritten file.
2. **Given** `_sum_sidecar_costs` is called on the cycle, **When** it sums across batches, **Then** the result equals the sum of all batches' real spend.

---

### Edge Cases

- ✅ **Resolved 2026-05-26 (Clarifications Q2)**: Dispatched calls that fail mid-execution (subprocess crash, timeout, parse error) write a sidecar with `status: "failed"` + `exit_code` + best-effort partial telemetry. See FR-011.
- ✅ **Resolved 2026-05-26 (Clarifications Q3)**: `_quality_report_guard` retry-after-report triggers FR-005's uniform numeric-suffix policy — each retry produces the next `{stage}-N.json` sidecar; all of them count in `_sum_sidecar_costs`. See FR-012.
- ✅ **Resolved 2026-05-26 (Clarifications Q4)**: Real-agent timestamps use millisecond precision (`YYYY-MM-DDTHH:MM:SS.sssZ`); fake-agent's deterministic sentinels keep current second-precision form for back-compat. See FR-003 + FR-004.
- For fake-agent (`agent_kind: "fake"` per FR-002), should the deterministic timestamp scheme stay as-is (`2000-01-01T00:00:00Z`)? *(answered in FR-004 — preserve.)*

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `dispatch()` MUST capture real `cost_usd`, `tokens_in`, `tokens_out` for successful `claude` invocations. The existing CLI-path stream-json parsing logic (`agent_call.py:507-579`) MUST be reused — not re-implemented.
- **FR-002**: `_sidecar_timestamps()` MUST NOT use `cost_usd == 0.0` as the "stub call" heuristic. Instead, an explicit `agent_kind: "fake" | "real"` signal MUST determine timestamp behaviour.
- **FR-003**: For real-agent (claude/codex) invocations, `started_at` and `completed_at` MUST reflect actual wall-clock timestamps with **millisecond precision** (ISO 8601 `YYYY-MM-DDTHH:MM:SS.sssZ`, e.g. `2026-05-26T17:40:35.123Z`). `latency_ms` MUST equal `round((completed_at - started_at).total_seconds() * 1000)` (Python's `datetime.timedelta` has no `total_milliseconds()` method — use `total_seconds() * 1000`; within ±1ms rounding tolerance). Canonical Python writer: `datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")`.
- **FR-004**: For fake-agent invocations, the deterministic timestamps (`2000-01-01T00:00:00Z`, `2000-01-01T00:00:01Z`) MUST be preserved **exactly as currently written** (second-precision form, no millisecond suffix). Already-committed fixture data depends on the exact string; test-replay determinism is a hard requirement. The `agent_kind` discriminator (FR-002) is what tells consumers which precision to expect.
- **FR-005**: When `dispatch()` is called multiple times for the same `stage` within the same cycle, sidecars MUST be written with numeric suffixes: first call `{stage}.json`, second `{stage}-2.json`, etc. No overwrites.
- **FR-006**: The note-writer batch loop in `pipeline/steps/research.py` MUST write per-batch cost sidecars under the **unified per-cycle `agent-calls/` subdirectory**: `<vault>/_pipeline/cycles/cycle-NNN/agent-calls/{stage}-batch-{B}.json` (e.g., `agent-calls/note_writer-batch-1.json` — note the stage name is the canonical `note_writer` underscore form, NOT `research`; B is 1-indexed; stage is the dispatching pipeline stage as emitted by `scripts/agent_call.py --stage <name>`). Per-batch sidecars MUST use the same JSON schema as per-call sidecars — **sidecar v1.1** as locked by `specs/028-dispatch-telemetry/contracts/sidecar-v1.contract.md` (this spec is the v1.0→v1.1 bump from spec 025's original lock; `schema_version: "1.1"` is the only legal value going forward) — with two additional **optional** discriminator fields populated only for batch sidecars: `batch_index: int` (1-indexed batch number within the cycle) and `topic_count: int` (number of topics processed in this batch). The legacy `cycle-{N}-research.cost.json` flat-path artifact is RETIRED — `_sum_sidecar_costs` (FR-007) aggregates from the new per-batch files instead. `scripts/agent_call.py --cost-sidecar` MUST be updated as part of this spec to emit sidecar v1.1 payloads (replacing its current `{runtime, cost_usd, input_tokens, ...}` shape) so the parser is uniform across per-call and per-batch artifacts; tasks.md will own the migration sequence.
- **FR-007**: `_sum_sidecar_costs` (`pipeline/orchestrator.py:952-977`) MUST sum across all per-batch / suffixed sidecars, not just the canonical-named one. Discovery is glob-based against the cycle directory (single-schema parsing for both per-call and per-batch entries); the optional `batch_index` field is the discriminator for telemetry consumers that care to distinguish.
- **FR-008**: A regression test MUST exist for each FR (live_llm or recorded-fake-agent variant): cost-capture, timestamp authenticity, sidecar non-collision, batch-cost summation.
- **FR-009**: The existing single-dispatch behaviour MUST be preserved: when only one dispatch per stage per cycle happens, sidecar filename is `{stage}.json` (no suffix). Backward compat.
- **FR-010**: `AgentCallResult` (the dataclass returned by `dispatch()`) MUST populate `cost_usd`, `tokens_in`, `tokens_out`, `latency_ms` with real values for real-agent calls.
- **FR-011**: When a dispatched call fails (subprocess crash, timeout, non-zero exit code, stream parse error), `dispatch()` MUST still write a sidecar with: `status: "failed"`, `exit_code: int` (the subprocess return code, or a synthetic sentinel like `-1` for timeouts / parse failures), and **best-effort partial telemetry** captured from the stream before the failure — `cost_usd`, `tokens_in`, `tokens_out`, `started_at`, `completed_at` populated from whatever events were seen (missing values default to `0` / `started_at == completed_at`). For successful calls, sidecars MUST set `status: "ok"` and `exit_code: 0` (both fields are REQUIRED on every sidecar — aligns with `specs/_archive/025-simplify-pass/contracts/llm-dispatch.contract.md §3` which treats `exit_code` as required). `_sum_sidecar_costs` MUST include failed-call telemetry in cap-math summation.
- **FR-012**: When `pipeline/orchestrator.py::_quality_report_guard` (or any other retry-after-report mechanism) re-dispatches a stage after a quality-report write, each retry MUST follow FR-005's uniform numeric-suffix policy — `{stage}.json` (first attempt), `{stage}-2.json` (first retry), `{stage}-3.json` (second retry), etc. The retry sidecars MUST appear in `_sum_sidecar_costs` like any other dispatch (retries are real Anthropic-billed calls). `_quality_report_guard` itself does not need to change — sidecar naming remains `dispatch()`'s responsibility.

### Key Entities

- **`AgentCallResult`**: Existing dataclass in `agent_call.py`. Already has the fields; just needs them populated.
- **Per-stage sidecar**: `<vault>/_pipeline/cycles/cycle-NNN/agent-calls/{stage}[-K].json`. **Sidecar schema version `1.1`** — bumped by this spec (was `1.0` in spec 025; v1.1 adds millisecond-precision real-agent timestamps + `status`/`exit_code` REQUIRED fields + the optional batch discriminators below). Canonical contract: `specs/028-dispatch-telemetry/contracts/sidecar-v1.contract.md`.
- **Per-batch sidecar** (new): `<vault>/_pipeline/cycles/cycle-NNN/agent-calls/{stage}-batch-{B}.json` (same `agent-calls/` directory as per-call sidecars; B is 1-indexed). **Schema decided 2026-05-26**: same schema as the per-call sidecar (sidecar **v1.1**, this spec's bump), with two **optional** discriminator fields populated only for batch sidecars: `batch_index: int`, `topic_count: int`. Single-schema parsing keeps `_sum_sidecar_costs` simple; the unified location + discriminator fields make batch sidecars queryable without forking the data model. See Clarifications session 2026-05-26.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a real-claude-backed `dispatch()` call, the resulting sidecar's `cost_usd` is within 5% of the equivalent CLI-path invocation's recorded cost. (Both should reflect the same Anthropic-side billing.)
- **SC-002**: For a fake-agent-backed `dispatch()` call, the sidecar has `cost_usd = 0.0` and deterministic timestamps unchanged from the current implementation.
- **SC-003**: Two `dispatch()` calls for the same stage in one cycle produce two distinct sidecars (no overwrite).
- **SC-004**: A multi-batch note-writer cycle's `total_cost_usd` (from `_sum_sidecar_costs`) equals the sum of all per-batch costs within 0.01 USD.
- **SC-005**: When a cumulative budget cap is enabled in `settings.yaml`, multi-batch cycles correctly halt when crossing the cap mid-cycle (regression test required).

## Assumptions

- The existing CLI-path stream-json parsing is correct (verified by spec 025 SC-011 deferral + ongoing release smoke). Reusing it is safe.
- Real-agent telemetry is the source of truth for billing reconciliation. The Anthropic API returns these in stream-json; we just plumb them through.
- Fake-agent's deterministic timestamps are load-bearing for test replay (specifically tier-6 fake-agent interception test). Preserve.
- The numeric-suffix naming convention (`{stage}-2.json`) doesn't conflict with any existing sidecar consumer. (Audit needed during planning — check `_sum_sidecar_costs` glob patterns.)

## Dependencies

- None on unshipped specs. Builds on `scripts/agent_call.py` + `pipeline/orchestrator.py::_sum_sidecar_costs` + `pipeline/steps/research.py` — all shipped in 0.3.0/0.3.1.

## Acceptance coverage

Draft — evidence cells will be populated by `/speckit.tasks` for
this spec. Listed for the ADR-0008 guard so the spec is accepted
into the queue (the guard refuses any G/W/T-bearing spec without
this section).

| User Story | Evidence |
|------------|----------|
| US1 — Per-call cost telemetry survives the in-process dispatch path | _(deferred to tasks.md — populated by `/speckit.tasks`)_ |
| US2 — Sidecar paths don't collide for batched stages | _(deferred to tasks.md — populated by `/speckit.tasks`)_ |
| US3 — Per-batch note-writer cost sidecars don't overwrite | _(deferred to tasks.md — populated by `/speckit.tasks`)_ |

## Out of Scope

- New cost-enforcement features (hard cycle cap with graceful pause, per-tier guardrails). Spec 033 owns those.
- Reworking `_quality_report_guard` retry-after-report semantics. Spec 030 (quality v3) may revisit.
- Migrating other stages (`note_writer`, `verifier`) to `dispatch()`. Each migration is its own decision; this spec just unblocks them.
- Cross-cycle cost aggregation. Vault-level cost summary already exists (`vault health`) — out of scope for this spec.

---

## rc3 amendment — codex-runtime cost telemetry *(added 2026-06-05 — defect 3.5)*

**Status (amendment):** SHIPPED **1.0.0rc3** (2026-06-06, PR #126, squash `2d217be`)
— rc3 wave (sibling specs 061/062/063; co-amendment to spec 048 v2). FR-028A..C
delivered: codex/non-claude dispatches record a real cost via try-parse-else-estimate
with `cost_source ∈ {runtime,estimated,none}`; sidecar schema `1.1 → 1.2` (additive).
Extended this SHIPPED spec; did not change any 0.4.0 behaviour.

### Why this amendment exists

The 2026-06-05 codebase-vault rc1 evaluation (§3.5) found `run-report.md` and
`budget-log.md` logging **`$0.0000` / 0 tokens for all 6 cycles** under the **codex**
runtime. Budget adherence is therefore unverifiable, and any cost gate (spec 033) is
blind on the runtime we are actually validating rc on. Root cause: cost capture is
**claude-only** — `scripts/agent_call.py` routes `capture and runtime == "claude"` →
`_claude_cmd_with_cost` (incremental stream-json parse, FR US1 above). The codex path
has no equivalent, so both the CLI and `dispatch()` write zeros for codex calls.

### Amendment requirements

- **FR-028A — Codex cost capture.** When `runtime == "codex"`, `agent_call` MUST
  populate `cost_usd` / `tokens_in` / `tokens_out` in the per-call/per-batch sidecar
  from codex's own usage signal when one exists (clarify Q1). If codex emits parseable
  usage → first-class capture mirroring the claude stream parse. If not → fall back to
  the **spec-033 two-tier estimator** (stdlib p95 history; optional `tiktoken`) and
  tag the record so consumers know the precision.
- **FR-028B — No silent `$0`.** A *successful* codex call MUST NOT write
  `cost_usd: 0.0` unless the call genuinely had zero cost. (A `$0` sidecar on a real
  call is exactly the failure mode the spec-063 §4.1 telemetry gate flags; this
  amendment removes its cause rather than just detecting it.)
- **FR-028C — Sidecar `cost_source` discriminator.** Add `cost_source:
  "runtime" | "estimated" | "none"` to the sidecar so the spec-033 gate and the
  spec-063 telemetry gate can distinguish measured spend (`"runtime"`) from an estimate
  (`"estimated"`); `"none"` is reserved for the rare case where even the estimator fails
  (and is accompanied by a WARNING — it is the only path that may legitimately leave a
  `$0`/0-token record). Sidecar schema version bumped accordingly (clarify Q2 — 1.1→1.2).

### Acceptance (amendment)

- `tests/scripts/test_agent_call_codex_cost.py`: a codex call with a usage signal
  populates non-zero `runtime` cost; a codex call without one falls back to an
  estimate + tags `cost_source: "estimated"`; **no successful codex call writes a
  silent `$0`**.
- The existing claude capture path (US1) is unchanged.

### Clarifications (resolved 2026-06-05)

- **Q1 (policy)** — **Try first-class parse, else estimate.** When `runtime ==
  "codex"`, attempt to parse codex's own usage signal; if none is emitted, fall back
  to the spec-033 two-tier estimator and tag `cost_source: "estimated"`. The policy
  degrades gracefully regardless of the empirical answer; **whether codex actually
  emits a parseable signal is confirmed by a quick probe at `/speckit.plan`** (shared
  finding with spec 052 Q1). Either way, **no successful call writes a silent `$0`**
  (FR-028B).
- **Q2** — **Bump the sidecar schema 1.1 → 1.2** to add `cost_source`. A version bump
  (not a silent optional field) keeps the contract honest for the spec-033 / spec-063
  consumers.

Shipped 1.0.0rc3 (2026-06-06, PR #126) — implemented per `plan-rc3-amendment.md` + `tasks-rc3-amendment.md`.

### Cross-references

Spec 033 (cost gate — the consumer that goes blind today), spec 063 §4.1.5 (the
telemetry sanity gate that catches a `$0` regression), spec 052 (Cursor CLI executor —
same cost-signal question; resolving Q1 here informs it).

