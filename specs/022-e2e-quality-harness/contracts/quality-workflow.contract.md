# Contract: `.github/workflows/quality.yml`

**Spec**: [`../spec.md`](../spec.md) FR-014 |
**Research**: [`../research.md`](../research.md) D5

Defines the GitHub Actions workflow that runs the quality harness
in CI. Locked by clarify Q4 (Option B: tag-push + `workflow_dispatch`
only; no PR trigger).

## 1. Triggers

```yaml
on:
  push:
    tags:
      - 'v[0-9]+.[0-9]+.[0-9]+'
      - 'v[0-9]+.[0-9]+.[0-9]+-*'   # pre-release suffixes (v0.3.0-rc1, etc.)
  workflow_dispatch:
    inputs:
      fixture:
        description: 'Optional — limit to one fixture (tech-lite | source-poor | source-rich); default = all'
        required: false
        default: 'all'
        type: choice
        options:
          - all
          - tech-lite
          - source-poor
          - source-rich
```

### Triggers MUST NOT include

- `push:` (any branch, including `main`) — would defeat Q4's
  no-per-PR-cost decision.
- `pull_request:` — same as above.
- `schedule:` — not in v1 (would require nightly tokens).
- `release:` — release-tag triggering would race with
  `release.yml`; `push: tags` is the canonical trigger.

## 2. Job structure

Single job, single OS for v1.

```yaml
jobs:
  quality:
    name: Quality regression harness
    runs-on: ubuntu-latest
    timeout-minutes: 20   # SC-006 = 12 min + 8 min CI overhead headroom

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install
        run: |
          python -m pip install --upgrade pip
          pip install -e .[dev]

      - name: Run quality harness
        run: |
          ./build.sh --quality ${{ github.event_name == 'workflow_dispatch' && format('--fixture {0}', inputs.fixture) || '' }} --no-color

      - name: Upload regression report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: regression-report-${{ github.run_id }}
          path: _pipeline/quality/regression-report.json
          retention-days: 30
```

### Constraints

- `runs-on: ubuntu-latest` matches `release.yml`. macOS runners
  are 10× more expensive on GH-hosted infra and not warranted
  for v1.
- `timeout-minutes: 20` is a hard kill — gives 8 min of slack vs
  the 12 min target. If the workflow ever hits this timeout, the
  fix is to optimise the harness, not raise the limit.
- `actions/checkout@v4`, `actions/setup-python@v5`,
  `actions/upload-artifact@v4` pinned to major versions (consistent
  with `release.yml`).
- `pip install -e .[dev]` to pick up `pytest` and other test deps.
- The harness step uses GitHub Actions's `format()` to inject the
  `--fixture` argument only when triggered via dispatch.
- Artifact upload is `if: always()` so the JSON report is captured
  even on failure (key for debugging post-mortem).

## 3. Permissions

```yaml
permissions:
  contents: read   # checkout only; never writes back
```

The workflow MUST NOT have `contents: write`. Unlike `release.yml`
(which creates tags + releases), `quality.yml` is pure-read; any
write attempt is a violation.

## 4. Concurrency

```yaml
concurrency:
  group: quality-${{ github.ref }}
  cancel-in-progress: true
```

Cancel any in-progress harness run for the same ref when a new
trigger arrives. Useful for the `workflow_dispatch` re-run case
(developer iterating).

## 5. Failure signalling

- Workflow status reflects the harness exit code: `0` → ✅; `1`,
  `2` → ❌.
- The artifact upload preserves the JSON report regardless of
  status, so a failed run can be diagnosed without re-running.
- The job summary (auto-generated) includes the workflow's stdout
  tail — sufficient to identify which fixture+metric failed.

## 6. Cost / budget

- Free GitHub-hosted minutes for public repos. Private repo cost
  estimate (ubuntu-latest = 1× multiplier): ~12 min/run × 1 run per
  release tag = ~12 min/month at current release cadence (~2/mo).
  Well under any plan's budget.
- `workflow_dispatch` runs are uncapped in budget impact; assume
  ~4 manual runs/month worst case.

## 7. Future-proofing

Reserved for v2 — DO NOT add in v1:

- Matrix over `[ubuntu-latest, macos-latest]` (after macOS runtime
  budget is reviewed).
- Nightly cron schedule (after the 6-fixture v2 set lands).
- PR comment with diff (after a stable diff format is shipped).
- Path-filtered PR trigger (clarify Q4 mentions this as a possible
  upgrade if late-warning bites).
