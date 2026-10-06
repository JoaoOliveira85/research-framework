# Contract: Managed-Fetch Agent I/O (spec 054 FR-002..005)

**Status:** PROPOSED (ships with spec 054 / 0.9.0)
**Builds on:** spec-020 `contracts/signal-payload.schema.json` (reused verbatim),
spec-028 `contracts/dispatch-protocol.contract.md` (the dispatch path), spec-051
`contracts/preflight.contract.md` (the fail-closed gate).
**Amends:** `specs/020-code-bridge/contracts/manifest.schema.json` — adds an
**optional** `managed: boolean` property (additive; `required` unchanged).

A **managed** module's fetch is performed by an MCP-capable Claude Code subagent
through the framework's existing `agent_call.dispatch()` path, **not** a
subprocess extractor. The agent emits the **same `SignalPayload`** a subprocess
extractor would, so everything downstream is transport-agnostic (FR-003). This
contract defines (1) the manifest declaration, (2) the routing rule, (3) the
managed-fetch request the framework sends, (4) the response the agent MUST emit,
(5) the fail-closed rules, and (6) the dispatch/MCP wiring.

---

## 1. Manifest declaration

```yaml
# <vault>/modules/<name>/manifest.yaml
managed: true          # spec 054 FR-001. Optional, default false.
```

- Default `false` ⇒ subprocess extractor (today's path, unchanged).
- `parse_manifest()` (`source_bridge/discovery.py`) reads `bool(raw.get("managed",
  False))` — defensive: any non-`true` value ⇒ unmanaged.
- `managed` is a **module property** (Clarifications Q3). The source stays
  declarative; the module declares spec-020 `triggers`; there is **no per-source
  `managed` field**.

## 2. Routing rule (FR-002)

In `orchestrator._process_source`, **before** the version-probe/cache check:

```
if manifest.managed and not force_off:   →  managed_fetch(...)
else:                                     →  extract_source(...)   # unchanged subprocess path
```

- `force_off` is a settings/CLI override that globally disables the managed
  transport. When force-off applies to a managed module, the module is treated as
  unavailable for this run (recorded, not silently empty — see §5).
- Unmanaged routing is **byte-identical** to pre-feature (SC-002).

## 3. Managed-fetch request (framework → agent)

The framework dispatches `agent_call.dispatch(stage="managed_fetch", prompt,
vault_dir=…, cycle_dir=…, timeout_s=…)`. The `prompt` MUST contain:

| element | content |
|---------|---------|
| instruction | "Fetch the source below using your MCP tools and return ONLY a SignalPayload JSON object." |
| module few-shot | the module's managed few-shot (`schema_examples` / managed `*.md`) showing the target `facts` shape |
| `source` | the routed `sources.yaml` record (JSON) |
| `source_id` | the resolved per-source id |
| `raw_mode` | boolean — when true, instruct the agent to use the raw envelope (§4.2) |

MCP tool access is **NOT** in the prompt — it is supplied by the
`managed_fetch` stage executor's `args` in `settings.yaml` (e.g. an MCP-config
flag + an allowed-tools flag). See §6.

## 4. Managed-fetch response (agent → framework)

The agent MUST emit a single JSON object parseable as a spec-020
`SignalPayload` (the framework extracts it with the same `_extract_json_blob`
the extractor uses, tolerating surrounding prose).

### 4.1 Default — facts-schema mode (FR-003 default)

```json
{
  "source_version": "<stable version/etag/timestamp the agent observed>",
  "verdict": "ok",
  "truncated": false,
  "partial": false,
  "facts": { "...module-specific structured facts per the few-shot..." },
  "notable": [
    {"observation": "...", "confidence": "high", "evidence_ref": "..."}
  ]
}
```

The framework stamps `module`, `source_id`, `bridge_version`, and `extracted_at`
after parse (exactly as `extract_source` does), so the agent need not echo them.

### 4.2 Opt-in — raw-content envelope (FR-003, Clarifications Q2)

When `raw_mode` is requested, the agent wraps raw fetched content inside the
existing `facts` object — **no new top-level field, no schema change**:

```json
{
  "source_version": "...",
  "verdict": "ok",
  "truncated": false,
  "partial": false,
  "facts": { "raw_mode": true, "raw": "<verbatim fetched content>" },
  "notable": []
}
```

Facts-schema mode is the **default**; raw mode is opt-in for cases where the
pipeline wants something specific the facts-schema would obscure.

### 4.3 Verdicts

| condition | verdict |
|-----------|---------|
| source fetched, facts present | `ok` |
| source reachable but no new/notable content | `empty` |
| agent could not fetch (MCP error past preflight, bad source, etc.) | `error` |

## 5. Fail-closed rules (FR-005, US2, SC-003)

A managed module MUST NEVER produce a **silent empty success** and MUST NEVER
crash the cycle. Two layers:

1. **Preflight gate (primary).** The managed module's mandatory spec-051
   `preflight()` probes MCP availability. When MCP is unavailable it returns
   `verdict: "fatal_fail"` with a machine-readable message. The orchestrator
   (`run_extraction`) already logs a WARN and skips the module
   (`continue`) — the cycle proceeds, other modules unaffected. The
   spec-048-v2 ledger then records the source `ACCESS_FAIL` / `NOT_REACHED`
   (NOT `USED`) via the SAME logic as an unmanaged source (SC-004).
2. **Fetch-time guard (defense in depth).** If the agent returns empty/garbage
   stdout (no parseable SignalPayload), `_agent_dispatch_fetch` returns `None`
   and the orchestrator's existing failed-source path records a non-`USED`
   outcome — never a silent success. A non-zero dispatch exit or timeout maps the
   same way.

**Prohibited:** mapping a missing-MCP managed module to a `verdict=ok` empty
payload (that would let the ledger falsely record the source as considered —
the exact failure the ledger exists to catch).

## 6. Dispatch + MCP wiring (FR-004, Principle IV)

- The fetch goes through `agent_call.dispatch(stage="managed_fetch", ...)`. **No
  script calls an MCP server directly** (FR-008 stubs the direct-Python path);
  the LLM-dispatch guard stays satisfied and **its allowlist stays EMPTY**.
- MCP tools reach the agent via the `managed_fetch` stage executor's `args` in
  `settings.yaml` (the existing settings→executor→`args` channel; no new
  dispatch parameter). Example shape (illustrative — exact flags are an
  environment concern):

  ```yaml
  stages:
    managed_fetch:
      executor:
        runtime: claude
        model: <model>
        args: ["--mcp-config", "<path>", "--allowedTools", "mcp__Atlassian__*"]
        timeout_s: 600
  ```

## 7. Pluggable fallback seam (FR-004, Clarifications Q1)

`managed_fetch()` is structured as:

```
if (bespoke := _bespoke_for(manifest)) is not None:
    return bespoke(...)        # future per-module robust fetch — NOT implemented in v1
return _agent_dispatch_fetch(...)   # the implemented fallback
```

- v1 implements **only** the fallback (`_agent_dispatch_fetch`); `_bespoke_for`
  always returns `None`.
- The seam is required in v1 so a future bespoke per-module fetch can take
  precedence without re-plumbing the orchestrator.

## 8. Conformance checklist

- [ ] `parse_manifest` reads `managed` (default false); five in-tree modules
      remain unmanaged (SC-002).
- [ ] manifest.schema.json gains optional `managed` boolean; `required`
      unchanged.
- [ ] `_process_source` routes `managed=true` → `managed_fetch`,
      `false` → `extract_source` (byte-identical).
- [ ] `managed_fetch` returns a `SignalPayload` shape-identical to a subprocess
      module's for the same source (SC-001).
- [ ] raw-mode round-trips through `facts.raw` with no schema change.
- [ ] no MCP ⇒ managed preflight `fatal_fail` ⇒ skip-with-WARN, source NOT
      `USED`, no crash (SC-003, 100%).
- [ ] empty/garbage agent stdout ⇒ non-`USED` outcome, never silent success.
- [ ] dispatch goes through `agent_call.dispatch`; dispatch-guard allowlist
      EMPTY (Principle IV).
- [ ] fallback seam present; bespoke branch declared but absent in v1.
- [ ] (FR-009) O'Reilly key reads settings file → env fallback (separate from
      managed; O'Reilly is unmanaged).
