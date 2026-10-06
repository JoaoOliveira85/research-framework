# Observability Strategy — Layered Ladder

**Status**: active (drafted 2026-05-29 as part of spec 048
Observability v1 MVP).
**Background (pre-0.5.0)**: Spec 048 surfaced the gap between this
framework's excellent **forensic** trail (sidecar telemetry, cycle
summaries, run-report) and its absent **runtime** surface. There was
no `logging.basicConfig()` anywhere, no global `--log-level` flag, and
the `bridge.log` referenced in spec 020's quickstart was stale (never
implemented). Tier 5 (runtime logger) and Tier 6 (subprocess audit)
existed only on paper. **All three were closed in 0.5.0** (spec 048
MVP cut) — see the FR-by-FR sections below for the as-shipped state.
**History**: `specs/048-observability-v1/spec.md` (the original draft
that motivated this doc; SHIPPED in v0.5.0).
**Decision record**: `docs/adr/0007-smoke-gate-mandatory.md` covers
why the smoke gate is non-skippable; spec 048 added Tier 5/6 to the
set it gates.

---

## Where this fits in the roadmap

Observability is the **sibling** of the Testing Strategy. They answer
two different questions:

- **Testing** (`docs/testing-strategy.md`): "Will this commit break a
  shipped feature?" Answered at CI/pre-merge time.
- **Observability** (this doc): "Why did the unattended cycle that
  ran overnight do _that_?" Answered at post-mortem time, while
  reading logs and sidecars.

Both use the same six-tier mental model — you walk **up** the ladder
when investigating an incident (cheap → expensive evidence) and
**down** when designing instrumentation (the lower tier you can
attach to, the cheaper it is to reason about).

### What spec 048 v1 MVP shipped

- **Tier 5 (runtime logger)**: `logging.basicConfig()` wired on CLI
  entry; global `--log-level {debug,info,warning,error}` flag;
  TTY-aware default (`info` interactive, `warning` piped); 111
  hot-path `print()` calls migrated to `_LOG.info/warning/error`.
- **Tier 6 (subprocess audit)**: per-cycle
  `<vault>/_pipeline/cycles/cycle-NNN/bridge.log` capturing extractor
  stderr verbatim, line-buffered, with header / `[<module>:<pid>]
  body` / success-or-KILLED footer framing per
  `specs/048-observability-v1/contracts/bridge-log-format.contract.md`.
- **Regression guard**: `tests/observability/test_log_surfaces.py`
  with 35 tests gating the five FR-015 surfaces.

### What spec 048 v1.1 shipped (2026-06-04)

- **`vault status` verb** (Tier 4): `vault status --vault <path> [--json]`
  reads extended `_pipeline/state.json`, tails the active cycle's
  `cycle.log`, and when idle replays the FR-013 health header from the
  last `cycle-NNN-summary.md`. Completes in <1s for ≤1000 cycles of
  history (bounded reads only).
- **One-line cycle-health header** (FR-013): line 1 of every
  `cycle-NNN-summary.md` — also consumed by `vault status` (FR-011) and
  spec 035's digest.
- **Per-cycle `cycle.log`** (Tier 5 file): framework `logger.*` output
  captured at `_pipeline/cycles/cycle-NNN/cycle.log` via a
  `FileHandler` attached for the cycle body. Distinct from Tier 6
  `bridge.log` (extractor stderr only).
- **Print allowlist** (FR-014): `tests/observability/print_allowlist.txt`
  + `test_log_surfaces.py::test_pipeline_print_allowlist_no_net_new_unlisted_prints`
  gate all remaining `print()` sites under `pipeline/`.

### What's deferred beyond v1.1

- External metrics push (Datadog/Prometheus), structured event
  tracing, real-time alerting — **explicitly out of scope** (v2
  horizon). See spec 048 v2 (Source-Consideration Ledger).

---

## TL;DR

When something looks wrong with an unattended cycle:

1. Read **Tier 1** (sidecar telemetry next to the note) for the
   single-event "what did this LLM call cost / decide?" answer.
2. Read **Tier 2** (`cycle-NNN-summary.md`) for the per-cycle
   "what shipped and what got rejected?" answer.
3. Read **Tier 3** (`run-report.md` at the vault root) for the
   "across all cycles, where is the campaign drifting?" answer.
4. Read **Tier 4** (`vault status`) for the "is the live
   cycle making forward progress _right now_?" answer — or tail the active
   cycle's **Tier 5 file** (`cycle.log`) for framework logger output.
5. Read **Tier 5** (logger output on stderr / `cycle.log`) for the "what
   did the Python code think at this exact wall-clock second?" answer.
6. Read **Tier 6** (`bridge.log` per cycle) for the "what did the
   `yt-dlp` / `arxiv-api` subprocess say verbatim?" answer.

If you're not sure which tier to reach for, **walk up from 1** — each
upper tier is more expensive to interpret but more granular.

---

## The six-tier ladder

| Tier | Name | Format | Lifetime | Location |
|------|------|--------|----------|----------|
| **1** | Sidecar telemetry | JSON per note | Permanent (git-tracked) | `<note>.sidecar.json` adjacent to each note |
| **2** | Cycle summary | Markdown | Permanent (git-tracked) | `_pipeline/cycles/cycle-NNN-summary.md` |
| **3** | Run report | Markdown | Permanent (git-tracked) | `<vault>/run-report.md` |
| **4** | `vault status` | CLI table (+ `--json`) | Live (regenerated on demand) | stdout |
| **5** | Logger output | Plain-text records | Live (stderr) + per-cycle `cycle.log` | `sys.stderr` / `_pipeline/cycles/cycle-NNN/cycle.log` |
| **6** | Subprocess audit | Framed plain text | Per-cycle artifact (git-tracked) | `_pipeline/cycles/cycle-NNN/bridge.log` |

### Tier 1 — Sidecar telemetry

**One JSON file per note**. Records what LLM call(s) produced the
note, with cost, latency, tier, model, retry count, verifier verdict,
and the exact prompt+response signature. Source of truth for
per-note forensics. Written by `cycle_runner.py` after each
note-writer + verifier pair.

**Reach for it when**: "Why did note _X_ get flagged?" "How much did
that one note cost?" "Did the verifier retry?"

### Tier 2 — Cycle summary

**One Markdown file per cycle**. Aggregates Tier-1 data into a
per-cycle digest: notes added/rejected, coverage delta, total cost,
wall-clock time, exit-decision reason. Written at cycle-end by
`pipeline/cycle_summary.py`.

**Reach for it when**: "What happened in cycle 12?" "Why did we exit
the loop?" "What did this cycle cost?"

### Tier 3 — Run report

**One Markdown file per campaign** (overwritten each `./vault
research` run). Cross-cycle view: coverage trajectory, cost burn
rate, source-quality scorecard, top open gaps. Written at end-of-run
by `pipeline/run_report.py`.

**Reach for it when**: "Is the campaign on-track?" "Where are we
spending money?" "Which sources are pulling weight?"

### Tier 4 — `vault status`

**On-demand CLI read** of the currently-executing cycle: cycle N of M,
stage name, elapsed time, budget remaining (wall + dollar), and the
most recent framework log line (from `cycle.log`). Plain-text by
default; `--json` for automation. Read-only; inherits global
`--log-level`. Implemented in spec 048 v1.1 (`cli/status.py`).

**Reach for it when**: "Is the unattended cycle hung?" "How close are
we to the budget cap?" "Which stage is it in?"

### Tier 5 — Logger output

**`research_framework.<module>` records** at the configured level.
During an active cycle, the same records are also tee'd to
`_pipeline/cycles/cycle-NNN/cycle.log` (spec 048 v1.1). `--log-level
debug` opens the firehose; `--log-level warning` silences pipeline
progress. Format pinned by
`specs/048-observability-v1/contracts/logger-wiring.contract.md`:

```
2026-05-29 12:34:56,789 [INFO] research_framework.pipeline.cycle_runner: message
```

TTY-aware default: interactive runs land at `INFO`, piped/CI runs at
`WARNING`. Override globally with `research-framework --log-level
debug research ...`.

**Reach for it when**: "Why is the framework doing _X_ right now?"
"What's the verifier seeing for batch 3?" Tail `cycle.log` during an
unattended run for a durable per-cycle logger file (complementary to
live stderr).

### Tier 6 — `bridge.log`

**One framed file per cycle** at
`<vault>/_pipeline/cycles/cycle-NNN/bridge.log`. Captures every
extractor-subprocess stderr line **verbatim**, line-buffered (so
`tail -f` shows live progress within ~100ms of the extractor
emitting), framed with a header (per-extractor invocation), `[
<module>:<pid> ] body` lines, and a footer (success with exit-code
or KILLED with reason).

**Reach for it when**: "Why did the `youtube` extractor hang?" "What
did `yt-dlp` say before the wall-clock cap killed it?" "Did the
extractor write to stderr at all before exiting?"

The line-buffered guarantee is the spec's value-prop: an operator
opens a second terminal during an unattended overnight cycle, runs
`tail -f $(ls -td <vault>/_pipeline/cycles/*/bridge.log | head -1)`,
and sees real-time per-extractor output without joining the cycle
process. Pinned by
`tests/observability/test_log_surfaces.py::test_bridge_log_is_line_buffered`.

---

## Decision tree — which tier do I reach for?

```
START: "Something looks wrong with my cycle."
  │
  ├─ Is the cycle still running?
  │     │
  │     ├─ Yes → start at Tier 4 (`vault status`) OR
  │     │       tail Tier 5 (`cycle.log`) / Tier 6 (`bridge.log`) for live signal.
  │     │
  │     └─ No  → start at Tier 2 (cycle summary). Read the exit
  │             reason. If unclear, drop to Tier 1 (sidecars) for
  │             per-note detail OR Tier 6 (bridge.log) for the
  │             subprocess that misbehaved.
  │
  ├─ Is it a "wrong content / wrong note" question?
  │     → Tier 1 (sidecar) first. Then Tier 5 (logger) for the
  │       verifier's internal commentary.
  │
  ├─ Is it a "cost / budget / pacing" question?
  │     → Tier 3 (run-report) for the campaign view, then Tier 2
  │       (cycle summary) for the offending cycle.
  │
  ├─ Is it a "the subprocess died / hung" question?
  │     → Tier 6 (bridge.log) — the framing tells you the reason.
  │       KILLED footers carry an enum value
  │       (wall-clock cap / dollar cap / manual interrupt / parent exit).
  │       If bridge.log is empty, drop to Tier 5 (logger output) —
  │       the framework may have failed to spawn the subprocess at all.
  │
  └─ Is it a "framework code behavior" question?
        → Tier 5 (logger output). Re-run with `--log-level debug` to
          see internal state transitions.
```

---

## Anti-patterns

### "I'll just add a `print()` — it's just one line"

A `print()` ignores `--log-level`, can't be captured by `caplog` in
tests, doesn't carry a level/module/timestamp, and accumulates. The
`tests/observability/test_log_surfaces.py::test_no_net_new_print_in_hot_path_files`
regression guard fails the build if any of the 7 hot-path files
re-introduces one. **Use `_LOG.info/warning/error()`**. The cost is
literally one line per file (the module-level `_LOG =
logging.getLogger(__name__)`).

### "f-strings in log calls are fine"

Functionally true — the eager-evaluation cost is usually negligible.
But the standard-library style is lazy formatting (`_LOG.info("foo
%s", bar)`), which lets log filters skip the format work when the
record won't be emitted. ruff's `G004` rule (not currently enabled
in this repo) would catch this. Spec 048 MVP did NOT chase
f-string-to-`%s` conversion mechanically — it left existing styles
intact and only required the function-call name change. v1.1 may
tighten.

### "I'll add a separate `_log.txt` file for my module"

There's already a tier for that — **Tier 6 `bridge.log`** for
subprocess audit, **Tier 5 logger** for in-process code. Adding a
third surface fragments the operator's mental model. If you genuinely
need a new on-disk artifact (e.g. a "consensus deliberation transcript"
for spec 020 modules), thread it through the existing per-cycle
directory (`_pipeline/cycles/cycle-NNN/`) and document it in the spec.

### "logger.disable() in tests / `caplog` will swallow it"

`logging.disable()` is global state with no rollback. Tests that need
to silence specific loggers should use `caplog.set_level()` or the
`reset_root_logger` fixture pattern from
`tests/observability/conftest.py`. Spec 048's
`test_basicconfig_called_once_per_process` test would fail if a
prior test left the root logger in an unexpected state.

### "I'll write to `sys.stderr` directly — it's simpler"

`sys.stderr.write()` bypasses the level filter, the format string,
and the test capture machinery. Same penalty as `print()`. Use
the logger.

### "It's a fatal error — I'll raise + print the traceback"

`raise` already emits the traceback to stderr via the Python
runtime; layering a manual print on top duplicates the noise. If you
want context **before** the raise, use `_LOG.error("context: %s",
detail)` then `raise`.

---

## Composition with the spec 022 quality harness

The quality harness (spec 022, SHIPPED 0.3.0) runs **6 vault fixtures
through full cycles** at e2e tier and asserts metric-level invariants
(coverage growth, note quality, cycle health, source quality). It is
the **functional** acceptance gate — does the system produce
acceptable vaults?

Observability is the **debugging** gate — when the quality harness
fails, what did the cycle actually do? The harness output points you
at a failing fixture+cycle; you then walk the six-tier ladder of
that fixture's vault to find out why.

In practice:
- Harness fail → grep `cycle-NNN-summary.md` (Tier 2) for the exit
  reason.
- Cycle-summary says "extractor crashed" → open `bridge.log` (Tier 6)
  for that cycle for the verbatim subprocess stderr.
- Cycle-summary says "verifier rejected note X" → open `<note
  X>.sidecar.json` (Tier 1) for the verifier's verdict + retry
  history.

Spec 048's MVP makes this loop possible. Before spec 048, an extractor
crash was opaque (no `bridge.log`); now it's transparent.

---

## Regression discipline

Every shipped observability bug fix MUST link a regression test in
`tests/observability/test_log_surfaces.py` (or a sibling test file
under `tests/observability/`) that:

1. **Reproduces the bug** by name in the docstring (cycle number /
   spec / commit SHA of the fix).
2. **Fails BEFORE the fix lands** (verify by checking out the
   pre-fix commit and running the test).
3. **Passes AFTER the fix lands** (the fix commit and the test land
   together).

This mirrors the testing-strategy.md regression-discipline convention.
The five FR-015 surfaces are the load-bearing test names:

- `test_basicconfig_called_once_per_process` (root-logger config)
- `test_log_record_format_pinned` (logger format)
- `test_cycle_runner_creates_bridge_log_at_cycle_start` (bridge.log
  creation)
- `test_bridge_log_is_line_buffered` (line-buffered guarantee)
- `test_no_net_new_print_in_hot_path_files` (print baseline)

`test_fr015_checks_a_through_e_present` is the meta-test that fails
loudly if any of these get renamed or deleted. Do **not** rename
these without a new spec amendment.

---

## How to run each tier

| Tier | Inspection command |
|------|--------------------|
| 1 | `cat <vault>/<note>.sidecar.json \| jq` |
| 2 | `cat <vault>/_pipeline/cycles/cycle-NNN-summary.md` |
| 3 | `cat <vault>/run-report.md` |
| 4 | `research-framework vault status <vault>` _(v1.1)_ |
| 5 | `research-framework --log-level debug research <vault>` (live) OR `grep '<module>' <pipe>` (captured) |
| 6 | `tail -f <vault>/_pipeline/cycles/cycle-NNN/bridge.log` (live) OR `cat ...` (post-mortem) |

---

## Pointers

- Spec: `specs/048-observability-v1/spec.md`
- Plan: `specs/048-observability-v1/plan.md`
- Contracts: `specs/048-observability-v1/contracts/`
  (`log-level-flag.contract.md`, `bridge-log-format.contract.md`,
  `logger-wiring.contract.md`)
- Regression suite: `tests/observability/test_log_surfaces.py`
- Quickstart for operators:
  `specs/048-observability-v1/quickstart.md`
- Sibling doc: `docs/testing-strategy.md` (the question on
  pre-merge time).
