# Tasks: The weekly pipeline runner

**Spec**: [`spec.md`](spec.md) · **Status of the spec**: `shipped` — the
runner described there already exists. These tasks are the follow-up work the
spec's § Known divergences identified. Nothing here is a re-implementation.

Task boxes are live: a `- [ ]` on this spec means genuinely not done.

## Phase 1: Correct the documents that contradict the code

- [ ] T001 Correct `src/research_framework/agents/pipeline.md.j2`'s `finish`
      description (D2). It tells the operator `finish` "skips research if
      queue already clear"; `run_finish` never runs research at all.

  ### Testing Requirements

  _Authored 2026-09-07, before implementation._

  - **Test 1**: `tests/pipeline/test_runner_triage_prompt.py::test_the_pipeline_agent_definition_points_at_the_same_artifact`
    - Behavior: extend the existing assertion so the rendered agent
      definition's `finish` line cannot claim a conditional the runner does
      not implement. Fails today against the stale wording.
    - Tier: 2

  **TDD discipline**: required — the assertion lands in the same commit as
  or earlier than the template edit.

- [ ] T002 Give `075` and the multi-cycle orchestrator distinct names in
      ARCHITECTURE.md and CLAUDE.md (D1), so "the pipeline" is never
      ambiguous.

## Phase 2: Close the honesty gaps

- [ ] T003 Report "dispatcher not found" as its own phase error rather than
      letting it surface as a missing artifact (D3).

  ### Testing Requirements

  _Authored 2026-09-07, before implementation._

  - **Test 1**: `tests/pipeline/test_runner_agent_dispatch.py::test_a_missing_dispatcher_is_named_as_the_reason`
    - Behavior: with no `agent_call.py` in either location, the phase's
      `errors` name the missing script, not just the absent artifact.
    - Tier: 3

  **TDD discipline**: required.

- [ ] T004 Decide and record whether the runner should honour the vault's
      `research.spec.md` `processors:` block (D4). Today the multi-cycle
      orchestrator does and the runner does not, and nothing says so.
- T005 — satisfied (2026-09-08). `pipeline-state.schema.json` is wired by
  #326: `tests/contracts/test_json_schema_validation.py::test_blank_pipeline_state_validates_against_schema`
  and `::test_real_saved_pipeline_state_file_validates_after_a_phase_transition`
  validate a blank state and one the real runner wrote. Relocated out of
  `specs/_archive/` into this spec's `contracts/` by #295; its future beside
  the run receipt is `080-run-receipt` § Absorbed tasks (D5).
