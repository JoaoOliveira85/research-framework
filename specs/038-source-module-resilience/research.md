# Research: Source-Module Resilience Polish (spec 038)

**Date**: 2026-06-03 | **Branch**: `038-source-module-resilience`
**Mandate**: Spec 038 is a **DELTA** over the shipped spec-051 `preflight()`
contract (0.8.0) and the shipped 0.6.2 `raw_capture.py`. This file audits what
already exists so the plan only specifies *net-new* content.

---

## A. The shipped `preflight()` surface (spec 051 / 0.8.0) — audited 2026-06-03

| Shipped artifact | What it already does | 038 builds on it by… |
| --- | --- | --- |
| `pipeline/source_bridge/preflight_types.py` | Frozen `PreflightResult{schema_version, verdict, corrections, messages}` + `SourceCorrection{original, suggested, reason, applied}`. `from_json` is the cross-process trust boundary (rejects malformed payloads, bad `applied` non-bool). Convenience ctors `success()/warning()/fatal()`. `Verdict = Literal["success","warning","fatal_fail"]`. | **Reuse verbatim.** 038 adds NO new dataclass — auth/connectivity findings ride the existing `messages[]` + `corrections[]` channels; the verdict table is unchanged. |
| `pipeline/source_bridge/preflight_runner.py` | `run_preflight(vault_dir, manifest)` spawns `<module>/<preflight.entry_point> preflight` via `popen_session`, feeds `{schema_version, sources, watermarks}` on stdin, parses stdout, clamps `timeout_seconds` to `[1,300]`, fail-closes (crash/timeout/non-zero/garbage → `fatal_fail`). | **Reuse the spawn machinery verbatim.** 038 adds probe *content* INSIDE each module's `check()`; it does NOT touch the runner except (optionally) to widen the stdin request with an `env_present` map (see §C). |
| `pipeline/source_bridge/orchestrator.py` (L75-113) | Calls `run_preflight` once per module at cycle start; records `module_stats["preflight"]`; `fatal_fail` ⇒ skip-with-WARN that module only (Principle VIII isolation); `warning` messages surfaced. | **Reuse the verdict→action wiring.** 038's auth-missing case is a module emitting `fatal_fail` with a clear message — already handled. |
| `cli/refresh_sources.py` (`_preflight_sweep`, `_report_preflight`) | `./vault refresh-sources` runs a discrete preflight sweep across installed modules, fail-closed per module, with a verdict report. | **Reuse the sweep as US2/US4's "preflight at install/refresh" surface** — no new CLI verb needed for the auth probe. |
| `modules/{youtube,reddit,rss,oreilly,code,_template}/preflight.py` | Each ships a subprocess `main()` + pure `check(sources, watermarks, *, timeout_seconds)`. URL-shape validation only. `rss` does a fixture-overridable HEAD probe. | **Extend each `check()`** with the §C probe content (env-var presence + connectivity), guarded by the same fixture-override discipline `rss` already uses. |
| `modules/*/manifest.yaml` | `preflight: {entry_point, timeout_seconds}` REQUIRED (spec-020 schema amended; `preflight` in `required`). | **Add two OPTIONAL manifest blocks** — `authentication` and `rate_limits` — to the spec-020 schema (§B). `failure_policy` partially exists implicitly (see §D). |
| `specs/020-code-bridge/contracts/manifest.schema.json` | Already lists `preflight` in `required`; `additionalProperties: false`. | **Amend** to allow `authentication`, `rate_limits`, `failure_policy` (all optional, default-safe). |
| `scripts/raw_capture.py` (0.6.2) | Per-URL capture into `<vault>/raw_data/{year}/{month}/<slug>-<hash>.<ext>` + sibling `meta.json`; `classify_payload` (`rich/thin/js_shell/binary`); 5 MB cap; 20 s timeout; idempotent on existing `meta.json`; exit 0/1/2. | **Reuse `capture()` as the per-URL primitive.** 038 adds a *batch* driver `scripts/raw_capture_batch.py` that enumerates new-note `source_urls` and calls `capture()` per unique URL, OUTSIDE the agent loop (§E). |

### A.1 The already-shipped EMPTY-vs-FAILED distinction (KEY FINDING)

FR-005's headline ("`EMPTY` distinct from `FAILED`") is **substantially already
shipped** at the extractor/watermark layer:

- `signal.py`: `Verdict = Literal["ok", "empty", "exhausted", "error"]` — `empty`
  (200 OK, zero hits) is already a *distinct* value from `error` (network/auth/parse).
- `cache.py::WatermarkEntry` already persists `verdict: Verdict` AND
  `consecutive_empty_cycles: int` per source, atomic-written to
  `_pipeline/sources/<module>/watermarks.json`.
- `orchestrator.py` already sets `payload.verdict = "error"` on isolated-call
  failure and writes the `WatermarkEntry(verdict=payload.verdict, ...)`.

**Therefore 038's FR-005 delta is NOT "add an EMPTY status"** (it exists). The
genuine delta is:
1. **Surface** the distinction in the **cycle report** ("source health: youtube
   FAILED with HTTP 401" vs. silent for EMPTY) — US1 acceptance #1/#2.
2. A **sustained-failure gate**: FAIL the quality harness when a module's `error`
   rate exceeds a threshold over a rolling window (US1 acceptance #3, SC-004).
   `consecutive_empty_cycles` exists; a `consecutive_error_cycles` (or rolling
   `error` ratio) does not — that is the net-new field.
3. Spec wording in FR-005 uses uppercase `EMPTY`/`FAILED`; the shipped enum is
   lowercase `empty`/`error`. **The plan keeps the shipped lowercase enum** (do
   NOT rename — that would be a breaking schema change across all signal/watermark
   files) and treats `FAILED == error`, `EMPTY == empty` as the spec-038 alias.

This is the single biggest scope reduction the audit produces.

---

## B. Manifest delta — `authentication`, `rate_limits`, `failure_policy`

The spec-020 manifest schema is `additionalProperties: false`, so 038 MUST amend
it to add three optional blocks. Default-safe (absent ⇒ today's behaviour):

```yaml
authentication:            # FR-001; absent ⇒ "none"
  env_vars: [OREILLY_API_KEY]   # MANDATORY-for-this-module (Q3)
  # probe is the module's preflight check() itself — no separate probe spec needed
rate_limits:               # FR-003; absent ⇒ unbounded (today's behaviour)
  requests_per_minute: 60
  requests_per_hour: 1000
  backoff: exponential     # base=2, max=300s, jitter=0.2 defaults
failure_policy: block_cycle  # FR-004 enum: block_cycle | degrade_gracefully | defer
```

**Q3 (clarified)**: anything in `authentication.env_vars` is MANDATORY for that
module — its absence makes the module's `preflight check()` emit `fatal_fail`
(skip-with-WARN per the shipped verdict table). External checks (`gh auth status`,
generic connectivity) are WARN-only.

**FR-003 rate_limits** — declared in the manifest but **client-side enforcement
lives in each module's `extractor.py`** (modules can't import from `src/`). v1 of
038 ships the *declaration* + a stdlib token-bucket helper duplicated module-side
(like the process-tree helper duplication pattern). The plan flags whether
enforcement is in-scope for the first ship or deferred (see plan Phase boundary).

**FR-004 failure_policy** — `block_cycle` is the de-facto today (a `fatal_fail`
preflight skips the module; an extractor error sets `verdict=error`).
`degrade_gracefully`/`defer` are net-new orchestrator branches.

---

## C. Probe content delta — env-var presence + connectivity

The module `check(sources, watermarks, *, timeout_seconds)` is the seam. 038 adds:

- **Env-var presence probe**: the module reads its own `os.environ` for the vars it
  needs (the subprocess inherits the parent env). Missing MANDATORY var ⇒
  `fatal_fail` with `module 'youtube': missing env var YOUTUBE_API_KEY`. This is
  the cheapest possible check (<2 s, zero API calls) — satisfies US2 acceptance #1.
  - **Open design point**: does the module read `os.environ` directly, OR does the
    runner pass an `env_present: {VAR: bool}` map in the stdin request? Reading
    `os.environ` directly is simpler and needs no runner change; passing a map
    keeps the module deterministic under test. **Recommend: module reads
    `os.environ` directly, with an env-override (`<MODULE>_PREFLIGHT_FAKE_ENV`)
    for hermetic tests** — mirrors the shipped `RSS_FIXTURE`/`YT_DLP_BIN` pattern.
- **Connectivity probe** (WARN-only): an optional bounded HEAD/GET to the module's
  declared API endpoint (`rss` already does this for feed URLs; `oreilly` would
  HEAD `learning.oreilly.com`). Failure ⇒ `warning` message, NOT `fatal_fail`
  (Q3). Fixture-overridable for tests.
- **`gh auth status`** (US4 #4, FR-012): a WARN-level check, but `gh` is a *vault
  external tool*, not a module subprocess concern. **Recommend this lives in the
  `refresh-sources` sweep / a `./vault preflight`-style host check, NOT inside a
  module's `check()`** — modules stay offline-safe and tool-agnostic. Flagged as a
  design boundary in the plan.

No new `PreflightResult` fields are required: a missing-env finding is a
`fatal_fail` message; a connectivity warning is a `warning` message. The existing
contract carries all of it.

---

## D. archive.org fallback (US5 / FR-008) — fail-and-defer

- `vault_health.py` already exists with an `--apply` convention (creates stub notes,
  fixes wikilinks). 038 adds an archive.org snapshot pass to `vault_health --apply`.
- **Q2 (clarified): fail-and-defer.** On rate-limit/failure, record the URL as
  `deferred` in `_pipeline/archive-snapshots.json` and **exit 0** (non-blocking) —
  do NOT throttle 100 dead URLs to completion in an unattended run. Deferred URLs
  accumulate across cycles.
- Snapshot creation = a single POST to `https://web.archive.org/save/<url>` (stdlib
  `urllib`). Network access ⇒ Principle V: MUST be fixture-overridable for tests
  (an env-override returning a canned snapshot URL), and the feature is **opt-in**
  via `--apply` (never auto-fires offline).
- Persistent artifact `_pipeline/archive-snapshots.json`: `{url: {snapshot_url,
  created_at, status}}` where `status ∈ {archived, deferred, unarchivable}`.

---

## E. `scripts/raw_capture_batch.py` (US3 / FR-006) — NEW, builds on 0.6.2

- **Q1 (clarified): a separate centralized batch script**, NOT a per-module hook.
  Runs ONCE outside the agent loop = sandbox-proof (the 2026-05-13 feeds-vault
  incident: the sandboxed agent can't fetch; the host batch can).
- Reads new-note `source_urls` from frontmatter (via the canonical
  `vault/frontmatter.py` parser — FR-011 reuses it), de-dups by `sha256(url)`,
  calls `raw_capture.capture()` (the shipped 0.6.2 primitive) per unique URL.
- **Output location**: spec.md FR-006 says
  `<vault>/raw_data/captures/<YYYY-MM-DD>/<sha256>.{html,pdf}` +
  `manifest.json`. The shipped `raw_capture.py` writes to
  `<vault>/raw_data/{year}/{month}/<slug>-<hash>`. **Decision for the plan**: the
  batch writes its own **manifest** under `raw_data/captures/<DATE>/manifest.json`
  mapping URL → captured-path + timestamp + status + citing-notes, but **delegates
  the actual byte-mirroring to the existing `capture()`** (which keeps its
  `year/month` layout). The manifest is the index; the bytes live where `capture()`
  puts them. This avoids forking the capture primitive. (Alternative: pass a
  `target_dir` override to `capture()` — flagged as a minor contract tweak.)
- **Idempotent (FR-007)**: `capture()` is already idempotent on an existing
  `meta.json`; the batch manifest's `status` field drives partial-run resume (only
  re-fetch URLs without an `OK` manifest entry).
- **Exit-0 on per-URL failure (FR-006 #2, SC-002)**: a 5xx/timeout records
  `status: FAILED` and the batch continues; the batch exits 0 even with all-failed
  URLs (US3 is non-fatal).

---

## F. Install preflight items (US4) — mostly thin wiring

| FR | Shipped state | 038 delta |
| --- | --- | --- |
| FR-009 install path confirm | `dist-templates/install.sh` exists | Add the `[Y/n]` echo + `--accept-path` headless flag. Shell change only. |
| FR-010 O'Reilly loud failure | oreilly preflight + `failure_policy` | Wire `block_cycle` ⇒ loud non-zero in the refresh-sources sweep when the module is unreachable. Reuses §B/§C. |
| FR-011 validator detailed-spec fields | `vault/frontmatter.py` canonical parser shipped (spec 025 B4) | Regression test only — assert validator summaries traverse detailed-spec fields. The bug is already fixed; 038 locks it. |
| FR-012 extended preflight | `refresh-sources` sweep | Add `gh auth status` + connectivity + local-repo-path checks (code-bridge clone existence) as host-level WARN checks in the sweep. |
| FR-013 env-var matrix | manifest `authentication.env_vars` (§B) | Declarative per module; MANDATORY for the module. |
| FR-015 O'Reilly opt-in tiers | `oreilly/sources.yaml.template` uses `value_tier` | Default O'Reilly to a `tier:` block so it's not in broad queries unless opted in. |

---

## G. Deferred / tombstoned

- **FR-014 (`DataSourceConfig.kind`/`module`)** — DEFERRED until ADR-0009 reaches
  ACCEPTED (currently PROPOSED). Stays a tombstone; NOT implemented in 038. Modules
  already declare URL triggers (spec 020), so the runs don't need it.
- **Cross-module rate-limit coordination** — out of scope (each module owns its
  quota; no shared bus).
- **Cloud/S3 raw-URL mirroring** — spec 044 territory; 038 is local-disk only.

---

## H. NEEDS CLARIFICATION (real unknowns surfaced by the audit)

1. **FR-003 rate-limit ENFORCEMENT in first ship?** The audit can confirm the
   *declaration* is cheap (manifest + schema). Client-side enforcement requires a
   token-bucket duplicated into each module's `extractor.py` (modules can't import
   from `src/`). Is enforcement in v1, or does v1 ship the declaration + leave
   enforcement to a follow-up once real rate-limit incidents are observed (the
   spec's own Assumption: "≥2 modules ported BEFORE this spec … need real-world
   signal")? **Recommend: declare in v1, defer enforcement.** Confirm at /tasks.
2. **`raw_capture_batch.py` byte layout** — keep `capture()`'s `year/month` layout
   with a separate `captures/<DATE>/manifest.json` index (no capture fork), OR add
   a `target_dir` override to `capture()` so bytes land under `captures/<DATE>/`
   exactly as FR-006 literally reads? **Recommend the manifest-index approach** (no
   fork); confirm at /tasks if the literal FR-006 path matters to a downstream
   consumer.

Both are /tasks-level, not /plan blockers — the plan proceeds with the recommended
defaults and flags them.
