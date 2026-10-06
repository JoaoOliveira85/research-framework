# Implementation Plan: Observability **v1.1** (Spec 048 — `vault status` + health header + print allowlist)

**Branch**: `048-v1.1-vault-status` · **Date**: 2026-06-03
**Spec**: [spec.md](./spec.md) (v1.1 FRs: FR-009/010/011/013/014) ·
**Research**: [research-v1.1.md](./research-v1.1.md) ·
**Contract**: [contracts/vault-status-v1.1.contract.md](./contracts/vault-status-v1.1.contract.md) ·
**Tasks**: [tasks-v1.1.md](./tasks-v1.1.md)
**Status**: IMPLEMENT-READY (post-clarify CL-1..CL-4 + plan + research + contract + tasks + analyze).

## Summary

Close the three v1.1 FR groups deferred from the 0.5.0 cut, in increasing
coupling order:

1. **FR-013 — one-line cycle-health header** (smallest, no new surface): prepend
   a deterministic `CYCLE N: STATUS | …` line to `cycle-NNN-summary.md`.
2. **FR-009/010/011 — `vault status` verb**: a new read-only CLI verb showing
   live cycle state, backed by an **extended `state.json`** (D1) + a new per-cycle
   **`cycle.log`** (D2).
3. **FR-014 — print-allowlist convention**: extend the shipped FR-015 test to all
   of `pipeline/` with a documented `# noqa: T201` allowlist (D4).

All deterministic, LLM-free, stdlib-only.

## Technical Context

**Language**: Python 3.11+ · **Deps**: stdlib only (`logging`, `argparse`,
`json`, `pathlib`, `datetime`) — **no new runtime dependency** (Principle V).
**Base**: v1.0 (shipped 0.5.0, on `main`).

**Modules touched / added**:

| Concern | File | Change |
|---|---|---|
| Live-status state (D1) | `pipeline/cycle_runner.py` (`_state_write` seam, ~:263) | write `stage` + `cycle_started_at` + `budget_snapshot` at each stage transition |
| Status state schema | `pipeline/cycle_state.py` *(new, small)* | typed read/write of the extended `state.json` (one writer, one reader — no ad-hoc dict access) |
| Per-cycle logger file (D2) | `observability/cycle_log.py` *(new)* | `FileHandler` attach/detach context manager (mirrors v1.0 `publish_bridge_writer` lifecycle) |
| `cycle.log` wiring | `pipeline/cycle_runner.py` | open the file handler on cycle start, close on exit (incl. error/kill paths) |
| Status verb (D3) | `cli/status.py` *(new)* + `cli/_parser.py` (register) + the `./vault` shim template | `vault status --vault <path> [--json]`; reads state.json + last summary + tails cycle.log |
| Health header (FR-013) | `pipeline/cycle_summary.py` (`write_summary`, :171) | prepend line-1 header; add a `health_header()` pure function (reused by `vault status` FR-011 + spec 035) |
| Print allowlist (D4) | `tests/observability/test_log_surfaces.py` (+ `tests/observability/print_allowlist.txt`) | count-based assertion over all `pipeline/`; classify the ~13 sites |

**Reused (read-only) surfaces**: `pipeline/timings.py` (`cycle_started_at` →
elapsed), `pipeline/budget_guard.py` / `pipeline/cost_estimator.py` (budget
remaining + spend), `pipeline/quality_report.py` (gate counts → verifier-passed
+ STATUS), `cli/_log_level.py` (the `--log-level` plumbing the new verb inherits).

## Constitution Check

| Principle | Status | Notes |
|---|---|---|
| IV — deterministic gates, no LLM self-assessment | ✅ PASS | status/header/test are pure deterministic reads; zero agent dispatch |
| V — no new runtime dependency | ✅ PASS | stdlib `logging`/`argparse`/`json` only |
| X — vault history append-only git | ✅ PASS | `vault status` is read-only; `cycle.log` + `state.json` under `_pipeline/` (not vault content); covered by 050's existing scope |
| Testing pyramid (ADR-0008) | ✅ PASS | tier-2 unit (header fn, state schema, status formatting), tier-3 integration (`tmp_path` vault → status output), extends the tier-5/6 FR-015 regression file |
| Observability "don't fragment surfaces" (`docs/observability-strategy.md`) | ✅ PASS | `cycle.log` is the Tier-5 logger file the strategy already names; `vault status` is the Tier-4 verb already in the ladder — both were *planned* surfaces, not new ones |

**No violations. No complexity-tracking entries required.**

## Project Structure (delta)

```text
src/research_framework/
  cli/
    status.py                      # NEW — vault status verb (plain + --json)
    _parser.py                     # register `status`
  pipeline/
    cycle_state.py                 # NEW — extended state.json read/write
    cycle_runner.py                # write stage/start/budget; open/close cycle.log
    cycle_summary.py               # FR-013 health header (+ health_header() fn)
  observability/
    cycle_log.py                   # NEW — per-cycle FileHandler context manager
tests/
  observability/
    test_log_surfaces.py           # extend: all-pipeline print allowlist (FR-014/015)
    print_allowlist.txt            # NEW — committed allowlist
    test_vault_status.py           # NEW — FR-009/010/011
    test_health_header.py          # NEW — FR-013
    test_cycle_log.py              # NEW — FR-010 tail source
specs/048-observability-v1/
  *-v1.1.md, contracts/vault-status-v1.1.contract.md, checklists/requirements-v1.1.md
```

## TDD task strategy

Three independent groups; recommended order **FR-013 → cycle_log/state → status
verb → print allowlist** (header + log file are inputs the status verb consumes;
the allowlist is orthogonal and `[P]`).

- **Phase 1 — health header (FR-013)**: pure `health_header()` fn first
  (test: STATUS derivation table + format), then wire into `write_summary` line 1.
- **Phase 2 — live-status backing (D1/D2)**: `cycle_state` schema + `cycle_log`
  context manager (tests first), then wire both into `cycle_runner` (incl.
  error/kill paths close the file).
- **Phase 3 — `vault status` verb (FR-009/010/011)**: active-cycle render,
  no-active-cycle render (reuses `health_header()`), `--json`, edge cases
  (`--vault` required, first-second-of-cycle, <1s on 1000-cycle history).
- **Phase 4 — print allowlist (FR-014) `[P]`**: classify the ~13 `pipeline/`
  sites (migrate noise → logger; allowlist raw ones), commit `print_allowlist.txt`,
  extend the FR-015 test.
- **Phase 5 — polish**: `docs/observability-strategy.md` Tier-4/5 sections updated
  (`vault status` + `cycle.log` now real); CHANGELOG/ROADMAP; ruff + full fast-loop.

## Complexity / implement-time validations

- **`budget_snapshot` source** — confirm the live wall-clock + dollar remaining
  are readable mid-cycle from the shipped 033 budget guard (vs. only at gate
  time). If only gate-time, snapshot at each stage transition (the D1 write point)
  — graceful-degrade to "n/a" if unavailable.
- **`cycle.log` handler lifecycle** — must detach+close on EVERY exit path
  (clean / constrained / abort / kill), reusing v1.0's leak-fix pattern; a
  regression test asserts no handler leak across two cycles in one process.
- **STATUS derivation** — PASS/WARN/FAIL is defined deterministically in the
  contract; confirm the gate-count + incident inputs are present in
  `quality_report` at summary-write time.
