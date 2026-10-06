# Tasks: The run receipt

**Spec**: [`spec.md`](spec.md) · **Status of the spec**: `planned`. Task
boxes are live: a `- [ ]` means genuinely not done. Order matters — T001
and T002 are what every later task reads.

## Phase 1: The directory and the sidecar

- [x] T001 Allocate `_pipeline/runs/<run_id>/` in `run_full` and derive it
      from the state file's `run_id` everywhere else (FR-001, FR-002,
      FR-004). Write `run.json` on every phase close as a pure function of
      the state file plus what is on disk (FR-006, FR-007), with its schema
      at `tests/contracts/run-receipt-1.0.schema.json` wired the way #326
      wired the state schema. Implementation in
      `src/research_framework/pipeline/runner.py` and a new
      `src/research_framework/pipeline/run_receipt.py`.

  ### Testing Requirements

  _Authored 2026-09-08, before implementation._

  - **Test 1**: `tests/pipeline/test_run_receipt.py::test_full_allocates_a_run_directory_named_by_the_state_file`
    - Behavior: after `run_full` on a minimal vault, `_pipeline/runs/<run_id>/`
      exists for the `run_id` in `pipeline-state.json`, holding `run.json`.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_run_receipt.py::test_two_runs_in_one_minute_do_not_share_a_directory`
    - Behavior: freeze the clock, call `run_full` twice; the second `run_id`
      carries a suffix and the first directory is byte-unchanged.
    - Tier: 3
  - **Test 3**: `tests/pipeline/test_run_receipt.py::test_run_json_is_a_pure_function_of_state_and_disk`
    - Behavior: build the receipt twice from the same state file and
      artifacts; the two documents are identical, and the receipt restates
      every phase status the state file holds.
    - Tier: 2
  - **Test 4**: `tests/contracts/test_json_schema_validation.py::test_real_run_receipt_validates_against_schema`
    - Behavior: a `run.json` the real runner wrote after a phase transition
      validates against `tests/contracts/run-receipt-1.0.schema.json`.
    - Tier: 2

  **TDD discipline**: required — the tests above MUST be added in the same
  commit as or earlier than the implementation commit for
  `src/research_framework/pipeline/run_receipt.py`.

- [x] T002 Pass `--cost-sidecar <run_dir>/agent-calls/<stage>.json` on every
      dispatch in `_call_agent`, copy the sidecar's cost into the phase
      summary, and roll the total into the receipt (FR-010…FR-013). A
      missing sidecar is `null` plus a `WARNING`, never `0`. Implementation
      in `src/research_framework/pipeline/runner.py`.

  ### Testing Requirements

  _Authored 2026-09-08, before implementation._

  - **Test 1**: `tests/pipeline/test_run_receipt_sidecars.py::test_every_dispatch_requests_a_cost_sidecar_under_the_run_directory`
    - Behavior: with the fake agent installed, drive `scout`, `research` and
      `report`; assert each dispatch's argv carries `--cost-sidecar` pointing
      under `<run_dir>/agent-calls/`, and the file exists afterwards.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_run_receipt_sidecars.py::test_a_failed_dispatch_still_leaves_a_sidecar_marked_failed`
    - Behavior: a fake agent that exits 1 leaves `agent-calls/<stage>.json`
      with `status: failed`; the phase is `failed` and its summary carries
      the sidecar path.
    - Tier: 3
  - **Test 3**: `tests/pipeline/test_run_receipt_sidecars.py::test_a_missing_sidecar_is_null_cost_with_a_warning_never_zero`
    - Behavior: delete the sidecar between dispatch and phase close; the
      summary's `cost_usd` is `None`, a `WARNING` names the expected path,
      and the receipt's `cost.sidecars_missing` is 1.
    - Tier: 3
  - **Test 4**: `tests/pipeline/test_run_receipt_sidecars.py::test_the_receipt_total_is_the_sum_of_readable_sidecars`
    - Behavior: three sidecars with known `cost_usd`; `run.json.cost.total_usd`
      equals their sum and `sidecars_read` is 3.
    - Tier: 2

  **TDD discipline**: required — the tests above MUST be added in the same
  commit as or earlier than the implementation commit for
  `src/research_framework/pipeline/runner.py`.

## Phase 2: Move the record home, then say where it is

- [x] T003 Relocate the per-phase log, the rendered prompt and the verify
      report under the run directory with numeric suffixes on re-drive
      (FR-003, FR-005), and make `resume`/`finish` reconstruct a missing
      directory rather than fail (FR-004). Move the path assertions in
      `tests/pipeline/test_runner_agent_timeout.py`,
      `tests/pipeline/test_runner_failure_reporting.py` and
      `tests/pipeline/test_runner.py` with the files. Implementation in
      `src/research_framework/pipeline/runner.py`.

  ### Testing Requirements

  _Authored 2026-09-08, before implementation._

  - **Test 1**: `tests/pipeline/test_run_receipt.py::test_a_second_full_run_leaves_the_first_run_intact`
    - Behavior: two `run_full` calls; every file under the first run
      directory has the same bytes after the second.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_run_receipt.py::test_resume_and_finish_write_into_the_run_named_by_state`
    - Behavior: `full` then `resume` then `finish`; exactly one run
      directory exists and holds logs for `scout`, `research` and `report`.
    - Tier: 3
  - **Test 3**: `tests/pipeline/test_run_receipt.py::test_a_pre_receipt_state_file_is_reconstructed_not_refused`
    - Behavior: write a state file with a `run_id` and no run directory;
      `run_finish` creates it, the receipt carries `reconstructed: true`,
      and no phase failed because of it.
    - Tier: 3
  - **Test 4**: `tests/pipeline/test_run_receipt.py::test_a_redriven_stage_suffixes_rather_than_overwrites`
    - Behavior: drive `scout` twice in one run; `logs/scout.log` and
      `logs/scout-2.log` both exist, as do both sidecars.
    - Tier: 3

  **TDD discipline**: required — the tests above MUST be added in the same
  commit as or earlier than the implementation commit for
  `src/research_framework/pipeline/runner.py`.

- [x] T004 Write `run-report.md` beside `run.json` (FR-008), name the run
      directory in `_close_phase`'s `ERROR` line (FR-009), and teach the
      spec-070 FR6 backstop hint to name the receipt for `pipeline` verbs
      (D4). Implementation in `src/research_framework/pipeline/run_receipt.py`
      and `src/research_framework/cli/__init__.py`.

  ### Testing Requirements

  _Authored 2026-09-08, before implementation._

  - **Test 1**: `tests/pipeline/test_run_receipt.py::test_run_report_answers_which_phase_failed_how_long_and_what_it_cost`
    - Behavior: a run with one failed phase and two sidecars; the rendered
      `run-report.md` names the failed phase and its first error, carries a
      duration per phase, and a per-phase and total cost.
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_runner_failure_reporting.py::test_a_failed_phase_names_the_run_directory`
    - Behavior: capture logging at ERROR through a failed `collect`; the
      record names `_pipeline/runs/<run_id>` and the state file.
    - Tier: 3
  - **Test 3**: `tests/cli/test_nonsilent_exit_guard.py::test_the_hint_names_the_run_receipt_for_pipeline_verbs`
    - Behavior: a `pipeline` verb that exits non-zero silently produces a
      hint naming `_pipeline/runs/<run_id>/run-report.md`, not only the
      state file.
    - Tier: 3

  **TDD discipline**: required.

- [x] T005 Add `run_dir`, `receipt`, per-phase `cost_usd` and
      `cost_total_usd` to `status`, `null` where unknown, in both renderings
      (FR-018, FR-019). Implementation in
      `src/research_framework/pipeline/runner.py` and
      `src/research_framework/cli/research_cycles.py`.

  ### Testing Requirements

  _Authored 2026-09-08, before implementation._

  - **Test 1**: `tests/cli/test_pipeline.py::test_status_json_carries_cost_and_run_dir`
    - Behavior: `status --json` on a run with sidecars carries `run_dir`,
      `receipt`, `phases.<stage>.cost_usd` and `cost_total_usd`.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_runner.py::test_status_cost_keys_are_null_without_a_state_file`
    - Behavior: no state file; the keys are present and `None`; return code
      path is unchanged.
    - Tier: 2
  - **Test 3**: `tests/cli/test_pipeline.py::test_status_text_renders_cost_per_phase_and_total`
    - Behavior: the text rendering shows a cost on each dispatching phase
      line and a total line marked as a lower bound when a sidecar is
      missing.
    - Tier: 3

  **TDD discipline**: required.

## Phase 3: Tell the report what happened (#224)

- [x] T006 Render the report phase's run-context block from `run.json`
      (FR-015, FR-016, FR-017): phase statuses, unsupported sources, queue
      size, research counts, verify verdict with flag split and top
      families, total cost, and the explicit zero-notes sentence.
      Implementation in `src/research_framework/pipeline/runner.py`.

  ### Testing Requirements

  _Authored 2026-09-08, before implementation._

  - **Test 1**: `tests/pipeline/test_runner_agent_dispatch.py::test_the_rendered_report_prompt_carries_the_runs_own_counts`
    - Behavior: after `full` + `resume` with a fake research agent that
      writes 2 created / 1 updated, the rendered report prompt names those
      counts, the queue size and the verify verdict.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_runner_agent_dispatch.py::test_a_zero_note_run_is_named_as_such_in_the_report_context`
    - Behavior: research created 0 notes; the rendered prompt contains a
      sentence stating that no notes were created by this run, before the
      agent definition text.
    - Tier: 3
  - **Test 3**: `tests/pipeline/test_runner_agent_dispatch.py::test_the_report_context_names_the_receipts_verify_report`
    - Behavior: the rendered prompt names `<run_dir>/verify-report.json`
      and no `verify-*.md` path.
    - Tier: 3

  **TDD discipline**: required.

- [x] T007 Correct `src/research_framework/agents/report.md.j2`'s `reads:`
      entry and its "Verify report" step (D3): the runner writes JSON under
      the run directory, never `_pipeline/logs/verify-*.md`.

  ### Testing Requirements

  _Authored 2026-09-08, before implementation._

  - **Test 1**: `tests/generator/test_report_agent_definition.py::test_the_report_agent_reads_the_receipts_verify_report`
    - Behavior: render the report agent definition for a fixture spec;
      assert it names `_pipeline/runs/` and `verify-report.json` and does
      not name `verify-*.md`.
    - Tier: 2

  **TDD discipline**: required.

## Phase 4: Retention and the cap

- [x] T008 `pipeline <vault> prune-runs --keep N --older-than DAYS
      [--dry-run]` (FR-020, Q1). Never deletes the run named by the current
      state file. Implementation in
      `src/research_framework/cli/research_cycles.py` and
      `src/research_framework/pipeline/run_receipt.py`.

  ### Testing Requirements

  _Authored 2026-09-08, before implementation._

  - **Test 1**: `tests/cli/test_pipeline_prune_runs.py::test_prune_keeps_the_newest_n_and_anything_younger_than_the_age`
    - Behavior: eight run directories with spread mtimes; `--keep 5
      --older-than 90` removes only those beyond both bounds.
    - Tier: 3
  - **Test 2**: `tests/cli/test_pipeline_prune_runs.py::test_prune_never_removes_the_current_run`
    - Behavior: the run named by the state file survives whatever the
      bounds say.
    - Tier: 3
  - **Test 3**: `tests/cli/test_pipeline_prune_runs.py::test_dry_run_deletes_nothing_and_lists_what_it_would`
    - Behavior: `--dry-run` leaves every directory in place and prints the
      set it would remove.
    - Tier: 3

  **TDD discipline**: required.

- [x] T009 Decide and record whether `--budget-cap` on `pipeline` verbs is
      wired against the receipt's running total (FR-014) or stays refused
      in favour of `limits.cycle_budget_usd`.

  **Decided 2026-09-10: it stays refused.** The receipt makes spend
  *recorded*, which was the precondition — but a cap needs to be checked
  *before* a dispatch, and the sidecar exists only *after* one. Wiring
  `--budget-cap` against a running total would therefore stop the run at the
  first phase that overshot, having already paid for it: a cap that reports a
  breach rather than preventing one. `limits.cycle_budget_usd` is enforced at
  `agent_call.py`, which is the surface that knows a call is about to happen,
  and spec 033 put it there deliberately (`docs/ROADMAP.md` § Notes on
  decisions already made: "don't add a second dispatch surface"). The honest
  wiring is to teach `agent_call.py`'s existing pre-dispatch check to read the
  run's accumulated total, which is a spec-033 amendment and not this spec's
  scope. `075` FR-006 stays correct as written and
  `tests/cli/test_pipeline.py::TestPipelineBudgetCapIsRefused` stays green —
  with its refusal message updated, because "no pipeline phase records
  per-call cost yet" stopped being true with this spec.
