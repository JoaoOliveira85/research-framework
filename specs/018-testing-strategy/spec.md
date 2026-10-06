# Feature Specification: Layered Testing Strategy

**Feature Branch**: `018-testing-strategy`
**Created**: 2026-05-17
**Status**: shipped(2026-05-17, version 0.2.23) — SHIPPED 0.2.23 (2026-05-17); **pyramid naming superseded in part by ADR-0008** (2026-05-21) — Tier 3 renamed "Seam" → "Integration"; old Tier 4 split into "Component integration" + "Cycle e2e"; pyramid extended to 7 tiers. Smoke gate (ADR-0007) and underlying test infrastructure unchanged. See `docs/adr/0008-testing-pyramid-restructure.md` and current `docs/testing-strategy.md` for the active design.
**Input**: Post-mortem of three consecutive seam-bug releases (0.2.20 → 0.2.21 → 0.2.22); developer fatigue and real $$$ token cost of failed end-user test runs.

## Context

Three consecutive bundle releases (0.2.20, 0.2.21, 0.2.22) each shipped with a different **seam bug** — a contract mismatch between two correct sub-components that no unit test could catch because each component tests in isolation. The user's `reference-vault-v3` and `reference-vault-v4` trial runs both aborted mid-cycle after consuming real LLM tokens, dollars, and 15+ minutes of wall-clock time per attempt.

### The three seam bugs

| Release | Seam | Failure mode | Why unit tests missed it |
|---------|------|--------------|--------------------------|
| 0.2.20 | scout output ↔ research plan | scout produced `topics_found.new` but plan generation ran **before** scout, so dispatcher saw empty queue and aborted | No test wired scout output into plan generation |
| 0.2.21 | placeholder generator ↔ slicer | research_plan filled queue with placeholder topics that the slicer then dropped, leaving empty batches | Each tested its own filtering in isolation; the seam was never exercised |
| 0.2.22 | slicer ↔ BatchResult serializer | slicer produced legitimate 2-topic tail batch (queue=8, batch_size=3 → 3+3+2); serializer enforced `3..10` invariant designed for the slicer's *preferred* batch size as a *hard* contract | Every existing `BatchResult` test used `len(topics) >= _MIN_BATCH`; asymmetric-tail case was never constructed |

The common factor: **none of these are visible until `run_cycle_steps` runs end-to-end with realistic inputs**. The "e2e" test that exists (`tests/pipeline/test_e2e_synthetic_vault.py`) monkey-patches `run_cycle_steps` with a fake — it tests the orchestrator wrapper, not the cycle runner itself, so it caught zero of the three bugs.

### Real cost of the gap

- Each failed end-user run consumes 50K–200K LLM tokens at production prices before crashing.
- Each diagnosis round-trip costs the developer 15–60 minutes of attention and 10K–50K agent tokens for the post-mortem chat.
- The release cadence is **broken**: three consecutive hot-fix releases in three days, each fixing the previous one's seam bug.
- Developer trust in the test suite is eroded: "1053 tests pass" tells the developer nothing about whether the bundle will actually run a cycle.

### What this spec is NOT trying to fix

This spec adds testing infrastructure. It does **not** change pipeline behavior, fix any individual bug, or alter the release cadence. The goal is purely: **stop shipping bundles that fail on the first cycle.**

## Clarifications

### Session 2026-05-17

- Q: Which failure mode hurts most — token cost, iteration speed, or release quality? → A: Iteration speed (fast seam tests catch drift before bundling) AND release quality (full pipeline must complete e2e before stamping a version). Token cost is the consequence, not the constraint.
- Q: Approach A (minimal) vs B (layered with reusable fakes) vs C (property-based)? → A: B — a formal pyramid with shared fake-agent infrastructure, single-cycle and multi-cycle e2e tests, and a hard build gate.
- Q: How strict should the release gate be? → A: Hard gate. `build.sh` refuses to build a bundle if the e2e tier fails. No "warn only," no separate command the developer might forget.
- Q: Does this replace or complement Spec Kit feature 017 (vault-quality-fix)? → A: Complements. 017 fixed *what* the pipeline does; 018 fixes *how we verify* that fixes don't drift between releases.
- Q: Real LLM calls in any test tier? → A: Never. Every tier uses deterministic fakes. The only place real agents run is the user's actual `./generate.sh` invocation against a real vault.

## User Scenarios & Testing

### User Story 1 — A reusable fake-agent module replaces every external LLM call in the test suite (Priority: P0)

A new `tests/_helpers/fake_agent.py` module is the single source of truth for how the test suite stubs out `scripts/agent_call.py`. The fake knows how to:

- Emit a valid **v2 scout report** (`cycle-NNN-scout.json`) for any spec, including configurable `topics_found.new`, `topics_from_code`, `intent_from_confluence`, and `dimensions_covered`.
- Emit valid **note files** for every topic in a `## Batch topics (JSON)` block, with proper YAML frontmatter (type, coverage_category, source_urls, summary, lifecycle.created_at_cycle, related, template_version) and Markdown body that satisfies the active note-type's `min_word_count`.
- Append the correct entry to **`cycle-NNN-research.json`** (notes_created, notes_updated) after each batch.
- Write a valid **`--cost-sidecar`** JSON file with input/output tokens and zero USD cost.
- Be **deterministic**: same prompt → same output, regardless of run order.

**Why this priority**: This is the keystone of the entire strategy. Without it, tier 4–5 (single- and multi-cycle e2e) cost real money and cannot run in CI or local dev. With it, every tier becomes free.

**Independent Test**: Drop the fake's `agent_call.py` shim into a temp scripts directory, invoke it directly with `--stage scout` and `--stage note_writer` against a hand-written prompt, and assert the produced artefacts pass `scripts/validate_cycle.py` and `scripts/validate_vault.py`.

**Acceptance Scenarios**:

1. **Given** a vault with a v2 research.spec.md and a fake `agent_call.py` shim wired to `tests/_helpers/fake_agent.py`, **When** the test invokes `python scripts/agent_call.py --vault $VAULT --stage scout --prompt-file $PROMPT --cost-sidecar $COST`, **Then** the produced `cycle-001-scout.json` contains every field listed in `REQUIRED_REPORT_FIELDS_V2` and passes `validate_cycle.py` with `--scout-only` exit 0.
2. **Given** a batch prompt containing a `## Batch topics (JSON)` block with 4 topics, **When** the same shim is invoked with `--stage note_writer`, **Then** 4 valid markdown files appear under `data_vault/<folder>/` and `cycle-001-research.json` is updated atomically with all 4 in `notes_created`.
3. **Given** identical inputs run twice, **When** both runs complete, **Then** every output file is byte-identical (determinism).

---

### User Story 2 — Single-cycle e2e test exercises the real `run_cycle_steps` against the fake agent (Priority: P0)

A new `tests/pipeline/test_full_cycle_e2e.py` drives the **real** `research_vault.pipeline.cycle_runner.run_cycle_steps` against a temp vault built by `tests/_helpers/vault_factory.py`. The fake `agent_call.py` from US1 is installed before invocation. The test asserts that:

- `run_cycle_steps` returns 0 (or a documented soft-failure code).
- Every expected artefact lands on disk: `cycle-NNN-scout.json`, `cycle-NNN-research.json`, `cycle-NNN-batch-NNN.json`, `cycle-NNN-quality-report.json`, `cycle-NNN-timings.json`, `cycle-NNN-summary.md`, plus `N` markdown notes under `data_vault/`.
- Every emitted JSON validates against its schema.
- No exception propagates out of `run_cycle_steps`; a CG/SG FAIL is acceptable but a `ValueError` / `KeyError` / `AttributeError` is a test failure.

The test file contains **at least five named scenarios** covering the failure modes we have actually seen in production:

1. `test_happy_path_single_cycle` — 15 topics, batch_size=6 → 3 + 3 + 3 + 3 + 3, every gate green, exit 0.
2. `test_asymmetric_tail_batch_serializes` — 8 topics, batch_size=3 → 3 + 3 + 2, exit 0, batch-003 written with `len(topics) == 2` (locks 0.2.22).
3. `test_empty_scout_queue_aborts_via_sg001` — scout returns 0 `topics_found.new` and 0 `topics_from_code` → SG-001 FAIL → cycle aborts with exit 2 and a quality-report explaining why (no exception, no orphans).
4. `test_corrupted_skill_file_self_repairs_in_preflight` — overwrite `.agents/skills/scout/SKILL.md` with invalid YAML before invoking → preflight restores from `dist-templates/`, cycle proceeds, exit 0.
5. `test_sg005_failure_triggers_correction_batch` — fake agent skips frontmatter on first batch → SG-005 FAIL → correction directive issued → second pass succeeds, cycle exits 0 or 1 (documented).

**Why this priority**: This is the test that would have caught all three of 0.2.20–0.2.22. It is also the keystone that the hard gate (US4) enforces. Without US2, US4 has nothing to gate on.

**Independent Test**: `pytest tests/pipeline/test_full_cycle_e2e.py -v` against a clean checkout — every scenario passes in under 10 seconds, no network, no real agents, zero token spend.

**Acceptance Scenarios**:

1. **Given** the fake-agent shim from US1 and a minimal vault factory, **When** `run_cycle_steps(vault, 1, 100.0, 10)` is invoked, **Then** the call returns within 10 seconds, returns 0 or a soft-failure code (1 / 2), and produces every expected on-disk artefact.
2. **Given** the asymmetric-queue scenario (8 topics, batch_size=3), **When** the cycle completes, **Then** three `cycle-001-batch-*.json` files exist with topic counts `[3, 3, 2]` and every batch report validates against the batch-report schema.
3. **Given** any scenario in this file fails on `main`, **When** the developer runs `pytest tests/pipeline/test_full_cycle_e2e.py -v`, **Then** the failure points at a specific cycle stage (scout / plan / dispatch / validate / report) — not a generic stack trace from inside `cycle_runner`.

---

### User Story 3 — Multi-cycle e2e test exercises cycle-to-cycle state transfer (Priority: P1)

A new `tests/pipeline/test_multi_cycle_e2e.py` runs **three cycles back-to-back** through the orchestrator (`run_cycles`) with the fake agent and asserts:

- Coverage progresses: cycle 1 fills 5 targets, cycle 2 fills 5 more (no duplicates), cycle 3 fills 5 more.
- `research-plan.md` is regenerated between cycles with shrinking gaps.
- `_pipeline/run-report.md` lists three cycles in chronological order with correct timing + cost data.
- No note file is overwritten between cycles (lifecycle.created_at_cycle is preserved).
- The cumulative SQLite source-preflight DB (`_pipeline/sources.db`) grows monotonically and never throws "database is locked".

Scenarios:

1. `test_three_cycles_progress_coverage` — three clean cycles, asserts coverage state moves forward each cycle.
2. `test_cycle_two_picks_up_where_cycle_one_left_off` — cycle 1 finishes with 3/10 in `cat_a`; cycle 2 starts and fills `cat_a` to 6/10 without reprocessing the same topics.
3. `test_correction_loop_across_cycles` — cycle 1 fails CG (coverage gate), retry triggers cycle 2 with correction directive, cycle 2 passes.

**Why this priority**: P1 because cycle-to-cycle bugs have not yet bitten in production — but they are the next class of seam bug that will. The user has only ever run 1 cycle so far; the moment a real run progresses to cycle 2, drift between cycle-end state and cycle-start input becomes the next failure surface.

**Independent Test**: `pytest tests/pipeline/test_multi_cycle_e2e.py -v` — every scenario passes in under 30 seconds.

**Acceptance Scenarios**:

1. **Given** a vault factory configured for 3 cycles and the fake agent, **When** `run_cycles(spec, vault)` is invoked, **Then** the call returns within 30 seconds and produces `cycle-{001,002,003}-*.json` and a `_pipeline/run-report.md` listing all three.
2. **Given** cycle 1 has filled 3/10 of `cat_a`, **When** cycle 2 starts, **Then** the cycle 2 priority queue contains the remaining 7 `cat_a` titles and excludes the 3 already written.

---

### User Story 4 — `build.sh` refuses to build a bundle if the e2e tier fails (Priority: P0)

`build.sh` gains a mandatory **smoke gate** that runs `pytest tests/pipeline/test_full_cycle_e2e.py tests/pipeline/test_multi_cycle_e2e.py -q` before the wheel is built. If the gate fails:

- The build aborts with a non-zero exit code.
- The bundle tarball is **not** created.
- The error message tells the developer which scenario failed and how to reproduce it locally.
- There is no `--skip-smoke` flag. The only way to ship a broken bundle is to delete the gate from `build.sh`, which is a code change requiring intent.

The gate runs in under 60 seconds total (US2 + US3 combined), so it does not meaningfully slow the build.

**Why this priority**: P0 because every other piece of this spec is wasted effort if a developer can release a bundle that bypasses the tests. The hard gate is the structural enforcement that turns "we have e2e tests" into "we cannot ship without passing e2e tests."

**Independent Test**: Introduce a deliberate regression in `pipeline/batch.py` (e.g. re-tighten the serializer to `5..10`), run `./build.sh`, assert it exits non-zero and no `build/research-vault-*.tar.gz` is produced.

**Acceptance Scenarios**:

1. **Given** a clean tree where all tests pass, **When** the developer runs `./build.sh`, **Then** the smoke gate runs (visible output), the wheel is built, and the bundle tarball is produced.
2. **Given** a regression that breaks `test_asymmetric_tail_batch_serializes`, **When** the developer runs `./build.sh`, **Then** the build aborts with exit code 1 BEFORE the wheel is built, the bundle tarball is not produced, and the error message names the failing scenario.

---

### User Story 5 — Seam-test convention documented so future contributors know where to add tests (Priority: P2)

A new `docs/testing-strategy.md` documents the six-tier pyramid (unit → schema contract → seam → single-cycle e2e → multi-cycle e2e → smoke gate), lists the canonical example test for each tier, and gives a one-paragraph decision tree for "which tier do I add a test at?":

- New pure function with no I/O → tier 1 (unit)
- New JSON/Markdown output format or change to existing format → tier 2 (schema contract)
- Change to data flow between two modules (A produces X, B consumes X) → tier 3 (seam)
- Change to `run_cycle_steps` orchestration → tier 4 (single-cycle e2e)
- Change to `run_cycles` orchestration or cycle-to-cycle state → tier 5 (multi-cycle e2e)

The doc lives at the repo root for discoverability and is referenced from `CLAUDE.md` so AI agents adding code follow the same convention.

**Why this priority**: P2 because convention without enforcement is wishful thinking — the actual seam coverage is what catches bugs, not the doc. But P2, not skipped, because the team's next 6 months of contributions need a shared mental model or they will revert to "unit tests only" by inertia.

**Independent Test**: A new contributor (or an AI agent) is given a feature to add (e.g., "add a new SG gate"). They read `docs/testing-strategy.md` and produce both a unit test and a tier-3 seam test without being asked separately.

**Acceptance Scenarios**:

1. **Given** the docs are in place, **When** a contributor opens a PR that changes `pipeline/batch.py`, **Then** the PR template (or a CI advisory) reminds them to add a tier-3 seam test if the change affects an output contract.
2. **Given** the docs reference each canonical example test, **When** a contributor wants to add a tier-4 test, **Then** they find a working example to copy in under 60 seconds.

---

## Acceptance coverage

Backfilled per spec 024 FR-013 (ADR-0008). Each row ties the user story to
its contract under `specs/018-testing-strategy/contracts/` and the
matching tier-2 contract or guard tests.

| User Story | Evidence |
|------------|----------|
| US1 — A reusable fake-agent module replaces every external LLM call in the test suite | `specs/018-testing-strategy/contracts/fake-agent.contract.md` + `tests/_helpers/test_fake_agent_contract.py` |
| US2 — Single-cycle e2e test exercises the real `run_cycle_steps` against the fake agent | `specs/018-testing-strategy/contracts/fake-agent.contract.md` + `tests/pipeline/test_full_cycle_e2e.py` |
| US3 — Multi-cycle e2e test exercises cycle-to-cycle state transfer | `specs/018-testing-strategy/contracts/vault-factory.contract.md` + `tests/pipeline/test_multi_cycle_e2e.py` |
| US4 — `build.sh` refuses to build a bundle if the e2e tier fails | `tests/pipeline/test_full_cycle_e2e.py` + `tests/pipeline/test_multi_cycle_e2e.py` (smoke gate via `./build.sh`) |
| US5 — Seam-test convention documented so future contributors know where to add tests | `specs/018-testing-strategy/contracts/llm-dispatch-guard.contract.md` + `tests/_helpers/test_llm_dispatch_guard.py` + `tests/_helpers/test_vault_factory_contract.py` |

## Success Criteria

This feature is complete when **every** criterion below is true. These are external observations a stakeholder can verify without reading the code.

- **SC-001**: `pytest tests/pipeline/test_full_cycle_e2e.py tests/pipeline/test_multi_cycle_e2e.py -q` completes in under 60 seconds total, with zero external network calls and zero real LLM token spend.
- **SC-002**: Re-introducing the exact 0.2.20 bug (scout output not merged into plan) causes `test_empty_scout_queue_aborts_via_sg001` to fail with a clear "scout topics not reaching dispatcher" message — not a generic stack trace.
- **SC-003**: Re-introducing the exact 0.2.21 bug (placeholder generation) causes a tier-3 seam test to fail before the e2e tier — i.e. the bug is caught at the cheapest possible tier.
- **SC-004**: Re-introducing the exact 0.2.22 bug (`BatchResult.to_dict` tightened back to `3..10`) causes `test_asymmetric_tail_batch_serializes` to fail.
- **SC-005**: Running `./build.sh` against a tree with any failing e2e test exits non-zero and produces no tarball. Verified by deliberately breaking a test.
- **SC-006**: A contributor reading `docs/testing-strategy.md` for the first time can answer "which tier should I add a test at?" for at least 4 of 5 representative change types without further help.
- **SC-007**: The fake-agent module is the single source of truth for stubbing LLM calls. No test file invokes `subprocess` or `Popen` against a real `claude` / `codex` binary.
- **SC-008**: The next three bundle releases (0.2.23 onward) ship without a seam-bug hot-fix release within 7 days. (Long-running outcome metric.)

## Out of Scope

- Property-based / hypothesis-style tests (Approach C). Worth considering later but not for this feature.
- Mutation testing (e.g. `mutmut`).
- Performance benchmarking of the cycle runner.
- CI infrastructure (GitHub Actions, etc.) — the hard gate lives in `build.sh` only.
- Real LLM-backed integration tests against `claude` / `codex` CLIs.
- Changes to the `scripts/agent_call.py` itself — only the stub equivalent.
- Refactoring existing unit tests (1053 tests) to fit the new pyramid taxonomy. New tests follow the taxonomy; existing tests are grandfathered.

## Constraints

- **No new runtime dependencies.** All test-only additions go under `[project.optional-dependencies.dev]` if needed; pytest, hypothesis are the only acceptable additions, and hypothesis is out of scope for this feature.
- **No real agent calls.** Every test must be deterministic and free.
- **Test suite must remain under 3 minutes total wall-clock time.** Adding e2e tier must not bloat the suite past this limit.
- **Backwards compatibility:** existing tests must continue to pass unchanged. The new fake-agent module replaces ad-hoc stubs (`tests/fixtures/stubs/claude`) only after the new tier-4 tests are proven on it.

## Non-Goals (Explicit)

- This feature does not attempt to detect every possible seam bug in advance. It establishes the *infrastructure* to add seam tests cheaply when new seams are introduced.
- This feature does not change the cycle-runner's behavior. If a tier-4 test reveals a bug, that bug is fixed in a separate feature.
- This feature does not produce a regression-test for every existing bug. It produces regression tests for the three documented bugs (0.2.20, 0.2.21, 0.2.22) as the seed examples, and the convention for adding more.
