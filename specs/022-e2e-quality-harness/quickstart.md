# Quickstart: E2E Quality + Test Harness

**For**: contributors who want to run, interpret, or update the
quality harness.
**Prereqs**: working `research-framework` checkout (`pip install -e .[dev]`).
**Time**: 15 min start to finish on a recent Mac.

---

## 1. Run the harness locally (most common task)

```bash
./build.sh --quality
```

What happens (per [`contracts/regression-report.contract.md`](./contracts/regression-report.contract.md)):

1. Smoke gate runs first (~2 min); fails fast if broken.
2. Harness exercises all 3 fixture vaults (`tech-lite`,
   `source-poor`, `source-rich`) via the fake-agent
   infrastructure. Each fixture's cycle runs end-to-end with
   canned LLM responses.
3. Harness writes
   `_pipeline/quality/<fixture>.current.json` per fixture and
   `_pipeline/quality/regression-report.json` overall.
4. Harness diffs each `current.json` against the committed
   `tests/fixtures/quality/baselines/<fixture>.baseline.json`.
5. Stdout shows pass / warn / fail per metric per fixture.
6. Exit code `0` if all pass or warn; `1` if any metric regressed
   ≥ 15%; `2` if the harness itself crashed.

### Common variations

```bash
# One fixture only — fastest iteration loop
./build.sh --quality --fixture tech-lite

# Direct pytest invocation — useful when debugging a single test
pytest -m e2e tests/quality/test_quality_harness_tech_lite.py -v

# No ANSI colours (e.g. piping to a file)
./build.sh --quality --no-color > harness.log
```

### Expected runtime

| Scope | Wall-clock (recent Mac) |
|---|---|
| Smoke gate alone | ~2 min |
| Harness alone (3 fixtures) | < 10 min |
| Total `./build.sh --quality` | < 12 min |

If your run substantially exceeds these, see § 5 Troubleshooting.

---

## 2. Interpret a regression report

If the harness exits non-zero, look at:

### Stdout (immediate signal)

```text
--- tech-lite ---
  Status: FAIL
  coverage.coverage_pct           = 0.6800  (baseline 0.8300, Δ -18.1%)  ✗  FAIL
  …
```

### `_pipeline/quality/regression-report.json` (structured)

Parse for downstream tooling or to diff manually. Schema: see
[`contracts/baseline-schema.contract.md`](./contracts/baseline-schema.contract.md) § 3.

### Failure categories (final stderr line)

The harness always prints a reproduction recipe. Categories:

| Category | What it means |
|---|---|
| `regression` | A real quality drop. Investigate the metric. |
| `baseline-missing` | First-time scenario — see § 4. |
| `baseline-stale` | Fixture's `coverage-targets.json` changed; baseline needs refresh. See § 3. |
| `fixture-not-initialised` | Fixture vault is missing files; this is a v2 path. |
| `cycle-runner-crash` | Cycle runner crashed mid-fixture; see logs under `_pipeline/quality/<fixture>/logs/`. |
| `determinism-violation` | Two back-to-back runs produced different JSON. The harness or fake_agent introduced nondeterminism. |

---

## 3. Update a baseline (rare, deliberate)

When you've genuinely improved the system and want to bless a new
expected output:

```bash
./vault quality-baseline-update tech-lite \
  --reason "Spec 025 A1 routed plan_narrator through agent_call.py; cost capture improved cycle_health.retry_once_rate from 0.05 to 0.02"
```

What happens (per [`contracts/quality-cli.contract.md`](./contracts/quality-cli.contract.md) § 2):

1. Harness runs for the one named fixture.
2. Diff between `current.json` and existing `baseline.json` is
   printed.
3. Interactive prompt: "Apply baseline update for tech-lite? [y/N]"
4. On `y`, baseline is overwritten atomically with the new values
   plus the `--reason` text and your name as `last_updated_by`.
5. Commit the modified baseline file in a focused PR.

### Always test the update first with `--dry-run`

```bash
./vault quality-baseline-update tech-lite --dry-run
```

Shows the diff without writing. Use it before every real update.

### Never auto-update baselines

The harness explicitly does NOT auto-write baselines (FR-007).
There's no `--auto-baseline` flag and we won't add one. Baselines
are the contract; updating them silently destroys the gate.

---

## 4. First-time baseline blessing (ship-PR-blessed flow)

This applies only to:
- The ship PR for spec 022 v1 itself.
- Future PRs that add new fixtures (v2 work).

Procedure per FR-016 + clarify Q5 Option A:

```bash
# On the spec-022 ship branch:
./build.sh --quality                   # first run — emits "baseline missing" for each fixture
# Generate baselines from this run:
./vault quality-baseline-update tech-lite --reason "Initial baseline at spec 022 v1 ship" --actor "$(git config user.name)"
./vault quality-baseline-update source-poor --reason "Initial baseline at spec 022 v1 ship"
./vault quality-baseline-update source-rich --reason "Initial baseline at spec 022 v1 ship"

# Confirm green:
./build.sh --quality                   # all 3 fixtures should now pass

# Commit:
git add tests/fixtures/quality/baselines/
git commit -m "fixtures(022): initial baseline JSONs for tech-lite, source-poor, source-rich"
```

The reviewer eyeballs the three baseline JSON files (they're small
~5–15 KB each and structured JSON is human-readable). They should:
- Confirm `coverage_targets_hash` matches the fixture's coverage
  targets.
- Confirm `metrics` values look sane for the fixture's stated
  failure mode.
- Confirm `last_updated_reason` is meaningful.

---

## 5. Troubleshooting

### "Harness took 25 minutes; budget is 10 min"

Likely causes:
- Fake-agent fell through to a real LLM call. Check
  `_pipeline/quality/<fixture>/logs/` for "claude" or "codex"
  process invocations. The fake-agent contract (spec 024 US2) is
  supposed to prevent this — file a bug against the fake_agent.
- A fixture's cycle is doing real work (real source fetching, real
  cycle iteration counts). Check the fixture's `settings.yaml` —
  `max_cycles` should be ≤ 6 per fixture.
- Disk I/O. Try `iostat -x 1` during a run; if disk is the
  bottleneck, the harness's `_pipeline/` writes are too chatty.

### "Determinism violation across two runs of the same commit"

The harness has an internal deterministic-guard that catches this.
If it fires, the typical culprits are:
- Python `dict` ordering (less likely in 3.7+, but watch nested
  `Counter` results).
- `datetime.now()` leaked into a metric.
- Random topic-list ordering in fake_agent (should be sorted; if
  not, file a bug).
- Float precision (the harness truncates to 4 decimals — see
  [`contracts/baseline-schema.contract.md`](./contracts/baseline-schema.contract.md) § 1 determinism rules).

Reproduce locally: `./build.sh --quality --fixture <name>` twice
and diff `_pipeline/quality/<fixture>.current.json` between runs.
The harness saves a diff at `_pipeline/quality/<fixture>.current-diff.txt`
when the guard fires.

### "Baseline stale" after editing a fixture

Expected. You've changed the fixture's `coverage-targets.json`
contract. Re-bless:

```bash
./vault quality-baseline-update <fixture> --reason "Changed coverage targets to add <new-category>"
```

### CI: workflow didn't fire on my PR

Expected per spec.md clarify Q4 + FR-014. The workflow triggers
ONLY on `v*` tag push and `workflow_dispatch`. To get a CI run on
your PR without merging:

1. Go to Actions tab → "Quality" workflow → "Run workflow".
2. Pick your branch + (optionally) one fixture.
3. Click "Run workflow". Result appears as a separate workflow run.

### Local-run recommendation (FR-015)

The spec soft-recommends running `./build.sh --quality` locally
before merging PRs that touch:
- `src/research_framework/` (especially `cycle_runner.py`,
  `agent_call.py`, `plan_narrator.py`, `verifier.py`)
- `scripts/`
- `tests/_helpers/fake_agent.py`

It's a recommendation, not enforcement. Use judgement.

---

## 6. Add a new fixture (v2 work — placeholder)

v1 ships with 3 fixed fixtures (`tech-lite`, `source-poor`,
`source-rich`). Adding the v2 set (`embedded-firmware`, `childcare`,
`gaming`) involves:

1. Author the fixture vault under `tests/fixtures/quality/<name>/`.
2. Generate the fake_agent_responses tree.
3. Run `./build.sh --quality --fixture <name>` to confirm.
4. `./vault quality-baseline-update <name> --reason "v2 fixture
   `<name>` initial baseline"`
5. Update `REGISTERED_FIXTURES` constant in
   `src/research_framework/quality/runner.py`.
6. Add a `test_quality_harness_<name>.py` file.

Full v2 quickstart will ship with spec 022 v2.

---

## 7. Where to read the design

- High-level spec — [`spec.md`](./spec.md) (6 user stories,
  17 FRs, 7 SCs, 5 locked clarifications)
- Plan — [`plan.md`](./plan.md) (technical context, structure,
  constitution check)
- Research — [`research.md`](./research.md) (9 design decisions
  with rationale + rejected alternatives)
- Data model — [`data-model.md`](./data-model.md) (6 entities,
  relationships, state transitions)
- Contracts:
  - [`contracts/baseline-schema.contract.md`](./contracts/baseline-schema.contract.md)
  - [`contracts/regression-report.contract.md`](./contracts/regression-report.contract.md)
  - [`contracts/quality-cli.contract.md`](./contracts/quality-cli.contract.md)
  - [`contracts/quality-workflow.contract.md`](./contracts/quality-workflow.contract.md)
