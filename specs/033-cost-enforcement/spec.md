# Feature Specification: Cost Enforcement

**Feature Branch**: `033-cost-enforcement`
**Created**: 2026-05-22
**Status**: shipped(2026-05-27, PR #31) — SHIPPED 0.4.0 (2026-05-27, impl PR #31 squash on main; second feature shipped under the foreman verification pattern of ADR-0010; released via the Wave 1 recovery bump PR #34). Delivered: per-cycle dollar cap (`limits.cycle_budget_usd`), parallel codex token cap (`limits.codex_token_budget`), wall-clock backstop (`limits.cycle_wallclock_budget_minutes`), opt-in top-level `approval_gates` with separate `_pipeline/BUDGET_PAUSED` and `_pipeline/APPROVAL_REQUIRED` markers; pre-dispatch estimates from bundled `dist-templates/cost-estimates.yaml` with optional `tiktoken` via `pip install research-framework[budget]`; `./vault research --resume` gains `--force-budget`, `--approve`, `--approve-all`, `--reject` with TTY-vs-headless env acks (`RF_FORCE_BUDGET_ACK`, `RF_APPROVE_<STAGE>_ACK`, …); new quality-harness metric family `cost_efficiency` / `cost_per_substantive_note`. **Urgency: shipped before the 2026-06-01 codex token cap** — the framework can now run unsupervised across the cap transition. Pre-implement reconciliation (PR #27) addressed 3 HIGH findings before implementation.
**Input**: User description: "Cost TRACKING is already done: per-stage budget_usd in settings.yaml, per-call cost_usd capture via agent_call.py, cycle-end cost summary. What remains is ENFORCEMENT: hard cycle budget cap with graceful pause (BUDGET_PAUSED marker, resume on `./vault research --resume`), per-tier cost guardrails (flag if `tier: basic` calls drift above $/call threshold), cache-hit-ratio gates, cost-per-substantive-note as a 022 v3 harness metric. Real-world urgency: codex token cap hits 2026-06-01. The 2026-05-13 feeds-vault audit burned $5.85 on a sandbox-failure retry loop that would have looped indefinitely without manual stop. Was Horizon 3 deferred per quality-first arc; now near-term."

## Clarifications

### Session 2026-05-26

- Q: Dispatch estimate computation (FR-003) — Anthropic API roundtrip, heuristic p95 history, local tokenizer, or hybrid? → A: **Two-tier hybrid honoring Principle V, simplified to `tiktoken`-only on the optional precision path.** **Default (zero-dep path)**: heuristic per-stage rolling p95 from `_pipeline/cycles/cycle-NNN/agent-calls/{stage}*.json` history (per spec 028's sidecar v1.1 contract — the `agent-calls/` subdirectory is a child of `cycle-NNN/`, not a hyphen-joined suffix); first-cycle / no-history fallback uses a hardcoded conservative ceiling shipped in `dist-templates/cost-estimates.yaml`. **Optional precision path** (gated on optional extra `pip install research-framework[budget]`): when `tiktoken` is importable at runtime, the framework switches to tiktoken-based pre-dispatch counting for ALL cloud backends — exact for Codex (`cl100k_base` / `o200k_base`), close approximation for Claude (`cl100k_base` proxy, ~5-15% error margin) with a per-vendor calibration factor (`claude: 1.15` default, configurable in `settings.yaml::limits.estimator_calibration`) applied to absorb worst-case under-count. Anthropic-SDK-specific roundtrip explicitly NOT pursued (added complexity for marginal accuracy gain since output is already overestimated via `max_tokens`). Output is ALWAYS assumed = `max_tokens × output_rate` (provably conservative; the dominant cost component for this framework). For local LLM backends, token estimation is irrelevant — wall-clock cap (FR-012) is the operative budget. New FR-003 rewrite + new FR-012 + new FR-013.
- Q: Optional manual approval gate for per-stage user-in-the-loop confirmation (operator-flagged Gap 1 from the 2026-05-26 feeds-vault assessment) — inline `confirm: true` flag, settings list + pause flow, cost-threshold-based, defer to separate spec, or combo? → A: **Settings list + pause flow** (Option B). `settings.yaml::approval_gates: [stage_name, ...]` is the opt-in list; before dispatching any listed stage, framework writes `_pipeline/APPROVAL_REQUIRED` (parallels `BUDGET_PAUSED`) with stage name, prompt preview (first 500 chars), estimated cost, and the cycle's running spend; framework exits non-zero with a clear message. `./vault research --resume` reads the marker, prompts y/N in TTY mode (with full estimated cost + tier visible), proceeds on approval or aborts on rejection. In headless/autonomous mode (no TTY) the resume flow REFUSES to auto-approve — operator MUST pass `--approve <stage>` explicitly (the headless analogue). Reuses the existing pause/resume infrastructure (one less mechanism); opt-in per stage means operators only pay friction for stages they care about; no silent auto-approval in autonomous contexts. New FR-014 + FR-015 + Key Entities entry; cycle report MUST surface "approval_gates_fired" telemetry per cycle.
- Q: TTY vs autonomous cycle behavior — different cap values per mode, TTY-only gates, no central policy, or shared caps with UX-layer adaptation? → A: **Caps enforce identically TTY/headless; resume/force/approve UX adapts per mode** (Option A). The dollar/wallclock caps (FR-002/FR-012) and approval gates (FR-014) ALWAYS engage regardless of TTY status — one contract. What changes is the resume/force/approve UX layer: **TTY mode** (`sys.stdin.isatty() AND sys.stdout.isatty()` — BOTH must be true) emits human-readable summaries + interactive y/N prompts for `--force-budget` / `--approve` / `--approve-all`; **headless mode** (anything else — i.e., `not (sys.stdin.isatty() AND sys.stdout.isatty())`, covering piped stdin, redirected stdout, or both non-TTY) exits non-zero with `--json`-compatible structured payloads and requires an explicit per-flag env var (`RF_FORCE_BUDGET_ACK=1`, `RF_APPROVE_ALL_ACK=1`, `RF_APPROVE_<STAGE>_ACK=1`) to bypass each gate. The headless env-var-gating prevents scripts from accidentally bypassing caps; the TTY prompts give operators a low-friction interactive path. Cycle initiation (`./vault research`) reads settings/caps the same way in both modes — TTY check ONLY affects the resume/force/approve path. New FR-016 codifies the central policy.
- Q: Codex enforcement model — fake $/token conversion, parallel codex_token_budget, wallclock-only, or defer? → A: **Parallel `codex_token_budget` knob** (Option B). Codex bills tokens (monthly subscription with token quota), not dollars — forcing a fake $/token conversion creates phantom precision. `settings.yaml::limits.codex_token_budget: <int>` enforces independently from `cycle_budget_usd`; both caps run in the same cycle; whichever fires first triggers `BUDGET_PAUSED`. Pause marker's `pause_reason` enum extends to `"codex_token_cap_exceeded"`. The dollar cap continues to track Claude spend; the token cap tracks codex spend. Wall-clock cap (FR-012) remains the universal backstop. Out-of-Scope entry "Dollar-converted enforcement for codex" is now Resolved (not deferred, not added — explicitly rejected as a design path). New FR-017 + Key Entities entry.
- Q: Cap exactly hit — pause or continue? → A: **Allow equality, continue** (Option A). The cap check is `<=` (inclusive), not `<` (strict). The cap value the operator configures IS achievable — "$1.00 budget" means "$1.00 spend is OK, $1.01 is not." Pause fires only when the next dispatch would strictly EXCEED the cap (`cumulative_spend + this_dispatch_estimate > cycle_budget_usd`). Matches operator intuition; eliminates epsilon-padding workarounds. Floating-point math makes exact equality rare in practice (typically zero-output cache hits landing on the line) — the inclusive behaviour ensures those edge cases don't spuriously pause. FR-002 updated to make the inequality direction explicit.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Cycle budget cap enforces graceful pause (Priority: P1)

The operator configures `settings.yaml::limits.cycle_budget_usd: 1.50`. A cycle starts. After several stages, cumulative spend approaches the cap. When the next dispatch WOULD cross the cap, the cycle pauses cleanly (writes a `BUDGET_PAUSED` marker, leaves vault state consistent, exits non-zero with a clear message). The operator inspects, decides whether to bump the cap, then runs `./vault research --resume` to continue.

**Why this priority**: Without enforcement, the framework can burn unbounded budget on retries, infinite loops, or unexpectedly expensive prompts. The 2026-05-13 sandbox-failure incident proves this is a real failure mode.

**Independent Test**: Construct a fixture where stages are guaranteed to cumulatively cross a $1.00 cap by stage 3. Run with `cycle_budget_usd: 1.00`. Assert:
- Cycle pauses at stage 3 (or whenever the cap would be crossed)
- A `_pipeline/BUDGET_PAUSED` marker exists with the spend snapshot
- `git status` shows the cycle's partial state preserved
- `./vault research --resume` resumes from where it paused (with whatever fresh cap the operator configured)

**Acceptance Scenarios**:

1. **Given** `cycle_budget_usd: 1.00` configured, **When** a cycle's cumulative spend would cross $1.00 on the NEXT dispatch, **Then** the cycle pauses BEFORE the dispatch (no overshoot).
2. **Given** a paused cycle, **When** operator runs `./vault research --resume` without bumping the cap, **Then** the framework refuses with "still over budget; bump cycle_budget_usd or pass --force-budget".
3. **Given** the operator bumps `cycle_budget_usd` to $2.00, **When** they run `./vault research --resume`, **Then** the cycle resumes from the paused state and completes within the new cap.

---

### User Story 2 — Per-tier cost guardrails detect prompt bloat (Priority: P2)

When a `tier: basic` call drifts above a configurable $/call threshold (e.g., $0.10), it's almost certainly a prompt bloat. Flag the call in the cycle report so the operator knows to investigate.

**Why this priority**: Drift detection. Without it, prompt bloat slowly inflates costs across all cycles. With it, the next cycle report flags the regression.

**Acceptance Scenarios**:

1. **Given** `limits.tier_thresholds.basic: 0.10` configured, **When** a `tier: basic` call costs $0.15, **Then** the cycle report includes a "tier-cost warning" with the stage + cost + delta.
2. **Given** a cycle's report has tier-cost warnings, **When** the operator reviews, **Then** the warnings include enough context (stage, prompt-length, output-tokens) to investigate.

---

### User Story 3 — Cost-per-substantive-note is a quality-harness metric (Priority: P2)

This was originally a candidate 5th metric family in 022 v1 but deferred. As cost telemetry becomes honest (per spec 028), the harness can compute `cost_usd / substantive_notes_added` per cycle. A baseline can be set; regressions flag prompt or model regressions.

**Why this priority**: Quality-with-cost-awareness. A cycle that produces good notes at 2x the cost is regression-worthy.

**Acceptance Scenarios**:

1. **Given** the harness consumes spec 028's honest cost telemetry, **When** a fixture cycle reports, **Then** `cost_per_substantive_note` is a new metric in the report.
2. **Given** a baseline at $0.40/note, **When** a cycle regresses to $0.65/note, **Then** the moderate gate fires FAIL (>15%).

---

### User Story 4 — Cache-hit-ratio gate catches cache-busting changes (Priority: P3)

Spec 020 will introduce per-commit-SHA source caching. A cache-hit-ratio gate ("if any cycle's source-extraction has <80% cache hits after the first run, investigate") detects when an upstream change accidentally invalidates the cache for all subsequent cycles.

**Why this priority**: Pre-emptive bug-catching. Without it, a misconfigured cache key can silently 10x source-extraction cost.

**Acceptance Scenarios**:

1. **Given** spec 020's source cache lives, **When** a cycle's source-extraction has <80% cache-hit-ratio after the first run, **Then** a warning fires.

---

### Edge Cases

- ✅ **Resolved 2026-05-26 (Clarifications Q5)**: Cap check is inclusive (`<=`). Equality passes; pause fires only on strict exceed (`>`). Applies to dollar (FR-002), wallclock (FR-012), and codex token (FR-017) caps. See FR-002.
- What if a single dispatch is BUDGET-IS-FREE (cost=0 from cache hit) — should it count against the cap? (No — by definition.)
- What if the operator wants to FORCE through the cap for a single cycle? `--force-budget` flag with confirmation prompt.
- ✅ **Resolved 2026-05-26 (Clarifications Q3)**: Caps enforce identically in TTY and headless mode (one contract); resume/force/approve UX adapts per mode (TTY = y/N prompt; headless = explicit per-flag env var). TTY detected via `sys.stdin.isatty() AND sys.stdout.isatty()`. See FR-016.
- How does this interact with spec 031's git boundary (the BUDGET_PAUSED state needs to be on a side branch for autonomous cycles)?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `settings.yaml::limits.cycle_budget_usd: <float>` MUST be the canonical configuration knob for hard cycle budget cap. Existing schemas SHOULD migrate to this name.
- **FR-002**: Before every dispatch, the framework MUST check `(cumulative_spend + this_dispatch_estimate) <= cycle_budget_usd`. The inequality is **inclusive** — equality passes (the cap value is achievable). The cycle pauses only when the strict-exceed condition `(cumulative_spend + this_dispatch_estimate) > cycle_budget_usd` is true. The same inclusive-equality rule applies to FR-012 wallclock and FR-017 codex token caps.
- **FR-003**: Dispatch ESTIMATE (vs actual) is the upstream signal. The estimate MUST be conservative (overestimate, never underestimate) per dispatch. **Two-tier implementation honoring Principle V** (no new REQUIRED runtime deps):
  - **Default (zero-dep) path**: per-stage rolling p95 cost from `_pipeline/cycles/cycle-NNN/agent-calls/{stage}*.json` history (the canonical sidecar location locked by spec 028's `sidecar-v1.contract.md` — `agent-calls/` is a child directory of `cycle-NNN/`, NOT a hyphen-joined suffix on `cycle-N`). First-cycle / no-history fallback uses hardcoded conservative ceilings shipped in `dist-templates/cost-estimates.yaml` (one entry per known stage; ceiling is the conservative ceiling chosen per stage — initial values derived from existing test-fixture observations with a safety factor applied; the precise statistic-and-factor is an implementation choice owned by tasks.md and may be revised as real-world telemetry lands). Vault operators MAY override the file per-vault.
  - **Optional precision path** (gated on `pip install research-framework[budget]` extra): when `tiktoken` is importable at runtime, the framework switches to tiktoken-based pre-dispatch counting for ALL cloud backends. For Codex, tiktoken is exact (the encoding IS OpenAI's tokenizer). For Claude, tiktoken with `cl100k_base` is a close approximation (~5-15% error margin in either direction). The framework MUST apply a per-vendor calibration factor (`settings.yaml::limits.estimator_calibration: {claude: 1.15, codex: 1.0}` — defaults shown) multiplicatively to absorb worst-case under-count and remain conservative. Output is ALWAYS assumed = `max_tokens × output_rate` (provably conservative; framework reads `max_tokens` from the dispatch's argv / settings; this is the dominant cost component and dwarfs any input-estimation error).
  - **Anthropic SDK explicitly NOT pursued**: added complexity (API roundtrip latency, SDK dep beyond tiktoken) for marginal accuracy gain since output is already overestimated via `max_tokens`. Reconsider only if real-world data shows tiktoken+calibration is mis-firing the cap.
  - The framework MUST log which estimation method was used per dispatch (`estimation_method: "p95_history" | "tiktoken" | "default_ceiling"`) for auditability.
  - If both default and precision paths fail (e.g., import error mid-dispatch), the framework MUST treat the dispatch as if its cost equals the per-stage ceiling — never underestimate.
- **FR-004**: On pause, the framework MUST write `_pipeline/BUDGET_PAUSED` containing: cumulative spend, paused-stage name, paused-at timestamp, current cycle number, the dispatch that would have crossed the cap.
- **FR-005**: `./vault research --resume` MUST detect `BUDGET_PAUSED`, surface its contents to the user, and refuse to resume unless the budget allows it (or `--force-budget` is passed).
- **FR-006**: `--force-budget` MUST require an interactive confirmation in TTY mode (echo the over-budget amount, prompt y/N). In headless/autonomous mode, refuse without a separate explicit env var.
- **FR-007**: Per-tier cost guardrails: `settings.yaml::limits.tier_thresholds.<tier>: <float>` configures the per-call dollar threshold for each tier. Calls exceeding the threshold MUST be logged in the cycle report (`_pipeline/cycles/cycle-N-report.md`) with stage, cost, delta.
- **FR-008**: Soft-warning threshold MAY be configured (`limits.cycle_budget_warn_at: 0.80`); when cumulative spend crosses 80% of the cap, a non-blocking log entry fires.
- **FR-009**: A new harness metric `cost_per_substantive_note` MUST be computed from spec 028's honest cost telemetry + the existing substantive-note count. Baseline per fixture; moderate gate.
- **FR-010**: A new harness metric `source_cache_hit_ratio` MUST be computed when source modules (spec 020) are in use. Threshold-gated (warning below 80% after cycle 1).
- **FR-011**: Cost summary in cycle-end report MUST distinguish: cumulative spend, per-stage breakdown, per-tier breakdown, cache hits/misses (if 020 lives).
- **FR-012**: `settings.yaml::limits.cycle_wallclock_budget_minutes: <int>` MUST be honored as a wall-clock cap that triggers the same `BUDGET_PAUSED` flow when crossed. Functions as a backend-agnostic safety net: enforces a bound on any cycle (cloud Claude, local Ollama, free-tier Codex, anything else) regardless of whether the dollar cap fires. The pause marker MUST record `pause_reason: "wallclock_exceeded"` (vs `"dollar_cap_exceeded"`) to disambiguate. Default value: unset (no wall-clock cap unless operator opts in).
- **FR-013**: For local-LLM backends (any backend reporting `cost_usd: 0.0` in `agent_call.py`'s telemetry), the framework MUST still record token counts (input + output) for cost-telemetry continuity, but MUST NOT count them against the dollar cap (which would be zero by definition). The wall-clock cap (FR-012) is the operative budget for local-LLM cycles. The cycle report MUST surface the backend type (`cloud` / `local`) per call so operators can audit which calls were free vs paid.
- **FR-014**: `settings.yaml::approval_gates: [<stage_name>, ...]` configures per-stage manual approval gates. Before dispatching any stage listed here, the framework MUST write `_pipeline/APPROVAL_REQUIRED` (parallels `BUDGET_PAUSED` schema-wise) with: `stage_name`, `prompt_preview` (first 500 chars of the prompt to be dispatched), `estimated_cost_usd`, `cumulative_spend_usd`, `cycle_number`, `paused_at`. The framework MUST exit non-zero with a clear message naming the stage requiring approval. Approval gates fire IN ADDITION to (not instead of) the budget cap — both gates can pause the same cycle on different dispatches.
- **FR-015**: `./vault research --resume` MUST detect `APPROVAL_REQUIRED`, surface its contents to the operator, and gate the resumption: in TTY mode, prompt y/N showing full estimated cost + tier; in headless / no-TTY mode, REFUSE to auto-approve and require operator to pass `--approve <stage_name>` explicitly. A `--approve-all` flag MAY exist for batch approvals BUT MUST require a separate explicit env var (`RF_APPROVE_ALL_ACK=1`) in headless mode to prevent accidental blanket approvals. On rejection (`n` in TTY or explicit `--reject <stage>`), the framework MUST leave the cycle in pause state for the operator to inspect; the rejected dispatch MUST NOT silently retry. The cycle report (`_pipeline/cycles/cycle-N-report.md`) MUST log `approval_gates_fired: [{stage, approved, decided_at, decided_by_mode}]` for the cycle.
- **FR-016**: TTY vs headless mode adapts ONLY the resume/force/approve UX, never the caps themselves. The framework MUST detect TTY via `sys.stdin.isatty() AND sys.stdout.isatty()` (both — protects against piped stdin/stdout). **TTY mode**: pause flows emit human-readable summaries + prompt y/N for `--force-budget` / `--approve` / `--approve-all`; defaults to safe behaviour (refuse on bypass until y/N confirmed). **Headless mode**: pause flows exit non-zero with `--json`-compatible structured payloads; each bypass flag (`--force-budget`, `--approve <stage>`, `--approve-all`) REQUIRES its own explicit env var (`RF_FORCE_BUDGET_ACK=1`, `RF_APPROVE_<STAGE>_ACK=1`, `RF_APPROVE_ALL_ACK=1`). Cycle initiation (`./vault research`, not `--resume`) reads settings/caps identically in both modes — the TTY check ONLY affects the resume/force/approve path. The framework MUST log `tty_mode: bool` in the cycle report for auditability.
- **FR-017**: `settings.yaml::limits.codex_token_budget: <int>` MUST enforce a per-cycle codex token quota, INDEPENDENTLY of the dollar cap (FR-002). The framework tracks cumulative codex tokens (input + output) per cycle from `agent_call.py`'s telemetry (per spec 028) and pauses the cycle on `BUDGET_PAUSED` with `pause_reason: "codex_token_cap_exceeded"` when the next codex dispatch's estimated tokens would cross the cap. The dollar cap and codex token cap enforce in parallel — whichever cap fires first triggers the pause. Dispatch estimation for codex MUST use `tiktoken` when the `[budget]` extra is installed (per FR-003) or the heuristic p95 fallback when not. **Pause-marker schema**: `BUDGET_PAUSED.pause_reason` enum is `{"dollar_cap_exceeded", "wallclock_exceeded", "codex_token_cap_exceeded"}` ONLY. Approval-gate pauses are signaled by a SEPARATE marker file (`APPROVAL_REQUIRED` per FR-014/FR-015), not by a `BUDGET_PAUSED.pause_reason`. The two marker kinds are mutually exclusive per pause event but a single cycle MAY traverse both kinds sequentially. Out-of-Scope entry "Dollar-converted enforcement for codex" is explicitly rejected — codex enforcement is token-based, not dollar-converted.

### Key Entities

- **`BUDGET_PAUSED` marker**: A `_pipeline/BUDGET_PAUSED` file (JSON or YAML) containing the pause state.
- **Cycle budget cap**: A float in USD; configured in `settings.yaml`; checked before every dispatch.
- **Per-tier threshold**: A float in USD per call; configured per tier (basic / important / critical).
- **Resume flow**: `./vault research --resume` reads the marker, validates the budget, optionally consults a new cap, continues from the paused stage.
- **Wallclock budget**: A backend-agnostic wall-clock cap (`limits.cycle_wallclock_budget_minutes`). When the cycle's elapsed wall-clock crosses this value, the same pause flow fires with `pause_reason: "wallclock_exceeded"`. Decouples enforcement from any specific pricing model — works for local LLMs, free-tier accounts, and runaway-loop scenarios.
- **Cost estimation method**: Configurable two-tier method. Default zero-dep path: `p95_history` (or `default_ceiling` fallback when no history exists). Optional precision path (gated on `pip install research-framework[budget]`): `tiktoken` for both Claude and Codex (per Clarifications Q1's tiktoken-only simplification — Anthropic SDK roundtrip was explicitly NOT pursued). Per-dispatch method choice (`p95_history` | `tiktoken` | `default_ceiling`) is aggregated into the **cycle report** (`_pipeline/cycles/cycle-N-report.md` — matching FR-007 + FR-015 placeholder convention, field `estimation_methods_used: {<stage>: <method>, ...}`) for auditability — this spec does NOT extend spec 028's sidecar v1.1 schema (the sidecar contract is owned by 028 and closed to 033 extensions; cross-spec field additions would couple the two release trains unnecessarily).
- **`dist-templates/cost-estimates.yaml`**: Hardcoded conservative ceilings per known stage, used as the no-history fallback for FR-003's default path. Vault operators MAY override per-vault.
- **`APPROVAL_REQUIRED` marker**: A `_pipeline/APPROVAL_REQUIRED` file (parallel to `BUDGET_PAUSED`) containing the per-stage approval pause state. Mutually exclusive with `BUDGET_PAUSED` per pause event, but a single cycle MAY traverse both kinds of pauses sequentially.
- **`approval_gates` config + per-stage gate**: An opt-in list in `settings.yaml` enumerating stages that require manual approval before dispatch. Targeted at expensive or risk-bearing stages (note-writer on large batches, verifier on critical notes, codex dispatches with `tier: critical`). Fires IN ADDITION to the dollar/wallclock caps.
- **Codex token budget**: A parallel per-cycle quota in codex tokens (`limits.codex_token_budget`). Decouples codex enforcement from a fake $/token conversion. The dollar cap and codex-token cap enforce independently; both can fire in the same cycle on different dispatches. Maps to codex's real-world billing model (monthly token quota, no dollar invoice).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A cycle with a $1.00 cap and stages that would cumulatively cost $1.50 pauses cleanly within $0.05 of the cap (never overshoots by >5%).
- **SC-002**: A paused cycle resumes with `./vault research --resume` and completes the originally-planned work (no skipped stages).
- **SC-003**: A `tier: basic` call at 1.5x the configured threshold fires exactly one warning in the cycle report.
- **SC-004**: `cost_per_substantive_note` appears in `./build.sh --quality` baselines after spec 028 + this spec ship.
- **SC-005**: The 2026-05-13 sandbox-failure-retry-loop scenario, replayed against the new enforcement, halts in <1 minute when the cap is reached (vs unbounded burn today).

## Assumptions

- Spec 028 ships before this spec, so cost telemetry is honest. (Soft dependency — could ship in parallel with a stub estimate.)
- The dispatch estimate doesn't need to be precise; conservative overestimate is fine.
- The pause/resume semantics match spec 031's git boundary (BUDGET_PAUSED is a special "successful pause" state, not a failure — main branch is clean and the resume mechanism is in-place).
- Codex token cap (2026-06-01) makes this near-term; otherwise it's been Horizon 3 deferred since 2026-05-20.

## Dependencies

- **Hard**: spec 028 (dispatch telemetry) — cost capture must be honest for enforcement to be honest.
- **Soft**: spec 020 (source modules) — `source_cache_hit_ratio` metric needs the cache.
- **Soft**: spec 031 (git boundary) — pause/resume semantics align.
- **Soft**: spec 030 (quality v3) — `cost_per_substantive_note` is a harness metric.

## Acceptance coverage

Draft — evidence cells will be populated by `/speckit.tasks` for
this spec. Listed for the ADR-0008 guard so the spec is accepted
into the queue (the guard refuses any G/W/T-bearing spec without
this section).

| User Story | Evidence |
|------------|----------|
| US1 — Cycle budget cap enforces graceful pause | `tests/pipeline/test_budget_guard.py`, `tests/pipeline/test_budget_markers.py`, `tests/e2e/test_budget_pause_resume.py`, `tests/pipeline/test_budget_guard_sandbox_loop.py` |
| US2 — Per-tier cost guardrails detect prompt bloat | `tests/pipeline/test_budget_guard.py`, `tests/pipeline/test_reporter_cost.py` |
| US3 — Cost-per-substantive-note is a quality-harness metric | `tests/quality/unit/test_cost_efficiency_metric.py` |
| US4 — Cache-hit-ratio gate catches cache-busting changes | `tests/quality/unit/test_cost_efficiency_metric.py` *(blocked on 020 cache metadata until Milestone B)* |

## Out of Scope

- Cross-cycle budget caps (e.g., "$10/day total"). This spec is per-cycle.
- Per-vault budget caps. Use settings.yaml per vault.
- ~~Dollar-converted enforcement for codex (different pricing model). Codex tracking is honest; enforcement may require codex-specific logic.~~ ✅ **Resolved 2026-05-26 (Clarifications Q4)**: codex enforcement is token-based via `limits.codex_token_budget` (FR-017), not dollar-converted. Parallel cap that enforces independently from `cycle_budget_usd`.
- Automatic prompt-bloat detection / rewriting. Per-tier guardrails fire warnings; humans investigate.

---

## Amendment — a cost preflight, and a verb for the markers *(added 2026-09-07)*

**Status (amendment):** shipped — issues #236 / #237 / #238. Additive: no cap,
no marker schema and no resume branch changes meaning. Companion contract
amendments live in `contracts/approval-marker.contract.md` §5.1a and §8, and
`contracts/budget-marker.contract.md` §5.1.

### FR-018 — `--estimate-only`: price a cycle before it dispatches (#238)

**Today.** `cost_estimator.estimate_dispatch` is asked one dispatch at a time,
from inside a cycle that is already running and already spending. Until issue
#230 seeded real ceilings into the shipped profiles, the first signal an
operator got about a run's cost was the bill.

**Proposed.** `generate --estimate-only` and `cycle --estimate-only` project
the next cycle's spend and exit **without dispatching anything**. The
projection is the guard's own: the same estimator, the same
`cost-estimates.yaml` ceilings, the same p95 history floor, and each stage's
agent and tier resolved through the same precedence the dispatch hook uses
(`budget_guard.resolve_dispatch_agent` / `resolve_max_tokens`, moved there from
`cycle_runner` so both callers read one implementation rather than two
opinions).

It counts **dispatches, not stages**: `note_writer` runs once per batch and
`verifier` once per note, so a total assuming one dispatch per stage would
understate a cycle by an order of magnitude. Counts come from the deterministic
spec-051 yield model and the configured batch size — the same inputs the cycle
itself uses — floored at `cycle_yield.min_floor`, because a fully-covered
vault has no *mandatory* yield but can still write notes, and an estimator
that under-reports is worse than none.

What it cannot know is the prompt: prompts are rendered by the cycle that has
not run yet, so the per-dispatch figure omits the prompt's own token cost —
the smallest term, and one the stage ceiling floors anyway. The terms that
decide a pause are identical.

**Exit code is the verdict, not decoration.** `0` when a
`limits.cycle_budget_usd` resolves; **`2` when none does**, because the
question the preflight answers is "is this safe to leave running unattended",
and a run with no ceiling is not — nothing would stop it, whatever it cost.
The estimate is printed either way: a refusal that withholds the number it
refused over is useless.

**Acceptance**: `tests/cli/test_estimate_only.py` — every guard-visible stage
priced at its ceiling; dispatch counts projected from the yield model and
batch size; a disabled verifier omitted; the projection floored; the resolved
cap and an over-cap projection both reported; the vault tree byte-identical
after a run; `run_cycles` / `run_single_cycle` never called; exit 2 with no
cap; and a stable JSON shape.

### FR-019 — `pause show | clear` (#237)

**Today.** `budget-marker.contract.md` §5 has listed "operator aborts cycle
(explicit cleanup command)" as a clear condition since this spec was planned,
and nothing implemented it. Abandoning a paused cycle meant deleting
`_pipeline/BUDGET_PAUSED` by hand, and no verb would first say what the marker
held — which stage stopped, what the blocked dispatch was about to cost, how
much the cycle had already spent.

**Proposed.** A `pause` verb with two subcommands and deliberately different
temperaments:

- `show` is a **read-only inspector** and never fails on the thing it exists to
  diagnose. A marker this build cannot parse is reported as such (path, error,
  and what to do) and the verb still exits 0 — failing there would take the
  diagnostic away at the moment it is needed. `--json` gives `status` and the
  fleet view something to render.
- `clear` **destroys operator state**, so it never happens by accident: a TTY
  gets the marker rendered and a y/N; headless requires `--yes`. `--marker
  budget|approval|all` selects. It is also the one sanctioned way to remove a
  marker this build cannot read — `budget_resume` deliberately refuses to
  (resuming over an unreadable pause would drop whichever cap stopped the run),
  which had left that state with no way out at all.

`show` renders exactly the fields the resume path re-checks. A `show` with its
own field list would be a second reader of the same state, and would drift.

**Clearing an approval pause records NO decision.** `approval-decisions.json`
is the record of verdicts an operator reached (approval-marker.contract.md
§6.1); walking away from a gate is not a verdict, and writing
`approved: false` would put a decision in the cycle report that nobody made.

**Acceptance**: `tests/cli/test_pause_verb.py` — registration and a callable
handler; every re-checked field rendered; read-only; both markers; JSON shape
including the unpaused case; an unreadable marker and an unknown
`schema_version` both surfaced without failing; `clear` refused headless
without `--yes`, prompted and honoured "n" on a TTY, selective by `--marker`,
a no-op success on an unpaused vault, able to remove an unparseable marker,
and writing no `approval-decisions.json` row.

### FR-014a — The approval prompt shows what it is buying (#236)

**Today.** `approval-marker.contract.md` §5.1 is two steps and only the second
one existed: "display stage, tier, `estimated_cost_usd`, `cumulative_spend_usd`,
`prompt_preview`", THEN "prompt". The prompt asked an operator to consent to a
paid dispatch while withholding every number that would make consent
meaningful — all of which the marker had already persisted. Q2's own
clarification promised "prompts y/N in TTY mode (with full estimated cost +
tier visible)".

**Proposed.** Render the marker summary before the prompt, on stderr (spec 070
FR6's stream rule: the thing that stopped a run must survive `> run.log`).
Shown before a flag-driven TTY approval too — `--approve` on a TTY is still a
person watching a gate clear. Not shown for `--reject`, which is a decision
already taken.

The summary adds the **projected cycle total** (`cumulative + estimated`),
computed at render time rather than stored: it is a rendering of two fields the
marker already carries, and a derived number in a versioned on-disk schema
would give a later reader two sources for one fact.

The headless refusal body is unchanged. §5.2 step 4 pins
`{"error": "approval_required", "stage": "..."}` and this amendment does not
widen it.

**Acceptance**: `tests/cli/test_approval_prompt_shows_cost.py` — stage, tier,
agent, estimated cost, cumulative spend, preview and projected total all
present before the prompt; on stderr; on the flag-driven TTY path; safe with
the optional `agent` absent; absent for `--reject`; headless body byte-equal to
the contract's.
