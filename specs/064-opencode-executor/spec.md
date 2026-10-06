# Feature Specification: opencode Executor (provider-agnostic agentic runtime)

**Feature Branch**: `064-opencode-executor`
**Created**: 2026-06-11
**Status**: shipped(2026-06-13, PR #146) — ✅ **SHIPPED 1.0.0rc7 — PR #146, squash `d0ce765` (merged 2026-06-13).** Full trail: `/speckit.specify` → clarify → plan → tasks → analyze (remediated, 0 CRITICAL) → blind foreman test-design (42 Testing Requirements) → implement (all 32 tasks, TDD). ~40 new opencode tests; full fast suite green (2612 passed, 0 regressions); ruff clean; FR-014 non-regression holds. The plan-time risk (FR-010 containment) is resolved + **live-verified** — `opencode run --dir <vault>` write-scoped a real $0 ollama run. **Copilot review (6 findings)** addressed in `81ea140` on the same branch before merge — preflight executability check (bare-name vs explicit-path), `local_providers` wired end-to-end (resolver + cache key + cost class + preflight), telemetry sidecar on preflight failure, matrix label whitespace normalization, quickstart test-path fix, test-isolation via digest-unique module name. See `plan.md` + `research.md` + `contracts/` + `tasks.md`. Closes issue #145. **Sibling deliverable**: spec **065** (local-model agentic fit — SPIKE) — captures the empirical finding that the executor + box are fine but local 27–30B models don't *complete* the autonomous stages on this prompt surface (`v1.0.0` validation campaign therefore runs on `cursor-agent`).
**Supersedes / tombstones**: Spec 047 (Backend-Agnostic Agent Layer). 047's umbrella goal — "stop being CLI-and-Anthropic-only; reach any model provider" — is delivered here through a concrete agentic executor instead of a speculative three-stage interface refactor. 047's shipped v1 (the Ollama **HTTP** dispatch primitive, 1.0.0rc5 / PR #138) is **superseded**: that run proved a raw HTTP backend is *non-agentic* (it returns text but cannot write the stage output files scout / note-writer require). opencode closes that gap because it is an agentic runtime that writes files like `claude` / `codex` / `cursor-agent` do.
**Absorbs**: Spec 011 (per-flow LLM routing) — per-stage model selection is expressed as opencode's per-stage model choice (inherited from 047, which had absorbed 011).
**Precedent**: Spec 052 (Cursor CLI executor, SHIPPED 1.0.0rc4) — `cursor-agent` was wired as a third first-class runtime through the single `_RUNTIME_ADAPTERS` dispatch surface in `scripts/agent_call.py`. opencode follows that exact pattern as the fourth runtime; the difference is that opencode is explicitly **provider-agnostic** — one executor that can drive Ollama (local, $0), OpenAI, Anthropic, Google, OpenRouter, and others by configuration, with no new framework code per provider.

**Input**: User description: "Add opencode as a first-class executor where I can use Ollama or any other model provider. Reframe spec 047: Ollama is just a *backend* (model provider), opencode is the actual *frontend/executor*."

## Clarifications

### Session 2026-06-11 — framing

- **Executor vs backend split** — The framework's runtime axis is the **executor** (the agentic program the framework shells out to: `claude`, `codex`, `cursor-agent`, now `opencode`). The **model provider / backend** (Anthropic, OpenAI, Ollama, Google, OpenRouter…) is a *property the executor is configured with*, not a framework-level runtime. opencode is the first executor whose whole value proposition is that the provider is a free-floating configuration choice. This is the reframe: 047 treated "Ollama" as a backend the *framework* dispatches to over HTTP; 064 treats Ollama as a model *opencode* talks to, and the framework only ever sees "opencode".
- **Why this supersedes the 047 HTTP path** — The 2026-06-08 validation run found that the framework's stages are *file-producing*: scout, note-writer, verifier, etc. write artifacts the next stage reads. A raw HTTP call returns a string and stops there, so it can't run a real cycle. opencode (like the other CLI executors) runs an agent loop with filesystem tools, so it satisfies the stage-output contract the HTTP primitive could not.

### Session 2026-06-11 — clarify

- Q: For v1 acceptance, is a live (billed) hosted-provider cycle on the critical path, or is provider-agnosticism proven structurally + on local Ollama with live hosted opt-in? → A: **Structural + local gates v1; the live hosted run is `live_llm` opt-in.** v1 "done" = a real local-Ollama cycle plus a *structural* proof (fake-agent harness) that a hosted-provider config is accepted and dispatched with **no** framework code change (FR-005). An actual billed hosted-provider cycle is the canonical `live_llm` opt-in surface (consistent with spec 056 / benchmark conventions) — it is **not** a hard acceptance gate. Rationale: the driving need is local/$0; no paid run or provider-credential dependency belongs on the critical path.
- Q: Should the spec-056 benchmark harness be able to sweep tasks through opencode (and through arbitrary models behind it)? → A: **Yes.** opencode MUST be a dispatchable benchmark cell, and because the benchmark already validates executors against `_RUNTIME_ADAPTERS ∪ _HTTP_RUNTIMES` and sweeps a per-executor `models` list, adding opencode to `_RUNTIME_ADAPTERS` (FR-001/002) makes `{opencode × any-model × task}` cells work with **no benchmark code change**. A guard test MUST assert opencode is in the benchmark's allowed-runtime set so this can't silently regress. (Confirmed against `src/research_framework/benchmark/matrix.py::valid_runtimes`.)
- Q: Nice-to-have — a custom label per executor so the same executor can be swept under different combinations? → A: **Yes, but low-effort/SHOULD, not MUST.** Add an OPTIONAL `label` to the benchmark matrix executor block; when present it replaces the runtime name in the cell key + report so e.g. `opencode-local-qwen` and `opencode-gpt5` can coexist as distinct, human-readable cells for the same `opencode` runtime. Absent `label` ⇒ today's `task__executor__model` behavior is byte-identical (pure addition). Explicitly capped at a small matrix.py/reporter change — not worth more.

### Session 2026-06-11 — live verification (opencode → local ollama)

A real opencode run was executed against the operator's ollama box
(`localhost:11434`, model `ollama/qwen3-coder:30b-64k`, $0) to retire the plan's
`VERIFY@IMPL` risks. Findings (folded into `research.md` / `contracts/`):

- **Agentic file-write CONFIRMED** — `opencode run --dir <tmp> --format json …` used its
  `write` tool to create the requested file with exact contents, exit 0. This is the
  capability the 047 HTTP primitive lacked (FR-009 is achievable).
- **`--dir` containment CONFIRMED** — the write resolved against `--dir` and landed
  inside it; nothing was created outside (FR-010). (A hard out-of-dir *denial* test
  is still the SC-005 implementation target.)
- **Cost telemetry shape CONFIRMED** — `--format json` is **NDJSON**; `step_finish`
  events carry `part.tokens.{input,output,total,…}` + a real `part.cost`. Local ⇒
  `cost: 0` + real tokens ⇒ measured `$0`. For metered providers opencode derives a
  real per-call dollar from its models.dev pricing catalog, so the common metered
  case is `cost_source: "runtime"` (real $) — *richer* than cursor; the estimator
  (`runtime_tokens`) is a fallback, not the primary path. The opencode provider is
  already configured in `~/.config/opencode/opencode.json` (FR-005 provider plumbing
  is operator-owned, as assumed).

### Session 2026-06-12 — performance note (local-model practicality)

A deeper live session refined the local-Ollama picture (the executor code is
correct and unchanged; this is an operational characteristic, not a defect):

- **opencode carries a large fixed per-call context** — a trivial `"say hi"`
  prompt sent **~13.5k input tokens** (system prompt + ~37 skills + tool schemas).
  On a 30B local model the first (cold) call pays ~25s to load + prefill that;
  once warm, the same call is ~2s.
- **Known limitation**: for local models this overhead, multiplied by agentic
  multi-step loops and cold model reloads (e.g. a benchmark switching models per
  cell), makes full research stages slow and timeout-prone. opencode is best
  paired with **fast / hosted providers**, or with a **warm, single** local model
  and a realistic per-call timeout. The $0-local cost story stands; the *latency*
  story is the caveat.
- A first live benchmark run also exposed a **benchmark-harness** bug (spec 056,
  out of scope here): the runner leaks orphaned opencode processes on timeout
  (one held the box ~3h) and lacks a per-cell timeout/`args` knob. Tracked
  separately; the 064 executor is unaffected.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Run a full vault cycle on opencode driving a local Ollama model (Priority: P1)

The operator sets `opencode` as the vault's executor and points it at a local Ollama model (the box the operator already runs). A full research cycle (scout → harvest → note-writing → verification → post-processing) completes end-to-end, producing the same stage artifacts a `claude`/`codex`/`cursor-agent` cycle produces. Marginal model cost is $0; the run is bounded by the wall-clock guardrail, not the dollar cap.

**Why this priority**: This is the headline capability and the thing the 047 HTTP primitive could not do — a *non-CLI / non-Anthropic, agentic, file-writing* cycle. It directly unblocks offline-first and zero-marginal-cost vault runs after the codex token cap / cursor cost pressure.

**Independent Test**: Configure a fixture vault with `default_agent: opencode` + a local Ollama model; run one cycle against the fake-agent harness (and, opt-in `live_llm`, against a real Ollama box). Verify every expected stage output file exists, the cycle commits, and the run report records `executor: opencode` with the underlying model.

**Acceptance Scenarios**:

1. **Given** a vault configured with `opencode` + a local Ollama model, **When** a cycle runs, **Then** all stage output files are written and the cycle commits exactly as it would under `claude`.
2. **Given** the same run, **When** it completes, **Then** the spec-028 sidecar records `cost_usd: 0.0` with **real** token counts and `cost_source` marking the cost as measured-local (not estimated, not silently zero).
3. **Given** an unattended run, **When** the wall-clock cap (spec 033) is reached, **Then** the cycle pauses via `BUDGET_PAUSED` even though the dollar cost never moved.

---

### User Story 2 — Swap the model provider without touching framework code (Priority: P1)

The operator changes the opencode model from a local Ollama model to a hosted provider (e.g. OpenAI, Anthropic, OpenRouter, Google) by editing configuration only. No framework code, no new adapter, and no new `settings.<x>.yaml` peer profile is required per provider — the provider/model is an opencode configuration value.

**Why this priority**: This is the "any other model provider" half of the request and the structural payoff of the reframe — the framework gains N providers for the cost of integrating *one* executor. It is what makes 064 a genuine replacement for 047's per-backend ambitions.

**Independent Test**: Run the fixture cycle on the fake-agent harness with two different opencode model configs (one local, one hosted) changing *only* configuration; assert the dispatch carries the hosted config and the sidecar `executor` is `opencode` in both while the recorded model differs — **no framework source change** between the two. A real billed hosted-provider cycle is validated separately as a `live_llm` opt-in (not part of this gate; see Clarifications Session 2026-06-11).

**Acceptance Scenarios**:

1. **Given** a working opencode-on-Ollama vault, **When** the operator changes only the model/provider config to a hosted provider, **Then** the next cycle runs against that provider with no framework code change.
2. **Given** a metered (paid) provider behind opencode, **When** a cycle runs, **Then** the dollar cap (spec 033) is live and `BUDGET_PAUSED` can fire on cost; `cost_source` reflects how the dollar figure was obtained (measured tokens vs estimated).

---

### User Story 3 — Cost & telemetry guardrails survive on the new executor (Priority: P1)

Every opencode call lands a spec-028 telemetry sidecar and participates in the spec-033 budget tally, identically to `claude` / `codex` / `cursor-agent`. There is no path by which an opencode run produces a silent `$0`, escapes the budget tally, or skips telemetry.

**Why this priority**: Cost containment is the load-bearing reason the multi-vendor pivot exists; a new executor that bypassed it would be a regression. The 047 work already surfaced a real footgun here (a sidecar-schema mismatch silently dropping modern sidecars from the tally), so this must be explicit.

**Independent Test**: A fixture cycle on opencode asserts: (a) one sidecar per call, (b) the sidecar's executor/model fields are populated, (c) the cumulative cost the budget guard sees equals the sum of the sidecars, (d) a zero-cost local run still advances the wall-clock budget.

**Acceptance Scenarios**:

1. **Given** an opencode cycle, **When** each call returns, **Then** exactly one telemetry sidecar is written with `executor: opencode` and the resolved model.
2. **Given** a local ($0) opencode run, **When** cost is tallied, **Then** the cost is an honest measured `0.0` with real tokens — never a silent/sentinel zero.
3. **Given** a metered opencode run, **When** the cumulative dollar cost crosses the cap, **Then** `BUDGET_PAUSED` fires.

---

### User Story 4 — Writes stay contained to the vault (Priority: P1)

When opencode runs with filesystem tools enabled, its writes are confined to the vault directory — matching the containment the framework already enforces for `codex` (`--cd <vault>`) and `cursor-agent` (`--workspace <vault>`). The agent may read broadly but must not write outside the vault, and must not require an unsandboxed full-disk mode.

**Why this priority**: Containment is a shipped invariant (it is why endpoint security tolerates the framework's runs; see the rc2 fix). A new file-writing executor that wrote anywhere would reintroduce the exact pattern that previously tripped endpoint security and aborted a validation run.

**Independent Test**: Run a cycle and assert no files are created or modified outside the vault root; assert the executor is invoked with the vault-scoping option and not a full-access mode.

**Acceptance Scenarios**:

1. **Given** an opencode cycle, **When** the agent writes stage artifacts, **Then** all writes land inside the vault root and none outside it.
2. **Given** the executor invocation, **When** it is constructed, **Then** it carries the vault-scoping option (the opencode analogue of codex `--cd` / cursor `--workspace`) and never a full-disk-access flag.

---

### User Story 5 — Existing executors and autonomy behavior are unchanged (Priority: P2)

Adding opencode changes nothing for vaults on `claude` / `codex` / `cursor-agent`: their configs, sidecars, and per-cycle behavior are byte-for-byte unaffected. The spec-042 autonomy level maps onto opencode the way it maps onto the other executors (the executor adapter owns its autonomy semantics).

**Why this priority**: Non-regression of the three shipped executors is mandatory but lower-risk than the new-capability stories; it is a guardrail, not the value.

**Independent Test**: Run the full fast-loop suite before and after; assert claude/codex/cursor sidecars are byte-identical and no existing test required modification. Assert each autonomy level resolves to a defined opencode behavior.

**Acceptance Scenarios**:

1. **Given** a vault on `claude`, **When** opencode support is added, **Then** its sidecars and behavior are unchanged.
2. **Given** a vault with `autonomy_level: full-auto` on `opencode`, **When** it dispatches, **Then** opencode's autonomy mapping fires (the executor's filesystem/approval posture matches the requested level).

---

### User Story 6 — opencode is a benchmark cell; sweep any model through it (Priority: P2)

The operator runs the spec-056 benchmark with an `opencode` executor block listing several models (a local Ollama model + one or more hosted models). The harness expands `{opencode × each-model × each-task}` into cells and scores quality/cost/latency per cell — so the operator can empirically compare models *through the same executor*, and (optionally) label each combination for a readable report.

**Why this priority**: This is what turns "opencode can route any model" into evidence — the operator can decide which model to run a vault on. P2 because it rides on the executor existing (US1/US2); it is leverage, not the core capability. It is also the natural home for the "run all our tests through opencode" wish.

**Independent Test**: Point the benchmark matrix at an `opencode` block with ≥2 models; assert (a) `opencode ∈ valid_runtimes()` (guard test), (b) the cell product contains one cell per `{opencode, model, task}`, (c) with an optional `label` set, the cell key/report uses the label.

**Acceptance Scenarios**:

1. **Given** the benchmark matrix YAML, **When** it declares `{runtime: opencode, models: [...]}`, **Then** loading the matrix succeeds (opencode is an allowed runtime) and produces one cell per model×task.
2. **Given** an executor block with an optional `label`, **When** cells are built, **Then** the label replaces the runtime name in the cell key + report; absent a label, keying is unchanged.

---

### Edge Cases

- **opencode not installed / not on PATH** → preflight fails closed with a clear, actionable message (which binary, how to install), the way `cursor-agent` / `codex` absence is handled — never a confusing mid-cycle crash.
- **Configured model/provider unavailable** (Ollama box down, hosted API key missing/invalid) → fail closed at preflight where derivable, with a per-cause message; do not start a cycle that will burn a stage then die.
- **opencode produces no parseable token usage** (a model/provider that omits usage) → the sidecar still lands; cost falls back to the spec-033 estimator with `cost_source` marking it estimated — never a silent zero.
- **Local model writes malformed / partial stage artifacts** (smaller local models are less reliable than frontier CLIs) → the existing stage validation / verifier path catches it as it would for any executor; this spec does not weaken those gates to accommodate weaker models.
- **Provider switched mid-vault-history** → telemetry must let an operator see which cycles ran on which executor+model (the sidecar carries both), so a quality regression can be attributed.

## Requirements *(mandatory)*

### Functional Requirements

#### opencode as a first-class executor

- **FR-001**: The framework MUST support `opencode` as a selectable executor wherever `claude` / `codex` / `cursor-agent` are selectable, including as a valid `default_agent` / default executor and as a per-stage executor override.
- **FR-002**: opencode MUST be wired through the **single** existing dispatch surface (`scripts/agent_call.py` / `_RUNTIME_ADAPTERS`), as a peer adapter to the existing CLI runtimes — NOT as a parallel dispatch script. (This is the FR-008/009 single-dispatch invariant inherited from 047.)
- **FR-003**: opencode MUST be invoked in a headless / non-interactive mode that runs the agent loop to completion and returns a parseable result, suitable for unattended cycles.
- **FR-004**: The framework MUST ship an opencode configuration profile (the peer of `settings.codex.yaml` / `settings.cursor.yaml` / `settings.ollama.yaml`), bundled into the wheel and the vault bundle, exposing the basic/normal/flagship model-tier mapping convention used by the other executors.

#### Provider-agnostic model selection

- **FR-005**: The model provider/backend (Ollama, OpenAI, Anthropic, Google, OpenRouter, …) MUST be a *configuration* choice consumed by opencode, requiring **no** new framework adapter, dispatch branch, or per-provider `settings.<x>.yaml` to add a provider opencode already supports.
- **FR-006**: A **local** model provider (Ollama) MUST be supported with **true `cost_usd: 0.0`** and **real** measured token counts (not a sentinel), tagged with a `cost_source` that distinguishes measured-local from estimated.
- **FR-007**: A **metered** model provider behind opencode MUST report cost such that the spec-033 dollar cap is enforceable — measured tokens where the provider returns usage, otherwise the spec-033 estimator — with `cost_source` recording which path produced the dollar figure (never a silent zero).
- **FR-008**: The resolved underlying model MUST be recorded per call so a vault's cycle history is attributable to a specific executor+model pair.

#### Output-file contract (the 047-HTTP gap this closes)

- **FR-009**: An opencode cycle MUST satisfy the same stage-output-file contract the existing executors satisfy — every stage that is expected to write artifacts (scout, harvest, note-writer, verifier, post-processing) produces them, so a full cycle runs and commits.
- **FR-010**: opencode's filesystem writes MUST be contained to the vault root via the opencode analogue of codex `--cd` / cursor `--workspace`; an unsandboxed full-disk-access mode MUST NOT be required or used.

#### Guardrails survive (inherited invariants)

- **FR-011**: Every opencode call MUST emit a spec-028 telemetry sidecar in the existing backend-agnostic JSON shape, with the `executor` field set to `opencode` and the resolved model recorded.
- **FR-012**: opencode cost MUST participate in the spec-033 budget tally identically to the other executors; `BUDGET_PAUSED` MUST fire on the dollar cap (metered) and on the wall-clock cap (zero-cost local).
- **FR-013**: opencode MUST have a **defined unattended autonomy posture in v1** — the `settings.opencode.yaml` approval args (the cursor `--force --approve-mcps` analogue: opencode's permission config, or `--dangerously-skip-permissions` as the blunt fallback), contained by `--dir`. The full per-level `autonomy_level: interactive | semi-auto | full-auto` → opencode mapping is a **forward integration with spec 042** (still draft, ROADMAP #19): 064 owns the executor-level posture; 042 will add opencode to its per-executor mapping table. v1 satisfies FR-013 at the executor level only — the per-level wiring is explicitly deferred (research R5).

#### Containment of scope / non-regression

- **FR-014**: Adding opencode MUST NOT change the behavior, configs, or sidecars of `claude` / `codex` / `cursor-agent` vaults; their sidecars MUST remain byte-identical and no existing test may require modification to accommodate opencode.
- **FR-015**: opencode preflight MUST fail closed (binary missing, model/provider unreachable, credentials absent) with an actionable per-cause message before a cycle starts, where the failure is derivable ahead of dispatch.

#### Spec 011 absorbed; 047 tombstoned

- **FR-016**: Per-stage model selection (spec 011's per-flow routing) MUST be expressible as opencode's per-stage model choice; spec 011 stays SUBSUMED (now under 064).
- **FR-017**: Spec 047 MUST be marked TOMBSTONED / superseded-by-064 in its status header, with a one-line forward pointer; its shipped Ollama-HTTP primitive MUST be documented as superseded (this spec decides, at plan time, whether to retire the raw HTTP dispatch branch or leave it as dead-but-harmless — see Out of Scope).

#### Benchmark integration (spec 056)

- **FR-018**: `opencode` MUST be a dispatchable cell in the spec-056 benchmark harness — i.e. it MUST appear in `benchmark/matrix.py::valid_runtimes()` (the `_RUNTIME_ADAPTERS ∪ _HTTP_RUNTIMES` union), which it does for free once FR-001/002 land. A guard test MUST assert `opencode ∈ valid_runtimes()` so a future refactor can't silently drop it.
- **FR-019**: The benchmark MUST be able to sweep arbitrary models through opencode — an `{opencode, models: [m1, m2, …]}` executor block in the matrix YAML MUST expand to one `{opencode × m_i × task}` cell per model, with **no** benchmark code change beyond FR-018. This is the "run all our tests through opencode, any model" capability.
- **FR-020** *(SHOULD — low-effort nice-to-have)*: The benchmark matrix executor block MAY carry an OPTIONAL `label`. When present, the label replaces the runtime name in the cell key + report (e.g. `opencode-local-qwen`, `opencode-gpt5`) so the **same** runtime can be swept under several distinct, human-readable configurations. When absent, behavior is byte-identical to today's `task__executor__model` keying (pure addition). Scope is explicitly capped at a small `matrix.py` / `reporter.py` change — no broader benchmark redesign.

### Key Entities

- **Executor** — the agentic program the framework shells out to (`claude` / `codex` / `cursor-agent` / `opencode`). Selected per-vault and per-stage; recorded in telemetry. *Terminology note (axis 1): "executor" (this spec) = "**runtime**" (the `_RUNTIME_ADAPTERS` registry key in `agent_call.py`) = "**`default_agent`**" (the settings key that selects it) — three names for the same thing, inherited from the existing codebase. Do not conflate with axis 2 below.*
- **Model provider (backend)** — *(axis 2)* the LLM source the executor talks to (Ollama / OpenAI / Anthropic / Google / OpenRouter / …), a.k.a. "**provider**". For opencode this is a configuration value (`--model provider/model`), **not** a framework runtime/executor.
- **opencode configuration profile** — the bundled `settings.opencode.yaml` peer, mapping the basic/normal/flagship tier convention onto opencode model choices.
- **Telemetry sidecar (spec 028)** — per-call JSON; carries `executor`, resolved model, tokens, `cost_usd`, `cost_source`. Backend-agnostic by design.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A full research cycle completes on `opencode` driving a local Ollama model, producing every expected stage artifact and a clean commit — the thing the 047 HTTP primitive could not do.
- **SC-002**: Switching the opencode model from a local provider to a hosted provider requires **zero** framework source changes — configuration only — proven structurally on the fake-agent harness (the gate). A live billed hosted-provider cycle producing valid artifacts is validated as a `live_llm` opt-in, off the acceptance critical path (per Clarifications Session 2026-06-11).
- **SC-003**: For a local ($0) opencode run, the spec-028 sidecar shows `cost_usd: 0.0` with non-zero **real** token counts and a `cost_source` that is not the "silent/none" value; the wall-clock cap can still pause the run.
- **SC-004**: For a metered opencode run, `BUDGET_PAUSED` fires when cumulative dollar cost crosses the cap, in a fixture test.
- **SC-005**: All opencode writes in a cycle land inside the vault root; a test asserts zero out-of-vault file modifications.
- **SC-006**: The existing fast-loop suite passes unchanged; `claude` / `codex` / `cursor-agent` sidecars are byte-identical before and after; no existing test was modified to accommodate opencode.
- **SC-007**: The benchmark accepts an `opencode` executor block and expands it to one cell per `{model × task}`; a guard test asserts `opencode ∈ valid_runtimes()`. Achieved with no benchmark code change beyond the guard test (FR-018/019).
- **SC-008**: With an optional `label` on a benchmark executor block, two opencode configs (e.g. a local and a hosted model) appear as two distinct, labeled cells; with no label, cell keys are byte-identical to the pre-064 format (FR-020).

## Assumptions

- opencode is installed and authenticated out-of-band by the operator (its own provider/model config + credentials live in opencode's config, not re-implemented by the framework) — the framework consumes it, the way it consumes a logged-in `cursor-agent` or `gh`.
- opencode exposes a headless/non-interactive run mode that runs the agent loop to completion and returns a result the wrapper can parse for tokens — consistent with how `cursor-agent` is driven (spec 052).
- opencode honors a vault-scoping / working-directory option analogous to codex `--cd` and cursor `--workspace`; if it does not, FR-010 is the gating risk to resolve at plan time.
- The operator's local Ollama box (the one referenced by 047's v1) is the reference local provider for validation.
- This spec is provider-agnostic by design; the v1 **acceptance gate** is a real local-Ollama cycle + a *structural* fake-agent proof that a hosted-provider config dispatches with no framework change (FR-005). A live billed hosted-provider cycle is `live_llm` opt-in, not a gate (Clarifications Session 2026-06-11). Exhaustive per-provider certification is out of scope.
- The spec-kit `opencode` *integration* (the `.opencode/` command files / `AGENTS.md` that let `/speckit.*` run inside the opencode CLI) is a **separate, unrelated** concern from opencode-as-vault-executor; this spec does not depend on it.

## Acceptance coverage

| User Story | Evidence |
|---|---|
| US1 — local Ollama cycle ($0) | `tests/pipeline/test_opencode_executor_cycle.py::test_opencode_cycle_writes_stage_files_and_commits` + `tests/pipeline/test_opencode_executor_cycle.py::test_opencode_cycle_sidecar_honest_local_cost` + `tests/pipeline/test_opencode_executor_cycle.py::test_live_opencode_ollama_cycle_completes` _(live_llm)_ |
| US2 — provider swap by config | `tests/pipeline/test_opencode_executor_cycle.py::test_opencode_provider_swap_config_only` |
| US3 — cost + budget guardrails | `tests/scripts/test_agent_call.py::test_opencode_cost_class_metered_real_dollar_is_runtime` + `tests/pipeline/test_budget_guard_opencode.py::test_budget_paused_fires_on_dollar_cap_metered` + `tests/pipeline/test_budget_guard_opencode.py::test_budget_paused_fires_on_wall_clock_cap_local` |
| US4 — vault containment | `tests/pipeline/test_opencode_executor_cycle.py::test_opencode_command_contains_dir_and_no_full_disk_flag` + `tests/pipeline/test_opencode_executor_cycle.py::test_opencode_cycle_no_writes_outside_vault` |
| US5 — non-regression + autonomy | `tests/scripts/test_agent_call.py::test_existing_executor_sidecars_unchanged_after_opencode` + `tests/pipeline/test_opencode_executor_cycle.py::test_settings_opencode_unattended_posture_present` |
| US6 — benchmark cell + label | `tests/benchmark/unit/test_matrix.py::test_opencode_in_valid_runtimes` + `tests/benchmark/unit/test_matrix.py::test_two_opencode_blocks_distinct_labels_produce_distinct_cells` |

## Dependencies

- **Hard**: `scripts/agent_call.py` single-dispatch surface + `_RUNTIME_ADAPTERS` (the seam opencode plugs into).
- **Hard**: Spec 028 (telemetry sidecars) + spec 033 (cost enforcement) — opencode must satisfy both.
- **Hard**: Spec 042 (autonomy per-executor mapping) — opencode needs its mapping.
- **Soft**: Spec 052 (Cursor CLI executor) — the reference implementation for "add a CLI executor through the registry"; opencode mirrors its shape, including the honest-cost `cost_source` handling for non-Anthropic runtimes.
- **Subsumes**: Spec 011 (per-flow LLM routing).
- **Tombstones**: Spec 047 (Backend-Agnostic Agent Layer).

## Out of Scope

- The full "claude/codex behind a re-architected interface" three-stage refactor that 047 theorized (FR-001..006 of 047) — opencode delivers provider-agnosticism *as a fourth executor*, not by rewriting the existing three. Retiring or further abstracting the existing adapters is explicitly not part of this spec.
- Cross-executor or cross-provider consensus (one cycle quorum spanning opencode + claude, or two providers): single-executor operation in v1, consistent with 047's deferred Q3.
- Retirement of the shipped Ollama-HTTP dispatch branch (047 v1): the *decision* of whether to delete it or leave it dormant is a plan-time call recorded here; this spec does not pre-commit to ripping it out.
- Re-implementing opencode's own provider/credential management inside the framework — opencode owns that.
- Certifying every model provider opencode supports — v1 validates one local + one hosted to prove the agnostic seam (FR-005).
