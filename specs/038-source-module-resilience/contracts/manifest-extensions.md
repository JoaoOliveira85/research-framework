# Contract: Manifest extensions (spec 038 FR-001/003/004/013)

**Status:** PROPOSED (ships with spec 038)
**Amends:** `specs/020-code-bridge/contracts/manifest.schema.json` — adds three
**OPTIONAL** blocks to a schema that is currently `additionalProperties: false`.
All three are default-safe: **absent ⇒ today's behaviour** (no auth, no rate
limit, `block_cycle`).

This sits ON TOP of the shipped spec-051 `preflight` block (already REQUIRED) —
038 does not touch `preflight`.

---

## 1. `authentication` (FR-001/013) — OPTIONAL

```yaml
authentication:
  env_vars: [OREILLY_API_KEY]   # MANDATORY-for-this-module (Q3)
```

- `env_vars`: list of environment variables this module needs. **Each is MANDATORY
  for the module** (Q3). The module's `preflight.py::check()` reads `os.environ`
  (subprocess inherits the parent env) and emits `verdict=fatal_fail` with
  `module '<name>': missing env var <VAR>` when any is unset.
- Absent (or `authentication: none`) ⇒ module needs no credentials.
- The *probe* IS the module's existing `check()` — no separate probe-command spec
  (the shipped contract already spawns `check()`); FR-001's "probe-command" is
  satisfied by the connectivity probe added to `check()` (see plan §C).

```json
"authentication": {
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "env_vars": { "type": "array", "items": { "type": "string", "minLength": 1 } }
  }
}
```

## 2. `rate_limits` (FR-003) — OPTIONAL

```yaml
rate_limits:
  requests_per_minute: 60
  requests_per_hour: 1000
  burst: none                 # default
  backoff: exponential        # base=2, max=300s, jitter=0.2 (defaults)
```

- **v1 ships the DECLARATION + schema.** Client-side ENFORCEMENT (token-bucket
  duplicated module-side, since modules can't import from `src/`) is flagged
  NEEDS-CLARIFICATION in the plan: recommended deferred until real rate-limit
  incidents are observed (spec's own "need real-world signal" assumption).
- Absent ⇒ unbounded (today's behaviour).

```json
"rate_limits": {
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "requests_per_minute": { "type": "integer", "minimum": 1 },
    "requests_per_hour": { "type": "integer", "minimum": 1 },
    "burst": { "type": "string", "default": "none" },
    "backoff": { "type": "string", "default": "exponential" }
  }
}
```

## 3. `failure_policy` (FR-004) — OPTIONAL

```yaml
failure_policy: block_cycle   # block_cycle (default) | degrade_gracefully | defer
```

- `block_cycle` — de-facto today: a `fatal_fail` preflight skips the module; an
  extractor error sets `verdict=error`. This is the default when absent.
- `degrade_gracefully` — warn + skip the module's contribution this cycle (net-new
  orchestrator branch).
- `defer` — mark for retry next cycle, continue without (net-new branch).

```json
"failure_policy": {
  "type": "string",
  "enum": ["block_cycle", "degrade_gracefully", "defer"],
  "default": "block_cycle"
}
```

## 4. Status enum note (FR-005) — NO schema change

FR-005's `EMPTY` already ships as `signal.py::Verdict = Literal["ok","empty",
"exhausted","error"]`. **038 does NOT rename to uppercase** (that would break every
signal/watermark JSON). Spec-038 `EMPTY`/`FAILED` are aliases of `empty`/`error`.
The delta is `WatermarkEntry.recent_cycle_verdicts` (rolling 3-cycle window for
the sustained-failure gate) — see `data-model.md`.

## 5. Acceptance

- `manifest.schema.json` gains the 3 optional blocks; existing manifests (no
  blocks) still validate.
- `discovery.parse_manifest` parses + validates the blocks; an unknown
  `failure_policy` enum value raises `ValueError` (fail-fast).
- O'Reilly's `manifest.yaml` declares `authentication.env_vars: [OREILLY_API_KEY]`
  and `failure_policy: block_cycle`; its `preflight.py::check()` fails-closed on the
  missing key (US2 #1).
