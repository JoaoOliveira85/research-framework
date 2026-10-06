# Quickstart: Source-Module Resilience Polish (spec 038)

Operator-facing walkthrough of the surfaces spec 038 adds **on top of** the
shipped spec-051 `preflight()` contract and the 0.6.2 `raw_capture.py`.

---

## 1. Declare a module's credentials (US2 / FR-001)

Add an `authentication` block to a module's `manifest.yaml`. Each listed var is
MANDATORY for that module:

```yaml
# modules/oreilly/manifest.yaml
authentication:
  env_vars: [OREILLY_API_KEY]
failure_policy: block_cycle      # default; loud failure if unreachable
```

If `OREILLY_API_KEY` is unset, the module's preflight fails closed in **< 2 s**
with `module 'oreilly': missing env var OREILLY_API_KEY`, and the orchestrator
**skips only that module** for the cycle (other modules proceed). No more 15-minute
mid-cycle timeouts.

## 2. Run the preflight sweep (US2 / US4)

The shipped `./vault refresh-sources` sweep now also runs each module's env-var +
connectivity probe, plus host checks (`gh auth status`, connectivity, local repo
paths for code-bridge modules):

```bash
./vault refresh-sources
# [refresh-sources] preflight FAILED for module oreilly: missing env var OREILLY_API_KEY
# [refresh-sources] preflight [rss]: HEAD probe could not confirm XML at https://… (WARN)
# [refresh-sources] host: gh not authenticated — GitHub sources may be unreachable (WARN)
```

Mandatory failures are loud + non-zero; connectivity/`gh` issues are WARN.

## 3. EMPTY vs FAILED in the cycle report (US1)

A quiet week (200 OK, 0 hits) records `verdict: empty` and stays silent. A broken
source (401/timeout/parse error) records `verdict: error`, bumps
`consecutive_error_cycles`, and surfaces in the cycle report:

```text
source health: youtube FAILED with HTTP 401
```

Sustained errors (default: `error` rate > 50% over 3 cycles for one module) FAIL
the quality harness with a per-module breakdown. EMPTY never trips the gate.

## 4. Mirror source URLs after a cycle (US3 / FR-006)

Run the batch capture on the HOST (not the sandboxed agent) so citations survive
both sandbox network blocks and later link-rot:

```bash
scripts/raw_capture_batch.py --vault ~/Documents/feeds-vault --cycle 7
# OK    https://example.com/post        -> raw_data/2026/06/post-ab12cd34.html
# FAILED https://dead.example/gone      -> network error: 404
# wrote raw_data/captures/2026-06-03/manifest.json (10 URLs: 8 OK, 2 FAILED)
```

Idempotent — re-running skips `OK` URLs and retries `FAILED`/`PENDING`. **Exits 0
even if every URL fails** (citation durability is best-effort, never blocks).

## 5. Archive fragile URLs (US5 / FR-008)

```bash
scripts/vault_health.py --vault ~/Documents/feeds-vault --apply
# archived  https://fragile.blog/post -> https://web.archive.org/web/2026…/…
# deferred  https://throttled.site    -> rate-limited (retry next cycle)
```

Fail-and-defer: rate-limited URLs are recorded `deferred` in
`_pipeline/archive-snapshots.json` and retried next run — the pass always **exits
0** so it never stalls an unattended cycle.

## 6. Install with an explicit path confirm (US4 / FR-009)

```bash
./install.sh ~/Documents/feeds-vault
# Installing into: /Users/you/Documents/feeds-vault — confirm? [Y/n]
# headless:
./install.sh --accept-path ~/Documents/feeds-vault
```

---

## What did NOT change

- The spec-051 `preflight()` machinery (spawn, timeout, fail-closed verdict table,
  `PreflightResult` schema) — reused verbatim.
- The `signal.py` `empty`/`error` enum — NOT renamed (spec-038 `EMPTY`/`FAILED` are
  aliases).
- `raw_capture.py`'s per-URL `capture()` primitive + its `year/month` byte layout —
  the batch is just an index + driver over it.
- `DataSourceConfig` — `kind`/`module` (FR-014) is DEFERRED until ADR-0009 is
  ACCEPTED.

## Verify

```bash
.venv/bin/pytest -m "not e2e" tests/modules tests/scripts/test_raw_capture_batch.py \
  tests/source_bridge/test_watermark_error_streak.py
bash build.sh --quality      # SC-004: 0 EMPTY-vs-FAILED conflations across 3 fixtures
```
