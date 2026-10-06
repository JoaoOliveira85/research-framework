# Data Model: Source-Module Resilience Polish (spec 038)

**Date**: 2026-06-03 | **Branch**: `038-source-module-resilience`

Only NEW or EXTENDED entities are listed. Everything else (PreflightResult,
SourceCorrection, SignalPayload, the `empty`/`error` Verdict enum) is **reused
verbatim** from the shipped spec-051/spec-020 surface — see `research.md`.

---

## 1. Manifest blocks (EXTEND `manifest.yaml`)

Three OPTIONAL blocks added to the spec-020 schema. Full schema +
defaults in `contracts/manifest-extensions.md`.

- `authentication.env_vars: [str]` — MANDATORY-for-module env vars (Q3).
- `rate_limits.{requests_per_minute, requests_per_hour, burst, backoff}` —
  declaration only in v1 (enforcement timing flagged in plan).
- `failure_policy: block_cycle | degrade_gracefully | defer` — default `block_cycle`.

Absent ⇒ today's behaviour (no auth, unbounded, block_cycle).

## 2. `WatermarkEntry` (EXTEND `pipeline/source_bridge/cache.py`)

Shipped today:

```python
@dataclass
class WatermarkEntry:
    source_version: str
    bridge_version: str
    extracted_at: str
    verdict: Verdict                       # "ok" | "empty" | "exhausted" | "error"
    consensus: dict | None = None
    consecutive_empty_cycles: int = 0
```

**Delta** — add a rolling verdict window (NOT a consecutive-error streak):

```python
    recent_cycle_verdicts: list[str] = field(default_factory=list)  # NEW (FR-005) — capped at 3
```

- On each cycle, append the source's cycle verdict (`ok`/`empty`/`error`/…); keep
  only the last 3 entries (oldest dropped).
- `load_watermarks` reads it with `list(entry.get("recent_cycle_verdicts", []))`
  (back-compat: pre-038 watermarks default to `[]` — NO migration needed).
- `save_watermarks` serializes via the existing `asdict(entry)` — automatic.

This field is the substrate for the **sustained-failure gate** (FR-005, US1 #3):
a deterministic verdict that FAILs when any module's rolling `error` rate exceeds
>50% over the last 3 cycles (`error` count / len(window) > 0.5 when len ≥ 3).

## 3. `quality/source_health` gate (NEW or extend existing metric family)

- Input: per-module `watermarks.json` (`recent_cycle_verdicts`) across the rolling
  3-cycle window.
- Threshold: configurable (`settings.yaml`), default per spec US1 #3 (sustained
  `error` rate > 50% over 3 cycles for a single module).
- Output: a deterministic `pass`/`fail` verdict feeding the spec-022 quality harness
  (Principle I). EMPTY (`empty`) NEVER counts toward the gate — only `error`.

## 4. `raw_data/captures/<YYYY-MM-DD>/manifest.json` (NEW)

Index emitted by `scripts/raw_capture_batch.py`. Full schema in
`contracts/raw-capture-batch.contract.md`. Maps `sha256(url)` →
`{url, status, captured_path, captured_at, error?, payload_kind, citing_notes[]}`.
`status ∈ {OK, FAILED, PENDING}`.

## 5. `_pipeline/archive-snapshots.json` (NEW)

Persistent, cross-cycle archive.org ledger. Schema:
`contracts/archive-snapshots.schema.json`. Maps URL →
`{snapshot_url, created_at, status, reason?, attempts}` where
`status ∈ {archived, deferred, unarchivable}` (fail-and-defer, Q2).

## 6. Cycle-report extension (US1 #2)

The orchestrator already records `module_stats["preflight"]`. 038 adds a per-cycle
**"source health"** section listing each module whose cycle verdict was `error`,
formatted `source health: <module> FAILED with <underlying error>`. EMPTY modules
are NOT listed (the whole point — FR-005). This is a presentation delta on existing
data, not a new artifact.

---

## Relationships

```text
manifest.authentication.env_vars
        └─(read by)→ modules/<name>/preflight.py::check()  ──→ PreflightResult(fatal_fail) [shipped channel]

extractor verdict=error
        └─(appends to)→ WatermarkEntry.recent_cycle_verdicts (≤3)  ──→ source_health gate ──→ spec-022 harness
        └─(surfaced in)→ cycle report "source health" line

new-note source_urls (frontmatter.py)
        └─(enumerated by)→ raw_capture_batch.py ──(calls)→ raw_capture.capture()  [shipped primitive]
                                                  └─(writes)→ captures/<DATE>/manifest.json

vault_health --apply (fragile URLs)
        └─(writes)→ _pipeline/archive-snapshots.json  [fail-and-defer, exit 0]
```
