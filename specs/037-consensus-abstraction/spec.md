# Feature Specification: Multi-Agent Consensus Abstraction

**Feature Branch**: `037-consensus-abstraction`
**Created**: 2026-05-27 (promoted from `docs/TODO.md` during the post-Wave-1 doc restructure).
**Status**: planned — 🚧 **BLOCKED — design-space spec only.** Rule-of-three says do not extract this abstraction until a SECOND concrete use case for M-of-N consensus is on the table. This spec captures the design constraints + reuse candidates so the right shape is sketched when the trigger fires. **Do not run `/speckit.plan` or `/speckit.tasks` against this spec until promotion criteria are met.**

> ## ⚠️ Promotion gate
>
> This spec exists to PRESERVE design constraints. It is NOT ready for
> planning or implementation.
>
> **Promotion criterion**: at least ONE of the four "Reuse Candidates"
> (US2 below) ships a concrete second use site for M-of-N consensus.
> Spec 020's `source_bridge` is the first use site; until a SECOND
> arrives, extracting the abstraction would calcify around source-
> extraction's quirks.
>
> **What this spec IS**:
> - A design-space document capturing the proposed API surface, the
>   four reuse candidates, the cost trade-offs, and the open
>   clarifications.
> - A constraint-preservation contract — when the trigger fires, the
>   second use site MUST validate the proposed API before we commit.
>
> **What this spec is NOT**:
> - An IMPLEMENTABLE spec. The promotion criterion gates `/speckit.plan`.
> - A commitment to the proposed API shape — the second use site will
>   inform the final shape, possibly overriding the proposed signature.

**Input**: Spec 020 (`source_bridge`) ships M-of-N consensus for source extraction — N=1/3/5 agents based on `value_tier` (`routine`/`important`/`critical`), majority vote on verdict, union of findings. The pattern is broader than 020: any stochastic LLM call benefits from N-way consensus when stakes are high. Multiple concrete reuse candidates exist (verifier on high-stakes notes, scout exhaustion checks, `/ask` cross-validation, doc-writer + verifier N-drafter consensus) BUT none have shipped yet. The rule-of-three says: do not extract until duplication forces it. This spec preserves the constraints so the right shape lands when the trigger fires.

## Clarifications

### Pending — `/speckit.clarify` session deferred until promotion

The clarifications below are NOT actionable until the rule-of-three trigger
fires. They represent the design-space questions the second use site
will resolve.

- **Q1 (Parallel vs serial)**: Should consensus calls be PARALLEL (faster, costlier in concurrent token rate) or SERIAL (slower, gentler)? Spec 020 chose serial; revisit when a latency-sensitive use case (e.g. `/ask`) shows up. Default proposal: serial in v1, parallel as a `--parallel` opt-in once concurrent rate-limits are charted.
- **Q2 (Disagreement at critical tier)**: How do we handle disagreement at the `critical` tier when no majority exists (N=5, vote 2/2/1)? Block? Surface for human review? Pick the highest-confidence? Default proposal: BLOCK + surface for human review (per spec 033's `APPROVAL_REQUIRED` pattern); never silently default to a minority verdict.
- **Q3 (Telemetry shape)**: Should each invocation emit a separate sidecar (current spec 028 default) or one rolled-up `consensus-<stage>.json`? Default proposal: separate sidecars per invocation + one rolled-up `consensus-<stage>.json` summarizing the vote outcome (both, for auditability + readability).
- **Q4 (API surface)**: Is the proposed `consensus(*, invocations, n, vote_key, union_keys, tier)` signature right? OR should consensus be a decorator pattern (`@consensus(n=3, tier='important')` on the stage function)? Default proposal: function-call signature (more flexible); decorator is sugar over it if the second use case wants it.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Source-bridge consensus migrates to shared abstraction (Priority: P1, AFTER promotion)

When the rule-of-three trigger fires, `pipeline/source_bridge.py`'s consensus logic is extracted into `pipeline/consensus.py` exporting the proposed `consensus()` API. The source-bridge migrates to call through the new module. End-to-end behavior is UNCHANGED — the same source-extraction cycles produce the same outputs.

**Why this priority**: Re-shaping the existing use site is the validation that the abstraction is correct. If migrating spec 020 to the new module breaks behavior, the abstraction is wrong + needs reshaping.

**Independent Test**: Run the source-bridge consensus tests before + after the migration. Verify: same inputs produce same outputs; no test regressions; the public source-bridge API is unchanged.

**Acceptance Scenarios**:

1. **Given** the migration is complete, **When** spec 020's source-bridge tests run, **Then** all tests pass without modification.
2. **Given** the new `pipeline/consensus.py` module, **When** source-bridge invokes it, **Then** the behavior matches the original embedded implementation byte-for-byte.
3. **Given** the migration ships, **When** spec 028's telemetry sidecars are inspected, **Then** they conform to per-invocation sidecars + a rolled-up `consensus-<stage>.json` (per Q3).

---

### User Story 2 — Second use case validates the abstraction (Priority: P1, TRIGGERS PROMOTION)

ONE of the four reuse candidates ships a concrete second use site that genuinely calls through `pipeline/consensus.py`. The candidates:

1. **Verifier on high-stakes notes** — N=3 verifications on legal/medical/critical-tier note types instead of single-shot verifier.
2. **Scout exhaustion** — N=3 gated "exhausted" verdict on critical domains; don't give up too early on the wrong signal.
3. **`/ask` cross-check** — N draftings → consensus before surfacing the answer to the user.
4. **Doc-writer + verifier** — N drafters → consensus → single verifier (cheaper than N verifier passes).

**Why this priority**: This IS the promotion trigger. Without a second use site, this spec stays DESIGN-SPACE. With a second use site, this spec promotes to FULL + implementable.

**Acceptance Scenarios**:

1. **Given** a concrete second use site is proposed (one of the four), **When** the trigger is acknowledged, **Then** this spec promotes from BLOCKED to FULL + the second use case's spec links to this one.
2. **Given** the second use site is implemented, **When** it runs in production, **Then** it ACTUALLY exercises the `consensus()` API (no parallel codepath).
3. **Given** the second use site reveals design-space surprises, **When** they are surfaced, **Then** the abstraction is RESHAPED before being canonical — the proposed signature in this spec is a STARTING POINT, not a contract.

---

### User Story 3 — Cost-aware tier selection survives the abstraction (Priority: P1)

The `value_tier` field (`routine`/`important`/`critical`) drives N selection: `routine` = N=1 (no consensus), `important` = N=3, `critical` = N=5. The cost-guardrail hard cap (spec 033) MUST survive the abstraction — consensus calls inherit the per-call cost capture from `agent_call.py`. A consensus of N=5 critical-tier calls correctly counts as 5 dispatches against the budget.

**Why this priority**: Spec 033's enforcement is load-bearing. Any abstraction that breaks cost accounting is a regression.

**Acceptance Scenarios**:

1. **Given** a consensus call with N=5, **When** the budget tracker reports cost, **Then** all 5 calls are accounted for (not just the consensus outcome's cost).
2. **Given** `tier=routine`, **When** the consensus invocation runs, **Then** only 1 call fires (no consensus overhead for routine work).
3. **Given** spec 033's BUDGET_PAUSED would fire mid-consensus (e.g. after call #3 of N=5), **When** the consensus dispatch checks the budget, **Then** the pause fires correctly + the partial consensus state is recorded in the cycle report.

---

### Edge Cases

- What if N is even? → Reject at API time with "N must be odd to ensure majority". Spec 020's invariant.
- What if all N invocations fail (no successful results)? → Return `ConsensusResult(verdict=null, confidence=0.0, error="all invocations failed")`. The caller decides escalation.
- What if N invocations produce DIFFERENT `union_keys` shapes (one returns `{tags: []}`, another returns `{tags: null}`)? → Coerce null to empty; document this as a contract requirement on `invocations` callable.
- What if the rule-of-three trigger never fires (no second use case in 12 months)? → This spec stays BLOCKED indefinitely. That's fine — design-space spec ≠ obligation to ship.
- What if a third use case wants DIFFERENT semantics (e.g. weighted vote rather than majority)? → Either generalize the API (vote function as parameter) OR ship a sibling abstraction (`weighted_consensus`); spec amends.
- What if the second use site reveals that `tier` is the wrong axis (e.g. some stages want N=5 for `routine` work)? → The proposed `tier` parameter is a default; allow override. Reshape if needed.

## Requirements *(mandatory)*

### Functional Requirements *(POST-PROMOTION)*

All FRs below are CONDITIONAL on the rule-of-three trigger firing.
Until then, they represent the design-space SKETCH, not a contract.

- **FR-001 (post-promotion)**: A new `pipeline/consensus.py` module MUST export the `consensus()` function with the proposed signature (modulo refinements from the second use site).
- **FR-002 (post-promotion)**: The `invocations` parameter MUST be a callable that produces ONE fresh result per invocation (not a list — supports retries + lazy evaluation).
- **FR-003 (post-promotion)**: `N` MUST be odd; even N rejected at API time with a clear error.
- **FR-004 (post-promotion)**: `vote_key` identifies the field whose value drives the majority vote. `union_keys` (optional list) identify fields whose values are unioned across all N invocations.
- **FR-005 (post-promotion)**: `tier` (`routine`/`important`/`critical`) MAY be used to gate the default N selection: `routine` → N=1 (no consensus); `important` → N=3; `critical` → N=5. Operators may override explicitly.
- **FR-006 (post-promotion)**: All N invocations MUST flow through `agent_call.py` (single LLM dispatch surface per Principle V). The consensus module does NOT contain its own LLM call code.
- **FR-007 (post-promotion)**: Cost capture via spec 028 sidecars MUST account for all N invocations. The cycle's budget tracker correctly counts N dispatches against the cap.
- **FR-008 (post-promotion)**: Spec 033's BUDGET_PAUSED MUST fire correctly mid-consensus when the budget cap is exceeded. The partial consensus state MUST be recorded in the cycle report.
- **FR-009 (post-promotion)**: Disagreement at the `critical` tier with no majority MUST follow Q2's clarification (default: block + surface via APPROVAL_REQUIRED).
- **FR-010 (post-promotion)**: Per Q1's default, consensus calls are SERIAL in v1. Parallel dispatch is a `--parallel` opt-in once concurrent rate-limits are charted.
- **FR-011 (post-promotion)**: Telemetry per Q3 default — each invocation emits a separate sidecar; the consensus call emits a rolled-up `consensus-<stage>.json` summarizing the vote outcome.
- **FR-012 (post-promotion)**: Spec 020's `source_bridge` MUST migrate to call through `pipeline/consensus.py`. End-to-end behavior MUST be unchanged.

### Functional Requirements *(PRE-PROMOTION — meta-requirements)*

These FRs apply WHILE this spec is BLOCKED. They preserve constraints
during the design-space phase.

- **FR-100**: This spec MUST NOT be promoted to IMPLEMENTABLE until the rule-of-three trigger fires (a second concrete use site is on the table).
- **FR-101**: Any future spec proposing a USE of consensus (verifier-N, scout-exhaustion-N, etc.) MUST reference this spec in its Dependencies block.
- **FR-102**: This spec's Reuse Candidates (US2) MUST be kept up to date — when a candidate ships under a different spec number, this spec's US2 entry MUST link to that spec.
- **FR-103**: If 12+ months pass with no trigger, this spec MAY be re-evaluated for closure / merge into spec 020 documentation (rule-of-three was the constraint; never coming = the abstraction wasn't needed).

### Key Entities

- **`pipeline/consensus.py` module** (post-promotion): The shared abstraction. Lives in the pipeline package.
- **`consensus()` API**: Function-call signature per FR-001 (refinements from second use site allowed).
- **`ConsensusResult` dataclass**: Output type. Fields: `verdict` (the majority-voted value), `confidence` (0.0-1.0), `votes` (full vote breakdown), `union` (unioned values across N), `cost_usd` (sum of N invocation costs), `errors` (per-invocation error list).
- **`value_tier` enum**: `routine` / `important` / `critical`. Drives default N selection.
- **`agent_call.py` (existing)**: The single LLM dispatch surface. Consensus calls flow through this.
- **`tests/contracts/consensus-result.schema.json`**: JSON schema for the rolled-up sidecar (per FR-011). Mirror of spec 020's existing schema.

## Success Criteria *(mandatory, POST-PROMOTION)*

### Measurable Outcomes

All SCs are CONDITIONAL on the rule-of-three trigger firing.

- **SC-001**: After promotion + migration, source-bridge tests pass 100% unchanged (FR-012 invariant).
- **SC-002**: The second use site (whichever ships first from US2's candidates) successfully exercises the `consensus()` API in production (not a parallel codepath).
- **SC-003**: Cost accounting matches: a consensus of N=5 calls counts as 5 dispatches in the budget tracker (FR-007 invariant).
- **SC-004**: Spec 033's BUDGET_PAUSED fires correctly mid-consensus when the cap is exceeded (FR-008 invariant).
- **SC-005 (pre-promotion)**: This spec stays BLOCKED until US2's trigger fires. 0 attempts to promote prematurely.

## Assumptions

- The proposed API signature is a STARTING POINT — the second use site informs the final shape. May change materially.
- Spec 020 (source-bridge) is shipped and producing consensus correctly. The migration in FR-012 is refactor, not redesign.
- Spec 028 (telemetry sidecars) is shipped. Consensus invocations land in the sidecar shape per FR-011.
- Spec 033 (cost enforcement) is shipped. Consensus inherits cost capture per FR-007/008.
- The rule-of-three is the right discipline here. Premature extraction calcifies the abstraction.

## Dependencies

- **Hard (post-promotion)**: Spec 020 (source-bridge) — migrated in FR-012.
- **Hard (post-promotion)**: Spec 028 (telemetry sidecar) — telemetry contract.
- **Hard (post-promotion)**: Spec 033 (cost enforcement) — budget accounting.
- **Hard (pre-promotion)**: At least ONE of US2's Reuse Candidates ships its second use site — THIS is the promotion trigger.
- **Soft**: Spec 047 (backend-agnostic agent layer) — multi-vendor consensus is a 047 concern, not a 037 concern.

## Acceptance coverage

**Pre-promotion**: No acceptance coverage. This spec is design-space only.

**Post-promotion**: Acceptance cells populated by `/speckit.tasks` AFTER the rule-of-three trigger fires.

| User Story | Evidence |
|---|---|
| US1 — Source-bridge consensus migrates to shared abstraction | _(deferred to tasks.md — promotion-gated; not implementable until rule-of-three / dual-trigger fires)_ |
| US2 — Second use case validates the abstraction | _(deferred to tasks.md — promotion-gated; not implementable until rule-of-three / dual-trigger fires)_ |
| US3 — Cost-aware tier selection survives the abstraction | _(deferred to tasks.md — promotion-gated; not implementable until rule-of-three / dual-trigger fires)_ |

## Out of Scope

- Replacing single-shot LLM calls indiscriminately. Consensus has 3-5x the cost; only worth it for `important`/`critical` tiers.
- Cross-vendor consensus (one Anthropic + one OpenAI + one Ollama). v1 stays homogeneous — multi-vendor is a spec 047 concern.
- Weighted-vote consensus (different agents with different weights). v1 is unweighted majority; revisit if a third use case wants weights.
- Asynchronous consensus (consensus over multiple cycles' worth of partial results). v1 is per-call.
- LLM-driven consensus tuning (e.g. "ask an agent how many votes we should use"). Deterministic N selection only.

---

*This spec is **BLOCKED**. Do not run `/speckit.plan` or `/speckit.tasks` against it until US2's promotion trigger fires (a second concrete use site for M-of-N consensus arrives). Until then, this spec is a constraint-preservation document.*
