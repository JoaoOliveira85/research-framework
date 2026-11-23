# Tasks: The research backlog as structured state

**Spec**: [`spec.md`](spec.md) · **Plan**: [`plan.md`](plan.md) · **Status of
the spec**: `planned`. Task boxes are live: a `- [ ]` means genuinely not
done. `083` T001–T012 are the precondition and land first.

Throughout: `B` is `src/research_framework/pipeline/backlog.py`.

## Phase 1: The module, with no caller

- [x] T001 The store: load, validate against
      `contracts/research-backlog.schema.json` (hand-rolled checks, no
      dependency), atomic save, `update(vault, writer, fn)`, id derivation,
      operator-status detection (`status_by` / `status_written`), unknown
      fields preserved; a malformed store or a newer major version is never
      written (FR-001…FR-005, FR-007, FR-008; `research.md` R1, R5, R6).

  ### Testing Requirements

  _Authored 2026-11-22, before implementation._

  - **Test 1**: `tests/pipeline/test_backlog_store.py::test_round_trip_preserves_unknown_fields_and_order`
    - Tier: 1
  - **Test 2**: `tests/pipeline/test_backlog_store.py::test_topic_ids_fold_case_and_whitespace`
    - Behavior: `"Danish Kaffemote Coffee\nMeeting  Norm"` and its
      single-line, differently cased form derive one id (spec acceptance 6).
    - Tier: 1
  - **Test 3**: `tests/pipeline/test_backlog_store.py::test_a_status_change_made_outside_the_module_is_recorded_as_the_operators`
    - Tier: 1
  - **Test 4**: `tests/pipeline/test_backlog_store.py::test_malformed_store_is_left_byte_identical_and_logged`
    - Behavior: invalid JSON, a duplicate id, and a missing required field
      each: `update` writes nothing, logs `ERROR` naming the file; a query
      returns no entries and logs `WARNING` (spec acceptance 9).
    - Tier: 1
  - **Test 5**: `tests/pipeline/test_backlog_store.py::test_newer_major_version_is_read_only`
    - Tier: 1
  - **Test 6**: `tests/pipeline/test_backlog_store.py::test_an_entry_without_an_id_gets_one_on_the_next_write`
    - Tier: 1
  - **Test 7**: `tests/pipeline/test_backlog_store.py::test_store_validates_against_the_committed_schema`
    - Behavior: a store written by the module satisfies every `required`,
      `enum` and `pattern` in the committed schema file (checked by a small
      walker in the test, no `jsonschema` dependency).
    - Tier: 2

  **TDD discipline**: required.

- [x] T002 Observations and queries: `observe_topic`, `observe_quarantine`,
      `resolve_covered`, `resolve_quarantine`, `resolve_quarantine_stem`,
      `planner_topics`, `all_titles` (FR-007, FR-009, FR-010, FR-012,
      FR-013; `data-model.md` writer and reader maps; `research.md` R7).

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_backlog_observations.py::test_carry_over_is_one_entry_with_the_latest_citations`
    - Behavior: spec acceptance 2, first sentence.
    - Tier: 1
  - **Test 2**: `tests/pipeline/test_backlog_observations.py::test_a_writer_touches_only_observation_fields`
    - Behavior: an existing entry's `title`, `origin`, `added`,
      `first_seen_cycle` and an unknown field are unchanged by every
      observation.
    - Tier: 1
  - **Test 3**: `tests/pipeline/test_backlog_observations.py::test_a_dropped_or_operator_reopened_entry_is_never_moved_by_a_writer`
    - Behavior: spec acceptance 4's status half, and R5's reopen hazard.
    - Tier: 1
  - **Test 4**: `tests/pipeline/test_backlog_observations.py::test_resolve_quarantine_stem_is_exact`
    - Behavior: resolving `deseq` leaves `deseq2` open, for both kinds
      (spec acceptance 5).
    - Tier: 1
  - **Test 5**: `tests/pipeline/test_backlog_observations.py::test_planner_topics_queue_on_evidence`
    - Behavior: operator-owned and cited entries are returned, ordered by
      `first_seen_cycle` then store order; researcher-only, proposal,
      quarantine and migrated entries are not.
    - Tier: 1
  - **Test 6**: `tests/pipeline/test_backlog_observations.py::test_all_titles_ignores_status`
    - Tier: 1

  **TDD discipline**: required.

- [x] T003 The view: render per `contracts/backlog-view.contract.md`, the
      digest footer, hand-edit detection with the single overwritten copy,
      render-if-missing (FR-011, FR-016…FR-018; `research.md` R4).

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_backlog_view.py::test_view_matches_the_contract_layout`
    - Behavior: a golden render of a store covering every section; empty
      sections omitted; coverage section read from the coverage targets.
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_backlog_view.py::test_hand_edit_is_kept_once_and_warned_about`
    - Behavior: spec acceptance 8, including the second hand edit replacing
      the first copy.
    - Tier: 1
  - **Test 3**: `tests/pipeline/test_backlog_view.py::test_identical_render_writes_nothing`
    - Tier: 1
  - **Test 4**: `tests/pipeline/test_backlog_view.py::test_missing_view_is_rendered_before_a_read`
    - Tier: 1
  - **Test 5**: `tests/pipeline/test_backlog_view.py::test_nothing_under_src_or_scripts_parses_the_view`
    - Behavior: no file but `B` reads `research-backlog.md` (static scan).
    - Tier: 2

  **TDD discipline**: required.

## Phase 2: Writers and the reader move onto the module

- [x] T004 `scripts/topic_harvest.py` records its follow-ups through `B`
      and resolves covered topics; it no longer writes the Markdown file
      (FR-006, FR-009, FR-011).

  ### Testing Requirements

  - **Test 1**: `tests/scripts/test_topic_harvest_store.py::test_two_orphans_and_a_flag_become_three_open_entries`
    - Behavior: spec acceptance 1.
    - Tier: 3
  - **Test 2**: `tests/scripts/test_topic_harvest_store.py::test_a_written_note_resolves_its_entry`
    - Behavior: spec acceptance 3.
    - Tier: 3
  - **Test 3**: `tests/scripts/test_topic_harvest_store.py::test_coverage_gaps_are_not_stored`
    - Tier: 3
  - Retained, re-pointed at the store:
    `tests/scripts/test_topic_harvest.py::test_preserves_manual_backlog_entries`.

  **TDD discipline**: required.

- [x] T005 `scripts/topic_propose.py` records accepted proposals through `B`
      and dedupes against `all_titles()` (FR-006, FR-013).

  ### Testing Requirements

  - **Test 1**: `tests/scripts/test_topic_propose_store.py::test_an_accepted_proposal_is_an_open_proposal_entry`
    - Tier: 3
  - **Test 2**: `tests/scripts/test_topic_propose_store.py::test_dedupe_sees_resolved_and_dropped_titles`
    - Tier: 3
  - Retained, re-pointed:
    `tests/scripts/test_topic_propose.py::test_coexistence_with_phase1_backlog_block`.

  **TDD discipline**: required.

- [x] T006 The orchestrator's quarantine sweep and `./vault re-grade` use
      `observe_quarantine` / `resolve_quarantine` / `resolve_quarantine_stem`;
      the source-exhausted and constrained-exit messages name the harvest
      manifest and the JSON file (FR-010, FR-014, FR-015).

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_quarantine_backlog_store.py::test_sweep_upserts_one_entry_per_stem_with_its_kind`
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_quarantine_backlog_store.py::test_operator_entries_survive_every_sweep`
    - Behavior: F1 — an operator entry is intact after two sweeps.
    - Tier: 3
  - **Test 3**: `tests/cli/test_regrade_backlog_store.py::test_regrade_resolves_exactly_the_reinstated_stem`
    - Behavior: F2, F3, F4.
    - Tier: 4
  - **Test 4**: `tests/pipeline/test_loop_trigger_unchanged.py::test_continuation_reads_the_harvest_manifest_not_the_store`
    - Behavior: a store full of open entries with an empty harvest manifest
      does not continue the loop (FR-014).
    - Tier: 3
  - Retained, re-pointed:
    `tests/pipeline/test_rejected_note_handling.py::test_backlog_pointer_appended_with_reason`,
    `::test_pointer_clears_once_the_quarantine_file_is_gone`,
    `::test_manual_backlog_entries_outside_the_block_are_preserved`.
    `::test_pointer_lives_inside_a_managed_quarantine_block` is rewritten
    against the store.

  **TDD discipline**: required.

- [x] T007 The planner reads `planner_topics()`; `_parse_orphans` and its
      regular expression are deleted (FR-012).

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_research_plan_store.py::test_an_operator_entry_is_queued_and_a_researcher_flag_is_not`
    - Behavior: spec acceptance 2, second sentence.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_research_plan_store.py::test_score_uses_the_latest_citation_count`
    - Behavior: F9.
    - Tier: 1
  - Retained, re-pointed: `tests/pipeline/test_research_plan.py`,
    `tests/pipeline/test_research_plan_integration.py`.

  **TDD discipline**: required.

## Phase 3: Existing vaults and the surfaces that name the path

- [ ] T008 The converter (`research.md` R8) and the migration step
      `convert_backlog_to_store` in `layout_migration.MIGRATION_STEPS`; the
      archive's registry row in `state_layout`; the unconverted-vault
      predicate in the legacy check (FR-020…FR-023).

  ### Testing Requirements

  All on `tests/fixtures/backlog/legacy-shapes.md`, assembled from the
  shapes in spec § Evidence (invented content).

  - **Test 1**: `tests/pipeline/test_backlog_conversion.py::test_every_line_is_typed_carried_verbatim_or_counted_as_derived`
    - Behavior: spec acceptance 10 — typed entries for every recognised
      bullet, `migrated` entries for every other non-boilerplate line,
      wrapped titles joined, pointer duplicates collapsed by stem.
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_backlog_conversion.py::test_archive_is_byte_equal_and_second_run_is_a_no_op`
    - Tier: 3
  - **Test 3**: `tests/pipeline/test_backlog_conversion.py::test_the_step_commits_the_store_and_drops_the_markdown_from_the_index`
    - Behavior: one `framework:` commit after `083`'s; `git ls-files` no
      longer lists `_pipeline/research-backlog.md`; the file is on disk and
      carries the view footer.
    - Tier: 3
  - **Test 4**: `tests/pipeline/test_backlog_conversion.py::test_dry_run_converts_nothing`
    - Tier: 3
  - **Test 5**: `tests/pipeline/test_backlog_conversion.py::test_info_line_counts_each_origin_and_the_derived_lines`
    - Tier: 1
  - **Test 6**: `tests/cli/test_legacy_layout_refusal.py::test_an_unconverted_backlog_is_refused_like_a_legacy_layout`
    - Tier: 4
  - **Test 7**: `tests/pipeline/test_backlog_conversion.py::test_store_and_markdown_both_present_means_the_markdown_is_a_view`
    - Tier: 3

  **TDD discipline**: required.

- [x] T009 Scaffold, `.gitignore`, health, manifest: the scaffold seeds an
      empty store and its view; `083`'s transitional
      `!_pipeline/research-backlog.md` line is deleted; the spec-058 list
      and the scaffold manifest name the JSON file (FR-024).

  ### Testing Requirements

  - **Test 1**: `tests/generator/test_vault_gitignore.py::test_git_tracks_the_backlog_store_and_ignores_its_view`
    - Behavior: spec acceptance 11, with real `git check-ignore`; the
      stanza test no longer expects a per-file `_pipeline/` line.
    - Tier: 3
  - **Test 2**: `tests/generator/test_scaffold_backlog_store.py::test_a_fresh_vault_has_an_empty_store_and_a_rendered_view`
    - Tier: 3

  The scaffold-seed half landed with the writers' move (commit
  "scaffold seeds the backlog store"); the `.gitignore` line, the
  control-file list and the manifest followed in the T009 commit.

  **TDD discipline**: required.

- [ ] T010 The scout prompt's required-reading item describes the view's
      sections; the prompt corpus and the fixtures carrying a rendered
      scout prompt are regenerated (FR-019; `research.md` R9).

  ### Testing Requirements

  - **Test 1**: `tests/generator/test_scout_prompt_backlog.py::test_prompt_names_the_views_sections_not_the_retired_blocks`
    - Behavior: spec acceptance 12.
    - Tier: 3
  - `tests/docs/test_prompt_corpus_is_current.py` stays green.

  **TDD discipline**: required.

## Phase 4: Proof

- [ ] T011 The guard, the end-to-end case and the gates.

  ### Testing Requirements

  - **Test 1**: `tests/guards/test_backlog_single_writer.py::test_only_the_module_writes_either_backlog_path`
    - Behavior: spec acceptance 7; a planted writer fails it.
    - Tier: 2
  - **Test 2**: `tests/e2e/test_backlog_operator_ownership.py::test_operator_fields_survive_a_cycle_a_sweep_and_a_regrade`
    - Behavior: spec acceptance 4 end to end, with the fake agent.
    - Tier: 5

  Gates, run and reported in the PR: `pytest -m "not e2e"`,
  `pytest -m e2e`, `python scripts/guards/run_all.py`, `ruff check .`,
  `ruff format --check .`, `bash build.sh --quality`; refresh the
  test-count marker; `CHANGELOG.md` `[Unreleased]` with a
  `### Migration notes` entry (covered by the same `./vault update` as
  `083`).

  Rehearsal, reported in the PR: `migrate-layout --dry-run` then the real
  conversion on copies of three live vaults — one framework-generated, one
  with a hand-written wikilink list, one with pre-#257 pointer lines — with
  the INFO line's counts and a spot check of ten `migrated` entries against
  the archive.

  **TDD discipline**: required.
