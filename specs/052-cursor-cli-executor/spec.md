---
spec_number: 052
title: Cursor CLI Executor — third cost-driven runtime
status: Implemented (2026-06-08) — foreman Arm A+B green; PR open, pending merge into 1.0.0rc4
priority: high
priority_reason: |
  Cost. Cursor's `agent`/`cursor-agent` CLI is a candidate cheaper executor
  for batch research stages (flat-rate / cheaper-per-token vs. claude/codex
  metered API). The codex token cap hit 2026-06-01; a third runtime gives the
  operator a cost lever WITHOUT building the full vendor abstraction (spec 047).
  Promoted INTO the critical path 2026-06-08: the codex workspace ran out of
  credits mid-validation-run, so cursor-agent (flat-rate Cursor subscription,
  ~$0 marginal) is now the operator's only affordable runtime for the vault
  validation runs.
target_version: 1.0.0rc4
created: 2026-06-02
source_input: |
  User request 2026-06-02 (mid-spec-051): "add cursor cli support (via `agent`
  cli command) … market it with high priority because of cost reasons." A
  dispatch-surface feasibility sweep (Explore agent, same session) mapped the
  executor layer: pluggable at the command level (`_RUNTIME_ADAPTERS` registry
  in scripts/agent_call.py already holds claude/codex/python), hardcoded-dual at
  the cost/telemetry level (~24 `if agent == "claude"/"codex"` sites across
  agent_call.py + cost_estimator.py + budget_guard.py + settings.py).
---

**Status:** shipped(2026-06-08, PR #131) — SHIPPED **1.0.0rc4** (PR #131, squash `c635a11`). **Marked high-priority (cost).** All four
`/speckit.clarify` questions (below) were resolved **empirically** by probing
the installed `cursor-agent` CLI (`--help`, `--list-models`, `--output-format
json|stream-json`); `plan.md` + `tasks.md` produced and executed. foreman
Arm A (21/21) + Arm B (PASS) green; Copilot review (3 findings) addressed.

> **Relationship to spec 047 (Backend-Agnostic Agent Layer):** 047 is the
> long-horizon *design-space* spec for making the agent layer vendor-/interface-
> agnostic (HTTP API direct, local Ollama). It is **🚧 BLOCKED** behind a
> promotion gate that requires a concrete **non-CLI** use case. Cursor's
> `agent`/`cursor-agent` is a **CLI** runtime — it slots into the *existing*
> `_RUNTIME_ADAPTERS` registry and does **not** satisfy (nor require) 047's
> abstraction. This spec is the smaller, near-term, CLI-only delivery; it is a
> **precursor** that exercises part of the registry pattern and feeds real
> signal into 047 later. **This spec MUST NOT grow into the 047 abstraction** —
> if it starts to, stop and promote 047 instead.

# Feature Specification: Cursor CLI Executor — third cost-driven runtime

**Feature Branch**: `052-cursor-cli-executor`

## Input

The pipeline dispatches every LLM call through a single surface
(`scripts/agent_call.py`, per ARCHITECTURE.md §6 "Single LLM dispatch surface")
and currently supports exactly two real LLM runtimes — `claude` and `codex` —
plus a `python` script runtime. Both LLM runtimes are metered API back-ends.
Cursor ships an agentic CLI (`agent` / `cursor-agent`) that may be materially
cheaper for batch research stages (the cost-amortised, latency-insensitive part
of the workload). Adding it as a **third runtime** gives the operator a cost
lever — choose Cursor per-stage or per-vault for the expensive batch stages
(scout, note-writer) while keeping claude/codex where they're proven.

This is a CLI-only addition. It deliberately does **not** build the vendor-
agnostic abstraction (spec 047) — it extends the existing CLI-adapter registry.

## Why high priority (cost)

- The codex token cap took effect **2026-06-01**; spec 033 enforces hard budget
  caps but cannot *reduce* unit cost — only a cheaper runtime can.
- Research stages run in batch and are latency-insensitive, so a cheaper-but-
  slower runtime is an acceptable trade there. Cursor is the closest drop-in
  (it's a CLI agent, like claude/codex) — lowest integration cost of any
  cost-reduction lever currently available.

## Clarifications

### Session 2026-06-08 — resolved EMPIRICALLY by probing the installed CLI

All four questions were answered by running the installed `cursor-agent`
(`~/.local/bin/cursor-agent`, v2026.06.04) directly, so no assumptions remain.

- **Q1 (FR-001 / cost-output contract) — GATING → RESOLVED (partial: tokens
  yes, dollars no).** `cursor-agent -p --output-format json` returns a single
  result object; `--output-format stream-json` returns NDJSON ending in a
  `result` event. Both carry a machine-parseable
  `usage:{inputTokens,outputTokens,cacheReadTokens,cacheWriteTokens}` plus
  `duration_ms`/`duration_api_ms` — but **no dollar figure**, because Cursor
  bills against a flat-rate subscription (no per-call price).
  **Decision:** capture the **real token counts** from the runtime, and derive
  the **dollar via the spec-033 estimator** (flat-rate ⇒ the $ is an estimate,
  not a bill). Record a new additive sidecar `cost_source: "runtime_tokens"`
  (tokens measured, dollar estimated) — distinct from `runtime` (both measured),
  `estimated` (neither measured), and `none`. Budget enforcement: the **dollar
  cap still applies** (on the estimated $, exactly like codex's estimate path),
  and the **codex token cap is generalised** to a metered-token cap that also
  covers cursor (FR-006). This keeps spec-033's "never a silent $0" invariant.
- **Q2 (FR-002 / binary + invocation) → RESOLVED.** Binary is `cursor-agent`
  (resolve via `CURSOR_BIN` env override, default `cursor-agent`). Runtime /
  `settings.yaml` name is `cursor-agent`. Non-interactive argv:
  `cursor-agent -p --output-format stream-json --model <m> --trust [--force]
  [--sandbox enabled|disabled] [--approve-mcps] [extra args…]`; the prompt is
  piped on **stdin** (like claude/codex). `-p/--print` is the headless mode;
  `--trust` is REQUIRED for headless workspace-trust (otherwise it prompts);
  `--force`/`--yolo` auto-approve tool use; `--approve-mcps` auto-approves MCP
  servers.
- **Q3 (FR-005/FR-007 / model identifiers) → RESOLVED via `--list-models`.**
  Cursor exposes its own ids: `composer-2.5`/`composer-2.5-fast`,
  `gpt-5.x-codex-*` (effort suffixes), `gpt-5.5-high`, `gpt-5.4-high`,
  `claude-opus-4-8-thinking-*`, etc. **Default tier→model map**
  (`_CURSOR_MODEL_TIERS`, overridable via `settings.yaml::tiers`):
  `basic→composer-2.5-fast`, `standard→gpt-5.4-high`,
  `expert→claude-opus-4-8-thinking-high`.
- **Q4 (FR-008 / autonomy + permissions) → RESOLVED.** Headless unattended
  cycles use `-p --trust --force` (no interactive prompt), with
  `--sandbox`/`--approve-mcps` as needed. The vault write-confinement concern
  that forced codex onto `--cd`/sandbox-workspace-write maps here to
  `--workspace <vault>` + `--sandbox` (documented; full autonomy-config
  scaffolding stays deferred to spec 042 — cross-reference, don't duplicate).

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Cursor runs a research stage end-to-end (Priority: P1)

The operator sets `default_executor.runtime: cursor-agent` (or per-stage
`stages.note-writer.runtime: cursor-agent`) in `settings.yaml`. A `./vault
research` cycle dispatches the note-writer stage through Cursor's CLI; notes are
written, the cycle completes, and the per-call sidecar records `agent:
cursor-agent`.

**Why this priority**: This is the whole point — a working third runtime.

**Independent Test**: With a fake `cursor-agent` binary (via `CURSOR_BIN`
pointing at a test stub, mirroring the `CLAUDE_BIN`/`CODEX_BIN`/`YT_DLP_BIN`
pattern), run a fixture cycle with the note-writer stage routed to Cursor.
Verify: the stub is invoked with the expected argv; a note is produced; the
sidecar's `agent` field is `cursor-agent`.

### User Story 2 — Cost is captured (or honestly degraded) (Priority: P1)

A Cursor-dispatched call records a cost figure in its spec-028 sidecar so spec
033 budget enforcement still fires. Per Q1: if Cursor emits a real cost signal,
it's captured verbatim (`cost_source: billed`); if not, a tiktoken estimate is
recorded (`cost_source: estimated`) and the operator is warned.

**Why this priority**: A runtime that silently reports `$0` would let a vault
blow its budget undetected — a regression against spec 033's hard-cap invariant.
Honest cost (real or flagged-estimate) is non-negotiable.

**Independent Test**: Run a Cursor-routed call; assert the sidecar has a
non-null `cost_usd` and a `cost_source` field. With budget caps set below the
recorded cost, assert `BUDGET_PAUSED` fires identically to claude/codex.

### User Story 3 — Existing runtimes are byte-identical (Priority: P1)

Adding Cursor changes nothing for claude/codex vaults: same sidecars, same
budget behaviour, same argv, no test modifications.

**Why this priority**: Load-bearing invariant — a cost lever must not regress
the proven runtimes.

**Independent Test**: Full suite green with no modifications to existing
claude/codex tests; spec-028 sidecars for claude/codex byte-identical pre/post.

## Requirements *(mandatory — DRAFT, refine at clarify/plan)*

- **FR-001 (GATING)**: Resolve Cursor's cost-output contract (Q1) and define how
  a Cursor call's `cost_usd` + `tokens_in/out` land in the spec-028 sidecar,
  including a `cost_source: billed|estimated` field.
- **FR-002**: Add a `_cursor_cmd(executor)` adapter to `_RUNTIME_ADAPTERS`
  (`scripts/agent_call.py:398`) building the Cursor argv; `CURSOR_BIN` override.
- **FR-003**: Widen the executor enum/validation everywhere it hardcodes
  `{"claude","codex"}` — `DefaultAgent` Literal + `_VALID_AGENTS` + the
  `_parse_default_agent` error message (`pipeline/settings.py:16,19,754`),
  `_LLM_AGENT_NAMES` (`scripts/agent_call.py:434`), and the LLM-dispatch guard's
  `_LLM_BINARIES` (`tests/_helpers/test_llm_dispatch_guard.py:31`) so a direct
  Cursor invocation outside `agent_call.py` is also forbidden.
- **FR-004**: Cost-estimator parity — add Cursor calibration + tiktoken-encoding
  selection branches in `pipeline/cost_estimator.py` (the `if agent == "codex" /
  "claude"` sites ~L156/171) and the `DEFAULT_ESTIMATOR_CALIBRATION` map
  (cost_estimator.py + settings.py).
- **FR-005**: Stream/output parsing — decide whether Cursor needs a dedicated
  output parser or reuses the claude `stream-json` path. The
  `use_stream = agent_name == "claude" and agent_kind == "real"` gate
  (`agent_call.py:866`) must be generalised or given a Cursor branch.
- **FR-006**: Budget-guard parity — generalise the codex-token-cap branches
  (`pipeline/budget_guard.py:254,362`) so Cursor is covered by an appropriate
  cap (or explicitly documented as dollar-cap-only).
- **FR-007**: Tier→model mapping for Cursor (Q3); `settings.yaml::tiers`
  override path works.
- **FR-008**: Fake-agent + tests — the `tests/_helpers/fake_agent.py` shim is
  binary-name-agnostic (intercepts by shim replacement), so basic flows need no
  new handler; add a `CURSOR_BIN` test stub + contract tests mirroring the
  youtube `_BIN` env-override pattern. Document the autonomy posture (Q4),
  cross-referencing spec 042.
- **FR-009**: Scaffold/template — if the generator writes runtime-specific
  config, add the Cursor branch (or document that Cursor needs no scaffolded
  config). Keep `settings.yaml` examples for the new runtime.

## Dispatch-surface seam map *(from the 2026-06-02 Explore sweep — the effort driver)*

| Layer | Pluggable? | Sites to touch |
|---|---|---|
| Command construction | ✅ registry (`_RUNTIME_ADAPTERS`) | +1 adapter fn |
| Executor selection / enum | ❌ hardcoded dual | `DefaultAgent`, `_VALID_AGENTS`, `_parse_default_agent`, `_LLM_AGENT_NAMES` (4) |
| Cost estimation | ❌ inline `if agent ==` | tiktoken-encoding choice + calibration + historical lookups (~6) |
| Budget enforcement | ❌ codex-specific | codex-token-cap branches (2) |
| Stream/cost capture | ❌ claude-specific | `use_stream` gate + stream-json parser (claude schema) |
| LLM-dispatch guard | ❌ `{"claude","codex"}` | `_LLM_BINARIES` (1) |
| Fake-agent shim | ✅ binary-agnostic | optional stage handler |

**Synthesis**: dispatch is pluggable; **cost/telemetry is the coupling** (~24
sites total). Effort is gated by Q1 — if Cursor emits no parseable cost, the
work is "adapter + enum widening + estimated-cost fallback + tests"; if it does,
add a Cursor stream parser.

## Out of Scope

- The full vendor-/interface-agnostic abstraction (HTTP API, Ollama, OpenAI,
  Gemini) — that is **spec 047**, which this spec must not absorb.
- Multi-backend consensus quorums (spec 037).
- Cursor-specific autonomy-config scaffolding beyond documentation (spec 042).
- Per-flow routing config rework (spec 011 history; use shipped `settings.yaml`
  per-stage overrides).

## Success Criteria *(DRAFT)*

- A fixture cycle routes a stage through a stubbed `cursor-agent` and produces
  notes; sidecar records `agent: cursor-agent` + a non-null `cost_usd` with
  `cost_source`.
- spec-033 budget caps fire identically for Cursor calls.
- Zero changes to existing claude/codex tests; their sidecars byte-identical.
- LLM-dispatch guard rejects a direct Cursor invocation outside `agent_call.py`.

## Open follow-ups

- GitHub tracking issue not yet created (sandbox/remote constraint at draft
  time). Create with `type:spec, epic:<bucket>, priority:high` and link from the
  ROADMAP Active entry.
