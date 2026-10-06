---

description: "Task list for spec 024 — Testing Infrastructure v2 (Phase 2 + Discipline Layer)"
---

# Tasks: Testing Infrastructure v2 — Phase 2 + Discipline Layer

**Input**: Design documents from `/specs/024-testing-infrastructure-v2/`
**Prerequisites**: plan.md ✅, spec.md ✅ (post-clarify), research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: Tests are **REQUIRED** for this spec. Three reasons:
1. Constitution Principle III (TDD — NON-NEGOTIABLE) applies to every script the project ships, and the new lint guards ARE scripts.
2. **The deliverable IS test infrastructure** — for US1/US4/US5 the "test" and the "implementation" are the same file. For US2/US6 the contract tests are the primary acceptance gate.
3. The spec's six post-clarify acceptance-scenario blocks (US1–US7) mandate test-first verification.

**Organization**: Tasks are grouped by user story per spec.md's `## User Scenarios & Testing` block. The three P1 stories (US1, US2, US3) together comprise the MVP. US6 depends on US2 (fake-agent stages); US7 depends on US6 (replacement coverage). US1/US3/US4/US5 are otherwise independent.

**Terminology note** — "Phase 1/2/3" in this document refers to the **spec-kit phases** below (Setup / Foundational / User-story phases), NOT to the **vault-generation Phase 1/2/3** the constitution references (the constitution's phase numbering targets generated vaults, not spec-kit task lists). No conflict.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1 … US7)
- Include exact file paths in descriptions

## Path Conventions

Single-project structure (per `plan.md` § Project Structure). All paths are repo-root-relative:

- Test infrastructure: `tests/_helpers/`, `tests/spec/`, `tests/integration/`, `tests/build/`
- Scenario data: `tests/_helpers/fake_agent_scenarios/<stage>/<scenario>.json`
- Specs touched by backfills: `specs/_archive/015a-corpus-folder-name/`, `specs/017-vault-quality-fix/`, `specs/018-testing-strategy/`
- Other in-place edits: `CHANGELOG.md`, `build.sh`, `docs/testing-strategy.md`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Directory + marker plumbing the user-story work assumes is already in place.

- [ ] T001 Create directory skeleton: `tests/_helpers/fake_agent_scenarios/verifier/`, `tests/_helpers/fake_agent_scenarios/narrator/`, `tests/_helpers/fake_agent_scenarios/probe_retrieval/`, `tests/spec/`, `tests/integration/` (use `mkdir -p`). `tests/spec/` likely exists already; idempotent.
- [ ] T002 [P] Verify `e2e`, `regression`, `acceptance`, `slow`, and `live_llm` pytest markers are already registered in `pyproject.toml`'s `[tool.pytest.ini_options].markers` (per ADR-0008). If any are missing, add them with one-line descriptions. **No new markers** are introduced by spec 024.
- [ ] T003 [P] Create empty marker files: `tests/spec/__init__.py` and `tests/integration/__init__.py` (only if they don't exist). `tests/_helpers/__init__.py` already exists and is unchanged.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared static data that the user-story work loads. Minimal — this spec is mostly self-contained per user story.

**⚠️ CRITICAL**: No user-story work can begin until this phase is complete.

- [ ] T004 Create `tests/_helpers/llm_dispatch_allowlist.yaml` as an empty YAML list (`[]`) plus a header comment block explaining the schema (per `data-model.md` § Entity 1) and pointing at `specs/018-testing-strategy/contracts/llm-dispatch-guard.contract.md`. Two real entries are added in T009 once the guard test exists; an empty allowlist at T004 lets the guard test land in T006 before the data exists.
- [ ] T005 [P] Spot-check the existing `tests/build/` files referenced by US3 (`tests/build/test_install_wizard_skip_redundant_questions.py` and `tests/build/test_smoke_gate_enforces_contract_tier.py`) — confirm both currently exist on disk and that `.venv/bin/pytest tests/build/ -q` is green. If red, **stop and triage** — flipping `build.sh`'s comment lines while these tests are red ships a broken smoke gate. Document the pre-flight result in PR description.
- [ ] T005a [P] **Record the SC-002 baseline wall-clock**: run `.venv/bin/pytest -m "not e2e" -q --tb=line` and note the final reported wall-clock seconds (expect ~ 240 s per `CLAUDE.md`). Capture as `BASELINE_FAST_LOOP_SECONDS` in the PR description. T055 and T066 compare against this value when verifying SC-002's "< 30 s delta" requirement.

**Checkpoint**: Foundation ready — user-story work can now begin.

---

## Phase 3: User Story 1 — LLM dispatch guard catches subprocess bypasses (Priority: P1) 🎯 MVP

**Goal**: A tier-2 static-analysis test at `tests/_helpers/test_llm_dispatch_guard.py` that scans `src/research_framework/**/*.py` for direct `claude`/`codex` subprocess invocations, tolerates exactly the two-entry allowlist in `tests/_helpers/llm_dispatch_allowlist.yaml`, and reports violations with file + line + remediation message.

**Independent Test** (from spec.md US1): Add a deliberate `subprocess.run(["claude", ...])` to a non-allowlisted module on a throwaway branch. Run `.venv/bin/pytest tests/_helpers/test_llm_dispatch_guard.py`. Confirm it fails with the file + line + remediation message. Remove the violation; rerun; confirm it passes.

### Tests for User Story 1 (write FIRST, ensure they FAIL before implementation)

- [ ] T006 [P] [US1] Write `tests/_helpers/test_llm_dispatch_guard.py` per `specs/018-testing-strategy/contracts/llm-dispatch-guard.contract.md`. Implements `scan_for_violations(scan_root, allowlist) -> list[Violation]` using Python stdlib `ast` (per research.md § Decision 2): walks every `.py` file under `src/research_framework/`, finds `Call` nodes for `subprocess.run` / `subprocess.Popen` whose first positional arg starts with `Str("claude")` or `Str("codex")` (handling both inline list literals AND the `args = ["claude", ...]; subprocess.run(args)` single-assignment pattern). The single test function `test_no_direct_llm_subprocess_in_pipeline_package()` asserts `violations == [], format_report(violations)`. Includes a unit-test-style mini-suite alongside the main test: synthetic Python source fixtures inline-stringed in the test module that exercise the AST walker against (a) clean code → no violations, (b) inline list literal → 1 violation, (c) single-assigned name → 1 violation, (d) `subprocess.run(["echo", "hello"])` → 0 violations (must not false-positive on non-LLM calls).
- [ ] T007 [US1] **First run (RED)**: With `llm_dispatch_allowlist.yaml` still empty from T004, run `.venv/bin/pytest tests/_helpers/test_llm_dispatch_guard.py -q`. Expect **FAIL** because the two real production bypasses (`pipeline/plan_narrator.py` and `pipeline/cycle_runner.py`'s probe-cache retrieval) are not yet allowlisted. Confirm failure output names both files + line numbers.

### Implementation for User Story 1

- [ ] T008 [US1] Open `src/research_framework/pipeline/plan_narrator.py` and find the actual line range of `prepend_narrative`'s `subprocess.run(["claude", …])` call. Open `src/research_framework/pipeline/cycle_runner.py` and find the actual line range of `_run_probe_retrieval_and_cache`'s `claude` invocation. Record both as `[start_line, end_line]` tuples for use in T009.
- [ ] T009 [US1] Populate `tests/_helpers/llm_dispatch_allowlist.yaml` with the two-entry allowlist per `data-model.md` § Entity 1 "At-ship contents":
  - Entry 1: `file: src/research_framework/pipeline/plan_narrator.py`, `function: prepend_narrative`, `line_range` from T008, `stage: research_plan_narrator`, `reason` (multi-line; cites pre-`agent_call.py` history), `cleared_by: 025-simplify-pass/A1`.
  - Entry 2: `file: src/research_framework/pipeline/cycle_runner.py`, `function: _run_probe_retrieval_and_cache`, `line_range` from T008, `stage: probe_retrieval`, `reason`, `cleared_by: 025-simplify-pass/A2`.
- [ ] T010 [US1] **Second run (GREEN)**: Run `.venv/bin/pytest tests/_helpers/test_llm_dispatch_guard.py -q`. Expect **PASS** (allowlist matches reality).
- [ ] T011 [US1] **Negative confirmation**: Add a deliberate `subprocess.run(["claude", "--test"])` to a scratch file (e.g. `src/research_framework/pipeline/_scratch_violation.py`). Re-run the guard. Expect **FAIL** with the scratch file + line + remediation pointer to `agent_call.py`. Delete the scratch file. Re-run. Expect **PASS**. Document both runs in the PR description.
- [ ] T012 [US1] **Boundary check**: Verify the guard's scan root excludes `scripts/agent_call.py` (the canonical dispatch surface), `tests/**`, and `processors/extract.py` (per the 018 contract). A deliberate `subprocess.run(["claude", …])` added to any of those paths MUST NOT trip the guard. Document the scan-root exclusions in `test_llm_dispatch_guard.py` as a docstring at module level.

**Checkpoint**: US1 fully wired. LLM dispatch guard is green with the two-entry allowlist; deliberate violations are caught; non-LLM `subprocess.run` calls are not false-positive. Spec 025 Tier A1/A2 will shrink the allowlist to zero in a follow-on PR.

---

## Phase 4: User Story 2 — fake_agent covers verifier, narrator, probe stages (Priority: P1)

**Goal**: `tests/_helpers/fake_agent.py` honors the v2 contract from `specs/018-testing-strategy/contracts/fake-agent.contract.md` for three previously-unimplemented stages (`verifier`, `narrator` aka `research_plan_narrator`, `probe_retrieval`) with five total scenarios (verifier × 3, narrator × 1, probe_retrieval × 1). Each scenario's response is stored as a deterministic JSON file under `tests/_helpers/fake_agent_scenarios/<stage>/<scenario>.json`. Contract tests in `tests/_helpers/test_fake_agent_contract.py` cover every (stage, scenario) pair.

**Independent Test** (from spec.md US2): Run `.venv/bin/pytest tests/_helpers/test_fake_agent_contract.py -q`. Confirm all three new stages have at least one passing `happy`/`accept` scenario test, verifier additionally has `reject` and `malformed_json`, and the discovery convention test passes (every JSON file under `fake_agent_scenarios/` has a matching test function).

### Tests for User Story 2 (write FIRST — discovery test fails until handlers exist)

- [ ] T013 [P] [US2] Extend `tests/_helpers/test_fake_agent_contract.py` with `test_verifier_accept_emits_canonical_verdict`: invokes the fake-agent CLI with `--stage verifier`, env `FAKE_AGENT_VERIFIER_SCENARIO=accept`, and an `--output-file`; asserts the file is parseable JSON with `verdict == "accept"`, `violations == []`, `suggested_fix is None`. Determinism check: invoke twice, assert byte-identical output (per the 018 contract § Determinism guarantee).
- [ ] T014 [P] [US2] Add `test_verifier_reject_emits_violations`: env `FAKE_AGENT_VERIFIER_SCENARIO=reject`; assert `verdict == "reject"`, `len(violations) >= 1`, each violation has `code` + `message`, `suggested_fix` is a non-empty string.
- [ ] T015 [P] [US2] Add `test_verifier_malformed_json_exercises_parser_tolerance`: env `FAKE_AGENT_VERIFIER_SCENARIO=malformed_json`; assert `--output-file` contains text matching `from research_framework.pipeline.verifier import _extract_json_blob; verdict = _extract_json_blob(content)` and the recovered `verdict.verdict == "reject"` (exercises ADR-0004's relaxed JSON extraction).
- [ ] T016 [P] [US2] Add `test_narrator_happy_emits_short_markdown`: invoke with `--stage research_plan_narrator`, env `FAKE_AGENT_RESEARCH_PLAN_NARRATOR_SCENARIO=happy`; assert stdout is non-empty markdown ≤ 200 words and contains `cycle ` followed by the integer extracted from the prompt's `Cycle N` line. Determinism check: twice → byte-identical.
- [ ] T017 [P] [US2] Add `test_probe_retrieval_happy_emits_array`: invoke with `--stage probe_retrieval`, env `FAKE_AGENT_PROBE_RETRIEVAL_SCENARIO=happy`; assert stdout is a parseable JSON array of objects each with `query`, `answer`, `sources` (list of URLs). Determinism check.
- [ ] T018 [P] [US2] Add `test_unknown_scenario_fails_loud`: invoke with `--stage verifier`, env `FAKE_AGENT_VERIFIER_SCENARIO=does_not_exist`; assert exit code 2 and stderr names the unknown scenario (per 018 contract: unknown scenario → `ValueError` at startup).
- [ ] T019 [US2] Add `test_scenario_discovery_walk`: walks `tests/_helpers/fake_agent_scenarios/<stage>/` for every JSON file; asserts a corresponding test function exists in `test_fake_agent_contract.py` (looks for `test_<stage>_<scenario>_*` patterns). This is the contract-completeness gate per `contracts/fake-agent-v2-stage-extensions.contract.md` § Discovery convention.
- [ ] T020 [US2] **First run (RED)**: Run `.venv/bin/pytest tests/_helpers/test_fake_agent_contract.py -q`. Expect FAIL on T013–T018 (handlers not yet implemented) and FAIL on T019 (no scenario JSONs exist yet). Confirm the failures name each missing piece.

### Implementation for User Story 2

- [ ] T021 [P] [US2] Create `tests/_helpers/fake_agent_scenarios/verifier/accept.json` containing the canonical accept verdict per `data-model.md` § Sub-schema 2a: `{"verdict": "accept", "violations": [], "suggested_fix": null}` (one line, terminating newline).
- [ ] T022 [P] [US2] Create `tests/_helpers/fake_agent_scenarios/verifier/reject.json` containing `{"verdict": "reject", "violations": [{"code": "SYNTHETIC", "message": "fake_agent reject scenario"}], "suggested_fix": "Add tier-2 sources"}` (one line, terminating newline).
- [ ] T023 [P] [US2] Create `tests/_helpers/fake_agent_scenarios/verifier/malformed_json.json` per `data-model.md` § Sub-schema 2d: a markdown text wrapper containing a deliberately invalid JSON code-fence block (`{verdict: "reject", missing_quotes: true}` — note unquoted keys, the violation that ADR-0004's `_extract_json_blob` recovers from).
- [ ] T024 [P] [US2] Create `tests/_helpers/fake_agent_scenarios/narrator/happy.json` containing `{"narrative": "Synthetic focus rationale for cycle {cycle}."}` (the `{cycle}` placeholder is interpolated by the handler — one of two whitelisted placeholders per `data-model.md` § Whitelisted template placeholders).
- [ ] T025 [P] [US2] Create `tests/_helpers/fake_agent_scenarios/probe_retrieval/happy.json` containing a JSON array of ≥ 2 `{query, answer, sources}` shapes per `data-model.md` § Sub-schema 2c. Sources are synthetic URLs (`https://synthetic.test/probe/...`).
- [ ] T026 [US2] Extend `tests/_helpers/fake_agent.py`'s `_SCENARIO_ENV_PER_STAGE` dict with three new entries: `"verifier": "FAKE_AGENT_VERIFIER_SCENARIO"`, `"research_plan_narrator": "FAKE_AGENT_RESEARCH_PLAN_NARRATOR_SCENARIO"`, `"probe_retrieval": "FAKE_AGENT_PROBE_RETRIEVAL_SCENARIO"`. Extend `VALID_SCENARIOS` with `{"accept", "reject", "malformed_json"}` (no need to add `"happy"` — already present). Add a per-stage scenario validator helper `_validate_scenario_for_stage(stage, scenario)` that rejects unknown combinations early with the failure message from T018.
- [ ] T027 [US2] In `tests/_helpers/fake_agent.py`, implement three new handler functions matching the existing `write_scout` / `process_batch` style: `_handle_verifier(args, scenario)`, `_handle_narrator(args, scenario)`, `_handle_probe_retrieval(args, scenario)`. Each loads the matching scenario JSON file via `_load_scenario_payload(stage, scenario) -> str`, interpolates the two whitelisted placeholders (`{cycle}` and `{cycle:03d}`) sourced from `_parse_cycle_from_prompt(prompt_text)`, and writes the payload to `args.output_file` (when provided) or stdout. Atomic write via the existing `_atomic_write` helper. For `malformed_json`, write the file's bytes verbatim with NO interpolation (the file IS the test fixture).
- [ ] T028 [US2] Extend `tests/_helpers/fake_agent.py`'s `main()` dispatch chain: after the existing `scout` / `note_writer` branches, add `verifier`, `research_plan_narrator`, `probe_retrieval` branches that call the T027 handlers. The existing "unknown stage → exit 0" fallback is preserved for stages that 024 does NOT implement (e.g. future `narrator/empty`). **Disjunction note**: unknown-STAGE (a stage 024 doesn't implement) → exit 0 fallback (legacy behaviour for auxiliary stages that pre-024 cycles silently no-op'd). Unknown-SCENARIO for a KNOWN stage (e.g. `verifier` × `does_not_exist`) → exit 2 with stderr per T026's `_validate_scenario_for_stage` (per the 018 contract). These two paths are intentionally different — the first preserves backwards-compat with pre-024 cycle runs; the second is the discipline gate T018 enforces.
- [ ] T029 [US2] Add module-level constant `_LOAD_SCENARIO_PLACEHOLDER_PATTERN = re.compile(r"\{(cycle(?::\d+d)?)\}")` and the `_load_scenario_payload(stage, scenario) -> str` helper that reads the JSON file via `pathlib`, interpolates placeholders via the regex, and returns the result. Co-located with `BATCH_BLOCK_RE` and the other regex constants near the top of the module. Document in a comment block that ONLY `{cycle}` and `{cycle:03d}` are honored — anything else is left literal. **Stage-to-directory aliasing** (resolves the `research_plan_narrator` stage name vs `narrator/` directory layout from `data-model.md` § Entity 2): also add an explicit map `_STAGE_TO_DIR = {"verifier": "verifier", "research_plan_narrator": "narrator", "probe_retrieval": "probe_retrieval"}` with a comment block citing the 018 contract (stage names are authoritative; directory layout follows the data-model.md schema). `_load_scenario_payload` resolves the directory via this map: `path = SCENARIOS_ROOT / _STAGE_TO_DIR[stage] / f"{scenario}.json"`. The map is intentionally explicit — adding a new stage requires touching this constant, which is the right friction.
- [ ] T030 [US2] **Second run (GREEN)**: Run `.venv/bin/pytest tests/_helpers/test_fake_agent_contract.py -q`. Expect all tests PASS, including the T019 discovery walk. If any scenario JSON exists without a matching test, T019 fails — fix by either adding the test or removing the orphan scenario file. The intent is "every scenario file has exactly one corresponding test function".

**Checkpoint**: US2 fully wired. Fake-agent v2 contract honored for the three new stages; contract tests cover all five scenarios + the discovery convention. Production paths for `plan_narrator` and `probe_retrieval` still bypass the fake-agent (spec 025 Tier A1/A2 fixes that); US2 only extends the fake-agent itself.

---

## Phase 5: User Story 3 — Smoke meta-tests restored (Priority: P1)

**Goal**: The two QW-2 meta-tests at `tests/build/test_install_wizard_skip_redundant_questions.py` and `tests/build/test_smoke_gate_enforces_contract_tier.py` run as part of `./build.sh`'s `SMOKE_TESTS` set and pass.

**Independent Test** (from spec.md US3): Run `./build.sh` and grep stdout for both test names appearing in the pytest output. Verify both pass. Revert the uncomment and confirm both are silently skipped (silent-skip is exactly the QW-2 problem the restoration solves).

### Implementation for User Story 3

- [ ] T031 [US3] **Re-confirm T005's pre-flight is still green** (only if hours/days have elapsed since T005 — otherwise this is a no-op and may be skipped). Re-run `.venv/bin/pytest tests/build/ -q` if the working tree has been touched since T005 in ways that could affect these tests. Expect PASS. If RED at this point, **stop and triage** — the uncomment in T032 will ship a broken smoke gate. Repair the failing meta-test FIRST and only then proceed to T032.
- [ ] T032 [US3] Edit `build.sh`: locate the commented-out `SMOKE_TESTS` entries (lines 74-75 at clarify time, per the `# "tests/build/test_install_wizard_skip_redundant_questions.py"` and `# "tests/build/test_smoke_gate_enforces_contract_tier.py"` markers) and remove the `# ` prefix from both lines. Also delete the now-obsolete "MISSING (must be restored)" comment block above them (lines 65-72 at clarify time) — those instructions are satisfied by this very task.
- [ ] T033 [US3] Run `./build.sh` from the worktree root. Expect green smoke gate. Grep stdout for both `test_install_wizard_skip_redundant_questions` AND `test_smoke_gate_enforces_contract_tier` appearing in the pytest test-list output. If either name is missing from the output, the existence pre-flight in `build.sh` (per ADR-0007 + 2026-05-20 triage item #9, `docs/TODO.md#restoration-notes`) caught a stale path → fix the path in T032 and re-run.
- [ ] T034 [US3] **Negative confirmation (per spec.md US3 acceptance scenario 2)**: On a throwaway local branch, temporarily delete a manifest entry that `test_smoke_gate_enforces_contract_tier.py` checks for (e.g. remove one `SMOKE_TESTS` entry that isn't one of the two we just restored). Re-run `./build.sh`. Expect FAIL with `test_smoke_gate_enforces_contract_tier.py` reporting the missing entry. Restore the deleted line. Re-run. Expect green. Document the test in the PR description (verifies the smoke-gate-enforces-itself meta-property). **Do NOT commit** the throwaway test.

**Checkpoint**: US3 fully wired. The smoke gate now tests itself — a missing `SMOKE_TESTS` row or a broken install-wizard skip-redundant-question contract fails `./build.sh` loudly, rather than silently degrading the gate.

---

## Phase 6: User Story 4 — Spec acceptance-coverage lint guard + FR-013 backfill (Priority: P2)

**Goal**: `tests/spec/test_acceptance_coverage_guard.py` enforces ADR-0008's spec acceptance-coverage convention strictly (no allowlist per Q4). Three existing specs that declare G/W/T scenarios but lack a `## Acceptance coverage` section (`015a-corpus-folder-name`, `017-vault-quality-fix`, `018-testing-strategy`) gain the section in the same PR.

**Independent Test** (from spec.md US4): On a throwaway branch, draft a `specs/999-test/spec.md` with at least one G/W/T scenario but no `## Acceptance coverage` section. Run `.venv/bin/pytest tests/spec/test_acceptance_coverage_guard.py`. Confirm it fails with the file path. Add the section; confirm it passes. Then on the 024 ship branch, run the guard against every existing spec and confirm zero failures (no allowlist needed).

### Tests for User Story 4 (write FIRST, ensure they FAIL before backfill)

- [ ] T035 [P] [US4] Write `tests/spec/test_acceptance_coverage_guard.py` per `contracts/acceptance-coverage-guard.contract.md`. Three helpers: `discover_specs_with_gwt(specs_dir) -> list[Path]` (regex over each `spec.md` for `**Given** … **When** … **Then**` shapes — both numbered list and bare-bullet variants per the contract), `validate_acceptance_coverage(spec_path) -> list[Problem]` (asserts the section exists with `^## Acceptance coverage\s*$`, contains a table with `US<N>` row identifiers, each row's evidence cell matches one of the four allowed forms in `data-model.md` § Entity 3), and `format_failures(failures) -> str` (per the contract's § Failure report format example). Single test function `test_every_spec_with_gwt_has_acceptance_coverage()` asserts `failures == []`. Includes a unit-test mini-suite with synthetic spec fixtures inline-stringed in the test module: (a) spec with G/W/T + complete coverage table → 0 problems, (b) spec with G/W/T + no section → 1 problem ("missing section"), (c) spec with G/W/T + table missing a US row → 1 problem ("US<N> declared but absent from table"), (d) spec with G/W/T + empty cell → 1 problem ("evidence cell empty"), (e) spec with no G/W/T → not scanned (out of scope).
- [ ] T036 [US4] **First run (RED)**: Run `.venv/bin/pytest tests/spec/test_acceptance_coverage_guard.py -q`. Expect **FAIL** for three real specs: `015a-corpus-folder-name`, `017-vault-quality-fix`, `018-testing-strategy` (no `## Acceptance coverage` section). Failure output names all three. Confirm 022, 024, 025 are NOT in the failure list (they already have populated sections).

### FR-013 backfill (per research.md § Decision 3 + data-model.md § Entity 5)

- [ ] T037 [P] [US4] Backfill `specs/_archive/015a-corpus-folder-name/spec.md`: add a `## Acceptance coverage` section at the end of the file (after the existing primary content) with a row per user story. Per research.md § Decision 3, point rows at `tests/scripts/test_validate_vault.py` and `tests/spec/test_validator.py` where the corpus-folder-name contract is exercised. Use the row schema from `data-model.md` § Entity 3.
- [ ] T038 [P] [US4] Backfill `specs/017-vault-quality-fix/spec.md`: add a `## Acceptance coverage` section. Per research.md § Decision 3, map: US1 (preflight) → `tests/scripts/test_preflight_sources.py`, US2 (quality report) → `tests/scripts/test_quality_report.py`, US3 (research plan) → `tests/pipeline/test_research_plan_*.py`. For user stories where coverage spans multiple files, use the "multiple test paths" form per `data-model.md` § Entity 3. For genuinely-historical user stories without a dedicated test, use `_(historical — see CHANGELOG.md [0.2.27])_` or the relevant version block.
- [ ] T039 [P] [US4] Backfill `specs/018-testing-strategy/spec.md`: add a `## Acceptance coverage` section. Each US row references the corresponding 018 contract file under `specs/018-testing-strategy/contracts/` AND the contract test under `tests/_helpers/test_fake_agent_contract.py` / `tests/_helpers/test_vault_factory_contract.py`. The LLM-dispatch row points at `tests/_helpers/test_llm_dispatch_guard.py` (created by THIS spec in T006) — a forward reference that becomes valid in the same ship PR.
- [ ] T040 [US4] **Second run (GREEN)**: Run `.venv/bin/pytest tests/spec/test_acceptance_coverage_guard.py -q`. Expect **PASS** for the in-scope specs: 015a/017/018 (backfilled by T037–T039), 022/025 (already populated by sibling drafts), 024 itself (dogfood), plus any other future in-scope spec. Specs without G/W/T scenarios are out of scope and silently skipped per the contract. US4 acceptance scenario 5 (spec 022 passes the guard) is directly verified here.
- [ ] T041 [US4] **Dogfood verification (SC-009)**: Run the guard scoped to spec 024 itself: `.venv/bin/pytest tests/spec/test_acceptance_coverage_guard.py -q -k "024"` (or otherwise filter to 024). Expect PASS — the dogfood `## Acceptance coverage` section in `specs/024-testing-infrastructure-v2/spec.md` (with `_(deferred to tasks.md ...)_` rows) is a valid evidence form per the contract.

**Checkpoint**: US4 fully wired. The lint guard is green strict-at-launch; three existing specs are backfilled; spec 024 itself dogfoods the convention. No allowlist exists; no allowlist is needed.

---

## Phase 7: User Story 5 — CHANGELOG regression-link lint guard + FR-014 backfill (Priority: P2)

**Goal**: `tests/spec/test_changelog_regression_links.py` enforces ADR-0008's CHANGELOG regression-discipline convention strictly (no allowlist per Q5). Every `### Fixed` bullet under every released-version block in `CHANGELOG.md` gains an annotation (`(test: …)`, `(regression test: …)`, or `(no test: <rationale>)`) in the same PR.

**Independent Test** (from spec.md US5): Add a `### Fixed` line to a future-version block without an annotation. Run the guard. Confirm FAIL with version + line number. Add `(test: …)`. Confirm PASS. On the 024 ship branch, run the guard against the full CHANGELOG and confirm zero failures.

### Tests for User Story 5 (write FIRST, ensure they FAIL before backfill)

- [ ] T042 [P] [US5] Write `tests/spec/test_changelog_regression_links.py` per `contracts/changelog-regression-guard.contract.md`. Implements a state-machine parser `parse_changelog_fixed_bullets(path) -> list[Bullet]` (per research.md § Decision 2: tracks released-vs-Unreleased blocks, identifies `### Fixed` sub-blocks, extracts each leading bullet line) and `validate_annotation(bullet) -> list[Problem]` (matches one of the three regex shapes from `data-model.md` § Entity 4; checks path existence for `(test: …)` and `(regression test: …)`; requires non-empty rationale string for `(no test: …)`). Single test function `test_every_changelog_fixed_bullet_has_test_annotation()` asserts `failures == []`. Includes a unit-test mini-suite with synthetic CHANGELOG fixtures inline-stringed in the test module covering: (a) `[Unreleased]` block with bare bullets → all skipped, (b) released block with `(test: existing-path)` → passes, (c) released block with `(test: missing-path)` → fails "path does not exist", (d) released block with bare bullet → fails "missing annotation", (e) released block with `(no test: )` (empty rationale) → fails "rationale required", (f) released block with two annotations on one bullet → fails "exactly one annotation required", (g) released block with multi-line bullet (annotation on leading line, detail on continuation line) → passes (continuation lines not parsed).
- [ ] T043 [US5] **First run (RED)**: Run `.venv/bin/pytest tests/spec/test_changelog_regression_links.py -q`. Expect FAIL with ~30–50 bullets across the 15 `### Fixed` sections enumerated in `data-model.md` § Entity 6. Capture the failure output to a scratch file (e.g. `/tmp/024-changelog-backfill.txt`) — it's the work-list for T044–T048.

### FR-014 backfill (per research.md § Decision 4 + data-model.md § Entity 6)

The 15 `### Fixed` sections (line numbers from `data-model.md` § Entity 6) are bundled into ~5 backfill tasks by version range, both for reviewability and so a partial ship doesn't risk a guard that's red on bullets nobody owns.

- [ ] T044 [P] [US5] Backfill `CHANGELOG.md` `### Fixed` sections in the **0.2.30–0.2.33** range (lines 191, 212, 599, 752 at clarify time). For each bullet, follow the priority ladder in research.md § Decision 4: (1) find sibling test commit via `git log --follow` → `(test: <path>::<name>)`, (2) test added later → `(regression test: …)`, (3) genuinely untested → `(no test: <one-line rationale>)`. Where multiple bullets share a test, each cites it independently. Edit in place. **Cross-story optimisation**: if US6 is already complete at the time you reach T044 (i.e. T054 is green), prefer pointing `(test: …)` / `(regression test: …)` at the new `tests/integration/test_cycle_e2e.py::test_cycle_<scenario>_*` paths directly where applicable, instead of the about-to-be-deleted `tests/pipeline/test_e2e_synthetic_vault.py`. This saves the T058 re-pointer round-trip for those bullets. If US6 is NOT yet complete, point at the existing `test_e2e_synthetic_vault.py` paths; T058 re-points them after US7's deletion.
- [ ] T045 [P] [US5] Backfill `### Fixed` sections in the **0.2.27–0.2.29** range (lines 871, 890, 960). Same procedure as T044.
- [ ] T046 [P] [US5] Backfill `### Fixed` sections in the **0.2.20–0.2.26** range (lines 1069, 1107, 1194, 1237). Same procedure.
- [ ] T047 [P] [US5] Backfill `### Fixed` sections in the **0.2.10–0.2.19** range (lines 1361, 1414, 1462). Same procedure. Where a bullet predates the project's testing discipline and the original test cannot be located, `(no test: pre-discipline; verified by manual smoke run at the time)` is acceptable.
- [ ] T048 [P] [US5] Backfill the oldest `### Fixed` section (line 1543) plus any sections T044–T047 missed (the line numbers in `data-model.md` § Entity 6 are a snapshot; backfill MUST run against the live file). After this task, every released-version `### Fixed` bullet has exactly one annotation.
- [ ] T049 [US5] **Second run (GREEN)**: Run `.venv/bin/pytest tests/spec/test_changelog_regression_links.py -q`. Expect PASS. If FAIL, the output names the remaining bullets — fix and re-run.

### FR-015 cross-check (synthetic-vault re-pointers; deferred to US7 completion)

- [ ] T050 [US5] **FR-015 sentinel**: Grep `CHANGELOG.md` for any annotation containing `tests/pipeline/test_e2e_synthetic_vault.py`. Document the matched bullets in the PR description (or write them to a scratch file). These bullets will need re-pointing once US7 deletes the file — the actual re-pointing happens in T058 (US7) once US6's tier-5 scenarios are in place to be the target. T050 is purely a discovery step; no edits yet.

**Checkpoint**: US5 fully wired. The lint guard is green strict-at-launch; every released-version `### Fixed` bullet has an annotation; `[Unreleased]` is skipped per the contract; the synthetic-vault re-pointer list is staged for US7.

---

## Phase 8: User Story 6 — Tier-5 cycle e2e wires three scout scenarios (Priority: P2)

**Goal**: `tests/integration/test_cycle_e2e.py` covers three previously-uncovered cycle paths (`oos_topic`, `partial_yield`, `verifier_reject`) end-to-end, using `vault_factory.build_minimal_vault` for fixture construction and the new fake-agent stages from US2 for stage routing.

**Independent Test** (from spec.md US6): For each scenario, snapshot the cycle output and assert the expected JSON shape. `oos_topic` → verifier rejection in `cycle-NNN-quality-report.json`. `partial_yield` → SG-002 diversity-gate warning. `verifier_reject` → note moved to `_pipeline/rejected/`. Each scenario MUST be deselected by `pytest -m "not e2e"` (fast loop unaffected).

**Dependency**: US6 requires US2 complete (T030 green) — the `verifier_reject` and `partial_yield` scenarios consume the new fake-agent stages.

### Tests for User Story 6 (each test IS the contract; no separate red-then-green dance)

- [ ] T051 [P] [US6] Add `test_cycle_oos_topic_rejected_by_verifier(tmp_path, monkeypatch)` to `tests/integration/test_cycle_e2e.py` per `data-model.md` § Entity 8. Uses `vault_factory.build_minimal_vault(tmp_path, …)`; sets `FAKE_AGENT_SCOUT_SCENARIO=oos_topic` AND `FAKE_AGENT_VERIFIER_SCENARIO=reject`; runs one cycle via the existing in-process cycle-runner entry; asserts the OOS topic appears in `vault/_pipeline/cycles/cycle-001-quality-report.json` as a verifier rejection. Decorated with `@pytest.mark.e2e`.
- [ ] T052 [P] [US6] Add `test_cycle_partial_yield_trips_diversity_gate(tmp_path, monkeypatch)`. Uses `FAKE_AGENT_NOTE_WRITER_SCENARIO=partial_yield`; runs cycle; asserts `cycle-001-quality-report.json` shows a SG-002 warning entry (per the existing `partial_yield` scenario in `fake_agent.py` already shipped at v1 — this task adds the e2e consumer, not a new scenario). `@pytest.mark.e2e`.
- [ ] T053 [P] [US6] Add `test_cycle_verifier_reject_moves_note_to_rejected(tmp_path, monkeypatch)`. Uses `FAKE_AGENT_VERIFIER_SCENARIO=reject` against an otherwise happy-path cycle; asserts the verifier-rejected note ends up under `vault/_pipeline/rejected/` (or the path the production verifier-reject branch writes to — confirm via reading `pipeline/verifier.py` and `pipeline/cycle_runner.py` Step 3b at impl time). `@pytest.mark.e2e`.
- [ ] T054 [US6] Run the new scenarios: `.venv/bin/pytest tests/integration/test_cycle_e2e.py -q -m e2e -k "oos_topic or partial_yield or verifier_reject"`. Expect 3 PASSED. If a scenario fails, triage — likely a fake-agent contract drift (re-read 018 § Scenarios by stage) or a stale assertion on the production cycle output shape. Do NOT mask the failure with a skip marker.
- [ ] T055 [US6] **Fast-loop isolation check (per US6 spec.md acceptance scenario 4)**: Run `.venv/bin/pytest -m "not e2e" -q` and confirm none of the three new test names appear in the collection output. Confirm fast-loop runtime delta from the SC-002 baseline (~ 240 s) is < 30 s.

**Checkpoint**: US6 fully wired. The tier-5 e2e covers three previously-untested cycle paths using the fake-agent stages from US2. Replacement coverage for US7's deletion is now in place.

---

## Phase 9: User Story 7 — Delete `tests/pipeline/test_e2e_synthetic_vault.py` outright (Priority: P3)

**Goal**: The legacy bespoke-mock test file is removed from the tree. Historical coverage flows through US6's three tier-5 scenarios. CHANGELOG annotations that previously pointed at the deleted file are re-pointed at the equivalent US6 scenarios (FR-015).

**Independent Test** (from spec.md US7): `ls tests/pipeline/test_e2e_synthetic_vault.py` returns no such file. `pytest -m "not e2e" --collect-only` reports no orphan imports. The US5 guard (T049) re-run against the post-T058 CHANGELOG state passes — no annotation points at the deleted file.

**Dependency**: US7 requires US6 complete (T054 green) — the replacement coverage MUST exist before the deletion lands.

### Implementation for User Story 7

- [ ] T056 [US7] **Replacement-coverage gate**: Re-run `.venv/bin/pytest -m e2e -q -k "oos_topic or partial_yield or verifier_reject"`. All three MUST be green. If any is red, **stop** — deleting `test_e2e_synthetic_vault.py` drops coverage that the spec promised to preserve.
- [ ] T057 [US7] Delete the file: `rm tests/pipeline/test_e2e_synthetic_vault.py`. Run `.venv/bin/pytest -m "not e2e" --collect-only -q 2>&1 | grep -i error`. Expect no errors. Run `.venv/bin/pytest -m "not e2e" -q --tb=line`. Expect green at the same count as the post-US1-through-US6 baseline (the deleted file contributed N tests — confirm the new total = previous total - N where N is the pre-deletion count of that file's tests).
- [ ] T058 [US7] **FR-015 re-pointer pass**: Using the discovery list from T050, edit each affected `CHANGELOG.md` bullet to re-point the `(test: …)` or `(regression test: …)` annotation from `tests/pipeline/test_e2e_synthetic_vault.py::<old_name>` to the equivalent `tests/integration/test_cycle_e2e.py::test_cycle_<oos_topic|partial_yield|verifier_reject>_*`. The mapping is judgmental — pick the US6 scenario that most closely covers the deleted test's scenario. Where no US6 scenario covers it, downgrade the annotation to `(no test: covered indirectly by 022 quality-harness regressions)` with a CHANGELOG note. Document each remap in the PR description.
- [ ] T059 [US7] Re-run the US5 guard: `.venv/bin/pytest tests/spec/test_changelog_regression_links.py -q`. Expect PASS — no annotation references the deleted path. This is SC-012's enforcement point; if FAIL, the path-existence check inside the guard correctly caught a missed remap → fix and re-run.

**Checkpoint**: US7 fully wired. The legacy file is gone; orphan imports are absent; CHANGELOG annotations are coherent with the post-deletion tree.

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: Doc-sync, checklist verification, ship-PR-ready hygiene. None of these change behaviour; all are required for ship-PR per the per-stage doc-update checklist in `CLAUDE.md`.

- [ ] T060 [P] Edit `docs/testing-strategy.md` line 38 (the `refactor/testing-strategy-phase2` reference): rewrite to `024-testing-infrastructure-v2` per FR-011. Confirm the surrounding paragraph still reads naturally.
- [ ] T061 [P] Tick off every checkbox in `docs/testing-strategy.md` § Phase 2 implementation checklist (lines 513-535 at clarify time) — eight checkboxes corresponding to QW-2, fake_agent verifier, fake_agent narrator+probe, contract tests, tier-5 cycle e2e, LLM dispatch guard, retire synthetic_vault, spec acceptance coverage guard, CHANGELOG regression-link guard, doc sync. Mark each `[x]` and append `(landed in 024)` where it adds clarity.
- [ ] T062 Add a `[Unreleased]` `### Added` entry in `CHANGELOG.md` describing spec 024's deliverables: "LLM dispatch guard with two-entry allowlist (clears in spec 025 Tier A); fake-agent v2 stages (verifier accept/reject/malformed_json, narrator happy, probe_retrieval happy) with contract tests; smoke meta-tests restored to `./build.sh`; spec acceptance-coverage lint guard (strict at launch); CHANGELOG regression-link lint guard (strict at launch); tier-5 cycle e2e scenarios (oos_topic / partial_yield / verifier_reject); deleted `tests/pipeline/test_e2e_synthetic_vault.py` (replaced by tier-5 e2e)." Add a corresponding `### Changed` entry noting the backfilled spec acceptance-coverage sections (015a, 017, 018) and the CHANGELOG annotation backfill. Each `[Unreleased]` bullet does NOT need a `(test: …)` annotation (the US5 guard skips Unreleased) — but adding them now anticipates the next release and prevents future scrambling. Annotate where convenient.
- [ ] T063 Update spec 024's status header in `specs/024-testing-infrastructure-v2/spec.md`: change from `**Status**: Draft (post-`/speckit.clarify` 2026-05-21, pre-`/speckit.plan`)` to `**Status**: SHIPPED <ship-version>` per the ship-stage entry in CLAUDE.md's doc-update checklist. Bump on the ship commit, not earlier.
- [ ] T064 Sync `docs/ROADMAP.md`: flip queue entry 1a from `[~]` to `[x]`; move to "Completed (recent)" block with `(0.<minor>.<patch>, <date>)` reference; update the strategic-sequencing block if 024 shipping changes the queue order (it shouldn't — 022 is still next). Also flip the corresponding specs-table row 024 status to `**SHIPPED <ship-version>**`. **Fix stale path**: row 024 currently references `tests/test_e2e_synthetic_vault.py` (missing the `pipeline/` segment) — correct it to `tests/pipeline/test_e2e_synthetic_vault.py` in the same edit. Delete any TODO.md entries that 024 resolved (per the ship-stage checklist).
- [ ] T065 Update `CLAUDE.md` "Recent Changes" section: prepend a `0.<minor>.<patch>` entry summarising 024's deliverables. Prune the "Recent Changes" section to the last 3–5 ship cycles per the documentation-discipline rule. If 024 changes "Active Technologies", "Project Structure", or "Important context locations" in CLAUDE.md, update those sections too — 024 doesn't change any of those (it's pure test infrastructure), so this task may be a no-op beyond the Recent Changes prepend.
- [ ] T066 **Final ship-PR checklist verification** (per quickstart.md § 8). Run, in order, with all expected results green:
  - `.venv/bin/pytest` (full sweep) — SC-001
  - `.venv/bin/pytest -m "not e2e"` (fast loop; record wall-clock to confirm < 30 s delta vs pre-024 baseline) — SC-002
  - `./build.sh` (smoke gate green, both QW-2 tests in output) — SC-003
  - Inspect `tests/_helpers/llm_dispatch_allowlist.yaml` (exactly 2 entries) — SC-004
  - `.venv/bin/pytest tests/spec/test_acceptance_coverage_guard.py -q` (green; no allowlist) — SC-005 + SC-010
  - `.venv/bin/pytest tests/spec/test_changelog_regression_links.py -q` (green; no allowlist) — SC-006 + SC-011 + SC-012
  - `ls tests/pipeline/test_e2e_synthetic_vault.py` (no such file) — SC-007
  - Visual inspection of `docs/testing-strategy.md` § Phase 2 checklist (every box ticked) — SC-008
  - `.venv/bin/pytest tests/spec/test_acceptance_coverage_guard.py -q -k "024"` (spec 024 dogfoods) — SC-009

  Document each result in the PR description. Any red light here is a ship blocker.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately.
- **Foundational (Phase 2)**: Depends on Setup. Blocks all user-story phases.
- **User-story phases (Phase 3+)**: All depend on Foundational. Story-internal dependencies are listed below.
- **Polish (Phase 10)**: Depends on all user-story phases.

### Inter-story dependencies

- **US1, US3, US4, US5** — fully independent of each other and of US2. Can be implemented in any order or in parallel.
- **US2** — fully independent. Can be implemented in parallel with US1/US3/US4/US5.
- **US6** — **depends on US2** (the new fake-agent stages). Must be completed AFTER T030 (US2 contract tests green).
- **US7** — **depends on US6** (replacement coverage). Must be completed AFTER T054 (US6 scenarios green).

### Within each user story

- The test task (US1 T006, US2 T013–T019, US4 T035, US5 T042) MUST be written before the implementation tasks.
- The "first run (RED)" task (T007, T020, T036, T043) confirms tests fail meaningfully before any implementation. **Do not skip the RED run** — it's the discipline gate Principle III mandates.
- Implementation tasks within a story may be parallel where marked `[P]` (different files, no internal dependencies).
- The "second run (GREEN)" task (T010, T030, T040, T049) confirms tests pass after implementation. Cannot be parallelized with anything in the same story.

### Parallel opportunities

- **Phase 1**: T002, T003 are `[P]` — can run in parallel with each other (T001 must complete first; it creates the parent directory tree).
- **Phase 3 (US1)**: only T006 is `[P]` (different file from anything else). T007 → T008 → T009 → T010 → T011 → T012 is sequential.
- **Phase 4 (US2)**: T013–T018 are all `[P]` (different test functions added to the same file, but per the spec-kit convention each test function is its own task — Python's atomic-file-write model handles concurrent contributions to a single file's appended functions cleanly via `git` line-level merging). T021–T025 are `[P]` (different scenario JSON files). T026–T029 are sequential (same file: `fake_agent.py`). T030 is sequential.
- **Phase 6 (US4)**: T037, T038, T039 are `[P]` (three different spec files). T036 must come before all three; T040 must come after all three.
- **Phase 7 (US5)**: T044, T045, T046, T047, T048 are `[P]` (same file `CHANGELOG.md`, but five disjoint version-range edits — git's hunk-level merge handles concurrent edits cleanly when they don't overlap line ranges). If unsure of the line-range partitioning, run them sequentially.
- **Phase 8 (US6)**: T051, T052, T053 are `[P]` (different test functions; same file, but as in Phase 4, atomic appends compose cleanly).
- **Phase 10 (Polish)**: T060, T061 are `[P]` (different files / different docs). T062, T063, T064, T065 each touch one file each — `[P]` if scheduled carefully. T066 is sequential (the final verification gate).

---

## Parallel Example: US2 Tests + Scenario Files

```bash
# Phase 4 setup phase — six parallel tests + five parallel scenario JSONs:

# Tests (all add new functions to test_fake_agent_contract.py; spec-kit treats them as parallel
# because each task adds an independent test function that doesn't share state with the others):
Task: "Add test_verifier_accept_emits_canonical_verdict to test_fake_agent_contract.py"   # T013
Task: "Add test_verifier_reject_emits_violations to test_fake_agent_contract.py"          # T014
Task: "Add test_verifier_malformed_json_exercises_parser_tolerance"                       # T015
Task: "Add test_narrator_happy_emits_short_markdown"                                       # T016
Task: "Add test_probe_retrieval_happy_emits_array"                                         # T017
Task: "Add test_unknown_scenario_fails_loud"                                               # T018

# Scenario JSONs (five different files; truly parallel):
Task: "Create fake_agent_scenarios/verifier/accept.json"           # T021
Task: "Create fake_agent_scenarios/verifier/reject.json"           # T022
Task: "Create fake_agent_scenarios/verifier/malformed_json.json"   # T023
Task: "Create fake_agent_scenarios/narrator/happy.json"            # T024
Task: "Create fake_agent_scenarios/probe_retrieval/happy.json"     # T025

# Then SEQUENTIAL (same file: fake_agent.py):
Task: "T026 — Extend _SCENARIO_ENV_PER_STAGE + VALID_SCENARIOS"
Task: "T027 — Implement three new stage handlers"
Task: "T028 — Wire main() dispatch chain"
Task: "T029 — Add _load_scenario_payload + placeholder regex"
Task: "T030 — GREEN run of fake-agent contract suite"
```

---

## Implementation Strategy

### MVP first (US1 + US2 + US3 — all P1)

1. Complete Phase 1 (Setup) and Phase 2 (Foundational).
2. Pick **one** P1 story to ship first as the "smallest demo":
   - **Easiest first**: US3 (smoke meta-tests) — 4 tasks total, no new test files to write, just an uncomment + verify.
   - **Highest leverage first**: US1 (LLM dispatch guard) — directly enforces Principle IV and is the prerequisite for spec 025's allowlist-shrink.
   - **Foundation for everything else**: US2 (fake-agent stages) — unblocks US6, which unblocks US7.
3. Verify the chosen story passes its independent test.
4. Repeat for the remaining two P1 stories in any order.
5. **MVP demo point**: After US1 + US2 + US3, the project has the LLM dispatch guard live, the fake-agent stage extensions ready for consumers, and the smoke gate testing itself. Ship-ready in principle, though US4/US5/US6/US7 ship in the same PR.

### Incremental delivery (recommended)

The spec ships as a single PR, but internally implementation proceeds in this order:

1. **Wave 1 (Foundation + US3, US1)** — sequential within wave but US3 + US1 may overlap if two contributors are available. Lowest risk, fastest wins.
2. **Wave 2 (US2)** — once Wave 1 is green. Unblocks Wave 3.
3. **Wave 3 (US4, US5, US6)** — US4 + US5 fully parallel (different file scopes). US6 starts after T030 (US2 green). US4 + US5 + US6 can otherwise overlap.
4. **Wave 4 (US7)** — after T054 (US6 green).
5. **Wave 5 (Polish)** — once all user stories are green and SC checklist passes.

### Parallel-team strategy (if multiple contributors)

- **Contributor A**: US1 → US4 (lint-guard track)
- **Contributor B**: US2 → US6 → US7 (fake-agent + e2e track)
- **Contributor C**: US3 → US5 (CHANGELOG backfill track)
- All converge on **Polish (Phase 10)**, which one contributor owns end-to-end to avoid CHANGELOG merge conflicts.

---

## Notes

- `[P]` tasks = different files OR independent append-only additions to the same file. Spec-kit treats clean `git` merges of parallel function additions as parallel-safe; if unsure for a specific task, sequence it.
- `[Story]` label maps task to specific user story for traceability and for the FR-013 backfill rows that 015a/017/018 will gain in T037–T039.
- Each user story is independently completable + testable per Principle III.
- **Verify tests fail before implementing** — the explicit RED-run tasks (T007, T020, T036, T043) make this discipline auditable in the PR diff.
- Commit at every meaningful checkpoint (end of each user story is the natural unit). Spec 024's eventual ship PR may combine the per-story commits or keep them — that's a `/speckit.implement`-time decision.
- **Avoid**: vague tasks (every task names a file path + exact action), cross-story dependencies that break independence (only US6→US2 and US7→US6 are real dependencies; everything else is independent), modifying production code under `src/research_framework/` (spec 025 owns that — 024 ONLY adds test infrastructure plus the four in-place doc edits in `build.sh`, `CHANGELOG.md`, `docs/testing-strategy.md`, and the three spec backfills).

---

## Format validation

All tasks above follow the required format: `- [ ] T<ID> [P?] [USx?] <Description with exact file path>`. Setup phase tasks (T001–T003) and Foundational phase tasks (T004–T005, T005a) carry NO `[USx]` label; user-story phase tasks (T006–T059) carry their owning `[USx]` label; Polish phase tasks (T060–T066) carry NO `[USx]` label.

**Total task count**: 67 (66 numbered T001–T066 + 1 inserted T005a after the `/speckit.analyze` pass; see [Post-analyze patch log](#post-analyze-patch-log) below).
**Per-story count**: US1 = 7, US2 = 18, US3 = 4, US4 = 7, US5 = 9, US6 = 5, US7 = 4. Setup + Foundational + Polish = 13 (was 12 before T005a).
**Parallel opportunities flagged**: 23 tasks carry `[P]` (T005a added one).
**MVP scope**: T001–T034 inclusive of T005a (Setup + Foundational + US1 + US2 + US3 = three P1 stories, 35 tasks).

---

## Post-analyze patch log

The `/speckit.analyze` pass (2026-05-21) surfaced 2 critical and 5 should-fix findings. All 7 were addressed in-place:

| Finding | Severity | Task(s) edited | Resolution |
|---|---|---|---|
| C1 — narrator stage-name vs scenario-dir mismatch | 🔴 | T029 | Added `_STAGE_TO_DIR` map spec to the task description; explicit alias from `research_plan_narrator` → `narrator/` directory. |
| C2 — ROADMAP stale path reference (row 024) | 🔴 | T064 | Added sub-instruction to correct `tests/test_e2e_synthetic_vault.py` → `tests/pipeline/test_e2e_synthetic_vault.py` in the same edit. |
| S1 — T005/T031 duplicate pre-flight | 🟡 | T031 | Reframed as "re-confirm if hours/days elapsed since T005, otherwise skip". |
| S2 — SC-002 baseline wall-clock not captured | 🟡 | T005a (NEW) | Added explicit task to record `BASELINE_FAST_LOOP_SECONDS` for T055/T066 to reference. |
| S3 — T040 GREEN-run could enumerate expected-pass specs | 🟡 | T040 | Now names 015a/017/018 (backfilled), 022/024/025 (already populated), and verifies US4 acceptance scenario 5. |
| S4 — T044–T048 backfill order vs US6 availability | 🟡 | T044 | Added cross-story optimisation note for the US6-first ordering case. |
| S5 — T028 unknown-stage vs unknown-scenario semantic disjunction | 🟡 | T028 | Clarification block: unknown-STAGE → exit 0 (legacy compat); unknown-SCENARIO for known stage → exit 2 (discipline gate per T026/T018). |

No findings rose to ⚠️ (gate-blocking) or required re-running `/speckit.clarify`. The 4 🟢 watch items from the analyze report (W1–W4 in the analyze findings — `VALID_SCENARIOS` flat-set extension to per-stage, T019 discovery-walk safety, spec 025 dir name verification, pre-existing `oos_topic`/`partial_yield` scenarios in `fake_agent.py`) required no task changes; they are informational for the implementer.
