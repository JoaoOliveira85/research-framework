# Data Model: E2E Quality + Test Harness — Phase 1

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) |
**Research**: [research.md](./research.md)

**Status**: frozen at ship, except § 1's `failure_mode` mapping, amended
2026-09-06 (issue #265) — source-poor's registered mode named something
the fixture cannot reach.

The harness traffics in 6 entities. Each is described below with
fields, types, relationships, and validation rules.

---

## 1. `Fixture`

A named, versioned set of files under
`tests/fixtures/quality/<name>/` that supplies one harness target.

| Field | Type | Notes |
|---|---|---|
| `name` | string | One of the v1 registered names: `tech-lite`, `source-poor`, `source-rich`. v2 extends. |
| `vault_dir` | `pathlib.Path` | Absolute path under `tests/fixtures/quality/`. |
| `spec_path` | `pathlib.Path` | `<vault_dir>/research.spec.md`. |
| `settings_path` | `pathlib.Path` | `<vault_dir>/settings.yaml`. |
| `coverage_targets_path` | `pathlib.Path` | `<vault_dir>/coverage-targets.json`. |
| `fake_agent_responses_dir` | `pathlib.Path` | `<vault_dir>/fake_agent_responses/`. |
| `note_count_target` | int | Architect's vault-shaped guideline: 15–20 notes per cycle. |
| `failure_mode` | string | Documented failure mode the fixture exercises: `code-derived-topic-discovery`, `low-diversity-scout-abort`, `source-quality-pruning`. Descriptive metadata — not part of `current.json` or any baseline. |

**Validation**:
- `name` MUST be in the registered fixture list (constant in
  `src/research_framework/quality/runner.py::REGISTERED_FIXTURES`).
- Every path field MUST exist on disk at harness invocation;
  missing → fail with FR-017 message.
- `failure_mode` MUST match the mapping:
  `tech-lite → code-derived-topic-discovery`,
  `source-poor → low-diversity-scout-abort`,
  `source-rich → source-quality-pruning`.
  The v1 mapping said `source-poor → gap-pursuit-substitution` (FR-011).
  Nothing exercised it: source-poor's canned scout puts every topic in one
  coverage category, so SG-002 fires and aborts the cycle immediately after
  scout on all three cycles — `note_writer` is never dispatched, and no
  substitution can occur. Renamed to what the fixture does (issue #265).
  Reaching the original mode would need a canned `note_writer` loader, a
  scout that clears SG-002, and per-fixture scenario env in the release
  runner; that is a feature, not a rename. The fixture vault's own
  generated prose (`research.spec.md` and everything derived from it)
  still says `gap-pursuit-substitution` — it is a generated vault and
  regenerating it to fix a sentence would churn its whole tree.

---

## 2. `MetricFamily`

A named bundle of related quality metrics. v1 ships three.

| Field | Type | Notes |
|---|---|---|
| `name` | string | `coverage`, `cycle_health`, `note_quality`. v2 adds `source_quality`. |
| `compute_fn` | callable | `Callable[[Fixture, CycleOutput], dict[str, float]]`. Pure function; no side effects. |
| `metrics` | list[str] | The metric keys this family produces. |
| `baseline_subset` | dict | The subset of `metrics` that participates in the regression gate (FR-004). Each entry: `{name: str, direction: "higher_is_better" | "lower_is_better"}`. |

**Validation**:
- `compute_fn` MUST be byte-deterministic for the same `(Fixture,
  CycleOutput)` pair (SC-001).
- All values produced MUST be JSON-serialisable scalars (float, int,
  string, bool) — no `Decimal`, no NumPy types.
- `baseline_subset` MUST be non-empty (a metric family that
  contributes nothing to the gate has no reason to exist).

**v1 metric inventory**:

```text
coverage
  coverage_pct              [higher_is_better]
  notes_per_category        {category: int}    [higher_is_better, per-key]
  spec_drift                [lower_is_better]

cycle_health
  cycles_pass               [higher_is_better]
  cycles_fail               [lower_is_better]
  sg002_trip_count          [lower_is_better]
  retry_once_rate           [neutral; warn only on huge spike]
  verifier_reject_rate      [lower_is_better]   # asserted by spec.md US3 scenario 3 (source-rich no-overpruning)

note_quality
  template_compliance_pct   [higher_is_better]
  per_template_section_fill {section: fill_pct}  [higher_is_better, per-key]
  acronym_link_pct          [higher_is_better]
```

---

## 3. `CycleOutput`

The result of one cycle's `run_cycle_steps` invocation against a
fixture. Read-only handle the harness uses to compute metrics.

| Field | Type | Notes |
|---|---|---|
| `fixture_name` | string | Backref to the originating `Fixture`. |
| `cycle_number` | int | Starts at 1. |
| `exit_code` | int | 0 / 1 / 2 per Constitution Script Exit Code Model. |
| `quality_report_path` | `pathlib.Path` | `<vault>/_pipeline/cycles/cycle-NNN-quality-report.json`. |
| `research_report_path` | `pathlib.Path` | `<vault>/_pipeline/cycles/cycle-NNN-research.json`. |
| `notes_written` | list[`pathlib.Path`] | Discovered by walking `<vault>/data_vault/` between pre/post cycle snapshots. |
| `scout_topics` | list[dict] | Parsed from research-report JSON. |
| `sg_trips` | list[str] | SG-NNN gate names that fired this cycle. |

**Validation**: read-only model. The harness never writes to its
fields; metric compute_fns read them.

---

## 4. `BaselineJSON`

The committed gold-standard file per fixture, under
`tests/fixtures/quality/baselines/<fixture>.baseline.json`.

Schema (versioned, see § 6 below for full contract):

```json
{
  "schema_version": "1.0",
  "fixture": "tech-lite",
  "baseline_commit": "abc123…",
  "last_updated": "2026-05-21T15:00:00Z",
  "last_updated_by": "Joao Oliveira",
  "last_updated_reason": "Initial baseline at spec 022 ship.",
  "coverage_targets_hash": "sha256:def456…",
  "metrics": {
    "coverage": { "coverage_pct": 0.83, "notes_per_category": {...}, "spec_drift": 0.12 },
    "cycle_health": { "cycles_pass": 5, "cycles_fail": 0, "sg002_trip_count": 0, "retry_once_rate": 0.05 },
    "note_quality": { "template_compliance_pct": 0.95, "per_template_section_fill": {...}, "acronym_link_pct": 0.88 }
  }
}
```

**Validation**:
- `schema_version` MUST match the harness's known versions.
- `coverage_targets_hash` MUST match the current fixture's hash
  (D3); mismatch → fail with "baseline stale" message.
- `metrics` MUST contain entries for all `MetricFamily`s the harness
  knows about; extra entries are ignored (forward compat).
- File MUST be byte-deterministic per D2 (`sort_keys=True`,
  `indent=2`).

**Lifecycle**:
- Created in the ship PR for spec 022 v1 (FR-016, ship-PR-blessed).
- Mutated only by `./vault quality-baseline-update <fixture>`
  (FR-007, FR-012).
- Read by every harness invocation.

---

## 5. `CurrentJSON`

The runtime output of one harness invocation per fixture. Same
schema as `BaselineJSON` minus the `last_updated*`,
`baseline_commit`, and `coverage_targets_hash` fields (those are
re-derived at compare time).

```json
{
  "schema_version": "1.0",
  "fixture": "tech-lite",
  "run_timestamp": "2026-05-21T15:00:00Z",
  "coverage_targets_hash": "sha256:def456…",
  "metrics": { … same shape as baseline … }
}
```

**Validation**:
- Written to `_pipeline/quality/<fixture>.current.json` (gitignored).
- Deterministic per D2; the same commit produces byte-identical
  `current.json` files except for `run_timestamp`.

**Lifecycle**: ephemeral; overwritten on every harness run.

---

## 6. `RegressionReport`

The aggregated diff result across all fixtures in one harness run.

```json
{
  "schema_version": "1.0",
  "run_timestamp": "2026-05-21T15:00:00Z",
  "harness_version": "0.2.34",
  "verdict": "pass" | "warn" | "fail",
  "fixtures": {
    "tech-lite": {
      "verdict": "pass" | "warn" | "fail",
      "metric_diffs": {
        "<family>.<metric>": {
          "baseline": float,
          "current": float,
          "delta_pct": float | "n/a",
          "direction": "higher_is_better" | "lower_is_better",
          "verdict": "pass" | "warn" | "fail"
        }
      },
      "summary": "<N> regressions, <M> warnings"
    },
    "source-poor": { … },
    "source-rich": { … }
  }
}
```

**Validation**:
- Per-metric `verdict` derived from `delta_pct` and `direction`:
  - `pass` if `delta_pct >= 0` or `|delta_pct| < 5%` (rounding).
  - `warn` if `5% <= |delta_pct| < 15%` and the change is in the
    wrong direction.
  - `fail` if `|delta_pct| >= 15%` and the change is in the wrong
    direction.
- Per-fixture `verdict` = worst of its metric verdicts.
- Top-level `verdict` = worst of its fixture verdicts.
- Exit code: 0 if `pass | warn`; 1 if any `fail`.

**Lifecycle**:
- Written to `_pipeline/quality/regression-report.json` (gitignored).
- Streamed to stdout in human-readable form.
- Picked up by CI workflow (D5) as a workflow artifact (optional v2;
  v1 only relies on exit code).

---

## Relationships

```text
Fixture (1) ──< CycleOutput (N, one per cycle in the harness run)
Fixture (1) ──< CurrentJSON (1, per harness run)
Fixture (1) ──< BaselineJSON (1, committed; rare updates)
MetricFamily (3, registered) ── computes ──> per-fixture metric subsets

CurrentJSON  ┐
              ├── diff() ──> per-fixture metric_diffs ──> RegressionReport
BaselineJSON ┘
```

## State transitions (BaselineJSON)

```text
[NONEXISTENT]
    │
    │  (1) ship-PR-blessed initial creation (FR-016)
    │      via `./build.sh --quality` + manual commit
    ▼
[COMMITTED]
    │
    │  (2) `./vault quality-baseline-update <fixture>` + --reason "..."
    │      (FR-007: explicit human action only)
    ▼
[COMMITTED (updated)]
    │
    │  (rare) baseline rotation across releases — same as (2)
    ▼
…

Forbidden transitions:
  [COMMITTED] → [COMMITTED]  via any non-CLI codepath  ← guarded by FR-012
  [NONEXISTENT] → [COMMITTED]  via auto-create        ← guarded by FR-017
```

## Open data-model items (deferred)

- **OI-D1**: Whether `per_template_section_fill` should be a flat
  dict or a list of `{section, fill_pct}` records for stable
  diffing. Tentative: dict (alphabetical key order satisfies
  determinism); revisit if v2 needs nested sections.
- **OI-D2**: Whether to expose `harness_version` as the package
  version or a hand-set spec-22 schema number. Tentative: package
  version; advances naturally with each release.
- **OI-D3**: Whether `notes_per_category` and
  `per_template_section_fill` should themselves be regression-
  gated (per-key) or only their roll-ups. Tentative: only roll-ups
  in v1; nested per-key gating is v2.
