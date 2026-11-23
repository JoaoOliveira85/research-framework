# Tasks: Outside-in discovery

**Spec**: [`spec.md`](spec.md) · **Plan**: [`plan.md`](plan.md) · **Status of
the spec**: `planned`. Task boxes are live. `087` lands first.

## Phase 1: Areas, ledger, settings (nothing calls them)

- [x] T001 `pipeline/discovery.py`: `scope_areas`, `choose_areas`, the ledger
      (`load_ledger`, `record_cycle`), the registry row and accessor in
      `state_layout` (FR-002, FR-008, FR-009; plan § 1).

  ### Testing Requirements

  _Authored 2026-11-23, before implementation._

  - **Test 1**: `tests/pipeline/test_discovery_rotation.py::test_never_checked_then_oldest_then_spec_order`
    - Tier: 1
  - **Test 2**: `tests/pipeline/test_discovery_rotation.py::test_every_area_is_checked_within_the_expected_cycles`
    - Behavior: spec SC-002, for 7 areas at 3 per cycle.
    - Tier: 1
  - **Test 3**: `tests/pipeline/test_discovery_ledger.py::test_checked_with_nothing_found_is_distinct_from_never_checked`
    - Tier: 1
  - **Test 4**: `tests/pipeline/test_discovery_ledger.py::test_assigned_but_not_reported_does_not_advance_the_area`
    - Tier: 1
  - **Test 5**: `tests/pipeline/test_discovery_rotation.py::test_simple_and_detailed_specs_both_yield_areas`
    - Tier: 1

  **TDD discipline**: required.

- [x] T002 Settings `pipeline.discovery` in the schema and every shipped
      profile; `split_quota` returns three counts with a carried fractional
      credit (FR-007, FR-012; plan § 2, § 4).

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_settings_discovery.py::test_defaults_and_validation`
    - Tier: 1
  - **Test 2**: `tests/pipeline/test_cycle_split.py::test_a_ten_percent_share_yields_one_slot_every_ten_quota_units`
    - Tier: 1
  - **Test 3**: `tests/pipeline/test_cycle_split.py::test_unused_discovery_share_falls_to_new_topics_and_refresh_dispatches_none`
    - Tier: 1
  - Existing `split_quota` tests are re-pointed at the three-count return.

  **TDD discipline**: required.

## Phase 2: The pass

- [x] T003 The scout prompt's discovery section, the report shape, and
      `validate_cycle.py` (FR-001, FR-003, FR-011; plan § 3).

  ### Testing Requirements

  - **Test 1**: `tests/generator/test_scout_prompt_discovery.py::test_section_lists_the_assigned_areas_and_the_window`
    - Tier: 3
  - **Test 2**: `tests/generator/test_scout_prompt_discovery.py::test_no_areas_means_no_section`
    - Tier: 3
  - **Test 3**: `tests/scripts/test_validate_cycle_discovery.py::test_reports_with_and_without_discovery_validate`
    - Tier: 3

  **TDD discipline**: required.

- [ ] T004 Rotation at cycle start, `DG-001`, routing, the three-way split in
      the plan and the batch loop, the ledger write after the scout step
      (FR-004…FR-009; plan § 4, § 5, § 6).

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_discovery_gate.py::test_each_bad_row_is_dropped_with_its_reason`
    - Behavior: parametrised over unassigned area, no source, date outside
      the window, malformed date, empty title.
    - Tier: 1
  - **Test 2**: `tests/pipeline/test_discovery_routing.py::test_rows_route_to_topic_update_observation_or_drop`
    - Tier: 3
  - **Test 3**: `tests/pipeline/test_discovery_routing.py::test_discovery_rows_do_not_count_toward_focus_or_diversity`
    - Tier: 3
  - **Test 4**: `tests/e2e/test_discovery_cycle.py::test_a_topic_with_no_shared_term_is_dispatched_and_attributed`
    - Behavior: spec SC-001 and User Story 1.
    - Tier: 5
  - **Test 5**: `tests/e2e/test_discovery_cycle.py::test_a_finding_about_an_existing_note_becomes_one_update_entry`
    - Behavior: spec SC-004 and User Story 2.
    - Tier: 5
  - **Test 6**: `tests/quality/test_discovery_off_matches_baseline.py::test_share_zero_plans_the_same_work_as_before`
    - Behavior: spec SC-003.
    - Tier: 5
  - The fake agent gains a discovery scenario.

  **TDD discipline**: required.

## Phase 3: Surfaces and proof

- [ ] T005 Cycle summary, `status`, `health`; `README.md`, `ARCHITECTURE.md`,
      `CHANGELOG.md`, `docs/ROADMAP.md` (FR-010).

  ### Testing Requirements

  - **Test 1**: `tests/cli/test_status_discovery.py::test_status_names_the_areas_checked_and_the_counts`
    - Tier: 4
  - **Test 2**: `tests/scripts/test_vault_health_discovery.py::test_health_lists_areas_never_checked`
    - Tier: 3

  **TDD discipline**: required for the two surfaces.

- [ ] T006 Gates: fast loop, e2e, guard battery, both ruff gates; refresh the
      test-count marker. `build.sh --quality` and the rehearsal on a vault
      copy are done separately.

  **TDD discipline**: not applicable.
