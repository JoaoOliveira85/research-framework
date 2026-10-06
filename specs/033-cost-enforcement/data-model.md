# Data Model: Cost Enforcement (Spec 033)

**Date**: 2026-05-26  
**Input sidecar schema (READ-ONLY — do not redefine)**: [`specs/028-dispatch-telemetry/contracts/sidecar-v1.contract.md`](../028-dispatch-telemetry/contracts/sidecar-v1.contract.md)  
**Marker contracts**: [`contracts/budget-marker.contract.md`](./contracts/budget-marker.contract.md), [`contracts/approval-marker.contract.md`](./contracts/approval-marker.contract.md)  
**Estimator contract**: [`contracts/cost-estimator.contract.md`](./contracts/cost-estimator.contract.md)

---

## External input: AgentCallSidecar v1.1 (spec 028)

Spec 033 **consumes** sidecars at:

```text
<vault>/_pipeline/cycles/cycle-<NNN>/agent-calls/<filename>.json
```

Billing fields used by enforcement (see 028 §2.1 — full schema not duplicated here):

| Field | Use in 033 |
|-------|------------|
| `cost_usd` | Dollar cap actuals (sum all files; include failed) |
| `tokens_in`, `tokens_out` | Codex token cap when `agent == "codex"` |
| `agent` | Distinguish codex vs claude vs local (`cost_usd == 0`) |
| `stage` | Per-stage p95 history bucketing |
| `tier` | Per-tier guardrail warnings (FR-007) |
| `status` | Failed calls still bill (028 §4) |

Local backends: `cost_usd: 0.0` — excluded from dollar-cap numerator for *incremental* spend attribution but still logged; wallclock cap applies (FR-013).

---

## Entities (spec 033 owned)

### `CycleSpendTally` (in-memory, per cycle run)

Ephemeral state inside `budget_guard`; rebuilt/updated after each dispatch.

| Field | Type | Source |
|-------|------|--------|
| `cycle_num` | `int` | Active cycle |
| `actual_usd` | `float` | Σ sidecar `cost_usd` (glob `agent-calls/*.json`) |
| `actual_codex_tokens` | `int` | Σ `tokens_in + tokens_out` where `agent == "codex"` |
| `cycle_started_mono` | `float` | `time.monotonic()` at cycle entry |
| `warn_emitted` | `bool` | FR-008 soft warn at 80% dollar cap |
| `last_estimation_method` | `str` | Last pre-dispatch method id |

**Validation**: `actual_usd >= 0`; monotonic anchor never reset mid-cycle except on new cycle id.

### `BudgetPausedMarker` (persisted JSON)

Path: `<vault>/_pipeline/BUDGET_PAUSED`

| Field | Required | Type | Notes |
|-------|----------|------|-------|
| `schema_version` | yes | string | `"1.0"` |
| `pause_reason` | yes | enum | `dollar_cap_exceeded` \| `wallclock_exceeded` \| `codex_token_cap_exceeded` |
| `cycle_number` | yes | int | ≥ 1 |
| `paused_at` | yes | string | ISO-8601 UTC |
| `paused_stage` | yes | string | Stage that would have dispatched |
| `cumulative_spend_usd` | yes | number | Snapshot at pause |
| `cycle_budget_usd` | yes | number | Config at pause |
| `dispatch_estimate_usd` | yes | number | Estimate that triggered strict exceed |
| `codex_tokens_cumulative` | no | int | When `pause_reason` is codex-related |
| `codex_token_budget` | no | int | When codex cap configured |
| `wallclock_elapsed_seconds` | no | number | When wallclock-related |
| `wallclock_cap_seconds` | no | number | When wallclock-related |
| `blocked_dispatch_preview` | no | string | First 200 chars of prompt (audit) |

**Lifecycle**: Written once per budget pause; cleared on successful resume after cap satisfied or `--force-budget` ack. Atomic write via temp + `os.replace`.

### `ApprovalRequiredMarker` (persisted JSON)

Path: `<vault>/_pipeline/APPROVAL_REQUIRED` — **separate file** from budget marker.

| Field | Required | Type | Notes |
|-------|----------|------|-------|
| `schema_version` | yes | string | `"1.0"` |
| `stage_name` | yes | string | Must match `approval_gates` entry |
| `cycle_number` | yes | int | ≥ 1 |
| `paused_at` | yes | string | ISO-8601 UTC |
| `prompt_preview` | yes | string | Max 500 chars |
| `estimated_cost_usd` | yes | number | Pre-dispatch estimate |
| `cumulative_spend_usd` | yes | number | Running actual + prior estimates policy per tasks |
| `tier` | yes | string | Resolved stage tier |
| `agent` | no | string | Resolved runtime if known pre-dispatch |

**Lifecycle**: Written before gated dispatch; cleared on approve. Reject (`n` / `--reject`) leaves marker + non-zero exit; no silent retry (FR-015).

### `LimitsSettings` (typed slice of `VaultSettings`)

Loaded from `settings.yaml::limits` (and top-level aliases migrated in tasks):

| Key | Type | Default | FR |
|-----|------|---------|-----|
| `cycle_budget_usd` | float \| null | null (disabled) | FR-001/002 |
| `codex_token_budget` | int \| null | null | FR-017 |
| `cycle_wallclock_budget_minutes` | int \| null | null | FR-012 |
| `cycle_budget_warn_at` | float | 0.80 | FR-008 |
| `tier_thresholds` | map[str, float] | {} | FR-007 |
| `estimator_calibration` | map[str, float] | `{claude: 1.15, codex: 1.0}` | FR-003 |

> **Note**: `approval_gates` is NOT a member of `LimitsSettings`. Per `spec.md` FR-014, `approval_gates` lives at the **top level** of `settings.yaml` (`settings.yaml::approval_gates`), not under `limits:`. See `ApprovalGatesSettings` below.

### `ApprovalGatesSettings` (typed slice of `VaultSettings`)

Loaded from `settings.yaml::approval_gates` (top-level list, not nested under `limits:`):

| Key | Type | Default | FR |
|-----|------|---------|-----|
| `approval_gates` (root) | list[str] | `[]` | FR-014 |

### `approval_gates` config

List of stage names (e.g. `note_writer`, `verifier`). Stage names MUST match the snake_case identifiers used by `dispatch()` and by spec 028's sidecar `{stage}.json` filenames. Empty list = feature off. Gate runs **after** budget pre-check passes (both can fire on different dispatches).

### `EstimatorCalibrationTable`

| Vendor key | Default factor | Confidence note |
|------------|----------------|-----------------|
| `claude` | 1.15 | tiktoken `cl100k_base` proxy; ~5–15% tokenization mismatch before factor; factor targets conservative **over**estimate |
| `codex` | 1.00 | tiktoken exact for OpenAI encodings |
| `local` | N/A | No token dollar estimate; wallclock only |

Operator override: `limits.estimator_calibration` shallow-merge over defaults.

### `DefaultStageCeiling` (file-backed)

Path: `<vault>/cost-estimates.yaml` (optional override) or bundled `dist-templates/cost-estimates.yaml`.

```yaml
# Illustrative — tasks pin exact stages
ceilings:
  plan_narrator: 0.35
  scout: 0.80
  research: 1.20
```

Used when `estimation_method == "default_ceiling"`.

---

## State transitions

### Budget enforcement (per dispatch)

```text
[idle] --pre_check--> would_exceed? --yes--> write BUDGET_PAUSED --> exit(1)
                  \--no--> dispatch --> refresh tally --> [idle]
```

### Approval gate (per dispatch)

```text
[idle] --stage in approval_gates?--no--> dispatch
       \--yes--> write APPROVAL_REQUIRED --> exit(1)
[paused] --resume + approve--> clear marker --> dispatch
         \--reject--> stay paused
```

### Resume precedence

```text
--resume --> if BUDGET_PAUSED: validate caps / force-budget
          --> elif APPROVAL_REQUIRED: approve flow
          --> else: normal resume
```

---

## Relationships

```text
settings.yaml (LimitsSettings)
       │
       ▼
budget_guard.check() ──reads──▶ AgentCallSidecar v1.1 (028)
       │
       ├──writes──▶ BUDGET_PAUSED
       └──writes──▶ APPROVAL_REQUIRED

cost_estimator.estimate() ──uses──▶ sidecar history + cost-estimates.yaml + optional tiktoken
```

---

## Cycle report extensions (FR-007, FR-011, FR-015)

Append-only fields on `_pipeline/cycles/cycle-N-report.md` (tasks define exact shape):

- `approval_gates_fired: [{stage, approved, decided_at, decided_by_mode}]`
- `tier_cost_warnings: [{stage, tier, cost_usd, threshold, delta}]`
- `tty_mode: bool`
- `estimation_methods_used: [{stage, method}]`
