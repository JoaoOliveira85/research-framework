# Tasks: Flow Separation — Phase 1 Minimum Subset

**Input**: Design documents from `/specs/023-flow-separation/`  
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md  
**Scope**: **US1 only** + **FR-013**, **FR-014**, **FR-015**, **FR-018** (per `spec.md` § Implementation phasing → Phase 1). Phase 2 (US2–US4, FR-004–FR-012, FR-016–FR-017) is **explicitly deferred** — zero actionable tasks below.

**Tests**: Included per plan.md / research.md / contract test obligations (tier-2/3/5; no live `claude`/`codex`).

**Organization**: Tasks grouped by phase; US1 consolidates all four Phase 1 FRs. Parallel streams A–D from `plan.md` mapped in **Parallel-stream alignment** (vault-script template edit serialized).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[US1]**: User Story 1 — `./vault` stable public CLI contract (Phase 1 partial + revival FRs)

## Path Conventions

- Package root: `src/research_framework/`
- Tests: `tests/`
- Templates: `templates/`, `dist-templates/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm Phase 1 boundary and prepare fixture assets for tier-3 CLI tests.

- [X] T001 Confirm Phase 1 scope is US1 + FR-013/014/015/018 only (no VaultHandle, active-sources.json, spec-fingerprint, in-loco-modules, or spec 020 `source_bridge/`) per `specs/023-flow-separation/spec.md` § Implementation phasing
- [X] T002 [P] Create minimal fixture vault `tests/fixtures/refresh_sources_vault/` with `research.spec.md`, `settings.yaml`, `.venv` stub or harness hook, and `scripts/collect_stub.py` that writes `raw_data/stub/` and exits 0 per `specs/023-flow-separation/contracts/refresh-sources-cli.contract.md`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core modules that FR-014 (shim render) and FR-018 (atomic I/O) depend on. **Blocks all US1 implementation.**

**⚠️ CRITICAL**: No user-story implementation until T003–T006 complete.

- [X] T003 Implement `src/research_framework/pipeline/atomic_write.py` (`write_bytes`, `write_text`, `write_json`) per `specs/023-flow-separation/contracts/atomic-write.contract.md`

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_atomic_write.py::test_write_text_os_replace_is_final_syscall`
    - Behavior: Patch `os.replace` (and temp-file write path as needed); assert `os.replace` is invoked exactly once and is the last step that mutates the destination path for `write_text`. MUST NOT mock `os.path.exists` or `Path.write_text` — those are UUT surfaces, not isolation targets.
    - Tier: 2
    - Notes: `atomic-write.contract.md` algorithm step 4.
  - **Test 2**: `tests/pipeline/test_atomic_write.py::test_write_json_fault_before_os_replace_preserves_destination`
    - Behavior: Pre-seed destination with known bytes; patch `os.replace` to raise `OSError`; call `write_json`; assert destination bytes are bit-identical to pre-call. Temp file cleaned up.
    - Tier: 2
    - Notes: Contract failure-mode table — SIGKILL before replace / crash safety.
  - **Test 3**: `tests/pipeline/test_atomic_write.py::test_write_bytes_fault_before_os_replace_preserves_destination`
    - Behavior: Same fault-injection pattern as Test 2 for `write_bytes` on a binary payload.
    - Tier: 2
    - Notes: Contract guarantee — destination unchanged on failure before step 4.
  - **Test 4**: `tests/pipeline/test_atomic_write.py::test_concurrent_reader_never_sees_invalid_json`
    - Behavior: Writer thread loops `write_json` with monotonically changing payload; reader thread opens target and `json.loads` in a tight loop (≥100 iterations). Assert zero `JSONDecodeError` and every successful parse matches `json.loads` of full file bytes. Use real filesystem paths under `tmp_path`, not mocked `open`.
    - Tier: 2
    - Notes: Contract test obligations — concurrent reader never sees torn JSON.
  - **Test 5**: `tests/pipeline/test_atomic_write.py::test_write_text_applies_mode_after_replace`
    - Behavior: Write with `mode=0o755`; assert final `path.stat().st_mode` permission bits match `0o755` after successful replace.
    - Tier: 2
    - Notes: Contract algorithm step 6 (required by FR-014 shim write).

  **TDD discipline**: required

- [X] T004 [P] Add tier-2 `tests/pipeline/test_atomic_write.py` (crash before `os.replace`, concurrent reader never sees torn JSON) — red until T003 green
- [X] T005 Extract shared `render_vault_shim(vault_dir: Path, spec: SpecConfig) -> str` from `src/research_framework/generator/scaffold.py::_write_vault_script` for reuse by `cli/regenerate_shim.py` and existing generate path

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/generator/test_render_vault_shim.py::test_render_vault_shim_matches_legacy_scaffold_output`
    - Behavior: On a `tests/_helpers/vault_factory.build_minimal_vault` tree, render via new `render_vault_shim` and via the pre-extraction `_write_vault_script` code path (or golden string captured at refactor time); assert byte-identical shim body for the same `(vault_dir, spec)`.
    - Tier: 2
    - Notes: FR-014 render inputs must match `generator/scaffold._write_vault_script` context.
  - **Test 2**: `tests/generator/test_render_vault_shim.py::test_render_vault_shim_vault_dir_is_resolved_absolute`
    - Behavior: Assert rendered template context contains `vault_dir` as `Path.resolve()` string (stable canonical path for idempotency).
    - Tier: 2
    - Notes: `regenerate-shim-cli.contract.md` idempotency — canonical `vault_dir`.

  **TDD discipline**: required

- [X] T006 [P] Extend `src/research_framework/pipeline/settings.py` typed loader with optional `refresh_sources.collectors` and `refresh_sources.timeout_s` per `specs/023-flow-separation/data-model.md` §4

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_settings_refresh_sources.py::test_load_refresh_sources_collectors_from_yaml`
    - Behavior: Minimal `settings.yaml` with `refresh_sources.collectors: [collect_stub.py]`; load via canonical settings loader; assert ordered basename list matches.
    - Tier: 2
    - Notes: `data-model.md` §4 — settings overlay drives discovery order.
  - **Test 2**: `tests/pipeline/test_settings_refresh_sources.py::test_refresh_sources_timeout_s_defaults_to_600`
    - Behavior: Load settings without `timeout_s` key; assert default `600` exposed on typed settings object.
    - Tier: 2
    - Notes: `refresh-sources-cli.contract.md` execution — timeout default.

  **TDD discipline**: required

**Checkpoint**: `atomic_write` importable; shim render helper shared; settings keys loadable.

---

## Phase 3: User Story 1 — `./vault` Stable Public CLI (Phase 1 MVP) 🎯

**Goal**: Ship `./vault refresh-sources`, `./vault regenerate-shim`, vault-local `scripts/` survive `./vault update`, and atomic research/postprocess writes so concurrent `./vault ask` never reads torn files.

**Independent Test**:
1. Subprocess `./vault refresh-sources --json` on fixture vault → exit 0/1/2 per contract; stdout JSON matches schema.
2. Double `./vault regenerate-shim --force` → byte-identical `vault` file.
3. `./vault update` on vault with `scripts/custom_collector.py` → file byte-identical.
4. Tier-5 concurrent read during fixture `research` cycle → no partial JSON/note content.

### FR-015 — Vault-local scripts survive update (Stream C)

- [X] T007 [P] [US1] Add tier-2 `tests/pipeline/test_scaffold_diff_scripts.py` — `scripts/custom_collector.py` survives `./vault update` byte-identically per spec Phase 1 ship criterion #3

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_scaffold_diff_scripts.py::test_vault_update_preserves_custom_collector_script_bytes`
    - Behavior: Build vault via `tests/_helpers/vault_factory.build_minimal_vault`; seed `scripts/custom_collector.py` with known bytes; run framework update apply (same entrypoint `./vault update` uses); assert file exists and `read_bytes()` unchanged.
    - Tier: 3
    - Notes: FR-015 ship criterion #3; spec Phase 1 independent test #3.
  - **Test 2**: `tests/pipeline/test_scaffold_diff_scripts.py::test_vault_update_preserves_collect_star_and_reddit_rss`
    - Behavior: Seed `scripts/collect_youtube.py` and `scripts/reddit_rss.py` with distinct byte payloads; after update, assert both paths unchanged.
    - Tier: 3
    - Notes: Revival collectors named in `data-model.md` §1 snapshot examples.

  **TDD discipline**: required

- [X] T008 [P] [US1] Add tier-2 `tests/generator/test_copy_scripts_merge.py` — `copy_scripts` merge never deletes unlisted `scripts/collect_*.py` or `scripts/reddit_rss.py`

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/generator/test_copy_scripts_merge.py::test_copy_scripts_merge_retains_unlisted_collect_glob`
    - Behavior: Vault `scripts/` contains `collect_custom.py` not in framework manifest; invoke `copy_scripts` merge; assert `collect_custom.py` still present with original bytes.
    - Tier: 2
    - Notes: FR-015 — unlisted `collect_*.py` protected by absence + merge.
  - **Test 2**: `tests/generator/test_copy_scripts_merge.py::test_copy_scripts_merge_retains_reddit_rss_allowlist`
    - Behavior: Vault contains `scripts/reddit_rss.py`; after merge, file retained byte-identically.
    - Tier: 2
    - Notes: Phase 1 frozen legacy allowlist (`refresh-sources` contract).

  **TDD discipline**: required

- [X] T009 [US1] Refactor `src/research_framework/generator/scripts.py::copy_scripts` to merge mode (copy framework-bundled scripts from manifest; **never** `shutil.rmtree` on `<vault>/scripts/`)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/generator/test_copy_scripts_merge.py::test_copy_scripts_never_rmtree_scripts_directory`
    - Behavior: Patch/spy `shutil.rmtree`; run `copy_scripts` against minimal vault with pre-existing `scripts/` tree; assert `rmtree` never called with a path ending in `/scripts` (or vault-relative `scripts`).
    - Tier: 2
    - Notes: Task prose MUST NOT — `shutil.rmtree` on `<vault>/scripts/`.
  - **Test 2**: `tests/generator/test_copy_scripts_merge.py::test_copy_scripts_adds_framework_script_without_deleting_user_files`
    - Behavior: Pre-seed user collector + invoke merge that installs a framework-bundled helper from manifest; assert both files exist post-merge.
    - Tier: 2
    - Notes: FR-015 positive merge contract vs destructive copy.

  **TDD discipline**: required

- [X] T010 [US1] Persist `<vault>/_pipeline/scaffold-manifest-snapshot.json` (dist entries + `scripts_user_owned`) on successful update apply in `src/research_framework/generator/scaffold.py` (or update apply path) per `specs/023-flow-separation/data-model.md` §1

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/generator/test_scaffold_manifest_snapshot.py::test_update_writes_scaffold_manifest_snapshot_json`
    - Behavior: After successful update apply on `build_minimal_vault` fixture, assert `<vault>/_pipeline/scaffold-manifest-snapshot.json` exists and parses as JSON with `framework_version`, `captured_at`, `entries` keys.
    - Tier: 2
    - Notes: `data-model.md` §1 vault snapshot extension.
  - **Test 2**: `tests/generator/test_scaffold_manifest_snapshot.py::test_snapshot_scripts_user_owned_lists_unlisted_scripts`
    - Behavior: Vault with `scripts/collect_youtube.py` not shipped by framework; after update, `scripts_user_owned` array contains that basename.
    - Tier: 2
    - Notes: `scripts_user_owned` append-only discovery rule.

  **TDD discipline**: required

- [X] T011 [US1] Set `dist-templates/scaffold-manifest.json` `vault` entry `is_user_owned_after_first_write` to `false` per `specs/023-flow-separation/data-model.md` §1 (enables FR-014 repair via update path post-027)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/generator/test_scaffold_manifest_snapshot.py::test_dist_manifest_vault_entry_not_user_owned_after_first_write`
    - Behavior: Load `dist-templates/scaffold-manifest.json`; find entry with `"path": "vault"`; assert `is_user_owned_after_first_write` is `false`.
    - Tier: 2
    - Notes: `data-model.md` §1 Phase 1 manifest change table.

  **TDD discipline**: required

### FR-018 — Atomic writer path (Stream D)

- [X] T012 [P] [US1] Add tier-5 `tests/pipeline/test_concurrent_ask_research.py` — parallel reads on `data_vault/` and `_pipeline/cycles/cycle-*-*.json` during fixture research cycle (red until P0 migrations land)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_concurrent_ask_research.py::test_concurrent_cycle_json_reads_never_invalid_during_fixture_research`
    - Behavior: Run a fixture research cycle (`fake_agent` only — no live `claude`/`codex`); spawn reader threads that repeatedly open `_pipeline/cycles/cycle-*-*.json` and `json.loads` while cycle runs; assert zero decode errors and no truncated-parse success.
    - Tier: 5
    - Notes: `atomic-write.contract.md` tier-5 obligation; spec independent test #4.
  - **Test 2**: `tests/pipeline/test_concurrent_ask_research.py::test_concurrent_data_vault_note_reads_never_empty_frontmatter_only`
    - Behavior: During same fixture cycle, reader threads open `data_vault/**/*.md` touched by cycle; assert each read is either prior full content or complete new content — never a lone `---` frontmatter stub without body closure.
    - Tier: 5
    - Notes: FR-018 concurrent `./vault ask` reader safety.

  **TDD discipline**: required

- [X] T013 [US1] Migrate P0 cycle JSON writes in `src/research_framework/pipeline/steps/research.py` to `atomic_write.write_json`

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_atomic_write_migrations.py::test_research_step_batch_json_calls_atomic_write`
    - Behavior: Exercise research step write path (unit or thin integration with stubbed upstream); patch `pipeline.atomic_write.write_json`; assert called for batch JSON artifact path matching `cycle-*-batch-*.json`.
    - Tier: 2
    - Notes: `atomic-write.contract.md` P0 research batch JSON.
  - **Test 2**: `tests/pipeline/test_atomic_write_migrations.py::test_research_step_research_json_calls_atomic_write`
    - Behavior: Same pattern for `cycle-*-research.json` write if present in step.
    - Tier: 2
    - Notes: P0 call-site table.

  **TDD discipline**: required

- [X] T014 [US1] Migrate P0 writes in `src/research_framework/pipeline/steps/postprocess.py` and `src/research_framework/pipeline/steps/scout.py` to `atomic_write`

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_atomic_write_migrations.py::test_postprocess_step_cycle_json_calls_atomic_write`
    - Behavior: Patch `atomic_write.write_json` (or `write_text` if JSON not used); trigger postprocess persist path; assert atomic_write invoked for `cycle-*-postprocess.json` (or equivalent P0 artifact).
    - Tier: 2
    - Notes: P0 postprocess cycle JSON.
  - **Test 2**: `tests/pipeline/test_atomic_write_migrations.py::test_scout_step_plan_write_calls_atomic_write`
    - Behavior: Trigger scout plan/archive write; assert `atomic_write.write_text` or `write_json` used instead of direct `Path.write_text`.
    - Tier: 2
    - Notes: P1 scout plan writes in contract table.

  **TDD discipline**: required

- [X] T015 [US1] Migrate P0 note writes in `src/research_framework/pipeline/verifier.py` and `src/research_framework/pipeline/wikilinks.py` to `atomic_write`

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_atomic_write_migrations.py::test_verifier_stamp_frontmatter_calls_atomic_write`
    - Behavior: Run `_stamp_frontmatter` (or verifier path) on tmp note; assert `atomic_write.write_text` called with destination note path.
    - Tier: 2
    - Notes: P0 verifier frontmatter stamp.
  - **Test 2**: `tests/pipeline/test_atomic_write_migrations.py::test_wikilinks_normalization_calls_atomic_write`
    - Behavior: Trigger wikilink rewrite on fixture note; assert `atomic_write` used for note body write.
    - Tier: 2
    - Notes: P0 wikilinks note body writes.

  **TDD discipline**: required

- [X] T016 [P] [US1] Delegate `src/research_framework/pipeline/runner.py`, `research_plan.py`, and `plan_narrator.py` local `_atomic_write_*` helpers to `pipeline/atomic_write.py` (behaviour-preserving)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_atomic_write_migrations.py::test_runner_local_atomic_helpers_delegate_to_module`
    - Behavior: Call runner's `_atomic_write_json` (or public wrapper); assert `pipeline.atomic_write.write_json` invoked (patch inner module function).
    - Tier: 2
    - Notes: Contract deprecation — thin wrappers only.
  - **Test 2**: `tests/pipeline/test_atomic_write_migrations.py::test_research_plan_and_plan_narrator_delegate_atomic_write`
    - Behavior: Invoke `research_plan` and `plan_narrator` local write helpers; assert delegation to `atomic_write.write_text` / `write_json` without duplicating temp+replace logic in-module.
    - Tier: 2
    - Notes: P1/P2 delegate call sites.

  **TDD discipline**: required

### FR-013 — `./vault refresh-sources` (Stream A)

- [X] T017 [P] [US1] Add tier-3 `tests/cli/test_refresh_sources.py` (stub collector ok, partial failure exit 1 + `partial_failure`, missing venv exit 2, `--only` unknown basename exit 2) per `specs/023-flow-separation/contracts/refresh-sources-cli.contract.md`

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_refresh_sources.py::test_refresh_sources_exit_0_stub_collector_json`
    - Behavior: Subprocess `python -m research_framework.cli refresh-sources --vault <fixture> --json` using `tests/fixtures/refresh_sources_vault/` (or `build_minimal_vault` + stub script); assert exit code **0**; stdout is single JSON object with `collectors[].status == "ok"` and `partial_failure` is false.
    - Tier: 3
    - Notes: FR-001 exit 0; contract `--json` schema §3.
  - **Test 2**: `tests/cli/test_refresh_sources.py::test_refresh_sources_exit_1_partial_failure_json`
    - Behavior: Fixture with one ok stub collector and one failing collector script; assert exit code **1**; JSON has `partial_failure: true` and mixed ok/failed statuses.
    - Tier: 3
    - Notes: Contract exit code 1 + `data-model.md` §3.
  - **Test 3**: `tests/cli/test_refresh_sources.py::test_refresh_sources_exit_2_missing_venv`
    - Behavior: Vault without `.venv/bin/python`; assert exit code **2** (framework error).
    - Tier: 3
    - Notes: Contract test obligations — missing venv.
  - **Test 4**: `tests/cli/test_refresh_sources.py::test_refresh_sources_exit_2_unknown_only_basename`
    - Behavior: `--only not_a_collector.py` where basename matches neither `collect_*.py` nor allowlist; assert exit code **2**.
    - Tier: 3
    - Notes: Collector discovery `--only` validation clause.

  **TDD discipline**: required

- [X] T018 [US1] Implement `src/research_framework/cli/refresh_sources.py` — discover `scripts/collect_*.py` + frozen allowlist `reddit_rss.py` only; subprocess via `<vault>/.venv/bin/python`; **no** reads under `<vault>/modules/`

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_refresh_sources.py::test_refresh_sources_discovery_includes_reddit_rss_allowlist`
    - Behavior: Vault with only `scripts/reddit_rss.py` (no `collect_*.py`); `--dry-run` or `--json` lists `reddit_rss.py` as candidate.
    - Tier: 2
    - Notes: Frozen legacy allowlist in contract.
  - **Test 2**: `tests/cli/test_refresh_sources.py::test_refresh_sources_never_traverses_modules_directory`
    - Behavior: Place decoy file under `<vault>/modules/decoy/collect_fake.py`; assert it never appears in discovery output and no read/open under `modules/` (spy `Path.glob`/`iterdir` on modules path or assert collector list excludes it).
    - Tier: 2
    - Notes: Task prose — no reads under `<vault>/modules/`.
  - **Test 3**: `tests/cli/test_refresh_sources.py::test_refresh_sources_invokes_python_not_executable_bit`
    - Behavior: Collector script mode `0644` (non-executable); run refresh; assert subprocess argv is `<venv>/bin/python` + script path and exit 0 when stub returns 0.
    - Tier: 2
    - Notes: Contract — no executable-bit filter.

  **TDD discipline**: required

- [X] T019 [US1] Register `refresh-sources` subcommand and handler in `src/research_framework/cli/_parser.py`

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_parser_refresh_sources.py::test_parser_registers_refresh_sources_subcommand`
    - Behavior: Build argparse parser via public CLI factory; assert `refresh-sources` dest exists and resolves to `refresh_sources` handler module.
    - Tier: 2
    - Notes: FR-013 wiring — subparser registration.

  **TDD discipline**: required

### FR-014 — `./vault regenerate-shim` (Stream B)

- [X] T020 [P] [US1] Add tier-2/3 `tests/cli/test_regenerate_shim.py` (double-run byte identity, `unverified`/`customized` exit 2 without `--force`, F2 broken-shim repair fixture) per `specs/023-flow-separation/contracts/regenerate-shim-cli.contract.md`

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_regenerate_shim.py::test_regenerate_shim_double_run_byte_identical`
    - Behavior: On `build_minimal_vault` + `--force`, run CLI twice; assert `vault` shim `read_bytes()` identical between runs.
    - Tier: 2
    - Notes: Contract idempotency MUST.
  - **Test 2**: `tests/cli/test_regenerate_shim.py::test_regenerate_shim_exit_2_unverified_without_force`
    - Behavior: Vault with stock sentinel but **no** `_pipeline/shim-fingerprint.json`; run without `--force`; assert exit code **2**.
    - Tier: 2
    - Notes: Customization table `unverified` row.
  - **Test 3**: `tests/cli/test_regenerate_shim.py::test_regenerate_shim_exit_2_customized_without_force`
    - Behavior: Shim missing sentinel or hash mismatch; without `--force`, exit code **2** and stderr mentions `--force`.
    - Tier: 2
    - Notes: Contract headless-safe failure.
  - **Test 4**: `tests/cli/test_regenerate_shim.py::test_regenerate_shim_repairs_broken_shim_fixture`
    - Behavior: Use committed broken-shim fixture (stale `VAULT_DIR`, `research_vault.cli`); after `regenerate-shim --force`, assert `vault` file contains `research_framework.cli`.
    - Tier: 3
    - Notes: Archaeology F2; contract tier-3 obligation.
  - **Test 5**: `tests/cli/test_regenerate_shim.py::test_regenerate_shim_preserves_user_scripts_bytes`
    - Behavior: Vault with pre-existing `scripts/custom_collector.py` bytes; run `regenerate-shim --force`; assert script path bytes unchanged (shim-only write).
    - Tier: 3
    - Notes: Vault-local script preservation during shim regen (operator concern from guidance).

  **TDD discipline**: required

- [X] T021 [US1] Implement `src/research_framework/cli/regenerate_shim.py` using `render_vault_shim`, `atomic_write.write_text(..., mode=0o755)`, and `_pipeline/shim-fingerprint.json` per `specs/023-flow-separation/data-model.md` §2

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_regenerate_shim.py::test_regenerate_shim_writes_shim_via_atomic_write_mode_755`
    - Behavior: Patch `pipeline.atomic_write.write_text`; run regenerate with `--force`; assert called with destination `<vault>/vault` and `mode=0o755`.
    - Tier: 2
    - Notes: Contract write behaviour steps 2–3.
  - **Test 2**: `tests/cli/test_regenerate_shim.py::test_regenerate_shim_writes_shim_fingerprint_json`
    - Behavior: After successful `--force` run, assert `_pipeline/shim-fingerprint.json` exists with `path`, `sha256`, `framework_version`, `rendered_at` keys per data model §2.
    - Tier: 2
    - Notes: Shim fingerprint entity.

  **TDD discipline**: required

- [X] T022 [US1] Register `regenerate-shim` subcommand and handler in `src/research_framework/cli/_parser.py`

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_parser_regenerate_shim.py::test_parser_registers_regenerate_shim_subcommand`
    - Behavior: Assert `regenerate-shim` dest registered on CLI parser and routes to `regenerate_shim` handler.
    - Tier: 2
    - Notes: FR-014 parser wiring.

  **TDD discipline**: required

### Serialized template edit (Streams A + B)

- [X] T023 [US1] Add **both** `refresh-sources)` and `regenerate-shim)` case arms plus help text in `templates/vault-script.sh.j2` in a **single commit** (serialize Streams A+B — shared file)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/generator/test_vault_script_template_verbs.py::test_vault_script_template_has_refresh_sources_case_arm`
    - Behavior: Render `templates/vault-script.sh.j2` with minimal context; assert output contains `refresh-sources)` case arm exec'ing `refresh-sources --vault`.
    - Tier: 2
    - Notes: `refresh-sources-cli.contract.md` integration — template case arm.
  - **Test 2**: `tests/generator/test_vault_script_template_verbs.py::test_vault_script_template_has_regenerate_shim_case_arm`
    - Behavior: Same for `regenerate-shim)` → `regenerate-shim --vault`.
    - Tier: 2
    - Notes: `regenerate-shim-cli.contract.md` template changes.

  **TDD discipline**: required

### US1 partial — headless contract for new verbs (SC-004 subset)

- [X] T024 [US1] Add tier-3 `tests/cli/test_vault_script_new_verbs.py` — subprocess `./vault refresh-sources --json` and `./vault regenerate-shim --json` from generated shim on fixture vault; assert FR-001 exit codes and FR-002 stdout shape (no TTY prompts)

  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_vault_script_new_verbs.py::test_vault_shim_refresh_sources_json_exit_0`
    - Behavior: `build_minimal_vault` with generated executable `./vault`; subprocess `./vault refresh-sources --json` with stub collector; assert exit **0**, valid JSON on stdout, no stdin/TTY interaction (run with `CI=1` or closed stdin).
    - Tier: 3
    - Notes: SC-004 headless `--json` for FR-013.
  - **Test 2**: `tests/cli/test_vault_script_new_verbs.py::test_vault_shim_regenerate_shim_json_exit_codes`
    - Behavior: Subprocess `./vault regenerate-shim --json --force` → exit **0** with JSON fields `classification`, `overwritten`; subprocess without `--force` on `unverified` vault → exit **2**.
    - Tier: 3
    - Notes: FR-001/FR-002 on public `./vault` surface (not only `python -m`).

  **TDD discipline**: required

**Checkpoint**: Phase 1 ship criteria #1–#4 satisfied by automated tests; criterion #5 (feeds-vault revival demo) validated in Polish phase.

---

## Phase 4: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, operator validation, and merge gates.

- [X] T025 [P] Add `CHANGELOG.md` `[Unreleased]` entries for `./vault refresh-sources`, `./vault regenerate-shim`, FR-015 scripts-survive-update, and FR-018 atomic-write module
- [X] T026 Execute `specs/023-flow-separation/quickstart.md` Steps 0–4 against `tests/fixtures/quality/tech-lite/` (or refresh_sources fixture); record pass/fail in implementation PR test plan
- [X] T027 Run `cd src && pytest -m "not e2e" && ruff check .` before Phase 1 merge; fix any regressions in touched modules

---

## Deferred to Phase 2

No actionable tasks. See `specs/023-flow-separation/spec.md` § Implementation phasing → **Phase 2 — Post-revival hardening** for US2 (`VaultHandle`), US3 (`active-sources.json`), US4 (`.local.md`), FR-004–FR-012, FR-016 (stale-spec warning), and FR-017 (in-loco deprecate-and-prune). `/speckit.tasks` for Phase 2 runs **after** Phase 1 ships.

---

## Dependencies & Execution Order

### Phase Dependencies

| Phase | Depends on | Blocks |
|-------|------------|--------|
| Setup (1) | — | Foundational |
| Foundational (2) | Setup | US1 (all streams) |
| US1 (3) | Foundational | Polish |
| Polish (4) | US1 complete | Phase 1 ship |

### User Story Dependencies

- **US1 (Phase 1 only story)**: Starts after T003–T006. Internal order: FR-015 tests → FR-015 impl (T007–T011) ∥ FR-018 tests → FR-018 impl (T012–T016) ∥ FR-013/014 tests → impl (T017–T022) → **T023** (template) → T024 (shim e2e).

### FR Dependency Graph

```text
T003 atomic_write ──┬──► T021 regenerate_shim
                    └──► T013–T016 migrations

T005 render_vault_shim ──► T021

T009 copy_scripts merge ──► T007/T008 tests green

T018 refresh_sources ──► T019 parser ──► T023 template
T021 regenerate_shim ──► T022 parser ──► T023 template
```

### Parallel Opportunities

- **Setup**: T002 ∥ T001
- **Foundational**: T004 ∥ T006 after T003 started; T005 ∥ T003 once API stable
- **US1**: T007 ∥ T008 ∥ T012 ∥ T017 ∥ T020 (tests, different files); T013–T016 parallel across files after T003; T018 ∥ T021 after foundational (different modules); **T023 must not parallelize** with any other `vault-script.sh.j2` edit
- **Polish**: T025 ∥ T026

---

## Parallel-stream alignment

| Stream | Primary files | Task IDs | Serialization |
|--------|---------------|----------|---------------|
| **A** — `refresh-sources` | `src/research_framework/cli/refresh_sources.py`, `cli/_parser.py`, `templates/vault-script.sh.j2` (case arm) | T017, T018, T019, T023 (partial), T024 | **T023** shares `vault-script.sh.j2` with B — one agent/commit |
| **B** — `regenerate-shim` | `src/research_framework/cli/regenerate_shim.py`, `generator/scaffold.py`, `dist-templates/scaffold-manifest.json`, `templates/vault-script.sh.j2` | T005, T011, T020, T021, T022, T023 (partial), T024 | Same as A |
| **C** — `atomic_write` + writer migration | `pipeline/atomic_write.py`, `pipeline/steps/{research,postprocess,scout}.py`, `verifier.py`, `wikilinks.py` | T003, T004, T012–T016 | Independent once T003 lands |
| **D** — `scaffold_diff` / `copy_scripts` | `generator/scripts.py`, `generator/scaffold.py`, `_pipeline/scaffold-manifest-snapshot.json` | T007–T011 | Independent of A/B/C |

**Template rule**: Only **T023** touches `templates/vault-script.sh.j2`; implementers doing Streams A and B in parallel must land CLI modules (T018–T022) first, then one integrator runs T023.

---

## Implementation Strategy

### MVP First (Phase 1 = US1)

1. Complete Setup + Foundational (T001–T006).
2. Land FR-015 (T007–T011) so revival collectors cannot be wiped by update.
3. Land FR-018 (T012–T016) for crash-safe concurrent reads.
4. Land FR-013 + FR-014 CLI (T017–T022) + serialized template (T023).
5. Shim subprocess contract test (T024).
6. Polish + operator quickstart (T025–T027).

### Incremental Delivery

| Increment | Tasks | Operator value |
|-----------|-------|------------------|
| Foundation | T003–T006 | Shared atomic I/O + shim render |
| Scripts safe | T007–T011 | `./vault update` no longer destroys collectors |
| Crash-safe writes | T012–T016 | `./vault ask` during `./vault research` |
| New verbs | T017–T024 | `refresh-sources` + `regenerate-shim` on `./vault` |
| Ship | T025–T027 | Docs + CI green |

### Parallel Team Strategy

- **Dev 1**: Stream D (T003–T004, T012–T016)
- **Dev 2**: Stream D scaffold (T007–T011)
- **Dev 3**: Stream A (T017–T019) — no `vault-script.sh.j2` until integrator
- **Dev 4**: Stream B (T020–T022) — same
- **Integrator**: T023 + T024 after CLI modules merge

---

## Cross-spec coordination note

Spec 023 Phase 1 tasks **deliberately exclude** any dependency on spec 020's `source_bridge/sources_loader.py`, `<vault>/modules/*/sources.yaml`, or `ModuleSourcesFile`. `refresh-sources` (T018) iterates **legacy** `<vault>/scripts/collect_*.py` plus the frozen `reddit_rss.py` allowlist only — filesystem-driven discovery shrinks as 020 ports collectors; no code coupling to 020 enumeration.

The **only** shared concern with spec 020 is `<vault>/scripts/` lifecycle: FR-015 (T009–T011) guarantees vault-local collectors survive `./vault update` until 020 module ports delete them intentionally. See `specs/023-flow-separation/plan.md` § Cross-spec coordination and `specs/020-code-bridge/plan.md` § Cross-spec coordination (Spec 020 ↔ Spec 023).

---

## Notes

- Constitution Principle V: stdlib + existing `jinja2`/`pyyaml` only — no new runtime deps.
- Principle IV: collectors and tests use `tests/_helpers/fake_agent.py` / stub scripts — no live LLM subprocesses in tests.
- `sqlite3` WAL for `_pipeline/sources.db` is already enabled — no task (FR-018b).
- Do **not** add Phase 2 FR tasks (FR-016/017, VaultHandle, `active-sources.json`, `docs/integration/assistant-framework.md`).
- Acceptance coverage cells in `spec.md` populate during implementation PR, not this tasks PR (spec is read-only here).
- After Phase 1 ships: set `spec.md` **Status** to `SHIPPED <version>` and update `docs/ROADMAP.md` per documentation discipline checklist.

---

## Acceptance coverage (Phase 1 evidence map)

| Scope | Task evidence |
|-------|----------------|
| US1 (partial) | T024; tier-3 tests T017, T020 |
| FR-013 | T017, T018, T019, T023, T024 |
| FR-014 | T005, T011, T020, T021, T022, T023, T024 |
| FR-015 | T007, T008, T009, T010, T011 |
| FR-018 | T003, T004, T012, T013, T014, T015, T016 |
