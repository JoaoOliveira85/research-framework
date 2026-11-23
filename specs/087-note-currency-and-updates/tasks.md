# Tasks: Note currency and updates

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Spec**: [`spec.md`](spec.md) · **Plan**: [`plan.md`](plan.md) · **Status of
the spec**: `planned`. Task boxes are live: a `- [ ]` means genuinely not
done. `083` and `084` land first; this branch is rebased onto `084`.

## Phase 1: Fields, entries and the sweep (nothing dispatched differently)

- T001 `src/research_framework/vault/note_currency.py`: field names,
      the five values, `effective`, `countable`, `is_due`. The note template
      stamps `as_of` and `currency` empty; `scripts/validate_vault.py`'s
      required list and `processors/verify.py`'s resolver read the names
      from the module (FR-006, FR-007, FR-008; plan § 1).

  ### Testing Requirements

  _Authored 2026-11-23, before implementation._

  - **Test 1**: `tests/vault/test_note_currency.py::test_missing_fields_read_as_current_and_never_due`
    - Tier: 1
  - **Test 2**: `tests/vault/test_note_currency.py::test_only_superseded_and_retracted_are_uncountable`
    - Tier: 1
  - **Test 3**: `tests/vault/test_note_currency.py::test_due_needs_an_interval_a_live_standing_and_an_old_as_of`
    - Behavior: parametrised over interval absent, `as_of` inside and
      outside the interval, each of the five values, and a malformed date
      (never due, no exception).
    - Tier: 1
  - **Test 4**: `tests/generator/test_note_template_currency.py::test_template_stamps_both_keys_empty_and_verify_requires_them`
    - Behavior: a rendered note-type template carries `as_of: ""` and
      `currency: ""`; `processors/verify.py`'s resolved required set
      contains both.
    - Tier: 3
  - **Test 5**: `tests/vault/test_note_currency.py::test_every_reader_takes_the_field_names_from_the_module`
    - Behavior: no file under `src/` or `scripts/` other than
      `note_currency.py` contains the literal `superseded_by`.
    - Tier: 2

  **TDD discipline**: required.

- T002 `NoteTypeConfig.review_after_days`: dataclass, `to_dict` /
      `from_dict`, `spec/simple.py::_expand_note_types`, a positive-integer
      check in `spec/validator.py`, `PARSER_VERSION` bump (FR-009; plan § 5).

  ### Testing Requirements

  - **Test 1**: `tests/spec/test_review_after_days.py::test_the_key_survives_both_spec_formats_and_the_parsed_cache`
    - Tier: 1
  - **Test 2**: `tests/spec/test_review_after_days.py::test_zero_negative_and_non_integer_values_are_refused`
    - Tier: 1
  - **Test 3**: `tests/spec/test_review_after_days.py::test_absent_means_none`
    - Tier: 1
  - `tests/spec/test_parsed_spec_cache.py` is updated for the version bump.

  **TDD discipline**: required.

- T003 `pipeline/backlog.py`: origin `update`, id `update:<stem>`,
      schema `1.1`, `observe_update`, `close_update`, `update_topics`, the
      "Notes to update" section of the view; the contracts under
      `specs/084-structured-research-backlog/contracts/` gain the origin
      (FR-003, FR-004; plan § 2).

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_backlog_updates.py::test_one_open_entry_per_note_and_a_second_sighting_updates_it`
    - Tier: 1
  - **Test 2**: `tests/pipeline/test_backlog_updates.py::test_new_material_outranks_review_due_then_oldest_as_of`
    - Tier: 1
  - **Test 3**: `tests/pipeline/test_backlog_updates.py::test_close_records_the_outcome_and_a_later_sighting_reopens`
    - Tier: 1
  - **Test 4**: `tests/pipeline/test_backlog_updates.py::test_a_1_0_store_is_read_and_written_as_1_1_without_loss`
    - Tier: 1
  - **Test 5**: `tests/pipeline/test_backlog_view.py::test_view_lists_notes_to_update`
    - Tier: 2

  **TDD discipline**: required.

- T004 `pipeline/currency.py::queue_due_reviews`, called at cycle start
      before the plan is generated, with a `recompute_from_disk` beside it
      (FR-010, FR-018's "where the planner looks"; plan § 4).

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_due_reviews.py::test_a_note_past_its_interval_gets_one_review_due_entry`
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_due_reviews.py::test_superseded_retracted_unstamped_and_interval_less_notes_are_not_queued`
    - Tier: 3
  - **Test 3**: `tests/pipeline/test_due_reviews.py::test_the_sweep_calls_no_model`
    - Behavior: with the fake agent installed and set to fail on any
      dispatch, the sweep completes.
    - Tier: 3
  - **Test 4**: `tests/pipeline/test_due_reviews.py::test_the_planner_sees_counts_recomputed_before_it_plans`
    - Tier: 3

  **TDD discipline**: required.

## Phase 2: The scout reports, the settings exist

- T005 The scout prompt renders existing notes as "already have a note"
      and persistent rejects as a separate skip list; the scout report
      accepts `topics_found.updates`; after the merge, `updates` rows and
      `new` rows that match an existing note become `new_material` entries;
      `_template_version` bumped and the prompt corpus regenerated
      (FR-001, FR-002; plan § 3).

  ### Testing Requirements

  - **Test 1**: `tests/generator/test_scout_prompt_existing_notes.py::test_existing_notes_are_reported_against_not_skipped`
    - Behavior: the rendered prompt has no "Already covered — skip these"
      heading, lists existing notes under the new heading with the
      instruction, and lists persistent rejects under a skip heading.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_scout_updates.py::test_an_updates_row_becomes_a_new_material_entry_with_its_source`
    - Tier: 3
  - **Test 3**: `tests/pipeline/test_scout_updates.py::test_a_new_row_matching_an_existing_note_is_queued_as_an_update_not_dropped`
    - Tier: 3
  - **Test 4**: `tests/pipeline/test_scout_updates.py::test_a_persistently_rejected_title_is_still_dropped`
    - Tier: 3
  - **Test 5**: `tests/scripts/test_validate_cycle_updates.py::test_a_scout_report_with_and_without_updates_validates`
    - Tier: 3
  - Re-pointed: `tests/generator/test_templates.py::test_scout_prompt_renders_target_topics_when_supplied`,
    `::test_scout_prompt_skips_resume_sections_when_empty`,
    `tests/pipeline/test_orchestrator.py::test_render_cycle_scout_prompt_focuses_on_unmet`,
    `::test_phase2_promoted_titles_merge_into_target_topics`.

  **TDD discipline**: required.

- T006 `pipeline.cycle_split` in the settings schema and every shipped
      profile; `research_mode` chooses how it applies, default `expand`;
      `phases` filters the scout prompt's sources; the `research_modes`
      blocks leave the profiles and `_INERT_PATHS`; the guard
      `scripts/guards/settings_key_consumers.py` (FR-015, FR-016, FR-017,
      SC-005; plan § 6, § 14).

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_cycle_split.py::test_split_rounds_to_the_quota_and_empty_shares_fall_to_the_others`
    - Behavior: parametrised over quotas 1, 3, 10, 17 and over no update
      entries, no coverage gaps, and discovery always empty.
    - Tier: 1
  - **Test 2**: `tests/pipeline/test_cycle_split.py::test_mode_overrides_the_split`
    - Behavior: `bootstrap` → 0 updates; `refresh` → 0 new topics;
      `expand` → the configured shares.
    - Tier: 1
  - **Test 3**: `tests/pipeline/test_settings_cycle_split.py::test_shares_must_be_three_non_negative_integers_summing_to_100`
    - Tier: 1
  - **Test 4**: `tests/spec/test_research_mode_default.py::test_a_spec_that_declares_no_mode_is_expand`
    - Tier: 1
  - **Test 5**: `tests/pipeline/test_scout_source_phases.py::test_a_source_outside_the_cycles_mode_is_not_in_the_prompt`
    - Tier: 3
  - **Test 6**: `tests/guards/test_settings_key_consumers.py::test_an_unread_pipeline_key_fails_and_the_tree_passes`
    - Tier: 2
  - Updated: the `tests/spec` tests that pin `bootstrap` as the default;
    `tests/pipeline/test_settings_unknown_keys.py`.

  **TDD discipline**: required.

## Phase 3: Updates are dispatched and judged

- T007 The plan's update queue and `_split_quota`; `BatchAssignment.kind`;
      the batch loop cuts and counts update batches; the update batch prompt
      (`## Update topics (JSON)`, exclusions exempt the assigned notes, no
      synthetic "no new file" failure, no "do not edit existing notes" hint)
      (FR-004, FR-005a, FR-022; plan § 7, § 8).

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_update_batches.py::test_plan_round_trips_its_update_queue_through_markdown`
    - Tier: 1
  - **Test 2**: `tests/pipeline/test_update_batches.py::test_ten_due_notes_and_a_share_of_three_dispatch_exactly_three_oldest_first`
    - Behavior: spec SC-002.
    - Tier: 5
  - **Test 3**: `tests/pipeline/test_update_batches.py::test_an_update_batch_that_writes_no_new_file_is_not_failed`
    - Tier: 3
  - **Test 4**: `tests/pipeline/test_update_batches.py::test_the_update_prompt_exempts_its_notes_from_the_binding_exclusions`
    - Tier: 3
  - **Test 5**: `tests/quality/test_split_off_matches_baseline.py::test_update_share_zero_plans_the_same_work_as_before`
    - Behavior: spec SC-006 on the three committed quality fixtures.
    - Tier: 3
  - Retained: `tests/pipeline/test_batch_orchestration.py` (new-topic
    batches unchanged).

  **TDD discipline**: required.

- T008 The writer's update contract and the outcome gate: the DFS prompt's
      update instructions (challenge from the problem the note addresses),
      `update_outcomes` in the research report, `UG-001` against `HEAD`,
      restore on failure, `close_update`, `notes_updated` derived, a
      `confirmed` outcome counted nowhere as content (FR-005, FR-011,
      FR-012, FR-014; plan § 9; spec D2, D4).

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_update_outcomes.py::test_each_outcome_is_checked_against_head`
    - Behavior: parametrised over the four outcomes, each with a passing
      shape and its characteristic lie (a `confirmed` that changed the
      body; a `revised` with no new source; a `superseded` with no
      successor link; a `retracted` with no reason).
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_update_outcomes.py::test_a_failed_outcome_restores_the_note_and_leaves_the_entry_open`
    - Tier: 3
  - **Test 3**: `tests/pipeline/test_update_outcomes.py::test_confirmed_moves_as_of_and_counts_as_no_content`
    - Behavior: not in `notes_created`, not in `notes_updated`, not in the
      yield or quality figures; the sources consulted are recorded.
    - Tier: 3
  - **Test 4**: `tests/e2e/test_update_cycle.py::test_new_material_revises_the_note_in_place`
    - Behavior: spec SC-001 and User Story 1.
    - Tier: 5
  - **Test 5**: `tests/e2e/test_update_cycle.py::test_a_due_note_ends_in_exactly_one_outcome`
    - Behavior: spec User Story 2.
    - Tier: 5
  - The fake agent gains an update scenario per outcome.

  **TDD discipline**: required.

- T009 The verifier's `IX-currency-evidence` and
      `IX-supersession-symmetry` rules (FR-007, FR-013; plan § 10).

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_verifier_currency.py::test_supersession_on_commentary_alone_is_rejected_without_a_model_call`
    - Behavior: spec SC-003.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_verifier_currency.py::test_supersession_with_a_corroborated_source_stands`
    - Tier: 3
  - **Test 3**: `tests/pipeline/test_verifier_currency.py::test_a_one_sided_supersession_link_is_rejected`
    - Tier: 3
  - **Test 4**: `tests/pipeline/test_verifier_currency.py::test_a_note_whose_standing_did_not_change_is_not_judged_by_the_rule`
    - Tier: 3

  **TDD discipline**: required.

## Phase 4: What the vault says about itself

- T010 Coverage skips uncountable notes; `./vault coverage` recounts in
      memory and shows past-review and superseded counts per category;
      `health` gains a Currency section; `status` shows the last cycle's
      outcomes by kind; the `ask` template's rule; prompt corpus regenerated
      (FR-018, FR-019; plan § 11, § 12).

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_coverage_currency.py::test_a_superseded_note_stops_counting`
    - Behavior: spec SC-004, first half.
    - Tier: 3
  - **Test 2**: `tests/cli/test_coverage_currency_columns.py::test_coverage_reports_past_review_and_superseded_and_writes_nothing`
    - Tier: 4
  - **Test 3**: `tests/scripts/test_vault_health_currency.py::test_health_lists_notes_past_review_per_category`
    - Tier: 3
  - **Test 4**: `tests/cli/test_status_outcomes.py::test_status_shows_the_last_cycles_outcomes`
    - Tier: 4
  - **Test 5**: `tests/generator/test_ask_template_currency.py::test_ask_is_told_to_follow_superseded_by_and_flag_past_review`
    - Tier: 3
  - Retained: `tests/pipeline/test_coverage_recompute.py`,
    `tests/quality/test_coverage_recompute_regression.py`.

  **TDD discipline**: required.

## Phase 5: Existing vaults, and proof

- T011 The migration step `stamp_note_currency` in
      `layout_migration.MIGRATION_STEPS` (FR-021, FR-022; plan § 13).

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_stamp_note_currency.py::test_as_of_comes_from_accessed_then_updated_then_created_then_git`
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_stamp_note_currency.py::test_no_body_and_no_existing_frontmatter_line_changes`
    - Behavior: for every note, the file minus the two added lines is
      byte-identical to the original.
    - Tier: 3
  - **Test 3**: `tests/pipeline/test_stamp_note_currency.py::test_dry_run_second_run_and_the_commit_shape`
    - Tier: 3
  - **Test 4**: `tests/pipeline/test_stamp_note_currency.py::test_alias_exempt_and_already_stamped_notes_are_left_alone`
    - Tier: 3
  - **Test 5**: `tests/pipeline/test_stamp_note_currency.py::test_the_first_cycles_after_stamping_review_at_most_the_update_share`
    - Tier: 5

  **TDD discipline**: required.

- T012 Docs: `README.md` (what "keeps itself current" now means),
      `ARCHITECTURE.md`, `examples/` specs gain `review_after_days` on one
      type, `CHANGELOG.md` `[Unreleased]` with `### Migration notes`, the
      ROADMAP row, the constitution's coverage-gate text if it says "note
      count".

  ### Testing Requirements

  - `tests/docs/` stays green; the prompt corpus test stays green.

  **TDD discipline**: not applicable (documentation).

- T013 Acceptance and the gates.

  ### Testing Requirements

  - **Test 1**: `tests/e2e/test_supersession_end_to_end.py::test_a_superseded_note_links_its_successor_and_ask_follows_it`
    - Behavior: spec User Story 3 and SC-004.
    - Tier: 5
  - **Test 2**: `tests/e2e/test_modes_end_to_end.py::test_refresh_runs_no_new_topic_batches_and_bootstrap_no_update_batches`
    - Behavior: spec User Story 4.
    - Tier: 5

  Gates, run and reported in the PR: `pytest -m "not e2e"`,
  `pytest -m e2e`, `python scripts/guards/run_all.py`, `ruff check .`,
  `ruff format --check .`, `bash build.sh --quality`; refresh the
  test-count marker.

  Rehearsal (NOT done in this task: it is done separately, on copies of live
  vaults, by the owner; `bash build.sh --quality` likewise), reported in the PR: the three migration steps, dry-run then
  real, on copies of two live vaults; then two fake-free research cycles on
  one copy with a 90-day interval on one note type, reporting the outcomes
  by kind, the dollars per worked update, and the extrapolated cost of a
  first pass over that vault (spec Q3).

  **TDD discipline**: required.

## Acceptance coverage

Which tests evidence each user story of `spec.md` (the spec's own table is not
edited here).

| Story | Evidence |
| --- | --- |
| US1 — new material on an existing topic updates its note | `tests/e2e/test_update_cycle.py::test_new_material_revises_the_note_in_place`; `tests/pipeline/test_scout_updates.py`; `tests/generator/test_scout_prompt_existing_notes.py` |
| US2 — a note past its interval is revisited and ends in one outcome | `tests/e2e/test_update_cycle.py::test_a_due_note_ends_in_exactly_one_outcome`; `tests/pipeline/test_due_reviews.py`; `tests/pipeline/test_update_outcomes.py`; `tests/pipeline/test_update_batches.py::test_ten_due_notes_and_a_share_of_three_dispatch_exactly_three_oldest_first` |
| US3 — a superseded note points at its successor and stops counting | `tests/e2e/test_supersession_end_to_end.py::test_a_superseded_note_links_its_successor_and_ask_follows_it`; `tests/pipeline/test_verifier_currency.py`; `tests/pipeline/test_coverage_currency.py::test_a_superseded_note_stops_counting`; `tests/generator/test_ask_template_currency.py` |
| US4 — `research_mode` changes what a cycle does | `tests/e2e/test_modes_end_to_end.py::test_refresh_runs_no_new_topic_batches_and_bootstrap_no_update_batches`; `tests/pipeline/test_cycle_split.py`; `tests/quality/test_split_off_matches_baseline.py` (SC-006) |
| US5 — an existing vault upgrades without a flood | `tests/pipeline/test_stamp_note_currency.py` (including the tier-5 test that the first cycles review at most the update share) |
| US6 — the operator can see how current the vault is | `tests/cli/test_coverage_currency_columns.py`; `tests/scripts/test_vault_health_currency.py`; `tests/cli/test_status_outcomes.py` |
