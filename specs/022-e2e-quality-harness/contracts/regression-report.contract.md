# Contract: Harness Output & Regression Report

**Spec**: [`../spec.md`](../spec.md) FR-004, FR-010 |
**Schema**: [`baseline-schema.contract.md`](./baseline-schema.contract.md) § 3

Defines the harness's behavioural contract — exit codes, stdout
format, side-effect files.

## 1. Invocation modes

| Mode | Entry point | Audience |
|---|---|---|
| Build script | `./build.sh --quality [--fixture <name>]` | Local dev + CI |
| Direct pytest | `pytest -m e2e tests/quality/` | Developer debugging |
| Python API | `research_framework.quality.runner.run(fixtures=[...])` | Internal callers; not stable public API |

All three modes converge on the same `runner.run()` function and
produce identical side effects.

## 2. Exit codes

| Code | Meaning |
|---|---|
| `0` | All fixtures pass OR all warn (no `fail`). |
| `1` | At least one fixture has at least one metric with `verdict == "fail"`. |
| `2` | Harness itself crashed (uncaught exception, missing baseline file per FR-017, fixture vault not initialised, etc.). |

Exit code `1` and `2` MUST be distinguishable: code 1 = quality
regression (data signal); code 2 = harness brokenness (need to
investigate the harness, not the cycle output).

## 3. Stdout format (per FR-010)

Pretty-printed, ANSI-colour-optional, parseable structure. Example:

```text
=== Quality Harness Run ===
  Harness version : 0.2.34
  Timestamp       : 2026-05-21T15:00:00Z
  Fixtures        : 3 (tech-lite, source-poor, source-rich)

--- tech-lite ---
  Status: PASS
  coverage.coverage_pct           = 0.8300  (baseline 0.8300, Δ +0.0%)  ✓
  cycle_health.sg002_trip_count   = 0       (baseline 0,      Δ n/a)   ✓
  note_quality.template_compl_pct = 0.9500  (baseline 0.9500, Δ +0.0%)  ✓
  note_quality.acronym_link_pct   = —       (UNMEASURED: no_acronym_occurrences_in_notes)  ∅
  Summary: 0 regressions, 0 warnings, 1 unmeasured

--- source-poor ---
  Status: WARN
  coverage.coverage_pct           = 0.5500  (baseline 0.6000, Δ -8.3%)  ⚠  WARN
  …

--- source-rich ---
  Status: PASS
  …

=== Verdict: WARN ===
  3 fixtures checked: 2 pass, 1 warn, 0 fail
  Regression report: _pipeline/quality/regression-report.json
```

- Header section: version + timestamp + fixture list.
- Per-fixture section: status + per-metric line with value,
  baseline, delta, and pass/warn/fail indicator.
- **Unmeasured gated metrics** (added 2026-09-06, issue #268): a metric
  whose denominator was empty this run carries no value to diff and so
  no verdict. It is listed after the diffed metrics as
  `= — (UNMEASURED: <reason>) ∅`, counted in the `Summary:` line
  (`", N unmeasured"`, omitted when N is 0), and emitted in
  `regression-report.json` as `fixtures.<name>.unmeasured`, a
  `{"<family>.<metric>": "<reason>"}` map. It never changes a verdict.
  Rationale: reporting `0.0` for "nothing to divide" made a
  non-measurement read as a passing gate.
- Footer: rolled-up verdict + summary counts + path to JSON report.
- ANSI colours: `--no-color` flag disables; auto-disable when
  stdout is not a TTY.

## 4. Side-effect files

The harness writes the following files. All are gitignored.

| Path | Purpose | Lifetime |
|---|---|---|
| `_pipeline/quality/<fixture>.current.json` | Per-fixture metric capture (FR-003 byte-deterministic) | overwritten per run |
| `_pipeline/quality/regression-report.json` | Aggregated diff report (contract above § 3) | overwritten per run |
| `_pipeline/quality/<fixture>/cycle-NNN-*` | Per-cycle outputs from cycle_runner | overwritten per run |
| `_pipeline/quality/<fixture>/logs/<stage>.log` | Stage-specific harness log | overwritten per run |

The harness MUST NOT write to:
- `tests/fixtures/quality/baselines/*.baseline.json` (FR-007, guard tested in FR-012)
- `tests/fixtures/quality/<fixture>/**` (fixture vaults are read-only at harness time)
- Any path outside `_pipeline/` (per Constitution Principle V — repo isolation)

## 5. Failure messaging (FR-010, FR-017)

When the harness exits non-zero, the final line of stderr MUST
contain a one-line reproduction recipe. Format:

```text
HARNESS FAILED: <category>. Reproduce with: ./build.sh --quality --fixture <name>
```

Where `<category>` ∈ `{"regression", "baseline-missing",
"baseline-stale", "fixture-not-initialised",
"cycle-runner-crash", "determinism-violation"}`.

Specific messages by category:

- **regression** — "<fixture>.<metric> dropped <X>% (baseline=<B>,
  current=<C>); see _pipeline/quality/regression-report.json"
- **baseline-missing** — "baseline missing for fixture
  <fixture>; run `./build.sh --quality` locally on the ship branch
  and commit the generated baseline" (per FR-017)
- **baseline-stale** — "baseline stale for fixture <fixture>;
  coverage-targets-hash mismatch (baseline=<B>, current=<C>);
  re-baseline required via `./vault quality-baseline-update <fixture>`"
- **fixture-not-initialised** — "fixture <fixture> not initialised
  — run `./vault quality-fixture-init <fixture>` first"
- **cycle-runner-crash** — "cycle runner crashed on fixture
  <fixture> cycle <N>; see _pipeline/quality/<fixture>/logs/"
- **determinism-violation** — "fixture <fixture> produced
  non-deterministic output across two back-to-back runs; diff at
  _pipeline/quality/<fixture>.current-diff.txt"

## 6. Performance (SC-006)

- Harness-only wall-clock < 10 min on a recent Mac (Apple M1 Pro,
  16 GB RAM). CI ubuntu-latest may be ~30% slower; budget there is
  < 13 min for the harness portion.
- Per-fixture cycle invocation budgeted at < 3.5 min (3 fixtures
  × 3.5 min = 10.5 min cap; report aggregation < 30 s adds back).
- The harness prints elapsed wall-clock per fixture in the stdout
  format above (informational; no hard gate beyond SC-006).
