# Contract: Per-Module preflight subprocess (spec 051 FR4, spec 020 amendment)

**Status:** PROPOSED (ships with spec 051 / 0.7.1)
**Amends:** `specs/020-code-bridge/contracts/manifest.schema.json` — adds
`preflight` to the manifest's `required` keys (Phase-2 amendment; technically
breaking, but all four Tier-1 modules are in-tree and updated in the same ship).

**Execution model (decided 2026-06-02, research.md D6/C1):** preflight runs as
an **isolated subprocess**, mirroring the extractor stdin/stdout JSON contract —
NOT in-process. The framework core never imports vault-local module code at
runtime; modules stay hot-swappable and as isolated as possible (the reason
spec-020 isolates extractors in the first place). This also dissolves the
in-process import-safety question (research U1): there is no import, only a
spawn. The wall-clock budget is enforced by the same
`popen_session` + `terminate_process_tree` machinery the extractor uses
(`pipeline/source_bridge/extractor.py`), which spec 051 FR5 also regression-locks.

This contract defines (1) the manifest `preflight` block, (2) the subprocess
invocation + the request/response JSON payloads, (3) the `PreflightResult`
payload + its schema, and (4) how the orchestrator acts on it.

---

## 1. Manifest declaration (REQUIRED)

Every `<vault>/modules/<name>/manifest.yaml` MUST include:

```yaml
preflight:
  entry_point: preflight.py       # module-relative script, spawned as a subprocess
  timeout_seconds: 30             # optional; default 30, range [1, 300]
```

- `entry_point` mirrors the manifest's top-level `entry_point` (the extractor
  script) — a module-relative `*.py` path.
- `parse_manifest()` (`source_bridge/discovery.py`) MUST raise `ValueError` when
  the `preflight` block is absent OR its `entry_point` file does not exist. The
  error message MUST name the fix ("add preflight.py and declare it; see
  modules/_template/").
- A missing/invalid block fails *that module's* load via the existing
  `isolated_call` fail-closed path — it MUST NOT crash the cycle.

## 2. Subprocess invocation

The bridge spawns the preflight subprocess exactly like the extractor
(`pipeline/source_bridge/extractor.py`):

```python
proc = popen_session([sys.executable, str(module_dir / preflight_entry), "preflight"])
# write the request JSON to proc.stdin; read PreflightResult JSON from proc.stdout
# wall-clock cap = manifest.preflight.timeout_seconds, enforced via terminate_process_tree
```

**Request payload (stdin, JSON):**

```json
{
  "schema_version": "1.0",
  "sources":   { /* the parsed sources.yaml block for this module */ },
  "watermarks": { /* _pipeline/sources/<module>/watermarks.json, may be {} */ }
}
```

**Response payload (stdout, JSON):** a `PreflightResult` (see §3).

Each `modules/<name>/preflight.py` MUST:

- Expose a `main()` that reads `sys.argv[1] == "preflight"`, parses the stdin
  JSON request, and prints the `PreflightResult` JSON to stdout — identical
  dispatch shape to `extractor.py::main()` (which keys off `"extract"`).
- Internally factor the logic into a pure `check(sources, watermarks, *,
  timeout_seconds) -> PreflightResult` helper that `main()` wraps. This keeps
  the URL-shape logic unit-testable directly while the **runtime** boundary is
  always the subprocess.
- Be offline-safe: only `rss` performs a network HEAD probe (stdlib `urllib`),
  bounded by `timeout_seconds`; that network access MUST be fixture-overridable
  for tests (env var, mirroring `RSS_FIXTURE`/`YT_DLP_BIN`) — Principle V.
- Never write vault files.
- Never crash the bridge: a non-zero exit, a timeout (tree-killed), unparseable
  stdout, or a raised exception is all treated by the orchestrator as
  `verdict="fatal_fail"` with a diagnostic message (fail-closed), so a broken
  preflight skips only its own module.

## 3. `PreflightResult` payload + schema

Cross-process JSON payload (schema: `contracts/preflight-result.schema.json`),
parsed on the orchestrator side into frozen dataclasses
(`pipeline/source_bridge/preflight_types.py`):

```jsonc
{
  "schema_version": "1.0",
  "verdict": "success | warning | fatal_fail",
  "corrections": [
    { "original": "...", "suggested": "...", "reason": "...", "applied": true }
  ],
  "messages": ["human-readable note", "..."]
}
```

```python
@dataclass(frozen=True)
class PreflightResult:
    schema_version: str                    # "1.0"
    verdict: Literal["success", "warning", "fatal_fail"]
    corrections: list[SourceCorrection]    # may be empty
    messages: list[str]                    # human-readable, may be empty

@dataclass(frozen=True)
class SourceCorrection:
    original: str       # malformed value exactly as written in sources.yaml
    suggested: str      # corrected value
    reason: str         # why the original is wrong
    applied: bool       # True = correction used this cycle; False = suggestion only
```

Convenience constructors on `PreflightResult`: `success()`,
`warning(corrections, messages)`, `fatal(messages)`. `schema_version` follows the
spec-036 cross-boundary payload discipline (now a genuine cross-process
boundary).

## 4. Orchestrator behaviour (verdict → action)

Spawned at two points (research.md D6):
- `source_bridge/orchestrator.run_extraction()` — once per module at cycle start,
  after manifest + sources + watermarks load, before the per-source loop.
- `cli/refresh_sources.py` — a discrete preflight sweep over installed modules.

| `verdict` | Orchestrator action |
| --- | --- |
| `success` | Run the module normally. |
| `warning` | Run the module. Log each `message`; record `corrections` in the cycle report. Where `applied=true`, the corrected URL is used for this cycle's extraction. |
| `fatal_fail` | **Skip this module this cycle.** Log + record in cycle report. MUST NOT abort the whole cycle (Principle VIII module isolation). Other modules proceed. Subprocess crash/timeout/garbage-stdout map here (fail-closed). |

## 5. Per-module check obligations (all four MANDATORY for 0.7.1)

| Module | Checks |
| --- | --- |
| `youtube` | strip trailing whitespace; validate channel-URL shape; detect plain handle without `@` prefix → suggest `@handle` form |
| `reddit` | validate `/r/<name>` or bare `<name>`; normalize to canonical; reject obvious typos |
| `rss` | de-dup `/feed/feed/` → `/feed/`; `arxiv.org/list/cs.AI` → suggest `rss.arxiv.org/rss/cs.AI`; HEAD probe confirms the URL emits XML/Atom (within `timeout_seconds`; fixture-overridable) |
| `oreilly` | verify `learning.oreilly.com/search/?q=` shape; reject legacy `oreilly.com/api/v2/search` → suggest the search-URL form |

Each gets `tests/modules/<name>/test_preflight.py` (~6–8 tests). Mirror the
extractor test pattern (`tests/source_bridge/test_youtube_module.py::_run_extractor`):
the **contract** is exercised by invoking the subprocess (JSON in → JSON out),
and fine-grained URL-shape logic MAY additionally call the pure `check()` helper
directly. rss tests use a HEAD-probe fixture override to stay hermetic/offline.

## 6. Skeleton (new modules)

`modules/_template/preflight.py` (reference, not a shipped module) — a subprocess
script mirroring `extractor.py`:

```python
"""Preflight for <module>. Subprocess contract — see
specs/051-post-revival-hardening/contracts/preflight.contract.md."""
from __future__ import annotations
import json, sys
# PreflightResult/SourceCorrection are duplicated module-side as plain dict
# builders (modules cannot import from src/ — same constraint as extractor.py),
# or emitted directly as the JSON dict below.

def check(sources: dict, watermarks: dict, *, timeout_seconds: int = 30) -> dict:
    # TODO: add module-specific URL-shape checks here.
    return {"schema_version": "1.0", "verdict": "success", "corrections": [], "messages": []}

def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "preflight"
    payload = json.loads(sys.stdin.read() or "{}")
    if command == "preflight":
        out = check(payload.get("sources") or {}, payload.get("watermarks") or {},
                    timeout_seconds=int(payload.get("timeout_seconds", 30)))
    else:
        out = {"schema_version": "1.0", "verdict": "fatal_fail",
               "corrections": [], "messages": [f"unknown command: {command}"]}
    print(json.dumps(out))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

> Note: like the extractors, module scripts run in their own subprocess and
> CANNOT import from `src/research_framework/` — they emit the `PreflightResult`
> JSON shape directly. The orchestrator side parses it into the typed dataclasses
> in `pipeline/source_bridge/preflight_types.py`.

## 7. Acceptance

- `manifest.schema.json` lists `preflight` in `required`; all four in-tree
  `manifest.yaml` declare `preflight.entry_point: preflight.py`.
- `parse_manifest` rejects a manifest without `preflight` (or with a missing
  `entry_point` file) — test.
- The bridge **spawns** preflight as a subprocess (popen_session) with the
  request JSON, parses the `PreflightResult`, enforces `timeout_seconds` via
  `terminate_process_tree`, and maps crash/timeout/garbage to `fatal_fail` —
  tests.
- `run_extraction` and `refresh-sources` honour the verdict table (tests).
- Four `modules/<name>/preflight.py` (subprocess scripts) + four
  `tests/modules/<name>/test_preflight.py`.
- `modules/_template/preflight.py` skeleton present.
- `contracts/preflight-result.schema.json` present and validated against.
