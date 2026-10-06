# Tasks: The `settings.yaml` schema

**Spec**: [`spec.md`](spec.md) · **Status of the spec**: `shipped` — the
schema described there is the one the loaders implement. These tasks are the
follow-up work § Known divergences identified.

## Phase 1: Stop shipping config nothing reads

- [ ] T001 Remove, or wire up, the dead keys listed in D1. Each needs an
      individual decision: `schema_version`, `communication.mode`, the
      top-level `model_router` block, `research_modes`, `exit_invariant`,
      the top-level `dimensions` list, the seven superseded
      `pipeline.gates.*` thresholds, `queryability_score_regression_pp`,
      `stages.source_manager.auto_promote_discovered`,
      `stages.verifier.on_timeout`, `stages.verifier.output_filename`,
      `stages.topic_propose.auto_promote`.

  ### Testing Requirements

  _Authored 2026-09-07, before implementation._

  - **Test 1**: `tests/pipeline/test_shipped_profiles_enforce_budget.py::test_profile_ships_no_key_no_reader_parses`
    - Behavior: for every shipped profile, assert `extras` contains no key
      from a named dead-key set — the same shape as the existing
      `test_profile_has_no_unparsed_budget_block`, generalised. The set
      shrinks as keys are removed or wired.
    - Tier: 2

  **TDD discipline**: required — the test is written against the current
  dead-key set and fails until each is resolved.

- [ ] T002 Bring `examples/settings.yml` under that guard (D3). It still
      carries the `budget:` block #230 removed, because the guard's glob
      matches neither its extension nor its directory.

## Phase 2: Resolve the ambiguities

- [ ] T003 Either implement the `research.spec.md`-overrides-`settings.yaml`
      merge the file's own header promises, or delete the promise (D2).
- [ ] T004 Rename one of the two `tier` vocabularies (D5), or document the
      hazard at the key itself.
- [ ] T005 Establish whether the D7 model-tier resolver has a production
      caller; if not, decide whether to wire it or retire it (D5).
