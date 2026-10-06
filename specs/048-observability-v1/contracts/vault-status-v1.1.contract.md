# Contract: Observability v1.1 surfaces

**Spec**: 048 v1.1 · **Date**: 2026-06-03 · **Status**: implement-ready
Covers FR-009/010/011 (`vault status`), FR-013 (health header), FR-014 (print
allowlist), and the two backing artifacts (extended `state.json`, `cycle.log`).
Everything here is **deterministic** (Principle IV) and stdlib-only (Principle V).

---

## 1. Extended `_pipeline/state.json` (D1 / CL-1)

Single small JSON, atomically rewritten at **each stage transition** by
`cycle_runner` (extends the existing `{"in_progress_cycle": N}` write).

```json
{
  "in_progress_cycle": 3,
  "cycles_budgeted": 5,
  "stage": "research",
  "cycle_started_at": "2026-06-03T14:02:11Z",
  "budget_snapshot": {
    "wall_remaining_s": 4380,
    "dollar_remaining": 0.67,
    "dollar_budget": 1.50
  },
  "updated_at": "2026-06-03T14:49:30Z"
}
```

- `stage` ∈ the pipeline's known stage names (scout / research / postprocess /
  …); `null` only in the sub-second window before the first transition.
- `cycles_budgeted` = the run's total cycle budget (the `--cycles` arg), set once
  at cycle start — gives `vault status` the "N of M" denominator from the single read.
- All `budget_snapshot` fields are nullable → render `n/a` if the 033 surface
  can't supply them mid-cycle (graceful degrade, never crash).
- Absent file ⇒ no active cycle (FR-011 path).
- `updated_at` lets `vault status` show staleness if a cycle died without
  clearing the file.

**Invariant**: exactly one writer (`cycle_state.write`) and one reader
(`cycle_state.read`); no ad-hoc dict access elsewhere.

---

## 2. Per-cycle `cycle.log` (D2 / CL-2)

- Path: `<vault>/_pipeline/cycles/cycle-NNN/cycle.log`.
- A `logging.FileHandler` attached to the framework logger on cycle start, using
  v1.0's formatter (`%(asctime)s [%(levelname)s] %(name)s: %(message)s`),
  **in addition to** the v1.0 stderr handler.
- Opened via a context manager (`observability/cycle_log.py`) that
  **detaches + closes on every exit path** (clean / constrained / abort / kill),
  mirroring v1.0's `publish_bridge_writer` leak-fix. No handler may survive into
  the next cycle in the same process.
- Distinct from `bridge.log`: `cycle.log` = framework `logger.*` output;
  `bridge.log` = extractor-subprocess stderr. Complementary, never merged.

---

## 3. `vault status` verb (FR-009/010/011)

### CLI surface
```
vault status --vault <path> [--json] [--log-level {debug,info,warning,error}]
```
- `--vault` is **required** — no global default; missing ⇒ exit 2 + clear error
  (edge case from spec.md).
- Plain-text by default; `--json` emits the machine object (Q2 locked).
- MUST complete in **<1s** for ≤1000 cycles of history (FR-009) — achieved by
  reading only `state.json` + the last `cycle-NNN-summary.md` + a bounded tail of
  `cycle.log` (no full-history scan).
- Read-only verb; inherits `--log-level` from the v1.0 plumbing.

### Plain output — ACTIVE cycle (FR-010), exactly the 5 data points
```
CYCLE 3 of 5 — stage: research
  elapsed:  47m 19s
  budget:   1h 13m wall remaining · $0.67 of $1.50 remaining
  last log: 2026-06-03 14:49:30 [INFO] …research.dfs: drafting note 'AlphaEvolve'
```
First-second-of-cycle-1 (no state.json yet) ⇒ `CYCLE 1 — (starting)` + elapsed
timer; never crash.

### Plain output — NO active cycle (FR-011)
```
(no active cycle)
CYCLE 2: PASS | 41 notes drafted, 38 verifier-passed | $1.21 spent, $1.50 budget | 1h 04m elapsed | 0 errors, 1 warnings
  last successful cycle: 2 days ago
  deferred warnings: 1 (mistral.ai capture: JS_SHELL)
```
Line 2 is **verbatim** the FR-013 health header of the last cycle.

### `--json` object (stable contract for automation)
```json
{
  "active": true,
  "cycle": 3, "cycles_budgeted": 5, "stage": "research",
  "elapsed_s": 2839,
  "budget": {"wall_remaining_s": 4380, "dollar_remaining": 0.67, "dollar_budget": 1.50},
  "last_log_line": "2026-06-03 14:49:30 [INFO] …research.dfs: drafting note 'AlphaEvolve'",
  "last_cycle_header": null,
  "days_since_last_success": null,
  "deferred_warnings": []
}
```
When `active: false`: `cycle`/`stage`/`elapsed_s`/`last_log_line` null,
`last_cycle_header` = the FR-013 string, `days_since_last_success` + a
`deferred_warnings` list populated.

---

## 4. One-line cycle-health header (FR-013)

**Line 1 of every `cycle-NNN-summary.md`**, produced by a pure
`health_header(cycle_n, summary_inputs) -> str` (also consumed by §3 FR-011 and
spec 035):

```
CYCLE <N>: <STATUS> | <notes_drafted> notes drafted, <verifier_passed> verifier-passed | $<spent> spent, $<budget> budget | <elapsed> elapsed | <errors> errors, <warnings> warnings
```

### Deterministic field sources
| field | source |
|---|---|
| `notes_drafted` | `len(research.notes_created)` |
| `verifier_passed` | quality-report gate counts (notes that passed the verifier gate) |
| `spent` | `research.cumulative_cost_usd` (2 dp) |
| `budget` | settings/033 dollar cap (2 dp; `n/a` if uncapped) |
| `elapsed` | `cycle_end − timings.cycle_started_at` (`<H>h <M>m` / `<M>m <S>s`) |
| `errors` | gate FAIL count + required-source-incident aborts |
| `warnings` | gate WARN count + capture-failure groups + degraded-source notices |

### STATUS derivation (total, deterministic)
- `FAIL` — exit_code == 2 (ABORT) **or** any gate FAIL **or** errors > 0.
- `WARN` — exit_code ∈ {0,1} **and** no FAIL **and** warnings > 0.
- `PASS` — exit_code ∈ {0,1}, no FAIL, 0 warnings.

(Exit 1 = TERMINATE/condition-met is a healthy stop, not a failure.)

---

## 5. Print-allowlist convention (FR-014 / CL-4)

- Enforcement = an extended assertion in
  `tests/observability/test_log_surfaces.py`: re-count `^\s*print\(` across **all**
  of `src/research_framework/pipeline/` and assert the set ⊆ the committed
  `tests/observability/print_allowlist.txt` (no NET-NEW unlisted `print()`).
  **No ruff rule change** — the test is the gate.
- Each allowlisted site MUST carry:
  ```python
  print(...)  # noqa: T201 — keep raw print: <reason>
  ```
  with `reason ∈ {interactive prompt, test-mode signal, CLI usage error, final report stdout contract}`.
- `print_allowlist.txt`: one `relative/path.py:reason` per line; the test parses
  it and cross-checks the inline `# noqa` reason matches.
- Classification of the ~13 current sites (`verifier` 3, `_cycle_helpers` 4,
  `research_plan` 3, `budget_guard` 2, `timings` 1) happens at implement-time:
  **progress-noise → migrate to `logger`; genuinely-raw → allowlist**. A migrated
  site is NOT added to the allowlist (it's gone).

---

## 6. Failure / edge behaviour (all FRs)
- `vault status` on a vault with no `_pipeline/` ⇒ "(no cycles yet)" exit 0.
- Corrupt/partial `state.json` ⇒ treat as no-active-cycle + a one-line warning;
  never traceback.
- `cycle.log` open failure ⇒ log a warning to stderr and continue (observability
  must never fail a cycle — same fail-open posture as v1.0's `bridge.log`).
- Health-header inputs missing ⇒ render `?` for that field, never crash
  (`write_summary` already "never raises").
