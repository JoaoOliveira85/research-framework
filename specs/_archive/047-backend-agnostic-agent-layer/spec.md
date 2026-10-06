# Feature Specification: Backend-Agnostic Agent Layer

**Feature Branch**: `047-backend-agnostic-agent-layer`
**Created**: 2026-05-27 (promoted from `docs/ROADMAP.md` Horizon 3 "Vendor- and interface-agnostic agent layer" during post-Wave-1 doc restructure).
**Absorbs**: Spec 011 (per-flow LLM routing) — per-flow model selection is a special case of "pick a backend per stage."
**Precursor (does NOT promote this spec)**: Spec 052 (Cursor CLI executor, DRAFT 2026-06-02) adds `cursor-agent` as a third **CLI** runtime via the existing `_RUNTIME_ADAPTERS` registry. CLI-only, so it does **not** satisfy this spec's *non-CLI* promotion trigger — but it exercises part of the registry/cost-coupling surface and should inform 047's final abstraction shape. 052 must not grow into this abstraction; if it starts to, promote 047 instead.
**Status**: superseded(by spec 064) — 🪦 **TOMBSTONED 2026-06-11 — superseded by [spec 064 (opencode Executor)](../064-opencode-executor/spec.md).** The "reach any model provider, not just CLI-and-Anthropic" goal is delivered by 064 as a concrete **provider-agnostic agentic executor** (opencode, the 4th `_RUNTIME_ADAPTERS` runtime) rather than this spec's speculative three-stage interface refactor. 047's shipped v1 (the Ollama **HTTP** dispatch primitive below) is **superseded**: the 2026-06-08 run proved raw HTTP is *non-agentic* (can't write stage output files) — opencode closes that gap because it runs a real agent loop with filesystem tools. Spec 011 (per-flow routing), formerly absorbed here, is now subsumed under 064. The design-space content below is preserved for historical context only; do **not** plan/implement against this spec. **Prior status (historical):** ✅ v1 (preview) SHIPPED [Unreleased] / 1.0.0rc5 — PR #138, squash `4a8c922`, 2026-06-08. **Dispatch-only**: the Ollama HTTP backend is validated as a programmatic **dispatch primitive**, NOT yet a drop-in full-cycle executor — HTTP is *non-agentic* (returns text but cannot write the stage output files that scout / note-writer rely on; surfaced by the 2026-06-08 validation run, see CHANGELOG `[Unreleased]`). An output-file contract for HTTP stages + the full claude/codex-behind-an-interface refactor (FR-001..006) remain deferred to later 047 stages. Both promotion triggers fired: (a) **6 spec-020 source-module ports shipped** (youtube / reddit / rss / oreilly + the 2026-06-08 batch github + atlassian — well past the ≥3 bar) AND (b) **a concrete non-CLI use case materialized** — a local **Ollama HTTP server** (localhost) the operator is already running, motivated by the MCP-free / multi-vendor cost pivot. **v1 scope = the Ollama HTTP backend ONLY**, added incrementally as one guarded `http`/`api` branch at the single `agent_call.py` dispatch point (the full claude/codex-behind-an-interface refactor of FR-001..006 is deferred to later 047 stages). See Clarifications Session 2026-06-08.

> ## ⚠️ Promotion gate — ✅ FIRED 2026-06-08
>
> Both criteria below held as of 2026-06-08, so this spec was promoted to
> **v1 implementation** (Ollama HTTP backend only). The design-space content
> beneath is preserved verbatim for the later full-abstraction stages.
>
> **Promotion criteria** (BOTH must hold):
> 1. Spec 020's source-module ports (Wave 2 Tier-1) are at least 3
>    modules deep — we need real-world signal that the framework's
>    CLI-only assumptions are stable BEFORE we abstract them.
> 2. A concrete non-CLI use case materializes: HTTP API direct (for
>    cost reasons OR for rate-limit-sensitive workflows) OR a local
>    LLM runtime (Ollama, llama.cpp) for offline-first vaults.
>
> Speculative abstraction NOW would conflate "is the abstraction right"
> with "do the new backends work" — bad signal mixing.
>
> **What this spec IS**:
> - A design-space document capturing the three-stage migration plan,
>   the seam audit, the absorbed spec 011 routing semantics, the
>   load-bearing constraints from specs 028 / 033 / 042.
> - A constraint-preservation contract — when the trigger fires, the
>   concrete second backend MUST validate the proposed abstraction.
>
> **What this spec is NOT**:
> - An IMPLEMENTABLE spec. The promotion criterion gates `/speckit.plan`.
> - A commitment to the proposed three-stage shape — the second backend
>   informs the final shape, possibly overriding the stage order.

**Input**: Current pipeline is CLI-only and the scaffold generates Anthropic-shaped config. This blocks API-direct usage (cheaper for high-volume vaults; required for rate-limit-sensitive workflows), local LLMs (Ollama, llama.cpp) for offline-first vaults, other vendors (OpenAI, Google Gemini), and any non-CLI interface. The cost-guardrail hard cap (spec 033) MUST survive this refactor — it lives at the dispatch point, not in CLI-specific code. Existing CLI runtimes (`claude`, `codex`) become two implementations of the same interface; cost capture, permission model, and prompt rendering each become pluggable.

## Clarifications

### Session 2026-06-08 — v1 promotion (Ollama HTTP backend)

This session recorded the decisions that scope **v1** to the Ollama HTTP
backend and resolve the FR-008/009 single-dispatch-point tension for an
incremental ship. The four pre-promotion design questions (Q1–Q4 below) are
**still deferred** to the later full-abstraction stages — they don't gate v1.

- **Q-v1.1 (v1 scope)**: What does v1 deliver? → **The Ollama HTTP/API backend ONLY.** The framework already runs `claude`/`codex`/`cursor-agent` through CLI adapters; v1 adds the first *non-CLI* runtime (a local Ollama server) without rewriting the existing adapters. The three-stage claude/codex-behind-an-interface refactor (FR-001..006) is explicitly deferred — v1 is the "second backend validates the seam" milestone (User Story 2), not the "CLI runtimes refactored" milestone (User Story 1).
- **Q-v1.2 (Ollama-first vs API-first)**: The original spec leaned API-first because local-GPU availability was uncertain. → **That reason is now moot** — the operator is already running an Ollama box (localhost). v1 targets Ollama directly. A generic OpenAI-compatible HTTP backend falls out for free because Ollama exposes `/v1/chat/completions`; both the OpenAI-compatible and the Ollama-native `/api/chat` response shapes are parsed.
- **Q-v1.3 (FR-008/009 single-dispatch-point honored?)**: Does adding an HTTP path create a second permanent dispatch point (violating FR-009)? → **No.** v1 introduces ONE guarded `http`/`api` branch *inside* the existing single `agent_call.py` dispatch point — not a parallel script. `communication.mode: http` + `default_executor.type: api` (both previously parsed-but-unused) are the trigger; `_dispatch_http()` sits beside the existing CLI/streaming branches and shares the same sidecar-emission tail. The clarify step blesses this as a v1 stepping-stone toward the full interface, NOT an abandonment of FR-009.
- **Q-v1.4 (cost provenance for a local runtime)**: How is a $0 local runtime represented in the spec-028 sidecar / spec-033 budget? → **`cost_usd: 0.0` with REAL token counts** from the API `usage` block, tagged **`cost_source: "runtime"`** (both numbers measured, not estimated — distinct from cursor's estimated dollar). The dollar cap can never fire for Ollama; the **wall-clock cap (spec 033)** is the operative guardrail for unattended local runs. Ollama tokens are NOT added to the metered-token cap (it has no external token quota, unlike codex/cursor).
- **Q-v1.5 (sidecar footgun)**: `budget_guard.list_sidecars_v11` hard-matched `schema_version == "1.1"` while the writer emits `"1.2"`, silently dropping every modern sidecar from the dollar tally. → **Fixed as part of v1**: the consumer now accepts the additive `1.x` line from 1.1 onward (1.0 stays excluded). Without this, Ollama/cursor cost telemetry would never reach the budget tally.

### Pending (deferred to the full-abstraction stages — do NOT gate v1)

- **Q1 (FR-015 / Claude-specific templates)**: How much existing template-level assumption about Claude Code's system-prompt format can we tolerate? Some templates rely on Claude-specific tags (e.g. `<thinking>`); others are vendor-neutral. Default proposed: AUDIT all templates during Stage 1; vendor-neutralize where cheap; document Claude-specific dependencies for backends that can't honor them.
- **Q2 (FR-007 / cost unit)**: Should the abstraction expose cost as a uniform `cost_usd` decimal, or pass through vendor-native cost units (Anthropic counts cache tokens differently from OpenAI)? Default proposed: BOTH — `cost_usd` is the canonical aggregator (spec 033 enforces on this); vendor-native fields are passed through in the sidecar (`cost_vendor_native` JSON object).
- **Q3 (FR-018 / consensus across backends)**: How does the abstraction interact with spec 037's consensus? Can a consensus quorum span multiple backends (one Anthropic + one OpenAI + one local), or is consensus always within a single backend? Default proposed: SINGLE-BACKEND consensus in v1 (homogeneous quorum); multi-vendor consensus is a v2 extension if a use case surfaces.
- **Q4 (FR-002 / backend selection scope)**: Where does the backend choice live — per-stage in `settings.yaml::stages.*.backend`, per-vault in `settings.yaml::default_backend`, or both? Default proposed: BOTH — per-stage overrides per-vault default. Same pattern as `stages.*.model` (spec 025).

## User Scenarios & Testing *(mandatory)*

### User Story 1 — CLI runtimes survive the refactor unchanged (Priority: P1, AFTER promotion)

When the promotion criterion fires + Stage 2 of the refactor ships, the existing CLI runtimes (`claude`, `codex`) work UNCHANGED from the user's perspective. Same `settings.yaml::stages.*.model` keys. Same scaffolded configs. Same per-cycle behavior. The refactor is INVISIBLE to users running CLI-based vaults.

**Why this priority**: This is the load-bearing invariant. The refactor MUST be transparent for existing users; otherwise it's a breaking change.

**Independent Test**: Run the full test suite before and after Stage 2 of the refactor. Verify: all tests pass; no test modifications required; spec 028 sidecars are byte-identical; spec 033 budget enforcement fires identically.

**Acceptance Scenarios**:

1. **Given** an existing vault using `claude`, **When** the refactor ships, **Then** `./vault research` behaves identically (no user-visible changes).
2. **Given** an existing vault using `codex`, **When** the refactor ships, **Then** same — no user-visible changes.
3. **Given** the test suite, **When** run before + after the refactor, **Then** all tests pass without modification.

---

### User Story 2 — Second backend (HTTP API or Ollama) validates the abstraction (Priority: P1, TRIGGERS PROMOTION)

A concrete non-CLI backend ships:

- **Option A — HTTP API** (recommended first): Anthropic Direct API OR OpenAI API as the reference. Cheaper to test; proves the abstraction with fewer moving parts (no GPU dependency).
- **Option B — Local LLM** (recommended second): Ollama OR llama.cpp server. Local before API would conflate "is the abstraction right?" with "does my GPU work?".

**Why this priority**: This IS the promotion trigger. Without a concrete second backend, this spec stays DESIGN-SPACE. With one, the abstraction is extracted with real validation.

**Independent Test**: Implement ONE non-CLI backend (HTTP API recommended). Run a full cycle on a fixture vault using it. Verify: cycle completes; spec 028 sidecars land with vendor-native + canonical cost fields; spec 033 budget enforcement fires correctly.

**Acceptance Scenarios**:

1. **Given** a concrete non-CLI backend is proposed, **When** the trigger is acknowledged, **Then** this spec promotes from BLOCKED to FULL.
2. **Given** the non-CLI backend is implemented, **When** it ships, **Then** it ACTUALLY uses the abstraction (no parallel codepath).
3. **Given** the non-CLI backend reveals design-space surprises, **When** they surface, **Then** the abstraction is RESHAPED before being canonical.

---

### User Story 3 — Cost guardrail (spec 033) survives across backends (Priority: P1)

The cost-guardrail hard cap (spec 033) fires correctly regardless of backend. A vault using `claude` for some stages + `anthropic-api` for others has BUDGET_PAUSED fire when cumulative cost (across backends) exceeds the cap. Per Q2, vendor-native cost units are preserved in sidecars; `cost_usd` is the canonical aggregator.

**Why this priority**: Spec 033 is load-bearing. The abstraction MUST preserve its semantics across backends.

**Acceptance Scenarios**:

1. **Given** a vault using two backends in the same cycle, **When** cumulative cost exceeds the cap, **Then** BUDGET_PAUSED fires with the multi-backend spend breakdown.
2. **Given** vendor-native cost units differ (Anthropic vs OpenAI cache-token accounting), **When** the sidecar lands, **Then** both vendor-native AND canonical `cost_usd` are recorded.
3. **Given** a local LLM backend (Ollama) with `cost_usd: 0.0`, **When** the cycle runs, **Then** the dollar cap is never hit (zero cost) but the wall-clock cap (FR-012 in spec 033) still applies.

---

### User Story 4 — Spec 011 (per-flow LLM routing) is subsumed cleanly (Priority: P2)

Per-flow model selection is a special case of "pick a backend per stage." When this spec promotes, spec 011 is marked SUBSUMED-by-047. Operators using `settings.yaml::stages.*.model` see no behavior change; the same key works in the new abstraction.

**Why this priority**: Cleanup of an existing spec that became redundant. P2 because it's housekeeping, not a new capability.

**Acceptance Scenarios**:

1. **Given** spec 011's per-flow routing is shipped, **When** this spec promotes, **Then** spec 011 is marked SUBSUMED-by-047 in its status header.
2. **Given** an existing vault using per-stage model selection, **When** the refactor ships, **Then** the per-stage selection still works (now via the unified `backend` selector).

---

### User Story 5 — Spec 042 (autonomy) per-backend defaults survive (Priority: P1)

Spec 042 ships per-backend `autonomy_level` mappings for Claude Code, Codex, and Ollama (when its runtime ships). The abstraction MUST NOT collapse those backend-specific behaviours into a generic "autonomy: full-auto" flag — autonomy is genuinely per-backend (Claude Code's `permissions.defaultMode` and Codex's `approval_mode` aren't the same concept).

**Why this priority**: Spec 042 is load-bearing. The abstraction MUST preserve its per-backend semantics.

**Acceptance Scenarios**:

1. **Given** a vault with `autonomy_level: full-auto`, **When** it uses `claude` backend, **Then** the Claude-specific autonomy mapping fires (per spec 042 FR-004).
2. **Given** the same vault uses `codex` backend, **When** it dispatches, **Then** the Codex-specific autonomy mapping fires (per spec 042 FR-006).
3. **Given** a future Ollama backend, **When** it ships, **Then** spec 042's Ollama wrapper autonomy mapping fires (per spec 042 FR-011).

---

### Edge Cases

- What if a template uses Claude-specific tags (`<thinking>`) and the operator switches to OpenAI? → Per Q1, audit at promotion time; vendor-neutralize templates where cheap; OpenAI sees the tags as inert text (no behavior change, may waste tokens).
- What if a backend goes offline mid-cycle (HTTP API rate-limit, Ollama crashed)? → Spec 020's failure_policy applies via the backend abstraction; the policy is per-stage, not per-backend.
- What if two backends report cost in different time zones (UTC vs local)? → Spec 028's sidecar contract requires UTC; the abstraction enforces this regardless of backend.
- What if a future backend has no analog to `permissions.defaultMode` (e.g. Ollama)? → Per spec 042 FR-011, the wrapper owns the autonomy mapping; the abstraction must allow the wrapper to inject it.
- What if the abstraction's API breaks when adding a 4th backend? → That's the signal the API is wrong. Re-shape during the 4th-backend integration (don't keep papering over).
- What if 24+ months pass with no second backend? → This spec stays BLOCKED. Re-evaluate for closure.

## Requirements *(mandatory)*

### Functional Requirements *(POST-PROMOTION)*

All FRs below are CONDITIONAL on the dual-trigger firing.

#### Three-stage refactor

- **FR-001 (post-promotion, Stage 1)**: AUDIT every codepath in `agent_call.py` and related modules that assumes CLI I/O or Anthropic-shaped config. Output: a written audit document listing seams + a proposed target interface.
- **FR-002 (post-promotion, Stage 2)**: `agent_call.py` MUST be backend-agnostic post-Stage-2. The proposed dispatch signature is `dispatch(prompt, *, backend, **kwargs)` where `backend` is resolved per Q4 (per-stage > per-vault default).
- **FR-003 (post-promotion, Stage 2)**: Cost capture MUST become pluggable per backend. Each backend reports `cost_usd` (canonical) + `tokens_in` + `tokens_out` + `cost_vendor_native` (per Q2) in its own way.
- **FR-004 (post-promotion, Stage 2)**: Permission model MUST become pluggable per backend. CLI runtimes use `.claude/` / `.codex/` config; HTTP backends use API-key + scope; Ollama uses the wrapper permission model per spec 042 FR-011.
- **FR-005 (post-promotion, Stage 2)**: Prompt rendering MUST become pluggable per backend. Preserve Jinja2 throughout; make the system-prompt format a backend-config choice.
- **FR-006 (post-promotion, Stage 2)**: The existing CLI runtimes (`claude`, `codex`) MUST become two implementations of the same interface. Nothing user-visible changes.
- **FR-007 (post-promotion, Stage 3)**: HTTP API backend FIRST (Anthropic Direct + OpenAI API as reference impls). Local LLM (Ollama / llama.cpp) SECOND. The order is non-negotiable for design-validation reasons.

#### Load-bearing constraint: every LLM call flows through `agent_call.py`

- **FR-008 (post-promotion)**: Every new feature that touches LLM interaction MUST go through `agent_call.py`. CI gate (per spec 041) MUST enforce — no `import anthropic` or `import openai` outside `agent_call.py` and the backend implementations.
- **FR-009 (post-promotion)**: NO second dispatch point "temporarily" — those become permanent. Strict invariant.

#### Cost guardrails survive

- **FR-010 (post-promotion)**: Spec 033's BUDGET_PAUSED MUST fire correctly regardless of backend. Cumulative cost is computed across all backends in the cycle.
- **FR-011 (post-promotion)**: Per Q2, vendor-native cost units MUST be preserved in spec 028 sidecars (`cost_vendor_native` JSON field). Canonical `cost_usd` MUST always be computed.
- **FR-012 (post-promotion)**: For zero-cost backends (local LLM), the dollar cap is never hit; the wall-clock cap (spec 033 FR-012) is the operative budget.

#### Telemetry sidecars survive

- **FR-013 (post-promotion)**: Spec 028's telemetry sidecars MUST land regardless of backend — JSON shape is backend-agnostic by design.
- **FR-014 (post-promotion)**: The sidecar's `backend` field MUST identify which backend produced the call (`claude` / `codex` / `anthropic-api` / `openai-api` / `ollama` / etc.).

#### Templates + autonomy mappings

- **FR-015 (post-promotion)**: Per Q1, templates MUST be audited for vendor-specific assumptions. Vendor-neutralize where cheap; document Claude-specific dependencies for backends that can't honor them.
- **FR-016 (post-promotion)**: Spec 042's per-backend autonomy mappings MUST be preserved. The abstraction MUST allow each backend to inject its autonomy semantic.

#### Spec 011 absorbed

- **FR-017 (post-promotion)**: Spec 011 (per-flow LLM routing) MUST be marked SUBSUMED-by-047 once this spec promotes.
- **FR-018 (post-promotion)**: `settings.yaml::stages.*.model` continues to work — it's now a backend-config sub-key per Q4.

#### Consensus interaction

- **FR-019 (post-promotion)**: Per Q3, spec 037's consensus operates within a SINGLE backend in v1. Cross-backend consensus is a v2 extension.

### Functional Requirements *(PRE-PROMOTION — meta-requirements)*

- **FR-100**: This spec MUST NOT be promoted to IMPLEMENTABLE until BOTH triggers fire (≥3 source-module ports + concrete non-CLI backend).
- **FR-101**: Any future spec proposing a NEW BACKEND MUST reference this spec in its Dependencies block.
- **FR-102**: If 24+ months pass with no second backend, this spec MAY be re-evaluated for closure.

### Key Entities

- **`agent_call.py::dispatch()` (refactored)**: The single LLM dispatch surface post-Stage-2. Backend-agnostic.
- **Backend interface (post-Stage-2)**: An ABC (or duck-typed protocol) every backend implements. Methods: `render_prompt`, `invoke`, `parse_cost`, `enforce_permissions`.
- **Per-backend implementations**: One module per backend (`backends/claude.py`, `backends/codex.py`, `backends/anthropic_api.py`, `backends/openai_api.py`, `backends/ollama.py`, …).
- **`settings.yaml::default_backend` + `stages.*.backend`**: Per Q4 — per-vault default + per-stage override.
- **`cost_vendor_native` sidecar field**: Per Q2 — preserves vendor-native cost units alongside canonical `cost_usd`.
- **Audit document** (Stage 1 output): Lists all seams + proposed interface.
- **CI gate against second-dispatch-point** (FR-008/009): Mechanical check; lives in spec 041's CI.

## Success Criteria *(mandatory, POST-PROMOTION)*

### Measurable Outcomes

- **SC-001**: After Stage 2 ships, the full test suite passes 100% unchanged on existing CLI-only vaults (FR-006 invariant).
- **SC-002**: After Stage 3's first non-CLI backend ships, that backend's full integration test cycle completes within reasonable wall-clock (e.g. <10 min for HTTP API on a fixture vault).
- **SC-003**: Spec 033's BUDGET_PAUSED fires correctly in a mixed-backend cycle (FR-010 invariant), verified by a fixture test using two backends.
- **SC-004**: Adding a 3rd or 4th backend requires zero changes to `cycle_runner.py` — ONLY `agent_call.py` + a new backend module need touching. Verified by adding a placeholder 3rd backend in the test suite.
- **SC-005 (pre-promotion)**: This spec stays BLOCKED until BOTH triggers fire. 0 attempts to promote prematurely.

## Assumptions

- The three-stage refactor is the right shape. The second backend (US2) informs the final shape — may differ from the proposed split.
- Spec 020 source-module ports succeed in Wave 2 — without them, we don't have stable signal on what CLI assumptions are baked in.
- HTTP API access (Anthropic Direct, OpenAI) is cheap enough to be the v1 non-CLI backend. Local LLMs follow.
- Vendor-native cost units differ enough (per Q2) that the abstraction NEEDS both canonical + vendor-native fields. If real-world data shows otherwise, simplify.
- The "single dispatch surface" invariant (FR-008/009) is enforceable via CI grep. If a more sophisticated tool is needed, use it.

## Dependencies

- **Hard (post-promotion)**: Spec 020 (source modules) ports — ≥3 Tier-1 modules deep.
- **Hard (post-promotion)**: Spec 028 (telemetry sidecar) — sidecar shape MUST stay backend-agnostic.
- **Hard (post-promotion)**: Spec 033 (cost enforcement) — must survive the refactor.
- **Hard (post-promotion)**: Spec 042 (autonomy backend defaults) — per-backend mappings must be preserved.
- **Hard (pre-promotion)**: Concrete non-CLI use case materializes — THIS is one of the two promotion triggers.
- **Soft**: Spec 011 (per-flow LLM routing) — SUBSUMED by this spec post-promotion.
- **Soft**: Spec 041 (release infra v2) — CI gate for FR-008/009.

## Acceptance coverage

**Pre-promotion**: No acceptance coverage. This spec is design-space only.

**Post-promotion**: Acceptance cells populated by `/speckit.tasks` AFTER both promotion triggers fire.

| User Story | Evidence |
|---|---|
| US1 — CLI runtimes survive the refactor unchanged | _(deferred to tasks.md — promotion-gated; not implementable until rule-of-three / dual-trigger fires)_ |
| US2 — Second backend (HTTP API or Ollama) validates abstraction | _(deferred to tasks.md — promotion-gated; not implementable until rule-of-three triggers)_ |
| US3 — Cost guardrail survives across backends | _(deferred to tasks.md — promotion-gated; not implementable until rule-of-three / dual-trigger fires)_ |
| US4 — Spec 011 subsumed cleanly | _(deferred to tasks.md — promotion-gated; not implementable until rule-of-three / dual-trigger fires)_ |
| US5 — Spec 042 per-backend autonomy survives | _(deferred to tasks.md — promotion-gated; not implementable until rule-of-three / dual-trigger fires)_ |

## Out of Scope

- A first-class HTTP API client implementation. That's a downstream spec; 047 just makes the abstraction admit one.
- Multi-vendor consensus (different vendors for different consensus members in spec 037). Out of v1 (per Q3).
- UI for backend selection (web dashboard, GUI). `settings.yaml` is the surface.
- Vendor-specific cost optimization (Anthropic prompt-caching specifics, OpenAI batch API). Each backend's own polish; not 047's concern.
- Authentication management (rotating API keys, OAuth flows). Backend-specific; not 047's contract.
- Streaming output handling (delta-by-delta token streaming). v1 is request-response; streaming is a v2 extension if needed.

---

*This spec is **BLOCKED**. Do not run `/speckit.plan` or `/speckit.tasks` against it until BOTH promotion triggers fire (≥3 Tier-1 source-module ports complete + a concrete non-CLI use case materializes). Until then, this spec is a constraint-preservation document.*
