# Tasks: Durable vault state lives in `_pipeline/state/`

**Spec**: [`spec.md`](spec.md) · **Plan**: [`plan.md`](plan.md) · **Status of
the spec**: `planned`. Task boxes are live: a `- [ ]` means genuinely not
done. Each task is one commit (or a short series), tests in the same commit
as or earlier than the code they pin.

Throughout: `L` is `src/research_framework/pipeline/state_layout.py`.

## Phase 1: The layout, with no behaviour change

- [ ] T001 Create `L`: `STATE_DIR`, one accessor per artefact, the
      `STATE_ARTEFACTS` registry (name, new path, legacy path, kind),
      `is_legacy_layout(vault)` and `require_migrated(vault)` with its typed
      error (FR-001, FR-002, FR-004; plan § 1, § 8).

  ### Testing Requirements

  _Authored 2026-11-22, before implementation._

  - **Test 1**: `tests/pipeline/test_state_layout.py::test_every_artefact_resolves_under_the_state_directory`
    - Behavior: every registry row's new path is under `_pipeline/state/`
      and every accessor returns the path its row declares.
    - Tier: 1
  - **Test 2**: `tests/pipeline/test_state_layout.py::test_registry_is_the_spec_table`
    - Behavior: the registry's (new, legacy) pairs equal the FR-002 table,
      parsed from `specs/083-durable-state-layout/spec.md`; the backlog row
      is present and marked as not moved by this spec.
    - Tier: 2
  - **Test 3**: `tests/pipeline/test_state_layout.py::test_legacy_layout_is_detected_from_any_legacy_path_but_the_backlog`
    - Behavior: a vault with only `_pipeline/research-backlog.md` is not
      legacy; adding `_pipeline/coverage-targets.json` makes it legacy;
      `require_migrated` then raises the typed error naming
      `./vault migrate-layout`.
    - Tier: 1

  **TDD discipline**: required.

- [ ] T002 Render the new `.gitignore` stanza in
      `generator/scaffold.py::_render_vault_gitignore`, including the
      transitional backlog re-include (FR-003, FR-019; plan § 2).

  ### Testing Requirements

  - **Test 1**: `tests/generator/test_vault_gitignore.py::test_pipeline_stanza_names_no_file_but_the_transitional_backlog`
    - Behavior: the rendered body contains `!_pipeline/state/` and the two
      sidecar ignores; the only per-file `_pipeline/` entry is the backlog
      line, and it carries the comment naming spec 084.
    - Tier: 1
  - **Test 2**: `tests/generator/test_vault_gitignore.py::test_git_tracks_state_and_ignores_the_rest`
    - Behavior: in a real temporary git repo with the rendered file,
      `git check-ignore` reports `_pipeline/state/coverage-targets.json` and
      `_pipeline/state/quarantine/x.md` as not ignored, and
      `_pipeline/cycles/x.json`, `_pipeline/state/sources.db-wal` and
      `_pipeline/spec-parse.json` as ignored.
    - Tier: 3

  **TDD discipline**: required.

- [x] T003 Move coverage targets to `L.coverage_targets_path`: the scaffold
      seed, `pipeline/coverage.py`, `scripts/topic_harvest.py`, and every
      reader (`quality_report`, `preconditions`, `digest/sections`,
      `quality/`, `research_plan`, `reporter`, `orchestrator`,
      `gates_cycle`, `steps/scout`, `cli/status`, `cli/research_cycles`,
      `benchmark/scoring`, `scripts/topic_propose.py`,
      `scripts/vault_health.py`), plus the prompt templates, agent skills
      and help strings that name the path (FR-002, FR-004).

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_state_layout_writers.py::test_scaffold_seeds_coverage_targets_under_state`
    - Behavior: a scaffolded vault has `_pipeline/state/coverage-targets.json`
      and no `_pipeline/coverage-targets.json`.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_state_layout_writers.py::test_save_and_load_targets_round_trip_at_the_state_path`
    - Behavior: `coverage.save_targets` then `load_targets` use the state
      path; nothing is written at the legacy path.
    - Tier: 1
  - Existing tests that spell the legacy path are re-pointed through `L`,
    not deleted.

  **TDD discipline**: required.

- [x] T004 Move `propose-rejects.md`, `approval-decisions.json`,
      `archive-snapshots.json` and `sources/<module>/facts-schema.json`
      (`scripts/topic_propose.py`, `orchestrator._load_propose_rejects`,
      `budget_guard`, `cli/pause.py`, `scripts/vault_health.py`,
      `source_bridge/schema_gen.py`). The transient
      `facts-schema.regenerated.json` and `.drift.md` stay where they are:
      they are cache (`research.md` § C).

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_state_layout_writers.py::test_each_small_state_writer_writes_under_state`
    - Behavior: parametrised over the four writers, each driven through its
      own public function; the file appears at its `L` path and not at its
      legacy path.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_state_layout_writers.py::test_transient_schema_files_stay_out_of_state`
    - Behavior: a drift regeneration writes `facts-schema.regenerated.json`
      beside the cache, not under `state/`.
    - Tier: 3

  **TDD discipline**: required.

- [x] T005 Move `sources.db` to `L.sources_db_path` (`source_manager`,
      `orchestrator`, `digest/sections`, `reports/top_sources`,
      `scripts/source_ledger.py`, `scripts/reconcile_source_metrics.py`,
      `scripts/vault_audit.py`, the scaffold seed) and add
      `source_manager.checkpoint(vault)` (plan § 4).

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_state_layout_writers.py::test_seed_creates_the_database_under_state`
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_source_manager_checkpoint.py::test_checkpoint_leaves_an_empty_wal`
    - Behavior: after writes in WAL mode, `checkpoint` leaves `sources.db`
      holding every row when opened with the sidecars deleted.
    - Tier: 3

  **TDD discipline**: required.

- [x] T006 Move the quarantine directory to `L.quarantine_dir`
      (`orchestrator`, `cli/regrade.py`, `vault/claims_export.py`,
      `quality_report`, `run_report`, `spec_append`, `cli/export.py`,
      `cli/acceptance.py`, `scripts/validate_vault.py`, the shim template's
      help text). The source-bridge "quarantine" of a failing module is a
      different thing and is not touched.

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_state_layout_writers.py::test_an_orphan_note_is_quarantined_under_state`
    - Tier: 3
  - **Test 2**: `tests/cli/test_regrade_state_layout.py::test_regrade_reinstates_from_the_state_quarantine`
    - Tier: 4

  **TDD discipline**: required.

## Phase 2: Facts that used to live in scratch

- [x] T007 Add `pipeline/cycle_ledger.py`; append a row when a cycle closes;
      make `_resolve_resume_cycle`, `_cumulative_sidecar_cost` and
      `_hours_since_last_cycle` read it under the plan § 3 rule (FR-006).

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_cycle_ledger.py::test_a_closed_cycle_appends_exactly_one_row`
    - Tier: 1
  - **Test 2**: `tests/pipeline/test_cycle_ledger.py::test_readers_survive_an_empty_cycles_directory`
    - Behavior: with a three-row ledger and no `cycles/`, the resume cycle
      is 4, the lifetime spend is the rows' sum, and the hours since the
      last cycle come from the last row.
    - Tier: 3
  - **Test 3**: `tests/pipeline/test_cycle_ledger.py::test_scan_supplies_only_cycles_the_ledger_lacks`
    - Behavior: ledger rows for cycles 1–2 and a `cycles/` tree for 1–3
      whose cycle-2 sidecars disagree with the ledger: spend is ledger(1,2)
      plus scan(3); next cycle is 4.
    - Tier: 3
  - **Test 4**: `tests/pipeline/test_cycle_ledger.py::test_a_corrupt_ledger_is_reported_not_guessed`
    - Behavior: an unparseable ledger raises a typed error whose message
      names the file; no reader silently falls back to the scan.
    - Tier: 1

  **TDD discipline**: required.

- [x] T008 Precondition 4 requires the state directory and the ledger's
      parent, not `budget-log.md`; a missing `budget-log.md` is re-created
      (spec D9; plan § 10).

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_preconditions_state.py::test_a_missing_budget_log_no_longer_blocks_a_run`
    - Tier: 3

  **TDD discipline**: required.

- [x] T009 `vault_commit`: stage `_pipeline/state/` with every cycle and
      command commit (checkpointing `sources.db` first), and make
      `begin_run` commit pending state on the base branch as
      `vault: pending state` before it branches (FR-008, D-4; plan § 5).

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_vault_commit_state.py::test_pending_state_edit_gets_its_own_commit_before_the_run_branch`
    - Behavior: an uncommitted edit to `_pipeline/state/coverage-targets.json`
      on `main`; after `begin_run`, `main` has one new commit titled
      `vault: pending state` touching only that file, and the run branch
      starts from it.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_vault_commit_state.py::test_scratch_under_pipeline_is_still_masked`
    - Behavior: an untracked `_pipeline/cycles/x.json` neither blocks the
      run nor is committed.
    - Tier: 3
  - **Test 3**: `tests/pipeline/test_vault_commit_state.py::test_a_cycle_commit_carries_the_state_it_wrote`
    - Behavior: after a fake-agent cycle, `git status --porcelain --
      _pipeline/state` is empty and the sidecars are not in the index.
    - Tier: 5
  - **Test 4**: `tests/pipeline/test_vault_commit_state.py::test_opted_out_vault_commits_nothing`
    - Behavior: `vault_commit.enabled: false` → no commit, one INFO line.
    - Tier: 3

  **TDD discipline**: required.

## Phase 3: Existing vaults

- [x] T010 `pipeline/layout_migration.py` with `MIGRATION_STEPS` and the
      `move_state_into_state_dir` step; the CLI verb `migrate-layout
      <vault> [--dry-run] [--force]`; the shim verb and `./vault help`; the
      row in the `077` contract table (FR-007, FR-009, FR-011…FR-014,
      FR-018; plan § 6, § 7).

  ### Testing Requirements

  All on a legacy fixture built by a helper
  (`tests/_helpers/legacy_layout.py::build_legacy_vault`) that commits the
  two historically tracked files and leaves the rest untracked.

  - **Test 1**: `tests/pipeline/test_layout_migration.py::test_moves_every_state_path_and_leaves_the_backlog`
    - Behavior: spec § Acceptance US3, first bullet, including
      `git log --follow` reaching the commit that first added
      `_pipeline/coverage-targets.json`.
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_layout_migration.py::test_the_commit_is_renames_additions_ignore_file_and_ledger_only`
    - Behavior: `git show --stat -M` shows each tracked move as a 100 %
      rename; the commit title starts `framework:`.
    - Tier: 3
  - **Test 3**: `tests/pipeline/test_layout_migration.py::test_second_run_reports_already_migrated`
    - Tier: 3
  - **Test 4**: `tests/pipeline/test_layout_migration.py::test_conflicting_destination_aborts_with_nothing_moved`
    - Behavior: differing content at both paths → exit 2, the pair named,
      the tree byte-identical. Identical content at both → proceeds.
    - Tier: 3
  - **Test 5**: `tests/pipeline/test_layout_migration.py::test_dry_run_prints_and_touches_nothing`
    - Tier: 3
  - **Test 6**: `tests/pipeline/test_layout_migration.py::test_customised_gitignore_gets_one_reinclude_or_a_named_winning_rule`
    - Tier: 3
  - **Test 7**: `tests/pipeline/test_layout_migration.py::test_ledger_is_backfilled_from_cycles`
    - Tier: 3
  - **Test 8**: `tests/pipeline/test_layout_migration.py::test_dirty_tree_refuses_unless_forced`
    - Tier: 3
  - **Test 9**: `tests/pipeline/test_layout_migration.py::test_non_git_vault_moves_files_and_logs_the_opt_out`
    - Tier: 3
  - **Test 10**: `tests/pipeline/test_layout_migration.py::test_run_control_and_legacy_settings_are_left_alone`
    - Behavior: `BUDGET_PAUSED`, `pipeline-state.json` and
      `_pipeline/settings.yaml` are not moved; the last produces a warning
      naming the vault-root `settings.yaml`.
    - Tier: 3
  - **Test 11**: `tests/cli/test_migrate_layout_verb.py::test_the_verb_is_in_help_and_the_contract_table`
    - Tier: 2

  **TDD discipline**: required.

- [x] T011 Run the migration from `vault_update.sync_vault_scripts`, so a
      shim rendered by the previous release migrates the vault (FR-010).

  ### Testing Requirements

  - **Test 1**: `tests/pipeline/test_vault_update_migrates.py::test_an_old_shims_update_hook_migrates_the_vault`
    - Behavior: call the hook the 2.0.1 shim calls, on the legacy fixture;
      the vault ends migrated, with the migration as its own commit before
      the upgrade commit.
    - Tier: 4
  - **Test 2**: `tests/pipeline/test_vault_update_migrates.py::test_a_failed_migration_fails_the_update_loudly`
    - Behavior: a conflicting destination makes the hook report the failure
      at ERROR and return non-zero; scripts are still synced.
    - Tier: 4

  **TDD discipline**: required.

- [x] T012 State-writing verbs refuse a legacy vault with exit 2 before any
      dispatch; `status`, `status --json` and `health` without `--apply`
      report it and carry on (FR-015, FR-016).

  ### Testing Requirements

  - **Test 1**: `tests/cli/test_legacy_layout_refusal.py::test_mutating_verbs_exit_2_naming_the_migration`
    - Behavior: parametrised over `generate --resume`, `cycle`,
      `pipeline full`, `re-grade`; exit 2, stderr names
      `./vault migrate-layout`, the fake agent is never called.
    - Tier: 4
  - **Test 2**: `tests/cli/test_legacy_layout_refusal.py::test_status_reports_and_exits_0`
    - Behavior: `status --json` exits 0 and carries a `legacy_layout`
      notice.
    - Tier: 4
  - **Test 3**: `tests/cli/test_legacy_layout_refusal.py::test_no_reader_falls_back_to_a_legacy_path`
    - Behavior: with state only at legacy paths, `coverage.load_targets`
      does not return the legacy file's content.
    - Tier: 3

  **TDD discipline**: required.

## Phase 4: Keeping it true

- [x] T013 The guard `scripts/guards/state_paths.py`, wired into
      `scripts/guards/run_all.py` (FR-005; plan § 9).

  ### Testing Requirements

  - **Test 1**: `tests/guards/test_state_paths_guard.py::test_a_planted_literal_fails_and_the_tree_passes`
    - Behavior: spec § Acceptance US4.
    - Tier: 2
  - **Test 2**: `tests/e2e/test_state_directory_contents.py::test_a_cycle_writes_nothing_unregistered_under_state`
    - Tier: 5

  **TDD discipline**: required.

- [x] T014 Everything that names the paths in prose or data:
      `scripts/vault_health.py::CONTROL_FILE_PATHS` and the spec-058 check
      (FR-017); `scripts/build_scaffold_manifest.py` and the regenerated
      `dist-templates/scaffold-manifest.json`; the constitution's
      coverage-targets and loop-continuation text (PATCH amendment);
      `ARCHITECTURE.md`, `README.md`'s vault tree, `docs/RELEASE.md`;
      `CHANGELOG.md` `[Unreleased]` with a `### Migration notes` block.

  ### Testing Requirements

  - **Test 1**: `tests/scripts/test_vault_health_state_tracking.py::test_untracked_state_directory_is_warned_about`
    - Tier: 3
  - **Test 2**: `tests/docs/test_state_paths_in_docs.py::test_no_doc_names_a_legacy_state_path_as_current`
    - Behavior: outside `specs/`, `CHANGELOG.md` and `_archive/`, no tracked
      Markdown file names `_pipeline/coverage-targets.json`,
      `_pipeline/sources.db`, `_pipeline/propose-rejects.md` or
      `_pipeline/quarantine` as a current path.
    - Tier: 2

  **TDD discipline**: required for the health check; the doc test may land
  with the doc changes.

## Phase 5: Proof

- [x] T015 End-to-end acceptance and the gates.

  ### Testing Requirements

  - **Test 1**: `tests/e2e/test_state_survives_git_clean.py::test_a_cleaned_vault_continues_like_its_twin`
    - Behavior: spec § Acceptance US2, both bullets: two fake-agent cycles,
      commit, copy, `git clean -fdx` on one copy, re-scaffold scripts; the
      third run's resume anchor, lifetime spend, scout exclusions and
      discovered sources equal the twin's; `re-grade` finds the same
      quarantined notes.
    - Tier: 5
  - **Test 2**: `tests/e2e/test_state_survives_git_clean.py::test_only_state_is_tracked_under_pipeline`
    - Behavior: spec § Acceptance US1.
    - Tier: 5

  Gates, all run and reported in the PR: `pytest -m "not e2e"`,
  `pytest -m e2e`, `python scripts/guards/run_all.py`, `ruff check .`,
  `ruff format --check .`, `bash build.sh --quality`; refresh the
  `<!-- test-count: … -->` marker in `docs/testing-strategy.md`.

  Rehearsal (not done in this change; the coordinator runs it separately on
  copies of live vaults — this line stays open), reported in the PR: `migrate-layout --dry-run`, then the real
  migration, on copies of two live vaults (one with 40+ cycles), with the
  before/after `git ls-files _pipeline/` and the ledger's totals against a
  manual sum of the sidecars.

  **TDD discipline**: required.
