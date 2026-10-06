# Quickstart: Author a Managed (MCP) Source Module

**Spec**: [spec.md](./spec.md) · **Contract**:
[contracts/managed-fetch.contract.md](./contracts/managed-fetch.contract.md) ·
Date: 2026-06-03

This walks a vault author through making a source that is reachable **only via an
MCP server** (Confluence, Jira, GitHub-MCP, M365, Slack) — a **managed** module.
A managed module is fetched by an MCP-capable Claude Code subagent instead of a
subprocess extractor; everything downstream is identical.

> **When NOT to use this**: if your source is reachable over plain HTTP/CLI/file
> (YouTube, RSS, Reddit, a local repo, an API with a token), write a normal
> subprocess module (`managed` stays `false`). Managed is only for MCP-only
> sources.

---

## 1. Scaffold the module

A managed module is a normal spec-020 module with two differences: `managed:
true` in the manifest, and a preflight that probes MCP availability.

```text
<vault>/modules/confluence/
├── manifest.yaml
├── preflight.py                  # MCP-availability probe (drives fail-closed)
├── managed_fetch_fewshot.md      # teaches the agent the facts shape
└── sources.yaml                  # the Confluence spaces/pages to fetch
```

(Copy `src/research_framework/modules/_template/` as the starting point — it ships
the managed reference files.)

## 2. The manifest

```yaml
# modules/confluence/manifest.yaml
name: confluence
version: 0.1.0
description: Confluence pages via the Atlassian MCP server (intent source)
managed: true                     # ← spec 054 FR-001. THIS is the only routing switch.
triggers:
  - type: url_pattern
    pattern: "^https?://[^/]+\\.atlassian\\.net/wiki/"
entry_point: extractor.py         # still required by the schema; unused on the managed path
preflight:
  entry_point: preflight.py
  timeout_seconds: 30
default_value_tier: critical      # intent sources are usually critical
schema_examples: managed_fetch_fewshot.md
source_id_from:
  confluence_pages: url
user_owned:
  - sources.yaml
```

- `managed: true` is the **only** switch. Source rows in `sources.yaml` stay
  declarative — there is no per-source managed field.
- `triggers` route source→module exactly as for an unmanaged module.

## 3. The preflight — fail-closed MCP probe (US2)

The preflight is the **single fail-closed gate**: if MCP is unavailable, return
`fatal_fail` and the orchestrator skips the module with a WARN (never a silent
empty success).

```python
# modules/confluence/preflight.py  (subprocess; CANNOT import from src/)
import json, os, sys

def check(sources, watermarks, *, timeout_seconds=30):
    # v1 deterministic probe: the orchestrator sets this flag when the managed
    # transport is active and MCP is configured for the managed_fetch stage.
    if os.environ.get("MANAGED_MCP_AVAILABLE") != "1":
        return {"schema_version": "1.0", "verdict": "fatal_fail",
                "corrections": [],
                "messages": ["Atlassian MCP not available — skipping confluence this cycle"]}
    return {"schema_version": "1.0", "verdict": "success", "corrections": [], "messages": []}

def main():
    payload = json.loads(sys.stdin.read() or "{}")
    print(json.dumps(check(payload.get("sources") or {}, payload.get("watermarks") or {})))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

> The exact MCP-availability signal is being finalized (research D6 / NEEDS
> CLARIFICATION). The deterministic flag above is the v1 approach and is what the
> tests assert against.

## 4. The few-shot — what the agent emits

`managed_fetch_fewshot.md` teaches the agent to return a `SignalPayload` (same
shape a subprocess extractor returns). Default = facts-schema:

```json
{
  "source_version": "<page version / etag>",
  "verdict": "ok",
  "truncated": false,
  "partial": false,
  "facts": { "title": "...", "owner": "...", "decisions": ["..."] },
  "notable": [{"observation": "...", "confidence": "high", "evidence_ref": "..."}]
}
```

For raw mode, the agent wraps content in `facts`:
`{"facts": {"raw_mode": true, "raw": "<verbatim page text>"}}`.

## 5. Wire MCP into the dispatch stage (settings)

MCP tools reach the agent through the `managed_fetch` stage's executor `args` —
the existing settings channel, not a new flag:

```yaml
# <vault>/settings.yaml
stages:
  managed_fetch:
    executor:
      runtime: claude
      model: <model>
      args: ["--mcp-config", "<path-to-mcp.json>", "--allowedTools", "mcp__Atlassian__*"]
      timeout_s: 600
```

## 6. Force-off override (optional)

To run without any managed transport (e.g. a cost-constrained run, or an
environment with no MCP):

```yaml
# settings.yaml
source_extraction:
  managed_force_off: true      # managed modules are recorded as unavailable, not silently empty
```

(Exact key is a `/speckit.tasks` pinning detail; CLI form will mirror it.)

## 7. Run + verify

```bash
./vault research                  # managed modules fetch via the agent; unmanaged via subprocess
```

Then confirm in the spec-048-v2 source-consideration ledger that the Confluence
source shows **`USED`** (success) or **`ACCESS_FAIL`/`NOT_REACHED`** (MCP absent
→ skip-with-WARN) — never silently missing.

## 8. Test it hermetically (no live LLM)

The fake agent intercepts `dispatch()` for the `managed_fetch` stage exactly as
for every other stage — **no live `claude`/`codex`**:

```bash
.venv/bin/python -m pytest tests/pipeline/source_bridge/test_managed_routing.py \
                           tests/pipeline/source_bridge/test_managed_fetch_seam.py \
                           tests/pipeline/source_bridge/test_managed_fail_closed.py
```

- routing: `managed: true` → managed_fetch; `false` → subprocess.
- seam: bespoke-absent → agent dispatch → SignalPayload **shape-identical** to a
  subprocess module (SC-001).
- fail-closed: no MCP → preflight `fatal_fail` → skip-with-WARN, source NOT
  `USED`, no crash (SC-003).

## 9. O'Reilly note (FR-009, unrelated to MCP)

O'Reilly stays an **unmanaged subprocess** module, but its API key now reads from
a settings file (surviving `./vault update`) with the `OREILLY_API_KEY` env var
as a fallback. Managed sources never store credentials in the framework — they
authenticate via the MCP server's own session.
