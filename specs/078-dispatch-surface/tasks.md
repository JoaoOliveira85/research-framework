# Tasks: The `agent_call` dispatch surface

**Spec**: [`spec.md`](spec.md) · **Status of the spec**: `shipped` — the seam
described there is the one that exists. These tasks are the follow-up work
§ Known divergences identified.

## Phase 1: Point the documents at the real file

- [ ] T001 Correct every reference to
      `src/research_framework/pipeline/agent_call.py` (D1). No such file has
      ever existed; the seam is `scripts/agent_call.py`. ARCHITECTURE.md and
      CONTRIBUTING.md both name the wrong path, and a clean-room reader
      following them would build the seam where it is not.

  ### Testing Requirements

  _Authored 2026-09-07, before implementation._

  - **Test 1**: `tests/docs/test_one_source_per_fact.py::test_docs_name_the_real_dispatch_module`
    - Behavior: scan the root docs for a path ending
      `pipeline/agent_call.py`; assert none, and assert the path the docs do
      name exists on disk. Fails today.
    - Tier: 2

  **TDD discipline**: required.

- [ ] T002 Correct ARCHITECTURE's audit-log filename claim (D2): it
      describes `<timestamp>-<stage>-<call-id>.json`; the sidecars are
      `<stage>.json` / `<stage>-N.json` / `<stage>-batch-N.json`.

## Phase 2: Retire what is inert

- [ ] T003 Remove the unused `tier` parameter from the cost estimator, or
      make it do something (D4).
- [ ] T004 Move the cursor tier→model dictionary into documentation, since
      no code path consults it (D5).
- T005 — decided (2026-09-08) by `080-run-receipt` FR-010: the weekly
  runner requests a cost sidecar on every dispatch, written under
  `_pipeline/runs/<run_id>/agent-calls/<stage>.json` (D6). Until `080`
  ships, `075` FR-006's refusal of `--budget-cap` is the correct behaviour
  and stays; `080` T009 owns the cap decision once the record exists.
