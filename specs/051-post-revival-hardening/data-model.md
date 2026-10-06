# Phase 1 Data Model — Post-Revival Hardening (spec 051)

New and amended typed entities, grouped by FR. All dataclasses are
`@dataclass(frozen=True)` following the established `settings.py` pattern
(e.g. `LimitsSettings` at `settings.py:31`). No new runtime dependencies.

---

## FR1 — Cycle-yield model

### `CycleYieldSettings` (new, `pipeline/settings.py`)

```python
@dataclass(frozen=True)
class CycleYieldSettings:
    """settings.yaml::cycle_yield (spec 051 FR1)."""
    base_notes_per_cycle: int = 5
    cadence_factor: dict[str, float] = field(default_factory=lambda: {
        "daily": 1.0, "weekly": 3.0, "biweekly": 5.0, "monthly": 8.0,
    })
    coverage_factor: dict[str, float] = field(default_factory=lambda: {
        "coverage_below_50pct": 1.5,
        "coverage_50_to_80pct": 1.0,
        "coverage_above_80pct": 0.5,
    })
    min_floor: int = 1       # never gate below this (Principle VIII override)
    max_ceiling: int = 50    # never aim above this (cost guardrail)
```

- Added to `VaultSettings` as `cycle_yield: CycleYieldSettings = field(default_factory=CycleYieldSettings)` (`settings.py:63`).
- Parser `_parse_cycle_yield(raw, *, vault_dir)` mirrors `_parse_limits` (`settings.py:481`): tolerant of absent block (returns defaults), validates types, rejects negative/zero `base`/`floor`/`ceiling`.

**Validation rules:**
- `base_notes_per_cycle ≥ 1`, `min_floor ≥ 1`, `max_ceiling ≥ min_floor`.
- All `cadence_factor` / `coverage_factor` values `> 0`.
- Unknown cadence/coverage keys: ignored with a WARN (forward-compat).

### Yield computation (model)

`coverage.remaining_yield(vault_dir, cycle_number, max_cycles, settings)` returns
a `YieldTarget` (new) instead of a bare `int`:

```python
@dataclass(frozen=True)
class YieldTarget:
    target: int               # ceil(base * cadence_factor * coverage_factor), clamped [floor, ceiling]
    base: int
    cadence_bucket: str       # "daily" | "weekly" | "biweekly" | "monthly"
    cadence_factor: float
    coverage_bucket: str      # "coverage_below_50pct" | ... | "coverage_above_80pct"
    coverage_factor: float
    floor: int
    ceiling: int
```

**Derivation:**
- `cadence_bucket` from time-since-last-cycle (reuses the existing
  `_hours_since_last_cycle` at `coverage.py`): `<24h → daily`, `24h–7d → weekly`,
  `7d–14d → biweekly`, `>14d → monthly`. Cold start (no prior cycle) → `monthly`
  (most generous; a fresh dormant vault should write a full batch).
- `coverage_bucket` from `met/target` ratio across `load_targets(vault_dir)`
  categories: `<50% → below_50`, `50–80% → 50_to_80`, `>80% → above_80`.
- `target = clamp(ceil(base * cadence_factor * coverage_factor), floor, ceiling)`.

**Backward-compat / baseline pin:** defaults chosen so the reference-vault fixture's
computed target equals its current effective threshold (so `./build.sh
--quality` regression diff does not move). Verified in
`test_cg001_yield_model.py` against the committed tech-lite fixture.

### CG-001 gate semantics (amended, `gates_cycle.py`)

`CG001_min_cycle_yield` (`gates_cycle.py:12`) state transitions:

| Condition | Result | Exit semantics |
| --- | --- | --- |
| `actual ≥ target` | PASS | continue |
| `min_floor ≤ actual < target*0.5` | WARN | continue (record under-target in report) |
| `target*0.5 ≤ actual < target` | WARN | continue |
| `actual < min_floor` | FAIL | gate fails (Principle I stop) |

> Single WARN band (below `target`, at/above `floor`). FAIL only below `floor`.
> Distinct from the old binary pass/fail at a flat threshold.

### `yield-calibration.json` sidecar (new artifact)

`_pipeline/yield-calibration.json` — a JSON **array** appended to each cycle.
Each element (schema in `contracts/yield-calibration.schema.json`):

```json
{
  "schema_version": "1.0",
  "cycle": 7,
  "ts": "2026-06-02T14:31:09Z",
  "base": 5,
  "cadence_bucket": "weekly",
  "cadence_factor": 3.0,
  "coverage_bucket": "coverage_below_50pct",
  "coverage_factor": 1.5,
  "target": 23,
  "actual": 19,
  "exit_status": "WARN"
}
```

Written via `atomic_write.write_json` (read-modify-write the array atomically).
Diagnostic also embedded in `cycle-NNN-quality-report.json` under the CG-001
gate entry (D2).

---

## FR3 — Stub classification

### `StubsSettings` (new, `pipeline/settings.py`)

```python
@dataclass(frozen=True)
class StubsSettings:
    """settings.yaml::stubs (spec 051 FR3)."""
    anchor_link_threshold: int = 5   # Q2: flag-not-delete at >= this many inbound links
```

- Added to `VaultSettings` as `stubs: StubsSettings = field(default_factory=StubsSettings)`.
- Parser `_parse_stubs(raw)`; `anchor_link_threshold ≥ 1`.

### `StubClassificationContext` (new, `pipeline/stubs.py`)

```python
@dataclass(frozen=True)
class StubClassificationContext:
    path: Path
    inbound_links_count: int
    body_len: int
```

### `classify_stub` (new public function, `pipeline/stubs.py`)

```python
def classify_stub(
    ctx: StubClassificationContext, *,
    body_len_threshold: int,
    anchor_link_threshold: int,
) -> Literal["not-a-stub", "anchor-stub", "deletable-stub"]:
```

**State machine:**
1. `body_len > body_len_threshold` → `not-a-stub`.
2. else `inbound_links_count >= anchor_link_threshold` → `anchor-stub` (FLAG, never delete; gets `status: needs-research`; surfaced in research-backlog with deferred-work annotation).
3. else → `deletable-stub` (normal stub-removal candidate).

> `classify_stub` is a pure function. The existing `scan_stubs` (`stubs.py:86`)
> detection criteria (word_count / source_urls / verifier / lifecycle) are
> unchanged — classification is an *additional* lens, not a replacement.

### `inbound_link_counts` helper (new, `vault/indexer.py`)

```python
def inbound_link_counts(vault_dir: Path) -> dict[str, int]:
    """Note-stem → number of inbound wikilinks, from the same graph
    computation rebuild_all() already performs. Built once per stub pass."""
```

No behaviour change to `rebuild_all` (`indexer.py:93`); this exposes the inbound
count map the indexer already computes internally. Caller (FR3) builds it once
per scan and feeds each `StubClassificationContext`.

---

## FR4 — Module preflight contract

### `manifest.schema.json` amendment (`specs/020-code-bridge/contracts/manifest.schema.json`)

Add `"preflight"` to the `required` array, and define (subprocess model — the
`entry_point` is a module-relative script, mirroring the manifest's top-level
`entry_point`):

```json
"preflight": {
  "type": "object",
  "required": ["entry_point"],
  "additionalProperties": false,
  "properties": {
    "entry_point":     { "type": "string", "pattern": "^[A-Za-z0-9_./-]+\\.py$", "description": "module-relative preflight script, e.g. 'preflight.py'" },
    "timeout_seconds": { "type": "integer", "minimum": 1, "maximum": 300, "default": 30 }
  }
}
```

### `ModuleManifest.preflight` (amended dataclass, `source_bridge/discovery.py:39`)

```python
preflight: dict[str, Any]   # REQUIRED — parse_manifest raises if absent / entry_point missing
```

`parse_manifest` (`discovery.py:55`) raises `ValueError("manifest missing
required 'preflight' block — add preflight.py and declare it (see
modules/_template/)")` when the block is absent or its `entry_point` file does
not exist; the existing `isolated_call` fail-closed path (`discovery.py:90`)
turns that into a skipped-module WARN rather than a crashed cycle.

### `PreflightResult` (cross-process payload — subprocess stdout JSON)

`PreflightResult` is the JSON the module's preflight **subprocess** writes to
stdout (schema: `contracts/preflight-result.schema.json`), parsed on the
orchestrator side into frozen dataclasses in
`pipeline/source_bridge/preflight_types.py`. Contract in
`contracts/preflight.contract.md`. Shape:

```python
@dataclass(frozen=True)
class PreflightResult:
    schema_version: str            # "1.0"
    verdict: Literal["success", "warning", "fatal_fail"]
    corrections: list[SourceCorrection]   # suggested URL fixes (may be empty)
    messages: list[str]                   # human-readable notes
```

```python
@dataclass(frozen=True)
class SourceCorrection:
    original: str       # the malformed source value as written in sources.yaml
    suggested: str      # the corrected value (e.g. rss.arxiv.org/rss/cs.AI)
    reason: str         # why (e.g. "arxiv.org/list/ is HTML, not a feed")
    applied: bool       # False = suggestion only (warning); semantics per verdict
```

**Verdict → orchestrator behaviour:**
- `success` → run the module normally.
- `warning` → run the module; log + record `corrections` in the cycle report (corrected URLs used where `applied=True`).
- `fatal_fail` → **skip this module this cycle** (Principle VIII isolation — do NOT abort the whole cycle).

### Subprocess invocation + `check()` helper (each `modules/<name>/preflight.py`)

**Runtime boundary is the subprocess** (research.md D6/C1). The bridge spawns
`popen_session([sys.executable, <module>/preflight.py, "preflight"])`, writes the
request JSON (`{schema_version, sources, watermarks}`) to stdin, reads the
`PreflightResult` JSON from stdout, and enforces `timeout_seconds` via
`terminate_process_tree` — identical to the extractor invocation in
`pipeline/source_bridge/extractor.py`. Crash / timeout / unparseable stdout →
`fatal_fail` (fail-closed).

Each `preflight.py` has a `main()` (dispatch on `sys.argv[1]=="preflight"`, like
`extractor.py::main`) wrapping a pure helper kept for direct unit testing:

```python
def check(
    sources: dict,            # parsed sources.yaml block for this module
    watermarks: dict,         # _pipeline/sources/<module>/watermarks.json (may be {})
    *,
    timeout_seconds: int = 30,
) -> dict: ...                # the PreflightResult JSON dict (modules can't import src/)
```

> Module scripts run isolated and CANNOT import from `src/research_framework/`
> (same constraint as extractors); they emit the `PreflightResult` JSON shape
> directly. The typed `PreflightResult`/`SourceCorrection` dataclasses live on
> the **orchestrator** side (`preflight_types.py`) and parse that JSON.

In-process call (not subprocess — D6). `timeout_seconds` bounds any network
HEAD probe (rss only). Skeleton at `modules/_template/preflight.py` returns
`PreflightResult.success()` unconditionally.

---

## FR2 — (no new typed entities)

FR2 is bash-only (`install.sh` + shim). The "entities" are runtime checks, not
data structures:
- **Stale-venv signal:** `.venv/pyvenv.cfg`'s `home =` path missing-on-disk or
  pointing at a different bundle.
- **Version-mismatch signal:** `research_framework.__version__` (runtime import)
  ≠ bundle `pyproject.toml` version → non-zero exit + remediation message.

---

## FR5 — (no new entities; tests only)

Net-new tests exercise existing functions (`_cycle_helpers._run_script`,
`_highest_completed_cycle`). No new data structures.

---

## Entity → file map

| Entity | File | New/Amended |
| --- | --- | --- |
| `CycleYieldSettings`, `_parse_cycle_yield` | `pipeline/settings.py` | new |
| `YieldTarget`, model in `remaining_yield` | `pipeline/coverage.py` | amended |
| CG-001 warn/fail split | `pipeline/gates_cycle.py` | amended |
| yield diagnostic + sidecar append | `pipeline/quality_report.py` | amended |
| `yield-calibration.json` schema | `contracts/yield-calibration.schema.json` | new |
| `StubsSettings`, `_parse_stubs` | `pipeline/settings.py` | new |
| `StubClassificationContext`, `classify_stub` | `pipeline/stubs.py` | new |
| `inbound_link_counts` | `vault/indexer.py` | new (extraction) |
| `preflight` required key (`entry_point`) | `specs/020-code-bridge/contracts/manifest.schema.json` | amended |
| `ModuleManifest.preflight` + validation | `source_bridge/discovery.py` | amended |
| `PreflightResult` JSON schema | `contracts/preflight-result.schema.json` | new |
| `PreflightResult`, `SourceCorrection` (typed parse, orchestrator-side) | `source_bridge/preflight_types.py` | new |
| preflight subprocess spawn (popen_session + tree-kill) + verdict handling | `source_bridge/orchestrator.py`, `cli/refresh_sources.py` | amended |
| preflight subprocess scripts (`main()` + `check()`, emit JSON) | `modules/<name>/preflight.py` (×4) + `modules/_template/preflight.py` | new |
| `cycle_yield:` / `stubs:` blocks | repo-root `settings.yaml` + `scaffold-manifest.json` | amended |
