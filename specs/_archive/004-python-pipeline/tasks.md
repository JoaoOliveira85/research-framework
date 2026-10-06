---
description: "Task list for 004 — Python-only pipeline orchestration + verifier wiring"
---

# Tasks: 004 — Python-Only Pipeline Orchestration + Verifier Wiring

**Input**: `specs/_archive/004-python-pipeline/spec.md`
**Prerequisites**: spec.md ✅

**Tests**: TDD required per constitution Principle III. Every task with an
implementation counterpart must have a failing test written first.

**Organization**: Grouped by phase. Phase 3 (cycle_runner) and Phase 4
(verifier) can be worked in parallel once Phase 2 fixtures are in place.

## Format: `[ID] [P?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- File paths are absolute within the `knowledge-vault-generator` repo

---

## Phase 1: Setup

- [ ] T001 Create `specs/_archive/004-python-pipeline/` directory (already done), `tests/pipeline/test_cycle_runner.py` (empty), `tests/pipeline/test_verifier.py` (empty); confirm `pytest --collect-only` still exits 0

---

## Phase 2: Fixtures

- [ ] T002 [P] Create `tests/fixtures/cycle-reports/research-with-notes.json` — research report fixture with `phase: "research"`, `notes_created: ["data_vault/01 - Concepts/Alpha.md", "data_vault/01 - Concepts/Beta.md"]`, `notes_updated: []`, `unresolved_wikilinks: []`, `termination_condition: null`; used by verifier stage tests
- [ ] T003 [P] Create `tests/fixtures/verifier/accept-verdict.json` — `{"verdict": "accept", "violations": [], "suggested_fix": null}`
- [ ] T004 [P] Create `tests/fixtures/verifier/reject-verdict.json` — `{"verdict": "reject", "violations": [{"rule_id": "IX-tier2-missing", "location": "note:data_vault/01 - Concepts/Alpha.md", "message": "No source_urls entry"}], "suggested_fix": "Add at least one source URL"}`
- [ ] T005 [P] Create `tests/fixtures/stubs/verifier` — executable Python stub that reads `--output-file` from argv and writes the contents of `tests/fixtures/verifier/accept-verdict.json` to that path; `chmod +x`; used by verifier tests to avoid real claude CLI dependency
- [ ] T006 [P] Create `tests/fixtures/settings/verifier-enabled.yaml` — minimal settings YAML with `stages: {verifier: {enabled: true, model: sonnet, timeout_s: 30, on_timeout: pending}}`
- [ ] T007 [P] Create `tests/fixtures/settings/verifier-disabled.yaml` — same but `enabled: false`

**Checkpoint**: All fixtures in place; ready to write tests.

---

## Phase 3: `agent_call.py` extension (blocking prerequisite for Phase 4)

The verifier stage needs to read the agent's output as structured JSON. Currently
`agent_call.py` streams the agent output to stdout and has no way to write the result
to a file. This small extension is required before the verifier stage can be
implemented or tested.

### Tests (write first)

- [ ] T008 Write failing test `tests/scripts/test_agent_call.py::test_output_file_flag_writes_result` — assert that when `--output-file /tmp/result.json` is passed, the agent's stdout text is written to that path as a UTF-8 file after the run completes; pass a stub prompt that echoes `{"verdict":"accept"}` to confirm round-trip

### Implementation

- [ ] T009 Extend `scripts/agent_call.py`: add `--output-file PATH` optional argument; after `run()` completes successfully, write the captured agent output text to that path; when flag is absent, behaviour is unchanged (output still goes to process stdout); make T008 pass

---

## Phase 4: `cycle_runner.py` (TDD)

Pure Python translation of `scripts/run_cycle.sh`. Every step calls
`subprocess.run([sys.executable, scripts_dir / "script.py", ...])`.

### Tests (write first — must fail before implementation)

- [ ] T010 Write failing tests `tests/pipeline/test_cycle_runner.py`:
  - `test_steps_execute_in_order` — mock subprocess; assert calls happen in order: vault_metrics → agent_call(scout) → validate_cycle(scout) → agent_call(note_writer) → validate_vault → vault_metrics → validate_cycle(research) → topic_harvest
  - `test_scout_abort_halts_cycle` — mock validate_cycle returning exit 2 on scout report; assert function returns 2 and DFS (note_writer) is never called
  - `test_scout_terminate_skips_dfs` — mock validate_cycle returning exit 1 on scout; assert function returns 1 and DFS is never called
  - `test_research_exit_code_propagated` — mock validate_cycle returning 0 on scout and 1 on research; assert function returns 1
  - `test_rv_python_env_var_set` — assert `RV_PYTHON` in env passed to every subprocess call equals `sys.executable`
  - `test_scout_prompt_placeholders_substituted` — assert rendered scout prompt file replaces `{CYCLE_NUM}` and `{SCOUT_REPORT}` before agent_call is invoked
  - `test_dfs_prompt_placeholders_substituted` — assert rendered DFS prompt replaces `{CYCLE_NUM}`, `{SCOUT_REPORT}`, `{RESEARCH_REPORT}`
  - `test_missing_scout_prompt_returns_abort` — no scout-prompt.md in vault → returns 2 without calling any agent
  - `test_missing_dfs_prompt_returns_abort` — no dfs-prompt.md in vault → returns 2

### Implementation

- [ ] T011 Implement `src/research_vault/pipeline/cycle_runner.py`:
  - `run_cycle_steps(vault_dir: Path, cycle_num: int, budget_cap: float, max_cycles: int, scripts_dir: Path | None = None) -> int`
  - `scripts_dir` defaults to `vault_dir / "scripts"` (matches generated vault layout)
  - Prompt substitution: `str.replace("{CYCLE_NUM}", ...).replace("{SCOUT_REPORT}", ...)` on the prompt file content, write rendered copy to `_pipeline/cycles/cycle-NNN-{scout,dfs}-prompt.rendered.md`
  - All subprocess calls use `[sys.executable, str(scripts_dir / script_name), ...]`; thread `RV_PYTHON=sys.executable` in env
  - Best-effort steps (topic_harvest, topic_propose) catch non-zero exits and WARN; never propagate
  - Post-DFS validation suite (step 4) is report-only; captures exit codes, prints summary, never propagates
  - Step ordering and exit-code logic must match `run_cycle.sh` exactly
  - Make T010 pass

### Wire into orchestrator

- [ ] T012 Modify `src/research_vault/pipeline/orchestrator.py` `run_single_cycle()`:
  - Replace `subprocess.run(["bash", str(script), ...])` with `cycle_runner.run_cycle_steps(vault_dir, cycle_num, budget_cap, max_cycles)`
  - Remove `RV_PYTHON` injection from orchestrator (moves into cycle_runner)
  - Remove `RUN_CYCLE_SH` path constant (no longer called)
  - Existing tests in `tests/pipeline/test_orchestrator.py` must still pass after this change

**Checkpoint**: `pytest tests/pipeline/test_cycle_runner.py tests/pipeline/test_orchestrator.py -v` passes. Running `research-vault generate --spec examples/research.spec.md --output /tmp/rv-004a --skip-gate --dry-run` exits 0 (scaffold only; no cycle run needed for this check).

---

## Phase 5: `verifier.py` (TDD)

Implements the per-note verifier stage: reads research report, calls verifier
per note, stamps frontmatter, writes summary manifest.

### Tests (write first — must fail before implementation)

- [ ] T013 Write failing tests `tests/pipeline/test_verifier.py`:
  - `test_accept_stamps_verified` — mock agent_call returning accept verdict; assert `verifier_status: verified` written to note frontmatter; `verifier_notes` absent
  - `test_reject_stamps_rejected_with_notes` — mock returning reject verdict; assert `verifier_status: rejected` and `verifier_notes` matches violations list
  - `test_timeout_stamps_pending` — mock subprocess timeout (raise `TimeoutExpired`); assert `verifier_status: pending`, WARN printed, function does not raise
  - `test_parse_error_stamps_pending` — mock agent_call writing non-JSON to output file; assert `verifier_status: pending`, WARN printed
  - `test_disabled_skips_all_notes` — `stages.verifier.enabled: false` → zero subprocess calls, no frontmatter changes, no manifest written
  - `test_manifest_written` — two notes in research report; after stage runs, `_pipeline/cycles/cycle-001-verifier.json` exists with `verdicts` list of two entries
  - `test_frontmatter_write_is_atomic` — assert write uses temp-file + rename (check that original is never partially written); simulate by patching `Path.rename`
  - `test_notes_updated_also_verified` — research report has `notes_updated: ["data_vault/01 - Concepts/Gamma.md"]`; assert Gamma.md is included in verifier calls

### Implementation

- [ ] T014 Implement `src/research_vault/pipeline/verifier.py`:
  ```python
  @dataclass
  class VerifierVerdict:
      note_path: str
      status: str           # "verified" | "pending" | "rejected"
      violations: list[dict]
      suggested_fix: str | None

  @dataclass
  class VerifierSummary:
      cycle: int
      verdicts: list[VerifierVerdict]
      timestamp: str

  def run_verifier_stage(
      vault_dir: Path,
      cycle_num: int,
      research_report: dict,
      scripts_dir: Path | None = None,
      settings: dict | None = None,
  ) -> VerifierSummary
  ```
  - Load settings; if `stages.verifier.enabled == false`, return empty summary immediately
  - For each path in `research_report["notes_created"] + research_report.get("notes_updated", [])`:
    - Write a temp prompt file containing the note's full content (read from `vault_dir / note_path`)
    - Call `agent_call.py --vault vault_dir --stage verifier --prompt-file <temp> --output-file <tmp-result>`
    - Parse `<tmp-result>` as JSON → VerifierVerdict
    - Stamp frontmatter atomically (temp file + rename) with `verifier_status` and `verifier_notes`
    - On timeout or parse error: stamp `verifier_status: pending`, log WARN, continue
  - Write `_pipeline/cycles/cycle-NNN-verifier.json` (serialized VerifierSummary)
  - Return VerifierSummary

- [ ] T015 [P] Add `stages.verifier` block to `settings.yaml`:
  ```yaml
  stages:
    verifier:
      enabled: true
      model: sonnet
      timeout_s: 600
      on_timeout: pending    # pending | skip
      output_filename: "cycle-{cycle:03d}-verifier.json"
  ```

- [ ] T016 [P] Mirror `stages.verifier` block in `settings.codex.yaml` with `model: gpt-5.4` and any Codex-specific overrides

### Wire verifier into cycle_runner

- [ ] T017 Extend `src/research_vault/pipeline/cycle_runner.py` to call `verifier.run_verifier_stage()` as Step 3b (after DFS, before Step 4 post-DFS checks):
  - Read research report JSON from disk after Step 3 completes; if file missing, log WARN and skip Step 3b
  - Pass loaded settings to `run_verifier_stage()`
  - Best-effort: any exception from the stage logs WARN and continues
  - Add test `tests/pipeline/test_cycle_runner.py::test_verifier_called_after_dfs`

**Checkpoint**: `pytest tests/pipeline/test_verifier.py tests/pipeline/test_cycle_runner.py -v` passes.

---

## Phase 6: Re-tighten stub gate (TDD)

### Tests (write first)

- [ ] T018 Write failing tests `tests/pipeline/test_stubs.py`:
  - `test_empty_verifier_status_is_stub_when_verifier_enabled` — note with `verifier_status: ""` + settings `stages.verifier.enabled: true` → `scan_stubs()` flags it
  - `test_empty_verifier_status_not_stub_when_verifier_disabled` — same note + `enabled: false` → not flagged (existing neutral behaviour preserved)
  - `test_rejected_verifier_status_is_always_stub` — `verifier_status: rejected` → flagged regardless of enabled setting

### Implementation

- [ ] T019 Modify `src/research_vault/pipeline/stubs.py`:
  - `_FAILING_VERIFIER_STATUSES` is now a function `_failing_verifier_statuses(settings: dict) -> frozenset[str]` (or the set is computed at scan time)
  - When `stages.verifier.enabled == true`: include `""` (absent/empty) in the failing set
  - When `stages.verifier.enabled == false`: exclude `""` (current behaviour, back-compat)
  - `"rejected"` is always in the failing set regardless of setting
  - Make T018 pass

---

## Phase 7: Polish & Integration

- [ ] T020 Write integration test `tests/pipeline/test_cycle_runner.py::test_full_cycle_dry_run` — using the existing `tests/fixtures/stubs/claude` stub binary: configure a fixture vault with a spec, scaffold it, run `cycle_runner.run_cycle_steps()` against it; assert exit code is 0 or 1 (not 2); assert `cycle-001-scout.json` does not exist (stub writes no output file), assert the function handles the missing report gracefully by returning 2 (ABORT) — covers the "agent wrote no report" branch
- [ ] T021 [P] Run `ruff check . --fix` and `black src/ tests/`; confirm both exit 0
- [ ] T022 [P] Update `README.md` line "352 tests and counting" to reflect new count; update any reference to `run_cycle.sh` being the cycle driver
- [ ] T023 Update `CLAUDE.md` "Recent Changes" to add: `004-python-pipeline: Python-native cycle runner (cycle_runner.py) replaces bash wrapper; verifier skill wired as Step 3b; stub gate re-tightened`

---

## Dependencies & Execution Order

- **Phase 1 + 2**: No dependencies — start immediately; all Phase 2 tasks parallel
- **Phase 3** (`agent_call.py` extension, T008–T009): Blocks Phase 5 (verifier.py needs `--output-file`)
- **Phase 4** (`cycle_runner.py`, T010–T012): Can start after Phase 2; independent of Phase 3/5
- **Phase 5** (`verifier.py`, T013–T017): Depends on Phase 3 (agent_call extension)
- **T017** (wire verifier into cycle_runner): Depends on both Phase 4 and Phase 5
- **Phase 6** (stub gate, T018–T019): Depends on Phase 5 being complete
- **Phase 7** (polish, T020–T023): Depends on all prior phases

### Parallel opportunities

After Phase 2 completes, Phase 3 and Phase 4 can run in parallel (different files):
- Phase 3: `scripts/agent_call.py` + `tests/scripts/test_agent_call.py`
- Phase 4: `pipeline/cycle_runner.py` + `tests/pipeline/test_cycle_runner.py` + `pipeline/orchestrator.py`

Within Phase 5, T015 and T016 (settings files) are parallel to T014 (verifier.py impl).

---

## Notes

- `scripts/run_cycle.sh` is NOT modified — it stays on disk unchanged, keeps
  working for any generated vault that calls it directly, and serves as a
  reference implementation during development
- Exit-code contract (0=CONTINUE, 1=TERMINATE, 2=ABORT) must be identical
  between the old bash path and the new Python path — test every branch
- The verifier is best-effort at two levels: (1) individual note failures
  never propagate; (2) the whole stage failure never halts the cycle
- `verifier_status: pending` means "couldn't get a verdict" — it is not
  the same as "verifier ran and found issues"; the note is not flagged as
  wrong, just unverified
