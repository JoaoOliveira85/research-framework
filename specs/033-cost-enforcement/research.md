# Research: Cost Enforcement (Spec 033)

**Date**: 2026-05-26  
**Spec**: [spec.md](./spec.md)  
**Upstream**: [sidecar v1.1](../028-dispatch-telemetry/contracts/sidecar-v1.contract.md), [dispatch protocol](../028-dispatch-telemetry/contracts/dispatch-protocol.contract.md)

---

## 1 — tiktoken vendor-agnosticism and Claude calibration

**Decision**: Optional `tiktoken` path uses OpenAI encodings (`cl100k_base` for Claude proxy, `o200k_base` for Codex when applicable). Claude estimates multiply by `settings.yaml::limits.estimator_calibration.claude` (default **1.15**). Codex uses **1.0**. Output cost always uses `max_tokens × output_rate` (conservative). Local backends skip token dollar math; wallclock cap applies.

**Rationale**: Clarification Q1 explicitly rejected Anthropic SDK roundtrip (latency + extra dep). tiktoken is exact for Codex/GPT tokenization; for Claude it is a documented ~5–15% proxy — calibration factor absorbs under-count risk while keeping Principle V on the default install path.

**Alternatives considered**:
- Anthropic tokenizer API roundtrip — rejected (spec Q1).
- Single encoding for all vendors without calibration — rejected (under-count risk on Claude).
- Mandatory `tiktoken` in core deps — rejected (Principle V).

---

## 2 — Sidecar consumption and running-cost tally

**Decision**: **Lazy refresh with in-memory cache per cycle run.** After each dispatch completes, `budget_guard.refresh_actuals(vault_dir, cycle_num)` globs `cycle-NNN/agent-calls/*.json`, sums `cost_usd` (includes `status: failed` per 028 §4), sums `tokens_in + tokens_out` where `agent == "codex"`, and updates a `CycleSpendTally` dataclass. Pre-dispatch checks use `tally.actual_usd + estimate_usd` against caps. No separate dispatch-memory ledger — sidecars are source of truth (028 dispatch-protocol §3.2).

**Rationale**: Matches 028's `_sum_sidecar_costs` design; avoids drift between in-process counters and filesystem. Cache invalidates on every post-dispatch refresh (O(n) files, n ≪ LLM latency).

**Alternatives considered**:
- Increment-only counter without re-glob — rejected (misses CLI subprocess sidecars written outside `dispatch()`).
- Re-read entire vault history each check — rejected (unnecessary; per-cycle glob sufficient).

---

## 3 — BUDGET_PAUSED vs APPROVAL_REQUIRED marker separation

**Decision**: **Two separate files** at vault root: `_pipeline/BUDGET_PAUSED` and `_pipeline/APPROVAL_REQUIRED`. Mutually exclusive per pause *event* (only one written per stop). A cycle may hit both sequentially (budget pause on dispatch N, later approval pause on dispatch M). `BUDGET_PAUSED.pause_reason` enum is only `dollar_cap_exceeded | wallclock_exceeded | codex_token_cap_exceeded` — never approval. Approval state lives only in `APPROVAL_REQUIRED`. `./vault research --resume` checks **budget marker first**, then approval marker (or single unified reader that returns typed pause kind).

**Rationale**: PR #13 / spec FR-017 — conflating approval into `pause_reason` broke downstream parsers. Separate files preserve clear operator semantics.

**Alternatives considered**:
- Single marker with `pause_reason: approval_required` — rejected (Copilot fix / FR-017).
- YAML markers — JSON chosen for schema validation parity with sidecars.

---

## 4 — TTY detection and headless bypass

**Decision**: `is_tty = sys.stdin.isatty() and sys.stdout.isatty()`. Caps always enforce. Resume/bypass: TTY → interactive y/N for `--force-budget`, `--approve <stage>`, `--approve-all`; headless → non-zero exit + structured JSON payload; requires `RF_FORCE_BUDGET_ACK=1`, `RF_APPROVE_<STAGE>_ACK=1` (stage uppercased, `-` → `_`), or `RF_APPROVE_ALL_ACK=1`. CI may set ack env vars in fixture tests.

**Rationale**: Clarification Q3 — one cap contract, UX adapts. Prevents scripted accidental bypass while keeping operator friction low in terminal sessions.

**Alternatives considered**:
- Different cap values per mode — rejected (Q3).
- Auto-approve in headless — rejected (FR-015 safety).

---

## 5 — Inclusive `<=` cap-check semantics

**Decision**: For dollar cap, pause when `(cumulative_actual_usd + dispatch_estimate_usd) > cycle_budget_usd`. Equality allows dispatch. Zero-cost cache hits (`cost_usd == 0` sidecar) do not advance dollar cap numerator for *estimate* path; actuals still sum post-dispatch. Same pattern for codex tokens: `(cumulative_codex_tokens + estimate_tokens) > codex_token_budget`. Wallclock: `(elapsed_monotonic_seconds > wallclock_cap_seconds)` with equality allowed (convert minutes config once at load).

**Rationale**: Clarification Q5 — operator-configured cap is achievable; avoids epsilon hacks.

**Alternatives considered**:
- Strict `<` cap — rejected (Q5).
- Pause at equality — rejected.

---

## 6 — Wallclock cap placement

**Decision**: `budget_guard.check()` invoked at **start of each stage dispatch boundary** in `cycle_runner.run_cycle_steps` (same hook as dollar/token pre-check). Uses `time.monotonic()` anchored at cycle start (first step entry). Independent of vendor; fires `pause_reason: wallclock_exceeded`.

**Rationale**: FR-012 backend-agnostic backstop for local LLM / runaway loops; monotonic clock immune to NTP skew.

**Alternatives considered**:
- Per-dispatch wallclock only — rejected (cannot catch stuck single dispatch without timeout — timeout is separate).
- Wallclock only in orchestrator outer loop — rejected (cycle_runner is where dispatches cluster).

---

## 7 — Calibration factor storage

**Decision**: Defaults in code (`DEFAULT_ESTIMATOR_CALIBRATION = {"claude": 1.15, "codex": 1.0}`). Operator overrides via `settings.yaml::limits.estimator_calibration` merged shallowly at `VaultSettings` load. Documented in `data-model.md` with confidence note (~5–15% tiktoken proxy error band before calibration).

**Rationale**: Keeps vault-free installs predictable; power users tune per vault without code change.

**Alternatives considered**:
- Vault-only `cost-estimates.yaml` for calibration — rejected (wrong file semantics).
- Hardcode only — rejected (spec FR-003 requires configurable).

---

## 8 — Test-tier placement

**Decision**:
- **Tier-2**: `cost_estimator` methods; `budget_guard` cap inequality; calibration merge; marker JSON schema validation.
- **Tier-3**: atomic marker write; `--resume` detects marker; headless refuses without env; fake-agent fixture cumulative cap.
- **Tier-5**: full cycle pauses at cap, operator bumps cap or `--force-budget`, completes remaining stages.

**Rationale**: ADR-0008 — pure logic lowest tier; CLI/marker lifecycle integration tier-3; pause/resume only in e2e.

**Alternatives considered**:
- Tier-4 only for US1 — rejected (resume is CLI + filesystem integration).

---

## 9 — Estimation method selection and failure closed

**Decision**: At import time, detect `tiktoken` availability if `[budget]` extra installed. Per dispatch: if importable → `tiktoken` path; else if stage has ≥3 sidecar history rows → `p95_history`; else `default_ceiling` from `cost-estimates.yaml`. Any exception → `default_ceiling` for that stage (never underestimate). Log `estimation_method` on pre-dispatch audit row (cycle report / optional sidecar extension deferred to tasks — do not extend 028 schema in 033 without ADR).

**Rationale**: FR-003 two-tier + fail-closed.

**Alternatives considered**:
- Silent fallback to zero estimate — rejected (violates conservative rule).

---

## 10 — Interaction with spec 028 contracts (blocker audit)

**Decision**: No conflicts. 033 reads `cost_usd`, `tokens_in`, `tokens_out`, `agent`, `stage` from sidecar v1.1 required fields. Estimates are pre-dispatch (033-owned); actuals post-dispatch (028-owned). 028 §5.3 explicitly assigns spec 033 as consumer.

**Rationale**: Field names stable; path `agent-calls/*.json` mandatory.

**Alternatives considered**: N/A — hard dependency satisfied on branch `028-dispatch-telemetry-plan`.
