# Feature Specification: E2E Quality + Test Harness

**Feature Branch**: `022-e2e-quality-harness`
**Created**: 2026-05-21
**Status**: **SHIPPED 0.3.0** (coordinated 022+024 release, 2026-05-21). All 5 user stories merged via parallel-agent execution per `~/.cursor/plans/three-spec_parallel_strategy_a19098b4.plan.md` (architect's phased-serial plan). Sub-D conductor pass landed integration fixes (worktree-portable shim, dict-form source-key normalization, disk-aware coverage metric, fake_agent round-robin + scout-canned-payload honoring, conftest gates dict-iter fix, scout-derived SG-002 fallback) and committed v1 baselines under `tests/fixtures/quality/baselines/`. `/speckit.clarify` interactive session 2026-05-21 locked 5 decisions (architect v1 cut, vault-shaped fake-agent responses, < 10 min harness budget, tag-trigger CI only, ship-PR-blessed baselines); `/speckit.plan` produced contract files + research.md + data-model.md + quickstart.md; `/speckit.tasks` produced 88 tasks across 9 phases; `/speckit.analyze` surfaced 5 MEDIUM + 3 LOW findings, all resolved in commit `ce5fb80`. See Clarifications block below for the locked decisions.
**Follow-up patches — 0.3.1 + 0.3.2 (2026-05-22)**: 0.3.1 retargeted the harness's metric calculators from the pre-B3 monolithic `cycle_runner.py` seams to the post-B3 `pipeline/steps/<step>.py` typed step results (`./build.sh --quality` remained green across all three fixtures with **baselines unchanged**, confirming behaviour preservation). 0.3.2 closed a latent Principle-IV violation in `tests/quality/conftest.run_fixture_cycles` + the in-process bootstrap path used by the harness — `fake_agent.install_shim` is now installed into `<fixture.vault_dir>/scripts/` at test setup so the shim intercepts in-process `agent_call.dispatch()` (`plan_narrator` + probe-retrieval). Tier-6 e2e went 22/23 → **23/23**; suite wall-clock dropped 644s → 114s.
**Fidelity correction — `[Unreleased]` (2026-09-06, epic #216)**: the shipped
harness did not run the gate this spec describes. `runner._invoke_cycles` drove
**one** cycle per fixture against plan.md § Performance Goals' `max_cycles: 3`,
data-model.md's `Fixture (1) ──< CycleOutput (N, one per cycle in the harness
run)`, US3 acceptance scenario 2's "the 3-cycle harness run", and
`tests/quality/conftest.run_fixture_cycles`, which always drove three — so the
release gate was a third of the specified one and US3's `source-poor` scenario
could not be reached. Fixed in the code, not the spec;
`quality.runner.HARNESS_MAX_CYCLES` is now the single source of the number.
Alongside it: `cost_per_substantive_note` divided by `2 × notes` (#294); the
scout's SG-001..003 verdicts were never persisted, so the quality report
recorded `NA`/"not recorded" for every step gate on every cycle — including the
one that had just aborted the cycle (#269, `pipeline/step_gate_log.py`); and a
gated metric with an empty denominator reported `0.0` rather than
`unmeasured` (#268, contract § 3). All three baselines were re-blessed from a
3-cycle run; the ones committed in 0.3.0 encoded the one-cycle shape and a
`cost_per_substantive_note` of `0.40` that no run has ever produced. **The
locked clarify Q2 ("vault-shaped … correct section structure") is still
unmet**: the fake agent's note bodies carry none of their template's sections,
so `template_compliance_pct` measures a real but structurally-pinned `0.0`.
That, and #267's zero-baseline escape hatch, remain open under epic #216.

**Gate-hardening — `[Unreleased]` (2026-05-22)**: the canonical interception test (`tests/quality/test_fake_agent_interception.py::test_no_live_claude_or_codex_during_fixture_run`) was promoted to a ship gate — now in `build.sh::SMOKE_TESTS` (locked by the meta-test) and `release.yml` runs `bash build.sh --quality` before publishing. A Principle-IV regression of the kind 0.3.2 fixed can no longer land on `main` undetected. **Open v3 follow-up** (deferred, not in this spec): source-quality metric family, embedded-firmware/childcare/gaming fixtures, with-vault-vs-without-vault `/ask` comparison.
**Input**: ROADMAP queue #1 — locked design 2026-05-20. Promoted from
`docs/ROADMAP.md` § "Spec 022 — Quality + E2E test harness (expanded
design notes)" (lines 373–456). Architect's recommended scope cut
(2026-05-21 sprint plan): **v1 = 3 fixtures + 3 metric families +
fake-agent only**; full 6-fixture / 4-family / with-vault-vs-without
gate is v2.

## Clarifications

### Session 2026-05-21 (interactive clarify with user)

- Q: v1 scope — accept the architect's cut (3 fixtures + 3 metric
  families + fake-agent only) or expand to the full design? →
  **A: Option A — architect cut accepted.** Ship the v1 gate by
  2026-06-01 with 3 fixtures (`tech-lite`, `source-poor`,
  `source-rich`), 3 metric families (coverage, cycle health,
  note-quality template-compliance), fake-agent only. Queue v2
  immediately after with the missing 3 fixtures (`embedded-firmware`,
  `childcare`, `gaming`), the 4th metric family (source quality —
  unblocks when spec 020 ships), and the with-vault-vs-without
  `/ask` comparison (the most important signal per ROADMAP line
  299, but needs live LLM). Foundation-first ≠ maximum-scope-first
  for v1.
- Q: How realistic should canned fake-agent responses be per
  fixture? → **A: Option B — vault-shaped.** Each fixture ships
  with ~15–20 notes that follow the templates faithfully (correct
  frontmatter, correct section structure, correct wikilink
  shape), but the *content* of each note can be obviously
  synthetic (lorem-ipsum-style topic names, placeholder citation
  URLs). Sufficient to catch structural, counting, and
  template-compliance regressions. Hand-authoring effort estimate:
  ~2–3 days for all 3 fixtures combined. Realistic content
  (Option C) is deferred to v2 if and when source-quality metrics
  demand it.
- Q: Performance ceiling for the harness portion of
  `./build.sh --quality`? → **A: Option B — harness-only budget
  < 10 min on a recent Mac.** Total `./build.sh --quality` runtime
  therefore targets ~12 min (~2 min smoke gate + ~10 min harness).
  Industry norm: any single CI check under 15 min is comfortable;
  under 10 is unnoticeable.
- Q: Where and when does the harness run in CI? → **A: Option B —
  GitHub Actions on `v*` tag push only.** No per-PR trigger. Two
  cheap mitigations to offset the late-warning risk: (1) a
  `workflow_dispatch` (manual-fire) trigger on the same workflow,
  so a dev can run the harness against any branch on demand from
  the GitHub UI; (2) a spec recommendation that devs run
  `./build.sh --quality` locally before merging anything that
  touches `src/`, `scripts/`, or `tests/_helpers/fake_agent.py`.
  Rationale: per-PR CI (Option A in the clarify question) would
  add ~10 min to every doc-only PR — unacceptable friction given
  the current cadence of doc updates. If the late-warning risk
  bites in practice, the workflow can be upgraded to
  path-filtered per-PR triggers without a spec change.
- Q: Where do the initial baseline JSON files come from? →
  **A: Option A — ship-PR-blessed.** The dev shipping 022 v1
  runs `./build.sh --quality` locally on the ship branch,
  generates baseline JSON for all 3 fixtures, commits them in the
  same PR as the harness code. Reviewer eyeballs the JSON.
  Rationale: v1 is fake-agent only and SC-001 mandates byte-
  identical determinism, so the dev's local run produces identical
  JSON to what CI would produce. No bootstrap-mode complexity; no
  follow-up PR; standard golden-file testing pattern. If CI later
  detects drift from local baselines, that itself is a regression
  caught by the harness (the determinism contract was broken).

### Session 2026-05-21 (asynchronous draft — agent's best-effort starting positions)

The pre-clarify draft session below captured the agent's starting
positions. Entries flagged `[LOCKED 2026-05-21]` were resolved by
the interactive clarify session above; remaining `[PROPOSED]` items
are still open and will be resolved in subsequent clarify rounds or
at `/speckit.plan` time.

- **[LOCKED 2026-05-21] Q: v1 scope?** → 3 fixture vaults + 3 metric
  families + fake-agent only, per architect 2026-05-20. With-vault-
  vs-without-vault `/ask` comparison deferred to **v2** (requires
  live LLM). v1 must be cheap enough to run on every release.
- **[LOCKED 2026-05-21] Q: Which 3 fixtures in v1?** → `tech-lite`
  (small Java service domain), `source-poor` (deliberately
  under-resourced spec to test how the cycle handles gaps),
  `source-rich` (curated source list that should hit coverage
  easily). `embedded-firmware`, `childcare`, `gaming` queued for v2.
- **[LOCKED 2026-05-21] Q: Which 3 metric families in v1?** →
  **Coverage** (% coverage_targets met, notes per category,
  spec-vs-vault drift), **Cycle health** (cycle pass/fail count,
  SG-NNN gate trip counts, retry-once rate), and **Note quality
  (template-compliance subset)** (per 2026-05-20 triage item #26 —
  see `docs/TODO.md#restoration-notes` — "template available" is
  not enough; we measure section
  completion). **Source quality** queued for v2 — depends on
  spec-020 (code-bridge) source consensus output that isn't
  shipped yet.
- **[PROPOSED] Q: Regression gate threshold?** → **Moderate** per
  ROADMAP: any metric drops >15% fails the build; 5–15% drop emits
  a warning. Identical metrics or improvement = pass. This is a
  **MODERATE** gate — a strict gate would fail any drop and a lax
  gate would only fail on catastrophic drift. Moderate matches the
  project's iteration speed.
- **[PROPOSED] Q: Where does the baseline JSON live?** →
  `tests/fixtures/quality/baselines/<fixture-name>.baseline.json`
  committed to the repo. A regression run produces a corresponding
  `<fixture-name>.current.json` (gitignored) and the harness diffs
  the two. Baselines are updated by an explicit human action
  (`./vault quality-baseline-update <fixture>`), never by the
  harness itself.
- **[LOCKED 2026-05-21]** Q: Fake-agent only — but how realistic?
  → Each fixture vault ships with a **canned fake-agent script**
  that produces deterministic, **vault-shaped** outputs (template-
  faithful structure with synthetic content; ~15–20 notes per
  cycle) covering the fixture's coverage targets — see the
  interactive clarify Q2 answer for the full vault-shaped
  definition. Per-fixture
  `tests/fixtures/quality/<name>/fake_agent_responses/` directory.
- **[LOCKED 2026-05-21]** Q: Where does the harness run? → As a
  new `tier-6` multi-cycle e2e test (per ADR-0008's numbering) in
  `tests/quality/test_quality_harness_<fixture>.py`. Gated by
  `@pytest.mark.e2e + @pytest.mark.slow` — runs in CI / release
  gate but not the fast local loop. CI trigger: `v*` tag push or
  `workflow_dispatch` only (no per-PR trigger) — see the
  interactive clarify Q4 answer.
- **[LOCKED 2026-05-21]** Q: Hook into `build.sh` smoke gate? →
  **No.** The smoke gate (`SMOKE_TESTS` per ADR-0007) is for "did
  the build break?" — fast, deterministic correctness checks.
  Quality regression is a **separate** gate. Conflating them would
  slow `build.sh` from 2 min to 10+ min. A new `./build.sh
  --quality` flag (additive, not default) invokes the harness for
  release prep and on-demand local runs. CI invokes the same
  `./build.sh --quality` from the tag-push workflow.
- **[PROPOSED] Q: Spec acceptance coverage hookup (ADR-0008)?** →
  Yes. This spec self-references the new `## Acceptance coverage`
  convention. Each user story below ships with the test reference
  that proves it, demonstrating the convention from day one.

### Background — why this spec gates everything else

`docs/ROADMAP.md` line 247 — the strategic-sequencing decision:

> 1. **Quality** — ship the E2E quality harness (spec 022) FIRST so we
>    can baseline 0.2.31 and prove every subsequent feature improves
>    the metrics rather than regressing them.

This spec is the gate. Until it ships, the project cannot:

- Implement spec 020 (code-bridge) and prove it doesn't degrade vault
  quality. (Currently PAUSED per `docs/ROADMAP.md` line 62.)
- Implement spec 021 (gap-pursuit) for the same reason.
- Ship Tier 1 source modules (`youtube`, `reddit`, `oreilly`, `arxiv`)
  — each must be gated by 022's regression check.
- Publish to PyPI — "no PyPI push until the quality baseline says
  we're ready" (ROADMAP line 92).

The three back-to-back seam-bug releases (0.2.20 → 0.2.22 — see Feature
018 + ADR-0007) proved that "1000+ unit tests pass" does not mean "the
bundle works." Feature 018 added the smoke gate to catch *correctness*
drift. Spec 022 adds the quality harness to catch *output-quality*
drift — a class the smoke gate can't measure because the smoke gate's
fake agent produces minimal deterministic outputs, not realistic
cycle output.

### Relationship to ADR-0008

ADR-0008 (2026-05-21) restructured the testing pyramid 6→7 tiers and
added two cross-cutting test-purpose conventions: **regression
discipline** (every `CHANGELOG.md` `### Fixed` entry must link a
preventing test) and **spec acceptance coverage** (every spec.md with
Given/When/Then scenarios must ship an `## Acceptance coverage` table).

Spec 022 **inherits** ADR-0008's vocabulary and **adds**:

- A new **quality-regression layer** — orthogonal to the existing
  correctness-regression layer (ADR-0008 § Regression discipline).
  Correctness regression: "did a previously-fixed bug return?"
  Quality regression: "did vault output get worse?"
- A new fixture-vault namespace: `tests/fixtures/quality/` (owned by
  this spec, per ADR-0008 § Boundary with spec 022).
- A new build-gate composition: `./build.sh` runs the smoke gate;
  `./build.sh --quality` additively runs the quality harness.

### What this spec is NOT

- It is **NOT** a replacement for the smoke gate (ADR-0007). The smoke
  gate stays mandatory for every wheel build. Spec 022's quality gate
  runs on release-candidate branches only.
- It is **NOT** a cost-tracking gate. Per-call `cost_usd` is captured
  today via `agent_call.py`; cost-as-quality-metric (the deferred
  "Cost-per-substantive-note" — ROADMAP line 912) is v3 work.
- It is **NOT** the `topic-propose` skill or the gap-pursuit logic
  (spec 021). 022 *measures* gap-pursuit's effect; it doesn't
  implement it.
- It is **NOT** a real-LLM gate. v1 uses fake-agent outputs. The
  "with-vault vs without-vault" comparison (most important per
  ROADMAP) requires real LLM access and is **v2**.
- It is **NOT** a vault-correctness validator. `scripts/validate_cycle.py`
  and the spec-018 smoke gate already do that.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Baseline-driven regression gate on three fixtures (Priority: P1)

A release author runs `./build.sh --quality` on a release-candidate
branch. The harness exercises the three fixture vaults (`tech-lite`,
`source-poor`, `source-rich`) end-to-end via the fake agent, computes
the three v1 metric families, and writes
`tests/fixtures/quality/<fixture>.current.json` for each. The harness
then diffs `current.json` against the committed `<fixture>.baseline.json`
and either passes (no metric dropped >15%), warns (any metric dropped
5–15%), or fails (any metric dropped >15%).

**Why this priority**: This is the entire MVP. Without it, no
subsequent feature spec can ship safely; with it, every feature spec
gets an objective drift gauge.

**Independent Test**: Run `./build.sh --quality` twice in a row on the
same commit and assert (a) both runs produce identical `current.json`,
(b) the diff against `baseline.json` is empty, (c) exit code 0.
Deliberately regress one metric (e.g. lower a fixture's coverage
target so its `% met` drops) and assert exit code 1 with a clear
report identifying the regressed metric.

**Acceptance Scenarios**:

1. **Given** a release-candidate branch with no behaviour changes vs
   the baseline commit, **When** `./build.sh --quality` runs, **Then**
   exit code 0 and the report says "0 regressions, 0 warnings".
2. **Given** a change that drops the `tech-lite` fixture's coverage
   metric by 20%, **When** the harness runs, **Then** exit code 1 and
   the report names the regressed metric, the magnitude, and the
   fixture.
3. **Given** a change that drops a metric by 10% (within the warn
   band), **When** the harness runs, **Then** exit code 0 with a
   warning printed to stdout and the per-metric `verdict` field in
   `_pipeline/quality/regression-report.json` set to `"warn"` for
   the affected metric. (No separate `quality-warnings.json` file
   is written — warns surface via the regression report's per-metric
   verdict, per `contracts/regression-report.contract.md` § 4.)
4. **Given** an explicit baseline update (`./vault quality-baseline-update
   tech-lite`), **When** the human confirms, **Then** the
   `tech-lite.baseline.json` is overwritten and the next run uses
   the new baseline.

---

### User Story 2 — Three v1 metric families produce stable, comparable scores (Priority: P1)

A contributor adds an instrumentation hook to the cycle runner. They
run the harness twice on the same commit and want the three v1 metric
families (**coverage**, **cycle health**, **note quality / template
compliance**) to produce **byte-identical** JSON output across runs —
no `datetime.now()`, no random ordering, no platform-dependent floats.

**Why this priority**: Determinism is the foundation. If two runs of
the same commit differ, the harness is noise and the gate is useless.

**Independent Test**: For each fixture, run the harness twice and
assert `current_run_1.json == current_run_2.json` byte-for-byte
(except for an explicit `run_timestamp` field that's excluded from
the diff).

**Acceptance Scenarios**:

1. **Given** a fixture vault, **When** the harness runs twice
   back-to-back, **Then** the two `current.json` files are
   byte-identical modulo the excluded `run_timestamp`.
2. **Given** the harness on `tech-lite`, **When** coverage is
   computed, **Then** the metric is `{coverage_pct: 0.83, notes_per_category:
   {...}, spec_drift: 0.12}` and all three numbers are reproducible.
3. **Given** the harness on `source-poor` (deliberately under-resourced),
   **When** cycle health is computed, **Then** the metric records the
   expected SG-NNN gate trips and the retry-once rate accurately.
4. **Given** the harness on any fixture, **When** note-quality
   template-compliance is computed, **Then** the metric reports per-
   template-section fill rates (each section either filled or
   `MISSING`, no fuzzy partial-fill states).

---

### User Story 3 — Three fixture vaults exercise distinct failure modes (Priority: P1)

A future contributor adds spec 020 (code-bridge) and runs the harness
against the three fixtures. They expect each fixture to surface
*different* failure modes — `tech-lite` should detect any regression
in code-derived topic discovery, `source-poor` should detect any
regression in gap-pursuit / source-substitution, and `source-rich`
should detect any over-eager pruning of high-quality sources.

**Why this priority**: One fixture is a smoke test; three fixtures
that *exercise different code paths* are a quality gate. If all three
look identical, we'd just have one fixture.

**Independent Test**: For each fixture, snapshot the cycle's
`_pipeline/cycle-NNN-research.json` and confirm:
- `tech-lite` has at least 5 code-derived topics
- `source-poor` triggers SG-002 (diversity gate warning) at least once
- `source-rich` produces ≥3 notes per category for at least 80% of
  categories

**Acceptance Scenarios**:

1. **Given** the `tech-lite` fixture, **When** a cycle runs, **Then**
   the scout report has `≥5` topics tagged `code-derived` and the
   metric `notes_per_category[services] ≥ 3`.
2. **Given** the `source-poor` fixture, **When** a cycle runs,
   **Then** at least one cycle in the 3-cycle harness run triggers
   the SG-002 diversity-gate warning and the metric reflects it.
3. **Given** the `source-rich` fixture, **When** a cycle runs,
   **Then** the metric `coverage_pct ≥ 0.80` and the cycle does not
   over-prune (verifier reject rate < 20%).
4. **Given** any fixture, **When** the cycle would normally call a
   real LLM, **Then** the fake agent intercepts and produces the
   canned response from `tests/fixtures/quality/<fixture>/fake_agent_responses/`.

---

### User Story 4 — Baseline is human-updated, never harness-auto-updated (Priority: P2)

A developer fixes a bug that genuinely improves cycle output. They
run the harness, see that `note_quality.template_compliance` is now
0.92 (was 0.84 baseline), and want to bless the new baseline. They
run `./vault quality-baseline-update tech-lite` and the harness
overwrites `tech-lite.baseline.json` with the current run's values
plus a `last_updated`, `last_updated_by`, and `last_updated_reason`
field.

**Why this priority**: Auto-updating baselines silently is how
quality gates die. Every baseline update should be an explicit human
choice with a written rationale, captured in git history.

**Independent Test**: Confirm that no codepath under `tests/quality/`
or `scripts/` writes to `tests/fixtures/quality/*.baseline.json`
*except* via the `vault quality-baseline-update` CLI subcommand. A
guard test (`tests/quality/test_baseline_update_isolation.py`) scans
the codebase for unsafe writes.

**Acceptance Scenarios**:

1. **Given** the harness in regression-check mode, **When** it
   detects a metric improvement (i.e. the `current` value is better
   than the `baseline` value per the metric's `direction` field —
   `higher_is_better` metric whose `current > baseline`, or
   `lower_is_better` metric whose `current < baseline`),
   **Then** it **does NOT** overwrite the baseline — it just
   reports the improvement and exits 0.
2. **Given** `./vault quality-baseline-update tech-lite`, **When**
   the developer confirms via stdin prompt (`Y/n`), **Then** the
   baseline file is overwritten and includes the rationale.
3. **Given** the developer answers `n` to the prompt, **When** the
   command exits, **Then** the baseline is unchanged and stderr says
   "baseline not updated".
4. **Given** the guard test runs, **When** any non-CLI write to a
   baseline JSON is detected, **Then** the test fails with the file
   and line that would write.

---

### User Story 5 — Harness runs in CI, not in `pytest -m "not e2e"` (Priority: P2)

A daily contributor running the fast local loop (`pytest -m "not e2e"`)
expects the harness NOT to run — it's expensive and CI-only. The
harness lives in `tests/quality/` with `@pytest.mark.e2e` and
`@pytest.mark.slow` decorators per ADR-0008.

**Why this priority**: Quality regression detection needs realistic
inputs which means slow runtime. Forcing it on every developer push
would slow iteration; running it only on release-candidate branches
gets the gate where it matters.

**Independent Test**: Run `pytest -m "not e2e"` and confirm 0 tests
under `tests/quality/` are collected. Run `pytest -m e2e
tests/quality/` and confirm the harness runs.

**Acceptance Scenarios**:

1. **Given** the fast local loop (`pytest -m "not e2e"`), **When** it
   runs, **Then** 0 tests from `tests/quality/` are collected.
2. **Given** `pytest -m e2e tests/quality/`, **When** it runs against
   a clean checkout, **Then** all three fixtures' harnesses run and
   each produces a `current.json`.
3. **Given** `./build.sh` (no `--quality` flag), **When** it runs,
   **Then** the harness does NOT run; smoke gate runs as today.
4. **Given** `./build.sh --quality`, **When** it runs, **Then** smoke
   gate runs first, harness runs second, and the wheel is built only
   if both pass.

---

### User Story 6 — Spec acceptance coverage proves the harness exists (Priority: P3)

This very spec's `## Acceptance coverage` section (ADR-0008 convention)
maps each User Story above to a concrete test in `tests/quality/`.
Demonstrates the convention day-1 instead of waiting for the lint guard.

**Why this priority**: P3 because it's documentation discipline; the
harness still works without it. But it's a forcing function — if the
spec ships without the section filled, the Phase 2 acceptance-coverage
lint guard (spec 024) will catch it.

**Independent Test**: Read the `## Acceptance coverage` section below
and confirm every User Story has a non-`(deferred)` evidence entry by
the time `/speckit.tasks` completes.

**Acceptance Scenarios**:

1. **Given** this spec at `/speckit.specify` time, **When** the
   `## Acceptance coverage` section is rendered, **Then** every User
   Story 1–5 has a test reference (initially `(deferred to
   tasks.md)`, replaced with concrete test paths at
   `/speckit.tasks` time).
2. **Given** the Phase 2 acceptance-coverage lint guard (delivered
   by spec 024), **When** it scans this spec.md, **Then** it passes
   without an allowlist entry.

### Edge Cases

- What happens when a fixture vault's `coverage-targets.json` itself
  changes between baseline and current? → The baseline schema
  includes a `coverage_targets_hash`; mismatch fails the run with
  "baseline stale for fixture `<name>`; re-baseline required".
- How does the harness handle a fake-agent canned response file that
  doesn't match the cycle's prompt? → Fail loudly with the prompt's
  expected key vs the canned response's key. No fallback to live LLM.
- What if a metric family is removed in v2+? → The harness reads only
  the metric families listed in
  `tests/fixtures/quality/<fixture>.baseline.json`; removed families
  become dead keys to ignore. Adding new families requires a baseline
  refresh.
- What if a fixture's fake-agent response file is missing entirely?
  → Fail with "fixture `<name>` not initialised — run
  `./vault quality-fixture-init <name>` first."
- What if a fixture's **baseline** JSON file is missing entirely?
  → Fail with "baseline missing for fixture `<name>`; run
  `./build.sh --quality` locally on the ship branch and commit
  the generated baseline" (FR-017). Never auto-create.
- What if a CI run produces a `current.json` that's malformed? →
  Treat as catastrophic failure (exit non-zero, attach the
  malformed file to the failure log).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Harness MUST exercise three fixture vaults
  (`tech-lite`, `source-poor`, `source-rich`) end-to-end via the
  fake-agent infrastructure (no live LLM in v1).
- **FR-002**: Harness MUST compute the three v1 metric families:
  coverage, cycle health, note-quality template compliance.
- **FR-003**: Harness MUST produce **byte-deterministic** JSON output
  for the same commit/fixture pair (modulo an excluded
  `run_timestamp` field).
- **FR-004**: Harness MUST diff `current.json` against
  `<fixture>.baseline.json` and exit non-zero on any metric drop
  >15%, warn on 5–15% drops, pass on smaller drops or improvements.
- **FR-005**: Harness MUST be invoked via `./build.sh --quality` (a
  new flag, additive, NOT default) and via direct `pytest -m e2e
  tests/quality/`.
- **FR-006**: Harness MUST NOT run during the fast local loop
  (`pytest -m "not e2e"`).
- **FR-007**: Harness MUST NOT auto-update baseline files. Baseline
  updates require explicit `./vault quality-baseline-update <fixture>`
  CLI invocation with stdin confirmation.
- **FR-008**: Baseline JSON files MUST be committed under
  `tests/fixtures/quality/baselines/`. `current.json` files MUST be
  `.gitignore`d.
- **FR-009**: Each fixture vault MUST ship with a canned fake-agent
  response directory at
  `tests/fixtures/quality/<fixture>/fake_agent_responses/`. Responses
  MUST produce **vault-shaped** outputs (Option B in the interactive
  clarify session): template-faithful structure (correct frontmatter,
  correct section headings, correct wikilink shape), with content
  that can be obviously synthetic (e.g. lorem-ipsum-style topic
  names, placeholder citation URLs). Each fixture's canned responses
  MUST produce ~15–20 notes per cycle when consumed end-to-end.
  Realistic-content fixtures are explicitly out of scope for v1.
- **FR-010**: Harness failure reports MUST identify the regressed
  metric, the magnitude (% drop), the fixture, and a deterministic
  reproduction recipe.
- **FR-011**: Each fixture MUST exercise a distinct failure mode
  (code-derived topic discovery for `tech-lite`, gap-pursuit for
  `source-poor`, source-quality for `source-rich`).
- **FR-012**: A guard test under `tests/quality/test_baseline_update_isolation.py`
  MUST verify no non-CLI codepath writes to baseline files.
- **FR-013**: The spec's own `## Acceptance coverage` section MUST
  pass the Phase 2 acceptance-coverage lint guard (per ADR-0008),
  with no allowlist entry required.
- **FR-014**: A GitHub Actions workflow at
  `.github/workflows/quality.yml` MUST invoke `./build.sh --quality`
  on **`v*` tag push only** (i.e. release-tag moment) and on
  **`workflow_dispatch`** (manual-fire) events. The workflow MUST
  NOT trigger on `push` or `pull_request` events for any branch.
- **FR-015**: The spec MUST document a soft recommendation that
  contributors run `./build.sh --quality` locally before merging
  PRs that touch `src/`, `scripts/`, or
  `tests/_helpers/fake_agent.py`. This is a documentation
  obligation in `CONTRIBUTING.md` / `docs/testing-strategy.md`,
  not a tooling enforcement.
- **FR-016**: The ship PR for spec 022 v1 MUST include
  freshly-generated baseline JSON files for all 3 fixtures
  (`tech-lite.baseline.json`, `source-poor.baseline.json`,
  `source-rich.baseline.json`) under
  `tests/fixtures/quality/baselines/`. Files MUST be generated by
  running `./build.sh --quality` on the ship branch immediately
  before commit. Reviewer MUST eyeball the JSON files before
  approving the PR.
- **FR-017**: When the harness runs and a baseline JSON file does
  not exist for a fixture, the harness MUST fail with a clear
  "baseline missing for fixture `<name>`; run `./build.sh
  --quality` locally on the ship branch and commit the generated
  baseline" message. The harness MUST NOT auto-create baselines
  in this case (preserves FR-007's "no auto-update" rule).

### Key Entities

- **Fixture vault** — a deterministic, minimal vault under
  `tests/fixtures/quality/<name>/` with its own
  `research.spec.md`, seed data, and `fake_agent_responses/`. Three
  in v1, six in v2.
- **Metric family** — a named group of related quality metrics
  (coverage, cycle health, note quality, source quality). v1 ships
  three; source quality is v2.
- **Baseline JSON** — a committed snapshot of all metric values for
  a fixture at a known-good commit. Format:
  `{schema_version, fixture, baseline_commit, last_updated,
  last_updated_by, last_updated_reason, coverage_targets_hash,
  metrics: { coverage: {...}, cycle_health: {...}, note_quality: {...} }}`.
- **Current JSON** — the runtime output of one harness invocation
  for one fixture. Same schema as baseline minus the
  `last_updated*` and `baseline_commit` fields.
- **Regression report** — the harness's stdout/stderr output on a
  failed run; structured enough to feed a CI status badge or a
  follow-up `gh` comment.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Two back-to-back harness runs on the same commit
  produce byte-identical `current.json` files (modulo
  `run_timestamp`) — for ALL three fixtures.
- **SC-002**: Spec 020 (code-bridge) Phase 1–2 ships through the
  022 gate without requiring a baseline refresh (i.e. 020 demonstrably
  does not regress quality).
- **SC-003**: A deliberate quality regression introduced for testing
  (e.g. lowering a fixture's coverage target by 20%) is detected by
  the harness with the correct fixture+metric+magnitude reported
  100% of the time across 10 trial runs.
- **SC-004**: Fast local loop (`pytest -m "not e2e"`) runtime is
  unchanged after 022 ships (the harness must not leak into the
  default sweep).
- **SC-005**: `./build.sh` (no `--quality`) runtime is unchanged
  (the smoke gate is still ~2 min).
- **SC-006**: `./build.sh --quality` runtime is **< 12 min** on a
  recent Mac (reference hardware: Apple M1 Pro, 16 GB RAM —
  matching `contracts/regression-report.contract.md` § 6),
  decomposed as **~2 min smoke gate + < 10 min harness**.
  The harness-only budget of 10 min is the gating number — exceeding
  it implies fixture or instrumentation cost overrun and should
  trigger optimisation before fixture growth.
- **SC-007**: At least one downstream spec (020 or 021) explicitly
  cites a 022 baseline as its acceptance criterion within 30 days
  of 022 shipping, proving the harness is being used.

## Assumptions

- The fake-agent infrastructure (`tests/_helpers/fake_agent.py` per
  the v2 contract) is sufficient to produce vault-shaped outputs.
  v2 expansion will need real-LLM access patterns.
- Spec 024's Phase 2 lint guards (acceptance-coverage,
  CHANGELOG regression-link) ship before or alongside 022.
- ADR-0008's tier numbering is final; the harness sits at tier 6
  (multi-cycle e2e per ADR-0008).
- `./vault quality-baseline-update` is a new top-level subcommand;
  adding it touches `src/research_framework/cli.py` and the
  `dist-templates/install.sh` flow but doesn't break existing
  surfaces.
- `tests/fixtures/quality/` is a new directory namespace; will not
  collide with `tests/fixtures/vault/` (the shared minimal vaults
  for ADR-0008 tier-3 / tier-4 tests).
- Cost-per-substantive-note metric is **deferred to v3** despite
  appearing in early design notes (ROADMAP line 912).

## Acceptance coverage

Demonstrates the ADR-0008 spec acceptance coverage convention. Filled
out at `/speckit.tasks` time; initial state is `(deferred to tasks.md)`
for every user story.

| User Story | Evidence |
|------------|----------|
| US1 — Baseline regression gate on three fixtures | `tests/quality/test_quality_harness_regression_gate.py` |
| US2 — Three v1 metric families produce stable scores | `tests/quality/unit/test_coverage_metric.py`, `tests/quality/unit/test_cycle_health_metric.py`, `tests/quality/unit/test_note_quality_metric.py`, `tests/quality/test_metric_determinism.py` |
| US3 — Three fixtures exercise distinct failure modes | `tests/quality/test_quality_harness_tech_lite.py`, `tests/quality/test_quality_harness_source_poor.py`, `tests/quality/test_quality_harness_source_rich.py`, `tests/quality/test_fake_agent_interception.py` |
| US4 — Baseline is human-updated, never auto-updated | `tests/quality/unit/test_baseline_update_cli.py`, `tests/quality/test_baseline_update_isolation.py` |
| US5 — Harness runs in CI, not in `pytest -m "not e2e"` | `tests/quality/unit/test_marker_isolation.py`, `tests/quality/test_build_script_quality_flag.py` |
| US6 — Spec acceptance coverage proves the harness exists | This section itself, plus the spec-024 lint guard once it ships |

## Out of scope (deferred to v2 / v3)

- 4th metric family: **source quality** (depends on spec-020 source
  consensus output; ships when 020 lands).
- 4th–6th fixtures: `embedded-firmware`, `childcare`, `gaming`.
- **With-vault vs without-vault `/ask` comparison** — the highest-
  signal metric per ROADMAP line 299, but requires live LLM and a
  baseline-LLM strategy. v2 will design this carefully.
- **Cost-per-substantive-note** as a metric family (v3 — depends on
  the cost-efficiency phase).
- **Post-release hotfix tracking** as a baseline metric (2026-05-20
  triage item #33, `docs/TODO.md#restoration-notes`) — v3 (needs
  release-history corpus).
- **PyPI publication gate** wiring — covered by ROADMAP queue #8;
  this spec produces the metric, queue #8 wires the gate.
- **Real-vault validation pass** (post-022 decision on spec 016 —
  ROADMAP lines 442–455) — decision deferred to after 022 v1 ships.
