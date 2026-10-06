---

description: "Implementation task list for 018-testing-strategy"
---

# Tasks: Layered Testing Strategy

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Input**: Design documents from `/specs/018-testing-strategy/`
**Prerequisites**: plan.md ✓, spec.md ✓
**Tests**: REQUIRED — Constitution Principle III (Test-First TDD) is NON-NEGOTIABLE. This feature *is* the test apparatus; every deliverable is a test or supporting infrastructure for tests. RED-first commitments are documented in plan.md § Phase 1.

**Organization**: Tasks are grouped by user story (US1..US5 from spec.md) in priority order (P0 → P2). MVP = US1 + US2 + US4 (the three P0 stories — without all three, the gate cannot enforce anything because there is nothing to gate on, and the gate is the structural enforcement that makes the rest matter).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks).
- **[Story]**: Which user story (US1..US5). Setup/Foundational/Polish phases have no story label.
- All file paths are repository-relative.

## Path Conventions

Single-project Python layout (per plan.md § Project Structure):

- Test helpers: `tests/_helpers/` (NEW dir)
- E2E tests: `tests/pipeline/test_full_cycle_e2e.py`, `tests/pipeline/test_multi_cycle_e2e.py` (NEW files)
- Contracts: `specs/018-testing-strategy/contracts/` (NEW dir)
- Docs: `docs/testing-strategy.md` (NEW file)
- Build gate: `build.sh` (MODIFIED)
- Markers: `pyproject.toml` (MODIFIED — add `markers` config)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Repo plumbing for the new test-only modules and the spec's contracts directory.

- T001 Create `tests/_helpers/` directory with `__init__.py` containing the module docstring `"""Reusable test infrastructure for feature 018 — fake agents, vault factories, etc."""`. Verify `pyproject.toml`'s `pythonpath = ["src"]` discovery still finds the package by running `pytest --collect-only tests/_helpers/` (should report 0 tests, 0 errors).
- T002 [P] Create `specs/018-testing-strategy/contracts/` directory and add a `README.md` listing the contract files this feature produces. Initial entry: `fake-agent.contract.md`.
- T003 [P] Register the new `e2e` marker in `pyproject.toml` under `[tool.pytest.ini_options]`: add `markers = ["e2e: end-to-end pipeline tests using the fake agent (feature 018)"]`. Verify `pytest --markers | grep e2e` lists it.
- T004 [P] Bump `pyproject.toml` `[project] version = "0.2.23"` (additive feature — minor bump per SemVer-for-PATCH because this introduces NO production behavior changes; only test infrastructure).

## Phase 2: Foundational Contracts (Blocks All Stories)

**Purpose**: Write the fake-agent contract and the vault-factory contract BEFORE either implementation, so US1 has a target to satisfy.

- T005 [P] Write `specs/018-testing-strategy/contracts/fake-agent.contract.md`. Sections: (a) command-line interface — every flag the real `scripts/agent_call.py` accepts that the fake must also accept (`--vault`, `--stage`, `--prompt-file`, `--cost-sidecar`, `--output-file`); (b) input parsing — for `--stage scout`, the fake reads `--prompt-file` and produces a deterministic scout report based on the spec referenced in the prompt; for `--stage note_writer`, the fake parses the `## Batch topics (JSON)` code block from the prompt; (c) output artefacts — exact JSON shape for `cycle-NNN-scout.json` (v2: `schema_version`, `cycle`, `phase`, `timestamp`, `dimensions_covered`, `topics_from_code`, `intent_from_confluence`, `sources_consulted`, `budget_consumed_usd`, `topics_found`), exact JSON shape for the cost sidecar (`cost_usd`, `input_tokens`, `output_tokens`), exact frontmatter shape for emitted notes (`type`, `coverage_category`, `source_urls`, `summary`, `lifecycle.created_at_cycle`, `related`, `template_version`); (d) determinism guarantee — same inputs → byte-identical outputs; (e) scenarios — empty-scout mode (returns 0 `topics_found.new`), skip-batch mode (returns subset of assigned topics), fail-frontmatter mode (omits a required field — used by US2 scenario 5).
- T006 [P] Write `specs/018-testing-strategy/contracts/vault-factory.contract.md`. Sections: (a) Python API — `build_minimal_vault(tmp_path: Path, *, num_categories: int = 3, num_targets_per_category: int = 5, spec_overrides: dict | None = None) -> Path` returns the vault root path; (b) post-conditions — vault MUST contain `research.spec.md`, `settings.yaml`, `.agents/skills/` with at least scout/note-writer/verifier skills, `scripts/` with the real bundled scripts (including the test's fake `agent_call.py` installed by the test, not the factory), `_pipeline/` with `coverage-targets.json` and `spec-parse.json`, `data_vault/` with subdirs per category; (c) post-condition validation — running `python scripts/validate_vault.py --vault $VAULT` against a fresh factory output MUST exit 0 (no false-positive failures); (d) determinism — same arguments → same paths and contents.

## Phase 3: User Story 1 (P0) — Reusable Fake Agent Module

**Purpose**: Build the keystone artefact. Every subsequent tier-4/5 test depends on this.

### TDD — Tests First (RED)

- T007 [US1] Create `tests/_helpers/test_fake_agent_contract.py` with five named tests asserting the contract from T005: `test_scout_stage_emits_v2_schema`, `test_scout_stage_passes_validate_cycle`, `test_note_writer_stage_writes_one_note_per_batch_topic`, `test_note_writer_stage_appends_to_research_json_atomically`, `test_determinism_byte_identical_outputs_for_same_inputs`. All five MUST be RED until T009 lands (the `fake_agent` module exists but every function raises `NotImplementedError`).

### Implementation (GREEN)

- T008 [US1] Create the `fake_agent.py` SKELETON at `tests/_helpers/fake_agent.py`: module docstring linking to `contracts/fake-agent.contract.md`, public functions `write_scout(vault: Path, cycle: int, *, spec, scenario: str = "happy") -> Path`, `process_batch(vault: Path, prompt_file: Path, cycle: int, *, scenario: str = "happy") -> list[Path]`, and `main(argv: list[str] | None = None) -> int` (the CLI entry point — argparse over `--vault`, `--stage`, `--prompt-file`, `--cost-sidecar`). Every function body is `raise NotImplementedError("see contracts/fake-agent.contract.md")`. Verify `pytest tests/_helpers/test_fake_agent_contract.py` reports "5 failed, 0 passed" (RED).
- T009 [US1] Implement `write_scout`: parse the prompt to discover the vault's spec via `_pipeline/spec-parse.json`, emit a v2 scout report with the exact fields listed in T005(c), use the spec's `coverage_targets` to derive `topics_found.new` for the "happy" scenario (one topic per gap, up to a configurable max), emit `[]` for the "empty_scout" scenario. Write the file atomically (write temp + rename). Make `test_scout_stage_emits_v2_schema` and `test_scout_stage_passes_validate_cycle` GREEN.
- T010 [US1] Implement `process_batch`: parse the `## Batch topics (JSON)` markdown block from the prompt (regex per plan.md Phase 0 design decision), write one note per topic into the right `data_vault/<folder>/<slug>.md` path with valid frontmatter per T005(c), append to `cycle-NNN-research.json` atomically (read-modify-write under a lockfile or rename-from-temp pattern). Honor the "fail_frontmatter" scenario by omitting `source_urls` from one note (used by US2 scenario 5). Make `test_note_writer_stage_writes_one_note_per_batch_topic` and `test_note_writer_stage_appends_to_research_json_atomically` GREEN.
- T011 [US1] Implement `main`: argparse, dispatch to `write_scout` or `process_batch` based on `--stage`, write the `--cost-sidecar` JSON (`{"cost_usd": 0.0, "input_tokens": 100, "output_tokens": 50}`), return 0. Make `test_determinism_byte_identical_outputs_for_same_inputs` GREEN (requires no randomness anywhere — use sorted iteration, deterministic timestamps from the spec).
- T012 [US1] Verify the round-trip end-to-end: drop a hand-written prompt file into `tmp_path`, invoke `python -m tests._helpers.fake_agent --stage scout --vault $VAULT --prompt-file $PROMPT --cost-sidecar $COST`, assert exit 0 and the produced files validate. This task adds NO new test — it's a sanity check that T007–T011 collectively satisfy the contract.

### Checkpoint US1

All five tests in `test_fake_agent_contract.py` GREEN. The fake agent is now usable by US2 / US3.

---

## Phase 4: User Story 2 (P0) — Single-Cycle E2E Tests

**Purpose**: The five scenarios that would have caught 0.2.20 / 0.2.21 / 0.2.22. Locks them as regression tests forever.

### TDD — Tests First (RED, then GREEN as production code is verified clean)

- T013 [US2] Create `tests/_helpers/vault_factory.py` with `build_minimal_vault` per T006's contract. Skeleton first (`raise NotImplementedError`), then implementation that calls the existing `research_vault.generator.scaffold.scaffold` + `research_vault.generator.render.render_all` + `research_vault.generator.scripts.copy_scripts` chain against a synthetic `SpecConfig` (reuse the synthetic spec from `tests/pipeline/test_e2e_synthetic_vault.py::_synthetic_spec` if possible, or extract it to the factory). After the factory builds the vault, the test installs the fake `agent_call.py` over the real one (`shutil.copy(fake_agent.cli_path(), vault / "scripts" / "agent_call.py")`).
- T014 [US2] Create `tests/_helpers/test_vault_factory_contract.py` with one test: `test_factory_output_passes_validate_vault`. RED until T013 implementation lands.
- T015 [P] [US2] Create `tests/pipeline/test_full_cycle_e2e.py` with the file-level docstring linking to spec.md § US2, the `@pytest.mark.e2e` decorator on every test, and five test stubs: `test_happy_path_single_cycle`, `test_asymmetric_tail_batch_serializes`, `test_empty_scout_queue_aborts_via_sg001`, `test_corrupted_skill_file_self_repairs_in_preflight`, `test_sg005_failure_triggers_correction_batch`. Each body: `assert False, "PENDING — see plan.md Phase 1"`. Verify `pytest tests/pipeline/test_full_cycle_e2e.py -v` reports 5 failed, 0 passed.
- T016 [US2] Implement `test_happy_path_single_cycle`: build vault with 15 spec targets and `batch_size=6`, install fake agent in "happy" mode, invoke `research_vault.pipeline.cycle_runner.run_cycle_steps(vault, 1, 100.0, 10)`, assert return code is 0, assert `cycle-001-{scout,research}.json` exist and validate, assert three batches landed with sizes `[5, 5, 5]` (or whatever the slicer produces — read the actual values from the produced batch files), assert ≥ 1 note exists under `data_vault/`. Make GREEN.
- T017 [US2] Implement `test_asymmetric_tail_batch_serializes`: build vault with 8 spec targets and `batch_size=3`, run cycle, assert return code in `(0, 1)`, assert three batches exist with sizes `[3, 3, 2]`, assert each batch JSON validates. This is the regression for 0.2.22. Make GREEN (the fix shipped in 0.2.22; test should already pass).
- T018 [US2] Implement `test_empty_scout_queue_aborts_via_sg001`: configure fake agent in "empty_scout" mode (returns 0 `topics_found.new` and 0 `topics_from_code`), run cycle, assert return code is 2 (abort), assert `cycle-001-quality-report.json` contains an SG-001 FAIL entry with a clear message, assert NO `cycle-001-batch-*.json` exists, assert NO `data_vault/<folder>/*.md` was created. This is the regression for 0.2.20. Make GREEN.
- T019 [US2] Implement `test_corrupted_skill_file_self_repairs_in_preflight`: build vault, overwrite `.agents/skills/scout/SKILL.md` with invalid YAML (`flatten the multiline strings`), run cycle, assert return code 0, assert the SKILL.md was restored to a known-good state (compare against `dist-templates/.agents/skills/scout/SKILL.md`). Make GREEN.
- T020 [US2] Implement `test_sg005_failure_triggers_correction_batch`: install fake agent in "fail_frontmatter" mode for the first batch only, run cycle, assert correction directive is written into the second batch's prompt, assert second batch passes SG-005, assert cycle final return is 0 or 1 (documented soft-failure). Make GREEN.

### Checkpoint US2

All five scenarios in `test_full_cycle_e2e.py` GREEN. The tier-4 layer of the pyramid exists and locks the three known seam bugs as regression tests.

---

## Phase 5: User Story 3 (P1) — Multi-Cycle E2E Tests

**Purpose**: Cycle-to-cycle state transfer — the NEXT class of seam bug.

- T021 [US3] Create `tests/pipeline/test_multi_cycle_e2e.py` with file-level docstring, `@pytest.mark.e2e` decorator, and three test stubs matching spec § US3 § Acceptance Scenarios: `test_three_cycles_progress_coverage`, `test_cycle_two_picks_up_where_cycle_one_left_off`, `test_correction_loop_across_cycles`. Each body `assert False`. Verify RED.
- T022 [US3] Implement `test_three_cycles_progress_coverage`: build vault with 30 spec targets across 3 categories, run `research_vault.pipeline.orchestrator.run_cycles(spec, vault)` configured for 3 cycles and `batch_size=5`, assert all three cycles complete, assert `_pipeline/run-report.md` lists all three with non-zero timings, assert coverage progresses monotonically (cycle N's met_count ≤ cycle N+1's met_count for every category).
- T023 [US3] Implement `test_cycle_two_picks_up_where_cycle_one_left_off`: configure fake agent so cycle 1 fills 3 of 10 targets in `cat_a`, assert cycle 2's `research-plan.md` lists the remaining 7 (not the 3 already done), assert no note from cycle 1 is overwritten in cycle 2 (lifecycle.created_at_cycle preserved).
- T024 [US3] Implement `test_correction_loop_across_cycles`: configure fake agent to fail a CG (coverage gate) on cycle 1, assert orchestrator retries with cycle 2 carrying a correction directive, assert cycle 2 passes the CG.

### Checkpoint US3

All three scenarios in `test_multi_cycle_e2e.py` GREEN. The tier-5 layer of the pyramid exists.

---

## Phase 6: User Story 4 (P0) — Hard Build Gate

**Purpose**: Structural enforcement. Without this, US1–US3 are nice-to-have; with this, they are mandatory.

- T025 [US4] Modify `build.sh` to add a "Phase 0 — smoke gate" section before the wheel-build step: `echo "[build] running e2e smoke gate"`, `python -m pytest tests/pipeline/test_full_cycle_e2e.py tests/pipeline/test_multi_cycle_e2e.py -q --tb=short`, `if [[ $? -ne 0 ]]; then echo "[build] e2e smoke gate failed — refusing to build bundle" >&2; exit 1; fi`. Place this AFTER the unit-test sweep (if one exists) and BEFORE `python -m build`. NO `--skip-smoke` flag, NO opt-out env var.
- T026 [US4] Add a `tests/build/test_smoke_gate_enforced.py` regression test: subprocess-invokes `build.sh` against a transient working tree where `pipeline/batch.py` has been deliberately mutated (re-tightening the `BatchResult.to_dict` lower bound to `3`), asserts `build.sh` exits non-zero and no `build/research-vault-*.tar.gz` is produced. Uses `git worktree add` against a tmp dir to avoid touching the developer's tree. Mark with `@pytest.mark.e2e` and `@pytest.mark.slow` so it can be skipped in fast loops but is included in the gate's own run (via a separate marker config — or just lives in the e2e set).
- T027 [US4] Update CHANGELOG entry for 0.2.23 to call out the new gate explicitly so the next contributor reading the release notes knows the build behavior changed.

### Checkpoint US4

`./build.sh` against a clean tree succeeds and produces a tarball. `./build.sh` against a tree with a deliberately-broken e2e scenario aborts with exit 1 and produces no tarball.

---

## Phase 7: User Story 5 (P2) — Documentation

**Purpose**: Convention without enforcement is wishful, but the team needs a shared mental model. P2 because the gate (US4) is the real enforcement; docs help future contributors stay within the pyramid by default.

- T028 [US5] Write `docs/testing-strategy.md` with sections: (a) Six-tier pyramid (unit → schema contract → seam → single-cycle e2e → multi-cycle e2e → smoke gate) with one canonical example test per tier; (b) Decision tree: "I changed X — which tier(s) do I add a test at?" with five concrete change types matching plan.md § Project Structure; (c) How to run each tier (`pytest tests/_helpers`, `pytest -m e2e`, `./build.sh`); (d) How to add a new fake-agent scenario (point at `contracts/fake-agent.contract.md`); (e) Anti-patterns: never monkey-patch `run_cycle_steps`, never invoke real `claude`/`codex` from a test, never use `time.sleep` for synchronisation.
- T029 [P] [US5] Add a "Testing" section to `CLAUDE.md` (or extend the existing one if present) that references `docs/testing-strategy.md` and includes the one-paragraph summary: "1053+ unit tests, 6 tier pyramid, e2e tier gated by build.sh. Run `pytest -m \"not e2e\"` for fast local iteration; `./build.sh` runs the gate."
- T030 [P] [US5] Add a `tests/README.md` (if not present) that points at `docs/testing-strategy.md` and lists the conventional directory roles (`_helpers/`, `pipeline/`, `scripts/`, `cli/`, `agents/`, `fixtures/`).

### Checkpoint US5

A new contributor (or an AI agent reading `CLAUDE.md`) finds the testing strategy in under 60 seconds and can answer "which tier should this test live in?" for at least 4 of 5 representative change types.

---

## Phase 8: Polish & Release

- T031 [P] Update `CHANGELOG.md` with a `## [0.2.23]` entry summarising the feature: new fake-agent module, two e2e test files, hard build gate, documentation. Include explicit mention that production behavior is unchanged.
- T032 [P] Run the full test sweep one final time: `pytest tests/ -q` — assert pass count is ≥ previous baseline (1053) plus the new tests (T007 × 5 + T014 × 1 + T015 × 5 + T021 × 3 + T026 × 1 = 15 new tests minimum). Document the new total in CHANGELOG.
- T033 Build the bundle: `./build.sh`. The smoke gate runs (proves the gate works on a clean tree), the wheel is built, the tarball is produced.
- T034 [P] Smoke-test the bundle: extract to `/tmp/research-vault-0.2.23`, run `./install.sh --non-interactive`, verify it completes cleanly with the new dependency-free fake-agent module untouched (it lives under `tests/`, not in the bundle).

---

## Dependency Graph

```text
T001..T004 (setup) ──────────────────────┐
                                          ▼
T005, T006 (contracts) ──────────────────►T007..T012 (US1)
                                          │
                                          ▼
                                          T013, T014 (vault factory)
                                          │
                                          ▼
                                          T015..T020 (US2 e2e single-cycle)
                                          │           │
                                          ▼           ▼
                                          T021..T024 (US3 e2e multi-cycle)
                                                      │
                                                      ▼
                                                      T025..T027 (US4 build gate)
                                                                  │
                                                                  ▼
                                                                  T028..T030 (US5 docs)
                                                                              │
                                                                              ▼
                                                                              T031..T034 (polish)
```

## Parallelization Hints

- T002, T003, T004 can all run in parallel (different files).
- T005 and T006 (contracts) can run in parallel; both block US1 / US2.
- Within US2, T016–T020 (individual scenarios) can be implemented in parallel by different developers once T013–T015 are GREEN.
- T029 and T030 (docs side-quests) can run alongside T028.
- T031, T032, T034 can run in parallel during polish; T033 (build) depends on T032 (test count check).
