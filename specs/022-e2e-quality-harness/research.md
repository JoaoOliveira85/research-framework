# Research: E2E Quality + Test Harness — Phase 0

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)
**Date**: 2026-05-21

The clarify session (`spec.md` § Clarifications) locked the macro
design (scope, fixture realism, performance, CI trigger, baseline
flow). This research file resolves the remaining *implementation-
level* patterns needed before Phase 1 design.

For each topic: **Decision** (chosen approach), **Rationale**
(why), **Alternatives considered** (what else was on the table).

---

## D1 — Fake-agent scenario selection contract

**Decision**: Reuse the existing per-stage env-var dispatch in
`tests/_helpers/fake_agent.py` (lines 53–74 at v0.2.33).
`_SCENARIO_ENV_GLOBAL = "FAKE_AGENT_SCENARIO"`; per-stage overrides
via `FAKE_AGENT_<STAGE>_SCENARIO` (e.g.
`FAKE_AGENT_VERIFIER_SCENARIO=reject`). The harness sets the relevant
env vars per fixture before invoking the cycle runner. Per-fixture
scenarios live as static JSON in `tests/fixtures/quality/<fixture>/
fake_agent_responses/<stage>/<scenario>.json`.

**Rationale**: The pattern already exists, is documented in the
fake-agent contract (`specs/018-testing-strategy/contracts/fake-agent.contract.md`),
and is exercised by ~20 existing tier-3/4/5 tests. Building a new
selector would fragment the test surface and require updating
spec 024's fake-agent contract twice (once for the new stages and
again for a new selector). The existing contract already accepts
scenario discovery from a directory tree — we just point it at our
fixture's directory.

**Alternatives considered**:
- A new harness-specific selector (e.g. fixture-name-as-selector
  `FAKE_AGENT_FIXTURE=tech-lite`) — rejected because it duplicates
  the existing env-var dispatch with no functional gain.
- Per-fixture monkeypatching of fake_agent functions — rejected
  because it would couple the harness to fake_agent internals
  (the contract intentionally hides those).
- A YAML/TOML manifest file declaring all scenarios — rejected as
  premature; the JSON-file-per-scenario pattern is already in use
  and scales fine to ~3 fixtures × 5 stages = ~15 files per
  fixture.

---

## D2 — Deterministic JSON serialisation

**Decision**: All harness-written JSON (current.json, baseline.json,
regression-report.json) uses
`json.dumps(payload, sort_keys=True, indent=2, separators=(",", ": "),
ensure_ascii=False)` with `\n` line endings and a trailing newline.
All `dict` values are pre-sorted (by key) before write. All `list`
values are pre-sorted (by deterministic key — usually `category` or
`fixture_name`) unless order is semantically meaningful.

**Rationale**: SC-001 requires byte-identical reruns. The Python
stdlib `json.dumps` with `sort_keys=True` is deterministic *for
basic types*; nondeterminism enters via dict-of-list-of-dict
shapes where the inner list's order matters. Sorting all lists by
a documented key (and rejecting unsortable structures at type-
check time) gives full reproducibility. `indent=2` makes diffs
human-readable in PR review (per SC-001's reviewer-eyeballed
ship-PR-blessed flow).

**Alternatives considered**:
- `json.dumps(sort_keys=True)` only (no list-sort) — rejected
  because list-order is the most common source of harness flakes.
- Use `orjson` or `simplejson` for performance — rejected (no new
  runtime deps per Principle V; and the payload is small enough
  that stdlib is fine).
- A pickle-based snapshot with hash comparison — rejected because
  pickle isn't human-readable in PR review and is platform-
  dependent.
- YAML output — rejected because YAML float/null handling is less
  deterministic than JSON.

The harness contains a `_assert_deterministic(payload)` helper
that re-serialises and compares; CI runs it twice per fixture
(SC-001 acceptance scenario US2 §1).

---

## D3 — Coverage targets hash strategy

**Decision**: Hash the fixture's `coverage-targets.json` with
SHA-256 over the canonical-JSON (D2) serialisation of the object's
**keys + per-category required counts** only — not over `current`
counts or any other mutable field. Store as
`coverage_targets_hash` in baseline.json; reject runs whose
fixture's hash diverges from the baseline's stored hash.

**Rationale**: A baseline tied to a stale spec is worse than no
baseline — the metric "% coverage met" depends entirely on what
the targets are. Hashing only the *contract* fields (keys, required
counts) lets `current` counts vary across cycles without
invalidating the baseline. The harness fails closed with "baseline
stale for fixture `<name>`; re-baseline required" (Edge Cases in
spec.md).

**Alternatives considered**:
- Hash the entire `coverage-targets.json` blob — rejected because
  `current` counts change every cycle, which would force a
  re-baseline after every test run (defeats the gate).
- No hash; just trust the path — rejected because fixture spec
  drift would silently invalidate metrics.
- Hash the fixture's `research.spec.md` body — rejected because
  the spec is the *input*, but `coverage-targets.json` is the
  *derived contract* the cycle runner consumes; hashing the spec
  would re-trigger on every prose edit.

---

## D4 — Per-fixture cycle invocation API

**Decision**: The harness invokes the cycle runner **in-process**
by importing
`research_framework.pipeline.cycle_runner.run_cycle_steps` (the
existing public API) and calling it with the fixture's vault
directory as `vault_dir`. Each cycle's output lands under the
fixture's `_pipeline/` subdir (which is `.gitignore`d for fixture
vaults so test runs don't dirty the repo).

**Rationale**: Subprocess invocation (`./vault research --vault
<fixture>`) is the production CLI path but adds ~3 seconds per
fixture-cycle for process startup. Across 3 fixtures × 6 cycles
each = 18 invocations × 3 s = 54 s of pure overhead. In-process
invocation is faster (fits the < 10 min budget) and gives the
harness direct access to the cycle's return value (exit code +
quality report path). The cycle runner's public API is stable per
spec 025 US6 (B3 cycle-step extraction will preserve
`run_cycle_steps` signature).

**Alternatives considered**:
- Subprocess invocation — rejected on performance + the harness
  would still need to read the quality report from disk to extract
  metrics; in-process gives direct access.
- A new "harness mode" flag on `run_cycle_steps` — rejected as
  unnecessary; the fake-agent env vars already gate behaviour
  appropriately.
- Mock-based unit testing of metric calculators against fabricated
  cycle output (no real cycle invocation) — rejected because it
  would NOT catch regressions in the cycle runner itself (which is
  the harness's primary value). Mock-based unit tests still ship
  as the tier-1 layer (`tests/quality/unit/`).

**Risk noted**: in-process invocation means a fixture-cycle crash
crashes the harness process. Mitigation: wrap each fixture's cycle
run in a `try/except` that records the crash as a "fixture
failed" metric (cycle_health.metric records the failure) and
continues to the next fixture. Total harness exit code is non-zero
if any fixture failed.

---

## D5 — GitHub Actions tag-trigger + workflow_dispatch pattern

**Decision**: `.github/workflows/quality.yml` triggers on:

```yaml
on:
  push:
    tags:
      - 'v[0-9]+.[0-9]+.[0-9]+'
      - 'v[0-9]+.[0-9]+.[0-9]+-*'
  workflow_dispatch:
    inputs:
      fixture:
        description: 'Optional — limit harness to one fixture (tech-lite, source-poor, source-rich); default = all'
        required: false
        default: 'all'
```

Job runs on `ubuntu-latest` (matching `release.yml`'s OS choice).
Steps: checkout, set up Python 3.11, `pip install -e .`, run
`./build.sh --quality` (passing the optional `--fixture` argument
when triggered via dispatch). Failure exits non-zero.

**Rationale**: Tag-trigger format mirrors the existing
`release.yml` (`.github/workflows/release.yml:28-34`) so the
project has one tag-pattern convention. `workflow_dispatch` with a
single `fixture` input gives developers a manual-fire option from
the GitHub Actions UI per Q4's mitigation. `ubuntu-latest`
matches release infrastructure (Linux CI is also queue #2 of
ROADMAP — this workflow contributes evidence the framework runs
on Linux).

**Alternatives considered**:
- Self-hosted runner — rejected (no runner infrastructure exists;
  ubuntu-latest is free for public repos).
- Matrix over `[macos-latest, ubuntu-latest]` — rejected for v1;
  macOS minutes are 10× more expensive on GH-hosted runners.
  Reconsider for v2 if macOS-specific bugs surface.
- Composite action wrapping the harness — rejected; the workflow
  is short enough that an inline `run:` block is more legible.
- Trigger on `release: published` event instead of `push: tags` —
  rejected because `release.yml` already publishes the release
  *after* the tag-push run completes; quality should gate the tag,
  not the release.

---

## D6 — Fixture vault authoring pattern

**Decision**: Extend `tests/_helpers/vault_factory.py` with a new
function `build_quality_fixture(name, vault_dir, spec_yaml,
note_count_target)` that:

1. Writes a `research.spec.md` per the fixture's parameter spec.
2. Writes a `settings.yaml` that points `cycle.runner.fake_agent`
   at the fixture's `fake_agent_responses/` directory.
3. Writes `coverage-targets.json` matching the spec.
4. Writes a `_templates/` directory mirroring the production
   templates.
5. Writes the `fake_agent_responses/` tree (handed in by caller as
   static JSON files committed to the fixture dir).

The function is called **once at fixture-author time** to
bootstrap each fixture; the result is committed to the repo. The
harness never re-runs the factory at test time.

**Rationale**: `vault_factory.build_minimal_vault(...)` already
exists for tier-3/4/5 vault factories. Adding a sibling for
quality fixtures keeps the pattern consistent. Bootstrapping
fixtures via a function (vs hand-authoring each file) ensures
all three fixtures share the same skeletal layout — any future
template change is a one-line edit.

**Alternatives considered**:
- Hand-author each fixture as static markdown/JSON files — rejected
  because all three fixtures share ~80% of the structure; a
  factory eliminates that boilerplate.
- Reuse `build_minimal_vault` directly — rejected because the
  minimal vault is too minimal (no fake_agent_responses/ tree).
- Generate fixtures dynamically at harness invocation time —
  rejected because it would mean the fixture vault is not a
  fixed test artifact (regression-detection requires fixed
  inputs).

---

## D7 — Pytest tier-6 marker combination

**Decision**: Harness tests at `tests/quality/test_quality_harness_*.py`
carry `@pytest.mark.e2e` + `@pytest.mark.slow`. Unit tests at
`tests/quality/unit/test_*.py` carry no e2e marker (run in fast
loop). Both are collected by `pytest tests/quality/`; only e2e
runs in the harness-gating CI.

**Rationale**: ADR-0008 § Pytest markers introduced `@pytest.mark.slow`
as the canonical slow-test marker; `@pytest.mark.e2e` is the
canonical e2e marker. Combining both is the standard tier-6 shape
(`docs/testing-strategy.md` tier-6 row). Unit tests for metric
calculators are tier-1 and contribute to fast local loop coverage
(< 30 s per file budget per ADR-0008 fast-loop convention).

**Alternatives considered**:
- A custom `@pytest.mark.harness` marker — rejected per ADR-0008's
  decision to consolidate (no proliferating markers).
- Put all tests under `@pytest.mark.e2e` (including unit) —
  rejected because metric-calculator unit tests are fast and
  should run in `pytest -m "not e2e"`.
- A separate `tests/harness/` directory — rejected; `tests/quality/`
  is already named in ADR-0008's boundary table (`Surfaces covered
  (reference map)` row 22 mentions `tests/fixtures/quality/`).

---

## D8 — Baseline-update CLI design

**Decision**: New `./vault quality-baseline-update <fixture>`
subcommand backed by `src/research_framework/quality/baseline_update.py`.
Flags:

- positional `<fixture>` — one of `tech-lite`, `source-poor`,
  `source-rich` (validated against a registered fixture list).
- `--dry-run` — print the diff that would be written, exit 0
  without writing (Constitution Always Do #2: every vault-mutating
  script must offer `--dry-run`).
- `--reason "<text>"` — required when not `--dry-run`; persisted
  to baseline.json as `last_updated_reason`.
- `--actor "<text>"` — defaults to `$GIT_AUTHOR_NAME` or
  `$USER`; persisted as `last_updated_by`.
- `--yes` — skip the interactive stdin confirmation (CI use only,
  not recommended for local).

Behaviour: run the harness once for the fixture, write
`<fixture>.current.json`, present the diff vs the existing
baseline (if any), prompt the user, write on confirmation.

**Rationale**: FR-007 requires baseline updates be explicit and
human-confirmed. The CLI is the *only* path that writes baselines
(FR-012 guard test enforces). `--reason` requirement gives the
git diff plus baseline JSON a clear human rationale ("blessed
new baseline because cycle health metric improved after spec-020
A1 landed").

**Alternatives considered**:
- A `--update-baseline` flag on `./build.sh --quality` — rejected
  because it would entangle the regression-check and baseline-update
  flows; cleaner to keep them as distinct surfaces.
- A bare `quality-baseline` subcommand with `--update` / `--show` /
  `--diff` modes — rejected as over-designed; one explicit verb
  per action is more legible.
- Git pre-commit hook that prompts on baseline diff — rejected
  because pre-commit hooks aren't universally installed.

---

## D9 — Regression report format

**Decision**: Harness writes `_pipeline/quality/regression-report.json`
with this top-level shape:

```json
{
  "schema_version": "1.0",
  "run_timestamp": "2026-05-21T15:00:00Z",
  "harness_version": "0.2.34",
  "verdict": "pass | warn | fail",
  "fixtures": {
    "tech-lite": {
      "verdict": "pass | warn | fail",
      "metric_diffs": {
        "coverage.coverage_pct": {"baseline": 0.83, "current": 0.83, "delta_pct": 0.0, "verdict": "pass"},
        "cycle_health.sg002_trip_count": {"baseline": 0, "current": 1, "delta_pct": "n/a", "verdict": "warn"}
        // … etc
      },
      "summary": "0 regressions, 1 warning"
    },
    // source-poor, source-rich
  }
}
```

Harness also prints a human-readable summary to stdout (per FR-010).

**Rationale**: A structured report file lets future tooling (e.g. a
GitHub Actions status comment) read the result programmatically;
the stdout summary serves humans. The `verdict` field at multiple
levels makes the diff easy to grep / parse in CI logs.

**Alternatives considered**:
- Markdown report — rejected because parseable structured data is
  the higher-value primary; markdown can be rendered from JSON.
- Per-metric JSON files — rejected as over-fragmented for v1.
- Embed the report in the existing cycle quality report — rejected
  because the harness operates across multiple cycles per fixture;
  a top-level harness report is a cleaner home.

---

## Open items (deferred to /speckit.tasks or impl)

- **OI-1**: Determining exactly which `coverage-targets.json` fields
  count as "contract" vs "state" for D3's hash. Tentative: hash
  the `categories[].{name, required_count, note_type}` triples.
  Will be locked when writing the first baseline (Phase 2 ship-PR
  blessing).
- **OI-2**: Exact thresholds for the **moderate** regression gate
  (>15% fail / 5–15% warn). Spec.md still flags this as
  `[PROPOSED]`. Lock by writing a single constant in
  `src/research_framework/quality/baseline.py` and referencing it
  from FR-004 acceptance scenarios.
- **OI-3**: Whether the harness should fail or warn on
  fixture-internal cycle-runner exceptions. Tentative: warn (record
  as cycle-health metric); fail only if ALL fixtures crash. Lock
  in tasks.md.
