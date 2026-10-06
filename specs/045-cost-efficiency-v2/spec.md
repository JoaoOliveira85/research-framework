# Feature Specification: Cost-Efficiency v2

**Feature Branch**: `045-cost-efficiency-v2`
**Created**: 2026-05-27 (promoted from `docs/ROADMAP.md` Horizon 3 "Cost Efficiency phase" residue after spec 033 absorbed the enforcement half during Wave 1).
**Status**: planned — DRAFT (full spec; awaiting `/speckit.clarify` on 4 open questions). Post-revival. Soft-blocked by spec 030 (quality harness v3 — needs `cost_per_substantive_note` as a metric).

**Input**: The POLISH layer on top of spec 033 (cost enforcement, shipped 2026-05-27): cache-hit-ratio gates, per-tier cost guardrails, and `cost_per_substantive_note` as a first-class metric in spec 022's harness. Spec 033 shipped the *enforcement* primitives (per-cycle dollar cap, codex token cap, wall-clock backstop, approval gates); spec 045 makes the cost story *informative* across cycles instead of just blocking on breach. Spec 033 enforces budgets — but it doesn't tell the user when a cycle was suspiciously cheap (under-spent → did too little research) or when the cache hit rate quietly dropped (prompt drift bloating costs). These are quality signals masquerading as cost signals; without them, the user discovers degradation by reading per-cycle reports manually.

## Clarifications

### Pending — `/speckit.clarify` session TBD

- **Q1 (FR-001 / cache-hit threshold)**: The right cache-hit threshold for the WARN — 80% is a guess (per stub). Real fixtures (post-Tier-1 ports) should drive this. Default proposed: 80% in v1, with a re-tune after first 30 days of real-world signal from Wave 2 vaults.
- **Q2 (FR-005 / substantive denominator)**: Is "substantive note" the right denominator for `cost_per_substantive_note`, or should we count "verifier-passed notes" instead? Quality vs acceptance trade-off. Default proposed: VERIFIER-PASSED notes (count what shipped, not what was attempted) — closer to "cost of a usable note".
- **Q3 (FR-008 / per-tier ceilings)**: Per-tier ceilings — static thresholds (e.g. `tier:basic` = $0.10/call hard cap), or baselined against the vault's own historical mean (e.g. "tier:basic is 2x its 30-day mean")? Default proposed: BASELINED (self-correcting; no per-vault tuning required); with a 7-day warm-up grace period where no warnings fire.
- **Q4 (FR-012 / hard-fail option)**: Should cache-hit-ratio gate become a HARD FAIL option (similar to spec 033's `approval_gates`), or stay warn-only? Default proposed: WARN-ONLY in v1. Hard-fail can be added if real-world signal shows warn-only is being ignored.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Cache-hit-ratio warns of upstream drift (Priority: P1)

A cycle runs with spec 020's per-source-version signal cache. Cache hit ratio for source-extraction is 95%+ for cycles 1-10. In cycle 11, an upstream config change accidentally invalidates the cache for most sources. The cache hit ratio drops to 30%. The cycle report includes a "cache-hit warning: 30% (threshold: 80%)" with the affected sources listed.

**Why this priority**: A cache-busting change can 10x source-extraction cost overnight. Detecting it via the next cycle's report (rather than next month's bill) is the difference between catching a regression in hours vs weeks.

**Independent Test**: Run a cycle with a fresh cache. Manually invalidate the cache for half the sources. Run a second cycle. Verify: cycle-2 report contains "cache-hit warning" with hit ratio + affected sources; cycle-2 still completes successfully (warning, not failure).

**Acceptance Scenarios**:

1. **Given** a vault with cache-hit-ratio dropping below threshold mid-run, **When** the cycle completes, **Then** the report contains a "cache-hit warning" entry naming the threshold + actual ratio + affected sources.
2. **Given** the threshold is exceeded (cache healthy), **When** the cycle completes, **Then** no cache-hit warning fires (no spurious noise).
3. **Given** spec 028's telemetry sidecars record per-call hit/miss, **When** the aggregator rolls them up, **Then** the cache-hit ratio is computed correctly per-stage and per-source.

---

### User Story 2 — `cost_per_substantive_note` surfaces prompt regressions (Priority: P1)

The quality harness reports `cost_per_substantive_note = $0.40` for the feeds-vault fixture's baseline. A prompt-bloat regression hits — the new cycle costs the same total but produces 30% fewer substantive notes. `cost_per_substantive_note` jumps to $0.55 (38% increase). The moderate gate (>15% regression per spec 030) fires FAIL.

**Why this priority**: Quality-with-cost-awareness. Per spec 033 FR-009 (already shipped), this metric is the killer signal — a cycle that produces good notes at 2x the cost is regression-worthy. P1 because it's the bridge between enforcement (spec 033) and quality (spec 030).

**Independent Test**: Run the quality harness against a fixture vault with known baseline `cost_per_substantive_note`. Run again after manufactured prompt bloat. Verify: the metric increases proportionally; moderate gate fires FAIL when delta > 15%.

**Acceptance Scenarios**:

1. **Given** spec 028's honest cost telemetry, **When** the harness computes metrics, **Then** `cost_per_substantive_note` is reported alongside the existing 4 metric families (coverage, note quality, cycle health, source quality).
2. **Given** a baseline of $0.40/note, **When** a cycle regresses to $0.65/note, **Then** the moderate gate fires FAIL (>15% — per spec 030's gate convention).
3. **Given** per Q2 default (verifier-passed denominator), **When** a cycle produces 50 notes but only 40 pass verifier, **Then** the denominator is 40, not 50.

---

### User Story 3 — Per-tier guardrails flag prompt bloat at call-time (Priority: P2)

A `tier: basic` call drifts above the threshold (e.g. $0.10/call → $0.15/call). The cycle report contains a "tier-cost warning: tier:basic call at stage 'note-writer' cost $0.15 (1.5x baseline). Investigate prompt length / output size." This complements spec 033 FR-007's surface but with self-baselined thresholds per Q3.

**Why this priority**: Spec 033 FR-007 already has STATIC per-tier guardrails; this spec proposes SELF-BASELINED guardrails (Q3 default). P2 because the static version already works; self-baselining is a polish.

**Acceptance Scenarios**:

1. **Given** a vault with 30+ days of cost history, **When** a `tier: basic` call costs 2x its 30-day mean, **Then** a tier-cost warning fires in the cycle report.
2. **Given** a fresh vault (<7 days history per the warm-up grace period in Q3), **When** a tier:basic call is expensive, **Then** NO warning fires (warm-up period — baselines aren't ready).
3. **Given** the warning includes stage + cost + delta vs mean, **When** the operator reviews, **Then** they have enough context to investigate.

---

### User Story 4 — Per-stage cost-share surfaces uneven distribution (Priority: P2)

A cycle's cost-summary shows note-writer at 78% of total spend. The "uneven cost distribution" warning fires: "Stage 'note-writer' consumed 78% of cycle budget (threshold: 60%). Likely indicator: cache miss, runaway batch, or model upgrade." The operator investigates and finds a stale cache key.

**Why this priority**: Diagnostic complement to total-cost enforcement. Without per-stage surface, the operator sees "$2.50 cycle" without context. With this surface, they see WHERE the cost concentrated.

**Acceptance Scenarios**:

1. **Given** a cycle where one stage exceeds 60% cost share, **When** the report renders, **Then** the stage is flagged with the share % + 3 likely causes (cache miss / runaway batch / model upgrade).
2. **Given** a cycle with even cost distribution (no stage above threshold), **When** the report renders, **Then** no uneven-distribution warning fires.

---

### User Story 5 — Warnings feed digest + health surfaces (Priority: P3)

Across a week, 3 cycles tripped the cache-hit gate. The cross-cycle digest (spec 035) summarizes: "This week: 3 cache-hit warnings. Most affected source: youtube. Consider running `./vault sources rebuild --module youtube`." The operator reads the digest, runs the suggested command, fixes the cache.

**Why this priority**: Aggregation > per-cycle noise. P3 because the per-cycle warnings (US1) are the foundation; aggregation is the polish layer.

**Acceptance Scenarios**:

1. **Given** spec 035's digest runs, **When** the week had cache-hit warnings, **Then** the digest's "Source Quality Drift" or "Cost Anomalies" section surfaces them with the most-affected source.
2. **Given** `./vault health` is invoked, **When** there are recent cache-hit warnings (last 7 cycles), **Then** the health output lists them with cycle numbers.

---

### Edge Cases

- What if a vault has no cache yet (cycle 1)? → Cache-hit-ratio is undefined; suppress the warning until cycle 2+.
- What if `cost_per_substantive_note` denominator is zero (no substantive notes)? → Report the metric as "N/A — no substantive notes produced this cycle"; do not divide by zero.
- What if a baselined threshold (per Q3) has insufficient history (<7 cycles)? → Skip the warning until enough history exists. Document the warm-up requirement.
- What if multiple gates fire on the same cycle (cache + tier + per-stage)? → Each is an independent warning in the report; don't conflate.
- What if the operator wants to silence a specific gate? → `settings.yaml::cost_efficiency.disabled_gates: [cache_hit, per_tier]`; document but don't recommend.
- What if spec 030's `cost_per_substantive_note` isn't shipping yet (timing dependency)? → This spec stubs the metric; spec 030 owns the implementation.

## Requirements *(mandatory)*

### Functional Requirements

#### Cache-hit-ratio gate

- **FR-001**: A new `cost_efficiency.cache_hit_warn_threshold: 0.80` setting MUST be supported in `settings.yaml` (per Q1 default; configurable).
- **FR-002**: After every cycle, the framework MUST compute cache-hit ratio = `cache_hits / (cache_hits + cache_misses)` from spec 028's sidecar data, aggregated across all source-extraction stages.
- **FR-003**: When the ratio is below the threshold AND the vault has prior history (cycle >= 2), the framework MUST emit a "cache-hit warning" entry in the cycle report with: actual ratio, threshold, top affected sources.
- **FR-004**: Per Q4 default, this gate is WARN-ONLY in v1. It does NOT fail the cycle. The cycle's exit code reflects only cycle-level outcomes.

#### `cost_per_substantive_note` metric

- **FR-005**: Per Q2 default, the metric MUST use `verifier-passed notes` as the denominator: `cost_per_substantive_note = total_cycle_cost_usd / count(verifier_passed_notes)`.
- **FR-006**: Spec 030's quality harness OWNS the actual metric implementation. This spec defines the contract (formula, denominator, threshold proposals).
- **FR-007**: The metric MUST be reported in `./build.sh --quality` output as the 5th metric family (after coverage, note quality, cycle health, source quality). Moderate gate fires FAIL when current cycle's value > 1.15 × baseline.

#### Per-tier cost guardrails (baselined)

- **FR-008**: Per Q3 default, per-tier cost ceilings are BASELINED against the vault's own historical mean. A new `cost_efficiency.tier_drift_factor: 2.0` setting controls the trigger threshold (default: warn at 2x mean).
- **FR-009**: The framework MUST require ≥7 days of cycle history before computing tier baselines. During warm-up, no per-tier warnings fire.
- **FR-010**: When a per-tier warning fires, the cycle report MUST include: stage, tier, actual cost, baseline mean, drift factor, sample size.

#### Per-stage cost-share threshold

- **FR-011**: A new `cost_efficiency.uneven_distribution_threshold: 0.60` setting MUST be supported. After every cycle, the framework MUST check whether any single stage consumed >60% of cycle budget.
- **FR-012**: When the threshold is exceeded, the cycle report MUST include an "uneven cost distribution" warning naming the stage + share % + 3 likely causes (cache miss / runaway batch / model upgrade).

#### Aggregation surfaces

- **FR-013**: The cross-cycle digest (spec 035) MUST include a "Cost Anomalies" section summarizing cost-efficiency warnings in scope.
- **FR-014**: `./vault health` MUST list cost-efficiency warnings from the last 7 cycles when invoked.
- **FR-015**: ALL warnings in this spec MUST be opt-out via `cost_efficiency.disabled_gates: [<gate_name>]` (per Edge Case 5). Documented but not recommended.

### Key Entities

- **`cost_efficiency.*` settings block**: New `settings.yaml` section with tuning knobs per FR-001/008/011/015.
- **Cache-hit aggregator**: Reads spec 028's per-call sidecars, aggregates hit/miss across source-extraction stages, computes ratio.
- **`cost_per_substantive_note` metric**: Contract owned by THIS spec; implementation owned by spec 030.
- **Per-tier baseline tracker**: Reads the last 30 days of cycle history (or last N cycles, configurable) per tier, computes mean. Triggers warning at `tier_drift_factor` × mean.
- **Per-stage cost-share computer**: Per-cycle simple ratio; trigger threshold per FR-011.
- **Warm-up period flag**: Internal flag set when the vault has insufficient history for baselined metrics. Surfaces in the report header.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After this spec ships + a 30-day baseline period, 100% of cache-busting regressions on the feeds-vault fixture are detected by US1's gate within 1 cycle of the regression.
- **SC-002**: `cost_per_substantive_note` is a stable metric in `./build.sh --quality` output for ≥30 consecutive cycles on the feeds-vault fixture.
- **SC-003**: 0 spurious per-tier-cost warnings fire during the 7-day warm-up period (per Q3 default).
- **SC-004**: 0 cycles fail because of cost-efficiency warnings (per Q4 default — warn-only).
- **SC-005**: After 90 days of real-world signal post-launch, ≥1 retrospective shows the cost-efficiency surface caught a regression that the static enforcement (spec 033) didn't.

## Assumptions

- Spec 028 (telemetry sidecar) is shipped and producing per-call hit/miss data.
- Spec 020 (source-module architecture) is shipped and producing source-version cache. Without the cache, FR-001's ratio is meaningless.
- Spec 030 (quality harness v3) is shipped or shipping in parallel. The `cost_per_substantive_note` metric implementation lives there.
- Warm-up grace periods (7 days for tier baselines) are sufficient for stable baselines. Re-tune post-launch if data shows otherwise.
- Operators want SELF-CORRECTING thresholds (per Q3) over per-vault tuning. If real demand shows otherwise, revisit.

## Dependencies

- **Hard**: Spec 028 (telemetry sidecar) — sidecar data is the input to all aggregators.
- **Hard**: Spec 020 (source modules) — cache is the input to FR-002.
- **Hard**: Spec 030 (quality harness v3) — owns `cost_per_substantive_note` implementation.
- **Soft**: Spec 035 (cross-cycle digest) — aggregation surface per FR-013.
- **Soft**: Spec 033 (cost enforcement) — complementary; 045 is informative, 033 is enforcement. Together they cover the "honest + actionable" cost story.

## Acceptance coverage

Draft — evidence cells populated by `/speckit.tasks` after `/speckit.clarify`.

| User Story | Evidence |
|---|---|
| US1 — Cache-hit-ratio warns of upstream drift | _(deferred to tasks.md — pending /speckit.clarify on open Q1/Q2/Q3)_ |
| US2 — `cost_per_substantive_note` surfaces prompt regressions | _(deferred to tasks.md — pending /speckit.clarify on open Q1/Q2/Q3)_ |
| US3 — Per-tier guardrails flag prompt bloat at call-time | _(deferred to tasks.md — pending /speckit.clarify on open Q1/Q2/Q3)_ |
| US4 — Per-stage cost-share surfaces uneven distribution | _(deferred to tasks.md — pending /speckit.clarify on open Q1/Q2/Q3)_ |
| US5 — Warnings feed digest + health surfaces | _(deferred to tasks.md — pending /speckit.clarify on open Q1/Q2/Q3)_ |

## Out of Scope

- Replacing or rewriting spec 033's enforcement layer. 045 is additive (informative); 033 is foundational (enforcement).
- Cross-vault cost aggregation (one report covering multiple vaults). Out until multi-vault aggregation ships per spec 023 Phase 2 / spec 036.
- Vendor-specific cost optimization (e.g. Anthropic prompt-caching specifics). Those are spec 047 concerns.
- Auto-remediation (e.g. "framework auto-fixes cache-busting changes"). Detection only in v1; remediation requires operator action.
- LLM-driven cost analysis (e.g. "ask an agent to summarize this week's cost trends"). Deterministic aggregators only in v1.

---

*Promote to active queue by running `/speckit.clarify` against this draft; the four pending clarifications (Q1-Q4) gate the promotion to `IMPLEMENTABLE`. Land AFTER spec 030 (quality harness v3) so the `cost_per_substantive_note` metric has a home.*
