# Contract: Baseline JSON Schema (and CurrentJSON / RegressionReport)

**Spec**: [`../spec.md`](../spec.md) | **Data model**: [`../data-model.md`](../data-model.md) §4–§6
**Status**: Draft (locked at Phase 1; FR-008 and FR-016 reference)

This contract pins the JSON shapes the harness writes and reads.
Any change to these shapes is a **breaking change** that requires:
(a) bumping `schema_version`, (b) a migration note in `CHANGELOG.md`,
(c) baseline regeneration (`./vault quality-baseline-update <fixture>`
for every committed baseline).

## 1. `BaselineJSON` (committed under `tests/fixtures/quality/baselines/`)

```json
{
  "schema_version": "1.0",
  "fixture": "tech-lite",
  "baseline_commit": "1b34c2b40e7a8…",
  "last_updated": "2026-05-21T15:00:00Z",
  "last_updated_by": "Joao Oliveira",
  "last_updated_reason": "Initial baseline at spec 022 ship.",
  "coverage_targets_hash": "sha256:def456abcdef…",
  "metrics": {
    "coverage": {
      "coverage_pct": 0.83,
      "notes_per_category": {
        "services": 4,
        "concepts": 2,
        "flows": 3
      },
      "spec_drift": 0.12
    },
    "cycle_health": {
      "cycles_pass": 5,
      "cycles_fail": 0,
      "sg002_trip_count": 0,
      "retry_once_rate": 0.05
    },
    "note_quality": {
      "template_compliance_pct": 0.95,
      "per_template_section_fill": {
        "summary": 1.0,
        "context": 0.93,
        "decisions": 0.88
      },
      "acronym_link_pct": 0.88
    }
  }
}
```

### Field rules

- **`schema_version`** — exact match required. v1 = `"1.0"`.
- **`fixture`** — MUST be one of the registered fixture names. Used
  for cross-reference with `coverage_targets_hash`.
- **`baseline_commit`** — short or long SHA of the commit when this
  baseline was blessed. Informational; harness does not verify.
- **`last_updated`** — ISO 8601 UTC timestamp with `Z` suffix.
- **`last_updated_by`** — free-form string. CLI defaults to
  `$GIT_AUTHOR_NAME` then `$USER`.
- **`last_updated_reason`** — REQUIRED non-empty string. The CLI
  rejects a baseline-update without `--reason "<text>"`.
- **`coverage_targets_hash`** — `sha256:<hex>` of the canonical-JSON
  serialisation of the fixture's `coverage-targets.json` keys +
  per-category required counts (D3). Recomputed at harness invocation
  time; baseline run fails if the hash mismatches.
- **`metrics`** — keys are the registered `MetricFamily` names.
  Extra keys ignored (forward compat); missing keys = baseline
  is older than the current harness and needs refresh.

### Determinism (FR-003)

- Written with `json.dumps(payload, sort_keys=True, indent=2,
  separators=(",", ": "), ensure_ascii=False)`.
- Newline at EOF.
- All inner `dict`s sorted by key. All inner `list`s sorted by a
  deterministic, documented key (usually `category` or `fixture`).
- `float` values truncated to 4 decimal places at compute time
  (avoids platform-dependent precision diffs).

## 2. `CurrentJSON` (gitignored under `_pipeline/quality/`)

Same as `BaselineJSON` MINUS:
- `baseline_commit`
- `last_updated`, `last_updated_by`, `last_updated_reason`

PLUS:
- `run_timestamp` — ISO 8601 UTC; **excluded from determinism
  comparison** (the harness's `_assert_deterministic` helper skips
  this field).

## 3. `RegressionReport` (gitignored under `_pipeline/quality/`)

```json
{
  "schema_version": "1.0",
  "run_timestamp": "2026-05-21T15:00:00Z",
  "harness_version": "0.2.34",
  "verdict": "pass",
  "fixtures": {
    "tech-lite": {
      "verdict": "pass",
      "metric_diffs": {
        "coverage.coverage_pct": {
          "baseline": 0.83,
          "current": 0.83,
          "delta_pct": 0.0,
          "direction": "higher_is_better",
          "verdict": "pass"
        }
      },
      "summary": "0 regressions, 0 warnings"
    }
  }
}
```

### Field rules

- **`schema_version`** = `"1.0"` (independent of BaselineJSON's).
- **`harness_version`** = `research_framework.__version__` at
  invocation time.
- **`verdict`** at any level: `"pass"` | `"warn"` | `"fail"`.
  Rolls up to top level as `max(fixture.verdict)` where
  `fail > warn > pass`.
- **`delta_pct`** — `(current - baseline) / baseline * 100`,
  rounded to 1 decimal place. `"n/a"` if `baseline == 0` (avoid
  divide-by-zero).
- **Per-metric `verdict`** rule:
  - `direction == "higher_is_better"` and `delta_pct < -15%` → `fail`
  - `direction == "higher_is_better"` and `-15% ≤ delta_pct ≤ -5%` → `warn`
  - `direction == "lower_is_better"` and `delta_pct > 15%` → `fail`
  - `direction == "lower_is_better"` and `5% ≤ delta_pct ≤ 15%` → `warn`
  - Otherwise → `pass`.
  - **`baseline == 0` (issue #267)** — the 5%/15% band above needs a real
    percentage, which `delta_pct: "n/a"` is not. `direction ==
    "lower_is_better"` → `fail` if `current > 0`, else `pass`: these
    metrics are non-negative counts/rates baselined at the best possible
    reading, so any real increase off zero is the regression in full, with
    no magnitude to place it in a band. `direction == "higher_is_better"`
    is unaffected by this rule and falls through to `pass`: these metrics
    are also non-negative, so a `0` baseline is already the *worst*
    possible reading and nothing can regress below it.
- **Exit code** — non-zero if top-level `verdict == "fail"`. Zero
  otherwise.

## 4. Schema versioning

When bumping `schema_version`:

1. Add a `_LEGACY_SCHEMA_VERSIONS` constant in
   `src/research_framework/quality/baseline.py` listing readable
   prior versions for migration.
2. Add a migration function `migrate_v<old>_to_v<new>(payload) ->
   payload`.
3. Update this contract document with the new schema.
4. Add a `CHANGELOG.md` entry under the version block introducing
   the change, with a `(regression test: tests/quality/unit/
   test_baseline_migration.py)` annotation per ADR-0008.
5. Run `./vault quality-baseline-update <fixture> --reason "schema
   v<old> → v<new>"` for each fixture.

Forward-compat rule: harness MUST tolerate baselines with
*extra* unknown keys at any depth (so a newer fixture seed can be
committed without breaking older harness runs). Harness MUST NOT
tolerate baselines with *missing* required keys (those are an
error, not a default).
