# Quickstart: Observability v1 MVP

**Audience**: Vault operators running `./vault research` (incl. unattended Feeds-Vault cycles).
**Status**: For the MVP cut (v1.0). The `vault status` verb described in spec FR-009/010/011 ships in v1.1.

---

## What lands in MVP

After this work merges to main, you get three new debugging surfaces:

1. **Logger output on stderr** — every framework module emits structured log records (timestamps, levels, module paths). Default: INFO when interactive, WARNING when piped.
2. **`--log-level` flag** — global flag on every subcommand; values: `debug` / `info` / `warning` / `error`.
3. **`bridge.log` per cycle** — verbatim stderr capture from every spec-020 extractor subprocess, framed with header/footer lines, line-buffered for live `tail -f`.

What's NOT in MVP (locked for v1.1):

- `vault status` verb — for now, watch `bridge.log` directly with `tail -f`.
- One-line cycle health header at the top of `cycle-NNN-summary.md` — for now, read the full summary report.

---

## How to use it

### Watching an unattended cycle live

Terminal A (kick off the cycle):

```bash
cd ~/Documents/feeds-vault
./vault research --cycles 5
# (terminal blocks for the full run; output is INFO-level by default)
```

Terminal B (watch progress in real time):

```bash
cd ~/Documents/feeds-vault
# Find the active cycle dir (highest cycle-NNN under _pipeline/cycles/)
ACTIVE_CYCLE=$(ls -1d _pipeline/cycles/cycle-* 2>/dev/null | tail -1)
tail -f "$ACTIVE_CYCLE/bridge.log"
```

You'll see real-time output like:

```
=== module: youtube, source: dQw4w9WgXcQ, pid: 47291, started: 2026-05-29T14:23:51.107 ===
[youtube:47291] yt-dlp: extracting metadata for dQw4w9WgXcQ
[youtube:47291] yt-dlp: downloading subtitle file (en, 142 KB)
[youtube:47291] yt-dlp: subtitle saved
=== exit: 0, duration: 4.328s, payload_status: ok ===
=== module: youtube, source: jNQXAC9IVRw, pid: 47330, started: 2026-05-29T14:24:03.901 ===
[youtube:47330] yt-dlp: extracting metadata for jNQXAC9IVRw
...
```

Lines appear within ~2 seconds of the subprocess emitting them (line-buffered, FR-007).

### Debugging a stuck extractor post-mortem

If a cycle was killed by the wall-clock backstop, the killed footer tells you exactly what happened:

```bash
$ tail -20 ~/Documents/feeds-vault/_pipeline/cycles/cycle-004/bridge.log
=== module: youtube, source: STUCK_VIDEO_ID, pid: 47291, started: 2026-05-29T14:23:51.107 ===
[youtube:47291] yt-dlp: extracting metadata for STUCK_VIDEO_ID
[youtube:47291] yt-dlp: ERROR: HTTP 429: rate limit exceeded, retrying in 60s
[youtube:47291] yt-dlp: ERROR: HTTP 429: rate limit exceeded, retrying in 60s
[youtube:47291] yt-dlp: ERROR: HTTP 429: rate limit exceeded, retrying in 60s
...
=== KILLED BY FRAMEWORK (wall-clock cap) after 300.0s ===
```

Root cause is visible at a glance. Today, without this surface, you'd have to re-run with `strace` or print-debugging.

### Dialing verbosity without code changes

More detail (cache decisions, dispatch reasoning, per-call timings):

```bash
./vault research --log-level debug --cycles 1
# expect ~10x more lines than default
```

Less noise (only warnings and errors):

```bash
./vault research --log-level warning --cycles 1
```

For unattended/cron usage, the framework auto-detects no-TTY and defaults to `warning`:

```bash
./vault research --cycles 1 > /tmp/cycle.log 2>&1
# stdout is not a TTY → default is WARNING (not INFO)
# stderr still emits all logger output
```

### Searching past cycles

`bridge.log` is per-cycle, so `rg` over the directory tree is the search interface:

```bash
# Find every yt-dlp rate-limit incident in the last 30 cycles
cd ~/Documents/feeds-vault/_pipeline/cycles
rg -l "rate limit exceeded" cycle-*/bridge.log

# How long did extractor invocations take on cycle 4?
rg "^=== exit:" cycle-004/bridge.log
```

---

## What the logger looks like

Default format (FR-001-pinned):

```
2026-05-29 14:23:51,107 [INFO] research_framework.pipeline.cycle_runner: cycle 3 / 5 starting
2026-05-29 14:23:51,892 [INFO] research_framework.pipeline.steps.scout: scout pass starting
2026-05-29 14:23:52,103 [DEBUG] research_framework.pipeline.steps.scout: cache hit for source youtube/VIDEO_ID
2026-05-29 14:24:14,003 [WARNING] research_framework.observability.bridge_log: extractor youtube exited non-zero (code=1)
2026-05-29 14:24:14,005 [INFO] research_framework.pipeline.cycle_runner: cycle 3 exit (status: pass)
```

The format is locked: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`. Module names are always the dotted Python path (`research_framework.<package>.<module>`).

---

## What you can't do yet (locked for v1.1)

- `./vault status --vault <path>` — would give you a 5-line summary without `tail -f`. Workaround in MVP: `ls -lh _pipeline/cycles/cycle-*/bridge.log | tail -3` and `tail -f` the last one.
- One-line cycle health header at the top of `cycle-NNN-summary.md` — would let you `head -1` the latest summary for a quick "did it pass?" check. Workaround: read the full summary report.

Both are locked for v1.1 in `spec.md` § Clarifications.

---

## How this interacts with existing artifacts

The MVP **adds** Tier 5 (logger) and Tier 6 (`bridge.log`) of the six-tier observability ladder. The other four tiers are unchanged:

| Tier | Surface | Status post-MVP |
|---|---|---|
| 1 | Sidecar telemetry (`_pipeline/cycles/.../agent-calls/*.json`) | Unchanged |
| 2 | Cycle summaries (`cycle-NNN-summary.md`) | Unchanged in MVP (line-1 header lands in v1.1) |
| 3 | Run-report skill output | Unchanged |
| 4 | `vault status` verb | NEW in v1.1 |
| 5 | Logger output on stderr | **NEW (MVP)** |
| 6 | `bridge.log` per-cycle | **NEW (MVP)** |

The full ladder, decision tree, and anti-patterns ship as a sibling doc: `docs/observability-strategy.md` (mirrors `docs/testing-strategy.md`).

---

## Troubleshooting

- **"I don't see any logger output, only the bridge.log."** → Check `--log-level` (default WARNING for non-TTY) or that you ran with a TTY. If both are correct, see FR-002: if `logging` was already configured by a parent process (e.g. `pytest` wrapping the CLI in tests), our `basicConfig` is intentionally skipped to avoid double-handlers.
- **"`tail -f bridge.log` shows nothing during a slow extractor."** → Verify the file exists (`ls -lh _pipeline/cycles/cycle-NNN/`). If empty during an active extractor, that's a regression — open an issue with the cycle number; FR-015 has a test that should have caught this.
- **"My script uses `python -m research_framework.cli` and gets no logger output."** → That's the supported entry point; check that no `> /dev/null` redirect is eating stderr (logger writes to stderr, not stdout).
- **"I want to disable the logger entirely."** → `./vault research --log-level error` is as quiet as it gets in MVP. There's no `--quiet` flag (use `error` instead). Full silencing is out of scope.

---

## Where the implementation lives

| Concern | File |
|---|---|
| `--log-level` flag definition + TTY-aware default | `src/research_framework/cli/_log_level.py` |
| `logging.basicConfig` invocation at CLI entry | `src/research_framework/cli/__main__.py` |
| `BridgeLogWriter` (file + lock + framing) | `src/research_framework/observability/bridge_log.py` |
| Per-extractor reader thread | `src/research_framework/observability/extractor_capture.py` |
| Cycle-level wiring (open/close `bridge.log`) | `src/research_framework/pipeline/cycle_runner.py` |
| Regression guard | `tests/observability/test_log_surfaces.py` |
| Sibling doc | `docs/observability-strategy.md` |
