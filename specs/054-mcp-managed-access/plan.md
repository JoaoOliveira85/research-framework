# Implementation Plan: MCP-Managed Source Access

**Branch**: `054-mcp-managed-access` | **Date**: 2026-06-03 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/054-mcp-managed-access/spec.md` (CLARIFIED 2026-06-03)

## Summary

Spec-020 source modules run as isolated subprocesses (`extractor.py` spawned over
a stdin/stdout JSON contract). A plain subprocess has **no MCP access**, so a
source reachable only through an MCP server (Confluence / Jira / GitHub-MCP /
M365 / Slack) cannot be fetched. This blocks the codebase-vault run, whose
authoritative *intent* sources are Confluence + Jira.

The fix is small and surgical: add a per-module manifest flag **`managed: bool`
(default `false`)** and **one routing branch** in the source-bridge
orchestrator. An unmanaged module spawns the subprocess extractor (today's path,
untouched); a managed module instead delegates the fetch to an MCP-capable
Claude Code subagent **through the existing `agent_call.dispatch()` path**
(Principle IV: scripts orchestrate, agents fetch). The agent emits the **same
spec-020 `SignalPayload` JSON** as a subprocess extractor, so everything
downstream (consensus, ledger, note-writing) is identical — only the fetch
transport differs.

Per the clarifications: the managed-fetch entry point is structured as a
**pluggable fallback seam** (`if bespoke_available: bespoke() else:
agent_dispatch()` — v1 implements only the agent-dispatch fallback); the agent's
output is the module's **facts-schema JSON by default** plus an **opt-in
raw-content-in-JSON envelope**; routing is **source-declarative** (the module
declares spec-020 `triggers`; `managed` is a module property) with a
**settings/CLI force-off** override and **no per-source field**; fail-closed is
driven by the module's mandatory spec-051 `preflight()` probing MCP
availability → skip-with-WARN. O'Reilly (API-key, not MCP) stays a subprocess
module but its key moves from env-only to a settings file (FR-009).

This is **run-enablement, not a new subsystem.** It reuses the spec-020 contract
and the spec-025/028 agent-dispatch path; it adds a manifest field, a routing
branch, and a thin managed-fetch module.

## Technical Context

**Language/Version**: Python 3.11+ (per `pyproject.toml` `requires-python`,
constitution Technology Constraints).
**Primary Dependencies**: stdlib + existing `pyyaml ≥ 6.0` (manifest parse) +
`jinja2 ≥ 3.1` (prompt template). **No new runtime dependency** — Principle V
upheld. MCP tool access is supplied by the Claude Code runtime at dispatch time
(an environment concern), not a Python package.
**Storage**: filesystem under the vault root. Managed fetches reuse the existing
signal sidecar tree (`_pipeline/sources/<module>/signals/`) and the spec-028
agent-call sidecars (`_pipeline/cycles/cycle-NNN/agent-calls/`). No new artifact
shape; the managed fetch writes the identical `SignalPayload` a subprocess
extractor would.
**Testing**: `pytest` (`.venv/bin/python -m pytest`) — seven-tier pyramid
(ADR-0008). Hermetic — a **fake MCP-capable agent** (extend `fake_agent.py`)
intercepts `dispatch()` exactly as it does for every other LLM stage; the
LLM-dispatch guard allowlist stays EMPTY.
**Target Platform**: macOS / Linux CLI (the framework's runtime).
**Project Type**: single project (CLI + pipeline library under
`src/research_framework/`).
**Performance Goals**: managed fetch wall-clock is bounded by the existing
`dispatch()` timeout (`executor.timeout_s`, default 600s) — no new perf surface.
**Constraints**: offline-capable for unmanaged paths (Principle V); a managed
fetch needs the MCP server at runtime but **fails closed** (skip-with-WARN) when
it is absent — it never crashes the cycle and never silently succeeds.
**Scale/Scope**: the five existing modules are unchanged; this adds the
mechanism + an updated `_template`/reference. The concrete `confluence`/`jira`
modules are authored at codebase-vault-build time (out of scope here).

## Constitution Check

*GATE: must pass before Phase 0. Re-checked after Phase 1 design.*

| Principle | Assessment |
|-----------|-----------|
| **I. Script-Validated Quality Gates** | Unaffected. Managed payloads flow through the same `validate_payload` + downstream gates as subprocess payloads — no agent self-validation introduced. |
| **III. Test-First (TDD)** | Honored. Contract tests for the routing branch, the managed-fetch seam, the fail-closed preflight skip, and the facts/raw envelope are written before implementation. Fake MCP agent — no live LLM. |
| **IV. Agent-Script Separation (KEY)** | **This is the load-bearing principle.** The fetch is done by an **agent** (MCP is an agent capability); the **script** only orchestrates/routes and validates. No script calls an MCP server directly (FR-008 stubbed). The managed fetch goes through the existing `agent_call.dispatch()` path — the LLM-dispatch guard (`tests/_helpers/test_llm_dispatch_guard.py`) stays satisfied; **its allowlist MUST remain EMPTY**. The seam does NOT add a new `claude`/`codex` subprocess in `src/` — it reuses `dispatch()`. |
| **V. Offline-First, No External Persistence** | No new dependency; no telemetry; no cloud persistence by the framework. MCP credentials live in the user's MCP server session, **never** stored by the framework (spec Key Entities + FR-009 note). Unmanaged paths stay fully offline. |
| **VIII. No Placeholders** | The `_template`/reference managed wrapper is a **working implementation** (delegates to the dispatcher), not a stub. The bespoke branch is an unimplemented-but-declared seam — surfaced explicitly, not a silent TODO. |
| **X. Vault History is Append-Only Git** | Unaffected — managed fetches write signals like any extraction; the cycle's existing auto-commit covers them. |

**Verdict: PASS.** No principle violation; no Complexity Tracking entry required.
The single sensitive point is Principle IV — the design keeps the agent as the
sole MCP caller and routes through the existing dispatch path, so the invariant
strengthens rather than weakens.

**Ask-First boundary check**: this does **not** change Phase 1/2/3 sequencing,
validation exit codes, frontmatter schema, naming convention, or
`coverage-targets.json` structure. It **adds** an optional manifest field
(`managed`, default false → fully backward-compatible) and migrates one
credential's home (FR-009). No new runtime network dependency is added by the
framework itself. No Ask-First trigger fires.

## Project Structure

### Documentation (this feature)

```text
specs/054-mcp-managed-access/
├── spec.md                       # CLARIFIED input
├── plan.md                       # This file
├── research.md                   # Phase 0 — dispatch path / seam shape / decisions
├── data-model.md                 # Phase 1 — manifest field, SignalPayload reuse, raw envelope
├── quickstart.md                 # Phase 1 — author a managed module end-to-end
├── contracts/
│   └── managed-fetch.contract.md # Phase 1 — managed-fetch agent I/O contract
└── tasks.md                      # Phase 2 (/speckit.tasks — NOT created here)
```

### Source Code (repository root)

```text
src/research_framework/pipeline/source_bridge/
├── discovery.py          # CHANGE: ModuleManifest gains `managed: bool` (default False);
│                         #         parse_manifest reads raw["managed"]
├── orchestrator.py       # CHANGE: _process_source routing branch —
│                         #         manifest.managed → managed_fetch(...) instead of extract_source(...)
├── managed_fetch.py      # NEW: the pluggable fallback seam.
│                         #   managed_fetch(vault_dir, manifest, source, source_id, bridge_version)
│                         #   → if _bespoke_for(manifest): bespoke() else: _agent_dispatch_fetch()
│                         #   _agent_dispatch_fetch builds the prompt (few-shot + source + raw-mode flag),
│                         #   calls agent_call.dispatch(stage="managed_fetch", ...), parses stdout into
│                         #   a SignalPayload, fails closed on empty/garbage.
├── extractor.py          # UNCHANGED (the unmanaged path)
├── signal.py             # UNCHANGED — SignalPayload reused verbatim (raw mode = facts envelope key)
└── preflight_runner.py   # UNCHANGED — managed modules' preflight probes MCP availability;
                          #   run_preflight already fails closed → orchestrator skips the module

src/research_framework/modules/_template/
├── manifest.yaml         # (reference) — show `managed: false` + a comment on opting in
├── preflight.py          # (reference) — show the MCP-availability probe pattern for managed modules
└── managed_fetch_fewshot.md   # NEW (reference) — few-shot the managed agent uses to emit SignalPayload

src/research_framework/modules/oreilly/
└── extractor.py          # CHANGE (FR-009): read OREILLY_API_KEY from settings file, env as fallback

src/research_framework/pipeline/settings.py
                          # CHANGE: surface the managed force-off override + the credential settings block

scripts/agent_call.py     # UNCHANGED dispatch() signature is reused; managed_fetch passes stage="managed_fetch"
                          #   (MCP tool flags flow via the settings executor `args`, as today)

specs/020-code-bridge/contracts/manifest.schema.json
                          # CHANGE: add optional `managed` boolean (default false) — backward-compatible amendment

tests/pipeline/source_bridge/
├── test_managed_routing.py        # NEW — manifest.managed routes to managed_fetch, not subprocess
├── test_managed_fetch_seam.py     # NEW — fallback seam: bespoke-absent → agent_dispatch; payload shape
├── test_managed_fail_closed.py    # NEW — no MCP → preflight fatal_fail → module skipped-with-WARN (US2)
├── test_managed_raw_envelope.py   # NEW — opt-in raw-content envelope round-trips in SignalPayload
└── test_managed_default_off.py    # NEW — absent `managed` ⇒ subprocess; 5 modules unchanged (US3, SC-002)

tests/modules/oreilly/
└── test_oreilly_settings_key.py   # NEW — key from settings file, no env (US4 / FR-009 / SC-005)

tests/_helpers/fake_agent.py       # CHANGE: add a `managed_fetch` handler emitting a canned SignalPayload
tests/_helpers/fake_agent_scenarios/managed_fetch/   # NEW — canned managed-fetch responses
```

**Structure Decision**: single project. The feature lands entirely inside the
existing `pipeline/source_bridge/` package (one new module, two edits), plus a
manifest-schema amendment, the `_template` reference, the O'Reilly FR-009 edit,
and the test/fake-agent additions. No new top-level directory.

## Phases

### Phase 0 — Research (→ `research.md`)

Resolve the three design questions the clarifications already steered, and pin
the exact seams:

1. **How the agent-dispatch path carries MCP tools.** `agent_call.dispatch(stage,
   prompt, ...)` resolves an executor from `settings.yaml`; the claude CLI's MCP
   access is supplied via the executor's `args` (e.g. `--mcp-config` /
   `--allowedTools`) — already settings-driven. The managed fetch uses a
   dedicated `stage="managed_fetch"` so vault authors can wire MCP flags for
   that stage only. **Decision**: no new dispatch parameter; MCP flows through
   the existing settings→executor→`args` channel.
2. **The fallback-seam shape.** `managed_fetch()` looks up an optional bespoke
   handler (`_bespoke_for(manifest)`, v1 always returns `None`) then calls the
   agent-dispatch fallback. **Decision**: registry-by-convention (module may ship
   a `bespoke_fetch.py`; absent in v1) so the seam is real but only the fallback
   branch is wired.
3. **Where fail-closed lives.** Reuse spec-051 `preflight()`: a managed module's
   preflight probes MCP availability and returns `fatal_fail` when absent;
   `orchestrator.run_extraction` already skips a `fatal_fail` module
   with a WARN. **Decision**: no new fail-closed path — preflight is the single
   gate (US2).

Also confirms: SignalPayload reuse (no schema change), raw-envelope key choice,
and the O'Reilly settings-key precedence (settings → env fallback).

### Phase 1 — Design & Contracts (→ `data-model.md`, `contracts/`, `quickstart.md`)

- **`data-model.md`**: the `managed` manifest field (type, default, schema
  amendment), `SignalPayload` reuse (managed == unmanaged shape), and the
  raw-mode envelope (`facts.raw` string + `facts.raw_mode: true`, opt-in).
- **`contracts/managed-fetch.contract.md`**: the managed-fetch agent I/O
  contract — the request the framework builds (source record + source_id +
  few-shot + raw-mode flag), the response the agent MUST emit (a SignalPayload
  JSON blob extractable by the same `_extract_json_blob` the extractor uses),
  the fail-closed rule (empty/garbage/no-MCP → `verdict=error` / skip-with-WARN),
  and the dispatch-stage / MCP-flag wiring.
- **`quickstart.md`**: author a managed module end-to-end (manifest
  `managed: true` + triggers, the MCP-probing preflight, the few-shot, the
  settings MCP-flag wiring, the force-off override) + how to verify with the
  fake agent.

### Phase 2 — Tasks (`/speckit.tasks`, NOT created here)

Tasks will be enriched with `### Testing Requirements` blocks by the test-design
subagent (ADR-0010) before implementation. Anticipated task clusters: manifest
field + schema amendment; routing branch; `managed_fetch.py` seam; fail-closed
wiring + US2; raw-envelope; fake-agent handler + scenarios; O'Reilly FR-009
settings key; `_template` reference; docs.

## Test Approach

- **Fake MCP-capable agent** — extend `tests/_helpers/fake_agent.py` with a
  `managed_fetch` handler that returns a canned `SignalPayload` JSON (and a
  raw-envelope variant). It intercepts `dispatch()` through the vault's
  `scripts/agent_call.py` shim exactly like every other stage, so **no live
  `claude`/`codex`** runs and the dispatch-guard allowlist stays EMPTY
  (Principle IV).
- **Tier-2 contract tests** for: the manifest `managed` parse + default; the
  routing branch (managed → seam, unmanaged → subprocess); the fallback seam
  (bespoke-absent → agent dispatch) producing a payload **shape-identical** to a
  subprocess module (SC-001); the raw envelope round-trip; the O'Reilly settings
  key (SC-005).
- **Fail-closed test (US2 / SC-003)**: a managed module whose preflight reports
  MCP-unavailable → orchestrator records skip-with-WARN, the source is NOT
  `USED`, no crash. Asserts the WARN reason is machine-readable.
- **Regression lock (US3 / SC-002)**: with no manifest change, the five existing
  modules run as subprocesses and the spec-020 + spec-051 suites stay green.
- **`./build.sh --quality`** before any release touching `pipeline/` — the three
  spec-022 fixtures use only unmanaged modules, so the quality baseline must show
  **zero regression** (managed is opt-in and absent from fixtures).

## Complexity Tracking

No Constitution Check violations — table intentionally empty.
