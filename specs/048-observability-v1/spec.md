# Feature Specification: Observability v1 — Runtime Logging, Live Status, and Subprocess Audit

**Feature Branch**: `048-observability-v1`
**Created**: 2026-05-29 (sibling to spec 018 testing-strategy; gap surfaced while planning the Feeds-Vault manual cycle and discovering the framework has no runtime logger wiring).
**Status**: shipped(2026-05-29, version 0.5.0) — SHIPPED 0.5.0 (2026-05-29, MVP cut). MVP cut = FR-001..008, FR-012, FR-015/016. **v1.1 SHIPPED 0.10.0** (PR #110, 2026-06-04) = FR-009/010/011 (`vault status`), FR-013/014 (cycle-health header, print allowlist) + backing `state.json` / `cycle.log`. **v2 scope SHIPPED 0.9.0** (PR #98, 2026-06-03): Source-Consideration Ledger (FR-017..021) — see "v2 scope" section below. **v2.1 amendment SHIPPED 1.0.0rc3 (2026-06-06, PR #126)**: ledger↔citation reconciliation (FR-022..024, defect 3.4; `LEDGER_DISAGREEMENT` + `read_via`, schema 1.1) — see "v2.1 amendment" at end of file.

**Input**: User description: "Observability v1 — runtime logging surface, live cycle visibility, and stderr capture from source-module extractors. Goal: make the framework debuggable during unattended feeds-vault cycles. Today the structured forensic trail (sidecar telemetry, cycle summaries, run-report) is excellent, but Tier 5 (runtime logs via Python `logging`) and Tier 6 (subprocess audit via `bridge.log`) are gaps — there's no `logging.basicConfig()` anywhere, no global `--log-level` flag on the CLI, and `bridge.log` mentioned in `specs/020-code-bridge/quickstart-module-author.md` is stale (not implemented). Sibling to the testing strategy: ship a `docs/observability-strategy.md` doc and Spec 048 (this spec) covering FRs for: global `--log-level {debug,info,warning,error}` flag, `logging.basicConfig` wiring on CLI entry, per-cycle `bridge.log` capturing all extractor stderr verbatim, migration of pipeline `print()` calls to `logger.info()`, and a `vault status` verb for live progress."

## Why this spec exists

The framework is excellent at producing **forensic** artifacts after a cycle completes — sidecar telemetry (spec 028), per-cycle summary reports, the run-report skill, and the cycle-NNN-quality-report.json all answer "what happened?" after the fact. But during an **unattended** Feeds-Vault cycle (the primary use case), the operator needs three things the framework does not provide today:

1. **Live visibility** — watching the cycle progress in real time, not just postmortem.
2. **Subprocess audit** — capturing stderr from spec-020 extractor subprocesses so a stuck or crashing module can be diagnosed.
3. **Verbosity control** — dialing logging up/down without code changes.

Concretely, three gaps were confirmed during this spec's drafting (2026-05-29):

- **Zero** calls to `logging.basicConfig()` exist in `src/research_framework/` (the root logger is unconfigured; any `logger.info()` call today is silently dropped unless the consumer wires up logging themselves).
- The `bridge.log` file mentioned in `specs/020-code-bridge/quickstart-module-author.md` is **never written** — the reference is stale documentation; extractor stderr is currently captured only into the `last_error` field of the SignalPayload on failure, with no streaming and no successful-call trail.
- **~125 `print()` calls** live in `src/research_framework/pipeline/` (counted via `rg "^\s*print\("`). They are the only runtime visibility surface today and they bypass the logger entirely — meaning a CI-redirected run or a piped invocation either floods stdout indiscriminately or drops the lines.

This spec ships the missing runtime surface; a sibling deliverable `docs/observability-strategy.md` (modeled on `docs/testing-strategy.md`) frames the broader tier ladder.

## Clarifications

### Session 2026-05-29

- **Q: (FR-006 / FR-007 stderr buffering policy)** Should `bridge.log` capture extractor stderr line-buffered (real-time, visible via `tail -f` during slow extractor calls) or block-buffered until subprocess exit (simpler, but `tail -f` shows nothing)? **A: Line-buffered.** `subprocess.Popen(..., stderr=subprocess.PIPE, bufsize=1, universal_newlines=True)` + a non-blocking reader thread per active extractor. The ~30 lines of orchestration code is a one-time cost; the alternative would silently invalidate US1's primary value (live watching). FR-007 updated to be explicit.

### Deferred to v1.1 (locked-but-not-implemented in this MVP cut)

The MVP scope (this session) ships FR-001/002/003/004/005/006/007/008/012/015/016 only — logger wiring + `--log-level` flag + per-cycle `bridge.log` + hot-path `print()` migration + regression guard. The following clarifications still have proposed defaults locked so v1.1 can implement them without re-litigating:

- **Q2 (FR-009 `vault status` output format)** — **Deferred** because the `vault status` verb itself is deferred to v1.1. **Locked default for v1.1**: plain-text by default + `--json` flag. JSON output stabilizes the contract for future automation; plain-text serves the human first-touch case. Two output paths is the cost of the best UX.
- **Q3 (FR-012 `print()` migration scope)** — **Resolved by MVP scope choice**: MVP is hot-path-only by definition (cycle_runner, orchestrator, runner, steps/scout, steps/research, steps/postprocess, source_bridge/orchestrator — ~80 of the ~125 pipeline `print()` calls). The ~45 non-hot-path call sites stay un-migrated in MVP **and are NOT yet in the FR-014 allowlist** — FR-014's allowlist convention itself is deferred to v1.1 (when the one-line health header and `vault status` verb also ship). For MVP, the regression test in FR-015 only enforces no NET-NEW `print()` calls in the hot-path scope.

### v1.1 clarified (Session 2026-06-03) — fleshed to implement-ready

The v1.1 FRs (FR-009/010/011/013/014) are now fully planned in the `*-v1.1.*` artifacts. Four implementation forks were resolved against a 2026-06-03 code audit:

- **CL-1 (FR-010 live-status source)** → **extend `_pipeline/state.json`** (today only `{in_progress_cycle}`, written at `cycle_runner.py:263`) with `stage` + `cycle_started_at` + `budget_snapshot`, written at each stage transition — one cheap read keeps `vault status` <1s.
- **CL-2 (FR-010 "tail of the cycle log")** → v1.0 logs to stderr with **no per-cycle log file**, so **add a per-cycle `cycle.log` `FileHandler`** under `cycle-NNN/` to tail; complements `bridge.log` (extractor stderr).
- **CL-3 (FR-009 verb placement)** → a **new first-class `status` verb**, distinct from the existing phase-level `pipeline status`.
- **CL-4 (FR-014 enforcement + scope)** → the "~45 non-hot-path prints" estimate is **stale (only ~13 remain in `pipeline/`)**; enforce via a **count-based test over all of `pipeline/` + a `# noqa: T201`-documented allowlist** (no ruff `T20` change).

Artifacts: [research-v1.1.md](./research-v1.1.md) (decisions D1-D4) · [plan-v1.1.md](./plan-v1.1.md) · [contracts/vault-status-v1.1.contract.md](./contracts/vault-status-v1.1.contract.md) · [tasks-v1.1.md](./tasks-v1.1.md) · [checklists/requirements-v1.1.md](./checklists/requirements-v1.1.md).

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Watch an unattended cycle live (Priority: P1)

The operator kicks off `./vault research --cycles 5` on the Feeds-Vault and walks away. They come back two hours later, open a second terminal, and run `tail -f ~/Documents/feeds-vault/_pipeline/cycles/cycle-003/bridge.log` — they see the YouTube extractor mid-call, can confirm yt-dlp is actually downloading the subtitle file, and trust the cycle is making progress. They also run `vault status --vault ~/Documents/feeds-vault` and see a 5-line summary: cycle 3 of 5, current stage (research), elapsed (47 min), wall-clock budget remaining (1h 13m), last `logger.info()` line.

**Why this priority**: This is the actual unblocker for the manual Feeds-Vault run. Without it, the operator either babysits the terminal for the full 5-cycle duration (10+ hours) or accepts that any hang is undetectable until exit-code time. The cycle's exit status is currently the only liveness signal — a stuck yt-dlp call is invisible.

**Independent Test**: Trigger a cycle with a deliberately slow extractor (mocked yt-dlp that `sleep 60`). Verify: (a) `bridge.log` shows extractor activity within 2 seconds of subprocess start; (b) `vault status` returns within 1 second and includes the active stage name; (c) when the cycle finishes, both surfaces remain readable and consistent with the cycle summary.

**Acceptance Scenarios**:

1. **Given** a cycle is mid-run with an active extractor subprocess, **When** the operator opens `tail -f bridge.log`, **Then** new stderr lines appear in real time (≤2s buffering), each tagged with module name + timestamp.
2. **Given** a cycle is mid-run, **When** the operator runs `vault status --vault <path>`, **Then** the output completes in <1s and shows the current stage, elapsed, budget remaining, cycle number, and the most recent `logger.info()` line.
3. **Given** the framework is started fresh (no logging config in the process), **When** the CLI entry point runs, **Then** `logging.basicConfig()` is wired with a sane default level (per Q4-from-/specify: TTY-aware — info when interactive, warning when piped) and stage transitions emit `logger.info()` calls that reach stdout.

---

### User Story 2 — Debug a stuck extractor post-mortem (Priority: P1)

A nightly Feeds-Vault cycle hangs and gets killed by the wall-clock backstop. In the morning the operator opens `_pipeline/cycles/cycle-004/bridge.log` and reads the verbatim stderr of every spec-020 extractor invocation that ran during cycle 4. They see the YouTube module spent 47 minutes waiting on a yt-dlp HTTPS handshake to a transcript URL — the underlying API rate-limited them. Root cause identified in <2 minutes; today the same diagnosis takes a stderr `print` debug session.

**Why this priority**: Spec 020's subprocess isolation buys correctness (extractor crashes can't take down the framework) but DESTROYS visibility — stderr is currently swallowed except for the `last_error` truncation on failure. `bridge.log` is the Tier 6 audit surface. Without it, every extractor failure becomes a re-run-with-strace exercise. P1 because spec-020 is the foundation of Wave-2 modules; observability for that foundation is non-optional.

**Independent Test**: Run a cycle where the YouTube extractor mock writes "STAGE A", "STAGE B", "STAGE C" to stderr then exits with code 1. Read `_pipeline/cycles/cycle-NNN/bridge.log`. Verify: all three lines appear verbatim, in order, each tagged with module name + PID + timestamp; the SignalPayload's `last_error` field also contains the last line for downstream summarization.

**Acceptance Scenarios**:

1. **Given** an extractor writes N lines to stderr during a call, **When** the call completes (success OR failure), **Then** all N lines appear in `_pipeline/cycles/cycle-NNN/bridge.log` verbatim with module-name + PID + timestamp framing.
2. **Given** a cycle ran 3 extractor calls (2 success, 1 failure), **When** the operator inspects `bridge.log`, **Then** all 3 calls are present, framed by a header line ("=== module: youtube, source: VIDEO_ID, pid: 12345, started: <ts> ===") and a footer line with exit code + duration.
3. **Given** the cycle is killed mid-extractor by the wall-clock backstop, **When** the operator reads `bridge.log` post-mortem, **Then** the partial stderr of the killed subprocess is preserved (line-buffered per Q1 default) plus a "KILLED BY FRAMEWORK (wall-clock cap)" footer.

---

### User Story 3 — Dial verbosity without code changes (Priority: P2)

A user reports their cycle "feels slow" but the cycle summary doesn't reveal a stage bottleneck. The operator re-runs with `./vault research --log-level debug` and gets the full timing trace, agent-call boundary breadcrumbs, prompt-cache hit/miss decisions, and per-module dispatch reasoning — all at debug level. They identify the culprit (an unexpected cache miss in the scout stage) and re-run at default verbosity. No code change required.

**Why this priority**: Verbosity is the universal escape hatch. Today the only way to "turn up the volume" is to drop `print()` statements into the source. A `--log-level` flag closes the gap. P2 because US1+US2 give us the *content* of the logs; US3 controls the *volume*. Useful but secondary.

**Independent Test**: Run the same cycle twice with `--log-level warning` vs `--log-level debug` and count output lines. Verify: debug produces ≥10x more lines (cache decisions, dispatch reasoning, agent-call boundaries) than warning; warning produces only stage start/end + actionable warnings; both runs produce the same exit code + cycle summary.

**Acceptance Scenarios**:

1. **Given** `./vault research --log-level debug`, **When** the cycle runs, **Then** the root logger level is set to DEBUG and every `logger.debug()` call in the pipeline reaches stdout.
2. **Given** `./vault research --log-level warning`, **When** the cycle runs, **Then** stage-transition `logger.info()` calls are suppressed; only warnings and errors reach stdout; cycle still produces normal artifacts.
3. **Given** `./vault research` (no flag), **When** stdout is a TTY, **Then** the root level defaults to INFO (loud-by-default for interactive runs); **When** stdout is piped or redirected, **Then** the root level defaults to WARNING (quiet-by-default for CI/non-interactive — per Q4-from-/specify: TTY-aware).

---

### User Story 4 — One-line cycle health summary (Priority: P3)

After every cycle, `cycle-NNN-summary.md` includes a one-line health header at the top: `CYCLE 003: PASS | 47 notes drafted, 41 verifier-passed | $1.83 spent, $2.50 budget | 1h 12m elapsed | 0 errors, 2 warnings`. The cross-cycle digest (spec 035) concatenates these one-liners into a weekly trend ("Week of 2026-05-25: 5 cycles, 4 pass, 1 warn; $7.40 spent; trending down 12% from prior week"). The line is also what `vault status` prints when no cycle is active.

**Why this priority**: Operational polish — the one-liner is what the operator scans to know "did the cycle go well?" at a glance. Today they have to read the full summary report to find that out. P3 because the same information is *retrievable* today; it's just not surfaced concisely.

**Independent Test**: Run a cycle; verify `cycle-NNN-summary.md` line 1 matches the format above; verify the same line appears in `vault status` output when invoked between cycles. Trigger a warning (e.g. mid-cycle budget reweight); verify the one-liner reflects "warnings: N" correctly.

**Acceptance Scenarios**:

1. **Given** a cycle completes successfully, **When** the cycle-summary report is generated, **Then** line 1 is the one-line health header in the format above (status, note counts, $$, elapsed, errors, warnings).
2. **Given** spec 035's cross-cycle digest aggregates summaries, **When** it renders the week's section, **Then** each cycle's one-line header is included verbatim and a 1-line trend summary follows.

---

### User Story 5 — Regression guard against silent log drops (Priority: P2)

A future refactor accidentally adds `logging.disable()` to the bootstrap path (or breaks the bridge.log writer by introducing a buffering bug). A new test in `tests/observability/test_log_surfaces.py` fails immediately: "expected ≥N log lines from a sentinel cycle, got 0" or "expected stderr in bridge.log, got empty file". The regression is caught in pre-commit, not in production.

**Why this priority**: Observability silently breaking is the worst failure mode — the operator doesn't know they've lost visibility until they need it. P2 because the regression guard is the *meta-feature* — without it, US1-US4 will degrade over time. P2 not P1 because US1-US2 deliver value the day they ship; the regression guard pays dividends over months.

**Independent Test**: Patch out `logging.basicConfig` in a copy of the framework; run the regression suite. Verify: the new tier-5 regression test fails with a clear message naming the lost surface (logger / bridge.log / vault-status / one-liner). Restore the function; verify the test passes.

**Acceptance Scenarios**:

1. **Given** a fresh CI run, **When** the regression suite runs, **Then** `tests/observability/test_log_surfaces.py` runs and verifies (a) the root logger is configured after CLI entry, (b) a sentinel `logger.info()` reaches stdout, (c) `bridge.log` is created and non-empty when a sentinel extractor is called, (d) `vault status` returns within 1s.
2. **Given** any of the four observability surfaces silently breaks, **When** the regression suite runs, **Then** the test fails naming the specific broken surface with a remediation hint.

---

### Edge Cases

- **No active cycle when `vault status` runs**: Output the last completed cycle's one-line header (FR-009) plus an "(no active cycle)" line; exit 0.
- **Multiple cycles running concurrently** (e.g. two terminals against two vaults): Each `bridge.log` lives under its own vault's `_pipeline/cycles/cycle-NNN/`; no cross-contamination. `vault status` requires `--vault <path>` (no global default — fail fast with a clear error).
- **`bridge.log` is huge** (extractor logged 200 MB to stderr): No rotation in v1 (per Q3-from-/specify: per-cycle, self-bounded). Document the upper-bound expectation; spec 037-style sandboxing already caps extractor wall-clock at 5 min, naturally bounding stderr volume.
- **Operator passes `--log-level INVALID`**: Reject with a clear error listing the four allowed values; exit 2 (CLI usage error).
- **`logging` already configured by a parent process** (e.g. `pytest` itself, or a wrapping script): Detect via `len(logging.root.handlers) > 0` and skip the framework's `basicConfig` to avoid double-configuration. Document this in `docs/observability-strategy.md`.
- **The 80-print allowlist for hot-path migration drifts** (per Q3 default): The regression test in FR-015 reads the allowlist and re-counts; any net-new `print()` outside the allowlist fails the test with a "use `logger.info()` instead" message.
- **`vault status` invoked during the first second of cycle 1** (before any state.json write): Show "(starting)" with the elapsed timer + budget; do not crash.

## Requirements *(mandatory)*

### MVP scope cut (2026-05-29)

This /clarify session locked the spec in two halves so observability-v1 can ship in two PRs without re-litigating decisions:

| Cut | FRs | Stories | Ships when |
|---|---|---|---|
| **MVP (v1.0)** — this work | FR-001, FR-002, FR-003, FR-004, FR-005, FR-006, FR-007, FR-008, FR-012, FR-015, FR-016 | US1 + US2 + US3 + US5 (live watch, debug, dial, regression guard) | **NOW** — unblocks the Feeds-Vault manual cycle |
| **v1.1 (deferred)** — locked, not implemented | FR-009, FR-010, FR-011, FR-013, FR-014 | US4 (one-line health header) + the polished half of US1 (`vault status` verb) | After MVP merges to main; PR-B during Wave-2 |

Rationale: shipping the logger + `bridge.log` + hot-path `print()` migration FIRST makes downstream Wave-2 module work debuggable from day 1. `vault status` and the one-line health header are polish that can land concurrently with Wave-2 without blocking it. Q2 (vault status output format) and the FR-014 allowlist convention are deferred-but-locked — see Clarifications.

### Functional Requirements

#### Logger wiring (root configuration) — MVP



- **FR-001**: The CLI entry point (`research_framework.cli:main` or equivalent) MUST call `logging.basicConfig()` exactly once at process start, BEFORE any pipeline code runs. Format: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`. Stream: `sys.stderr`. Level: derived from FR-004 logic.
- **FR-002**: The framework MUST detect when logging is already configured (`len(logging.root.handlers) > 0` at entry) and skip `basicConfig` in that case to avoid double-configuration when invoked from a parent process (e.g. pytest).
- **FR-003**: Every module that emits logs MUST use `logger = logging.getLogger(__name__)` (no use of the root logger directly); module-level logger names must be the dotted Python path so operators can filter via `--log-level` or future per-module config.

#### CLI flag — MVP

- **FR-004**: A global `--log-level {debug,info,warning,error}` flag MUST be added to the CLI (applies to ALL subcommands: `research`, `status`, `health`, `update`, `regenerate`). When the flag is passed, it overrides the default from FR-005.
- **FR-005**: When `--log-level` is NOT passed, the default MUST be TTY-aware (per /specify Q&A): `INFO` if `sys.stdout.isatty()` is true (interactive run); `WARNING` otherwise (piped/redirected/CI). The detection happens once at startup and is logged at DEBUG level for diagnostics.

#### Per-cycle `bridge.log` — MVP

- **FR-006**: For every cycle, the framework MUST create `<vault>/_pipeline/cycles/cycle-NNN/bridge.log` (creating the directory if needed) and write to it for the duration of the cycle. Format: one log file per cycle (per /specify Q&A — self-bounded, no rotation).
- **FR-007**: For every spec-020 extractor invocation, the framework MUST capture the subprocess's stderr stream **line-buffered** (resolved 2026-05-29 — see Clarifications) and append each line to `bridge.log` as it arrives. Implementation: `subprocess.Popen(..., stderr=subprocess.PIPE, bufsize=1, universal_newlines=True)` plus a non-blocking reader thread per active extractor that drains `proc.stderr` line-by-line into the framing. Framing: a header line (`=== module: <name>, source: <id>, pid: <pid>, started: <iso-ts> ===`), the verbatim stderr lines (each prefixed with `[<module>:<pid>] ` for disambiguation when multiple extractors are interleaved), and a footer line (`=== exit: <code>, duration: <s>s, payload_status: <verdict> ===`). `tail -f bridge.log` MUST show new lines within 2 seconds of the subprocess emitting them.
- **FR-008**: When an extractor is killed by the framework (wall-clock cap, manual interrupt), the reader thread MUST drain any remaining buffered stderr before the footer is written, and the footer MUST read `=== KILLED BY FRAMEWORK (<reason>) after <s>s ===`. Any partial stderr captured up to the kill point MUST be retained.

#### `vault status` verb — **DEFERRED to v1.1** (locked, not implemented in MVP)

- **FR-009** *(v1.1)*: A new CLI verb `vault status --vault <path>` MUST be added. Output format: plain-text by default (5-line summary) with a `--json` flag for machine-friendly output. The plain output MUST complete in <1 second for a vault with up to 1000 cycles of history.
- **FR-010** *(v1.1)*: When a cycle is ACTIVE, `vault status` MUST report: (1) cycle number + total budgeted, (2) current stage name (read from `_pipeline/state.json`), (3) elapsed since cycle start, (4) budget remaining (wall-clock and dollar), (5) most recent `logger.info()` line (read from a tail of the cycle log).
- **FR-011** *(v1.1)*: When NO cycle is active, `vault status` MUST report: (1) "(no active cycle)" plus the one-line health header from the last completed cycle (FR-013), (2) days since last successful cycle, (3) any deferred warnings from the last cycle.

#### `print()` migration — MVP (hot-path only)

- **FR-012**: Hot-path `print()` calls in `src/research_framework/pipeline/` MUST be migrated to `logger.info()` (or `logger.warning()` where the message is an actionable user warning). Hot-path scope: `cycle_runner.py`, `orchestrator.py`, `runner.py`, `steps/scout.py`, `steps/research.py`, `steps/postprocess.py`, `source_bridge/orchestrator.py` (~80 calls per `rg` count on 2026-05-29). The remaining ~45 non-hot-path call sites stay untouched in MVP; their migration + allowlist convention land in v1.1 (FR-014).
- **FR-013** *(v1.1)*: A one-line cycle health header MUST be written as line 1 of every `cycle-NNN-summary.md` in the format: `CYCLE <N>: <STATUS> | <notes_drafted> notes drafted, <verifier_passed> verifier-passed | $<spent> spent, $<budget> budget | <elapsed> elapsed | <errors> errors, <warnings> warnings`. The same line is read by spec 035's digest and `vault status` (FR-011).
- **FR-014** *(v1.1)*: For `print()` call sites EXPLICITLY NOT migrated to logger (the ~45 non-hot-path occurrences), each MUST receive a `# noqa: T201 — keep raw print: <reason>` comment AND be added to the v1.1 follow-up entry in `docs/TODO.md`. The reasons are constrained to a known set: `interactive prompt`, `test-mode signal`, `CLI usage error`, `final report stdout contract`.

#### Regression guard — MVP (scoped to MVP surfaces only)

- **FR-015**: A new test file `tests/observability/test_log_surfaces.py` MUST verify (in a sentinel fixture cycle): (a) the root logger is configured post-CLI-entry; (b) a sentinel `logger.info()` reaches captured stderr; (c) `bridge.log` is created and non-empty when an extractor is invoked; (d) the line-buffered guarantee (FR-007) is honored — an extractor that writes "LINE1\n", sleeps 1s, writes "LINE2\n", exits, results in both lines being readable in `bridge.log` BEFORE the subprocess exits (validated by a thread that polls the file during the sleep window); (e) **MVP scope**: no NET-NEW `print()` calls are added to the hot-path scope from FR-012 (compared to a snapshot baseline captured at MVP-merge time). The v1.1 expansion (full allowlist enforcement of all ~125 sites, plus `vault status` <1s sentinel) lands when FR-009/010/011/014 ship.
- **FR-016**: The test in FR-015 MUST run as part of the default `pytest -m "not e2e"` collection (no special markers), and MUST be in the smoke-gate set executed by `./build.sh` (per ADR-0007).

### Key Entities

- **Root logger**: Configured once at CLI entry per FR-001/002; default-level governed by FR-004/005.
- **Per-cycle `bridge.log` file**: New artifact at `<vault>/_pipeline/cycles/cycle-NNN/bridge.log`; framed entries per FR-007/008.
- **`vault status` verb**: New CLI surface; reads `_pipeline/state.json` + last cycle's summary + last log tail per FR-009/010/011.
- **One-line cycle health header**: New convention for `cycle-NNN-summary.md` line 1 per FR-013; consumed by FR-011 and spec 035's digest.
- **`print()`-allowlist**: Documented set of intentionally-not-migrated `print()` sites per FR-014; enforced by FR-015's test.
- **`docs/observability-strategy.md` (sibling deliverable, NOT part of this spec's code)**: Mirrors `docs/testing-strategy.md`'s structure (Where this fits, TL;DR, Tier ladder, Decision tree, Anti-patterns). Documents the 6-tier observability ladder (sidecar telemetry, cycle summaries, run-report, `vault status`, logger output, `bridge.log`) and when to reach for each. Lands in the same PR as the FR-001..FR-016 implementation but is a doc not a code change.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After this spec ships, the Feeds-Vault manual cycle (Wave-3 readiness item) is unblocked: an operator can start the cycle and walk away with the certainty that ANY hang or anomaly produces a recoverable forensic trail in `bridge.log` + logger output.
- **SC-002**: Across the smoke-gate suite, 100% of extractor stderr lines (counted in a sentinel test) appear in `bridge.log` — zero silent drops.
- **SC-003**: `vault status` completes in <1s on a 100-cycle vault, measured by the regression test in FR-015.
- **SC-004**: Running the same fixture cycle at `--log-level debug` produces ≥10x the line count of the same cycle at `--log-level warning` (verifiable measurement of the dial actually working).
- **SC-005**: Zero new `print()` calls land in hot-path modules after this ships, enforced by the FR-014/015 allowlist test (no opt-outs without explicit `# noqa` + justified reason).
- **SC-006**: `docs/observability-strategy.md` is referenced as the canonical entry point for "how do I debug a stuck cycle?" in `CONTRIBUTING.md`, `CLAUDE.md`, and the operator-facing parts of `README.md`.

## Assumptions

- Python's stdlib `logging` module is sufficient (no `structlog` or other dep — Principle V: no new runtime dependencies).
- `sys.stdout.isatty()` is a reliable enough signal for the TTY-aware default (FR-005). Edge cases (e.g. pseudo-TTYs in containers) are acceptable false-positives and can be overridden via `--log-level`.
- Per-cycle `bridge.log` is acceptable forensic granularity (per Q3 from /specify Q&A — operator can `tail -f` the current cycle's file; cross-cycle search via `rg` on the parent directory).
- Operators want one-line cycle health headers (FR-013) over a more verbose default — concise scannability beats completeness.
- The ~125 `print()` count from `src/research_framework/pipeline/` is approximately stable; small additions in unrelated PRs between /specify and /tasks are acceptable (the allowlist will be re-counted during /plan).
- TTY detection happens once at startup; the framework does NOT dynamically re-evaluate mid-cycle if redirected (which is fine — the run is committed to one mode for its lifetime).
- `docs/observability-strategy.md` mirrors `docs/testing-strategy.md`'s house style (the user explicitly cited that doc as the prior-art reference).

## Dependencies

- **Soft**: Spec 018 (testing strategy) — `docs/observability-strategy.md` is its sibling and mirrors its structure.
- **Soft**: Spec 020 (source-bridge / code module architecture) — `bridge.log` lives at the spec-020 boundary; the FR-007 capture happens in the orchestrator's subprocess driver.
- **Soft**: Spec 028 (telemetry sidecar) — the observability-strategy doc references sidecar telemetry as Tier 1 of the ladder; no code dependency.
- **Soft**: Spec 035 (cross-cycle digest) — consumes FR-013's one-line health header. If 035 ships after 048, the header simply waits for a consumer.
- **None**: No external dep. Pure stdlib + existing framework.

## Acceptance coverage

Draft — evidence cells populated by `/speckit.tasks` after `/speckit.clarify`. **Q1 resolved 2026-05-29; MVP scope cut locks v1.0 vs v1.1 split** (see "MVP scope cut" table under Functional Requirements).

| User Story | Evidence |
|---|---|
| US1 — Watch an unattended cycle live | `tests/observability/test_vault_status.py`, `tests/observability/test_cycle_log.py`, `tests/observability/test_cycle_state.py` (v1.0: `tests/observability/test_log_surfaces.py` bridge.log half) |
| US2 — Debug a stuck extractor post-mortem | `tests/observability/test_log_surfaces.py` (v1.0 SHIPPED) |
| US3 — Dial verbosity without code changes | `tests/observability/test_log_surfaces.py` (v1.0 SHIPPED) |
| US4 — One-line cycle health summary | `tests/observability/test_health_header.py` |
| US5 — Regression guard against silent log drops | `tests/observability/test_log_surfaces.py` (+ `print_allowlist.txt` v1.1 expansion) |

## v2 scope — Source-Consideration Ledger *(added 2026-06-02 — 🔴 HIGH PRIORITY)*

> **Status**: DRAFT scope addition, NOT in the shipped v1.0 cut. Added
> 2026-06-02 from `docs/TODO.md` "Source-consideration accountability" (raised by
> an outside agent preparing three live evaluation runs — clean-room
> codebase-vault rebuild, new reference-vault, feeds-vault update; specs + acceptance
> probe packs at `~/Personal/codebase-vault-test/` + `~/Personal/reference-vault-test/`).
> **High priority**: this is the lens those runs use to measure whether the
> framework actually *considers and uses every required source*. It is the first
> concrete **observability v2** capability. Clarifications 2026-06-03 RESOLVED;
> tasks + analyze complete; ready for `/speckit.implement`. Home rationale:
> this is diagnosability of source usage — squarely observability — and the
> design MUST honour `docs/observability-strategy.md`'s "don't fragment
> surfaces" anti-pattern (join existing artifacts, don't add a parallel log).

### The need

For every source in `spec.data_sources`, after a run we must be able to say,
crisply and per-source: was it **considered**? did it **contribute cited
content**? and if it contributed nothing, **which of four causes** applies:

- **(a) content genuinely not relevant** — a legitimate skip;
- **(b) access / technical failure** — auth, 403/404, timeout, MCP error, broken feed;
- **(c) workflow / pipeline drop** — the framework dropped it (e.g. scout-contract
  drift silently discarding rows, a stage that never ran);
- **(d) content fetched but quality-rejected** — verifier/gate.

Today (a), (b) and (c) can be **indistinguishable** — exactly the failure class
the live runs cannot afford to misread (a silent pipeline drop reading as "not
relevant" would make a broken framework look like it's working as intended).

### Current state — verified 2026-06-02 (the data is present but fragmented)

The signals exist across the six-tier observability ladder but no single view
fuses them:

- `_pipeline/sources.db` — `sources` (role, `status`, `consecutive_empty_cycles`)
  + `source_cycles` (`notes_generated`, **`notes_referencing`** = citations).
  `pipeline/source_manager.py:19,32` (schema), `:138` (`_count_notes_referencing`).
  Surfaced in the Tier-3 `run-report.md` source scorecard.
- Per-source **`{"name", "searched": bool, "reason": str}`** agent contract in the
  research stage — `pipeline/_cycle_helpers.py:443` (prompt template). This is the
  **(a)** signal — and its weakest link (cf. the 0.6.0 scout bare-string contract
  drift, `docs/POSTMORTEM-2026-05-30-vault-revival.md`).
- `notify_required_source_degraded()` → `_pipeline/cycles/cycle-NNN-source-incidents.json`
  (`pipeline/_cycle_helpers.py:706,774`) + `source_manager.mark_degraded()` →
  append-only `_pipeline/source-incidents.md` (`source_manager.py:312`). The **(b)**
  signal for **required** sources, with an abort threshold.
- `_aggregate_capture_failures()` groups web fetches by `(host, reason)` incl.
  `JS_SHELL`/`THIN`/404 from `scripts/raw_capture.py` — `pipeline/cycle_summary.py:89`,
  consumed at `:208`.
- `pipeline/preflight.py` — `gh auth`, HTTP reachability up front.
- Tier-1 sidecars + `cycle-NNN-quality-report.json` gates — the **(d)** signal.
- Tier-6 `bridge.log` — extractor-subprocess stderr (**module sources only**).

### Gaps that block clean diagnosis

1. **No single fused per-source ledger.** Reconstructing an (a/b/c/d) verdict
   means hand-joining 5–6 artifacts. No one view says "Source X → USED (3 notes,
   2 cited) / Y → SKIPPED_RELEVANCE / Z → ACCESS_FAIL (403) / W → QUALITY_REJECT".
2. **MCP sources are a blind spot — and the codebase vault leans on them most.**
   Jira/Confluence (Atlassian MCP) and GitHub PRs/ADRs (GitHub MCP) don't pass
   through `raw_capture.py` (no host+reason line) or `bridge.log` (not subprocess
   extractors). A silent MCP miss looks identical to (a) — only the agent's
   self-reported `reason` separates them, and that's the weakest link.
3. **"0 contribution + no recorded reason" is not currently a failure** — the exact
   signature of a (c) pipeline drop masquerading as an (a) skip. It should be loud.
4. Tier-4 live `vault status` (FR-009/010/011, deferred to v1.1) isn't shipped, so
   live monitoring during the runs is `--log-level debug` + `tail -f bridge.log`.

### Verdict state machine (FR-020 core)

`declared → considered? → fetch_attempted? → yielded notes? → cited?` — each
terminal state maps to exactly **one** verdict:

| Terminal state | Verdict |
|---|---|
| considered + notes generated + ≥1 cited | `USED` |
| considered, fetched, yielded notes, all verifier-rejected | `QUALITY_REJECT` |
| considered, fetch attempted, fetch failed | `ACCESS_FAIL` |
| considered, no fetch, agent recorded a relevance reason | `SKIPPED_RELEVANCE` |
| 0 contribution **and** no recorded reason | `PIPELINE_DROP` *(fires FR-019)* |
| stage never reached this source | `NOT_REACHED` |

### Functional Requirements *(DRAFT — continue spec 048's FR sequence)*

- **FR-017 — Source ledger artifact.** Emit a per-run, per-source ledger
  (`_pipeline/cycles/cycle-NNN-source-ledger.json` + a run-level roll-up to
  stdout and, optionally, `_pipeline/source-ledger-run.md` with `--write-rollup`;
  does **not** modify `run_report.py` — zero pipeline change) carrying, for each
  declared source: `declared`, `considered`
  (searched), `fetch_attempted`, `fetch_outcome`, `notes_generated`,
  `notes_referencing`, and a single `verdict` from the state machine above. Built
  by **joining existing artifacts** (sources.db + research.json `searched/reason`
  + source-incidents + capture-failures + quality gates) — NOT a new parallel
  logging system.
- **FR-018 — MCP access instrumentation (routing-derived, NOT source-declared).**
  Sources stay **purely declarative** (URL + `role`/`priority`); they do NOT
  declare `type: mcp` or which module processes them. The pipeline routes each
  source to a **module** via the module's `manifest.triggers` (spec 020 trigger
  registry — e.g. `github.com` → a GitHub-MCP module; `youtube.com`/`youtu.be` →
  the youtube module), falling back to a generic agent/HTTP fetch when no trigger
  matches. A source is **MCP-backed iff the module that handled it is
  `managed: true`** (spec 054) — **derived from the routing result, never from a
  source field** (Clarifications Q3). This keeps sources processing-agnostic: a
  new module can be installed *after* a source's spec was written, and the source
  need not know the module's contract or whether a module is installed at all.
  An MCP-backed (managed) handler MUST emit an explicit access signal (attempted
  / succeeded / failed + reason) so an empty MCP source resolves to `ACCESS_FAIL`,
  never `SKIPPED_RELEVANCE`. A cheap per-managed-source preflight probe (one known
  fetch) at run start MAY extend `pipeline/preflight.py`.
- **FR-019 — Fail loud on unexplained silence — handled as ANY other failure.**
  A **required** source resolving to a failure verdict — `ACCESS_FAIL`,
  `PIPELINE_DROP` (zero contribution + no recorded reason), or `QUALITY_REJECT` —
  is surfaced **uniformly**: a WARN in the roll-up + a non-zero diagnostic
  signal in v1, promotable to an **opt-in hard-fail** later (mirroring spec 033's
  `approval_gates`). Per Clarifications Q2, "unexplained silence" is **not** a
  special category — it is treated exactly like an unavailable service or a wrong
  API key (same WARN + diagnostic + opt-in-gate path), so (c) can't hide as (a).
- **FR-020 — Deterministic, documented verdict state machine** (table above) —
  each terminal state maps to exactly one verdict; documented so humans and the
  acceptance probe agree. Verdicts SHOULD be reportable per `role`
  (`behaviour|intent|domain`, per spec 002/046) — required intent/behaviour
  sources matter more than optional domain ones.
- **FR-021** *(nice-to-have)* — Surface the ledger roll-up in the cycle-summary
  health header (FR-013) / future `vault status` (FR-011) so it's visible
  mid-run, not only post-mortem.

### Acceptance criteria

- Ledger lists **every** `spec.data_sources` entry with exactly one verdict; the
  set reconciles (no declared source missing, none invented).
- Injected MCP access failure ⇒ `ACCESS_FAIL` (not `SKIPPED_RELEVANCE`).
- A legitimately-skipped source ⇒ `SKIPPED_RELEVANCE` carrying the agent's reason.
- A source whose notes are all verifier-rejected ⇒ `QUALITY_REJECT`.
- "0 contribution + no reason" ⇒ the FR-019 diagnostic fires.
- No new standalone log surface; the ledger is a documented join/roll-up.

### MVP (if the full scope can't land before the live runs)

Ship **FR-017 + FR-019 first as a read-only post-run script**
(`scripts/source_ledger.py`) that consumes the existing artifacts and prints the
table + the unexplained-silence flag — **zero pipeline changes, usable on the
three live runs immediately** — then promote FR-018/020/021 into the pipeline.

### Dependencies / build-on

`pipeline/source_manager.py`, `pipeline/_cycle_helpers.py` (searched/reason +
`notify_required_source_degraded`), `pipeline/cycle_summary.py`
(`_aggregate_capture_failures`), `pipeline/run_report.py`, `pipeline/preflight.py`,
`docs/observability-strategy.md`; relates to spec 029 (source-manager
correctness), spec 038 (source-module resilience), spec 005 (adaptive sources),
and the `role` model in spec 002 / 046.

### Clarifications — Session 2026-06-03 (v2 Source-Consideration Ledger) — RESOLVED

- **SL-Q1 (ledger granularity) → A**: per-cycle JSON (`cycle-NNN-source-ledger.json`,
  the gate-consumable artifact — spec 053's trunk-inversion reads it) **+** a
  per-run roll-up to stdout and, optionally, `_pipeline/source-ledger-run.md`
  (`--write-rollup`; does **not** modify `run_report.py` — zero pipeline change).
- **SL-Q2 (unexplained silence: hard-fail or warn?) → A, refined**: WARN + non-zero
  diagnostic in v1, opt-in hard-fail later (spec-033 `approval_gates` pattern).
  **Refinement**: treat unexplained silence as **any other failure** — same path
  as an unavailable service / wrong API key, not a special category. (FR-019
  updated.)
- **SL-Q3 (how is a source declared MCP-backed?) → routing-derived, NOT
  source-declared**: sources stay purely declarative; the **module** declares URL
  `triggers` (spec 020) and the pipeline routes source→module by trigger match; a
  source is MCP-backed iff its handling module is `managed: true` (spec 054).
  Rationale (user): a source may reference an uninstalled module, may not know the
  module's contract, a module may be installed *after* the spec was written, and
  sources should be declarative/processing-agnostic. (FR-018 updated. **Carries to
  spec 054 + spec 020's trigger registry.**)

## Out of Scope

- **External metrics push** — no Datadog, no Prometheus, no OpenTelemetry exporters. Out-of-scope; revisit in `observability v2` (Horizon 2 or 3). *(Note: the Source-Consideration Ledger section above is the first claimed v2 capability — promoted ahead of the rest of v2 for the upcoming live runs.)*
- **Structured event tracing** — no spans, no correlation IDs, no trace propagation across subprocesses. Out-of-scope; v2.
- **Real-time alerting** — no PagerDuty webhook, no Slack notifier, no "page me when a cycle fails" surface. Out-of-scope; v2.
- **Log aggregation / search backend** — no Loki, no Elastic, no centralized log store. `rg` over the per-vault `_pipeline/` tree is the search interface in v1.
- **Per-module log files** — `bridge.log` captures ALL extractors in one file per cycle. Splitting into `bridge-youtube.log`, `bridge-reddit.log`, etc. is a v2 consideration once the file gets unwieldy (likely never given spec-037's wall-clock caps).
- **Backporting log statements into spec-020 module extractors** — extractor authors choose their own logging strategy; this spec only captures what they emit to stderr. The `docs/observability-strategy.md` doc will give guidance but not enforce conventions inside third-party modules.
- **Full migration of all 125 pipeline `print()` calls in v1** — per Q3 default, hot-path-only in v1. Non-hot-path migration is a v2 follow-up.

---

*Status (2026-05-29): /speckit.clarify Session 2026-05-29 resolved Q1 and locked v1.0-vs-v1.1 MVP scope cut. Q2 + Q3 are deferred-but-locked. Ready for `/speckit.plan` against the MVP scope (FR-001..008, FR-012, FR-015/016). This spec **blocks the Feeds-Vault manual cycle** (Wave-3 readiness) — until logging + bridge.log + hot-path print() migration ship, an unattended multi-cycle run is not debuggable.*

---

## v2.1 amendment — ledger↔citation reconciliation *(added 2026-06-05 — defect 3.4)*

**Status (amendment):** SHIPPED **1.0.0rc3** (2026-06-06, PR #126, squash `2d217be`)
— rc3 wave (sibling specs 061/062/063; co-amendment to spec 028). FR-022..024
delivered: ledger-build joins note `source_urls`, adds the `LEDGER_DISAGREEMENT`
verdict (cited-but-failed sources no longer read as 0-contribution failures) +
best-effort `read_via ∈ {direct,mcp,unknown}`; sidecar schema `1.0 → 1.1` (additive).
Extended the SHIPPED v2 ledger (FR-017..021); did not change 0.9.0 behaviour.

### Why this amendment exists

The 2026-06-05 codebase-vault rc1 evaluation (§3.4) found the v2 ledger **unreliable
on the dominant evidence path**: the run-level ledger marked **every** required source
`ACCESS_FAIL` / `PIPELINE_DROP` with 0/0 notes — which the v2 contract turns into
multiple SA-4 CRITICALs — *while the notes cite code / PRs / Jira at 100% / 71% / 63%*
(a deterministic citation audit over 104 notes). Root cause: `sources.db` was never
populated, because the research agent read sources **directly** (file / PR / MCP)
rather than through the spec-020 source-module extraction path the ledger joins on. So
the join is **blind to direct + MCP reads** and emits false negatives.

This matters acutely because the ledger is the **designated eval lens for all three
live validation runs** (and spec 053's trunk-inversion gate reads
`cycle-NNN-source-ledger.json` directly — false verdicts there poison an enforcement
gate, not just a report).

### Amendment requirements

- **FR-022 — Reconcile verdicts against note citations.** The ledger MUST cross-check
  each source's verdict against the actual note `source_urls` corpus. A source the
  join marks `ACCESS_FAIL` / `PIPELINE_DROP` / `NOT_REACHED` but which notes
  **demonstrably cite** MUST NOT be asserted as a silent failure — it is either
  reclassified to `USED` (citation-evidenced) or emitted as a `LEDGER_DISAGREEMENT`
  diagnostic (clarify Q1). **The mismatch is the finding.**
- **FR-023 — `sources.db` covers the citation path.** Either (a) populate `sources.db`
  from note `source_urls` at note-write time so the join sees direct/MCP reads, or
  (b) teach the ledger to treat the citation corpus as a first-class evidence input to
  the join (clarify Q2). Invariant either way: **a source cited by ≥1 note can never be
  reported as 0-contribution `ACCESS_FAIL`.**
- **FR-024 — Direct/MCP read attribution.** Direct file reads, PR reads, and MCP tool
  calls (Jira / Confluence / GitHub) that don't flow through a spec-020 module MUST
  still be attributable in the ledger (extends FR-018's routing-derived MCP
  instrumentation; ties to spec 054 managed modules).

### Acceptance (amendment)

- On the rc1 snapshot, the reconciled ledger reports the **ledger↔citation
  disagreement** rather than a wall of `ACCESS_FAIL`.
- A source cited by ≥1 note is never `0-contribution ACCESS_FAIL`.
- SA-3 / SA-4 re-grade against the reconciled view (consumed by spec 063 US2).

### Clarifications (resolved 2026-06-05)

- **Q1 — mismatch handling** → **Flag, don't silently reclassify.** On a
  ledger↔citation mismatch the **reported verdict becomes `LEDGER_DISAGREEMENT`** while
  the original join verdict is **preserved in a `disagreement_was` field**, so the
  *reason* the join missed the evidence stays visible (a cited source still satisfies
  the FR-023 invariant — it can never read as `0-contribution ACCESS_FAIL`).
  `LEDGER_DISAGREEMENT` is added to the `Verdict` enum in
  `contracts/source-ledger-v2.contract.md`; because **spec 053's trunk-inversion gate
  reads that enum**, the gate MUST treat a derived-trunk source that resolves to
  `LEDGER_DISAGREEMENT` as citation-evidenced (acceptable, like `USED`), not as a trunk
  drop — coordinated at implementation (`tasks-rc3-amendment.md` T006).
- **Q2 — sources.db vs join** → **Join the citation corpus at ledger-build time**
  (zero-pipeline-change) for rc3. Populating `sources.db` from `source_urls` at
  note-write time (which would fix other consumers too) is recorded as a follow-up,
  not an rc3 deliverable.

Shipped 1.0.0rc3 (2026-06-06, PR #126) — implemented per `plan-rc3-amendment.md` + `tasks-rc3-amendment.md`.

### Cross-references

Spec 063 US2 (the harness-side cross-check consumes the reconciled ledger), spec 020
(the extraction path the join assumes), spec 054 (managed modules / MCP), spec 053
(trunk-inversion gate reads the per-cycle ledger — reconciliation makes that
enforcement honest), spec 062 FR1 (`QUALITY_REJECT` interplay with rejected notes).
