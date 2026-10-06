# Sandbox detection for `processors/extract.py`

**Spec:** 032-pipeline-reliability (FR-001, FR-002, FR-008, SC-005).
**Operator walkthrough:** `specs/032-pipeline-reliability/quickstart.md#sandbox-detection`.

## Why this exists

The code-extraction stage (`processors/extract.py`) dispatches a nested CLI
agent (Claude Code) to summarise repositories. When the *parent* run is itself
a sandboxed agent session, that nested dispatch typically **cannot reach the
OAuth keychain** — every call fails to authenticate. Before spec 032 the stage
treated those auth failures like any other extraction failure and wrote an
`extraction-failed` **stub** for each target. A sandboxed cold-start could
therefore silently poison a whole cycle with dozens of empty stubs that *look*
like "we tried and the source was bad", when in truth nothing was ever
attempted. That is a silent-data-loss footgun, not a content signal.

The detector turns that silent failure into a **loud, fail-closed** stop.

## The layered heuristic

A single `_SandboxClassifier` instance is created per `extract()` run and fed
every dispatch `AgentCallResult`. A successful call (exit 0) resets all state.
On a failed call it applies two layers, in order:

### Layer 1 — stderr/stdout auth signature (primary)

The combined `stderr` + `stdout` is lower-cased and matched against a tolerant
signature set:

- literal markers: `invalid api key`, `please run /login`, `not logged in`,
  `logged in`;
- heuristic markers: `auth` **and** `fail` co-occurring, `oauth`, `credential`,
  or `keychain`.

Any match trips the detector immediately (one bad call is enough — an explicit
auth-failure string is unambiguous).

### Layer 2 — fast-failure time fallback

Sandboxes that fail *without* a recognisable string still fail
**characteristically fast** (no network round-trip). If a call fails with
`latency_ms < 1000`, a counter increments; **3 consecutive** sub-second
failures trip the detector. A slow failure (≥1000 ms, e.g. a genuine network
timeout) resets the counter — slow failures are real work, not a sandbox.

Thresholds (`processors/extract.py`):
`_FAST_SANDBOX_FAILURE_MS = 1000`, `_FAST_SANDBOX_FAILURE_THRESHOLD = 3`.

## Fail-closed posture (and why it differs from the 048-v2 ledger)

On a trip the stage raises `SandboxDetectedError` and **writes zero stubs**. An
in-flight stub write is also aborted if the classifier has already tripped, so
no partial poisoning leaks through a race. The run stops loudly rather than
producing misleading artifacts.

This is deliberately **stricter** than the spec 048-v2 Source-Consideration
Ledger, which uses a non-blocking **WARN** posture. The two serve different
goals: the ledger is an *observability* lens (record what happened, never block
the pipeline), whereas sandbox detection guards against *writing wrong data*.
When the choice is "stop" vs "persist a false negative", extraction fails
closed.

## Override — `RV_DISABLE_SANDBOX_DETECT` (SC-005)

Some contexts are legitimately pre-authenticated inside a sandbox (autonomous
mode with `dangerouslyDisableSandbox: true`, or a manually `claude /login`-ed
shell). Set the environment variable to opt out of **both** layers:

```bash
RV_DISABLE_SANDBOX_DETECT=1 ./vault research      # also accepts: true, yes
```

Accepted truthy values: `1`, `true`, `yes` (case-insensitive). When set, the
classifier returns "not sandboxed" for every call and no stub writes are
blocked. The default (unset) is fail-closed.

## Remediation surfaced to the operator

`SandboxDetectedError`'s message is self-documenting and points back here:

> Sandboxed Claude Code environment detected (`<reason>`). Nested agent
> dispatch cannot authenticate — no extraction stubs were written.
> Remediation: run `claude /login` before autonomous extraction, or set
> `dangerouslyDisableSandbox: true` in the vault Claude settings when running
> inside a nested sandbox.

## Tests

`tests/processors/test_extract.py` (`-k sandbox`) covers both layers, the
override, the zero-stub guarantee, and the non-sandboxed pass-through.
