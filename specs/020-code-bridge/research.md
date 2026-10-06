# Phase 0 Research: Source-Module Architecture

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)
**Date**: 2026-05-20 (initial) / 2026-05-26 (source-enumeration refresh)

This document consolidates the implementation-time decisions surfaced
during plan.md Phase 0 plus `/speckit.clarify` decisions from
2026-05-20 (D5–D9) and **Session 2026-05-26** (source enumeration +
module discovery). All `NEEDS CLARIFICATION` markers are resolved as of
the spec's [`## Clarifications > ### Session 2026-05-26`](./spec.md)
block.

## Section 1 \u2014 Original Phase 0 plumbing decisions

These are decisions ABOUT HOW to implement the architecture, not WHAT
to build. They were proposed in `plan.md` Phase 0 and are finalized
below.

### R1 \u2014 Git invocation strategy for the code module

**Decision**: Use stdlib `subprocess.run(['git', ...])` directly. No
new Python git library (e.g. `GitPython`, `dulwich`) added.

**Rationale**: Principle V (no new runtime dependencies). The same
pattern already lives in `src/research_framework/pipeline/migrator_git.py`,
proven robust through 0.2.x. Operations we need:
`git rev-parse HEAD` (source_version), `git log --name-only --since=...`
(freshness window), `git ls-files` (file enumeration for the
extractor's walk). All cheap, all stdlib-compatible.

**Alternatives considered**:
- `GitPython`: friendlier API but adds a dependency tree (`gitdb`,
  `smmap`) for marginal ergonomic benefit. Rejected.
- `dulwich`: pure-Python git implementation; would let us skip the
  external `git` binary. Rejected because the binary is universally
  available on macOS/Linux dev machines and `dulwich` is +3000 LOC
  of attack surface.

### R2 \u2014 Bridge subprocess invocation pattern

**Decision**: Bridge spawns from `cycle_runner` via
`subprocess.run([sys.executable, 'scripts/source_bridge.py', ...])`,
matching `scripts/agent_call.py`. Returns:
- rc=0 on cache-hit (no extraction needed).
- rc=0 on successful extraction.
- rc=2 on hard failure (config error, FS write failure).

Bridge writes structured JSON log lines (one per line) to stderr so
the parent runner can `cycle_runner` can surface per-source status
without re-parsing free text.

**Rationale**: Matches every other pipeline stage. No new IPC
mechanism. Stderr-as-log is the existing convention (used by
`validate_cycle.py`, `topic_harvest.py`, etc.).

### R3 \u2014 Module subprocess invocation pattern

**Decision**: Bridge spawns each module's extractor via:

```python
subprocess.run(
    [sys.executable, f'{vault}/modules/{name}/extractor.py'],
    input=json.dumps({
        'source_id': ...,
        'source_version': ...,
        'schema': {...},          # the per-(vault, module) schema
        'value_tier': 'routine',  # resolved by caller
    }).encode(),
    capture_output=True,
    timeout=600,
)
```

Module returns a JSON SignalPayload on stdout. Manifest's `entry_point`
field names the file. Liveness via status-file heartbeat at
`_pipeline/sources/<module>/.status/<source-id-hash>.json` updated
every ~5s by the module (optional but recommended for long-running
extractions).

**Rationale**: Subprocess isolation is the load-bearing isolation
boundary (per D5 + D9). Structured stdin/stdout JSON is the
contract; modules don't import framework code at all.

### R4 \u2014 Signal-payload size limits

**Decision**: Hard cap 100 KB per payload. If a module produces more,
the framework truncates `notable` (preserving `facts` and envelope
fully) and sets `truncated: true` in the envelope. WARN logged with
the original size.

**Rationale**: Bounds cache disk and prompt input size to scout.
`facts` is structured and bounded by the per-vault schema; `notable`
is the free-text growth vector. Truncating `notable` preserves
structured data even when freeform observations sprawl.

**Alternatives considered**:
- Hard fail at 100 KB. Rejected because losing all data is worse than
  losing some freeform observations.
- Compressed cache files. Rejected because the disk math doesn't
  justify the read-side complexity.

### R5 \u2014 Schema versioning

**Decision**: Every `SignalPayload` envelope includes a
`bridge_version` field. Every `Watermark` entry includes the same.
On cache lookup, mismatch \u2192 invalidate that source's cache entry and
re-extract.

**Bridge_version bump policy**: bumped ONLY when the envelope schema
or extractor contract changes. Cosmetic framework releases (typos,
docs, performance) do NOT bump it.

**Rationale**: Decoupling the framework's `__version__` from
`bridge_version` means most releases serve cache hits across the
update boundary. Only structural changes force re-extraction.

### R6 \u2014 Spec-hash tracking for schema-gen invalidation

**Decision**: Store
`<vault>/_pipeline/sources/<module>/.schema-gen-hash` containing
`sha256(research.spec.md bytes)`. On any pipeline start, compare
current `research.spec.md` hash to the stored value. Mismatch \u2192
regenerate schema (or, with D8, trigger drift detection if
`manually_edited: true`).

**Rationale**: One small file per (vault, module). Cheap to read,
cheap to compare. SHA256 is overkill for the use case but it's
stdlib and the standard the rest of the codebase uses.

### R7 \u2014 Concurrent extractor invocations for consensus

**Decision**: Use `concurrent.futures.ThreadPoolExecutor(max_workers=N)`
where N is the resolved value_tier consensus count (per D2). Bridge
fans out, collects with `as_completed`, voting + finding-union
happens after all complete.

**Rationale**: Each extractor is a subprocess; threads are sufficient
to wait on them. No async/await complexity. Matches the existing
pattern in `pipeline/orchestrator.py` for parallel scout calls.

### R8 \u2014 First-match-wins trigger ordering

**Decision**: Use `settings.yaml::modules:` array order as
registration order. First matching trigger (across all triggers for
all modules in order) wins. The `--debug-triggers` flag on
`scripts/source_bridge.py` (task 12 / 27) prints the registry +
per-source match attempts for any given source.

**Rationale**: Deterministic. Vault-author-visible ordering surface.
No precedence rules to memorize.

### R9 \u2014 Manifest-discovery cadence

**Decision**: Walk `<vault>/modules/*/manifest.yaml` on every
pipeline start. No registry caching between runs.

**Rationale**: Cost is < 10 ms for a 10-module vault. Simplifies the
"drop a module folder into modules/" UX (auto-pickup on next run, no
config invalidation). Worth the trivial overhead.

### R10 \u2014 Module trust boundary

**Decision** (settled per D5): permissive default + documented. Trust
boundary documented in:
- `install.sh` interactive prompt when `settings.yaml::modules:` is
  non-empty: "Modules execute arbitrary Python; only install modules
  you trust. Continue? [y/N]"
- `quickstart-module-author.md` opens with a bold
  `> ## WARNING: Trust Boundary` section.

**NOT enforced technically in v1.** A future sandbox spec MAY add
subprocess + restricted-env isolation as opt-in via
`settings.yaml::stages.source_extraction.sandbox: true`.

## Section 2 \u2014 Clarification-driven decisions (2026-05-20)

These resolve the five `/speckit.clarify` Q&A from 2026-05-20.
Cross-referenced with plan.md `[DECIDED]` markers D5\u2013D9.

### R11 (D5 in plan) \u2014 Module trust boundary

Already documented in R10 above. No separate research needed.

### R12 (D6 in plan) \u2014 Module version compatibility on framework updates

**Decision**: Migrator (013) extends to re-copy each module **listed
in `settings.yaml::modules:`** from the new framework bundle on
`./vault update`. Modules NOT in the list are NOT auto-copied.

**Implementation notes**:
- Migrator reads `settings.yaml::modules:` from the vault's current
  settings (NOT the bundle's default).
- For each name in that list, refresh framework code under
  `<vault>/modules/<name>/` from the bundle. **`sources.yaml` and
  `user_owned` paths are preserved if present** (R26 / FR-025).
- Pre-copy manifest validation: parse `<bundle>/.../<name>/manifest.yaml`
  against `contracts/manifest.schema.json`. On validation failure: abort
  the update with a clear error pointing at the offending bundle module.
  Vault-side state stays as-is (no half-update).
- A new `--no-refresh-modules` migrator flag lets the user skip
  module-refresh during an update (e.g. when iterating on a vault-local
  manual edit). Default: refresh.

**Rationale**: Atomic update semantics. User intent (the `modules:`
list) is honored automatically; user gets to deviate via an explicit
flag.

**Alternatives considered**:
- Auto-copy ALL bundle modules. Rejected (violates user's explicit
  selection).
- Hard-error on version mismatch and require explicit `--refresh-modules`
  every time. Rejected (too much ceremony for the common case).

### R13 (D7 in plan) \u2014 Tier-based model selection

**Decision**: Introduce top-level `tiers:` block in `settings.yaml`:

```yaml
tiers:
  basic: claude-haiku-4.6      # cheap, fast, structured tasks
  normal: claude-sonnet-4.6    # default for reasoning-heavy stages
  flagship: claude-opus-4.7    # critical / complex synthesis
```

For codex-primary users, equivalent identifiers go in
`settings.codex.yaml` (e.g. `basic: gpt-5-codex-mini`, etc.).

**Stage executor consumes via `tier:`**:

```yaml
stages:
  schema_gen:
    tier: basic                # NEW: resolved via tiers block
  source_extraction:
    tier: basic                # default for routine value_tier
  scout:
    model: sonnet              # EXISTING: legacy model: field, unchanged
```

**Resolution rules** (config-load):
1. If executor has `tier:` set, resolve to `tiers[tier]`. If the named
   tier doesn't exist, fail config-load with clear error.
2. If executor has both `tier:` and `model:` set, fail config-load
   with clear error (mutually exclusive).
3. If executor has only `model:` set (legacy), use the model
   identifier directly. Existing behavior.
4. If executor has neither, use the global default from `executors:`
   block (existing behavior).

**Module-side**: `manifest.yaml::default_tier` is the module author's
hint for the value_tier mapping. Framework respects it unless the
user explicitly overrides at the stage executor.

**Rationale**: Single source of truth for vendor/model identity.
Module authors signal complexity without knowing user's runtime.
Scope-bounded to NEW stages (no legacy migration in 020).

**Alternatives considered**:
- Per-stage `model:` (current) extended to schema-gen. Rejected (every
  vault would duplicate the model name across N stages).
- YAML anchors/aliases (`&basic claude-haiku-4.6` then `*basic`).
  Rejected (anchors are a YAML feature, not first-class in the
  framework's config model \u2014 confusing to debug).
- Use `model-router` skill at runtime. Rejected (adds a meta-LLM call
  per stage call, overhead).

### R14 (D8 in plan) \u2014 Drift detection on manually-edited schemas

**Decision**: Fail-closed cycle abort on drift unless
`--force-stale-schema` is passed.

**Sidecar layout**:

```
<vault>/_pipeline/sources/<module>/
\u251c\u2500\u2500 facts-schema.json                    # the manual schema (manually_edited: true)
\u251c\u2500\u2500 facts-schema.regenerated.json        # NEW: schema-gen output on this run
\u251c\u2500\u2500 facts-schema.drift.md                # NEW: structural diff
\u2514\u2500\u2500 .schema-gen-hash                     # spec hash at last regeneration
```

**`facts-schema.drift.md` format** (machine-generated, human-readable):

```markdown
# Schema Drift Detected

**Module**: code
**Manual schema spec_hash**: abc123... (last regenerated 2026-05-15)
**Current spec_hash**: def456...

## Added buckets (in regenerated schema, missing from manual)
- `compliance_constraints` (list[str])

## Removed buckets (in manual schema, not in regenerated)
- `legacy_apis` (list[str])

## Changed bucket shapes
- `data_stores`: was `list[str]`, now `list[{name, kind}]`

## Resolution paths
1. Merge `facts-schema.regenerated.json` into `facts-schema.json`,
   then bump the watermark:
   `research-framework schema --acknowledge-drift code`
2. Remove `manually_edited: true` from `facts-schema.json` to let
   schema-gen regenerate authoritatively.
3. Ignore drift and proceed: pass `--force-stale-schema` on the
   cycle-running CLI. Drift detection skips for this run only.
```

**CLI surface**:
- `research-framework generate --force-stale-schema` proceeds despite
  drift (logged as WARN in the cycle's run-report).
- `research-framework schema --acknowledge-drift <module>` bumps the
  `.schema-gen-hash` to the current spec hash, marks drift as
  resolved. Implies the user merged the sidecar manually.

**Rationale**: Fail-closed honors the user's responsibility opt-in.
The three resolution paths give the user clear, documented exits.
Matches existing fail-closed validation posture.

**Alternatives considered**:
- Auto-merge sidecar into manual schema. Rejected (silent rewriting
  of user-edited file is worse than failing).
- Stay silent. Rejected (high risk of stale schemas going unnoticed).
- Warn-only. Rejected (user requested fail-closed).

### R15 (D9 in plan) \u2014 Module-isolation policy

**Decision**: Retry-once + salvage-and-continue for ALL module-subsystem
unhandled exceptions (extractor crash, validator Python exception,
manifest parse error).

**Algorithm**:

```python
def isolated_call(callable, *args, source_id, source_module, **kwargs):
    """Run callable with retry-once + salvage + isolation."""
    partial_output = None
    for attempt in (1, 2):
        try:
            return callable(*args, **kwargs)
        except Exception as exc:
            partial_output = getattr(exc, 'partial', None) or partial_output
            log_to_bridge_log(source_id, source_module, attempt, exc)
            log_to_agent_calls(source_id, source_module, attempt, exc)  # FR-024
            if attempt == 2:
                # Final failure: salvage and continue
                if partial_output:
                    write_partial_payload(source_id, source_module, partial_output)
                mark_source_failed(source_id, source_module)
                surface_in_run_report(source_id, source_module, exc)
                return None
            # else: retry
```

**Salvage semantics**:
- If the module's extractor produced partial stdout before crashing
  (e.g. wrote half a JSON payload then segfaulted), the framework
  attempts `json.loads` on increasingly-shortened prefixes until
  a valid JSON object parses. That partial payload is written with
  `verdict: "error"`, `partial: true`.
- Modules can explicitly emit partial state by raising an exception
  with a `.partial` attribute carrying the salvageable payload.
- If nothing parseable was produced, the source's signal becomes
  empty for this cycle (existing FR-023 behavior).

**Run-report surface**: A new section in
`_pipeline/cycles/cycle-NNN/run-report.md`:

```markdown
## Module-Subsystem Issues

The following module-subsystem failures occurred this cycle. The
pipeline continued; the failures are surfaced here so you can
investigate.

| Source | Module | Failure | Salvaged? | Log |
|--------|--------|---------|-----------|-----|
| /Users/.../my-repo | code | TimeoutError after 600s (retry: same) | partial (12/40 files) | bridge.log:142 |
| https://reddit.com/r/foo | reddit | ValidatorPyException (KeyError) | no | bridge.log:198 |
```

**Rationale**: Modular architecture exists specifically for
isolation. Retry-once handles transient flakes. Salvage preserves
useful work. Run-report surfacing closes the visibility gap so
failures don't get buried.

**Alternatives considered**:
- No retry, isolate on first failure. Rejected (transient network
  issues become permanent cycle damage).
- Three retries with backoff. Rejected (one cycle taking 3 \u00d7 600s on
  a hung extractor is too long; one retry suffices for transient
  cases and surfaces persistent issues fast).
- Halt cycle on any module failure. Rejected (violates the
  isolation principle the architecture is built around).

## Section 3 \u2014 Constitution check post-design

Re-running the Constitution Check from plan.md against the now-locked
design (5 new clarification decisions integrated):

- **Principle V (no new runtime deps)**: \u2713 Confirmed. All new
  decisions use stdlib (`concurrent.futures`, `subprocess`,
  `hashlib`, `json`, `pathlib`) plus existing deps. No new
  third-party packages.
- **Domain-agnostic principle (Constitution 1.3.2 expansion; NB: not to be confused with the post-1.4.0 Principle X, which is the auto-commit invariant)**: \u2713
  Confirmed. Tier-based model selection (R13) is vendor-agnostic by
  design \u2014 the same `tier: basic` resolves correctly for Claude,
  codex, or any future runtime via the user's `tiers:` block.
  Schema-gen (D1) remains the load-bearing context-agnostic
  mechanism for facts schemas.
- **Single LLM dispatch surface**: \u2713 Confirmed. All R13 tier
  resolution happens at `agent_call.py` load time. Per-call agent
  logging (FR-024) captures every invocation from this single
  surface.
- **Test-pyramid (018)**: \u2713 Confirmed. New tests added:
  - `tests/source_bridge/test_schema_drift.py` (R14, D8)
  - `tests/source_bridge/test_module_isolation.py` (R15, D9)
  - `tests/config/test_tier_resolution.py` (R13, D7)
  - `tests/migrator/test_module_refresh.py` (R12, D6)
- **Code-first / intent-first ordering**: \u2713 Unchanged. The
  source-bridge IS the codified code-first half; scout shrinks
  toward intent-first.

No constitutional violations.

## Section 4 \u2014 Implementation-time choices still pending

These weren't covered by the clarification session but were noted in
plan.md as TBD for research.md to settle. Resolving here:

### R16 \u2014 Where does `pursuit_state`-style metadata live for the bridge?

**Decision**: Inside the watermark file. Atomicity matters; one fewer
file per source.

### R17 \u2014 `--debug-triggers` flag output format

**Decision**: Markdown-formatted table to stdout. Example:

```
$ python scripts/source_bridge.py --debug-triggers https://youtube.com/watch?v=abc

# Trigger Registry (settings.yaml::modules order)

| Order | Module | Trigger type   | Pattern              | Matched? |
|-------|--------|----------------|----------------------|----------|
| 1     | code   | path_pattern   | `.+/\\.git/HEAD`     | NO       |
| 2     | youtube| url_pattern    | `(youtube\\.com|youtu\\.be)` | YES |

# Resolution: source matched module 'youtube' (first match wins)
```

### R18 \u2014 Module install-time copy implementation

**Decision**: Use `shutil.copytree(..., dirs_exist_ok=True)` in a
Python helper inside `install.sh` (called via `python -c`). Wraps
in try/except; rolls back on any failure (removes the partially-copied
directory). Manifest validation pre-copy: parse `<bundle>/.../<name>/manifest.yaml`
against `contracts/manifest.schema.json` before touching the vault.

### R19 \u2014 Schema-gen prompt few-shot example sources

**Decision**: `facts-schema-gen-prompt.md` ships with two contrasting
few-shot examples baked in:
- A web-microservices vault (drawn from the user's reference-vault spec).
- An embedded-firmware vault (drawn from
  `tests/fixtures/vault-embedded-firmware/` once Block F is built).

These prove to the schema-gen agent that the framework expects
domain-divergent output, not a generic template.

### R20 \u2014 Signal cache file format: `.json` per extraction (NOT `.jsonl`)

**Decision** (settled 2026-05-20): Each cached extraction is written
as a single `.json` file at
`_pipeline/sources/<module>/signals/<source-stem>-<version>.json`.
NOT a per-source append-only `.jsonl`.

**Rationale**:
- **O(1) cache lookup.** The framework's only access pattern is
  cache-key resolution: given `(module, source_id, source_version)`,
  produce the payload. Filename-keyed lookup with no parsing until
  cache-hit confirmed beats any JSONL scan or sidecar-index scheme.
- **Watermark map is the index.** `watermarks.json` already maps
  `source_id \u2192 source_version`; that version directly composes the
  filename. JSONL would re-introduce the lookup problem the watermark
  already solves.
- **GC is trivial** (D3, 30-day retention): `os.remove(path)` per
  stale file. JSONL would require read-filter-rewrite cycles that are
  crash-unsafe in the worst case.
- **Atomic writes.** `NamedTemporaryFile` + `os.replace` works
  trivially per file. JSONL append + crash mid-write would leave
  a partial line that corrupts forensics.
- **Consensus doesn't push back on this.** D2 spawns N extractors
  per source but the framework caches ONE final consensus payload
  (vote winner + union of findings). The N pre-consensus payloads
  live in `agent-calls/` for forensics, not in `signals/`. So there
  is no "many writes per cycle to the same source" pressure that
  would favour append-only.

**Alternatives considered**:
- Per-source `.jsonl`. Rejected per above.
- Per-source `.json` (overwritten on each extraction, history lost).
  Rejected because we want sample-level history during the
  30-day retention window for debugging cache misses.

**Implementation note**: `<source-stem>` is derived from `source_id`
via a simple normalizer:
- For path-shaped source_ids: take `basename(source_id)`, slug-cased.
- For URL-shaped source_ids: take the last meaningful URL segment,
  slug-cased.
- Always hash-suffix to disambiguate (e.g. `my-repo-abc12345-<6-char hash>`)
  to prevent collisions across modules/users.

### R21 \u2014 Heartbeat policy: 30s poll / 60s stall / warn-only / configurable hard timeout

**Decision** (settled 2026-05-20): The heartbeat mechanism is a
one-way module \u2192 framework liveness signal via a status file. The
framework polls at fixed cadence, warns on stall, but does NOT kill
mid-extraction. Hard wall-clock timeout remains the safety net (D9).

**Parameters**:

| Parameter | Value | Configurable? |
|-----------|-------|---------------|
| Module write cadence (target) | ~5s between updates | No (recommendation) |
| Parent poll cadence | 30s | No (hardcoded in v1) |
| Stall threshold | 60s without update | No |
| Action on stall | WARN only \u2014 log + run-report | No |
| Hard wall-clock timeout | 600s default | Yes (per-module) |

**Configurable hard timeout** (NEW):
- `manifest.yaml::extraction_timeout_seconds: <int>` (optional;
  default 600). Modules with legitimately-long extractions (e.g.
  video transcription) override here.
- `settings.yaml::stages.source_extraction.timeout_seconds: <int>`
  (optional; overrides manifest default for this vault). Vault
  authors who want to enforce a tighter budget can clamp.
- Resolution: vault setting wins if present, else manifest default,
  else hardcoded 600.

**Status-file format** (lives at
`_pipeline/sources/<module>/.status/<source-id-hash>.json`):

```json
{
  "progress": 0.42,
  "current_file": "src/api/UserController.java",
  "updated_at": "2026-05-20T15:42:33Z",
  "extractor_pid": 12345
}
```

The `extractor_pid` is added so the parent can disambiguate when
heartbeat files from earlier dead processes linger (e.g. after
SIGKILL didn't trigger cleanup).

**Parse-robustness**: parent reads with `try: json.loads(...)`. On
parse error: treat as "no recent heartbeat" (= 60s elapsed). Mid-
write partial JSON is therefore handled gracefully \u2014 the next
successful write fixes the file on the next poll cycle.

**Race with consensus (D2)**: when N>1 extractors run for the same
source, they all write to the same status path. Last writer wins.
Acceptable because the contents are diagnostic, not load-bearing.
Per-extractor isolation would require a spawn-index suffix; not
worth the complexity.

**Run-report surface**: stalled extractions appear in the
"Module-Subsystem Issues" section of `run-report.md` even when they
complete eventually (so the user sees that something WAS slow and
can investigate the prompt). Format:

```markdown
### Stalled extractions

The following extractions exceeded 60s without a heartbeat update
(but completed eventually within the 600s wall-clock budget):

| Source | Module | Stall duration | Last heartbeat | Final outcome |
|--------|--------|----------------|----------------|---------------|
| /Users/.../my-repo | code | 184s | progress=0.62, src/api/big_file.java | ok |
```

If empty, the sub-section is omitted.

**Rationale for warn-only (not kill-on-stall)**:
- D9's 600s hard timeout is already the load-bearing safety net.
- Kill-on-stall would punish modules whose long operations don't
  lend themselves to progress updates (e.g. a `subprocess.run` to
  an external transcript tool that doesn't expose progress).
- A future iteration can opt into `manifest.yaml::heartbeat_policy:
  kill_on_stall` if real-world data shows zombie subprocesses are
  common. v1 ships with warn-only and revisits.

**Alternatives considered**:
- Kill-on-stall by default. Rejected per above.
- Per-manifest `heartbeat_policy: warn | kill` knob. Deferred to v2
  pending evidence.
- Parent-side liveness via `psutil.is_running(pid)` instead of file
  polling. Rejected: requires reading the heartbeat file anyway to
  surface progress; adds `psutil` dependency (Principle V violation).

---

## Section 5 — Resolved 2026-05-26 (post-clarify Session)

Source-enumeration and module-discovery decisions from
`/speckit.clarify` Session 2026-05-26 (spec.md). Cross-ref FR-010,
FR-013a–c, FR-025; ADR-0009 option A (020 supersedes 014/015).

### R22 — Per-module `sources.yaml` is the extraction enumeration

**Decision**: Each installed module owns
`<vault>/modules/<name>/sources.yaml` beside `manifest.yaml`. The
source-extraction stage iterates every record in every discovered module's
file. Missing file → zero sources for that module + WARN once per pipeline
start.

**Rationale**: Module isolation (no merge conflicts across modules);
stable `source_id` derivation per module; matches feeds-vault revival path
(youtube port splits legacy `scripts/sources.yaml` once).

**Alternatives considered**:
- Single vault-level `sources.yaml` — rejected (merge conflicts, breaks
  module isolation).
- Hybrid dual-file with precedence — rejected (two sources of truth).

**Migration**: Vault-level `scripts/sources.yaml` (feeds-vault prior art) is
a **one-time porting input** when landing the first 020-shaped module, not
a runtime enumeration surface.

### R23 — Split: `sources.yaml` vs `research.spec.md::data_sources`

**Decision**: `sources.yaml` is authoritative for **what to extract**
(FR-013a). `data_sources` remains authoritative for **scout coverage framing
and schema-gen context** (FR-014). The framework MUST NOT derive the
0.3.0 extraction loop from `data_sources` alone. Authors SHOULD keep both
in sync manually during migration; no automatic cross-sync in 020.

**Rationale**: Spec contract for scout/coverage must stay stable; extraction
enumeration belongs with the module that knows instance shape.

**Alternatives considered**:
- `data_sources` as sole driver — rejected (pre-clarify assumption; wrong
  for multi-module vaults).
- Auto-sync in 020 — rejected (scope; deferred to future spec).

### R24 — Filesystem walk is authoritative for runtime module discovery

**Decision**: FR-010 unchanged in spirit: scan `<vault>/modules/*/manifest.yaml`
every pipeline start; every manifest on disk is registered. `settings.yaml::modules:`
controls **only** (1) which modules `install.sh` / `./vault update` copy from
the bundle, and (2) trigger-registry **precedence order** (first-match wins).
Drop-in folders work without editing settings (SC-007).

**Rationale**: Operator UX for manual module drops; settings list is install
intent, not runtime gate.

**Alternatives considered**:
- Settings-only discovery — rejected (blocks drop-in modules).

### R25 — Trigger registry: in-memory only, no `_pipeline/` cache

**Decision**: Build `TriggerRegistry` in memory from the filesystem walk on
each pipeline start. Do not persist under `_pipeline/`.

**Rationale**: Drop-in modules would stale a cache; ~ms cost at 5–50 sources.

**Alternatives considered**:
- Persisted registry under `_pipeline/` — rejected (invalidation complexity
  for no win at vault scale).

### R26 — `./vault update` preserves user-owned module files

**Decision**: On update, framework code under `<vault>/modules/<name>/` refreshes
from the bundle (FR-012), but **existing `sources.yaml` MUST NOT be overwritten**
(FR-025). Seed from bundle template only when absent. Unconditional — does not
require `keep_overrides` in settings. `manifest.user_owned` MAY list additional
relative paths (e.g. `custom_prompt.md`) with the same preserve-if-present rule.
Orthogonal to spec 023 `in-loco-modules.json` (governs `scripts/`, not `modules/`).

**Rationale**: Operator-edited channel lists are long-lived vault state; code
refresh should not clobber them.

**Alternatives considered**:
- Overwrite `sources.yaml` on every update — rejected (data loss on revival).
- Tie preservation to `keep_overrides` — rejected (unnecessary ceremony per
  clarify).

## Summary

All `NEEDS CLARIFICATION` markers resolved **as of 2026-05-26 Session**
(see spec.md Clarifications block). Decisions from 2026-05-18 through
2026-05-20 (R1–R21, D5–D9) plus Session 2026-05-26 (R22–R26) are
captured here. Ready for `/speckit.tasks` refresh (notably extraction loop
must iterate `sources.yaml`, not `data_sources` alone).
