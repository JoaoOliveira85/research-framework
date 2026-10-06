# Implementation Plan: Observability v1 (MVP cut)

**Branch**: `048-observability-v1` | **Date**: 2026-05-29 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/048-observability-v1/spec.md`

> **Scope**: This plan covers the **MVP cut only** (v1.0). The deferred-but-locked v1.1 surfaces (`vault status` verb, one-line cycle health header, FR-014 print-allowlist convention) get their own plan when promoted from the spec's Clarifications block. See the `## MVP scope cut` table in `spec.md` for the exact FR list.

## Summary

Ship Tier-5 (Python `logging`) and Tier-6 (subprocess stderr audit via `bridge.log`) of the observability ladder so the Feeds-Vault manual cycle is debuggable when unattended. Concretely:

1. **Wire the root logger** at CLI entry (FR-001/002/003) — `logging.basicConfig()` once at startup, idempotent against pre-configured parents (pytest), `getLogger(__name__)` everywhere.
2. **Add a global `--log-level` flag** (FR-004/005) with a TTY-aware default (INFO for interactive, WARNING for piped/CI).
3. **Capture extractor stderr live** (FR-006/007/008) — per-cycle `bridge.log` under `<vault>/_pipeline/cycles/cycle-NNN/`; line-buffered via `Popen(..., bufsize=1, universal_newlines=True)` + a per-extractor reader thread; framed with header/footer lines and a `[<module>:<pid>] ` line prefix to disambiguate interleaved output.
4. **Migrate hot-path `print()` calls** (FR-012) — ~80 calls across `cycle_runner.py`, `orchestrator.py`, `runner.py`, `steps/{scout,research,postprocess}.py`, and `source_bridge/orchestrator.py` move from `print(…)` to `logger.info(…)` (or `logger.warning(…)` for actionable warnings). Non-hot-path calls (~45) stay untouched in MVP.
5. **Regression guard** (FR-015/016) — `tests/observability/test_log_surfaces.py` verifies logger wiring, the line-buffered guarantee (timed write-sleep-write probe), `bridge.log` creation, and a no-net-new-`print()`-in-hot-path snapshot. Runs in `pytest -m "not e2e"` (no special markers) and in `./build.sh` smoke gate.

**Technical approach**: stdlib `logging` only (Principle V — no new deps). One subprocess reader thread per concurrent extractor (Wave-2 modules run sequentially today, so usually one active thread). Atomic append-only writes to `bridge.log` via a single per-cycle writer wrapped in a `threading.Lock` to serialize across reader threads.

## Technical Context

**Language/Version**: Python 3.11+ (per `pyproject.toml::requires-python` and constitution Technology Constraints).
**Primary Dependencies**: Standard library only — `logging`, `subprocess`, `threading`, `queue`, `sys`, `pathlib`, `time`, `os`. Existing project dep `jinja2 ≥ 3.1` unaffected. **No new runtime dependency** (Principle V upheld).
**Storage**: Filesystem under vault root. New artifact: `<vault>/_pipeline/cycles/cycle-NNN/bridge.log` (append-only, one per cycle, no rotation).
**Testing**: `pytest` (existing). New test directory `tests/observability/`. Test fixtures: a synthetic extractor script (Python one-liner) for the line-buffered probe.
**Target Platform**: Linux + macOS (existing matrix — `pyproject.toml::target = darwin/linux`). Windows out of scope.
**Project Type**: CLI tool (single project, `src/research_framework/` package).
**Performance Goals**: `tail -f bridge.log` shows new lines within ≤2s of subprocess emission (FR-007 acceptance). Logger overhead negligible (stdlib `logging` is already in every Python process's hot path). Reader-thread CPU cost ≤1% per active extractor.
**Constraints**: Cannot regress the existing `pytest -m "not e2e"` suite (~4 min on a recent Mac, 1278 tests as of 0.3.2). Must work whether `logging` was pre-configured by a parent (pytest) or not (FR-002 idempotency).
**Scale/Scope**: ~80 `print()` → `logger.info()` mechanical migrations + ~6 new files (CLI flag wiring, bridge log writer, reader thread, regression test, observability strategy doc, test fixture). LOC budget: ≤500 lines added net (incl. tests).

## Constitution Check

*Gate run 2026-05-29 against constitution v1.3.4.*

| Principle | Status | Notes |
|---|---|---|
| I — Script-Validated Quality Gates | ✅ N/A | This spec adds observability surfaces, not a cycle gate. FR-015 is a regression test (Tier-2 spec lint) not a cycle-validation gate. No new exit codes. |
| II — Phase Sequencing | ✅ N/A | No phase work. The MVP only modifies CLI bootstrap + the per-cycle subprocess driver; phase ordering unchanged. |
| III — Test-First (TDD — NON-NEGOTIABLE) | ✅ PASS | All work follows the foreman TDD pattern (ADR-0010). Each FR has a failing test committed BEFORE the implementing code in the same task block. No `pass`-body stubs ship. |
| IV — Agent-Script Separation | ✅ N/A | No agent work. The `vault status` verb (which WOULD touch this boundary) is deferred to v1.1. |
| V — Offline-First, No External Persistence | ✅ PASS | Pure stdlib. `bridge.log` writes locally under the vault tree (same locality as existing `_pipeline/` artifacts). No telemetry, no cloud sync, no new dep. |
| VI — No Duplicate Notes | ✅ N/A | No note generation. |
| VII — External Sources Mandatory | ✅ N/A | Not a research-cycle change. |
| VIII — No Placeholders in Deliverables | ✅ PASS | Every new file ships working code or a working test. FR-009/010/011/013/014 are documented as *(v1.1)* in the spec — they're NOT half-written stubs in MVP code. |
| IX — Vault-First Citation | ✅ N/A | No agent output. |

**ADR-0007 (mandatory smoke gate)**: FR-016 explicitly puts the regression test in the `./build.sh` smoke-gate set. No `--skip-smoke` flag exists per ADR-0007. Compliant.

**ADR-0010 (foreman verification pattern)**: tasks.md will ship with the standard `### Testing Requirements` blocks. `scripts/foreman/verify_test_coverage.py` Arm A must pass before merge.

**Gate result**: ✅ PASS — no violations, no Complexity Tracking entries needed.

## Project Structure

### Documentation (this feature)

```text
specs/048-observability-v1/
├── plan.md              # This file (MVP cut)
├── spec.md              # Feature spec (CLARIFIED 2026-05-29)
├── research.md          # Phase 0 output — 4 mini research notes (this commit)
├── data-model.md        # Phase 1 output — bridge.log format + record schema (this commit)
├── quickstart.md        # Phase 1 output — operator-facing usage examples (this commit)
├── contracts/
│   ├── log-level-flag.contract.md      # CLI surface contract for --log-level
│   ├── bridge-log-format.contract.md   # bridge.log file format contract (line framing)
│   └── logger-wiring.contract.md       # logging.basicConfig invariants
└── tasks.md             # Phase 2 output — populated by /speckit.tasks (NOT this command)
```

### Source Code (repository root)

```text
src/research_framework/
├── cli/
│   ├── __main__.py                  # ADD: logging.basicConfig() invocation at top
│   └── _log_level.py                # NEW: --log-level flag wiring, TTY detection
├── observability/                   # NEW package — Tier-5/Tier-6 surfaces live here
│   ├── __init__.py
│   ├── bridge_log.py                # NEW: bridge.log writer (header/footer framing, lock)
│   └── extractor_capture.py         # NEW: reader-thread that drains Popen.stderr line-buffered
├── pipeline/
│   ├── cycle_runner.py              # MOD: bridge.log lifecycle (open at cycle start, close at exit)
│   ├── orchestrator.py              # MOD: hot-path print() → logger.info()
│   ├── runner.py                    # MOD: hot-path print() → logger.info()
│   ├── source_bridge/
│   │   ├── extractor.py             # MOD: wire reader-thread per Popen invocation
│   │   └── orchestrator.py          # MOD: hot-path print() → logger.info()
│   └── steps/
│       ├── scout.py                 # MOD: hot-path print() → logger.info()
│       ├── research.py              # MOD: hot-path print() → logger.info()
│       └── postprocess.py           # MOD: hot-path print() → logger.info()

tests/observability/                  # NEW test directory
├── __init__.py
├── conftest.py                       # NEW: capsys-aware fixtures + sentinel-cycle harness
├── test_log_surfaces.py              # NEW: the FR-015/016 regression test
└── _fixtures/
    └── sentinel_extractor.py         # NEW: synthetic extractor for the line-buffered probe

docs/
└── observability-strategy.md         # NEW: sibling doc to docs/testing-strategy.md
```

**Structure Decision**: Single-project layout (existing convention). New `observability/` package keeps the Tier-5/Tier-6 surfaces co-located instead of scattering them across `cli/` and `pipeline/source_bridge/`. The `cli/_log_level.py` private module mirrors the existing `cli/_<surface>.py` pattern.

## Phase 0 — Research findings

*Most decisions were locked in `/speckit.specify` and `/speckit.clarify`. Phase 0 here is a brief audit of the four areas where best-practice clarity is worth pinning before tasks land.* See `research.md` for the full notes.

| Topic | Decision | Rationale |
|---|---|---|
| TTY detection | `sys.stdout.isatty()` only; no `os.isatty()` or environ overrides | Mirrors `pytest`, `ruff`, `pip` conventions; one source of truth |
| Line-buffered stderr capture | `Popen(..., bufsize=1, universal_newlines=True)` + `threading.Thread(target=_reader, daemon=True)` | Stdlib-only; doesn't block the orchestrator; daemon=True means thread dies with process |
| Logger config idempotency | `if logging.root.handlers: return` early | Avoids double-handler bug under pytest (its capture log handler is already on root) |
| `bridge.log` write contention | Single per-cycle file + `threading.Lock` around append | Wave-2 extractors run sequentially today, so contention is theoretical; lock is cheap insurance for future parallel-source patterns |

## Phase 1 — Design artifacts

**Generated files** (this commit, alongside `plan.md`):

1. **`research.md`** — extended notes on the four Phase-0 decisions plus the alternatives considered (e.g. `structlog` rejected per Principle V; `select()`-based reader rejected per spec Q1 alternative C; per-module log files rejected — see spec Out of Scope).
2. **`data-model.md`** — three entities:
   - **LoggerRecord** (in-memory) — the `%(asctime)s [%(levelname)s] %(name)s: %(message)s` format pinned in FR-001; fields explicitly named so future serialization (v1.1's `vault status`) can read them without reformatting.
   - **BridgeLogEntry** (on-disk line) — header line, framed body lines (`[<module>:<pid>] <stderr-line>`), footer line. Documented as the parseable surface so v1.1's `vault status` can grep it for "last extractor".
   - **CycleObservabilityState** (orchestrator-owned, transient) — the `(bridge_log_path, lock, active_reader_threads)` triple held by `cycle_runner` during a cycle.
3. **`quickstart.md`** — operator-facing usage (live-watch a cycle, debug a stuck extractor, dial `--log-level`, hook into existing artifacts).
4. **`contracts/log-level-flag.contract.md`** — CLI surface: flag name, allowed values, default selection algorithm (TTY-aware), error mode on invalid value (exit 2 per Edge Cases).
5. **`contracts/bridge-log-format.contract.md`** — exact byte-level format of header line, body line prefix, footer lines (success + KILLED). Includes a regex pinning the framing so the FR-015 test can parse.
6. **`contracts/logger-wiring.contract.md`** — invariants: `basicConfig` called at most once per process; `getLogger(__name__)` everywhere in `src/research_framework/`; format string locked; stream is `sys.stderr` (NOT stdout — avoids polluting any future JSON-output paths).

**Agent context update**: `.specify/scripts/bash/update-agent-context.sh cursor-agent` will be run at the end of `/speckit.plan` to register the new technologies (`logging`, `subprocess.Popen(..., bufsize=1)`, `threading.Thread`, `bridge.log` artifact) in `CLAUDE.md` Active Technologies.

**Constitution re-check post-design**: Same as Phase 0 — still ✅ PASS, no violations introduced.

## Complexity Tracking

No Constitution violations to justify. Section intentionally left empty per template guidance.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| _(none)_ | — | — |

## Out of scope for THIS plan (deferred to v1.1)

These FRs are locked in the spec but **NOT** addressed by this plan:

- **FR-009/010/011** — `vault status` verb. Will get its own plan when v1.1 starts. Likely a thin CLI command that reads `_pipeline/state.json` + `cycle-NNN-summary.md` line 1 (which itself needs FR-013 first).
- **FR-013** — One-line cycle health header at the top of `cycle-NNN-summary.md`. Sequencing constraint: must land before FR-011 (so `vault status` can read it).
- **FR-014** — `# noqa: T201` allowlist convention for the ~45 non-hot-path `print()` sites. Lands when FR-013 ships (same v1.1 PR).

Spec acceptance coverage table reflects the split: US1 partially shipped here, US4 fully deferred.

## Next command

`/speckit.tasks` — break this MVP plan into foreman-compatible tasks. Plan to produce ~12-15 tasks across 4 task groups:

1. **Logger wiring + CLI flag** (4-5 tasks): basicConfig + `--log-level` + TTY default + idempotency + smoke probe.
2. **bridge.log infrastructure** (3-4 tasks): writer + reader thread + framing contract test + KILLED footer path.
3. **Hot-path `print()` migration** (2-3 tasks): mechanical sweep + per-file ruff check + before/after snapshot.
4. **Regression guard** (2 tasks): `tests/observability/test_log_surfaces.py` + smoke-gate integration.

Each task ships with `### Testing Requirements` block per ADR-0010 (foreman pattern). Estimated MVP wall-clock: ~2-3 days (matches the spec's scope option estimate).
