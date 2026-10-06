# Tasks: The triage gate

**Spec**: [`spec.md`](spec.md) · **Status of the spec**: `planned`. Task
boxes are live: a `- [ ]` means genuinely not done. T001 and T002 are the
gate; everything after is what makes it liveable.

## Phase 1: The artifact, the verb, the refusal

- [ ] T001 The `pipeline <vault> triage` subcommand and `_pipeline/triage.json`
      (FR-001…FR-009): listing with stable indices, `--approve`/`--defer`,
      `--top N`, `--all`, `--json`, the digest, the schema at
      `tests/contracts/triage-1.0.schema.json`. Implementation in a new
      `src/research_framework/pipeline/triage.py`, wired through
      `src/research_framework/cli/_parser.py` and
      `src/research_framework/cli/research_cycles.py`; regenerate the
      `--help` golden.

  ### Testing Requirements

  _Authored 2026-09-08, before implementation._

  - **Test 1**: `tests/cli/test_pipeline_triage.py::test_triage_lists_the_queue_with_stable_indices`
    - Behavior: a scout report with four topics; `triage` with no selector
      prints four rows numbered 1–4, writes nothing, exits 0; a second call
      after `--approve 2` shows the same numbering.
    - Tier: 3
  - **Test 2**: `tests/cli/test_pipeline_triage.py::test_approve_and_defer_write_the_decision_and_leave_the_rest_pending`
    - Behavior: `--approve 1,3 --defer 2` on four topics; `triage.json`
      carries two approved, one deferred, one pending, and the summary line
      prints those counts.
    - Tier: 3
  - **Test 3**: `tests/cli/test_pipeline_triage.py::test_top_n_approves_the_first_n_and_defers_the_rest`
    - Behavior: `--top 2` on four topics leaves zero pending.
    - Tier: 3
  - **Test 4**: `tests/cli/test_pipeline_triage.py::test_conflicting_selectors_and_bad_indices_exit_2_and_write_nothing`
    - Behavior: `--all --top 2`, `--approve 9` on four topics, `--top 0`
      each exit 2 with a stderr reason and no artifact.
    - Tier: 3
  - **Test 5**: `tests/contracts/test_json_schema_validation.py::test_real_triage_artifact_validates_against_schema`
    - Behavior: an artifact the real verb wrote validates against
      `tests/contracts/triage-1.0.schema.json`.
    - Tier: 2

  **TDD discipline**: required — the tests above MUST be added in the same
  commit as or earlier than the implementation commit for
  `src/research_framework/pipeline/triage.py`.

- [ ] T002 `resume` reads the decision, refuses without one, hands research
      only the approved topics via `_pipeline/research-queue.json`, and
      records the counts in the triage summary (FR-010…FR-013). Rewrite the
      three tests spec.md § Testing Requirements names as pinning the old
      behaviour. Implementation in `src/research_framework/pipeline/runner.py`.

  ### Testing Requirements

  _Authored 2026-09-08, before implementation._

  - **Test 1**: `tests/pipeline/test_runner_triage_gate.py::test_resume_refuses_without_a_decision_and_names_the_verb`
    - Behavior: `full` then `resume` with no `triage.json`; exit 2, no
      dispatch, stderr names `pipeline <vault> triage` and `--all`.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_runner_triage_gate.py::test_resume_refuses_an_empty_approval_set_against_a_non_empty_queue`
    - Behavior: a decision with zero approved over four topics; exit 2.
    - Tier: 3
  - **Test 3**: `tests/pipeline/test_runner_triage_gate.py::test_resume_researches_only_the_approved_topics`
    - Behavior: two of four approved; `research-queue.json` holds exactly
      those two, the rendered research prompt names that file, and the
      fake research agent is handed a queue of two.
    - Tier: 3
  - **Test 4**: `tests/pipeline/test_runner_triage_gate.py::test_a_changed_queue_invalidates_the_decision`
    - Behavior: record a decision, then rewrite the scout report with an
      extra topic; `resume` exits 2 saying the queue no longer matches.
    - Tier: 3
  - **Test 5**: `tests/pipeline/test_runner_triage_gate.py::test_an_empty_queue_still_resumes_with_a_reason`
    - Behavior: `topics_found.new: []` and no decision; `resume` proceeds
      and the research summary carries `empty_queue_reason`.
    - Tier: 3

  **TDD discipline**: required — the tests above MUST be added in the same
  commit as or earlier than the implementation commit for
  `src/research_framework/pipeline/runner.py`.

## Phase 2: Carry-over, status, the pause

- [ ] T003 Deferred topics go to `_pipeline/research-backlog.md` with
      provenance and come back as `carried_over` in the next triage, without
      duplication (FR-014…FR-016). Implementation in
      `src/research_framework/pipeline/triage.py`.

  ### Testing Requirements

  _Authored 2026-09-08, before implementation._

  - **Test 1**: `tests/pipeline/test_runner_triage_gate.py::test_deferred_topics_are_carried_into_the_backlog_with_provenance`
    - Behavior: defer two topics, `resume`; the backlog gains a heading
      naming the `run_id` and one line per topic with its source.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_runner_triage_gate.py::test_carried_over_topics_reappear_in_the_next_triage_after_new_ones`
    - Behavior: a second `full` with two new scout topics; `triage` lists
      four rows — the new two first, then the carried two marked with the
      earlier `run_id` — and `counts.carried_over` is 2.
    - Tier: 3
  - **Test 3**: `tests/pipeline/test_runner_triage_gate.py::test_a_topic_deferred_twice_has_one_backlog_entry_naming_both_runs`
    - Behavior: defer the same carried topic again; the backlog holds one
      line for it naming two runs.
    - Tier: 3

  **TDD discipline**: required.

- [ ] T004 `status` renders the gate's counts, and `waiting` with the queue
      size before a decision (FR-017). Implementation in
      `src/research_framework/pipeline/runner.py` and
      `src/research_framework/cli/research_cycles.py`.

  ### Testing Requirements

  _Authored 2026-09-08, before implementation._

  - **Test 1**: `tests/cli/test_pipeline.py::test_status_reports_approved_deferred_and_carried_over`
    - Behavior: after a decision, the text `triage` line and the JSON
      summary carry the four counts.
    - Tier: 3
  - **Test 2**: `tests/cli/test_pipeline.py::test_status_says_how_many_topics_await_a_decision`
    - Behavior: paused with no decision; the `triage` line is `waiting`
      and names the queue size.
    - Tier: 3

  **TDD discipline**: required.

- [ ] T005 `resume --auto-approve top:N` (FR-018, FR-019): bounded, recorded,
      refused when unbounded, overridden by an operator's decision.
      Implementation in `src/research_framework/pipeline/runner.py` and
      `src/research_framework/cli/_parser.py`.

  ### Testing Requirements

  _Authored 2026-09-08, before implementation._

  - **Test 1**: `tests/pipeline/test_runner_triage_gate.py::test_auto_approve_top_n_records_who_approved_and_defers_the_rest`
    - Behavior: `top:2` over four topics with no decision; two approved,
      two deferred into the backlog, `decided_by == "auto:top:2"`.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_runner_triage_gate.py::test_auto_approve_without_a_bound_is_refused`
    - Behavior: `--auto-approve all` and a bare `--auto-approve` each exit
      2 with a stderr reason.
    - Tier: 3
  - **Test 3**: `tests/pipeline/test_runner_triage_gate.py::test_an_operators_decision_beats_auto_approve`
    - Behavior: a recorded operator decision plus `top:2`; the decision is
      unchanged and a WARNING says the flag was ignored.
    - Tier: 3

  **TDD discipline**: required.

- [ ] T006 The pause message and the generated `/pipeline` agent definition
      name the `triage` verb and stop saying there is no gate (FR-020).
      Implementation in `src/research_framework/pipeline/runner.py` and
      `src/research_framework/agents/pipeline.md.j2`.

  ### Testing Requirements

  _Authored 2026-09-08, before implementation._

  - **Test 1**: `tests/pipeline/test_runner_triage_prompt.py::test_pause_names_the_triage_verb_as_the_next_step`
    - Behavior: the captured pause narration names
      `research-framework pipeline <vault> triage` and does not contain
      "no approve/defer gate".
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_runner_triage_prompt.py::test_the_pipeline_agent_definition_names_the_same_verb`
    - Behavior: the rendered agent definition's triage step names the
      `triage` verb, so the two surfaces cannot disagree.
    - Tier: 2

  **TDD discipline**: required.

## Phase 3: Later

- [ ] T007 An optional `estimated_cost_usd` per topic in the artifact (D4),
      projected from `080`'s sidecar history and the spec-033 estimator;
      `null` until both exist for the vault. Decide the projection rule in
      this task before writing it.
