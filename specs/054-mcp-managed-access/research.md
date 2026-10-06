# Phase 0 Research: MCP-Managed Source Access

**Spec**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md) · Date: 2026-06-03

The three clarifications (Q1 fallback seam, Q2 facts-default + raw opt-in, Q3
per-module declarative routing + force-off) already steer the design. This file
pins the exact seams against the shipped code so `/speckit.tasks` is mechanical.

---

## D1 — How the agent-dispatch path carries MCP tools

**Question**: a subprocess extractor has no MCP. How does the managed agent get
MCP tool access, and what does the framework have to pass?

**Findings (verified in source):**

- The in-process dispatch entry point is
  `scripts/agent_call.py::dispatch(stage, prompt, *, tier, agent, vault_dir,
  cycle_dir, timeout_s)` → returns `AgentCallResult(stdout, stderr, exit_code,
  cost_usd, …)`. It is already called in-process from
  `pipeline/_cycle_helpers.py` and `pipeline/plan_narrator.py`.
- `dispatch()` resolves an **executor** from `settings.yaml` via
  `_executor_for_dispatch(settings, stage, agent_name)` →
  `_resolve_executor(settings, stage)`. The executor carries `runtime`
  (`claude`/`codex`/`python`), `model`, and **`args`** (a list of extra CLI
  flags). `_RUNTIME_ADAPTERS["claude"] = _claude_cmd` builds
  `[claude, --model, <m>, *executor["args"], --print]`.
- **MCP tool access for the claude CLI is supplied through those `args`** — the
  CLI flags that point at an MCP config and allow MCP tools (e.g.
  `--mcp-config …`, `--allowedTools …`). These are *settings-driven today*; no
  code change is needed in `agent_call.py` to carry them.

**Decision D1**: the managed fetch dispatches with a **dedicated
`stage="managed_fetch"`**. Vault authors wire the MCP flags into that stage's
executor `args` in `settings.yaml`, scoped to managed fetches only. **No new
`dispatch()` parameter; no change to `_RUNTIME_ADAPTERS`.** MCP availability is
an *environment + settings* concern (spec Assumptions); the framework just
selects the stage and passes the prompt.

**Why not a new dispatch param for MCP tools?** It would duplicate what settings
`args` already express, couple the bridge to CLI-flag specifics, and create a
second MCP-config surface. Routing through the existing settings→executor→args
channel keeps one source of truth and keeps Principle IV's dispatch path
untouched (allowlist stays EMPTY).

---

## D2 — The fallback-seam shape (Clarifications Q1)

**Question**: the entry point must be a pluggable seam (`if bespoke_available:
bespoke() else: agent_dispatch()`) but v1 implements only the fallback. What is
the concrete shape?

**Decision D2**: a single function in a new module
`pipeline/source_bridge/managed_fetch.py`:

```python
def managed_fetch(vault_dir, manifest, *, source, source_id, bridge_version,
                  cycle, raw_mode=False) -> SignalPayload | None:
    bespoke = _bespoke_for(manifest)          # v1: always None
    if bespoke is not None:
        return bespoke(...)                    # not implemented in v1
    return _agent_dispatch_fetch(...)          # the implemented fallback
```

- `_bespoke_for(manifest)` is the seam: it looks for an optional module-shipped
  bespoke handler (convention: a `bespoke_fetch.py` next to `extractor.py`, or a
  manifest hint). **In v1 it ALWAYS returns `None`** — the bespoke branch is
  declared and tested-as-absent, never wired. This satisfies FR-004's "seam
  required in v1, only fallback implemented" without shipping dead bespoke code.
- `_agent_dispatch_fetch(...)` builds the prompt (D3), calls
  `agent_call.dispatch(stage="managed_fetch", prompt, vault_dir=…, cycle_dir=…,
  timeout_s=…)`, then parses `result.stdout` into a `SignalPayload` using the
  same `_extract_json_blob` the extractor already uses (`extractor.py` imports it
  from `pipeline/verifier`). Returns `None` on empty/garbage (→ fail-closed at
  the caller, mirroring the extractor's `isolated_call`-returns-`None` path).

**Why a registry-by-convention rather than an abstract base class?** Modules are
subprocess-isolated and cannot import from `src/` (the spec-020/051 invariant), so
a Python ABC across the boundary is impossible. A convention (`bespoke_fetch.py`
present?) keeps the seam real and module-author-friendly while v1 ships only the
in-`src/` fallback. This mirrors spec 052's `_RUNTIME_ADAPTERS` registry style.

---

## D3 — What the managed agent emits + the request shape (Clarifications Q2)

**Question**: facts-schema JSON by default, raw-content envelope opt-in. What
does the framework send, and what must come back?

**Findings:**

- A subprocess extractor returns a `SignalPayload` dict (`signal.py`:
  `module, source_id, source_version, bridge_version, extracted_at, verdict,
  truncated, partial, facts, notable[]`). `extract_source` calls
  `SignalPayload.from_dict(data)` then stamps `module`/`source_id`/`bridge_version`.
- The module's few-shot (`schema_examples`, e.g. `few-shot.md`) is what teaches
  an LLM stage to emit the module's facts shape elsewhere in the pipeline.

**Decision D3 (request)**: `_agent_dispatch_fetch` renders a prompt = the
module's managed few-shot + the `source` record + the `source_id` + a **raw-mode
flag**. The agent uses its MCP tools to fetch and returns a SignalPayload JSON
blob. The framework stamps `module`/`source_id`/`bridge_version` after parse
(same as `extract_source`), so the agent need not echo them perfectly.

**Decision D3 (response — default vs raw)**:
- **Default (facts-schema)**: `facts` is the module's structured facts dict;
  `verdict=ok|empty|error`; `notable[]` as usual. Indistinguishable downstream
  from a subprocess payload (FR-003, SC-001).
- **Raw opt-in**: when `raw_mode` is set, the agent wraps raw fetched content in
  the SAME payload: `facts = {"raw": "<content>", "raw_mode": true}`. It stays a
  valid `SignalPayload` (the schema's `facts` is an open object), so no schema
  change and no downstream special-casing — a later structuring stage can read
  `facts.raw`. Raw mode is a per-fetch flag (settings/stage-level), **not** a
  per-source field (Q3).

**Why an envelope key inside `facts` rather than a top-level `raw` field?**
Adding a top-level field would change the SignalPayload schema and break
FR-003's "byte-shape-identical, no downstream special-casing". `facts` is already
an open `dict[str, Any]`, so `facts.raw` carries raw content with **zero schema
churn** — the spec's FR-003 explicitly allows `{"raw": "…"}` *inside the same
payload*.

---

## D4 — Where fail-closed lives (Clarifications Q3, FR-005, US2)

**Question**: a managed module with no MCP context must skip-with-WARN, never
silently succeed, never crash. Where?

**Findings:**

- Spec-051 made `preflight()` **mandatory** for every module
  (`discovery.parse_manifest` raises if absent). The orchestrator runs it once
  per module (`orchestrator.run_extraction`): a `fatal_fail` verdict logs a WARN
  and `continue`s — the module is skipped, the cycle proceeds (other modules
  unaffected). `run_preflight` is itself fail-closed (crash/timeout/garbage →
  `fatal_fail`).

**Decision D4**: a managed module's `preflight.py` **probes MCP availability**
(e.g. checks the MCP config / a settings flag the runtime sets) and returns
`fatal_fail` when MCP is absent. This reuses the spec-051 skip-with-WARN path
verbatim — **no new fail-closed mechanism**. This is exactly the
Clarifications-Q3 statement: "A managed module's mandatory `preflight()` is the
natural home for the MCP-availability probe that drives US2's fail-closed
skip-with-WARN."

**Second layer (defense in depth)**: even past preflight, if the managed agent
returns empty/garbage at fetch time, `_agent_dispatch_fetch` returns `None` and
the orchestrator's existing `_maybe_salvage_failed` / `failed` path records a
non-`USED` outcome — never a silent empty success. The spec-048-v2 ledger then
classifies the source `ACCESS_FAIL` / `NOT_REACHED` using the SAME logic as an
unmanaged source (SC-004).

**Note (real unknown, surfaced)**: the *exact* signal a managed preflight reads
to know "MCP is available" depends on how the Claude Code runtime exposes MCP
configuration to a spawned preflight subprocess. The preflight cannot import
from `src/`, and it is a plain subprocess (no MCP itself). The robust v1 probe is
**a settings/env flag the orchestrator sets when the managed path is active**
(e.g. `MANAGED_MCP_AVAILABLE` derived from settings), rather than the preflight
introspecting the live MCP server. This keeps the probe deterministic and
testable. See **NEEDS CLARIFICATION** in plan/spec follow-up: confirm the probe
signal before `/speckit.tasks` finalizes the preflight contract.

---

## D5 — Routing branch placement (FR-002)

**Findings:**

- `orchestrator._process_source` is the per-source dispatch site. For `n <= 1` it
  calls `extract_source` (subprocess) via `isolated_call`; for `n > 1` it runs
  consensus over repeated extractor spawns.

**Decision D5**: branch on `manifest.managed` at the **top of `_process_source`**
(before the version-probe / cache check, since a managed fetch's version probe is
also agent-mediated). Managed → `managed_fetch(...)`; unmanaged → today's path,
**byte-identical** (SC-002). Cache/watermark and consensus still apply to managed
payloads (they consume a `SignalPayload`, transport-agnostic) — but **v1 keeps
managed at the single-fetch (`n<=1`) path** to avoid M-of-N agent dispatches
multiplying cost; consensus over managed fetches is a future extension (noted in
Out of Scope, not blocking).

---

## D6 — FR-009 O'Reilly credential relocation

**Findings:**

- `modules/oreilly/extractor.py` reads `os.environ["OREILLY_API_KEY"]`
  (`_api_key_present`, line 85-86; used at 215-221). Env is lost on
  `./vault update` (a fresh shell).

**Decision D6**: the O'Reilly extractor reads the key from a **settings file**
that survives `./vault update` (the module's `user_owned` set already preserves
`sources.yaml`; the credential file joins that preserved set), with the env var
as a **fallback** for backward compatibility. Precedence: **settings file → env
var → error (verdict=error)**. The key-leak-safety test pattern from the 0.6.0
oreilly port (sentinel-string assertion against payload+stdout+stderr) is
extended to cover the settings-file path. Memory (`mcp-managed-access`) records:
"O'Reilly stays python but key moves to a settings file."

**Real unknown (surfaced)**: the exact settings file + key name (e.g.
`<vault>/modules/oreilly/credentials.yaml::api_key`, vs a central
`settings.yaml::credentials.oreilly_api_key`). Either survives `./vault update`
if `user_owned`; the central form is more consistent with FR-009's "consistent
across modules" goal. **NEEDS CLARIFICATION** before `/speckit.tasks` pins the
filename.

---

## Decisions summary

| ID | Decision | Drives |
|----|----------|--------|
| D1 | MCP via existing settings→executor→`args`; dedicated `stage="managed_fetch"`; no dispatch-param change | FR-004, Principle IV |
| D2 | `managed_fetch()` seam: `_bespoke_for()` (v1 → None) else `_agent_dispatch_fetch()` | FR-004 (Q1) |
| D3 | Agent emits `SignalPayload`; facts-default; raw opt-in via `facts.raw` envelope (no schema change) | FR-003 (Q2) |
| D4 | Fail-closed via the module's spec-051 `preflight()` MCP probe → skip-with-WARN; + empty-fetch second layer | FR-005, US2, SC-003 |
| D5 | Routing branch at top of `orchestrator._process_source`; managed stays single-fetch in v1 | FR-002, SC-002 |
| D6 | O'Reilly key from settings file (preserved on update), env fallback | FR-009, SC-005 |

## Open unknowns to resolve before /speckit.tasks

1. **Managed preflight MCP-availability signal** (D4 note) — the deterministic
   probe the preflight reads. Leaning: a settings/env flag the orchestrator sets,
   not live MCP introspection.
2. **O'Reilly credential file location + key name** (D6) — per-module vs central
   settings; both survive update, central is more consistent.

Both are pinning details, not architectural; neither blocks the plan.
