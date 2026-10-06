# Quickstart: Quality Harness v3

## Run the default (gating) harness

The `source_quality` family runs automatically — it is part of the
standard gate. No flag change needed:

```bash
./build.sh --quality                      # smoke gate + all 6 fixtures × 4 families
./build.sh --quality --fixture gaming     # one fixture
./build.sh --quality --no-color           # no ANSI
```

Each fixture's report now carries a `metrics.source_quality` subtree with
the 4 metrics. The run still exits 0 (pass), 1 (regression), or 2
(harness error). The opt-in comparison is **not** triggered by this path
and **no** live `claude`/`codex` call is made (Principle IV).

Run the calculator/harness directly during dev:

```bash
.venv/bin/python -m pytest tests/quality/unit/test_source_quality.py -q
.venv/bin/python -m pytest tests/quality/unit/test_typed_step_results.py -q
.venv/bin/python -m research_framework.quality.runner --fixture tech-lite
```

## Run the opt-in with-vs-without-vault `/ask` comparison

This requires a live `claude`/`codex` CLI and is **excluded** from the
default gate and from `release.yml`:

```bash
./build.sh --quality-deep                 # default gate + opt-in comparison
# (equivalently)
./build.sh --quality --comparison
```

Or via pytest, selecting both required markers:

```bash
.venv/bin/python -m pytest tests/quality/test_quality_comparison.py \
  -m "live_llm and quality_comparison" -q
```

If no agent CLI is reachable, or the `quality_comparison` marker is not
selected, the comparison **skips gracefully** (no failure, no
`comparison.json` written). It writes
`_pipeline/quality/<fixture>.comparison.json` with the 4 deltas
(`accuracy_delta`, `specificity_delta`, `citation_density_delta`,
`hallucination_delta`); skipped deltas are `null`.

## Add or re-bless a baseline

Baselines are committed gold-standards; the harness NEVER auto-writes
them. After an intentional metric change (e.g. adding the
`source_quality` subtree), re-bless via the existing flow:

```bash
.venv/bin/python -m research_framework.quality.baseline_update <fixture> \
  --reason "Spec 030 v3 — add source_quality family"
# or the CLI verb if wired:
./vault quality-baseline-update <fixture>
```

Inspect the diff, confirm the new `metrics.source_quality` block looks
right, then `git add tests/fixtures/quality/baselines/<fixture>.baseline.json`.

## Add a new fixture

1. Create `tests/fixtures/quality/<name>/` following the 022 v1 contract
   (see `data-model.md` §3): `research.spec.md`, `settings.yaml`
   (`max_cycles ≤ 3`), `coverage-targets.json`, `_templates/`,
   `fake_agent_responses/`, `data_vault/`, a seeded `_pipeline/sources.db`,
   and `canonical-questions.json`.
2. Register it in `quality/runner.py` (`REGISTERED_FIXTURES` +
   `_NOTE_COUNT_TARGETS`).
3. Run `--fixture <name>` once to produce `<name>.current.json`, bless it
   into `baselines/<name>.baseline.json`, commit both the fixture tree and
   the baseline in the same PR.

> The `_bootstrap_us3_fixtures.py` helper in `tests/fixtures/quality/` is
> the precedent generator for canned fixture vaults — extend it for the 3
> new fixtures rather than authoring trees by hand.

## What is NOT in v3

- `template_section_compliance` (FR-012) — **deferred to v4**.
- Per-release-hotfix tracking (FR-014) — lives as a **`docs/RELEASE.md`
  checklist item**, not a harness metric.
- Cost watch-item fields (FR-013) — **record-only**, ride on the existing
  `cost_efficiency` family; gating is spec 033's domain.
