# Data Model: Observability v1 MVP

**Spec**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md) · **Date**: 2026-05-29

Three entities. Two on-disk (`LoggerRecord` projected to stderr; `BridgeLogEntry` written to `bridge.log`), one in-memory (`CycleObservabilityState`).

---

## Entity 1 — `LoggerRecord` (in-memory; projected to stderr stream)

**What it is**: A single `logging.LogRecord` emitted by any module-level `getLogger(__name__)` instance within the framework. The format pins exactly how each record is rendered to the configured stream (stderr).

**Format** (locked by FR-001):

```
%(asctime)s [%(levelname)s] %(name)s: %(message)s
```

Example rendering:

```
2026-05-29 14:23:51,107 [INFO] research_framework.pipeline.cycle_runner: cycle 3 / 5 starting
2026-05-29 14:23:51,892 [DEBUG] research_framework.pipeline.steps.scout: cache hit for source youtube/VIDEO_ID
2026-05-29 14:24:14,003 [WARNING] research_framework.observability.bridge_log: extractor youtube exited non-zero (code=1)
```

**Fields**:

| Field | Format | Source | Notes |
|---|---|---|---|
| `asctime` | `YYYY-MM-DD HH:MM:SS,mmm` | `logging.Formatter` default | Millisecond precision. Local TZ. |
| `levelname` | `DEBUG`/`INFO`/`WARNING`/`ERROR` | `LogRecord.levelname` | Locked to these four (no CRITICAL — we don't use it). |
| `name` | dotted Python path | `getLogger(__name__)` | Must be the importing module's `__name__`. No literal strings (FR-003). |
| `message` | freeform UTF-8 | `logger.info(...)` arg | No multi-line records — `\n` in `message` produces a multi-line render but the record is still atomic. |

**Lifecycle**: Created by `Logger.info()` / `.debug()` / `.warning()` / `.error()`. Emitted synchronously to `sys.stderr`. Not retained; future v1.1 `vault status` reads a tail of `sys.stderr` redirected to a per-cycle log (NOT in MVP).

**Validation rule**: Format string is locked. `tests/observability/test_log_surfaces.py` asserts the rendering matches a pinned regex (see `contracts/logger-wiring.contract.md`).

**State transitions**: None — `LoggerRecord` is value-typed, append-only.

---

## Entity 2 — `BridgeLogEntry` (on-disk line in `<vault>/_pipeline/cycles/cycle-NNN/bridge.log`)

**What it is**: A sequence of lines representing one extractor subprocess invocation. The first line is the *header*, the last is the *footer*, and every line between is a verbatim stderr line from the extractor (prefixed with `[<module>:<pid>] ` for disambiguation when multiple extractors interleave).

**Framing** (locked by FR-007, FR-008):

```
=== module: <name>, source: <id>, pid: <pid>, started: <iso-ts> ===
[<module>:<pid>] <verbatim stderr line 1>
[<module>:<pid>] <verbatim stderr line 2>
...
[<module>:<pid>] <verbatim stderr line N>
=== exit: <code>, duration: <s>s, payload_status: <verdict> ===
```

For a killed subprocess:

```
=== module: <name>, source: <id>, pid: <pid>, started: <iso-ts> ===
[<module>:<pid>] <partial stderr captured before kill>
=== KILLED BY FRAMEWORK (<reason>) after <s>s ===
```

**Reasons** (locked enum): `wall-clock cap`, `dollar cap`, `manual interrupt`, `parent exit`.

**Fields per header**:

| Field | Type | Example |
|---|---|---|
| `module` | string | `youtube`, `code`, `reddit` |
| `source` | string (module-specific ID) | `VIDEO_ID_XYZ`, `commit_sha_abc123` |
| `pid` | integer | `47291` |
| `started` | ISO-8601 timestamp w/ ms | `2026-05-29T14:23:51.107` |

**Fields per footer (success)**:

| Field | Type | Example |
|---|---|---|
| `exit` | integer (Unix exit code) | `0`, `1`, `137` |
| `duration` | float seconds | `4.328` |
| `payload_status` | `BridgePayloadVerdict` enum value | `ok`, `empty`, `error` |

**Fields per footer (killed)**:

| Field | Type | Example |
|---|---|---|
| `reason` | enum (see above) | `wall-clock cap` |
| `after` | float seconds | `300.000` |

**Lifecycle**:

1. File created on first extractor invocation in a cycle (`open(path, "a", encoding="utf-8")`).
2. Header line written when extractor `Popen` returns; PID is `proc.pid`.
3. Body lines written by the reader thread as stderr arrives. Each acquires the shared `threading.Lock` for atomic append.
4. Footer line written when `proc.wait()` returns OR when the orchestrator decides to kill the subprocess (whichever comes first).
5. File handle stays open across extractor invocations within the same cycle (no per-call open/close).
6. File closed at cycle exit (success or failure) in a `finally:` block in `cycle_runner`.

**Validation rule** (FR-015): A regex test parses the framing and asserts well-formedness. The header regex is:

```
^=== module: (?P<module>[\w-]+), source: (?P<source>[^,]+), pid: (?P<pid>\d+), started: (?P<started>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}) ===$
```

**State transitions** (per extractor invocation):

```
[ no file or empty ]
  → header written
  → body line written (zero or more)
  → footer written (either success or KILLED form)
[ end of one invocation; next invocation appends next header ]
```

**Concurrency**: Lines from interleaved extractors may appear in any order (the lock guarantees atomicity per-write, not per-invocation). The `[<module>:<pid>] ` prefix is the disambiguator. Within a single extractor invocation, lines are always in stderr-emission order (single reader thread, sequential drain).

---

## Entity 3 — `CycleObservabilityState` (orchestrator-owned, transient, in-memory)

**What it is**: The state held by `cycle_runner` during a cycle. Tied to a single cycle's lifetime; created on cycle start, destroyed on cycle exit.

**Fields**:

| Field | Type | Notes |
|---|---|---|
| `bridge_log_path` | `pathlib.Path` | `<vault>/_pipeline/cycles/cycle-NNN/bridge.log` |
| `bridge_log_writer` | `BridgeLogWriter` instance | Holds the file handle + the framing lock |
| `active_capture_threads` | `list[threading.Thread]` | Tracked so the orchestrator can `.join(timeout=...)` at cycle end |

**Lifecycle**:

```
[ cycle_runner.run_cycle_steps ]
  → mkdir -p <vault>/_pipeline/cycles/cycle-NNN/
  → CycleObservabilityState(...)
    → BridgeLogWriter(...).__enter__()
  ↓
  [ source_bridge.orchestrator.dispatch_extractor(state, module, source) ]
    → start_capture(proc, module, source, state.bridge_log_writer)
      → thread added to state.active_capture_threads
    → proc.wait()
    → thread.join()
    → write footer
  ↓
  [ cycle_runner exit ]
  → for t in state.active_capture_threads: t.join(timeout=5.0)
  → state.bridge_log_writer.close()
  → state = None
```

**Validation rule**: At cycle exit, `active_capture_threads` should be empty (all extractors drained). Test asserts this via `state.active_capture_threads == []` post-`cycle_runner` invocation.

**State transitions**:

- **Created** (cycle start) → **Active** (an extractor is dispatched, reader thread running) → **Idle** (extractor done, thread joined) — alternates while extractors run — → **Closed** (cycle exit; file handle released).
- Once **Closed**, attempting to dispatch through this state is a programmer error and raises `ValueError("CycleObservabilityState is closed")`.

---

## Cross-entity invariants

1. **Logger records and bridge.log are independent surfaces.** A `logger.info("dispatching extractor youtube")` does NOT appear in `bridge.log`; it appears on stderr. A subprocess's stderr line `transcript not found` does appear in `bridge.log`; it does NOT appear on the framework's stderr. The operator gets both surfaces (one via terminal, one via `tail -f`).
2. **Cycle NNN's `bridge.log` is owned by a single process.** No multi-writer scenarios (different `./vault research` invocations in different terminals operate on different vaults → different cycle dirs). No file locking across processes needed.
3. **Verbatim preservation**: extractor stderr bytes pass through unchanged except for the `[<module>:<pid>] ` prefix. No filtering, no ANSI-strip, no truncation.

## References

- FR-001, FR-002, FR-003 (Entity 1)
- FR-006, FR-007, FR-008 (Entity 2)
- FR-015 (regression test parses Entity 2 framing)
- Plan § Phase 1 (this file is the data-model deliverable)
