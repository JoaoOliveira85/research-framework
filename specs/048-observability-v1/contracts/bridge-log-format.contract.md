# Contract: `bridge.log` file format

**Authority**: Spec 048 FR-006, FR-007, FR-008. Format is testable via `tests/observability/test_log_surfaces.py`.

## Location

```
<vault>/_pipeline/cycles/cycle-<NNN>/bridge.log
```

- `<NNN>` is the zero-padded cycle number (`cycle-001`, `cycle-042`, etc.) matching the existing `_pipeline/cycles/` naming.
- One file per cycle. No rotation. No size cap in v1.0 (spec 037 wall-clock cap on extractors naturally bounds stderr volume).
- Created lazily on the first extractor invocation in the cycle. If a cycle runs zero extractor calls, `bridge.log` is absent.

## File encoding

- **UTF-8**, no BOM.
- **LF line endings** (`\n`), not CRLF, regardless of host OS.
- Append-only: never rewritten, never truncated mid-cycle. New extractor invocations append to the existing file.

## Line grammar

Each line is exactly one of: header, body, footer-success, footer-killed.

### Header line

```
=== module: <name>, source: <id>, pid: <pid>, started: <iso-ts> ===
```

- `<name>` — module name, `[\w-]+` (alphanumeric + underscore + hyphen).
- `<id>` — module-specific source identifier. May contain spaces and slashes; SHALL NOT contain `,` or newlines.
- `<pid>` — positive integer (the subprocess's PID).
- `<iso-ts>` — `YYYY-MM-DDTHH:MM:SS.mmm` (millisecond precision, no timezone offset; assumed local).

Regex:

```
^=== module: (?P<module>[\w-]+), source: (?P<source>[^,\n]+), pid: (?P<pid>\d+), started: (?P<started>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}) ===$
```

### Body line

```
[<module>:<pid>] <verbatim stderr line>
```

- The `[<module>:<pid>] ` prefix is added by the framework, NOT by the subprocess.
- `<verbatim stderr line>` is the line as the subprocess wrote it, with the trailing `\n` already stripped by the reader (added back when written to `bridge.log`).
- If the subprocess writes a line longer than ~4 KB, it's still one body line (no wrapping).
- ANSI escape sequences in the stderr line are preserved verbatim (no stripping).
- A subprocess writing partial content without a newline at the time of kill: the partial content is flushed as a body line WITHOUT a `\n` only at the kill boundary (the footer line that follows starts on a new line via explicit `\n` prefix). See FR-008.

Regex (for parsing/test asserts):

```
^\[(?P<module>[\w-]+):(?P<pid>\d+)\] (?P<line>.*)$
```

### Footer line — success path

```
=== exit: <code>, duration: <s>s, payload_status: <verdict> ===
```

- `<code>` — Unix exit code as a non-negative integer (0-255).
- `<s>` — duration in seconds, fixed at 3 decimal places (e.g. `4.328`).
- `<verdict>` — one of `ok`, `empty`, `error` (matches `BridgePayloadVerdict` enum from spec 020).

Regex:

```
^=== exit: (?P<code>\d+), duration: (?P<duration>\d+\.\d{3})s, payload_status: (?P<verdict>ok|empty|error) ===$
```

### Footer line — KILLED path (FR-008)

```
=== KILLED BY FRAMEWORK (<reason>) after <s>s ===
```

- `<reason>` — one of: `wall-clock cap`, `dollar cap`, `manual interrupt`, `parent exit`.
- `<s>` — wall-clock seconds the subprocess ran before kill, 3 decimals.

Regex:

```
^=== KILLED BY FRAMEWORK \((?P<reason>wall-clock cap|dollar cap|manual interrupt|parent exit)\) after (?P<duration>\d+\.\d{3})s ===$
```

## Ordering invariants

1. Within a single extractor invocation, lines are always: 1 header → 0..N body lines → 1 footer.
2. Across invocations, headers/bodies/footers MAY interleave only if extractors run concurrently (rare in MVP — Wave-2 modules are sequential).
3. The `[<module>:<pid>] ` prefix is the canonical disambiguator. A parser MUST use it to associate a body line with its header, not assume body lines are contiguous to their header.
4. Each line is atomically written (under `BridgeLogWriter`'s lock). Partial lines never appear.

## Line-buffered guarantee (FR-007)

`tail -f bridge.log` MUST show new body lines within **2 seconds** of the subprocess's stderr write. The FR-015 regression test asserts this via:

```python
def test_bridge_log_is_line_buffered():
    # Sentinel extractor writes "LINE1", sleeps 1s, writes "LINE2", exits.
    # Background thread polls bridge.log every 100ms during the sleep window.
    # Assertion: "LINE1" is readable in bridge.log BEFORE the subprocess exits.
```

## Concurrency contract

- Single-process writers only. No file locking across `./vault` invocations (different cycles → different files).
- Multi-thread within process: `threading.Lock` serializes writes; lines are atomic but interleaved-extractor lines can appear out of order with respect to each other (still in stderr-emission order within a single extractor).
- `BridgeLogWriter.close()` MUST be idempotent — calling twice is a no-op.

## Example complete file

```
=== module: youtube, source: dQw4w9WgXcQ, pid: 47291, started: 2026-05-29T14:23:51.107 ===
[youtube:47291] yt-dlp: extracting metadata for dQw4w9WgXcQ
[youtube:47291] yt-dlp: downloading subtitle file (en, 142 KB)
[youtube:47291] yt-dlp: subtitle saved
=== exit: 0, duration: 4.328s, payload_status: ok ===
=== module: youtube, source: STUCK_VIDEO_ID, pid: 47330, started: 2026-05-29T14:24:03.901 ===
[youtube:47330] yt-dlp: extracting metadata for STUCK_VIDEO_ID
[youtube:47330] yt-dlp: ERROR: HTTP 429: rate limit exceeded, retrying in 60s
[youtube:47330] yt-dlp: ERROR: HTTP 429: rate limit exceeded, retrying in 60s
=== KILLED BY FRAMEWORK (wall-clock cap) after 300.000s ===
```

## Out of scope

- Compression/rotation/archival of `bridge.log`. (Per-cycle, naturally bounded.)
- Structured JSON-per-line format. (Plain text is the human-debugging surface; structured emissions are spec 028's sidecar telemetry job.)
- Cross-cycle search index. (`rg` is the search tool.)
