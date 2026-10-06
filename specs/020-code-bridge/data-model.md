# Phase 1 Data Model: Source-Module Architecture

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Research**: [research.md](./research.md)
**Date**: 2026-05-20 (initial) / 2026-05-26 (ModuleSourcesFile + clarify refresh)

Formalizes the Key Entities from spec.md into structured form with
explicit field types, validation rules, relationships, and state
transitions. JSON Schemas in `contracts/` reference these definitions.

## Entity Index

| # | Entity | File location | Lifecycle |
|---|--------|---------------|-----------|
| 1 | SignalPayload | `_pipeline/sources/<module>/signals/<source-stem>-<version>.json` | Written per extraction; cache-keyed by `source_version` |
| 2 | Watermark (map) | `_pipeline/sources/<module>/watermarks.json` | Updated after every successful extraction |
| 3 | ModuleManifest | `<vault>/modules/<name>/manifest.yaml` | Read at every pipeline start |
| 4 | ModuleSourcesFile | `<vault>/modules/<name>/sources.yaml` | Operator/module-author owned; read every extraction |
| 5 | TriggerRegistry | (in-memory only) | Rebuilt every pipeline start; never persisted (R25) |
| 6 | Trigger | (embedded in ModuleManifest) | n/a |
| 7 | FactsSchema | `<vault>/_pipeline/sources/<module>/facts-schema.json` | Generated at install + on spec-hash change |
| 8 | Validator (yaml + py) | `<vault>/<module>.validators.yaml` + `.py` | Vault-author owned |
| 9 | ConsensusResult | `_pipeline/sources/<module>/consensus/<source>-cycle-NNN.json` | Written per consensus run |
| 10 | AgentCallRecord | `_pipeline/cycles/cycle-NNN/agent-calls/<ts>-<stage>-<call-id>.json` | Written per LLM call |
| 11 | Tiers (per D7) | `settings.yaml::tiers` | Read at config-load |
| 12 | SchemaDriftReport (per D8) | `_pipeline/sources/<module>/facts-schema.drift.md` | Written on detected drift |

## 1. SignalPayload

Per-source, per-version cache payload. Shared envelope across modules;
`facts` content shape is per-module schema.

**Envelope fields** (always present, framework-owned):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `module` | string | yes | Module name that produced this payload (e.g. `"code"`). Matches a name in `<vault>/modules/`. |
| `source_id` | string | yes | Stable identifier for the source. For `code` module: absolute repo path. For `youtube`: video URL. |
| `source_version` | string | yes | Version identifier opaque to the framework. For `code`: commit SHA. For `youtube`: transcript hash. |
| `bridge_version` | string | yes | Framework version that produced this payload (semver). |
| `extracted_at` | ISO-8601 datetime | yes | UTC timestamp of extraction completion. |
| `verdict` | enum | yes | One of `ok`, `empty`, `exhausted`, `error`. |
| `truncated` | bool | yes | Set true if `notable` was truncated to fit the 100 KB envelope cap. |
| `partial` | bool | yes | Set true if this payload represents a salvaged partial output per D9 (verdict will be `error`). |
| `facts` | object | yes | Module-specific structured content; shape governed by `facts-schema.json`. |
| `notable` | array | yes | Freeform observations with evidence references. May be `[]`. |

**`notable[*]` shape**:

```json
{
  "observation": "string (required)",
  "confidence": "high | medium | low (required)",
  "evidence_ref": "string (required) - e.g. 'src/api/UserController.java:42' or 'transcript:00:14:32'"
}
```

**Validation rules**:
- Total payload size MUST be \u2264 100 KB (FR R4). If exceeded, framework
  truncates `notable` from the end, sets `truncated: true`.
- `verdict == "error"` implies `partial` MAY be true; other verdicts
  imply `partial == false`.
- `facts` MUST conform to the active per-(vault, module) FactsSchema
  unless `verdict == "error"` (errored extractions are allowed to ship
  any-shape facts for forensics).

**State transitions**: SignalPayload is immutable once written. New
extractions for the same source produce new files (keyed by
`source_version`); GC (D3, 30-day retention) eventually deletes older
files.

## 2. Watermark (map)

One file per module: `watermarks.json` is a JSON object mapping
`source_id` strings to watermark entries.

**Entry shape**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source_version` | string | yes | Last-extracted version. Cache-hit when this matches the current version. |
| `bridge_version` | string | yes | Framework version at last extraction. Mismatch \u2192 cache miss. |
| `extracted_at` | ISO-8601 datetime | yes | UTC timestamp. |
| `verdict` | enum | yes | Same as SignalPayload.verdict. |
| `consensus` | object \| null | no | Present when value_tier ran N>1. Fields: `n`, `majority`, `agreed_at`. |
| `consecutive_empty_cycles` | int | no | Per-source counter for "exhausted" detection (used by future US4 logic). |

**Validation rules**:
- `source_version` MUST match the most recent SignalPayload file's
  `source_version` for this source.
- File MUST be writable atomically (NamedTemporaryFile + os.replace).

**State transitions**:
- Created on first successful extraction for a source.
- Updated on every successful extraction.
- Source-removal: the entry stays (audit trail); GC of signal files
  proceeds normally.

## 3. ModuleManifest

Per-module declaration of identity, triggers, and interface. Lives at
`<vault>/modules/<name>/manifest.yaml`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Module identifier (lowercase, hyphenated). Must equal the parent directory name. |
| `version` | semver string | yes | Module's own version (independent of `bridge_version`). |
| `description` | string | yes | One-line human-readable description. |
| `triggers` | array of Trigger | yes | Pattern matchers; at least one required. |
| `entry_point` | string | yes | Python file relative to the module dir (e.g. `extractor.py`). |
| `default_value_tier` | enum | yes | `routine \| important \| critical`. Default tier suggestion for this module. |
| `default_tier` (NEW per D7) | enum | no | `basic \| normal \| flagship`. Module author's complexity hint; framework respects unless stage executor overrides. |
| `schema_examples` | string | yes | Path to few-shot file relative to the module dir (e.g. `few-shot.md`). |
| `extraction_timeout_seconds` (NEW per R21) | int | no | Per-source hard wall-clock budget (default 600, min 30, max 7200). Vault authors can override via `settings.yaml::stages.source_extraction.timeout_seconds`. |
| `source_id_from` (FR-013b) | object (string → string) | no | Maps each `sources.yaml` top-level key to the record field used as `source_id` (e.g. `youtube_channels: url`). Default: `url` if present on record, else `name`. |
| `user_owned` (FR-025) | array of strings | no | Relative paths preserved on `./vault update` if present (e.g. `custom_prompt.md`). `sources.yaml` is always preserved unconditionally. |
| `bridge_compat` | object | no | Reserved for future use (D6 currently does atomic refresh, not compat checks). |

**Validation rules**:
- `name` MUST match parent directory name.
- `entry_point` file MUST exist relative to the module dir.
- `schema_examples` file MUST exist relative to the module dir.
- `triggers` MUST be non-empty.
- `default_value_tier` MUST be one of the three enum values.
- If `default_tier` is set, it MUST be one of `basic | normal | flagship`.

## 4. ModuleSourcesFile

Per-module declarative list of source **instances** to extract. Lives at
`<vault>/modules/<name>/sources.yaml` (authoritative for FR-013a; NOT
`research.spec.md::data_sources`, which remains scout/schema-gen context
per FR-013c).

**File shape** (module-specific top-level keys; values are lists of records):

```yaml
# Example: youtube module
youtube_channels:
  - url: https://www.youtube.com/@TwoMinutePapers
    label: Two Minute Papers
  - url: https://www.youtube.com/@3blue1brown
    label: 3Blue1Brown

# Example: code module
github_repos:
  - path: /Users/me/src/my-microservice
    value_tier: important
  - url: https://github.com/org/other-repo
    value_tier: routine
```

| Concept | Rule |
|---------|------|
| Top-level keys | Module-defined kind names (e.g. `youtube_channels`, `github_repos`, `subreddits`). MUST match keys in `manifest.source_id_from` when that map is present. |
| Records | Each list item MUST include enough identity for FR-013b (`url`, `path`, and/or `name` per module). MAY include `value_tier`, `label`, module-specific metadata. |
| Missing file | Module contributes **zero** sources; WARN once per pipeline start naming the module. |
| Invalid YAML | Module-isolation (D9): skip enumeration for that module; surface in run-report. |
| Update / migrator | If file exists on `./vault update`, MUST NOT be overwritten (FR-025). Seed from bundle template only when absent. |
| Legacy migration | Vault-level `scripts/sources.yaml` is a **one-time port** input when landing the first 020-shaped module (split into per-module files). |

**`source_id` derivation** (framework, using `manifest.source_id_from`):

1. For each `(kind, record)` in the loaded file, look up `source_id_from[kind]`
   or default field order: `url` if key present and non-empty, else `name`.
2. Read `record[field]`; MUST be non-empty string.
3. `source_id` MUST be stable across runs for unchanged records.

**State transitions**: Operator-edited; framework read-only at extraction.
No automatic sync to `data_sources` in 020.

See [`contracts/sources.yaml.contract.md`](./contracts/sources.yaml.contract.md).

## 5. TriggerRegistry (in-memory)

Built at pipeline start from a **filesystem walk** of
`<vault>/modules/*/manifest.yaml` (FR-010). Every manifest on disk is
registered. `settings.yaml::modules:` affects install/update copy and
**precedence order only** — not which modules exist at runtime. Ordered
list (NOT a map) to preserve first-match-wins semantics. **Never persisted**
under `_pipeline/` (R25).

**Internal shape** (Python dataclass):

```python
@dataclass
class TriggerEntry:
    module_name: str
    trigger_index: int          # which trigger within the module's list
    trigger_type: str           # 'url_pattern' | 'path_pattern' | etc.
    compiled_pattern: re.Pattern
    
class TriggerRegistry:
    entries: list[TriggerEntry]  # ordered by settings.yaml::modules: array order
    
    def match(self, source: str) -> Optional[tuple[str, int]]:
        """Returns (module_name, trigger_index) of first match, or None."""
```

**State transitions**: Fully rebuilt on every pipeline start (R9, R25). No
disk cache.

## 6. Trigger (embedded in ModuleManifest)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | enum | yes | `url_pattern \| path_pattern \| path_exists`. |
| `pattern` | string | yes | Regex (for `*_pattern`) or path glob (for `path_exists`). |

**Validation rules**:
- `pattern` MUST compile successfully via `re.compile()` for
  `*_pattern` types.
- For `path_exists`: `pattern` is a glob applied to the source's
  resolved path (used by code module to detect git checkouts).

## 7. FactsSchema

Per-`(vault, module)` JSON Schema generated by schema-gen. Lives at
`<vault>/_pipeline/sources/<module>/facts-schema.json`.

**Top-level shape**:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "facts-schema-<module>-<vault>-<spec_hash>",
  "type": "object",
  "title": "Facts schema for module '<module>' in vault '<vault>'",
  "description": "Generated by schema-gen from research.spec.md on <date>.",
  "manually_edited": false,
  "properties": {
    "technologies": { "type": "array", "items": {"type": "string"} },
    "patterns": { "type": "array", "items": { ... } },
    ... per-vault buckets ...
  },
  "required": [...]
}
```

**Special fields**:
- `manually_edited` (bool, framework-recognized): when `true`, framework
  does not auto-regenerate over this file. Drift detection (D8) still
  runs on spec-hash mismatch.

**Sibling files**:
- `.schema-gen-hash` \u2014 sha256 of `research.spec.md` at last
  successful schema-gen (or drift acknowledgment).
- `facts-schema.regenerated.json` \u2014 transient sidecar (D8); produced
  during drift detection.
- `facts-schema.drift.md` \u2014 transient sidecar (D8); structural diff.

**Fallback default** (D1): when schema-gen returns invalid JSON
Schema, framework writes a 3-bucket minimal default:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "technologies": { "type": "array", "items": {"type": "string"} },
    "patterns": { "type": "array", "items": {"type": "string"} },
    "notable": { "type": "array", "items": {"type": "string"} }
  },
  "required": ["technologies"],
  "manually_edited": false,
  "_fallback": true,
  "_fallback_reason": "schema-gen returned invalid JSON Schema; loud WARN logged"
}
```

## 8. Validator (yaml + py)

Two-file pair living next to `research.spec.md`.

**`<module>.validators.yaml`** (declarative rules):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `facts.<bucket>.required` | bool | no | Whether the bucket must be present. |
| `facts.<bucket>.min_items` | int | no | Minimum array length (when `type` is array). |
| `facts.<bucket>.max_items` | int | no | Maximum array length. |
| `notable.min_items` | int | no | |
| `notable.max_items` | int | no | |

**`<module>.validators.py`** (procedural):

```python
def validate(payload: dict) -> list[str]:
    """Return list of error strings; empty list = pass.
    
    On unhandled exception: framework applies module-isolation policy
    per D9 (retry once, then isolate the source).
    """
    errors = []
    # ... custom logic ...
    return errors
```

## 9. ConsensusResult

Per-source per-cycle audit record. Lives at
`_pipeline/sources/<module>/consensus/<source-id-hash>-cycle-NNN.json`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `module` | string | yes | Module name. |
| `source_id` | string | yes | Source identifier. |
| `cycle` | int | yes | Cycle number. |
| `value_tier` | enum | yes | `routine \| important \| critical`. |
| `extractors_spawned` | int | yes | N. Must be odd (validated). |
| `verdicts` | array of enum | yes | One per extractor; ordered by spawn order. |
| `final_verdict` | enum | yes | Majority vote winner. |
| `findings_unioned` | int | yes | Total findings across all extractors after union. |
| `dissenting_extractor_indices` | array of int | yes | Indices of extractors whose verdict differed from final. |
| `consensus_decided_at` | ISO-8601 datetime | yes | When the vote completed. |

## 10. AgentCallRecord

Per-LLM-call audit record (FR-024, cross-cutting). Lives at
`_pipeline/cycles/cycle-NNN/agent-calls/<timestamp>-<stage>-<call-id>.json`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `stage` | string | yes | Pipeline stage (e.g. `schema_gen`, `scout`, `note_writer`). |
| `call_id` | string | yes | Unique identifier (UUID). |
| `timestamp` | ISO-8601 datetime | yes | Call initiation time. |
| `model` | string | yes | Resolved model identifier (post-tier resolution per D7). |
| `tier` | string \| null | no | Resolved tier name (e.g. `basic`) if set; null otherwise. |
| `prompt` | string | yes | Full prompt text. NOT truncated. |
| `response` | string | yes | Full response text. NOT truncated. |
| `latency_ms` | int | yes | Wall-clock time of the call. |
| `tokens_in` | int | yes | Prompt tokens. |
| `tokens_out` | int | yes | Response tokens. |
| `cost_usd` | float | yes | Computed cost. |
| `error` | string \| null | no | Traceback if the call failed; null on success. |
| `retry_attempt` | int | no | 1 or 2 (for D9 retry-once); absent for non-retry contexts. |

**Validation rules**:
- `prompt` and `response` MUST NOT be truncated (FR-024 requirement).
  If size is a concern in practice (large prompts), the framework may
  add per-call compression as a follow-up; v1 stores plaintext.

## 11. Tiers (per D7)

`settings.yaml::tiers` block. NOT a file of its own \u2014 a sub-object
of `settings.yaml`.

| Tier name | Type | Required | Description |
|-----------|------|----------|-------------|
| `basic` | string (model identifier) | yes | Cheap, fast, structured tasks. |
| `normal` | string (model identifier) | yes | Default reasoning-heavy. |
| `flagship` | string (model identifier) | yes | Critical / complex synthesis. |

**Additional tiers**: Vault authors MAY add custom tiers beyond the
three required. E.g. `experimental: claude-opus-4.8-preview`. The
framework treats any string key in `tiers:` as a valid tier name.

**Validation rules** (config-load):
- The three required tier names (`basic`, `normal`, `flagship`) MUST
  be present.
- Each value MUST be a non-empty string.
- Stage executors using `tier:` MUST reference a tier name present in
  this block. Mismatch \u2192 config-load error with clear message.

## 12. SchemaDriftReport (per D8)

Plain-markdown file at
`<vault>/_pipeline/sources/<module>/facts-schema.drift.md`. Generated
when drift is detected. NOT structured JSON (intended for human
consumption by the vault author).

**Required sections** (per R14 in research.md):

1. Header with: module name, manual schema `spec_hash`, current
   `spec_hash`.
2. "Added buckets" \u2014 in regenerated, missing from manual.
3. "Removed buckets" \u2014 in manual, not in regenerated.
4. "Changed bucket shapes" \u2014 same name, different schema.
5. "Resolution paths" \u2014 the three documented exits (acknowledge,
   remove `manually_edited`, `--force-stale-schema`).

**Sibling state**: `facts-schema.regenerated.json` is the
machine-readable sidecar that the vault author can `diff` or merge
manually.

## Relationships

```text
Vault
\u251c\u2500\u2500 research.spec.md::data_sources  \u2500\u2500scout/schema-gen\u2500\u2500> (not extraction loop)
\u251c\u2500\u2500 research.spec.md       \u2500\u2500hash\u2500\u2500> .schema-gen-hash
\u251c\u2500\u2500 settings.yaml::modules:  \u2500\u2500install copy + trigger order\u2500\u2500> TriggerRegistry
\u251c\u2500\u2500 settings.yaml::tiers   \u2500\u2500resolved by\u2500\u2500> Stage executor.tier:
\u251c\u2500\u2500 modules/<name>/manifest.yaml
\u2502   \u251c\u2500\u2500 source_id_from \u2500\u2500derives\u2500\u2500> source_id from sources.yaml
\u2502   \u2514\u2500\u2500 default_tier \u2500\u2500resolved by\u2500\u2500> Stage executor (fallback)
\u251c\u2500\u2500 modules/<name>/sources.yaml \u2500\u2500enumerates\u2500\u2500> source-extraction loop
\u251c\u2500\u2500 <module>.validators.yaml \u2500\u2500evaluates\u2500\u2500> SignalPayload
\u251c\u2500\u2500 <module>.validators.py   \u2500\u2500evaluates\u2500\u2500> SignalPayload
\u2514\u2500\u2500 _pipeline/sources/<module>/
    \u251c\u2500\u2500 facts-schema.json    \u2500\u2500constrains\u2500\u2500> SignalPayload.facts
    \u251c\u2500\u2500 watermarks.json      \u2500\u2500points to\u2500\u2500> signals/<source>-<version>.json
    \u251c\u2500\u2500 signals/             \u2500\u2500consumed by\u2500\u2500> scout (next stage)
    \u2514\u2500\u2500 consensus/           \u2500\u2500audit of\u2500\u2500> ConsensusResult per cycle
```

## Invariants across entities

- **Cache key invariant**: `(module, source_id, source_version)` MUST
  uniquely identify a SignalPayload. Two payloads with the same key
  must be content-identical (framework writes are deterministic).
- **Watermark consistency**: a Watermark entry's `source_version` MUST
  match the `source_version` of the most-recent SignalPayload file
  for that source.
- **Schema-gen idempotency**: running schema-gen twice on the same
  `(vault, module, spec_hash)` pair MUST produce semantically-equivalent
  schemas (model non-determinism notwithstanding). Tested via
  `tests/source_bridge/test_schema_gen.py::test_idempotency`.
- **Module isolation invariant** (D9): a cycle MUST NEVER abort due to
  module-subsystem failure, regardless of how many sources fail.
  Tested via `test_module_isolation.py::test_all_sources_fail_cycle_continues`.
