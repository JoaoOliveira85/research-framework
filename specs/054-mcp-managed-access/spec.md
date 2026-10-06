---
spec_number: 054
title: MCP-Managed Source Access
status: CLARIFIED
priority: high
priority_reason: |
  v1.0.0-rc1 Wave 1 / run-enablement. The codebase-vault's primary INTENT
  sources are Confluence + Jira, which are reachable only through MCP servers —
  not from a plain spec-020 subprocess extractor. Without this, the codebase-vault
  run cannot consider its required sources, so it fails the source-consideration
  ledger and cannot "ace" the test. Run-critical.
created: 2026-06-03
specified: 2026-06-03
source_input: |
  User direction across the 2026-06-02/03 planning sessions: source modules that
  need MCP (Jira/Confluence/GitHub-MCP/M365/Slack) cannot be fetched by the
  current subprocess extractor model. Add a per-module `managed` capability that
  delegates the fetch to an MCP-capable Claude Code subagent (default OFF, opt-in
  for the runs). Direct in-process MCP is stubbed. O'Reilly stays a subprocess
  module but its key moves to a settings file. (Memory: mcp-managed-access.)
---

> **Landed on `main` 2026-08-30** from the long-lived `054-mcp-managed-access` branch so the design work is not stranded on a branch. **Not implemented**, and no tracking issue yet.

**Status:** planned — SPECIFIED — authored 2026-06-03. Next: `/speckit.clarify` (3 open
questions below) → `/speckit.plan` → `/speckit.tasks` → TDD implement. **Wave 1 →
0.9.0; run-enablement (gates the codebase-vault run).** Builds on spec 020
(source-module subprocess contract) and Principle IV (agent-script separation).

# Feature Specification: MCP-Managed Source Access

**Feature Branch**: `054-mcp-managed-access`

## Problem

Spec-020 source modules run as **isolated subprocesses** — the framework spawns
`extractor.py` and exchanges a JSON contract over stdin/stdout. A plain
subprocess has **no MCP access**: it cannot reach the Jira / Confluence /
GitHub-MCP / Microsoft-365 / Slack servers, which exist only inside a Claude Code
**agent** context. So any source that is reachable *only* via MCP cannot be
fetched under today's extractor model.

This blocks the upcoming **codebase-vault** run: its primary **intent** sources
are **Confluence + Jira** (MCP-only). With no way to fetch them, the run cannot
*consider* its required sources — which means it fails the source-consideration
ledger (spec 048 v2) and cannot "ace" the evaluation. The reference-vault may
similarly want GitHub-MCP for PR/issue context.

The framework already has the right seam: **Principle IV** says scripts
orchestrate and **agents** do the fetching/LLM work, and the LLM-dispatch guard
forbids scripts from calling agents directly. MCP access is an *agent* capability.
So a source that needs MCP should be fetched by an **agent task**, not a script
subprocess — the framework just needs to route those sources differently.

## Solution (WHAT, not HOW)

Add a per-module **`managed`** capability:

- A module declared **`managed: true`** is fetched by **delegating to an
  MCP-capable Claude Code subagent** (via the framework's existing agent-dispatch
  path) instead of spawning a plain subprocess extractor. The subagent uses the
  configured MCP tools to retrieve the source and emits the **same spec-020
  SignalPayload JSON contract** (facts-schema, `source_id`, `source_version`,
  `verdict`, `truncated`/`partial`, …).
- Because the **output contract is identical**, everything downstream — consensus,
  the source-consideration ledger, note-writing — cannot tell a managed fetch
  from an unmanaged one. Only the *fetch transport* differs.
- **Default OFF.** Every module is an unmanaged subprocess unless it declares
  `managed: true`. Existing modules (youtube / reddit / rss / oreilly / code) are
  unchanged.
- **Direct in-process MCP from Python is explicitly out of scope (stubbed).** A
  subprocess can't safely hold the user's MCP credentials; the managed-agent path
  is the *only* supported MCP route.

This is **run-enablement, not a new subsystem** — it reuses the spec-020 contract
and the existing agent-dispatch path; it adds a routing branch + a manifest flag.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Fetch an MCP-only intent source (Priority: P1) 🎯 MVP

The codebase-vault declares a `confluence` (and/or `jira`) module as
`managed: true`. During a cycle, the orchestrator routes that module's fetch to
an MCP-capable subagent, which uses the Atlassian MCP tools to retrieve the pages
and returns the module's facts JSON. The source then appears **`USED`** in the
source-consideration ledger.

**Why P1**: this is the unblocker for the codebase-vault run; without it, the
vault's authoritative intent sources are unreachable.

**Independent Test**: with a stubbed MCP-capable agent (fake-agent returning a
canned facts payload), a managed module produces a SignalPayload **byte-shape-
identical** to what an unmanaged subprocess module would produce for the same
source, and the ledger marks it `USED`.

**Acceptance Scenarios**:

1. **Given** a module with `managed: true` and an available MCP-capable agent,
   **When** the orchestrator runs source extraction, **Then** the managed fetch is
   dispatched as an agent task (not a subprocess) and returns a valid spec-020
   SignalPayload.
2. **Given** the managed fetch's payload, **When** downstream consensus /
   ledger / note-writing consume it, **Then** they process it identically to an
   unmanaged module's payload (no special-casing downstream).

### User Story 2 — Misconfigured MCP fails closed, loudly (Priority: P1)

A managed module is invoked in a context where MCP is unavailable (no MCP server
configured, or the agent lacks the tool). The module is reported **skipped with a
WARN** and a clear reason — never a **silent empty success** (which would let the
ledger falsely record the source as "considered") and never an unhandled crash.

**Why P1**: silent missing-sources is the exact failure the source-consideration
ledger exists to catch; a managed source that quietly returns nothing would
defeat the eval. Fail-closed mirrors the spec-051 preflight posture.

**Independent Test**: a managed module run with no MCP context yields a
`skipped`/WARN verdict with a machine-readable reason, and the ledger records the
source as `ACCESS_FAIL` (or `NOT_REACHED`) — not `USED`, not a crash.

**Acceptance Scenarios**:

1. **Given** `managed: true` and no MCP-capable agent available, **When**
   extraction runs, **Then** the module is reported skipped-with-WARN and the
   cycle continues (other modules unaffected).
2. **Given** the skip, **When** the ledger is computed, **Then** the source is
   NOT marked `USED`.

### User Story 3 — Unmanaged modules are unchanged; managed is opt-in (Priority: P2)

All existing modules keep running as subprocesses with no behaviour change;
`managed` defaults to `false`; a vault opts a module in explicitly.

**Independent Test**: with no manifest changes, the five existing modules produce
identical behaviour to pre-feature (the spec-020 + spec-051 test suites stay
green).

### User Story 4 — Credentialed unmanaged sources read their key from settings (Priority: P2)

O'Reilly (API-key auth, **not** MCP) stays a subprocess module, but its key moves
from environment-only to a **settings file** that survives `./vault update`, so
the credential isn't lost on upgrade and credential config is consistent across
modules.

**Independent Test**: O'Reilly authenticates from a settings-file key with no env
var set, and the key survives a simulated `./vault update`.

## Requirements *(mandatory)*

### Manifest + routing — FR-001..003
- **FR-001**: The spec-020 `manifest.yaml` schema gains a **`managed: bool`** field
  (**default `false`**). Absent → unmanaged (subprocess), preserving every
  existing module.
- **FR-002**: The source-bridge orchestrator **branches on `managed`**: unmanaged
  → spawn the subprocess extractor (today's path, unchanged); managed → dispatch
  an MCP-capable agent fetch.
- **FR-003**: A managed fetch returns the **same spec-020 SignalPayload JSON
  contract** as a subprocess extractor (`module`, `source_id`, `source_version`,
  `verdict`, `truncated`, `partial`, `facts`, `notable`, …). Downstream consumers
  MUST require no managed-vs-unmanaged special-casing. **(Clarifications Q2)** The
  **default** emission is the module's facts-schema JSON (LLM-structured per the
  module's `few-shot.md`). The contract MAY ALSO support an **opt-in raw-content
  mode** — raw fetched content wrapped in a JSON envelope (e.g. `{"raw": "…"}`
  inside the same payload) — for cases where the pipeline wants something specific
  the facts-schema would obscure. Facts-schema stays the default.

### Behaviour, safety, observability — FR-004..008
- **FR-004**: The managed fetch is dispatched through the framework's **existing
  agent-call path** (Principle IV: scripts orchestrate, agents fetch). No script
  calls an MCP server directly; the LLM-dispatch guard remains satisfied. This
  agent dispatch is the only path implemented now and is known-good. **(Clarifications
  Q1)** The managed-fetch entry point MUST be structured as a **pluggable seam** so
  a future *bespoke* per-module fetch (a more robust, source-specific
  implementation) can take precedence, with the agent dispatch as the **fallback**
  — conceptually `if bespoke_available: bespoke() else: agent_dispatch()`. The seam
  is required in v1 even though only the fallback (agent-dispatch) branch is
  implemented; long-term a managed module is a thin wrapper whose *default*
  behaviour is to delegate to the dispatcher.
- **FR-005**: **Fail-closed.** A managed module invoked without an available MCP
  context produces a **skip-with-WARN** verdict (machine-readable reason logged),
  never a silent empty success and never an unhandled crash — consistent with the
  spec-051 preflight posture.
- **FR-006**: **Default OFF / opt-in.** Every existing module (youtube, reddit,
  rss, oreilly, code) remains unmanaged with **no behaviour change**.
- **FR-007**: A managed fetch is **observable** on the existing telemetry surfaces
  (spec 028 sidecars + spec 048 `bridge.log` / logs) so it is as debuggable as a
  subprocess extraction.
- **FR-008**: **Direct in-process MCP from Python extractors is out of scope
  (stubbed).** The managed-agent path is the only supported MCP route; the spec
  records the stub so a future spec can add a direct path if ever needed.

### Credential config — FR-009
- **FR-009**: Credentialed **unmanaged** modules read their secret from a
  **settings file** (not env-only) that survives `./vault update`. O'Reilly's
  `OREILLY_API_KEY` is migrated to this pattern as the reference case. (Managed
  sources authenticate via the MCP server's own session — the framework does not
  store their credentials.)

## Success Criteria *(mandatory)*

- **SC-001**: A managed module fetches an MCP source and the framework records its
  facts in a SignalPayload **shape-identical** to an unmanaged module's (verified
  on a fixture with a stubbed MCP-capable agent).
- **SC-002**: With `managed` unset (default), all five existing modules produce
  **byte-identical** behaviour to pre-feature (spec-020 + spec-051 suites green).
- **SC-003**: A managed module with no MCP context yields a **skip-with-WARN**
  verdict **100%** of the time — never a silent empty success.
- **SC-004**: The spec-048-v2 ledger marks a managed source `USED` /
  `ACCESS_FAIL` / `NOT_REACHED` using the **same** logic as an unmanaged source.
- **SC-005**: O'Reilly authenticates from a settings-file key with **no env var
  set**, and the key **survives** a `./vault update`.

## Key Entities

- **Managed module** — a spec-020 module with `manifest.managed: true`; fetched by
  an agent, not a subprocess.
- **MCP-capable fetch agent** — the Claude Code subagent the framework dispatches
  for a managed fetch; holds the MCP tool access and emits the module's
  facts-schema JSON.
- **SignalPayload contract** — the existing spec-020 JSON output; reused verbatim
  so managed/unmanaged are interchangeable downstream.
- **Settings-file credential** — the relocated home for unmanaged credentialed
  modules' secrets (FR-009).

## Acceptance coverage

Draft — evidence cells will be populated by `/speckit.tasks` for this spec.
Listed for the ADR-0008 guard so the spec is accepted into the queue (the guard
refuses any G/W/T-bearing spec without this section). **This spec is not
implemented**, so every cell is the deferred marker rather than a test path
that does not exist.

| User Story | Evidence |
|------------|----------|
| US1 — Fetch an MCP-only intent source | _(deferred to tasks.md — spec not implemented)_ |
| US2 — Misconfigured MCP fails closed, loudly | _(deferred to tasks.md — spec not implemented)_ |
| US3 — Unmanaged modules unchanged; managed is opt-in | _(deferred to tasks.md — spec not implemented)_ |
| US4 — Credentialed unmanaged sources read their key from settings | _(deferred to tasks.md — spec not implemented)_ |

## Assumptions

- The managed fetch reuses the **existing agent-dispatch path** (`agent_call.py` /
  the runtime adapters) — a new dedicated mechanism is not assumed (see open Q1).
- The MCP-capable subagent **emits the module's facts-schema JSON itself** (like
  other agent stages produce structured output per a few-shot), rather than
  returning raw content for a separate structuring step (see open Q2).
- `managed` is declared **per module** in `manifest.yaml`; a per-source or
  per-run override is not assumed in v1 (see open Q3).
- The actual `confluence` / `jira` vault modules are **authored when the
  codebase-vault is built** (they *use* this mechanism); this spec delivers the
  mechanism + an updated `_template` / reference, not the business modules.
- The runtime environment provides the MCP servers (Atlassian, GitHub, …); their
  configuration is an environment concern, out of scope here.

## Dependencies

- **Builds on**: spec 020 (source-module subprocess contract + `manifest.yaml`
  schema), Principle IV (agent-script separation + LLM-dispatch guard), spec
  028/048 (telemetry surfaces).
- **Feeds**: the source-consideration ledger (spec 048 v2) — managed sources must
  be ledger-visible.
- **Gates**: the **codebase-vault run** (Confluence/Jira intent sources).

## Out of Scope

- Direct in-process MCP client calls from Python extractors (stubbed; FR-008).
- Authoring the concrete `confluence` / `jira` codebase-vault modules (done at
  vault-build time using this mechanism).
- MCP server configuration / installation (environment concern).
- Any change to unmanaged-module behaviour beyond the FR-009 credential
  relocation.

## Clarifications

### Session 2026-06-03 — RESOLVED

- **Q1 (managed-fetch transport) → reuse `agent_call.py` NOW, behind a fallback
  seam.** The agent-call dispatch is the only implemented path and is known-good;
  but structure the entry point as a **pluggable seam** so a future *bespoke*
  per-module fetch can take precedence, with the agent dispatch as the **fallback**
  (`if bespoke_available: bespoke() else: agent_dispatch()`). v1 implements only
  the fallback branch. (FR-004 updated.)
- **Q2 (what the managed agent emits) → facts-schema JSON by default, with an
  opt-in raw-content mode.** Default = the module's facts-schema JSON; ALSO support
  a raw-content-wrapped-in-JSON envelope for cases where the pipeline wants
  something specific the facts-schema would obscure. (FR-003 updated.)
- **Q3 (declaration granularity) → per-module `managed` + spec-020 `triggers`;
  source stays declarative; + a settings/CLI force-off override; no per-source
  field.** Aligns with the 048-v2 routing decision (sources are declarative;
  modules declare URL triggers; the pipeline routes source→module; "managed" is a
  module property). A managed module's mandatory `preflight()` (spec 051) is the
  natural home for the MCP-availability probe that drives US2's fail-closed
  skip-with-WARN.
