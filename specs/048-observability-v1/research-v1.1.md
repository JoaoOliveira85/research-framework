# Research & Decisions: Observability **v1.1** (Spec 048 — `vault status` + health header + print allowlist)

**Date**: 2026-06-03 · **Stage**: post-clarify (CL-1..CL-4), pre-plan
**Scope**: the v1.1 FRs deferred-but-locked in the shipped v1.0 cut —
**FR-009/010/011** (`vault status` verb), **FR-013** (one-line cycle-health
header), **FR-014** (print-allowlist convention). NOT the v2 Source-Ledger
(FR-017..021 — separate `048-v2-source-ledger` line).

## Why a separate v1.1 artifact set

The v1.0 cut (FR-001..008/012/015/016) SHIPPED in 0.5.0; its `plan.md` /
`tasks.md` / `research.md` are that work's record and MUST NOT be clobbered. The
v1.1 FRs were locked-but-unimplemented (spec.md "MVP scope cut" table). This set
(`*-v1.1.*`) flesh es them to implement-ready as **net-new files** — no edit to
the v1.0 artifacts, and no edit to the in-spec v2 section (avoids a merge clash
with the parallel `048-v2-source-ledger` branch). The spec.md gains only a small
localized "v1.1 clarified" subsection + a status-header note.

## Audit findings (spec ↔ code reconciliation, 2026-06-03)

| spec claim / assumption | reality (2026-06-03) | resolution |
|---|---|---|
| FR-010: current stage "read from `_pipeline/state.json`" | `state.json` holds only `{"in_progress_cycle": N}` — written once at `cycle_runner.py:263`; no stage / start-time / budget | **CL-1**: extend `state.json` (stage + `cycle_started_at` + `budget_snapshot`), written at each stage transition |
| FR-010: "most recent `logger.info()` line … tail of the cycle log" | v1.0 wired `logging.basicConfig(stream=sys.stderr)` — **no per-cycle log FILE**; `bridge.log` is extractor *stderr* only | **CL-2**: add a per-cycle logger `FileHandler` → `cycle.log`; tail it |
| FR-009: a `vault status` verb | no top-level `status` verb; only a **phase-level** `pipeline status` (`research_cycles.py:61` → `runner.status()` reading `pipeline-state.json`) | **CL-3**: add a new first-class `status` verb, distinct from `pipeline status` |
| FR-014: "~45 non-hot-path `print()`" | only **~13** remain in `pipeline/` (verifier 3, `_cycle_helpers` 4, research_plan 3, budget_guard 2, timings 1) — the 0.5.0 migration + code-quality passes shrank it | **CL-4**: a count-based test over all of `pipeline/` + a small `# noqa`-documented allowlist; no ruff change |
| FR-004 listed `status` as a subcommand the `--log-level` flag applies to | the flag (`cli/_log_level.py`) already exists from v1.0; `status` just needs to register under the same parser | `status` inherits `--log-level` for free |
| FR-013 health header is "read by spec 035's digest" | 035 was fleshed 2026-06-03; it consumes real `sources.db`/sidecar artifacts, treats the header as a **soft** input | FR-013 ships the header; 035 stays soft-coupled (no hard ordering) |

**Net**: the three FR groups are sound; the audit corrected (a) the data
plumbing for live status (state.json + a real log file to tail), (b) the verb
placement vs. the existing `pipeline status`, and (c) the now-stale print count.

## Decisions

### D1 — Extend `_pipeline/state.json` as the single live-status source (CL-1)
`cycle_runner` writes `{in_progress_cycle, stage, cycle_started_at,
budget_snapshot:{wall_remaining_s, dollar_remaining}}` at **each stage
transition** (the existing `_state_write` RMW at `cycle_runner.py:263` is the
seam). One atomic file ⇒ `vault status` is a single cheap read (FR-009 <1s),
no multi-artifact join at status-time. **Rejected**: derive-from-timings
(multi-file read every status call; racy mid-write); minimal (drops the budget
+ stage the operator most wants mid-run).

### D2 — Per-cycle `cycle.log` FileHandler (CL-2)
On cycle start, attach a `logging.FileHandler(_pipeline/cycles/cycle-NNN/cycle.log)`
to the framework logger (alongside v1.0's stderr handler); detach + close on
cycle end (mirrors v1.0's `publish_bridge_writer` ContextVar lifecycle so it
can't leak across cycles). `vault status` tails the last `logger.info` line from
it. Bonus: a durable per-cycle logger trail next to `bridge.log` (logger output
vs. extractor stderr — complementary Tier-5/Tier-6 surfaces). **Rejected**:
drop-the-field (loses the "what's it doing right now?" line — the single most
reassuring datum mid-run); reuse-bridge.log (that's extractor stderr, not
`logger.info` — wrong semantics, empty for non-module cycles).

### D3 — New first-class `status` verb, distinct from `pipeline status` (CL-3)
`./vault status --vault <path>` (shim) → a new `status` subcommand in the `cli/`
registry (`_parser.py` pattern + a `cli/status.py` handler), reusing the v1.0
`--log-level` plumbing. Kept SEPARATE from the phase-level `pipeline status`
(Phase 1/2/3 progress) — different question ("is a cycle alive right now?" vs.
"which generation phase am I in?"). **Rejected**: fold-into-`pipeline status`
(overloads one verb with two unrelated views); rename-existing (churns a shipped
verb + its tests for cosmetics).

### D4 — Count-based print allowlist test over all of `pipeline/`; no ruff change (CL-4)
Extend the shipped FR-015 mechanism (`tests/observability/test_log_surfaces.py`)
to assert no NET-NEW `print()` across **all** of `pipeline/` vs. a committed
allowlist; each allowlisted site carries `# noqa: T201 — keep raw print:
<reason>` with `reason ∈ {interactive prompt, test-mode signal, CLI usage error,
final report stdout contract}` (FR-014's constrained set). The ~13 current sites
are classified at implement-time: progress-noise → migrate to `logger`;
genuinely-raw → allowlist. **Rejected**: enable ruff `T20` repo-wide (surfaces
the many *intentional* `cli/` user-output prints → noqa noise, scope creep into
non-pipeline code); `T20` pipeline-scoped (a per-file-ignore config + flips a new
rule for a 13-site problem the existing test mechanism already covers).

## Cross-spec interactions
- **v1.0 (HARD, shipped 0.5.0 on main)** — logger wiring, `bridge.log`,
  `state.json` writer, FR-015 test, `--log-level`. v1.1 extends all of these;
  base is on `main`, so v1.1 is implementable immediately.
- **035 (soft)** — consumes FR-013's header; no hard ordering (035 treats it as
  a soft input, falls back to its own artifacts).
- **033/028 (read-only)** — budget snapshot (wall + dollar) + spend for FR-010
  + FR-013 come from the shipped cost/budget surfaces.
- **026 (test isolation)** — status/health/cycle.log tests use `tmp_path` vaults.
- **050 (relevant)** — `cycle.log` + extended `state.json` land under `_pipeline/`
  (already covered by the vault-commit scope; read-only `vault status`).

## Determinism / Principle check
`vault status` + the health header + the print test are all **deterministic + LLM-free**
(Principle IV). No new runtime dep — stdlib `logging` / `argparse` / `json`
(Principle V). `vault status` is **read-only** on the vault; `cycle.log` +
`state.json` live under `_pipeline/` (Principle X — not vault content). ✅
