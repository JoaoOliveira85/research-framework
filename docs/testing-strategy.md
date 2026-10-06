# Testing Strategy — Layered Pyramid

**Status**: active (last test-count refresh 2026-09-08, mechanically
verified — see § TL;DR; strategy itself unchanged since the 2026-05-22
Foundation refresh)  
**Supersedes**: the 0.2.23 edition of this document in spirit; the
2026-05-21 pre-Phase-2 edition that anticipated the changes below. The
smoke gate is unchanged (ADR-0007). The pyramid is **seven tiers** per
ADR-0008 — Tier 3 was renamed "Seam" → "Integration" and old Tier 4
was split into "Component integration" + "Cycle e2e".  
**Background**: Three seam-bug releases (0.2.20 → 0.2.22) showed that
"unit tests pass" does not mean "a research cycle runs." Feature 018
added tier-4/5 e2e + the mandatory smoke gate. The 2026-05-21 refresh
added **agent contracts** and a **fake-agent stage matrix**; ADR-0008
closed the "agents can't find 'integration' in the docs" gap and added
a regression-discipline convention so every shipped bug-fix links a
test that prevents recurrence. **Specs 022/024/025 (Foundation arc,
SHIPPED 0.3.0 → 0.3.2)** then *implemented* the guards, fake-agent
extensions, smoke meta-tests, and quality harness this document had
proposed — see "How to run each tier" and "Quality harness" below for
the as-shipped surface.  
**History**: `specs/018-testing-strategy/spec.md` (original six-tier
design; superseded in part by ADR-0008). `specs/022-e2e-quality-harness/`
(quality harness, SHIPPED 0.3.0). `specs/024-testing-infrastructure-v2/`
(LLM dispatch guard + fake-agent extensions + lint guards, SHIPPED 0.3.0).  
**Decision record**: `docs/adr/0008-testing-pyramid-restructure.md`.

---

## Where this fits in the roadmap

The four-phase plan that motivated this document **has shipped end-to-end**:

| Phase | What | Status |
|-------|------|--------|
| **1** | Revise testing strategy doc | **Complete** — 2026-05-21 refresh, restructured under ADR-0008 |
| **2** | Implement guards, fake-agent extensions, smoke meta-tests | **SHIPPED 0.3.0** as spec 024 |
| **3** | Simplify refactor (Tier A → B) | **SHIPPED 0.3.0** (Tier A) + **0.3.1** (Tier B) as spec 025 |
| **4** | Spec 022 — E2E quality harness | **SHIPPED 0.3.0** (+ 0.3.1 v2 + 0.3.2 fixture intercept fix) |

There is **no remaining Phase work** from this document. New testing
work should land via a normal spec-kit cycle. The historical phase
checklists are preserved further below for traceability.

You do **not** need deep testing experience to use this doc. Follow the
decision tree when adding tests; the rest is reference material.

---

## TL;DR

```bash
pytest -m "not e2e"        # fast local loop, ~6-7 min
pytest                     # full sweep including tier-5/6 e2e, ~12 min
pytest -m e2e              # tier-5/6 e2e only
./build.sh                 # production gate: refuses to build if smoke tier is red
./build.sh --quality       # production gate + spec-022 quality harness (3 fixtures, regression diff vs baselines)
ruff check .               # lint baseline (must be zero)
```

<!-- test-count: not_e2e=4299 total=4329 e2e_only=30 refreshed=2026-10-04 -->
**This is the one place in the repo a test count is committed** — every
other doc that mentions a count (README, CLAUDE.md, CONTRIBUTING.md,
ARCHITECTURE.md, `docs/RELEASE.md`) points here instead of quoting its
own copy. Today that's **4299** fast-loop tests (`pytest -m "not e2e"`),
**4329** total (`pytest --collect-only -q`), **30** deselected as `e2e`.
`tests/docs/test_one_source_per_fact.py` re-collects the suite and
fails if the comment above no longer matches — when it fails, update
the comment **and** the three bolded numbers in this paragraph
together, then re-run the test.

The build gate is **hard** — no `--skip-smoke` flag (ADR-0007). Bypassing
it requires editing `build.sh`, which is an intentional code change.

**Golden rule**: production cycle code runs unmodified in e2e tests. The
**only** substitution is `tests/_helpers/fake_agent.py` in place of
`scripts/agent_call.py` at the subprocess boundary. The LLM dispatch
guard (`tests/_helpers/test_llm_dispatch_guard.py`, allowlist EMPTY at
0.3.2) statically enforces this for all of `src/research_framework/`.

---

## The seven-tier pyramid

Updated under ADR-0008 (2026-05-21). The mandatory smoke gate (ADR-0007)
is unchanged in substance — only the tier numbers it references shifted
because old Tier 4 was split. Do not weaken or opt out.

| Tier | Name | Scope | Canonical example | Approx cost |
|------|------|-------|-------------------|-------------|
| 1 | Unit | One pure function, no I/O | `tests/pipeline/test_batch.py` | < 1 ms / test |
| 2 | Schema / contract | One JSON shape, CLI contract, or guard | `tests/_helpers/test_fake_agent_contract.py` | < 50 ms / test |
| 3 | **Integration** | Module A output → module B input (data-flow seam) | `tests/pipeline/test_merge_scout_topics.py` | < 100 ms / test |
| 4 | **Component integration** | One pipeline component (`cycle_runner`, `orchestrator`, `plan_narrator`) + its real dependencies, sub-cycle | `tests/pipeline/test_cycle_runner.py`, `test_orchestrator.py` | < 2 s / test |
| 5 | Cycle e2e | Full `run_cycle_steps` via fake agent | `tests/pipeline/test_full_cycle_e2e.py` | < 10 s / scenario |
| 6 | Multi-cycle e2e | Real `run_cycles` × N + fake agent | `tests/pipeline/test_multi_cycle_e2e.py` | < 30 s / scenario |
| 7 | Smoke gate | Tier 2 + 5 + 6 as `build.sh` precondition | `tests/build/test_smoke_gate_enforced.py` | ~2 min |

> **Vocabulary note**: in conventional Python-testing parlance, **Tiers
> 3 and 4 are both "integration tests"** — Tier 3 narrowly between two
> modules, Tier 4 between one component and its real dependencies. The
> ADR-0008 rename surfaces this for searches that grep for "integration".

**Enforced rule**: tier-5/6 scenarios in `SMOKE_TESTS` MUST be green
before any wheel is built (`build.sh` § 0). ADR-0007's "tier 4+5" wording
refers to what ADR-0008 re-numbers as tier 5+6; the gate's actual
contents are unchanged (it selects by file path, not tier number).

### Pytest markers

Two axes: **tier-scope markers** (where the test sits in the pyramid)
and **purpose markers** (why the test exists). They compose freely.

| Marker | Axis | Meaning |
|--------|------|---------|
| `e2e` | scope | Tier 5 (single-cycle) or tier 6 (multi-cycle) — drives real `cycle_runner` with fake agent |
| `slow` | scope | Subprocesses into `build.sh` or other heavy harness |
| `live_llm` | scope | Real `claude` / `codex` CLI invocation — **costs money**, opt-in only. Renamed from `integration` in ADR-0008 to free that namespace for Tier 3. |
| `regression` *(voluntary)* | purpose | Test exists to prevent a specific shipped `CHANGELOG.md` bug from recurring. Add when fixing a bug in any release (see § Regression discipline below). |
| `acceptance` *(voluntary)* | purpose | Test proves a specific `specs/NNN-*/spec.md` acceptance scenario. Complements the per-spec `## Acceptance coverage` table (see § Spec acceptance coverage). |

Default local loop: `pytest -m "not e2e"`. Useful slices:

```bash
pytest -m regression           # run only regression tests across all tiers
pytest -m "acceptance and not e2e"   # spec acceptance proofs, fast tier only
pytest -m "not e2e and not live_llm" # cheap CI gate
pytest -m live_llm             # the money tests (CI only, behind an env gate)
```

> **The smoke gate does NOT use marker filters.** `build.sh` § 0 invokes
> `pytest "${SMOKE_TESTS[@]}"` with no `-m` flag — every test in the
> selected files runs regardless of `e2e` / `slow` markers. The gate
> selects by **file path**. Don't try to speed up the gate by adding
> marker filters — fix the tests instead.
>
> Markers do NOT govern the local developer loop only — CI selects by
> marker too, in two jobs with two different expressions. This paragraph
> claimed otherwise until issue #266, and while it did, 17 of the 27
> `e2e`-marked tests ran in no automation at all. See **§ Which
> automation runs what** below; `tests/README.md` carries the same matrix
> next to the marker table, and
> `tests/build/test_e2e_tier_runs_in_automation.py` enforces it.

### Which automation runs what

| Automation | Trigger | Selection |
|------------|---------|-----------|
| Local pre-commit hook (`.git-hooks/pre-commit`, wired by `scripts/install-git-hooks.sh`) and every PR's own reported run | Every commit / every PR — **this is the merge gate** since #323 | `scripts/guards/run_all.py`, `pytest -m "not e2e"`, `pytest -m e2e`, `ruff check`, `ruff format --check` |
| `ci.yml` job `ci` (Linux; macOS only with the `macos: true` dispatch input) | `v*` tag push, manual dispatch — **never** PR or push to `main` (CLAUDE.md § CI budget) | `pytest -m "not e2e"` — plus `scripts/guards/run_all.py` (portability + the guard test battery, § Guard battery aggregator), ruff, shellcheck, installer dry-run |
| `ci.yml` job `e2e` (Linux) | same | `pytest -m "e2e and not live_llm"` (~6.5 min) |
| `build.sh` § 0 smoke gate | Local; `build.sh` and `build.sh --quality` | `pytest "${SMOKE_TESTS[@]}"` — **file paths, no `-m`** |
| `quality.yml` | `v*` tag, manual dispatch | `build.sh --quality` — the smoke gate, then `research_framework.quality.runner`. **Not pytest** for the harness part |
| `release.yml` | `v*` tag, manual dispatch | `build.sh --quality` again, before publishing the Release |
| nothing | — | `live_llm` — opt in with `--live-llm` / `LIVE_LLM=1`, real money |

The workflows also have to be *enabled* on GitHub for a tag to run them —
see `docs/RELEASE.md` § The regime: tags and by hand only.

Two consequences worth internalising:

- An `e2e` marker no longer means "runs only locally". It means "runs in
  the `e2e` job on every version tag, in every PR's local gate, and in the
  smoke gate if the file is in `SMOKE_TESTS`".
- The reverse convention is load-bearing too:
  `tests/pipeline/test_runner_agent_dispatch.py` is deliberately
  **unmarked** because `-m "not e2e"` is what reaches it. Marking it
  `e2e` would move the spec-209 regression gate off the fast loop; the
  tier-7 test above fails if anyone does.

---

## Agent contract tier (tier 2) — read before touching tests or LLM stages

These contracts are enforced by tier-2 guard tests (existing + Phase 2
additions); they are the **testable surface** of the project's AI seams.
The contract file is the **source of truth** for both human and AI
contributors. Change the contract in the **same PR** as code or tests.

| Contract | Path | Governs |
|----------|------|---------|
| Fake agent CLI | `specs/018-testing-strategy/contracts/fake-agent.contract.md` | All e2e LLM stubbing |
| Fake CLI binary | `tests/_helpers/fake_cli_binary.py` module docstring | The tier-5 binary seam (#270) |
| LLM dispatch guard | `specs/018-testing-strategy/contracts/llm-dispatch-guard.contract.md` | No `claude`/`codex` outside `agent_call.py` |
| Vault factory | `tests/_helpers/vault_factory.py` module docstring | Minimal vault fixtures |
| Smoke gate manifest | `build.sh` `SMOKE_TESTS` + `tests/build/test_smoke_gate_enforces_contract_tier.py` | What blocks releases |
| Real LLM dispatch | `scripts/agent_call.py` module docstring | Production agent calls |

**Dual codebase warning**: runtime logic lives in **`src/research_framework/`**
(package) and **`scripts/`** (copied into every vault). Tests for validators
and `agent_call.py` live under `tests/scripts/`. When grepping for LLM
calls or cycle behaviour, search **both** trees.

---

## Two fake seams, and which tier owns which (issue #270)

There are two places a test can cut the LLM out, and they buy different
things. Pick deliberately.

| Seam | Helper | Replaces | Dispatcher coverage | Cost |
|------|--------|----------|--------------------|------|
| **Module** (default) | `tests/_helpers/fake_agent.py::install_shim` | the vault's whole `scripts/agent_call.py` | none — the dispatcher IS the fake | one process |
| **CLI binary** | `tests/_helpers/fake_cli_binary.py::activate` | only the leaf `claude` / `codex` executable | full — real argv, stdin, stream-json, cost parser, sidecar v1.2 | one subprocess per stage |

The module seam is the default and stays that way: it owns the fast loop
and the quality fixtures (`tests/quality/conftest.py::run_fixture_cycles`),
where thousands of runs make the per-stage subprocess real money in wall
clock. Its cost is a blind spot — under it *nothing* in `agent_call.py`
executes, so every sidecar any test reads is one the fake wrote, and both
#259 (a `NameError` in the shim's `dispatch`) and #262 (a missing `model`
kwarg) shipped through it.

The binary seam is for **tier 5** (`tests/e2e/`), where a handful of runs
buy the dispatcher its own coverage. Three properties make it a seam and
not a hole:

- **it checks the argv it is handed** against what each real CLI requires
  (`--model` + `--print`, `exec` for codex) and exits 2 otherwise, so an
  adapter regression is a red test rather than a stub that shrugs;
- **it writes no telemetry** — no cost sidecar, no cost line on stdout — so
  every sidecar a binary-seam test asserts on came from production code;
- **it fails closed** when `agent_call.py` has not published the call
  context, instead of exiting 0 having written nothing.

The context is that last piece: the CLI runtimes receive the prompt and
nothing else, so `agent_call.py` publishes `RESEARCH_FRAMEWORK_VAULT` and
`RESEARCH_FRAMEWORK_STAGE` into the runtime child's environment
(`_set_call_context`). Without it a leaf-binary fake would have to guess
both out of prompt prose.

Stage behaviour is *not* duplicated: the binary stub delegates to
`fake_agent`'s scenario handlers. The stage matrix below governs both seams.

---

## fake-agent stage matrix

The fake agent replaces `scripts/agent_call.py` in tests. Each **stage**
(`--stage`) must either be fully stubbed or explicitly documented as
passthrough. **As of v0.3.2:**

| Stage | Status | Used by |
|-------|--------|---------|
| `scout` | ✅ 5 scenarios | Step 1 — BFS topic discovery |
| `note_writer` | ✅ batch + legacy | Step 3 — note drafting |
| `verifier` | ✅ accept / reject / malformed | Step 3b — per-note QC |
| `research_plan_narrator` | ✅ stub narrative (also exposed via in-process `dispatch()` for the bootstrap path; see 0.3.2 fix) | Plan header (orchestrator) |
| `probe_retrieval` | ✅ stub Q&A cache fill (in-process `dispatch()` path) | Step 0 probes (optional) |
| *(other)* | no-op exit 0 | Auxiliary stages |

**Scenario env vars** (all live as of 0.3.0):

| Variable | Overrides |
|----------|-----------|
| `FAKE_AGENT_SCENARIO` | Global default (`happy`) |
| `FAKE_AGENT_SCOUT_SCENARIO` | `--stage scout` |
| `FAKE_AGENT_NOTE_WRITER_SCENARIO` | `--stage note_writer` |
| `FAKE_AGENT_VERIFIER_SCENARIO` | `--stage verifier` |
| `FAKE_AGENT_RESEARCH_PLAN_NARRATOR_SCENARIO` | `--stage research_plan_narrator` |
| `FAKE_AGENT_PROBE_RETRIEVAL_SCENARIO` | `--stage probe_retrieval` |

Per-stage overrides beat the global var. Valid scenario names are listed
in `fake-agent.contract.md` § Scenarios.

---

## Quality harness — `./build.sh --quality` (spec 022)

**Status**: SHIPPED 0.3.0 (+ 0.3.1 v2 retarget for the post-B3
`pipeline/steps/` boundaries + 0.3.2 fixture-shim intercept fix).

The harness is the project's regression gate for **output quality**
(distinct from the smoke gate, which guards **correctness**). It runs
**3 fixture vaults × 3 cycles × 3 metric families** and diffs the
results against committed baselines, failing the release if any
fixture regresses by >15% on any metric (warning at >5%).

| Component | Where |
|-----------|-------|
| Fixtures (committed) | `tests/fixtures/quality/{tech-lite,source-poor,source-rich}/` |
| Baselines (committed) | `tests/fixtures/quality/baselines/<fixture>.baseline.json` |
| Metric calculators | `src/research_framework/quality/metrics/{coverage,note_quality,cycle_health}.py` |
| Baseline I/O | `src/research_framework/quality/baseline.py`, `baseline_update.py` |
| Regression diff | `src/research_framework/quality/regression.py` |
| Cycles per fixture | `quality.runner.HARNESS_MAX_CYCLES` — the single source; `tests/quality/conftest.py` imports it |
| Gate entrypoint | `./build.sh --quality` (calls into `research-framework quality run`) |
| Tier-5/6 fixture-cycle runner | `tests/quality/conftest.py::run_fixture_cycles` (installs fake-agent shim at fixture vault setup) |

**How honest is this gate?** (issues #267–#269, #294; epic #216 tracks
the rest.) Until 2026-09-06 the runner drove ONE cycle per fixture while
this section claimed three, and the baselines were blessed from those
one-cycle runs. Read the current numbers before trusting a PASS:

- A metric with an **empty denominator now reports `unmeasured`**, not
  `0.0` — no acronym ever occurred, no citation's credibility resolved,
  no note was written, the verifier never ran. Those metrics are named
  in the `Summary:` line and in `regression-report.json`. They carry no
  verdict, so a PASS beside them means "not measured", not "fine".
  Today that is `acronym_link_pct` and `tier2_source_ratio` on every
  fixture, plus `template_compliance_pct` and `verifier_reject_rate` on
  `source-poor`.
- A metric whose **baseline is `0`** and stays `0` reads `_delta_pct`'s
  `n/a` as an honest "no change" (fixed in #267 — `_metric_verdict` now
  checks the raw values, not just the percentage: a `lower_is_better`
  metric baselined at `0` FAILs outright the moment `current > 0`, since
  there is no prior magnitude to bound the increase in a 5%/15% band).
  `higher_is_better` metrics baselined at `0` are unaffected — they are
  non-negative, so `0` is already the worst possible reading and nothing
  can regress below it.
- `template_compliance_pct` reads a real `0.0` on the fixtures that
  write notes: the fake agent's note bodies carry none of their
  template's sections, which contradicts spec 022's locked clarify Q2
  ("vault-shaped … correct section structure"). The metric works; the
  fixture content does not exercise it.
- `cost_per_substantive_note` reads a real `0.0` because fake-agent cost
  sidecars record `cost_usd: 0.0`. It is live on a real vault only.

**What is NOT in v1 (deferred to v3 / future spec)**:
- Source-quality metrics (Shannon entropy, broken-source rate, etc.).
- With-vault-vs-without-vault `/ask` comparison (the most important
  signal, but needs a live-LLM gate — a separate cost discussion).
- Cost-per-substantive-note gating (cost tracking exists; gating
  belongs in the post-features efficiency phase).

**Closed gap (post-Foundation gate hardening, `[Unreleased]`)**: the
canonical "no live LLM during fixture cycles" assertion
(`tests/quality/test_fake_agent_interception.py::test_no_live_claude_or_codex_during_fixture_run`)
**IS now in the smoke gate** (`build.sh::SMOKE_TESTS`) and the release
pipeline runs `bash build.sh --quality` before publishing. A
Principle-IV regression of the type 0.3.2 fixed will now hard-fail
both `./build.sh` (locally) and `release.yml` (in CI) before any tag
or GitHub Release is created. The test still carries
`@pytest.mark.e2e` + `@pytest.mark.slow` so it remains opt-in for the
fast local loop; the smoke gate selects by file path, not marker, so
the markers do not affect ship-gate enforcement.

---

## Spec acceptance coverage

The seven-tier pyramid tests **the system**; this section closes a separate
gap — **the spec → test traceability layer**. Spec-kit specs in
`specs/NNN-*/` routinely contain acceptance scenarios (Given / When /
Then) that today have no mechanical link to any passing test. If a spec
ships with 5 scenarios and only 3 are e2e-covered, nothing flags the
other 2.

### Convention

Every `specs/NNN-*/spec.md` that contains an **"Acceptance Scenarios"**
section (or equivalent Given/When/Then prose) **MUST** ship a sibling
section titled `## Acceptance coverage` that maps each scenario to its
evidence:

```markdown
## Acceptance coverage

| Scenario | Evidence |
|----------|----------|
| 1. User runs `./vault research` on a fresh vault, expects cycle-1 to abort with SG-001 if scout is empty | `tests/pipeline/test_full_cycle_e2e.py::test_empty_scout_queue_aborts_via_sg001` |
| 2. Note batch with asymmetric tail is serialised without loss | `tests/pipeline/test_full_cycle_e2e.py::test_asymmetric_tail_batch_serializes` |
| 3. Quality-report sidecar is written even on cycle failure | _(deferred to Tier A6)_ |
| 4. User can resume a failed cycle by rerunning `./vault research` | _(manual: `specs/NNN-*/quickstart.md` step 3)_ |
```

Permitted evidence values:

- A test reference `<file>::<test_function>` (tier-1/2/3/4/5).
- `(deferred to <spec or Tier ID>)` — points to where the work will land.
- `(manual: <step in quickstart.md or test plan>)` — for UX flows not
  yet automatable.

**Source of truth**: the spec.md acceptance scenarios are the contract;
the `Acceptance coverage` table is the evidence the contract was met.

### Composition with the seven-tier pyramid

This is a **traceability layer, not a new tier**. The tests it cites
already live somewhere in tiers 1–5; the section just makes the spec →
test mapping discoverable instead of implicit. No new test runtime cost.

### Composition with spec 022

Spec 022 measures **output quality** ("did the cycle produce a good
vault?"). Spec acceptance coverage measures **requirement satisfaction**
("did we ship what we promised in this spec?"). Different questions,
different gates — both required for 022 implementation work to start
from a known-good baseline.

### Rollout

- **Non-retroactive.** Existing specs (`001`–`019`, `021`) are annotated
  only when the spec is **next touched** for substantive work.
- New specs (starting with `020-code-bridge` and `022-*`) MUST include
  the section before `/speckit.plan` exits.
- The Phase 2 lint guard (below) starts with an empty allowlist and
  fails closed for any spec.md that has acceptance scenarios but no
  matching coverage table.

### Phase 2 guard

A tier-2 lint test at `tests/spec/test_acceptance_coverage_guard.py`
will scan `specs/*/spec.md` for acceptance-scenario blocks (Given/When/
Then patterns or an `## Acceptance Scenarios` heading) and assert a
matching `## Acceptance coverage` section exists. Failures opt new specs
into the convention; specs predating the convention can be added to an
explicit allowlist (which must shrink over time, same discipline as the
LLM dispatch guard).

---

## Regression discipline

Twin to spec acceptance coverage. Spec acceptance maps **what we
promised** to a test; regression discipline maps **what broke and got
fixed** to a test that prevents recurrence. Both are *cross-cutting*
conventions — they sit ALONGSIDE the seven-tier pyramid, not inside it.

The motivating failure mode is documented in ADR-0001 (Adopt ADRs):
between 0.2.20 and 0.2.31 the project repeatedly re-fixed the same
classes of bug because the WHY of the original fix lived only in commit
messages nobody re-read. Regression tests are the same kind of long-term
memory ADRs are — for runtime behaviour.

### Convention

Every entry under a released-version `### Fixed` block (or equivalent
bug-class block) in `CHANGELOG.md` MUST link evidence of a test that
prevents recurrence. Acceptable forms:

```markdown
### Fixed

- 0.2.21 — `BatchResult` serialisation drift between batch.py and the
  report writer; both files passed unit tests but the seam was wrong.
  (test: `tests/pipeline/test_full_cycle_e2e.py::test_asymmetric_tail_batch_serializes`)
- 0.2.27 — Five validator scripts crashed on cycle-source files with
  the new `local_path` shape.
  (regression test: `tests/scripts/test_validate_cycle_source_file_shapes.py`)
- 0.2.33 — Typo in onboard help text said "assess" after the migrator was retired.
  (no test: documentation-only correction; help-text drift is human-review territory.)
```

The Phase 2 lint guard (below) accepts three forms:

- `(test: <file>::<test_function>)`
- `(regression test: <file>::<test_function>)` — synonym
- `(no test: <one-sentence rationale>)` — escape hatch reviewed in PR

### Marker

Where a test is added specifically to prevent recurrence of a shipped
bug, tag it `@pytest.mark.regression` so contributors can run
`pytest -m regression` to verify the historical bug catalogue.

```python
import pytest

pytestmark = pytest.mark.regression

def test_asymmetric_tail_batch_serializes(...):
    """Regression test for 0.2.22 — BatchResult enforced wrong invariant."""
    ...
```

The marker is voluntary today and **becomes mandatory for new
`CHANGELOG.md` Fixed entries** once the Phase 2 lint guard ships. Apply
it to existing regression tests opportunistically when those tests are
next touched.

### Phase 2 guard

A tier-2 lint test at `tests/spec/test_changelog_regression_links.py`
will parse `CHANGELOG.md` released-version blocks, locate every entry
under a `### Fixed` heading, and assert each contains one of the three
forms above. Pre-ADR-0008 entries are grandfathered via an explicit
allowlist (same discipline as the LLM dispatch guard); the allowlist
must shrink over time.

### Composition with spec 022

Spec-022 measures **quality drift** (does the cycle produce a good
vault?). Regression discipline catches **correctness drift** (did a
previously-fixed bug return?). Different gates; both required for a
trustworthy release line.

---

## Decision tree — which tier?

Apply the **first** matching rule:

1. **New pure function, no I/O** → tier 1.  
   `tests/<module>/test_<feature>.py`

2. **New/changed JSON, Markdown artefact, or CLI contract** → tier 2.  
   `tests/_helpers/` or `tests/scripts/`

3. **Data flow between two modules** (scout JSON → merge, batch → serialiser) → tier 3 (Integration).  
   Wire both modules with minimal fixtures.

4. **Test one named component with its real dependencies** (e.g. `cycle_runner` end-to-end **but only up to a specific step**, `orchestrator` with retry logic, `plan_narrator` rendering) → tier 4 (Component integration).  
   Sub-cycle scope; real settings + fixture vault; fake agent if any LLM seam is involved.

5. **Change to `run_cycle_steps` end-to-end** (new step, abort gate, ordering across the full cycle) → tier 5 (Cycle e2e).  
   `tests/pipeline/test_full_cycle_e2e.py` or sibling with `pytestmark = pytest.mark.e2e`

6. **Change to `run_cycles` or cross-cycle state** → tier 6 (Multi-cycle e2e).  
   `tests/pipeline/test_multi_cycle_e2e.py`

7. **Change to `build.sh` SMOKE_TESTS manifest** → tier 7 meta-test must pass.  
   `tests/build/test_smoke_gate_enforces_contract_tier.py`

**If multiple rules match**: add the **cheapest** tier that pinpoints the
bug **plus** one tier-5 scenario for realistic end-to-end proof.

### Special cases

| Change type | Tier | Notes |
|-------------|------|-------|
| New LLM stage in production | 2 guard + 2 fake_agent contract + 5 if in cycle | Route through `agent_call.py` first |
| New validator in `scripts/` | 2 | Prompt↔validator contract pattern |
| Bug-fix shipping in `CHANGELOG.md` | whichever tier reproduces it + `@pytest.mark.regression` | See § Regression discipline |
| Spec acceptance scenario | whichever tier proves it + `@pytest.mark.acceptance` | See § Spec acceptance coverage |
| Refactor only (no behaviour change) | existing tiers must stay green | No new tier unless coverage gap found |

---

## How to run each tier

```bash
# Tier 1 — unit (fastest loop while coding)
pytest -m "not e2e and not slow" tests/pipeline/test_batch.py

# Tier 2 — contracts + guards
pytest tests/_helpers/ tests/build/ tests/scripts/test_prompt_validator_contract.py

# Tier 3 — integration (cross-module data flow)
pytest tests/pipeline/test_merge_scout_topics.py

# Tier 4 — component integration (one component + its deps, sub-cycle)
pytest tests/pipeline/test_cycle_runner.py tests/pipeline/test_orchestrator.py

# Tier 5 — cycle e2e (full run_cycle_steps via fake agent)
pytest tests/pipeline/test_full_cycle_e2e.py -v

# Tier 6 — multi-cycle e2e
pytest tests/pipeline/test_multi_cycle_e2e.py -v

# Tier 7 — smoke gate (what build.sh runs)
./build.sh
# or, without building the bundle:
pytest $(python3 -c "
import re
from pathlib import Path
text = Path('build.sh').read_text()
block = re.search(r'SMOKE_TESTS=\(\n(.*?)\n\)', text, re.DOTALL).group(1)
for line in block.splitlines():
    line = line.strip()
    if line.startswith('\"'):
        print(line.strip('\",'))
")

# Full sweep (CI / pre-release)
pytest
```

---

## How to add a fake_agent scenario

1. **Extend the contract** — `fake-agent.contract.md` § Scenarios (stage + name + behaviour).
2. **Implement** in `tests/_helpers/fake_agent.py` — deterministic only: no
   `datetime.now`, no `random`, sorted iteration.
3. **Contract test** — `tests/_helpers/test_fake_agent_contract.py`.
4. **E2e consumer** — set env var in tier-5/6 test via `monkeypatch.setenv`.

For **verifier** scenarios (phase 2), read prompt text for the note path,
write verdict JSON to `--output-file` or stdout per real `agent_call.py`
shape — mirror `tests/fixtures/verifier/{accept,reject}-verdict.json`.

---

## Guard tests (SHIPPED 0.3.0 as spec 024)

### LLM dispatch guard

**Contract**: `specs/018-testing-strategy/contracts/llm-dispatch-guard.contract.md`  
**Implementation**: `tests/_helpers/test_llm_dispatch_guard.py`  
**Allowlist**: `tests/_helpers/llm_dispatch_allowlist.yaml` — **EMPTY at v0.3.2**
(spec 025 SC-003).

Static test scans `src/research_framework/**/*.py` (and selected
`scripts/`) for forbidden patterns (`subprocess` + `claude`/`codex`,
bare `["claude",` invocations). At v0.3.2 the allowlist is empty;
**any new direct `claude`/`codex` subprocess in production code will
fail the guard at PR time.** Routes go through `scripts/agent_call.py`.

| Previously-allowlisted file | Cleared in |
|-----------------------------|------------|
| `pipeline/plan_narrator.py` | Spec 025 A1 (0.3.0) |
| `pipeline/cycle_runner.py` (probe cache) | Spec 025 A2 (0.3.0) |

**Formerly out of scope** (kept so the contract's history reads right):

- `processors/extract.py` used to spawn a legacy `claude -p` for the
  raw-data pipeline outside the guard's reach. It no longer does:
  `_call_claude` bootstraps `scripts/agent_call.py` and routes through
  `agent_call.dispatch()`, so it is inside the single dispatch surface
  (spec 078) and the guard's scan.

### Fake-agent completeness guard

Tier-2 test: every stage in the stage matrix above has a non–no-op
branch in `fake_agent.py` and a contract test. Prevents silent
regression to "exit 0, do nothing."

### Smoke gate manifest guard

`tests/build/test_smoke_gate_enforces_contract_tier.py` parses
`build.sh` and compares to `REQUIRED_IN_GATE`. **Both manifest entries**
(`tests/build/test_install_wizard_skip_redundant_questions.py` +
`tests/build/test_smoke_gate_enforces_contract_tier.py`) are uncommented
in `build.sh::SMOKE_TESTS` (restored in spec 024 US3, 0.3.0). Adding a
new tier-2 contract test that should be in the gate? Update both
`SMOKE_TESTS` AND `REQUIRED_IN_GATE` in the same PR or the meta-test
will fail.

### Spec acceptance-coverage guard

`tests/spec/test_acceptance_coverage_guard.py`. Tier-2 lint that scans
`specs/*/spec.md` for acceptance-scenario blocks and asserts a matching
`## Acceptance coverage` section exists. Launched **strict** in 0.3.0
with full backfill on 3 prior specs (`015a`, `017`, `018`). **v2 (issue
#283, 2026-09-07)**: the numbered-G/W/T discovery regex was single-line
and missed every scenario that wraps `**When**`/`**Then**` onto a
following line (specs 001, 002, 019, 020, 021, 024) — fixed with a
DOTALL, bounded regex; a citation naming a test that doesn't exist is
now also a failure, not just a citation shaped like one. See
`specs/024-testing-infrastructure-v2/contracts/acceptance-coverage-guard.contract.md`
(§ Changes since v1) and `docs/adr/0012-acceptance-bullet-format-not-guarded.md`
for the format gap left open.

### CHANGELOG regression-link guard

`tests/spec/test_changelog_regression_links.py`. Tier-2 lint that parses
every `### Fixed` bullet in released-version blocks of `CHANGELOG.md`
and requires one of `(test: ...)`, `(regression test: ...)`, or
`(no test: ...)`. Launched **strict** in 0.3.0 with full backfill across
all 15 released versions.

### Guard battery aggregator (issue #278)

Before 2026-09-07, "run the guards" meant a human reading a CLAUDE.md
checklist and invoking each one by hand; CI ran exactly one guard
(portability) as its own named step and left the rest inside
`pytest -m "not e2e"`'s ~3000 tests, indistinguishable from an ordinary
test failure. `python scripts/guards/run_all.py` now runs the
portability guard plus every guard test file listed in
`scripts/guards/run_all.py::GUARD_TEST_PATHS` as one battery, with a
per-guard pass/fail summary. `ci.yml`'s `Guard battery` step calls it;
`.git-hooks/pre-commit` (installed via `scripts/install-git-hooks.sh`,
since `.git/hooks/` is not tracked) calls it locally before a commit.

**Scope, deliberately narrow.** The aggregator only includes guards that
run against this repo with no external input. `check_abstraction.py`,
`check_acronym_links.py`, `check_code_source_coverage.py`,
`check_intent_drift.py`, `check_template_compliance.py`,
`check_trunk_inversion.py`, `validate_cycle.py`, `validate_spec.py`,
`validate_vault.py`, `quality_report.py`, and `vault_metrics.py` all take
a generated vault directory as a required positional argument — they
guard a *product* (a vault), not this corpus, and this repo ships no
vault fixture to point them at. The foreman Arm A verifier
(`scripts/foreman/verify_test_coverage.py`) is excluded for the same
reason: it verifies one spec's `tasks.md` against `--tasks`, and has no
corpus-sweep mode (`--all` / `--completed-only` / `--soft` — issue
#278's own suggested fix, not built by this PR). Folding any of these in
by silently skipping them would reproduce the exact "reports green
having checked nothing" failure the acceptance-coverage guard had
(issue #283); naming the gap in the aggregator's own docstring beats
hiding it.

**Parser-flag consumers (issue #271).**
`scripts/guards/parser_flag_consumers.py` is a named line of its own in the
battery. It walks every subparser of the *built* parser — argparse's own
`dest` inference, not a re-implementation of it — and requires each flag's
`dest` both to be read under `src/research_framework/cli/` and to appear as
a real Python identifier (an AST walk, so a mention in a comment, docstring
or string literal does not count) in a module outside `cli/`. Rule 2 is
waivable through the module's `ALLOWLIST`, one written reason per entry;
rule 1 is not waivable by anything. Run it alone with `--list` while wiring
a new flag. It is a floor, not a proof: a flag threaded into a non-CLI
function that then ignores it still passes, which was the shape of both
`--target-topics` and `--budget-cap` — catching *that* needs dataflow
analysis. What it does close is the flag that never leaves `cli/` at all.

**The cycle-runner seam (issue #86).**
`tests/_helpers/test_cycle_runner_seam_guard.py` rejects any `monkeypatch` or
`mock.patch` of `run_cycle_steps` under `tests/`, in either the attribute
(`setattr(mod, "run_cycle_steps", …)`) or the dotted
(`setattr("pkg.mod.run_cycle_steps", …)`) spelling — the 2026-05-30 audit
counted ten sites and the rule that was supposed to stop them lived only in
`CLAUDE.md` prose, so the count moved down by hand and back up by accident.
Replacing the module global from outside means the code under test still
*believes* it called the runner: the substitution is invisible at the call
site, leaks to every other test importing the same module in that process, and
depends on import order to bind at all. What replaces it is an **injectable
seam** — `orchestrator.run_single_cycle` and the quality harness's `run` /
`collect_fixture_current` / `_invoke_cycles` take a keyword-only
`cycle_runner`, `None` meaning "resolve the real runner at call time" — with
stubs in `tests/_helpers/cycle_runner_stub.py` that mirror
`run_cycle_steps`' real signature rather than swallowing `**kwargs`, so a
signature change fails loudly instead of being absorbed.

**Fail-closed discipline.** Several guard tests scanned a hardcoded root
with no floor on how much they found, so a moved/renamed/emptied root
made the scan (and the guard) pass vacuously — the same shape as the
LLM-dispatch guard's `SCAN_ROOT` issue #278 named directly. Each now has
a companion `test_*_is_not_vacuous` / `test_*_scan_is_not_vacuous`
assertion: `tests/_helpers/test_llm_dispatch_guard.py`,
`tests/quality/unit/test_marker_isolation.py`,
`tests/quality/test_baseline_update_isolation.py`,
`tests/benchmark/unit/test_marker_isolation.py`,
`tests/benchmark/unit/test_build_exclusion.py`, plus
`test_discovery_is_not_vacuous` in the acceptance-coverage guard itself.

---

## Anti-patterns (never)

| Anti-pattern | Why | Instead |
|--------------|-----|---------|
| Monkey-patch `run_cycle_steps` | Missed 0.2.20–0.2.22 seam bugs | Real `cycle_runner` + fake `agent_call.py` |
| Call real `claude` / `codex` in tests | Cost + non-determinism | New fake_agent scenario |
| `time.sleep` for sync | Cycle runner is synchronous | Fix the bug |
| Lower or skip e2e gate | Seam bugs ship | Fix flake or revert feature |
| `--skip-smoke` in build | ADR-0007 violation | Fix tests |
| Mutate `tests/fixtures/vault/` for 022 work | Serialization magnet | Use `tests/fixtures/quality/` (022) |
| Trim `SMOKE_TESTS` without meta-test update | Silent gate erosion | Update `REQUIRED_IN_GATE` set deliberately |

**Legacy debt status**: `tests/pipeline/test_e2e_synthetic_vault.py`
**DELETED in 0.3.0** (spec 024 US7). Replacement coverage lives in tier-5
e2e scenarios under `tests/pipeline/test_full_cycle_e2e.py` (spec 024
US6).

---

## Historical: Phase 2 & 3 (SHIPPED — for traceability only)

The Phase 2 (testing infrastructure) and Phase 3 (simplify Tier A)
checklists that this document originally proposed all shipped in 0.3.0
as specs 024 and 025. They are preserved here for traceability so a
contributor reading the 2026-05-21 design intent can map it to the
shipped surface; do **not** treat them as outstanding work.

| Phase-2 item (proposed) | Shipped as | Where |
|-------------------------|-----------|-------|
| QW-2 smoke-gate manifest entries | 024 US3 (0.3.0) | `build.sh::SMOKE_TESTS` |
| fake-agent verifier scenarios | 024 US2 (0.3.0) | `tests/_helpers/fake_agent.py` |
| fake-agent narrator + probe stubs | 024 US2 (0.3.0) | same |
| Contract tests for new stages | 024 US2 (0.3.0) | `tests/_helpers/test_fake_agent_contract.py` |
| Tier-5 cycle e2e scenarios | 024 US6 (0.3.0) | `tests/pipeline/test_full_cycle_e2e.py` |
| LLM dispatch guard + allowlist | 024 US1 (0.3.0) | `tests/_helpers/test_llm_dispatch_guard.py` |
| Retire `test_e2e_synthetic_vault.py` | 024 US7 (0.3.0) | file deleted |
| Spec acceptance-coverage guard | 024 US4 (0.3.0) | `tests/spec/test_acceptance_coverage_guard.py` |
| CHANGELOG regression-link guard | 024 US5 (0.3.0) | `tests/spec/test_changelog_regression_links.py` |
| Phase-3 A1 (plan_narrator → agent_call) | 025 A1 (0.3.0; intercept fix 0.3.2) | `pipeline/plan_narrator.py` |
| Phase-3 A2 (probe cache → agent_call) | 025 A2 (0.3.0; intercept fix 0.3.2) | `pipeline/_cycle_helpers.py` |
| Phase-3 A3 (smoke meta-tests) | 024 US3 (0.3.0) | overlap with QW-2 above |
| Phase-3 A4 (auto-detect `--resume`) | 025 A4 (0.3.0) | `cli/` subpackage |
| Phase-3 A5 (doc sync) | 025 A5 (0.3.0) | spec dirs + this doc |
| Phase-3 A6 (quality-report guard) | 025 A6 (0.3.0) | `cycle_runner._quality_report_guard` |

**As-shipped exit criteria**: full `pytest` green (1692 fast loop + 26
e2e at 0.3.2); `./build.sh` smoke green; `./build.sh --quality` green;
LLM dispatch guard allowlist **empty**; spec acceptance-coverage + 
CHANGELOG-regression-link guards green with no allowlist entries.

---

## Surfaces covered (reference map)

| Surface | Test file | Tier |
|---------|-----------|------|
| Fake-agent CLI | `tests/_helpers/test_fake_agent_contract.py` | 2 |
| Vault-factory output | `tests/_helpers/test_vault_factory_contract.py` | 2 |
| LLM dispatch guard | `tests/_helpers/test_llm_dispatch_guard.py` *(phase 2)* | 2 |
| Spec acceptance coverage guard | `tests/spec/test_acceptance_coverage_guard.py` *(phase 2)* | 2 |
| CHANGELOG regression-link guard | `tests/spec/test_changelog_regression_links.py` *(phase 2, ADR-0008)* | 2 |
| Smoke manifest | `tests/build/test_smoke_gate_enforces_contract_tier.py` | 7 |
| `build.sh` gate present | `tests/build/test_smoke_gate_enforced.py` | 2 |
| `cycle_runner` component tests | `tests/pipeline/test_cycle_runner*.py` | 4 |
| Orchestrator component tests | `tests/pipeline/test_orchestrator*.py` | 4 |
| Happy path cycle | `test_full_cycle_e2e.py::test_happy_path_single_cycle` | 5 |
| Empty scout abort | `…::test_empty_scout_queue_aborts_via_sg001` | 5 |
| SG-005 / frontmatter | `…::test_sg005_failure_triggers_correction_batch` | 5 |
| Asymmetric batch tail | `…::test_asymmetric_tail_batch_serializes` | 5 |
| SKILL preflight repair | `…::test_corrupted_skill_file_self_repairs_in_preflight` | 5 |
| Multi-cycle coverage | `test_multi_cycle_e2e.py::test_three_cycles_progress_coverage` | 6 |
| Cycle handoff | `…::test_cycle_two_picks_up_where_cycle_one_left_off` | 6 |
| Cross-cycle corrections | `…::test_correction_loop_across_cycles` | 6 |
| Verifier reject e2e | *(phase 2 — new scenario)* | 5 |

---

## Cost of the pyramid

(Wall-clock figures measured 2026-05-22 at v0.6.0 and not re-measured
since; the suite has more than doubled, so treat them as relative sizes,
not durations. The live test count is the TL;DR marker at the top of this
file — no count is quoted here.)

| Wall-clock | Coverage |
|------------|----------|
| ~2-3 min | `pytest -m "not e2e"` (tiers 1-4 + non-e2e tier-2/7 fast surface) |
| ~10 s | tier-4 component-integration scenarios (folded into the local loop above) |
| ~30 s | tier-5 cycle-e2e scenarios |
| ~90 s | tier-6 multi-cycle scenarios |
| ~2 min | tier-5/6 e2e sweep (23 scenarios; was 644s pre-0.3.2 intercept fix) |
| ~2 min | smoke gate (`build.sh` § 0; tier-7 enforcement) |
| ~4 min | full `pytest` (fast loop + e2e) |
| +~3 min | `./build.sh --quality` quality-harness add-on (3 fixtures × 3 cycles) |

Smoke gate runs once per `./build.sh` — cheaper than one real vault
cycle. The quality gate (`--quality`) is recommended before every release
that touches `pipeline/`, `quality/`, or fixture vaults.

---

## For agents (Cursor / Claude Code)

When assigned test or refactor work:

1. Read this file + the relevant contract in `specs/018-testing-strategy/contracts/`.
2. Pick tier from the decision tree — default to **lowest** applicable tier.
3. Never patch `run_cycle_steps`; install the fake agent at vault scaffold
   time (`vault_factory.build_minimal_vault` already does this).
4. Extend `fake-agent.contract.md` **before** editing `fake_agent.py`.
5. If adding an LLM call in production, route it through `agent_call.py`
   only. **The LLM dispatch guard allowlist is EMPTY at v0.3.2 — keep it
   that way.** Adding to the allowlist requires an ADR and a follow-up
   spec to clear the entry.
6. When adding a new shipped fix to `CHANGELOG.md`, include the
   `(test: <file>::<test_function>)` annotation on the leading bullet
   line (the CHANGELOG regression-link guard will reject the PR
   otherwise).
7. When drafting a new spec.md with acceptance scenarios, include the
   `## Acceptance coverage` table before `/speckit.plan` exits (the
   acceptance-coverage guard will reject the spec otherwise).

Related: `docs/ROADMAP.md` (Strategic sequencing — Foundation phase
shipped), `specs/022-e2e-quality-harness/`, `specs/024-testing-infrastructure-v2/`,
`specs/_archive/025-simplify-pass/`.
