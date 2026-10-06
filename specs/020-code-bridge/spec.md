# Feature Specification: Source-Module Architecture \u2014 Cached, Pluggable Data Source Access

**Feature Branch**: `020-code-bridge` (directory name preserved for git
history continuity; the spec's identity has broadened from "code-bridge"
to "source-module architecture")
**Created**: 2026-05-18
**Last Revised**: 2026-05-26
**Status**: shipped(2026-05-27, PR #32) — SHIPPED 0.4.0 (2026-05-27, impl PR #32 squash `27a8949` on main; released as part of the Revival-sprint Wave 1 recovery bump via PR #34). 123 tasks across 10 blocks executed under the foreman
verification pattern (test-design → implementer → foreman) — the largest
of the Revival-sprint Wave 1 specs. Copilot review fix-up commit
`18077bb` addressed 14 inline findings: stable SHA-256 `source_stem()`
digest (replacing `hash()` randomization), payload-size cap trims against
the progressively-trimmed `notable` list, `write_fallback_schema` returns
a schema `dict` (was returning `Path`), heartbeat-aware poll interval,
consensus workers go through `isolated_call()` (retry/quarantine), futures
collected in submission order for deterministic merge, `_validate_consensus_n`
rejects non-int and non-odd N at settings load, `FakeRepo` sets git
identity env vars for CI, `run_extraction(force_stale_schema=...)` ack
+ T111 docstring note for full propagation, empty `{}` validators file
honored, `load_facts_schema()` fail-soft on `JSONDecodeError`,
extractor-contract assertion strengthened, FR-009 module-tagging now
Step 2b (not gated on quality-gate), consensus orchestration test
requires `consensus_dir.is_dir()` + ≥1 `*.json`. Pre-implement
reconciliation (PR #27) addressed 1 CRITICAL + 5 HIGH findings before
implementation; PR #32 then resolved 14 of 14 Copilot review findings
on the impl. **Closes Revival-sprint Wave 1** alongside PRs #28/29/30/31.
**Input**: User brainstorming session 2026-05-18 (post-0.2.30 audit) +
follow-up sessions 2026-05-19 and 2026-05-20 generalizing the design from
code-specific to module-pluggable. Together they capture the architecture
for cached, schema-driven, value-tiered access to ANY data source.

## What this spec is

Two combined goals:

1. **Short-term (load-bearing for 0.3.0)**: Eliminate the per-cycle code-walk
   waste the 0.2.30 audit surfaced \u2014 cache code signals on disk keyed by
   a stable per-source key, so the scout reads from cache instead of
   re-walking every cycle.
2. **Long-term (groundwork for 0.4.0+)**: Generalize the cache + extractor +
   validator + schema pattern into a **pluggable source-module architecture**.
   Modules ship in the framework, are selected per-vault, and apply their
   own extraction logic to sources whose triggers they match (URL patterns,
   path patterns, etc.). Code is the first module; YouTube, Reddit, O'Reilly,
   and any future source types follow the same contract without framework
   changes.

The 0.3.0 release ships ONE module (code) and the full module-architecture
plumbing. The deferred modules (YouTube, Reddit, O'Reilly, custom) port
later without spec changes \u2014 they just drop into the framework's `modules/`
tree and conform to the contract this spec defines.

## Clarifications

### Session 2026-05-18 \u2014 original code-bridge brainstorming

The user and agent worked through the design as a structured
brainstorming pass. Decisions captured verbatim from that session:

- Q: What shape should the per-cycle code signal carry \u2014 a strict
  per-vault schema (A), a hand-coded extractor (B), a large freeform
  observation payload (C), or freeform + guardrails (D)? \u2192 **A mix of
  C and D**. Give agents room to say things the framework didn't
  anticipate, but bound them with guardrails so the same observations
  don't drift across cycles. Guardrails should be **per-vault**, not
  framework-global \u2014 the framework provides the slot, the vault
  provides the shape. Important: give the agent the affordance to
  declare "nothing useful here anymore."
- Q: Should the code-extractor be a NEW pipeline stage, a sub-step of
  scout, an agent skill, or a CLI helper? \u2192 **A new separate stage**.
  Keeps the contract explicit and lets it run on its own cadence,
  independent of scout.
- Q: How often should the extractor run \u2014 every cycle, only on cycle 0,
  every Nth cycle, or only when the commit SHA drifts? \u2192 **Only on
  source-version drift**. Sources are static between versions;
  re-walking is waste. Maintain a per-source watermark.
- Q: How should agents request fresh source information mid-cycle \u2014 not
  at all (A), free re-read (B), explicit "probe" call (C), or separate
  mini-MCP module (D)? \u2192 **D for now.** Source access becomes a
  separate module that agents never touch directly. One entry, one
  exit. Makes caching trivial and makes some validations independent
  of the research spec.
- Q: Implementation shape of the bridge \u2014 in-process Python module (A),
  subprocess script (B), local HTTP server (C), or actual MCP server
  (D)? \u2192 **Subprocess script**. Matches the rest of the framework's
  invocation pattern (every stage is `python scripts/<name>.py`).
  Cheapest to ship; can graduate to D later without breaking the
  contract.
- Q: How should per-vault validators be expressed \u2014 strict-schema only
  (A), strict + custom (B), arbitrary YAML rules (C), or YAML rules
  with a Python escape hatch (D)? \u2192 **YAML rules + Python escape
  hatch.** Most rules are simple "this category must be present" or
  "this field must be a non-empty list"; the escape hatch lets a
  vault layer in a cross-field check without having to fork the
  framework.

### Session 2026-05-20 \u2014 generalization to source-module architecture

Decisions from the follow-up session, all locked:

- Q: Default `facts` schema shape \u2014 ship 9 fixed buckets (technologies,
  patterns, data_stores, etc.), or generate the schema per-vault from
  the spec? \u2192 **Generate per-vault, dynamically.** A small agent
  (Haiku-equivalent) reads the vault's `research.spec.md` + module
  context and produces a JSON Schema tailored to THIS vault THIS
  module. Schemas are stored in vault state and regenerated only on
  spec-hash change. The 9 buckets from prior discussion become
  few-shot examples in the schema-gen prompt, not hardcoded defaults.
  This satisfies constitution Principle "domain-agnostic by
  construction" (Constitution 1.3.2).
- Q: Consensus mechanism \u2014 always N=2 with union-on-disagreement, or
  something better? \u2192 **Value-tiered consensus.** The caller declares
  a `value_tier` (`routine | important | critical`) per invocation;
  the framework maps tier \u2192 odd N (defaults 1 / 3 / 5). Framework
  validates N is odd at config-load time. For N\u22653: majority vote on
  `verdict`, union of findings. Default for every v1 invocation is
  `routine` (N=1) until heuristics for escalation are developed.
- Q: GC for stale signal files \u2014 K-per-source or time-based? \u2192
  **Time-based, 30 days.** Watermark is the active pointer; older
  signals are dead weight. Audit trail (consensus records, bridge
  log) is **never** auto-GC'd. Setting:
  `stages.source_extraction.signal_retention_days: 30 | 0` (0 = never).
- Q: Concrete extractor prompt \u2014 design-time decision or
  implementation iteration? \u2192 **Defer to implementation.** Framework
  ships a v1 prompt per module; tune against the user's test vaults
  until SC-002/SC-003 metrics hit; locks as v1. **Plus**: add
  framework-wide per-call agent logging (prompt + response captured at
  the single `agent_call.py` dispatch surface), stored under
  `_pipeline/cycles/cycle-NNN/agent-calls/<stage>-<call-id>.json`.
  This lands as a separate commit during 0.3.0 work \u2014 still in this
  spec, not split out.
- Q: How do modules plug in \u2014 framework-built-in only, vault-local, or
  both? \u2192 **Framework-only for code, copied to vault at install.**
  Module code lives in `src/research_framework/modules/<name>/`
  (single source of truth). At install, the names listed in
  `settings.yaml::modules:` are **copied** from the framework bundle
  into `<vault>/modules/<name>/`. The vault is then self-contained.
  Post-install, the user can manually copy additional modules from
  the framework bundle if they later need them \u2014 the framework
  scans the vault's `modules/` folder on every pipeline start.
- Q: How do modules claim sources \u2014 explicit per-source assignment in
  the spec, or trigger-based auto-routing? \u2192 **Trigger-based.** Each
  module's manifest declares triggers (URL patterns, path patterns).
  When the pipeline encounters a source, it checks the trigger
  registry; first match wins (order is `settings.yaml::modules:` array
  order). No match \u2192 fall back to generic web/file handling (existing
  pipeline behaviour, unchanged).
- Q: One unified `SignalPayload` schema across modules, or per-module
  schemas? \u2192 **Per-module schemas.** Each module's schema is generated
  per-`(vault, module)` pair by schema-gen. Schemas stored at
  `<vault>/_pipeline/sources/<module>/facts-schema.json`. The wrapper
  envelope (module name, source_id, source_version, extracted_at,
  verdict) is shared; the `facts` content shape is module-specific.
- Q: Manifest format \u2014 YAML or JSON? \u2192 **YAML.** Matches
  `settings.yaml` and `research.spec.md` frontmatter conventions;
  manifests are author-edited, not machine-generated.
- Q: Module trust-boundary enforcement \u2014 strict-by-default (sandbox),
  permissive + documented, or hybrid opt-in flag? \u2192 **Permissive +
  documented.** v1 trusts modules and per-vault validators in-process;
  warnings surface at install time and in `quickstart-module-author.md`.
  A sandbox (subprocess isolation, restricted env) is deferred to a
  follow-up spec; the contract is shaped so a future sandbox can land
  without breaking module authors. Matches the existing per-vault
  `validators.py` trust model already in 020.
- Q: Module version compatibility across framework updates \u2014 hard-error
  on mismatch (A), auto-rebuild on `./vault update` (B), warn-and-run (C),
  or manifest-declared compat range (D)? \u2192 **Auto-rebuild, scoped to
  installed modules only.** The migrator (013) extends to re-copy each
  module **listed in `settings.yaml::modules:`** from the new framework
  bundle. Modules NOT listed in `settings.yaml::modules:` are NOT
  auto-copied even if the bundle has them \u2014 the user's explicit
  module-selection choice is respected at every update. Vault-local
  manual edits to module files are overwritten by this refresh
  (documented behavior; rare in practice). Cache invalidates per FR-006
  on `bridge_version` mismatch as usual.
- Q: Where does the schema-gen agent's model come from? Inherit main
  runtime (A), separate `stages.schema_gen.model` setting (B), hardcoded
  Haiku-equivalent (C), or use the model-router skill (D)? \u2192 **Refined
  Option B \u2014 introduce a vendor-agnostic three-tier table in
  `settings.yaml`.** Add a top-level `tiers:` block mapping declarative
  complexity names (`basic`, `normal`, `flagship`) to the user's chosen
  vendor models (e.g. `basic: claude-haiku-4.6`, `normal: claude-sonnet-4.6`,
  `flagship: claude-opus-4.7`, or the codex equivalents). New stages
  introduced in 020 (`schema_gen`, `source_extraction`) reference tiers
  via a `tier:` field on the executor; the framework resolves
  `tier: basic` to the model identifier in the tiers table at
  config-load. Schema-gen defaults to `tier: basic`. Module manifests
  MAY declare a `default_tier:` so module authors signal expected
  complexity. Stages with both `tier:` and `model:` set MUST error at
  config-load (mutually exclusive). Existing stages (`scout`,
  `note_writer`, etc.) keep their current `model:` field for now \u2014
  migrating them to tiers is intentionally out of scope for 020 (a
  future refactor for settings-template hygiene).
- Q: Manually-edited schema vs spec drift \u2014 stay silent (A), detect
  and warn (B), interactive prompt (C), drift-tolerant auto-merge (D)?
  \u2192 **Detect, warn, FAIL CLOSED unless `--force` is passed.** When the
  spec hash changes AND `manually_edited: true` is set on the schema,
  the framework: (1) runs schema-gen to a sidecar
  `facts-schema.regenerated.json`, (2) computes a structural diff and
  writes `facts-schema.drift.md` with additions / removals, (3) refuses
  to proceed with the next cycle and surfaces a clear error message
  pointing the vault author at the sidecar + diff. The author resolves
  by either: (a) merging the sidecar contents into the manual schema
  and acknowledging via a CLI flag that bumps the stored spec-hash
  watermark, (b) removing `manually_edited: true` to let schema-gen
  take over again, or (c) passing `--force-stale-schema` (or
  equivalent) on the cycle-running CLI to proceed knowingly with the
  stale schema. Rationale: the user opted into responsibility when
  setting `manually_edited: true`; the framework refuses to silently
  honour a stale contract. Matches the existing fail-closed posture
  on validation errors.
- Q: Module-subsystem unhandled exceptions (validator throws, extractor
  crashes, manifest parse error) \u2014 halt cycle (A), skip silently (B),
  per-source isolation (C), or treat as validation error (D)? \u2192
  **Per-source isolation with retry-once.** The modular architecture
  exists specifically to insulate the main research loop from complex,
  failure-prone flows; a failing module MUST NOT bring down the cycle.
  Policy: (1) retry the failing call ONCE with the same input; (2) if
  the retry also fails, log the error + traceback, salvage any partial
  output the module produced (write to cache with `verdict: "error"`
  and `partial: true`), mark the source as failed for this cycle, and
  continue with other sources; (3) surface the failure in the cycle's
  run-report so the vault author sees it without having to dig
  through logs. Applies uniformly to extractor crashes, validator
  Python exceptions, and manifest parsing errors at module-discovery
  time.

### Session 2026-05-26 \u2014 source enumeration + module discovery

- Q: Where does the framework get the per-module list of `source_id`
  values for `get_source_version()` / `extract()`? \u2192 A:
  **Per-module `<vault>/modules/<name>/sources.yaml`.** Each installed
  module owns its source-instance list beside `manifest.yaml`. The
  source-extraction stage iterates entries in every discovered module's
  `sources.yaml` (missing file \u2192 zero sources for that module, WARN
  logged once per pipeline start). Vault-level `scripts/sources.yaml`
  (feeds-vault prior art) is a **one-time migration input** only \u2014 a
  porting script splits it into per-module files when landing the first
  020-shaped module (youtube first on the revival sprint). Rejected:
  single vault-level `sources.yaml` (merge conflicts, breaks module
  isolation); hybrid dual-file (two sources of truth, precedence fights).
- Q: How does per-module `sources.yaml` relate to
  `research.spec.md::data_sources`? \u2192 A: **Split responsibilities.**
  `sources.yaml` is the **authoritative enumeration for extraction**
  (what to walk, what `source_id` to pass). `data_sources` remains the
  **scout/spec contract** (coverage framing, schema-gen context per
  FR-014) and MAY overlap during migration, but the framework MUST NOT
  derive the extraction loop from `data_sources` alone in 0.3.0. Authors
  SHOULD keep the two in sync manually until a future spec adds
  cross-validation; no automatic sync in 020.
- Q: Module discovery \u2014 filesystem walk vs `settings.yaml::modules:`
  list? \u2192 A: **Filesystem walk is authoritative for runtime.**
  FR-010 stands: scan `<vault>/modules/*/manifest.yaml` every pipeline
  start. `settings.yaml::modules:` controls **only** (1) which modules
  `install.sh` / `./vault update` copy from the framework bundle, and
  (2) trigger-registry precedence order (first-match wins). A module
  folder manually dropped into `<vault>/modules/` is active without a
  `settings.yaml` edit (SC-007). Rejected: settings-only discovery
  (blocks drop-in modules).
- Q: Trigger-registry caching \u2014 persist under `_pipeline/` or
  rescan every start? \u2192 A: **Rescan every pipeline start; no
  persisted registry cache.** Build `TriggerRegistry` in memory from the
  filesystem walk (~ms at vault scale). Rejected: `_pipeline/` cache
  (stale-after-drop-in, invalidation rules add complexity for no win at
  5\u201350 sources).
- Q: `./vault update` vs user-edited module files (`sources.yaml`,
  in-loco policy from spec 023)? \u2192 A: **User-owned module files are
  never overwritten by the migrator.** On `./vault update`, framework
  code files under `<vault>/modules/<name>/` refresh from the bundle
  (existing FR-012 behaviour) BUT `<vault>/modules/<name>/sources.yaml`
  MUST be preserved if present (create from bundle template only when
  absent). This is orthogonal to spec 023's `_pipeline/in-loco-modules.json`
  lifecycle (that tracks vault-local scripts under `scripts/`, not
  020 module trees). `keep_overrides` in `settings.yaml` is NOT required
  for `sources.yaml` \u2014 preservation is unconditional. Module
  manifests MAY declare additional `user_owned:` relative paths (e.g.
  `custom_prompt.md`) that follow the same preserve-if-present rule.

### Background \u2014 the audit that motivated this spec

The user's reference-vault-0.2.30 trial-run (6 cycles, 3h 28m, ran to
completion) produced ~68 notes against a coverage target of ~150. The
post-run audit (`run-report.md`, `cycle-NNN-research.json`,
`cycle-NNN-scout.json`) found:

- **Scout under-delivered topics**: 7\u201312 new topics per cycle vs a
  quota of 49 (16% of target). Scout token spend was ~120k/cycle but
  ~80% of those tokens went into re-walking the same two repositories
  across all 6 cycles. The agent was reading the same Java files and
  proposing variants of the same five topics.
- **Coverage skew**: every category that derived from code (services,
  flows, decisions, kafka) filled up; every category that was
  external-only (concepts, learning-modules, java-jvm,
  spring-features) stayed empty. The scout never went looking for
  topics from the spec's coverage gaps because it had no surplus
  attention left after the code-walk.
- **Cost per useful topic**: ~17k tokens. With cached source signals
  the same yield should cost ~3k tokens.

The user's framing: "I see repositories as a way for research to
branch out but I don't see a reason for the agents to return to the
repository multiple times unless they find something like 'ok, it
seems that often testcontainers are used to test this type of
microservice architectures but I don't know what they're using, let
me check it out real quickly'."

This spec encodes that framing as the canonical pipeline behaviour \u2014
not just for code, but for any source type a module can be written for.

### What this spec is NOT

- It is **NOT** the 0.2.31 verifier/wikilink fixes \u2014 those shipped
  separately as `pipeline/verifier.py` (tolerant JSON extraction +
  prompt wrapper) and `pipeline/wikilinks.py` (auto-normalizer).
- It is **NOT** the spec-driven topic discovery for coverage gaps \u2014
  that's a sibling concern (captured in `specs/021-spec-driven-coverage/`
  so 020 can ship without it). Together they target 0.3.0.
- It is **NOT** the multi-agent consensus mechanism for note-writer
  (different feature; this spec only uses consensus for verdicts on
  source-extraction).
- It is **NOT** a port of the user's prior feeds-vault scripts \u2014 those
  ports are deferred to 0.4.0+. This spec is the architectural
  foundation; the ports drop in without further spec work.

### Session 2026-06-08 — `code` vs `github` module boundary (post-ship amendment)

A first-class `github` module (PRs / issues / releases via the `gh` CLI, governed by
spec 060) lands alongside the existing `code` module. Because both touch "code hosting",
the boundary is made **deliberate and explicit** so the first-match trigger registry never
double-claims a source:

- **`code` = local working copies.** Its extractor only ever runs against a checked-out
  repository on disk (`git rev-parse HEAD` for the source version; local file walks for
  signals). Its triggers are therefore **filesystem `path_pattern`s only**. The original
  manifest also carried a `url_pattern: (github|gitlab)\.com/` trigger, but that was
  **misleading** — the extractor has no remote-fetch path, so a bare `github.com/...` URL
  matched `code` and then could not actually be extracted. That `url_pattern` is **removed**
  from `code`'s manifest as part of this batch.
- **`github` = remote GitHub surfaces.** Its extractor shells `gh` (session auth) / `gh api`
  against `github.com/<org>/<repo>`. Its triggers are **`url_pattern`s on**
  `github\.com/.+/(pull|issues|releases)` (and the repo root for release/activity polling).
- **No overlap by construction.** `code` claims paths, `github` claims URLs; a local checkout
  and its remote are distinct sources that can both be enumerated without colliding in the
  first-match registry. A regression test pins that `code` no longer matches remote URLs.

This is a behaviour-narrowing manifest change to a SHIPPED module (no extractor logic
changes for `code`), recorded here rather than in a new spec per 060's "amend 020 directly
for the code-boundary" governance.

## User Scenarios & Testing *(mandatory)*

### User Story 1 \u2014 Cached source-walk eliminates re-extraction waste (Priority: P1)

A researcher runs `research-framework generate` against a vault whose
spec lists three GitHub repositories. The first cycle walks the
repos via the code module, extracts a structured signal payload (facts
+ freeform observations), and writes it to a cache keyed by
`(module=code, source_id=repo_path, source_version=commit_sha)`.
Subsequent cycles re-read the cache without touching the repos at all.
When the user pushes new commits to one of the repos, only that repo
is re-walked on the next cycle; the other two serve from cache.

The same flow applies to any future module: when a YouTube module
ships, a YouTube video URL in the spec gets cached by
`(module=youtube, source_id=video_url, source_version=transcript_hash)`,
and serves from cache on subsequent cycles unless the transcript
hash changes.

**Why this priority**: This is the load-bearing change. Without it,
the rest of the spec is decoration \u2014 the scout's coverage problem
is downstream of the scout's token starvation, which is caused by
the redundant source-walk. The user explicitly named this as the
single biggest perceived inefficiency.

**Independent Test**: Build a fake vault with two repos. Run the
extractor; observe a cache file is written. Run again; observe the
extractor reports "cache hit, skipping" and produces no subprocess
calls to the source-walker. Add a commit to one repo; observe only
that repo is re-extracted on the next run.

**Acceptance Scenarios**:

1. **Given** a vault with 3 repos and an empty source cache,
   **When** the cycle 0 source-extraction stage runs, **Then** all 3
   repos are walked by the code module, 3 signal payloads are written
   to `_pipeline/sources/code/signals/<source-stem>-<version>.json`,
   and the watermark file lists the current version for each source.
2. **Given** a vault where all 3 repos' watermarks match HEAD,
   **When** cycle 1's source-extraction stage runs, **Then** the
   stage logs "3/3 cache hits, skipping extraction" and produces
   zero new subprocess calls.
3. **Given** a vault where repo A's HEAD has advanced one commit,
   **When** cycle 2's source-extraction stage runs, **Then** only
   repo A is re-walked, its signal is rewritten, its watermark is
   updated, and repos B and C continue to serve from cache.

---

### User Story 2 \u2014 Scout reads cached signals instead of walking sources (Priority: P1)

The scout stage no longer invokes `git`, `gh`, or any direct source
read. It receives the latest signals as part of its input context
(passed via the prompt or as a referenced sidecar file). Its job
becomes "given these signals + the vault spec's coverage gaps,
propose this cycle's topics." Topic yield should rise because the
scout's attention budget is no longer spent on source-walking.

**Why this priority**: The cache (US1) is necessary but not
sufficient. Without rewriting the scout to actually consume the
cache, the same re-walking happens in a different file. The cache
is only useful if the consumer is fixed.

**Independent Test**: Run the scout with a stub source-extraction
process that emits a known signal payload. Inspect the scout's
prompt log: it MUST contain the signal payload contents and MUST
NOT contain any `git`-like operations. Inspect the scout's output:
topic count should rise from the 0.2.30 baseline of ~10/cycle to
\u22652\u00d7 baseline on the same spec.

**Acceptance Scenarios**:

1. **Given** a pre-extracted signal cache, **When** the scout
   stage runs, **Then** the scout's prompt input includes the
   signal payloads and the scout makes zero direct repo accesses.
2. **Given** the same spec the user ran on 0.2.30, **When** US1
   and US2 are both shipped, **Then** the per-cycle new-topic
   count is at least 2\u00d7 the 0.2.30 baseline (\u226520 topics/cycle
   vs the observed 7\u201312).

---

### User Story 3 \u2014 Modules are dynamically discovered and routed by trigger (Priority: P1)

The framework scans `<vault>/modules/*/manifest.yaml` on every
pipeline start (no persisted registry cache \u2014 see Session
2026-05-26), builds an in-memory trigger registry, and runs
source-extraction against each module's
`<vault>/modules/<name>/sources.yaml` enumeration. For each source
instance listed there:

1. Resolve `source_id` per FR-013b and invoke that module's extractor.
2. If a `data_sources` entry exists with no matching module trigger
   AND no owning `sources.yaml` section \u2192 fall back to generic
   handling (web fetch, file read, etc.) with cache key
   `(module="generic", ...)`. Existing pipeline behaviour for
   non-module sources is unchanged.
3. If a user drops a new module folder into `<vault>/modules/`
   between cycles \u2014 it's picked up automatically on the next
   pipeline start. No reinstall, no config change beyond placing
   the folder (settings.yaml edit optional for install-time copy only).

**Why this priority**: This IS the source-module architecture. Without
it, 020 is just code-bridge with extra ceremony. The trigger-routing
and runtime discovery are what enable the deferred YouTube / Reddit /
O'Reilly modules to drop in later without spec changes.

**Independent Test**: Two modules installed in the vault \u2014 a real
`code` module (with `<vault>/modules/code/sources.yaml` listing one
git repo entry) and a stub `web` module (with
`<vault>/modules/web/sources.yaml` listing one `example.com` URL
entry, plus trigger pattern `example\\.com` in its manifest). The
vault's `research.spec.md::data_sources` additionally references a
`random.org` URL that no module owns. Verify the code module
handles the repo (per its `sources.yaml`), the web module handles
the example.com URL (per its `sources.yaml`), and the `random.org`
URL falls back to generic handling (via the trigger-mismatch +
no-owning-`sources.yaml`-entry path of US3 step 2).

**Acceptance Scenarios**:

1. **Given** `settings.yaml::modules: [code, youtube]` and
   `install.sh` has run, **When** the pipeline starts, **Then**
   `<vault>/modules/code/` and `<vault>/modules/youtube/` exist
   and the trigger registry contains both modules' triggers.
2. **Given** a youtube module with `sources.yaml` listing two channels,
   **When** the source-extraction stage runs, **Then** the youtube
   extractor is invoked twice (once per enumerated `source_id`).
3. **Given** a `data_sources` entry with no owning module
   `sources.yaml` entry and no trigger match, **When** the
   source-extraction stage runs, **Then** the source is handled by
   the existing generic path (logged as "module: generic"); the cache
   key uses `(module="generic", source_id, source_version)`.
4. **Given** the user manually copies a new module folder into
   `<vault>/modules/` after install, **When** the next pipeline
   run starts, **Then** that module is auto-discovered, registered,
   and immediately available for trigger matching. No reinstall.

---

### User Story 4 \u2014 Per-module schema generated from the vault spec (Priority: P1)

At install time (and on spec-hash change), a small agent reads the
vault's `research.spec.md`, the `data_sources` list, and each enabled
module's few-shot example payloads, and generates a per-`(vault, module)`
JSON Schema. The schema lives at
`<vault>/_pipeline/sources/<module>/facts-schema.json`. Each module's
extractor consumes its own schema and produces payloads conforming to
it. If schema-gen fails or produces invalid JSON Schema, the framework
falls back to a 3-bucket minimal default (`technologies`, `patterns`,
`notable`) and logs loudly so the vault author can investigate.

**Why this priority**: The framework's domain-agnosticism (Constitution
Principle 1.3.2 update) lives or dies by this. A web-microservices
vault and an embedded-firmware vault need different facts schemas;
hardcoding any specific list of buckets in framework code is a
constitutional violation. Schema-gen is the mechanism that keeps the
framework honest.

**Independent Test**: Run install with two distinct specs (one web
microservices, one ESP32 firmware) using the same code module.
Verify the two schemas are visibly different (web has `data_stores`,
`api_protocols`; firmware has `peripherals`, `power_modes`,
`interrupt_handlers`). Run again with a deliberately broken
schema-gen agent; verify fallback to 3-bucket default and a loud
warning in the install log.

**Acceptance Scenarios**:

1. **Given** a vault spec describing a Java microservices vault,
   **When** install runs schema-gen for the code module, **Then**
   the produced schema contains buckets appropriate to that domain
   (e.g. `technologies`, `data_stores`, `api_protocols`).
2. **Given** a vault spec describing an ESP32 firmware vault,
   **When** install runs schema-gen for the code module, **Then**
   the produced schema contains buckets appropriate to firmware
   (e.g. `peripherals`, `interrupt_handlers`, `flash_layout`) \u2014
   NOT the web-microservices buckets.
3. **Given** schema-gen returns invalid JSON Schema, **When**
   install proceeds, **Then** the framework falls back to a
   3-bucket minimal default and logs a WARN naming the failed
   module + the path to inspect for debugging.

---

### User Story 5 \u2014 Per-vault validators shape the signal payload (Priority: P2)

A vault author can drop a `code-bridge.validators.yaml` (per-module
naming: `<module>.validators.yaml`) next to their `research.spec.md`
to declare which signal-payload fields are required and what shape
they must have. The validator is read by the module's extractor at
the end of each extraction and the extractor refuses to write a cache
entry that fails the validator. For cross-field or domain-specific
rules, the author can add `<module>.validators.py` with a single
`validate(payload) -> list[str]` function. YAML covers 90% of cases;
Python is the escape hatch.

**Why this priority**: Without per-vault validators, every payload
looks identical and the per-vault shaping the user wants becomes
prompt-engineering instead of structural. P2 because the P1 stories
work without it \u2014 you just get less-curated payloads.

**Independent Test**: Author a `code.validators.yaml` requiring
`facts.technologies` to be a non-empty list. Run the extractor against
a synthetic repo where the agent would naturally produce an empty
list. The extractor MUST reject the cache write with a clear error
pointing at the validator file and line.

**Acceptance Scenarios**:

1. **Given** a vault with `code.validators.yaml` requiring
   `facts.technologies` non-empty, **When** the extractor produces
   an empty list, **Then** the extraction fails with a clear error
   citing the validator and the cache file is NOT written.
2. **Given** a vault with `code.validators.py` defining
   `validate(payload)`, **When** the extractor produces a payload
   that fails the Python rule, **Then** the same rejection happens
   with the Python error message surfaced.
3. **Given** a vault with no validators, **When** the extractor
   runs, **Then** the framework's default minimal validator is
   used (must be valid JSON, must conform to the per-module
   generated schema, nothing else).

---

### User Story 6 \u2014 Value-tiered consensus per invocation (Priority: P2)

The caller (orchestrator) declares a `value_tier` per source-extraction
invocation: `routine | important | critical`. The framework maps tier
\u2192 odd N (defaults 1 / 3 / 5). When N\u22653, N extractors are spawned in
parallel; majority vote determines the verdict; findings are unioned
across all extractors (additive). N=1 means no consensus, no extra
calls. Default for every v1 invocation is `routine` until heuristics
emerge for when to escalate.

**Why this priority**: Closes the loop on agent agency for "this source
has nothing new" verdicts. Without consensus, a single agent's
"exhausted" verdict can short-circuit valuable extraction. P2 because
US1 ships with N=1 (no consensus) and is still load-bearing for the
token-spend win.

**Independent Test**: Configure `consensus.tiers.critical.n: 3`. Spawn
three stub extractors returning verdict="exhausted" + the same notable
findings. Verify the watermark advances and the next cycle is
short-circuited. Re-run with one extractor returning "exhausted" and
two returning new findings. Verify the verdict resolves to "ok" (the
majority) and the findings are unioned across all three.

**Acceptance Scenarios**:

1. **Given** N=3 extractors spawned for a source, **When** all three
   return `verdict: "exhausted"` with equivalent finding sets,
   **Then** the source's watermark is advanced + marked exhausted
   for the current version, and subsequent cycles skip re-extraction
   until version drifts.
2. **Given** N=3 extractors disagree (2 say "ok" + return findings,
   1 says "exhausted"), **Then** the final verdict is "ok" (majority
   rule), findings from ALL THREE are unioned and written, and a
   `ConsensusResult` audit record captures the dissent.
3. **Given** N=1 (`routine` tier, the default), **When** the
   single extractor returns "exhausted", **Then** the watermark
   advances directly. A WARN is logged.
4. **Given** `settings.yaml` declares an even N for any tier,
   **When** the framework loads the config, **Then** load fails
   with a clear error: "consensus N must be odd; got N=2 for tier
   'important'".

---

### User Story 7 \u2014 Per-call agent logging (cross-cutting, Priority: P2)

Every agent invocation (scout, note-writer, verifier, schema-gen,
source-extraction, ALL of them) writes a record to
`_pipeline/cycles/cycle-NNN/agent-calls/<timestamp>-<stage>-<call-id>.json`.
Shape: `{stage, call_id, timestamp, model, prompt, response, latency_ms,
tokens_in, tokens_out, cost_usd, error?}`. Hooks into the existing
`agent_call.py` dispatch surface so it's centralized \u2014 no stage opts
in or out.

**Why this priority**: Observability and debuggability. Without it,
post-mortem analysis of "why did cycle 3 produce that note" requires
re-running the cycle. With it, every prompt + response is on disk for
the user to inspect. P2 because it doesn't block the P1 features
shipping; it can land as its own commit during the 0.3.0 work.

**Independent Test**: Run a single cycle with two scout invocations
and three note-writer invocations. Verify
`_pipeline/cycles/cycle-001/agent-calls/` contains 5 files with the
expected shape, prompts populated, responses populated, costs
captured.

**Acceptance Scenarios**:

1. **Given** any agent invocation completes (success or failure),
   **When** the cycle ends, **Then** the corresponding JSON record
   exists under `_pipeline/cycles/cycle-NNN/agent-calls/` with the
   full prompt + response + cost data.
2. **Given** an agent invocation fails (timeout, parse error, etc.),
   **When** the cycle continues, **Then** the failure is captured
   in the record's `error` field (the cycle does NOT halt).
3. **Given** the user inspects `agent-calls/` for a past cycle,
   **When** they grep for a specific phrase, **Then** they find it
   in both the prompt and response payloads (it is NOT elided or
   truncated for size).

---

### Edge Cases

- **Source path is invalid / module's `extract` raises**: per the
  user's explicit decision, this is the module's responsibility to
  handle internally. The framework only checks "did the module produce
  output?" via a status-file heartbeat. No output \u2192 logged as a
  botched flow, the source's signal becomes empty for that cycle, the
  cycle proceeds. Framework does NOT retry or carry per-source failure
  counters.
- **User cites a source whose trigger matches no installed module**:
  fall back to generic web/file handling silently. The framework does
  NOT scan the spec for "you should install module X" suggestions \u2014
  the user is responsible for choosing modules. (Explicit user
  decision: "I'd just skip the question altogether.")
- **Cache disk corruption / unreadable JSON**: treated as a cache
  miss \u2014 re-extract. Log a WARN.
- **Schema drift across framework versions**: cache entries embed a
  `bridge_version` field. On version mismatch, the cache is
  invalidated and the source is re-walked, with a one-line log entry
  ("bridge version drift 0.3.0 \u2192 0.3.1 \u2014 re-extracting source X").
- **Validator file syntax error**: the extractor fails closed with a
  clear error pointing at the validator file. NO partial cache write
  \u2014 better to halt the cycle than to silently disable validation.
- **Mid-cycle source-version change** (e.g. user pushes during a
  cycle): the cache key uses the version observed at cycle start.
  Mid-cycle changes are picked up on the NEXT cycle, not the current
  one. Predictability beats freshness here.
- **Source with no version** (e.g. brand-new git repo, empty
  YouTube playlist): module returns an empty payload with
  `verdict: "empty"` and a sentinel version. Treated like a successful
  empty extraction (cache hit on subsequent runs).
- **Two modules' triggers both match a source**: first-match wins,
  using `settings.yaml::modules:` array order (deterministic). User
  reorders the array if they want a different precedence.
- **User removes a module from settings + deletes folder post-install**:
  sources fall back to generic handling; old cached signals GC'd by
  the 30-day window. No special handling needed.
- **Manifest is malformed**: skip the module at discovery time, log
  WARN, framework continues with the remaining modules.
- **Schema-gen produces invalid JSON Schema**: fall back to the
  3-bucket minimal default (`technologies`, `patterns`, `notable`)
  for that `(vault, module)` pair. Log loudly. Vault author can edit
  `<vault>/_pipeline/sources/<module>/facts-schema.json` manually to
  override.

## Requirements *(mandatory)*

### Functional Requirements

**Bridge core (FR-001..FR-007)**

- **FR-001**: The framework MUST expose a new pipeline stage
  "source-extraction" that runs BEFORE the scout stage in every cycle.
- **FR-002**: The source-extraction stage MUST be implemented as a
  subprocess invocation (`scripts/source_bridge.py`), matching the
  existing per-stage invocation pattern.
- **FR-003**: The stage MUST maintain a per-source watermark file at
  `_pipeline/sources/<module>/watermarks.json`. Each entry stores
  `{source_id, source_version, bridge_version, extracted_at, verdict}`.
- **FR-004**: When a source's current version matches its watermark
  AND the bridge version matches, the stage MUST skip the extraction
  and log "cache hit" without invoking any agent.
- **FR-005**: The stage MUST write per-source signal payloads to
  `_pipeline/sources/<module>/signals/<source-stem>-<version>.json`.
  Signals older than `signal_retention_days` (default 30) MUST be
  garbage-collected at the end of each successful write.
- **FR-006**: The signal payload MUST conform to the per-`(vault, module)`
  JSON Schema generated by schema-gen (FR-014). The envelope MUST
  always include: `module`, `source_id`, `source_version`,
  `extracted_at`, `verdict`, `bridge_version`.
- **FR-007**: All source-bridge artifacts MUST live under
  `_pipeline/sources/`. This directory MUST be safe to delete to force
  a full re-extraction (audit trail under `_pipeline/cycles/` is
  separate and unaffected).

**Scout integration (FR-008..FR-009)**

- **FR-008**: The scout stage MUST read the latest signal payloads
  from the cache and include them in its prompt input. The scout
  stage MUST NOT make any direct source accesses (git clone, gh API,
  HTTP fetches, file reads under a source path).
- **FR-009**: The scout stage MUST route by `module` field on each
  payload \u2014 it MAY treat different modules' payloads differently when
  proposing topics, but the framework guarantees all payloads share
  the envelope shape.

**Module architecture (FR-010..FR-013)**

- **FR-010**: The framework MUST scan `<vault>/modules/*/manifest.yaml`
  on every pipeline start and build an in-memory trigger registry.
  Discovery is **filesystem-authoritative**: every manifest found on
  disk is registered. `settings.yaml::modules:` affects install-time
  copy and trigger precedence order only \u2014 NOT which modules exist at
  runtime. The registry MUST NOT be persisted under `_pipeline/`; it
  is rebuilt from the walk on each pipeline start.

  **Precedence order**: The framework MUST evaluate module triggers in
  this deterministic order, first-match wins:

  1. **Listed modules first, in `settings.yaml::modules:` order.**
     Modules whose name appears in that list are evaluated in the
     listed order. Duplicate names are an error (caught by 023 P0
     spec-lint).
  2. **Unlisted modules second, in lexicographic (ASCII) name order.**
     Any manifest found under `<vault>/modules/*/manifest.yaml` whose
     name is NOT in `settings.yaml::modules:` is appended after the
     listed block, sorted by module `name`. A WARN is logged once per
     pipeline start naming these modules ("module 'X' discovered on
     disk but not listed in settings.yaml::modules: \u2014 considered
     last") so the operator can decide whether to promote them.

  Rationale: the listed order is the user's explicit priority signal;
  unlisted modules SHOULD be inert (zero `sources.yaml` instances) but
  if they ship trigger patterns that match `data_sources` URLs they
  still need a defined ordering for reproducibility.
- **FR-011**: Each module's manifest MUST declare: `name`, `version`,
  `description`, `triggers` (list of pattern matchers), `entry_point`
  (Python file relative to the module folder), `default_value_tier`
  (`routine | important | critical`), and `schema_examples` (path to
  few-shot examples for schema-gen). SHOULD declare `source_id_from`
  (map of `sources.yaml` top-level keys to identity field names per
  FR-013b). MAY declare `user_owned` (relative paths preserved on
  update per FR-025).
- **FR-012**: `settings.yaml` MUST support an optional `modules:` list.
  When present, `install.sh` MUST copy each named module from the
  framework bundle (`src/research_framework/modules/<name>/`) to
  `<vault>/modules/<name>/`. Missing/empty list \u2192 no modules copied
  (pipeline runs with generic handling only). On `./vault update`,
  the migrator (013) MUST re-copy each module listed in
  `settings.yaml::modules:` from the new framework bundle so that
  installed modules track framework `bridge_version` drift. Modules
  NOT listed in `settings.yaml::modules:` MUST NOT be auto-copied
  by the migrator even when present in the new bundle \u2014 the user's
  explicit module-selection choice is respected at every update.
  User-owned files under copied modules MUST be preserved per FR-025.
- **FR-013**: Each module MUST expose a stable Python interface via
  `entry_point`: `get_source_version(source_id: str) -> str` and
  `extract(source_id: str, version: str, schema: dict, value_tier: str) -> dict`.
  The framework calls these via subprocess invocation; the module's
  internal implementation is opaque to the framework.
- **FR-013a (per-module source enumeration)**: For each module
  discovered per FR-010, the source-extraction stage MUST enumerate
  source instances from `<vault>/modules/<name>/sources.yaml`. The
  file format is module-specific YAML: a top-level mapping whose keys
  name source kinds (e.g. `youtube_channels`, `github_repos`,
  `subreddits`) and whose values are lists of instance records. Each
  record MUST include enough identity for the module to derive a stable
  `source_id` per FR-013b. If `sources.yaml` is absent, the module
  contributes zero sources (WARN logged once per pipeline start naming
  the module).

  **Boundary with spec 023's `./vault refresh-sources` verb**: the two
  are runtime-decoupled. `./vault refresh-sources` (023 FR-013, Phase 1
  revival minimum subset) iterates the legacy vault-local
  `<vault>/scripts/collect_*.py` directory + the `reddit_rss.py`
  allowlist — NOT this per-module `sources.yaml`. The 020
  `sources_loader.py` (consumer of this FR-013a file) reads
  `<vault>/modules/*/sources.yaml` only. The two paths coexist during
  the ADR-0009 transition: legacy collectors continue to feed vaults
  whose modules have not yet been ported to 020 extractors; ported
  modules use `sources.yaml`. Per-module collector deletion is a
  manual post-port step gated on 023 FR-015 (`scripts/` survives
  update) — neither spec 020 nor spec 023 automates it.
- **FR-013b (`source_id` derivation)**: The framework MUST derive
  `source_id` from each `sources.yaml` record using module-declared
  rules in `manifest.yaml` under a `source_id_from:` mapping (field
  name per source-kind key, defaulting to `url` when present else
  `name`).   Examples: youtube \u2192 channel `url`; code/github \u2192 `url`
  or absolute `path`; reddit \u2192 `name` (subreddit slug). The derived
  `source_id` MUST be stable across runs for unchanged records.

  **Resolution algorithm** (deterministic, evaluated per `sources.yaml`
  record under top-level key `K`):

  1. If `manifest.yaml::source_id_from[K]` is declared \u2192 use that field
     name. If the named field is missing or empty on the record, FAIL
     fast with a clear error (`"module <name>: record under <K>[i]
     missing required source_id field '<field>'"`) and abort the
     extraction stage. No silent fallback.
  2. Otherwise (no `source_id_from[K]` declared), try fields in order:
     `url` then `name`. The first present-and-non-empty wins.
  3. If steps 1\u20132 yield no value \u2014 i.e. neither `url` nor `name` is
     present on the record AND no `source_id_from[K]` declaration
     resolved \u2014 FAIL fast with a clear error (`"module <name>: record
     under <K>[i] has no derivable source_id; declare source_id_from
     in manifest.yaml or add a url/name field"`). The extraction stage
     MUST NOT continue with the record. Allowing it would produce
     either non-deterministic cache keys or silent extraction skips.

  Trigger patterns (FR-011) are used for generic-path routing and
  debugging, not for discovering instances already listed in a
  module's `sources.yaml`.
- **FR-013c (`data_sources` vs `sources.yaml`)**: `research.spec.md::data_sources`
  MUST NOT be the sole driver of the source-extraction loop in 0.3.0.
  It remains authoritative for scout coverage framing and schema-gen
  input (FR-014). Vault authors MAY duplicate entries across both files
  during migration; automatic cross-sync is out of scope for 020.

**Schema generation (FR-014..FR-016)**

- **FR-014**: For each `(vault, module)` pair, a schema-gen agent
  call MUST be issued at install time AND on spec-hash change to
  produce `<vault>/_pipeline/sources/<module>/facts-schema.json`. The
  agent receives the vault's `research.spec.md`, the `data_sources`
  list, and the module's `schema_examples` few-shot file. The
  schema-gen executor MUST use the tier resolved from
  `settings.yaml::tiers:` (default `tier: basic`); see FR-014a.

- **FR-014a (tier-based model selection)**: `settings.yaml` MUST
  define a top-level `tiers:` block mapping declarative complexity
  names to vendor model identifiers, at minimum: `basic`, `normal`,
  `flagship`. Stages introduced by this spec (`schema_gen`,
  `source_extraction`) MUST accept a `tier:` field on the executor
  and resolve it to the model identifier via the `tiers:` block at
  config-load time. Specifying both `tier:` and `model:` on the same
  executor MUST cause a config-load error. Module manifests MAY
  declare a `default_tier:` field; the framework MUST honor it
  unless the user overrides on the executor. Existing stages
  (`scout`, `note_writer`, `verifier`, etc.) MAY continue to use the
  legacy `model:` field; migration to tiers is out of scope for 020.
- **FR-015**: If schema-gen returns invalid JSON Schema, the
  framework MUST fall back to a 3-bucket minimal default
  (`technologies`, `patterns`, `notable`) for that pair and log a
  WARN naming the module and the path of the failed schema file.
- **FR-016**: Vault authors MAY manually edit
  `_pipeline/sources/<module>/facts-schema.json` to override the
  generated schema. The framework MUST NOT regenerate over a manually-
  edited schema (detected via a `manually_edited: true` field).

- **FR-016a (drift detection on manually-edited schemas)**: When
  `manually_edited: true` AND the spec hash recorded at
  `_pipeline/sources/<module>/.schema-gen-hash` does NOT match the
  current `research.spec.md` hash, the framework MUST:
  1. Run schema-gen anyway, writing output to the sidecar
     `_pipeline/sources/<module>/facts-schema.regenerated.json`
     (does NOT overwrite the manual schema).
  2. Compute a structural diff against the manual schema and write
     it to `_pipeline/sources/<module>/facts-schema.drift.md`.
  3. **FAIL the next cycle with a clear error** citing the drift
     file path, the diff summary, and the three resolution paths
     (merge + bump watermark, remove `manually_edited`, or
     `--force-stale-schema`).

  The framework MUST NOT proceed with cycles in a drift state unless
  the user explicitly resolves OR passes `--force-stale-schema` (or
  equivalent) on the cycle-running CLI. This is a fail-closed
  contract: the user opted into responsibility when manually editing;
  the framework refuses to silently honour a stale contract.

**Validators (FR-017..FR-018)**

- **FR-017**: A vault MAY provide `<module>.validators.yaml` next to
  `research.spec.md`. When present, the extractor MUST evaluate it
  against every payload before writing the cache, and fail closed on
  validation errors. The default minimal validator (when no file is
  present) MUST validate payloads against the per-module schema only.
- **FR-018**: A vault MAY provide `<module>.validators.py` defining
  `validate(payload) -> list[str]`. When present, the extractor MUST
  execute it in addition to the YAML rules. Returning a non-empty
  list means failure. If `validate()` raises an unhandled exception
  (rather than returning errors via the contract), the framework MUST
  follow the module-isolation policy in FR-023a.

**Consensus (FR-019..FR-021)**

- **FR-019**: The source-extraction stage MUST accept a `value_tier`
  parameter per invocation (`routine | important | critical`),
  defaulting to `routine`.
- **FR-020**: The framework MUST map tier \u2192 odd N via
  `settings.yaml::stages.source_extraction.consensus.tiers`
  (defaults: routine=1, important=3, critical=5). At config-load
  time, the framework MUST validate that every configured N is odd
  and reject the config with a clear error otherwise.
- **FR-021**: When N\u22653, the framework MUST spawn N parallel extractor
  invocations per source, take majority vote on the verdict, and
  UNION findings across all extractors. A `ConsensusResult` audit
  record MUST be written to `_pipeline/sources/<module>/consensus/<source>-cycle-NNN.json`.

**Failure handling (FR-022..FR-023)**

- **FR-022**: The source-extraction stage MUST be idempotent: running
  it twice in a row on an unchanged vault MUST produce zero filesystem
  changes (other than timestamp metadata).
- **FR-023**: The source-extraction stage MUST be tolerant of
  per-source failures \u2014 a single module crash or timeout MUST NOT
  halt the cycle. The failing source's signal becomes empty for that
  cycle and a WARN is logged. Per explicit user decision: failure
  handling is the module's responsibility internally; the framework
  only checks "did the module produce output?" and moves on.

- **FR-023a (module-isolation policy on unhandled exceptions)**: When
  any module-subsystem call (extractor invocation, validator YAML
  evaluation, validator Python execution, manifest parsing during
  discovery) raises an unhandled exception, the framework MUST:
  1. **Retry the call ONCE** with the same input.
  2. If the retry also fails, log the error with full traceback to
     `_pipeline/sources/<module>/bridge.log` AND record it via the
     per-call agent-log surface (FR-024) for cross-cycle auditability.
  3. **Salvage any partial output** the module produced before the
     exception \u2014 write to the cache with `verdict: "error"` and
     `partial: true` so downstream consumers (scout) MAY use the
     partial data with a clear indicator that it's incomplete.
  4. Mark the source as failed for this cycle (signal is the partial
     payload OR empty if no partial output was produced).
  5. Continue the cycle with other sources.
  6. **Surface the failure in the cycle's run-report** (not only in
     the log) so the vault author sees it without having to dig
     through bridge.log.

  Rationale: the modular architecture exists specifically to isolate
  complex, failure-prone flows from the main research loop. A
  failing module MUST NOT bring down the cycle. This policy applies
  uniformly across the module subsystem; no flag toggles or
  exceptions \u2014 the cycle ALWAYS continues on per-source failure
  (with `--force-stale-schema` as the separate escape hatch for
  Q4-style spec-drift failures, which are NOT module exceptions).

**Cross-cutting observability (FR-024)**

- **FR-024**: All agent invocations across the framework (scout,
  note-writer, verifier, schema-gen, source-extraction, every stage)
  MUST write per-call records to
  `_pipeline/cycles/cycle-NNN/agent-calls/<timestamp>-<stage>-<call-id>.json`
  with full prompt + response + cost + latency captured. This
  capture MUST happen at the single `agent_call.py` dispatch surface
  (no stage opts in or out). This requirement lands as its own commit
  during the 0.3.0 work; it's grouped here because it shares the
  observability theme.

**Module registry (FR-025)**

- **FR-025 (user-owned module files on update)**: When `./vault update`
  re-copies a module from the framework bundle per FR-012, it MUST NOT
  overwrite `<vault>/modules/<name>/sources.yaml` if the file already
  exists. If absent, the migrator MAY seed a template from the bundle.
  Module manifests MAY declare a `user_owned:` list of additional
  relative paths preserved by the same rule. This is independent of
  spec 023's `_pipeline/in-loco-modules.json` deprecate-and-prune
  lifecycle (which governs vault-local `scripts/`, not `<vault>/modules/`).

### Key Entities *(include if feature involves data)*

- **SignalPayload**: per-source, per-version payload. Shared envelope
  fields: `module`, `source_id`, `source_version`, `extracted_at`,
  `verdict`, `bridge_version`. Plus `facts` (dict, shape per-module
  schema) and `notable` (list of freeform observations with evidence
  references). Stored at
  `_pipeline/sources/<module>/signals/<source-stem>-<version>.json`.
- **Watermark**: per-source entry tracking what was last extracted.
  Fields: `source_id`, `source_version`, `bridge_version`,
  `extracted_at`, `verdict`. Lives in
  `_pipeline/sources/<module>/watermarks.json`.
- **ModuleManifest**: per-module declaration of identity + triggers
  + interface. Fields: `name`, `version`, `description`, `triggers`
  (list), `entry_point`, `default_value_tier`, `schema_examples`,
  optional `source_id_from` (per-kind field map for FR-013b),
  optional `user_owned` (paths preserved on update per FR-025).
  Stored as `<vault>/modules/<name>/manifest.yaml`.
- **ModuleSourcesFile**: per-module declarative source-instance list.
  Stored as `<vault>/modules/<name>/sources.yaml`. Module-specific
  top-level keys; each record supplies identity fields for FR-013b.
  Authoritative input for source-extraction enumeration (FR-013a).
- **TriggerRegistry**: in-memory mapping built from all installed
  modules' manifests. Used to route incoming sources to modules.
  Order is `settings.yaml::modules:` array order \u2014 first match wins.
- **Trigger**: declarative pattern matcher. Fields: `type` (e.g.
  `url_pattern`, `path_pattern`), `pattern` (regex or glob).
- **FactsSchema**: per-`(vault, module)` JSON Schema. Generated by
  schema-gen from spec + data_sources + module's few-shot examples.
  Stored at `<vault>/_pipeline/sources/<module>/facts-schema.json`.
  May be manually edited (sets `manually_edited: true` to opt out of
  regeneration).
- **Validator** (per-module): vault-supplied rules for shaping the
  signal payload. Two surfaces: `<module>.validators.yaml` (declarative)
  and `<module>.validators.py` (procedural escape hatch). Live next to
  `research.spec.md`.
- **ConsensusResult**: per-source, per-cycle verdict from M-of-N
  extractors. Fields: `module`, `source_id`, `cycle`,
  `extractors_spawned`, `verdicts` (list), `final_verdict`,
  `findings_unioned` (count). Stored at
  `_pipeline/sources/<module>/consensus/<source>-cycle-NNN.json`.
- **AgentCallRecord**: per-call audit of every LLM invocation (FR-024).
  Fields: `stage`, `call_id`, `timestamp`, `model`, `prompt`,
  `response`, `latency_ms`, `tokens_in`, `tokens_out`, `cost_usd`,
  `error?`. Stored at
  `_pipeline/cycles/cycle-NNN/agent-calls/<ts>-<stage>-<call-id>.json`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a vault unchanged between two consecutive cycles, the
  second cycle's source-extraction stage MUST complete in under
  500 ms total (cache-hit path only, zero LLM calls).
- **SC-002**: On the user's reference-vault baseline (3 repos, 6 cycles),
  token spend in the source-walk path MUST drop by at least 60%
  compared to 0.2.30. Measured as the sum of agent tokens charged
  against the source-extraction + scout stages.
- **SC-003**: On the same baseline, new-topic yield per cycle MUST
  rise to at least 2\u00d7 the 0.2.30 baseline (\u226520 topics/cycle vs ~10).
- **SC-004**: When the user pushes one new commit to one of three
  repos, only that repo re-extracts on the next cycle. Verified by
  cache-file mtimes and a log line "1/3 cache miss".
- **SC-005**: Zero cycles MUST abort due to source-bridge failures
  on the user's baseline. A source-level failure surfaces as a WARN,
  not a halt.
- **SC-006**: Schema-gen MUST produce visibly different schemas for
  two structurally-different vault specs using the same module (e.g.
  web-microservices vs ESP32 firmware). This is the load-bearing
  test for Constitution Principle "domain-agnostic by construction"
  (1.3.2 update).
- **SC-007**: A module manually dropped into `<vault>/modules/`
  post-install MUST be auto-discovered and active on the next
  pipeline start, with no reinstall and no settings.yaml edit
  required.
- **SC-008**: When a source is encountered whose trigger matches no
  installed module, the pipeline MUST fall back to generic web/file
  handling without surfacing any "you should install module X"
  prompt to the user.
- **SC-009**: Every agent invocation in a successful cycle MUST
  produce a corresponding `agent-calls/` record. Verified by counting
  records vs cost-report invocation count.

## Assumptions

- The user's vaults will continue to have a manageable number of
  sources (5\u201350). Designing for thousands per vault is out of scope.
- "Source instance" for extraction means an entry in
  `<vault>/modules/<name>/sources.yaml` (FR-013a). `research.spec.md::data_sources`
  remains the scout/spec coverage contract and schema-gen input; the two
  MAY overlap during migration but are not auto-synced in 020.
  Scout-discovered URLs encountered mid-research still go through generic
  handling in 0.3.0; routing them through modules is a future enhancement
  (deferred to 0.4.0+).
- Codex remains the default runtime. Consensus N>1 assumes the
  per-call cost makes spawning N agents per source per cycle
  affordable for `important` / `critical` tiers; teams with stricter
  budgets keep everything at `routine` (N=1).
- Schema-gen runs once per `(vault, module)` pair at install time and
  on spec-hash change \u2014 NOT per-cycle. Cost is therefore tens of cents
  per vault lifetime, effectively free relative to the rest of the
  pipeline.
- The YAML-validator surface is enough for the common case. The
  Python escape hatch is the relief valve, NOT the default
  experience. If 50% of vaults end up needing Python, the YAML
  surface needs a redesign \u2014 we should monitor that metric.
- Modules and per-vault `<module>.validators.py` execute Python in
  the framework's process tree (via subprocess invocation for
  modules; in-process for validators), with full file-system access.
  This is a TRUST boundary v1 enforces only through documentation \u2014
  no technical sandbox in 0.3.0. Vault authors MUST NOT install
  modules from untrusted sources. The install wizard surfaces a
  warning when `modules:` is non-empty; `quickstart-module-author.md`
  opens with a bold warning. A future sandbox (subprocess isolation
  + restricted environment) is acknowledged as a follow-up but is
  out of scope for 0.3.0 \u2014 the v1 contract is intentionally shaped
  so a sandbox can land later without breaking module authors.
- The framework ships ONE module in 0.3.0 (code). YouTube, Reddit,
  O'Reilly, and other modules are deferred; their implementations
  drop into `src/research_framework/modules/` later without spec
  changes.

## Acceptance coverage

Backfilled per issue #283 (the acceptance-coverage guard's numbered-G/W/T
discovery pattern was single-line and never matched this spec's wrapped
`**Given**...**When**...**Then**` scenarios, so this spec silently escaped
enforcement from 0.3.0 onward). 020 shipped 0.4.0 via PR #32, seven specs
before the acceptance-coverage convention itself shipped (spec 024, 0.3.0),
and its test coverage has since been reorganized across the 025 Tier A/B
split and the 049 cycle-helpers split — no per-story test was tagged at
ship time, and reconstructing an exact story→test map now would be a
guess dressed as evidence.

| User Story | Evidence |
|------------|----------|
| US1 — Cached source-walk eliminates re-extraction waste | _(historical — shipped 0.4.0 via PR #32, predates the acceptance-coverage convention; coverage exists in the shipped suite under `src/research_framework`'s code-bridge cache path but was never tagged to this table)_ |
| US2 — Scout reads cached signals instead of walking sources | _(historical — shipped 0.4.0 via PR #32, predates the acceptance-coverage convention)_ |
| US3 — Modules are dynamically discovered and routed by trigger | _(historical — shipped 0.4.0 via PR #32, predates the acceptance-coverage convention; see `src/research_framework/pipeline/source_bridge/discovery.py::TriggerRegistry`, still live per spec 069)_ |
| US4 — Per-module schema generated from the vault spec | _(historical — shipped 0.4.0 via PR #32, predates the acceptance-coverage convention)_ |
| US5 — Per-vault validators shape the signal payload | _(historical — shipped 0.4.0 via PR #32, predates the acceptance-coverage convention)_ |
| US6 — Value-tiered consensus per invocation | _(historical — shipped 0.4.0 via PR #32, predates the acceptance-coverage convention; spec 037 later generalized the same M-of-N pattern beyond `source_bridge`)_ |
| US7 — Per-call agent logging (cross-cutting) | _(historical — shipped 0.4.0 via PR #32, predates the acceptance-coverage convention)_ |

## Out of Scope (Explicit)

- Spec-driven topic discovery for coverage gaps (sibling spec
  021).
- Multi-agent consensus for note-writer (different feature; this
  spec's consensus mechanism applies only to source-extraction).
- Graduating the subprocess invocation to an HTTP server or MCP
  server (graduation path exists; no work planned for 0.3.0).
- Routing scout-DISCOVERED URLs through modules. 0.3.0 only extracts
  instances declared in per-module `sources.yaml` (FR-013a). Promotion
  to module routing for discovered URLs comes later.
- Porting the user's prior feeds-vault scripts (YouTube, Reddit,
  O'Reilly) into framework modules. The architecture supports it;
  the ports happen in 0.4.0+ as separate work.
- Replacing existing direct repo-access in `validate_vault.py` and
  other non-scout consumers (those don't compete for the scout's
  token budget and are correctly direct-read).
- The 0.2.31 verifier/wikilink fixes \u2014 those shipped first to
  unblock the existing release line.

## Open Questions \u2014 to resolve in `plan.md` before implementation

All design decisions are LOCKED. The plan.md needs to resolve only
these implementation-time choices:

1. **Where does `pursuit_state`-style cached metadata live for the
   bridge?** Inside the watermark file or as a separate sidecar?
   (Probably the watermark file for atomicity, but plan should
   confirm.)
2. **Manifest-discovery filesystem walking strategy.** \u2705 Resolved
   in Clarifications Session 2026-05-26: walk every pipeline start, no
   `_pipeline/` registry cache (FR-010).
3. **First-match-wins ordering for triggers.** Spec says use
   `settings.yaml::modules:` array order; plan should confirm and
   document how a vault author can debug "why didn't my module
   match" (proposed: a `--debug-triggers` flag on the source-bridge
   that prints the trigger registry + match attempt log).
4. **Module discovery + install-time copy.** The shape of
   `install.sh`'s module-copy step. Probably a `cp -r` per named
   module from `<bundle>/modules/<name>/` to `<vault>/modules/<name>/`,
   with a manifest validation step. Plan to flesh out.
5. **Trust boundary documentation.** Where does the warning about
   "modules execute arbitrary Python" live? Install wizard? Quickstart?
   Both? Plan to decide.
6. **Spec-hash tracking for schema-gen.** Where is the spec hash
   stored to detect "spec changed since last schema-gen run"?
   Probably `<vault>/_pipeline/sources/<module>/.schema-gen-hash`.
   Plan to confirm.
