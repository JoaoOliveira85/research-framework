# Tasks: Pipeline Architecture & Seam-Bug Elimination

**Feature**: `019-pipeline-architecture` | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)
**Generated**: 2026-05-17

In-scope for 0.2.28: **US1 (extended smoke gate) + US2 (four HIGH-severity
seam fixes)**. US3-US6 are captured in spec-019 but deferred per the
2026-05-17 clarify session.

## Phase 1 — Setup

- [ ] T001 Confirm branch `019-pipeline-architecture` is checked out from `017-vault-quality-fix`; spec.md + plan.md present in `specs/019-pipeline-architecture/`
- [ ] T002 Verify full sweep is GREEN on the current 0.2.27 baseline before any modification: `python -m pytest tests/ -q --ignore=tests/cli/test_migrate_cli.py` returns "1128 passed, 2 skipped"

## Phase 2 — Foundational

No foundational blockers. Each H-bug fix and the smoke-gate change are
independent.

## Phase 3 — User Story 1: Extended smoke gate (P1)

**Story Goal**: `./build.sh` refuses to produce a wheel when any tier-2
contract test fails.

**Independent Test**: Deliberately rename `budget_consumed_usd` →
`spend_dollars` in `dfs-prompt.md.j2`; run `./build.sh`; assert exit
code ≠ 0 and stdout names `test_prompt_validator_contract.py` as the
failing test. (Revert before commit.)

- [ ] T010 [US1] [P] Catalogue the tier-1/tier-2 contract test files to include in the extended gate; document in `tests/build/CONTRACT_TIER_INCLUDES.md` (new file) — union of:
  - `tests/scripts/test_validate_cycle*.py`
  - `tests/scripts/test_prompt_validator_contract.py`
  - `tests/scripts/test_validate_spec.py`
  - `tests/scripts/test_check_abstraction.py`
  - `tests/scripts/test_quality_report.py`
  - `tests/scripts/test_probe_runner.py`
  - `tests/pipeline/test_preconditions*.py`
  - `tests/pipeline/test_full_cycle_e2e.py`
  - `tests/pipeline/test_multi_cycle_e2e.py`
  - All of `tests/_helpers/`
- [ ] T011 [US1] Write `tests/build/test_smoke_gate_enforces_contract_tier.py`: parses `build.sh` to extract the smoke-gate test list; asserts it matches the file from T010
- [ ] T012 [US1] Edit `build.sh` Section 0 (existing smoke gate block): expand the test list from the current two e2e files to the union from T010
- [ ] T013 [US1] Run `./build.sh` end-to-end against the unmodified codebase; assert it produces a 0.2.28-staged wheel (precondition before T020-T023)
- [ ] T014 [US1] Add a `--explain` flag to `build.sh` smoke-gate block: on FAIL, print `[smoke gate] failing test(s):` followed by the failing pytest test ids — so users know WHICH contract drifted (not just "the build failed")

## Phase 4 — User Story 2: Fix four HIGH-severity latent seams (P1)

**Story Goal**: H1–H4 are closed in 0.2.28 with regression tests in the
smoke gate.

**Independent Test**: For each H-bug, the new regression test fails on
unpatched code and passes on patched code.

### H1: DFS budget cap field-name resolution

Today: `validate_cycle.py:592` reads `report.get("budget_consumed_usd", 0)` ONLY. Structure check at `:494-501` accepts three aliases. Agent emits `cumulative_cost_usd` → structure check passes → cap check sees 0 → cap never trips.

- [ ] T020 [US2] [P] Write `tests/scripts/test_validate_cycle_budget_aliases.py`: 3 tests — research report with only `cumulative_cost_usd`/only `cost_estimate_usd`/only `budget_consumed_usd`, each at 90% of budget cap; assert Condition C fires correctly (TERMINATE / budget) for all three (RED on unpatched)
- [ ] T021 [US2] Edit `scripts/validate_cycle.py` `check_termination_v2` (around line 592): replace `report.get("budget_consumed_usd", 0)` with a helper that resolves the first non-None of the three aliases in `BUDGET_FIELDS_V2_RESEARCH` (which was added in 0.2.25 for structure check); apply the same resolution to v1 (`cumulative_cost_usd` path at `:253, :278-288`) if a similar latent path exists
- [ ] T022 [US2] Verify T020 tests are GREEN

### H2: v2 `sources_consulted` validation missing

Today: `check_termination_v2` never validates `sources_consulted`. A v2 scout/research report with `sources_consulted: []` or `{}` or wrong type passes the validator entirely. (v1 has `validate_sources` at `:227-228`; v2 was never wired.)

- [ ] T030 [US2] [P] Write `tests/scripts/test_validate_cycle_sources_consulted.py`: 4 tests — v2 scout with missing required source / malformed shape / wrong-type / correct shape. Required sources are derived from `_pipeline/spec-parse.json`'s `data_sources[*].name` where `required=true` (RED on unpatched)
- [ ] T031 [US2] Edit `scripts/validate_cycle.py`: factor a `validate_sources_v2(report, pipeline_dir)` helper modeled on the v1 `validate_sources`; call it from `check_termination_v2` for BOTH scout and research phases; respect the existing `required=true` semantics
- [ ] T032 [US2] Verify T030 tests are GREEN

### H3: DFS termination field aliasing

Today: `dfs-prompt.md.j2:127-128` shows agents how to emit `next_action` + `termination_reason`. `validate_cycle.py:593-624` reads ONLY `termination_condition`. An agent following the prompt example never trips A/B/C.

- [ ] T040 [US2] [P] Write `tests/scripts/test_validate_cycle_termination_fields.py`: 3 tests — research reports using (a) only `termination_condition: "B"`, (b) only `next_action: "terminate"` + `termination_reason: "<condition B reason>"`, (c) both. All three must reach the same termination decision (RED on unpatched for path b)
- [ ] T041 [US2] Edit `scripts/validate_cycle.py:check_termination_v2`: when `termination_condition` is absent, fall back to interpreting `next_action`/`termination_reason` (map to A/B/C) AND emit a single `DeprecationWarning` via `logging.warning`. Document removal in 0.3.0.
- [ ] T042 [US2] Edit `templates/prompts/dfs-prompt.md.j2`: replace `next_action`/`termination_reason` in the JSON example with `termination_condition` as the canonical field; keep an explicit note in prose that the old names are still accepted but deprecated
- [ ] T043 [US2] Verify T040 tests are GREEN

### H4: `_resume` skips Phase 3 (coverage gate, code-first gate, reindex, generate-report)

Today: `src/research_vault/cli.py::_resume` calls `run_cycles` and exits. `_cmd_generate` (line 168-201) has 30+ lines of Phase 3 work after the cycle loop. `--resume` never touches it.

- [ ] T050 [US2] [P] Write `tests/pipeline/test_resume_phase3_completion.py`: 3 tests — (a) a resume that finishes cycle N (not the terminal cycle) does NOT run Phase 3; (b) a resume whose final cycle TERMINATES via condition A/B/C runs Phase 3 to completion; (c) Phase 3 outputs (`run-report.md`, reindex artifacts) exist after the terminating resume (RED on unpatched)
- [ ] T051 [US2] Edit `src/research_vault/cli.py::_resume`: after `run_cycles` returns, detect whether the run reached terminal state (read `_pipeline/run-report.md` or the final cycle's report for the termination signal); if terminal, factor the Phase 3 logic from `_cmd_generate` into a shared `_run_phase3(spec, vault_dir)` helper and call it
- [ ] T052 [US2] Verify T050 tests are GREEN

### Cross-H validation

- [ ] T060 [US2] Run full sweep: `python -m pytest tests/ -q --ignore=tests/cli/test_migrate_cli.py` ≥ 1140 passing
- [ ] T061 [US2] Update `tests/_helpers/vault_factory.py`: add `code_first_with_local_paths()` factory variant that produces a spec with both `url` AND `local_path` per repo (the 0.2.27 shape); use this in at least one parameterised scout test so tier-4 e2e exercises the dual-shape repo case going forward

## Phase 5 — Polish & Release

- [ ] T070 Bump `src/research_vault/__init__.py` version `0.2.27` → `0.2.28`
- [ ] T071 Bump `pyproject.toml` version `0.2.27` → `0.2.28`
- [ ] T072 Prepend CHANGELOG.md `[0.2.28]` entry under `[Unreleased]`, summarising:
  - US1 extended smoke gate (which test files are now in the gate)
  - US2 H1–H4 fixes (one paragraph per H-bug with file+line of fix and test)
  - Pointer to spec-019 for US3-US6 deferred work
- [ ] T073 Run lint: `ruff check src/research_vault/ scripts/ tests/`
- [ ] T074 Run `./build.sh`; assert it produces `build/research-vault-0.2.28.tar.gz`
- [ ] T075 Smoke-test the bundle: extract to `/tmp/research-vault-0.2.28-smoke`, run `./install.sh` non-interactively, verify install completes with no errors
- [ ] T076 Reproduce the user's install command sequence (rebuild bundle path, copy spec/settings, run install); verify against the user's `~/Documents/research-vault-0.2.24/research.spec.md`

## Dependencies

```text
T001 ──┐
T002 ──┤
       ├─→ T010 (parallel head)
       ├─→ T020, T030, T040, T050 (parallel H-bug TDD heads — each independent)
       │
T010 ──┼─→ T011 ──→ T012 ──→ T013 ──→ T014
       │
T020 ──┼─→ T021 ──→ T022
T030 ──┼─→ T031 ──→ T032
T040 ──┼─→ T041 ──→ T042 ──→ T043
T050 ──┼─→ T051 ──→ T052
       │
       ├─→ T060 (after all H-fix verifications)
       └─→ T061 (independent, can run any time after T002)

T013 + T060 ──→ T070 → T071 → T072 → T073 → T074 → T075 → T076
```

## Parallel Execution

- T010, T020, T030, T040, T050 can all be dispatched together (each TDD test write is independent).
- T021, T031, T041, T051 can run in parallel (different files).
- T012 (build.sh) is independent of all US2 work (different file entirely).

## MVP Scope (if time-constrained)

**Minimum viable 0.2.28**: US1 (smoke gate) + US2 H1 + US2 H4. Reasoning:
- H1 is the most likely to bite production again (budget cap is silent).
- H4 affects every resume run starting NOW.
- H2 and H3 are real but require an agent following the prompt example
  literally to trigger; lower probability per run.

If time permits, add H2 and H3.

## Definition of Done

- [ ] All T0xx tasks marked `[X]`
- [ ] `./build.sh` produces `build/research-vault-0.2.28.tar.gz`
- [ ] User's install command sequence (`cp -r ... cd ... ./install.sh`) completes cleanly on the rebuilt bundle
- [ ] CHANGELOG describes US1+US2 and points at spec-019 for the deferred US3-US6
