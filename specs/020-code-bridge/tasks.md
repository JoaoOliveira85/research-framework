# Tasks: Source-Module Architecture (020-code-bridge)

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Input**: Design documents from `/specs/020-code-bridge/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart-*.md
**Branch**: `020-source-modules-tasks` (umbrella: `tasks/critical-path-revival`)

**Tests**: Included where plan.md / research.md / contracts flag ship deliverables (tier-1/2/4, SC-006 fixture diversity, module-isolation protocol).

**Organization**: Phases follow spec user-story priority (US1→US7). **Execution order** differs — see Dependencies & Parallel-stream alignment (plan Blocks S+A+M+E ship before US1 extraction wiring).

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Scaffold packages, entry points, test trees, and bundle module layout per plan.md Project Structure.

- T001 Create `src/research_framework/pipeline/source_bridge/` package with `__init__.py` exporting public stage API in `src/research_framework/pipeline/source_bridge/__init__.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_package_init.py::test_source_bridge_public_api_importable`
    - Behavior: Import `research_framework.pipeline.source_bridge`; assert exported symbols match `__init__.py` docstring/public API list.
    - Tier: 2
    - Notes: Setup smoke for package scaffold.

  **TDD discipline**: required

- T002 [P] Create `src/research_framework/modules/code/` reference module skeleton (`manifest.yaml`, `extractor.py`, `few-shot.md`, `sources.yaml.template`) in `src/research_framework/modules/code/`
- T003 [P] Add `scripts/source_bridge.py` CLI stub (argparse: `--vault`, `--cycle`, `--debug-triggers`, `--force-stale-schema`) in `scripts/source_bridge.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_source_bridge_cli.py::test_cli_parses_vault_cycle_and_flags`
    - Behavior: Invoke `scripts/source_bridge.py --help` and argv with `--vault`, `--cycle`, `--debug-triggers`, `--force-stale-schema`; assert argparse destinations populated.
    - Tier: 2
    - Notes: CLI stub contract.

  **TDD discipline**: required

- T004 [P] Create `tests/source_bridge/` package with `conftest.py` vault factory hooks in `tests/source_bridge/conftest.py`
- T005 [P] Create `tests/modules/code/` package in `tests/modules/code/`
- T006 [P] Add `tests/_helpers/fake_repo.py` stub (disposable git checkout helper) in `tests/_helpers/fake_repo.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/_helpers/test_fake_repo.py::test_fake_repo_checkout_returns_controlled_head_sha`
    - Behavior: Disposable git checkout under tmp_path; assert `head_sha()` matches injected commit.
    - Tier: 2
    - Notes: Helper API for SC-004 selective re-extract.

  **TDD discipline**: not required

- T007 [P] Add `tests/_helpers/fake_module.py` stub (controllable extractor + exception injection) in `tests/_helpers/fake_module.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/_helpers/test_fake_module.py::test_fake_module_extractor_emits_json_stdout`
    - Behavior: Stub module writes known JSON to stdout; bridge/parser consumer can read without network.
    - Tier: 2
    - Notes: Helper API for module-isolation tests.
  - **Test 2**: `tests/_helpers/test_fake_module.py::test_fake_module_inject_exception_on_attempt`
    - Behavior: Second `isolated_call` attempt sees injected exception per attempt number.
    - Tier: 2

  **TDD discipline**: not required

- T008 Extend `dist-templates/` / install bundle manifest so framework modules copy into wheel under `src/research_framework/modules/` per `plan.md` install-time copy path
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/generator/test_bundle_modules.py::test_wheel_includes_framework_modules_tree`
    - Behavior: Build or inspect dist manifest; assert `src/research_framework/modules/` paths present per plan install-time copy.
    - Tier: 2
    - Notes: Bundle layout.

  **TDD discipline**: required


**Checkpoint**: Directory layout matches plan.md; `pytest -m "not e2e"` collects new packages without import errors.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core dataclasses, contract validation, enumeration loader (FAIL-fast FR-013b), discovery skeleton, cache primitives, isolation helper. **Blocks all user stories.**

- T009 Implement `SignalPayload` dataclass + JSON serde per `contracts/signal-payload.schema.json` in `src/research_framework/pipeline/source_bridge/signal.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_signal.py::test_signal_payload_roundtrip_json`
    - Behavior: Construct `SignalPayload`; serde matches `contracts/signal-payload.schema.json` required fields.
    - Tier: 2
    - Notes: FR signal envelope.

  **TDD discipline**: required

- T010 [P] Implement `Watermark` entry types + map serde per `contracts/watermark.schema.json` in `src/research_framework/pipeline/source_bridge/cache.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_cache.py::test_watermark_map_roundtrip`
    - Behavior: `Watermark` entries serialize/deserialize per `contracts/watermark.schema.json`.
    - Tier: 2

  **TDD discipline**: required

- T011 [P] Implement `ModuleSourcesFile` + `EnumeratedSource` dataclasses per `data-model.md` §4 in `src/research_framework/pipeline/source_bridge/sources_loader.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_sources_loader.py::test_module_sources_file_dataclass_fields`
    - Behavior: `ModuleSourcesFile` + `EnumeratedSource` match data-model §4 required attributes.
    - Tier: 2
    - Notes: data-model §4.

  **TDD discipline**: required

- T012 [P] Implement `TriggerEntry` + `TriggerRegistry` dataclasses per `data-model.md` §5 in `src/research_framework/pipeline/source_bridge/discovery.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_discovery.py::test_trigger_entry_and_registry_dataclasses`
    - Behavior: `TriggerEntry` + `TriggerRegistry` construct per data-model §5.
    - Tier: 2

  **TDD discipline**: required

- T013 Add tier-1 envelope validation test against `contracts/signal-payload.schema.json` in `tests/source_bridge/test_signal_schema.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_signal_schema.py::test_signal_payload_validates_against_schema`
    - Behavior: Fixture JSON passes tier-1 schema validation.
    - Tier: 1
    - Notes: Contract tier-1.
  - **Test 2**: `tests/source_bridge/test_signal_schema.py::test_signal_payload_rejects_missing_required_field`
    - Behavior: Omit required envelope field; validator fails.
    - Tier: 1

  **TDD discipline**: required

- T014 [P] Add tier-2 manifest contract test against `contracts/manifest.schema.json` in `tests/source_bridge/test_manifest_contract.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_manifest_contract.py::test_reference_code_manifest_validates`
    - Behavior: Bundle `modules/code/manifest.yaml` validates against `contracts/manifest.schema.json`.
    - Tier: 2

  **TDD discipline**: required

- T015 [P] Add tier-2 watermark contract test in `tests/source_bridge/test_signal_schema.py` (watermark section)
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_signal_schema.py::test_watermark_entry_validates_against_schema`
    - Behavior: Watermark fixture validates per watermark.schema.json section.
    - Tier: 2

  **TDD discipline**: required

- T016 Implement atomic read/write helpers (`NamedTemporaryFile` + `os.replace`) for `_pipeline/sources/<module>/` in `src/research_framework/pipeline/source_bridge/cache.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_cache.py::test_atomic_write_uses_replace_not_inplace`
    - Behavior: Mock `os.replace`; assert `NamedTemporaryFile` + replace path for `_pipeline/sources/<module>/` writes.
    - Tier: 2
    - Notes: Atomic-write pattern.

  **TDD discipline**: required

- T017 Implement `sources_loader.load_module_sources(vault, module_name, manifest) -> list[EnumeratedSource]` reading only `<vault>/modules/<name>/sources.yaml` in `src/research_framework/pipeline/source_bridge/sources_loader.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_sources_loader.py::test_load_module_sources_reads_only_vault_modules_yaml`
    - Behavior: Vault fixture with `modules/foo/sources.yaml`; assert loader never reads `research.spec.md::data_sources` (FR-013a).
    - Tier: 2
    - Notes: FR-013a.

  **TDD discipline**: required

- T018 Implement FR-013b FAIL-fast `derive_source_id(manifest, kind, record, index)` — abort with clear error on missing/empty `source_id_from` field or missing `url`/`name` in `src/research_framework/pipeline/source_bridge/sources_loader.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_sources_loader.py::test_derive_source_id_fail_fast_missing_source_id_from_field`
    - Behavior: Record missing mapped field; stage aborts with error naming module, kind, index (FR-013b).
    - Tier: 2
    - Notes: FR-013b FAIL-fast.
  - **Test 2**: `tests/source_bridge/test_sources_loader.py::test_derive_source_id_fail_fast_no_url_name_or_path`
    - Behavior: Empty identity; abort with clear error (no WARN skip).
    - Tier: 2

  **TDD discipline**: required

- T019 Implement duplicate `source_id` WARN + first-wins dedupe in `src/research_framework/pipeline/source_bridge/sources_loader.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_sources_loader.py::test_duplicate_source_id_warn_first_wins`
    - Behavior: Two records same `source_id`; WARN logged; only first processed.
    - Tier: 2
    - Notes: sources.yaml.contract duplicate row.

  **TDD discipline**: required

- T020 Implement missing `sources.yaml` (empty + WARN) and invalid YAML (module-isolation skip + run-report) per `contracts/sources.yaml.contract.md` in `src/research_framework/pipeline/source_bridge/sources_loader.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_sources_loader.py::test_missing_sources_yaml_returns_empty_with_warn`
    - Behavior: No file → zero sources + WARN once.
    - Tier: 2
  - **Test 2**: `tests/source_bridge/test_sources_loader.py::test_invalid_sources_yaml_skips_module_with_run_report`
    - Behavior: Malformed YAML → module isolation skip; run-report entry (D9 kind 3 analogue).
    - Tier: 2
    - Notes: contracts/sources.yaml.contract.md invalid YAML row.

  **TDD discipline**: required

- T021 [P] Add `tests/source_bridge/test_sources_loader.py` — happy path, missing file, invalid YAML skip, `source_id_from` map, FAIL-fast missing field, FAIL-fast no url/name, stable IDs
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_sources_loader.py::test_sources_loader_happy_path_enumerates_records`
    - Behavior: Valid YAML + manifest `source_id_from` → stable `EnumeratedSource` list.
    - Tier: 2
    - Notes: Task-owned comprehensive loader tests.
  - **Test 2**: `tests/source_bridge/test_sources_loader.py::test_source_id_from_map_uses_manifest_field`
    - Behavior: Per-kind field mapping (e.g. `github_repos: path`) drives `source_id`.
    - Tier: 2

  **TDD discipline**: required

- T022 Implement `discovery.walk_modules(vault) -> list[ModuleManifest]` filesystem walk of `<vault>/modules/*/manifest.yaml` in `src/research_framework/pipeline/source_bridge/discovery.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_discovery.py::test_walk_modules_finds_manifest_yaml_under_vault_modules`
    - Behavior: Filesystem walk returns `ModuleManifest` for each `<vault>/modules/*/manifest.yaml`.
    - Tier: 2

  **TDD discipline**: required

- T023 Implement FR-010 trigger-registry ordering: listed `settings.yaml::modules:` first, then unlisted modules in lexicographic name order with once-per-start WARN in `src/research_framework/pipeline/source_bridge/discovery.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_discovery.py::test_fr010_listed_modules_before_unlisted_lexicographic`
    - Behavior: `settings.yaml::modules:` order first; unlisted modules sorted by name; WARN once per unlisted.
    - Tier: 2
    - Notes: FR-010.

  **TDD discipline**: required

- T024 Implement `isolated_call()` retry-once helper per `contracts/module-isolation-protocol.md` in `src/research_framework/pipeline/source_bridge/isolation.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_module_isolation.py::test_isolated_call_retries_once_then_returns_none`
    - Behavior: Callable raises twice; assert two attempts; second failure returns None.
    - Tier: 2
    - Notes: module-isolation-protocol.md algorithm.

  **TDD discipline**: required

- T025 [P] Add `tests/source_bridge/test_module_isolation.py` skeleton for `isolated_call` retry + double-failure path in `tests/source_bridge/test_module_isolation.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_module_isolation.py::test_isolated_call_double_failure_surfaces_without_crash`
    - Behavior: Both attempts fail; no unhandled exception propagates to caller.
    - Tier: 2
    - Notes: Skeleton completion for T025.

  **TDD discipline**: required

- T026 Implement 100 KB payload cap + `notable` truncation + `truncated: true` per research R4 in `src/research_framework/pipeline/source_bridge/signal.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_signal.py::test_payload_truncates_notable_over_100kb`
    - Behavior: Oversized `notable`; assert `truncated: true` and cap per research R4.
    - Tier: 2

  **TDD discipline**: required

- T027 Implement `bridge_version` constant sourced from package version in `src/research_framework/pipeline/source_bridge/__init__.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_package_init.py::test_bridge_version_matches_package_version`
    - Behavior: `bridge_version` constant equals installed package version string.
    - Tier: 2

  **TDD discipline**: required

- T028 Add `stages.source_extraction.enabled` default `false` + `modules:` list placeholder to settings templates in `dist-templates/settings.yaml` and `dist-templates/settings.codex.yaml`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_settings_templates.py::test_dist_templates_default_source_extraction_disabled`
    - Behavior: Rendered `dist-templates/settings.yaml` contains `stages.source_extraction.enabled: false` and `modules:` placeholder.
    - Tier: 2
    - Notes: Opt-in default until 0.3.0 ship flip.

  **TDD discipline**: required


**Checkpoint**: Loader + discovery unit tests green; no LLM or `cycle_runner` wiring yet.

---

## Phase 3: User Story 4 — Per-module schema generated from vault spec (Priority: P1)

**Goal**: Schema-gen produces per-`(vault, module)` `facts-schema.json` at install and on spec-hash change; fallback + drift fail-closed (D8).

**Independent Test**: Install two contrasting fixture vaults (web-microservices vs embedded-firmware); schemas differ (SC-006). Broken schema-gen → 3-bucket fallback + WARN.

### Tests for User Story 4

- T029 [P] [US4] Add `tests/source_bridge/test_schema_gen.py` — happy path, invalid JSON Schema fallback, `manually_edited` opt-out, spec-hash regeneration in `tests/source_bridge/test_schema_gen.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_schema_gen.py::test_schema_gen_happy_path_writes_facts_schema`
    - Behavior: Fake-agent schema-gen returns valid JSON Schema; `facts-schema.json` written under `_pipeline/sources/<module>/`.
    - Tier: 3
    - Notes: Use `tests/_helpers/fake_agent.py` for LLM dispatch.
  - **Test 2**: `tests/source_bridge/test_schema_gen.py::test_schema_gen_invalid_json_schema_falls_back_three_buckets`
    - Behavior: Invalid schema → `technologies`/`patterns`/`notable` buckets + WARN (FR-015).
    - Tier: 3
  - **Test 3**: `tests/source_bridge/test_schema_gen.py::test_manually_edited_skips_overwrite`
    - Behavior: `manually_edited: true` preserves on-disk schema (FR-016).
    - Tier: 2

  **TDD discipline**: required

- T030 [P] [US4] Add `tests/source_bridge/test_schema_drift.py` — sidecar write, `facts-schema.drift.md` sections, fail-closed cycle, `--force-stale-schema` override in `tests/source_bridge/test_schema_drift.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_schema_drift.py::test_drift_writes_sidecar_and_drift_md`
    - Behavior: Spec hash change with manual schema → `facts-schema.regenerated.json` + `facts-schema.drift.md` (D8).
    - Tier: 2
    - Notes: drift-detection-protocol.md.
  - **Test 2**: `tests/source_bridge/test_schema_drift.py::test_drift_fail_closed_raises_stale_manual_schema_error`
    - Behavior: Without override, cycle/schema step raises `StaleManualSchemaError`.
    - Tier: 2
  - **Test 3**: `tests/source_bridge/test_schema_drift.py::test_force_stale_schema_allows_proceed`
    - Behavior: `--force-stale-schema` bypasses fail-closed once.
    - Tier: 2

  **TDD discipline**: required


### Implementation for User Story 4

- T031 [US4] Wire schema-gen agent prompt from `contracts/facts-schema-gen-prompt.md` into `src/research_framework/pipeline/source_bridge/schema_gen.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_schema_gen.py::test_schema_gen_prompt_loaded_from_contract`
    - Behavior: Prompt builder includes required sections from `contracts/facts-schema-gen-prompt.md` (snapshot/substring).
    - Tier: 2

  **TDD discipline**: required

- T032 [US4] Implement `schema_gen.run(vault, module, spec_path) -> FactsSchema` with agent dispatch via `scripts/agent_call.py` in `src/research_framework/pipeline/source_bridge/schema_gen.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_schema_gen.py::test_schema_gen_dispatches_via_agent_call_stub`
    - Behavior: Monkeypatch/spawn boundary uses `scripts/agent_call.py` path only; fake_agent intercept (Principle IV).
    - Tier: 3
    - Notes: MUST use fake_agent.

  **TDD discipline**: required

- T033 [US4] Implement 3-bucket fallback (`technologies`, `patterns`, `notable`) + loud WARN on invalid schema per FR-015 in `src/research_framework/pipeline/source_bridge/schema_gen.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_schema_gen.py::test_three_bucket_fallback_on_invalid_schema`
    - Behavior: Invalid agent output → exactly three top-level buckets in written schema.
    - Tier: 3

  **TDD discipline**: required

- T034 [US4] Implement `.schema-gen-hash` write (sha256 of `research.spec.md` bytes) per research R6 in `src/research_framework/pipeline/source_bridge/schema_gen.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_schema_gen.py::test_schema_gen_hash_written_from_spec_bytes`
    - Behavior: `.schema-gen-hash` equals sha256 of `research.spec.md` bytes (research R6).
    - Tier: 2

  **TDD discipline**: required

- T035 [US4] Honor `manually_edited: true` — skip overwrite of `facts-schema.json` per FR-016 in `src/research_framework/pipeline/source_bridge/schema_gen.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_schema_gen.py::test_manually_edited_true_preserves_facts_schema_json`
    - Behavior: Re-run `schema_gen.run` does not mutate `facts-schema.json` bytes.
    - Tier: 2
    - Notes: FR-016.

  **TDD discipline**: required

- T036 [US4] Implement D8 drift detection: sidecar `facts-schema.regenerated.json`, `facts-schema.drift.md`, raise `StaleManualSchemaError` per `contracts/drift-detection-protocol.md` in `src/research_framework/pipeline/source_bridge/schema_gen.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_schema_drift.py::test_stale_manual_schema_error_on_hash_mismatch`
    - Behavior: D8 state machine: hash mismatch + `manually_edited` → `StaleManualSchemaError`.
    - Tier: 2

  **TDD discipline**: required

- T037 [US4] Add `research-framework schema --acknowledge-drift <module>` CLI handler in `src/research_framework/cli/schema.py` (or existing CLI subpackage module)
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_schema_acknowledge_drift.py::test_schema_acknowledge_drift_merges_and_clears_sidecars`
    - Behavior: CLI `research-framework schema --acknowledge-drift <module>` resolves drift files per contract.
    - Tier: 2

  **TDD discipline**: required

- T038 [US4] Hook schema-gen into `install.sh` post-copy for each `settings.yaml::modules:` entry in `install.sh`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/generator/test_install_schema_gen_hook.py::test_install_runs_schema_gen_per_modules_setting`
    - Behavior: Simulate install post-copy; each `settings.yaml::modules:` entry triggers schema-gen once.
    - Tier: 3
    - Notes: fake_agent for agent dispatch.

  **TDD discipline**: required

- [ ] T039 [P] [US4] Create `tests/fixtures/vault-web-microservices/research.spec.md` + minimal module install in `tests/fixtures/vault-web-microservices/`
- [ ] T040 [P] [US4] Create `tests/fixtures/vault-embedded-firmware/research.spec.md` + minimal module install in `tests/fixtures/vault-embedded-firmware/`
- T041 [US4] Add SC-006 assertion test comparing generated schemas across the two fixtures in `tests/source_bridge/test_schema_gen.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_schema_gen.py::test_sc006_schemas_differ_across_fixture_vaults`
    - Behavior: Compare generated schemas from `vault-web-microservices` vs `vault-embedded-firmware`; assert structural difference (SC-006).
    - Tier: 2
    - Notes: Constitution 1.3.2 fixture diversity.

  **TDD discipline**: required


**Checkpoint**: Schema-gen + drift tests green on fixtures; install path generates schemas.

---

## Phase 4: User Story 1 — Cached source-walk eliminates re-extraction waste (Priority: P1) 🎯 MVP

**Goal**: Source-extraction stage caches signals by `(module, source_id, source_version)`; cache-hit skips LLM/subprocess extraction (SC-001, SC-004).

**Independent Test**: Fake vault with two repos — first run writes signals + watermarks; second run logs cache hits with zero extractor subprocess calls; one repo SHA change re-extracts only that source.

### Tests for User Story 1

- T042 [P] [US1] Add `tests/source_bridge/test_cache.py` — watermark CRUD, cache-hit, cache-miss, `bridge_version` invalidation, 30-day GC in `tests/source_bridge/test_cache.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_cache.py::test_watermark_crud_roundtrip`
    - Behavior: Create/update/read watermark entries in `watermarks.json`.
    - Tier: 2
  - **Test 2**: `tests/source_bridge/test_cache.py::test_cache_hit_skips_extractor_subprocess`
    - Behavior: Matching `(module, source_id, source_version)` → no subprocess spawn (mock `subprocess.run`).
    - Tier: 2
    - Notes: FR-003/FR-004.
  - **Test 3**: `tests/source_bridge/test_cache.py::test_bridge_version_invalidation_cache_miss`
    - Behavior: Bump `bridge_version` → prior signals treated as miss.
    - Tier: 2

  **TDD discipline**: required

- T043 [P] [US1] Add tier-4 `tests/source_bridge/test_e2e_cache_hit.py` — two-cycle run, second cycle SC-001 timing budget in `tests/source_bridge/test_e2e_cache_hit.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_e2e_cache_hit.py::test_second_cycle_cache_hit_zero_extractor_calls`
    - Behavior: Two-cycle fixture vault with stub module; second cycle: zero extractor subprocesses.
    - Tier: 4
    - Notes: SC-001/SC-004 tier-4 e2e.

  **TDD discipline**: required


### Implementation for User Story 1

- T044 [US1] Implement watermark lookup + cache-hit fast path (no agent calls) per FR-003/FR-004 in `src/research_framework/pipeline/source_bridge/cache.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_cache.py::test_cache_hit_fast_path_no_agent_calls`
    - Behavior: Watermark hit → no `agent_call` invocations.
    - Tier: 2

  **TDD discipline**: required

- T045 [US1] Implement signal file write to `_pipeline/sources/<module>/signals/<source-stem>-<version>.json` per FR-005 in `src/research_framework/pipeline/source_bridge/cache.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_cache.py::test_signal_written_to_pipeline_sources_signals_path`
    - Behavior: Path `_pipeline/sources/<module>/signals/<stem>-<version>.json` exists with valid envelope (FR-005).
    - Tier: 2

  **TDD discipline**: required

- T046 [US1] Implement time-based signal GC (`signal_retention_days`, default 30) at end of each write per D3 in `src/research_framework/pipeline/source_bridge/cache.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_cache.py::test_signal_gc_removes_entries_older_than_retention`
    - Behavior: Inject aged signal files; GC at write removes >`signal_retention_days` (default 30).
    - Tier: 2
    - Notes: D3.

  **TDD discipline**: required

- T047 [US1] Treat unreadable/corrupt signal JSON as cache-miss + WARN per spec edge case in `src/research_framework/pipeline/source_bridge/cache.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_cache.py::test_corrupt_signal_json_treated_as_cache_miss`
    - Behavior: Unreadable signal file → cache-miss + WARN; re-extract attempted.
    - Tier: 2
    - Notes: Spec edge case.

  **TDD discipline**: required

- T048 [US1] Implement `source_bridge.run_extraction(vault, cycle)` orchestration: enumerate via `sources_loader` only (FR-013a; NOT `data_sources` loop per FR-013c) in `scripts/source_bridge.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_source_bridge_orchestration.py::test_run_extraction_enumerates_sources_yaml_only`
    - Behavior: Orchestration never iterates `data_sources` (FR-013c); only `sources_loader` output.
    - Tier: 3

  **TDD discipline**: required

- T049 [US1] Implement per-source version probe via module subprocess `get_source_version` contract in `src/research_framework/pipeline/source_bridge/extractor.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_extractor_contract.py::test_get_source_version_subprocess_json_contract`
    - Behavior: Fake extractor binary in fixture vault emits version JSON on stdout; bridge parses.
    - Tier: 2
    - Notes: Subprocess contract; no network.

  **TDD discipline**: required

- T050 [US1] Wire FR-001 Step 1.5 `source-extraction` before scout in `src/research_framework/pipeline/cycle_runner.py` behind `stages.source_extraction.enabled`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runner_source_extraction.py::test_step_15_runs_before_scout_when_enabled`
    - Behavior: With `stages.source_extraction.enabled: true`, cycle order invokes source-extraction before scout (FR-001).
    - Tier: 3
    - Notes: fake_agent cycle stub.

  **TDD discipline**: required

- T051 [US1] Implement subprocess spawn of `scripts/source_bridge.py` from cycle runner per FR-002/research R2 in `src/research_framework/pipeline/cycle_runner.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runner_source_extraction.py::test_cycle_runner_spawns_source_bridge_subprocess`
    - Behavior: Assert `subprocess` targets `scripts/source_bridge.py` with `--vault`/`--cycle` (research R2).
    - Tier: 3

  **TDD discipline**: required

- T052 [US1] Add structured stderr JSON log lines for per-source status in `scripts/source_bridge.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_source_bridge_cli.py::test_stderr_json_log_per_source_status`
    - Behavior: Run extraction stub; stderr lines are parseable JSON status records.
    - Tier: 2

  **TDD discipline**: required

- T053 [US1] Add SC-004 selective re-extract test using `tests/_helpers/fake_repo.py` controlled SHAs in `tests/source_bridge/test_cache.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_cache.py::test_sc004_selective_reextract_on_sha_change`
    - Behavior: `fake_repo` changes one repo SHA; only that source re-extracted (SC-004).
    - Tier: 2

  **TDD discipline**: required

- T054 [US1] Add SC-001 cache-hit latency assertion (<500 ms stage total with stub vault) in `tests/source_bridge/test_e2e_cache_hit.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_e2e_cache_hit.py::test_sc001_second_cycle_stage_under_500ms`
    - Behavior: Second cycle source-extraction stage wall time <500 ms with stub vault (SC-001).
    - Tier: 4

  **TDD discipline**: required


**Checkpoint**: US1 cache path works end-to-end with stub module; second cycle is cache-hit.

---

## Phase 5: User Story 3 — Modules discovered and routed by trigger (Priority: P1)

**Goal**: Filesystem-authoritative module discovery, FR-010 precedence, per-module `sources.yaml` enumeration, generic fallback for unmatched `data_sources` (SC-007, SC-008).

**Independent Test**: Vault with `code` + stub `web` modules plus `random.org` in `data_sources` only — repo and example.com extracted by modules; random.org uses generic `(module=generic)` path.

### Tests for User Story 3

- T055 [P] [US3] Extend `tests/source_bridge/test_discovery.py` — manifest walk, malformed manifest skip + retry-once, first-match-wins, unlisted lexicographic order in `tests/source_bridge/test_discovery.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_discovery.py::test_malformed_manifest_skipped_after_retry_once`
    - Behavior: Invalid manifest YAML → module excluded after `isolated_call` double failure.
    - Tier: 2
    - Notes: D9 kind 3.
  - **Test 2**: `tests/source_bridge/test_discovery.py::test_trigger_match_first_match_wins`
    - Behavior: Overlapping patterns; first registry entry wins.
    - Tier: 2

  **TDD discipline**: required

- T056 [P] [US3] Add multi-module routing integration test with `tests/_helpers/fake_module.py` stub `web` module in `tests/source_bridge/test_discovery.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_discovery.py::test_multi_module_routing_with_fake_module_stub`
    - Behavior: `code` + stub `web` modules route distinct sources via `fake_module` stdout.
    - Tier: 3

  **TDD discipline**: required

- T057 [US3] Add SC-007 drop-in module folder test (no settings edit) in `tests/source_bridge/test_discovery.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_discovery.py::test_sc007_drop_in_module_without_settings_edit`
    - Behavior: New folder under `modules/` discovered without changing `settings.yaml`.
    - Tier: 2
    - Notes: SC-007.

  **TDD discipline**: required

- T058 [US3] Add SC-008 generic fallback test — no install-module prompt surfaced in `tests/source_bridge/test_discovery.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_discovery.py::test_sc008_generic_fallback_no_install_module_prompt`
    - Behavior: `data_sources` orphan → `module=generic` path; no install prompt string in logs.
    - Tier: 2
    - Notes: SC-008.

  **TDD discipline**: required


### Implementation for User Story 3

- T059 [US3] Compile manifest triggers (`url_pattern`, `path_pattern`, `path_exists`) into `TriggerRegistry` in `src/research_framework/pipeline/source_bridge/discovery.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_discovery.py::test_compile_triggers_url_path_and_path_exists`
    - Behavior: Manifest trigger types populate `TriggerRegistry` entries.
    - Tier: 2

  **TDD discipline**: required

- T060 [US3] Implement `registry.match(source) -> Optional[tuple[str, int]]` first-match-wins per FR-010 in `src/research_framework/pipeline/source_bridge/discovery.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_discovery.py::test_registry_match_returns_module_and_priority`
    - Behavior: `registry.match(source)` first-match-wins tuple per FR-010.
    - Tier: 2

  **TDD discipline**: required

- T061 [US3] Wrap manifest YAML parse in `isolated_call` — skip module with WARN + run-report on double failure per D9 in `src/research_framework/pipeline/source_bridge/discovery.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_discovery.py::test_manifest_parse_double_failure_skips_module`
    - Behavior: YAML parse fails twice → module absent from registry + WARN.
    - Tier: 2
    - Notes: D9.

  **TDD discipline**: required

- T062 [US3] Implement `--debug-triggers` markdown table stdout per research R17 in `scripts/source_bridge.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_source_bridge_cli.py::test_debug_triggers_prints_markdown_table`
    - Behavior: `--debug-triggers` stdout is deterministic markdown table (research R17).
    - Tier: 2

  **TDD discipline**: required

- T063 [US3] Implement generic-path handler for `data_sources` entries with no module owner + no trigger match (`module=generic` cache keys) in `scripts/source_bridge.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_source_bridge_orchestration.py::test_generic_path_uses_module_generic_cache_keys`
    - Behavior: Unmatched `data_sources` entry processed with `module=generic`.
    - Tier: 3

  **TDD discipline**: required

- T064 [US3] Integrate discovery + sources enumeration into `source_bridge.run_extraction` pipeline start in `scripts/source_bridge.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_source_bridge_orchestration.py::test_run_extraction_integrates_discovery_and_enumeration`
    - Behavior: Pipeline start walks modules then loads per-module `sources.yaml`.
    - Tier: 3

  **TDD discipline**: required

- [ ] T065 [US3] Implement `install.sh` module copy via `shutil.copytree(dirs_exist_ok=True)` + manifest pre-validation per research R18 in `install.sh`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/generator/test_install_module_copy.py::test_install_copytree_modules_with_manifest_validation`
    - Behavior: `shutil.copytree(dirs_exist_ok=True)` + pre-validation per research R18.
    - Tier: 2

  **TDD discipline**: required

- [ ] T066 [US3] Seed `sources.yaml` from bundle template only when absent; never overwrite existing per FR-025 in `install.sh` / migrator hook
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/generator/test_install_module_copy.py::test_install_seeds_sources_yaml_only_when_absent`
    - Behavior: Existing `sources.yaml` never overwritten (FR-025).
    - Tier: 2

  **TDD discipline**: required


**Checkpoint**: US3 routing tests green; debug-triggers prints deterministic registry.

---

## Phase 6: User Story 5 — Per-vault validators shape signal payload (Priority: P2)

**Goal**: YAML + Python validators evaluated before cache write; fail-closed on validation errors; isolation on validator exceptions (FR-017, FR-018).

**Independent Test**: `code.validators.yaml` requiring non-empty `facts.technologies` rejects empty list with clear error and no cache write.

### Tests for User Story 5

- T067 [P] [US5] Add `tests/source_bridge/test_validators_yaml.py` — required buckets, min_items, fail-closed in `tests/source_bridge/test_validators_yaml.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_validators_yaml.py::test_yaml_validator_required_buckets_min_items`
    - Behavior: Rule requiring non-empty `facts.technologies` rejects empty list.
    - Tier: 2
    - Notes: FR-017.
  - **Test 2**: `tests/source_bridge/test_validators_yaml.py::test_yaml_validator_fail_closed_no_cache_write`
    - Behavior: Validation failure → no signal file created.
    - Tier: 2

  **TDD discipline**: required

- T068 [P] [US5] Add `tests/source_bridge/test_validators_python.py` — `validate()` errors, exception retry-once, isolation path in `tests/source_bridge/test_validators_python.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_validators_python.py::test_python_validator_returns_errors_list`
    - Behavior: `validate()` non-empty errors → rejection.
    - Tier: 2
  - **Test 2**: `tests/source_bridge/test_validators_python.py::test_python_validator_exception_retry_once_then_isolate`
    - Behavior: Validator raises; retry-once; second failure isolated without crashing cycle.
    - Tier: 2
    - Notes: D9 kind 2.

  **TDD discipline**: required


### Implementation for User Story 5

- T069 [US5] Implement YAML rule engine for `<module>.validators.yaml` per `contracts/validator-yaml.schema.json` in `src/research_framework/pipeline/source_bridge/validators.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_validators_yaml.py::test_yaml_rule_engine_loads_module_validators_yaml`
    - Behavior: Parses `<module>.validators.yaml` per `contracts/validator-yaml.schema.json`.
    - Tier: 2

  **TDD discipline**: required

- T070 [US5] Implement dynamic import + `validate(payload) -> list[str]` for `<module>.validators.py` in `src/research_framework/pipeline/source_bridge/validators.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_validators_python.py::test_dynamic_import_validate_callable`
    - Behavior: Imports `<module>.validators.py` and calls `validate(payload)`.
    - Tier: 2

  **TDD discipline**: required

- T071 [US5] Wire validator dispatch into extractor post-process before cache write in `src/research_framework/pipeline/source_bridge/extractor.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_extractor_contract.py::test_validators_run_before_cache_write`
    - Behavior: Invalid payload rejected before signal path written.
    - Tier: 3

  **TDD discipline**: required

- T072 [US5] Apply D9 retry-once around validator Python execution in `src/research_framework/pipeline/source_bridge/validators.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_validators_python.py::test_validator_isolated_call_retries_once`
    - Behavior: Exception path uses same retry-once policy as extractors.
    - Tier: 2

  **TDD discipline**: required

- T073 [US5] Default minimal validator: JSON Schema conformance only when no vault validator files in `src/research_framework/pipeline/source_bridge/validators.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_validators_yaml.py::test_default_json_schema_only_when_no_validator_files`
    - Behavior: Absent vault validator files → JSON Schema conformance only.
    - Tier: 2

  **TDD discipline**: required


**Checkpoint**: Validator rejection prevents cache write; cycle continues on isolated validator crash.

---

## Phase 7: User Story 6 — Value-tiered consensus per invocation (Priority: P2)

**Goal**: `value_tier` maps to odd N extractors; majority verdict + union findings; audit `ConsensusResult` (FR-019–FR-021).

**Independent Test**: `critical` tier N=3 — all exhausted advances watermark; 2×ok + 1×exhausted → final `ok` with unioned findings.

### Tests for User Story 6

- T074 [P] [US6] Add `tests/source_bridge/test_consensus.py` — N=1, N=3 agree/disagree, even-N config rejection in `tests/source_bridge/test_consensus.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_consensus.py::test_consensus_n1_passes_single_verdict`
    - Behavior: Tier mapping N=1 → single extractor outcome.
    - Tier: 2
  - **Test 2**: `tests/source_bridge/test_consensus.py::test_consensus_n3_majority_two_of_three_ok`
    - Behavior: Parameterized fake outputs: 2×ok + 1×exhausted → final `ok` with unioned findings (FR-019).
    - Tier: 2
    - Notes: M-of-N: 2-of-3 majority.
  - **Test 3**: `tests/source_bridge/test_consensus.py::test_consensus_rejects_even_n_at_config_load`
    - Behavior: Even N in settings → config error (FR-020).
    - Tier: 2
  - **Test 4**: `tests/source_bridge/test_consensus.py::test_consensus_n5_majority_three_of_five_exhausted_advances`
    - Behavior: Parameterized fake outputs: 3×exhausted + 2×ok on N=5 → final `exhausted` watermark advance (M-of-N majority).
    - Tier: 2
    - Notes: FR-019 exhausted path; no network.

  **TDD discipline**: required

- T075 [P] [US6] Extend `tests/source_bridge/test_extractor_contract.py` — stdin/stdout JSON, exit codes, heartbeat, retry-once, salvage in `tests/source_bridge/test_extractor_contract.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_extractor_contract.py::test_extractor_stdin_stdout_json_roundtrip`
    - Behavior: Fake Python extractor script in fixture vault; known stdin → stdout JSON.
    - Tier: 2
    - Notes: No network.
  - **Test 2**: `tests/source_bridge/test_extractor_contract.py::test_extractor_nonzero_exit_retries_once`
    - Behavior: Exit code ≠0 triggers retry-once then isolation.
    - Tier: 2
    - Notes: D9 kind 1.
  - **Test 3**: `tests/source_bridge/test_extractor_contract.py::test_extractor_salvage_partial_json_on_crash`
    - Behavior: Truncated stdout → partial payload `verdict: error`, `partial: true`.
    - Tier: 2

  **TDD discipline**: required


### Implementation for User Story 6

- T076 [US6] Implement tier→N resolution from `settings.yaml::stages.source_extraction.consensus.tiers` in `src/research_framework/pipeline/source_bridge/consensus.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_consensus.py::test_tier_maps_to_consensus_n_from_settings`
    - Behavior: `routine`/`important`/`critical` → configured odd N from `consensus.tiers`.
    - Tier: 2
    - Notes: Vendor-agnostic tiers.

  **TDD discipline**: required

- T077 [US6] Add config-load validation: all consensus N values odd per FR-020 in `src/research_framework/pipeline/settings.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_settings_loader.py::test_consensus_n_values_must_be_odd`
    - Behavior: Load settings with even N → validation error at config load (FR-020).
    - Tier: 2

  **TDD discipline**: required

- T078 [US6] Implement parallel extractor fan-out via `ThreadPoolExecutor` per research R7 in `src/research_framework/pipeline/source_bridge/consensus.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_consensus.py::test_parallel_fan_out_uses_thread_pool`
    - Behavior: N>1 spawns parallel extractors (mock ThreadPoolExecutor or call count).
    - Tier: 2
    - Notes: research R7.

  **TDD discipline**: required

- T079 [US6] Implement majority verdict + findings union + `ConsensusResult` write to `_pipeline/sources/<module>/consensus/` in `src/research_framework/pipeline/source_bridge/consensus.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_consensus.py::test_consensus_result_written_under_pipeline_consensus`
    - Behavior: `ConsensusResult` JSON under `_pipeline/sources/<module>/consensus/`.
    - Tier: 2
    - Notes: FR-021.

  **TDD discipline**: required

- T080 [US6] Implement module subprocess extractor invoke + tolerant JSON parse via `verifier._extract_json_blob` in `src/research_framework/pipeline/source_bridge/extractor.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_extractor_contract.py::test_extractor_tolerant_json_parse_via_blob_extractor`
    - Behavior: Stdout with surrounding noise; `_extract_json_blob` pattern recovers object.
    - Tier: 2

  **TDD discipline**: required

- T081 [US6] Implement D9 retry-once + partial salvage (`verdict: error`, `partial: true`) on extractor failure in `src/research_framework/pipeline/source_bridge/extractor.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_extractor_contract.py::test_extractor_double_failure_isolated_with_error_verdict`
    - Behavior: Two failures → no crash; `verdict: error` salvage path when partial present.
    - Tier: 2

  **TDD discipline**: required

- T082 [US6] Implement optional status-file heartbeat poll (30s/60s warn, 600s hard timeout) per research R21 in `src/research_framework/pipeline/source_bridge/extractor.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_extractor_contract.py::test_extractor_heartbeat_timeout_hard_kills_at_600s`
    - Behavior: Status file stale → hard timeout per research R21 (mock time/subprocess).
    - Tier: 2

  **TDD discipline**: required

- T083 [US6] Integrate consensus + validators into `source_bridge.run_extraction` per-source loop in `scripts/source_bridge.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_source_bridge_orchestration.py::test_per_source_loop_runs_consensus_then_validators`
    - Behavior: Integration ordering: consensus → validators → cache write.
    - Tier: 3

  **TDD discipline**: required


**Checkpoint**: Consensus tests green with stub extractors; FR-022 idempotency test added in T084.

- T084 [US6] Add FR-022 idempotency test — back-to-back extraction on unchanged vault produces no filesystem delta except timestamps in `tests/source_bridge/test_cache.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_cache.py::test_fr022_idempotent_back_to_back_no_filesystem_delta`
    - Behavior: Two extractions unchanged vault: only timestamp fields differ (FR-022).
    - Tier: 2

  **TDD discipline**: required


---

## Phase 8: User Story 2 — Scout reads cached signals (Priority: P1)

**Goal**: Scout prompt includes latest signal payloads; zero direct source access (FR-008, FR-009; SC-002/SC-003 measured in polish).

**Independent Test**: Pre-seeded cache + stub scout — prompt log contains signal JSON; no `git`/`gh`/HTTP source reads in scout stage.

### Implementation for User Story 2

- T085 [US2] Implement signal aggregation sidecar builder for scout input in `src/research_framework/pipeline/source_bridge/cache.py` (e.g. `_pipeline/cycles/cycle-NNN/source-signals.json`)
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_cache.py::test_build_source_signals_sidecar_for_scout`
    - Behavior: Aggregation writes `_pipeline/cycles/cycle-NNN/source-signals.json` with latest payloads.
    - Tier: 2

  **TDD discipline**: required

- T086 [US2] Edit scout step to load latest signals per module and inject into prompt in `src/research_framework/pipeline/steps/scout.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_scout_reads_signals.py::test_scout_prompt_includes_cached_signal_json`
    - Behavior: Pre-seeded cache; captured scout prompt contains signal JSON blob.
    - Tier: 3
    - Notes: fake_agent scout stage.

  **TDD discipline**: required

- T087 [US2] Remove/guard direct repo-access paths from scout stage (git, gh, source-path file reads) per FR-008 in `src/research_framework/pipeline/steps/scout.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_scout_reads_signals.py::test_scout_stage_no_git_or_http_subprocess`
    - Behavior: Assert no `git`/`gh`/HTTP client subprocess during scout when extraction enabled (FR-008).
    - Tier: 3

  **TDD discipline**: required

- T088 [US2] Add tier-2 test asserting scout prompt contains cached payload and no git subprocess in `tests/pipeline/test_scout_reads_signals.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_scout_reads_signals.py::test_scout_prompt_contains_cached_payload_no_git`
    - Behavior: Tier-2 combined assertion for T088 task deliverable.
    - Tier: 2
    - Notes: Task-listed test file.

  **TDD discipline**: required

- T089 [US2] Route scout topic proposal by `module` field on each payload per FR-009 in `src/research_framework/pipeline/steps/scout.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_scout_reads_signals.py::test_scout_routes_topics_by_payload_module_field`
    - Behavior: Topics tagged using each signal's `module` field (FR-009).
    - Tier: 3

  **TDD discipline**: required


**Checkpoint**: Scout consumes cache only when `source_extraction.enabled: true`.

---

## Phase 9: User Story 7 — Per-call agent logging (cross-cutting, Priority: P2)

**Goal**: Every LLM invocation writes full prompt/response records under `agent-calls/` (FR-024, SC-009). **Note**: Spec 028 may bump sidecar schema to v1.1 — align field names when 028 lands; do not block 020 on 028.

**Independent Test**: One cycle with multiple agent stages → record count matches invocations; prompt/response not truncated.

### Tests for User Story 7

- T090 [P] [US7] Add `tests/pipeline/test_agent_call_logging.py` — record shape, non-truncated prompt/response, error field on failure in `tests/pipeline/test_agent_call_logging.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_agent_call_logging.py::test_agent_call_record_shape_matches_schema`
    - Behavior: Written JSON validates `contracts/agent-call-record.schema.json` / 028 v1.1 fields when aligned.
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_agent_call_logging.py::test_prompt_and_response_not_truncated`
    - Behavior: Long prompt/response bytes preserved in sidecar file.
    - Tier: 2
    - Notes: FR-024.

  **TDD discipline**: required


### Implementation for User Story 7

- T091 [US7] Extend `scripts/agent_call.py` (the canonical dispatch entry point — consistent with T032) to capture full prompt + response text per FR-024
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_agent_call_logging.py::test_agent_call_captures_full_prompt_and_response`
    - Behavior: Dispatch via fake_agent; record contains full text fields.
    - Tier: 3
    - Notes: fake_agent only.

  **TDD discipline**: required

- T092 [US7] Write `AgentCallRecord` JSON to `_pipeline/cycles/cycle-NNN/agent-calls/<ts>-<stage>-<call-id>.json` per `contracts/agent-call-record.schema.json` (writer in `scripts/agent_call.py`; coordinate with 028's sidecar v1.1 writer to avoid double-emit — see Notes below)
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_agent_call_logging.py::test_agent_call_writes_under_agent_calls_directory`
    - Behavior: Path `_pipeline/cycles/cycle-NNN/agent-calls/<ts>-<stage>-<call-id>.json` (coordinate 028 v1.1 naming).
    - Tier: 3

  **TDD discipline**: required

- T093 [US7] Record `tier` + resolved `model` on each call per D7 in `scripts/agent_call.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_agent_call_logging.py::test_agent_call_records_tier_and_resolved_model`
    - Behavior: Sidecar includes `tier` + `model` per D7.
    - Tier: 2

  **TDD discipline**: required

- T094 [US7] Add SC-009 count test vs cost-report invocation tally in `tests/pipeline/test_agent_call_logging.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_agent_call_logging.py::test_sc009_record_count_matches_invocation_tally`
    - Behavior: One cycle N agent calls → N sidecar files vs cost-report tally (SC-009).
    - Tier: 3
    - Notes: fake_agent multi-stage cycle.

  **TDD discipline**: required


**Checkpoint**: Agent-call logging ships as independent commit (plan Block O).

---

## Phase 10: Block CM — Code reference module (supports US1 + US3)

**Goal**: Ship framework `code` module — first 020-shaped module for revival sprint repo walks.

- T095 [P] [US1] Author `src/research_framework/modules/code/manifest.yaml` with `path_pattern`/`path_exists` triggers + `source_id_from.github_repos: path` per FR-011
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/modules/code/test_manifest.py::test_code_manifest_triggers_and_source_id_from`
    - Behavior: Validates `path_pattern`/`path_exists` + `source_id_from.github_repos: path` (FR-011).
    - Tier: 2

  **TDD discipline**: required

- T096 [P] [US1] Author `src/research_framework/modules/code/few-shot.md` schema-gen examples in `src/research_framework/modules/code/few-shot.md`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/modules/code/test_schema_gen_examples.py::test_few_shot_md_non_empty`
    - Behavior: `few-shot.md` exists and contains schema-gen examples referenced by prompt.
    - Tier: 2
    - Notes: Doc/content task with assertable invariant.

  **TDD discipline**: not required

- T097 [US1] Implement `get_source_version` + `extract` in `src/research_framework/modules/code/extractor.py` using git subprocess per research R1 + `contracts/extractor-prompt-code.md`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/modules/code/test_extractor.py::test_code_extractor_get_source_version_from_fake_repo`
    - Behavior: Git subprocess against `fake_repo` checkout; version JSON contract.
    - Tier: 2
    - Notes: No real network.
  - **Test 2**: `tests/modules/code/test_extractor.py::test_code_extractor_extract_emits_signal_shape`
    - Behavior: `extract` stdout parses to signal envelope per code module contract.
    - Tier: 2

  **TDD discipline**: required

- T098 [US1] Add `tests/modules/code/test_extractor.py` against `tests/_helpers/fake_repo.py` in `tests/modules/code/test_extractor.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/modules/code/test_extractor.py::test_code_extractor_against_fake_repo_fixture`
    - Behavior: End-to-end module extractor invocation with controlled repo state.
    - Tier: 2
    - Notes: Task-owned module tests.

  **TDD discipline**: required

- T099 [P] [US1] Add `tests/modules/code/test_manifest.py` conforming to `contracts/manifest.schema.json` in `tests/modules/code/test_manifest.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/modules/code/test_manifest.py::test_code_manifest_conforms_to_manifest_schema`
    - Behavior: Bundle manifest validates against `contracts/manifest.schema.json`.
    - Tier: 2

  **TDD discipline**: required

- T100 [US1] Bundle default `sources.yaml.template` for code module in `src/research_framework/modules/code/sources.yaml.template`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/modules/code/test_manifest.py::test_sources_yaml_template_present_in_bundle`
    - Behavior: `sources.yaml.template` ships in module bundle with required comment header.
    - Tier: 2

  **TDD discipline**: not required


---

## Phase 11: Block CFG — Settings, tiers, migrator (cross-cutting)

**Goal**: Opt-in stage flag, tier resolution, module refresh on update (FR-012, FR-014a, FR-025, D6, D7).

- T101 Implement `tiers:` block defaults in settings templates per `contracts/tiers.schema.json` in `dist-templates/settings.yaml`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_settings_templates.py::test_dist_templates_include_tiers_block`
    - Behavior: Templates validate against `contracts/tiers.schema.json` defaults.
    - Tier: 2

  **TDD discipline**: required

- T102 Implement tier resolution for `schema_gen` + `source_extraction` executors in `src/research_framework/pipeline/settings.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_tier_resolution.py::test_schema_gen_executor_resolves_tier_to_model`
    - Behavior: Stage `schema_gen` uses `tiers:` block not hardcoded vendor strings.
    - Tier: 2
    - Notes: FR-014a.
  - **Test 2**: `tests/pipeline/test_tier_resolution.py::test_source_extraction_executor_resolves_tier`
    - Behavior: Consensus/extraction executors resolve tier from settings.
    - Tier: 2

  **TDD discipline**: required

- T103 Add config-load errors for `tier`+`model` conflict and unknown tier name in `src/research_framework/pipeline/settings.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_tier_resolution.py::test_tier_and_model_mutually_exclusive_raises`
    - Behavior: Executor with both `tier:` and `model:` → config-load error.
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_tier_resolution.py::test_unknown_tier_name_raises_at_load`
    - Behavior: References undefined tier label → clear error.
    - Tier: 2

  **TDD discipline**: required

- T104 [P] Add `tests/pipeline/test_tier_resolution.py` per research Section 3 (lives beside existing `tests/pipeline/test_settings_loader.py` since T102/T103 modify `src/research_framework/pipeline/settings.py`)
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_tier_resolution.py::test_tier_resolution_per_research_section_three`
    - Behavior: Matrix of settings fixtures → expected resolved model ids.
    - Tier: 2
    - Notes: Task-owned tier resolution suite.

  **TDD discipline**: required

- T105 Implement 0.3.0 upgrade-time settings.yaml mutation — flip `stages.source_extraction.enabled: true` + default `modules: [code]` if absent — in the update flow that runs from `dist-templates/install.sh` (per 0.2.33 `./vault update` = `pip install --upgrade` + re-run `install.sh`; the legacy spec-013 `pipeline/migrator.py` was retired in 0.2.33 so the mutation now lives in the install-script-invoked Python helper — add to `src/research_framework/generator/scaffold.py` or a sibling module, idempotent across repeat invocations)
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/generator/test_module_refresh.py::test_upgrade_flips_source_extraction_enabled_and_modules`
    - Behavior: 0.3.0 migration idempotent: sets `enabled: true` + `modules: [code]` when absent.
    - Tier: 2

  **TDD discipline**: required

- [ ] T106 Implement D6 module re-copy for listed `settings.yaml::modules:` only + `--no-refresh-modules` flag in `dist-templates/install.sh` (flag surface) + the supporting copy logic in `src/research_framework/generator/scaffold.py` (preserves `<vault>/modules/<name>/sources.yaml` per FR-013a + `user_owned` paths per FR-025; skips modules NOT listed in `settings.yaml::modules:`)
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/generator/test_module_refresh.py::test_listed_modules_recopied_unlisted_skipped`
    - Behavior: D6: only `settings.yaml::modules:` entries refreshed; unlisted untouched.
    - Tier: 2
  - **Test 2**: `tests/scripts/test_install_sh_flags.py::test_no_refresh_modules_skips_module_copy`
    - Behavior: `--no-refresh-modules` prevents re-copy (install.sh flag surface).
    - Tier: 2

  **TDD discipline**: required

- T107 [P] Add `tests/generator/test_module_refresh.py` — selective refresh, `sources.yaml` preservation, skip unlisted modules (covers both T105 and T106; lives beside existing `tests/generator/test_scaffold.py` since the copy logic ports to `src/research_framework/generator/scaffold.py`; install.sh-side flag surface coverage may belong in `tests/scripts/` alongside `test_install_sh_tty_handling.py` if the test needs subprocess execution)
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/generator/test_module_refresh.py::test_refresh_preserves_existing_sources_yaml`
    - Behavior: Re-copy does not overwrite operator `sources.yaml` (FR-025 / FR-013a).
    - Tier: 2
    - Notes: Covers T105+T106 refresh behavior.

  **TDD discipline**: required

- [ ] T108 Add D5 trust-boundary install prompt when `modules:` non-empty in `install.sh`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_install_sh_flags.py::test_install_prompts_when_modules_non_empty`
    - Behavior: Non-empty `modules:` triggers D5 trust-boundary prompt text on install.
    - Tier: 2
    - Notes: Permissive trust boundary — prompt only.

  **TDD discipline**: required

- [ ] T122 [P] Add `tests/generator/test_user_owned_preservation.py` — assert files under `<vault>/modules/<name>/` with `manifest.user_owned: true` survive `./vault update` re-copy unchanged (FR-025); cover both copied + manually-edited variants; cover `--no-refresh-modules` short-circuit too (lives beside existing `tests/generator/test_scaffold.py` since user-owned semantics are read by `src/research_framework/generator/scaffold.py`)
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/generator/test_user_owned_preservation.py::test_user_owned_files_survive_vault_update_recopy`
    - Behavior: `manifest.user_owned: true` paths byte-identical after `./vault update` simulation.
    - Tier: 2
    - Notes: FR-025.
  - **Test 2**: `tests/generator/test_user_owned_preservation.py::test_no_refresh_modules_skips_all_module_copy`
    - Behavior: `--no-refresh-modules` short-circuit preserves user-owned and listed modules alike.
    - Tier: 2

  **TDD discipline**: required

- T123 [P] Add `tests/pipeline/test_default_tier_resolution.py` — assert `manifest.yaml::default_tier` is honored when a stage executor omits `tier:` AND `model:`; assert explicit executor `tier:` overrides the manifest default; assert config-load error when both `tier:` and `model:` are set on the same executor (FR-014a) (lives beside existing `tests/pipeline/test_settings_loader.py` + `tests/pipeline/test_tier_resolution.py` since `default_tier` resolution lives in `src/research_framework/pipeline/settings.py`)
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_default_tier_resolution.py::test_manifest_default_tier_used_when_executor_omits_tier_and_model`
    - Behavior: FR-014a: `manifest.default_tier` honored.
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_default_tier_resolution.py::test_executor_explicit_tier_overrides_manifest_default`
    - Behavior: Stage executor `tier:` wins over manifest default.
    - Tier: 2
  - **Test 3**: `tests/pipeline/test_default_tier_resolution.py::test_executor_tier_and_model_conflict_raises`
    - Behavior: Both set on same executor → config-load error.
    - Tier: 2

  **TDD discipline**: required


---

## Phase 12: Integration polish — run-report, CLI, docs (Final Phase)

**Purpose**: Cross-cutting wiring, docs, CHANGELOG, SC-005, legacy port helper, ADR updates. **No** `cli/refresh_sources.py` or `scripts/collect_*.py` invocation tasks (023 owns those).

- [ ] T109 [US1] Implement D9 run-report "Module-Subsystem Issues" section collector in `src/research_framework/pipeline/cycle_runner.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_runner_run_report.py::test_run_report_module_subsystem_issues_section`
    - Behavior: Isolated failures appear under `## Module-Subsystem Issues` in run-report.
    - Tier: 3
    - Notes: fake_agent / stub bridge failures.

  **TDD discipline**: required

- T110 [US1] Wire `bridge.log` per-module append-only logging in `src/research_framework/pipeline/source_bridge/isolation.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_module_isolation.py::test_bridge_log_append_only_per_module`
    - Behavior: `bridge.log` receives append-only lines per module under `_pipeline/sources/<module>/`.
    - Tier: 2

  **TDD discipline**: required

- [ ] T111 Add `--force-stale-schema` propagation from CLI → cycle runner → `schema_gen` per D8 in `src/research_framework/cli/__init__.py` (or generate command module)
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_force_stale_schema_flag.py::test_force_stale_schema_propagates_to_schema_gen`
    - Behavior: CLI/generate flag reaches `schema_gen` and suppresses `StaleManualSchemaError` for one run.
    - Tier: 2
    - Notes: D8 override wiring.

  **TDD discipline**: required

- T112 [P] Add SC-005 test — all sources fail isolation yet cycle completes in `tests/source_bridge/test_module_isolation.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_module_isolation.py::test_sc005_all_sources_fail_isolation_cycle_completes`
    - Behavior: Every source isolated; cycle still completes (SC-005).
    - Tier: 3
    - Notes: tier-3/4 integration.

  **TDD discipline**: required

- [ ] T113 [P] Add one-time `scripts/port_legacy_sources_yaml.py` to split vault-level `scripts/sources.yaml` → per-module `sources.yaml` (migration helper only; not called from `sources_loader`) in `scripts/port_legacy_sources_yaml.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_port_legacy_sources_yaml.py::test_port_splits_vault_scripts_yaml_to_per_module`
    - Behavior: Legacy `<vault>/scripts/sources.yaml` → per-module `sources.yaml` files; not invoked by loader.
    - Tier: 2
    - Notes: Migration helper only.

  **TDD discipline**: required

- [ ] T114 Validate `specs/020-code-bridge/quickstart-vault-author.md` steps against fixture vault manually (document gaps in PR if any)
- [ ] T115 Validate `specs/020-code-bridge/quickstart-module-author.md` trust-boundary warning + module layout
- [ ] T116 [P] Update `CHANGELOG.md` `[Unreleased]` with 0.3.0 source-module architecture user-visible surface
- [ ] T117 [P] Update `docs/adr/0006-code-access-cached-infrastructure.md` status to shipped 0.3.0
- [ ] T118 [P] Draft new ADR for trigger-based source routing + per-module `sources.yaml` enumeration in `docs/adr/`
- [ ] T119 Add manifest-walk perf smoke (<10 ms for 10-module vault) in `tests/source_bridge/test_discovery.py` per research R9
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_discovery.py::test_manifest_walk_under_10ms_for_ten_modules`
    - Behavior: 10-module vault fixture; `walk_modules` <10 ms (research R9 smoke).
    - Tier: 2

  **TDD discipline**: required

- [ ] T120 [P] Add tier-2 static test forbidding `source_bridge` imports of `cli.refresh_sources` or subprocess invocation of `scripts/collect_*.py` in `tests/source_bridge/test_cross_spec_boundary.py`
  ### Testing Requirements

  _Authored by test-design agent on 2026-05-27. Do not edit during implementation._

  - **Test 1**: `tests/source_bridge/test_cross_spec_boundary.py::test_source_bridge_no_refresh_sources_import`
    - Behavior: Static AST/import scan: `source_bridge` must not import `cli.refresh_sources`.
    - Tier: 2
    - Notes: 023 boundary.
  - **Test 2**: `tests/source_bridge/test_cross_spec_boundary.py::test_source_bridge_no_collect_scripts_subprocess`
    - Behavior: Static scan forbids `scripts/collect_*.py` subprocess invocation from source_bridge package.
    - Tier: 2

  **TDD discipline**: required

- [ ] T121 [P] Document SC-002/SC-003 operator measurement procedure (reference-vault baseline token + topic yield; manual gate, not CI) in `CHANGELOG.md` `[Unreleased]` section

**Checkpoint**: Full `./build.sh` smoke + tier-4 e2e green; quickstarts validated.

---

## Dependencies & Execution Order

### Phase Dependencies

| Phase | Depends on | Blocks |
|-------|------------|--------|
| Setup (1) | — | Foundational |
| Foundational (2) | Setup | US4, US1, US3, US5, US6 |
| US4 Schema (3) | Foundational | US1 extraction (needs `facts-schema.json`) |
| US1 Cache (4) | US4 schemas + Foundational loader/cache | US2 scout |
| US3 Discovery (5) | Foundational discovery + US1 bridge shell | US1 completion |
| US5 Validators (6) | US1 extractor path | — |
| US6 Consensus (7) | US1 + US5 | — |
| US2 Scout (8) | US1 signals on disk | — |
| US7 Agent logs (9) | Foundational (`agent_call.py` exists) | Can parallel US6 |
| Code module (10) | US6 extractor contract | US1 real-repo runs |
| CFG (11) | Foundational settings | Integration |
| Polish (12) | All desired stories | Ship |

### User Story Dependencies

- **US4** before **US1** full extraction (schema required per FR-006).
- **US1** before **US2** (scout needs signals).
- **US3** parallel with US4/US1 after Foundational (discovery + enumeration).
- **US5/US6** after US1 extractor shell.
- **US7** independent of bridge (parallel Block O).

### Within-Story Order

Tests listed first where present → implementation → integration → checkpoint.

---

## Parallel-stream alignment

Maps plan.md Phase 2 blocks to task groups (for `/dispatching-parallel-agents`):

| Plan block | Tasks | Parallel with |
|------------|-------|---------------|
| **Block S** (schema-gen) | T029–T041 | **Block A** T042–T047, **Block M** T055–T066, **Block E** T017–T021 |
| **Block A** (cache/envelope) | T009–T016, T042–T047 | Block S, M, E |
| **Block E** (`sources.yaml` loader) | T011, T017–T021 | Block M, A |
| **Block M** (discovery/registry) | T012, T022–T024, T055–T066 | Block E, A |
| **Block V** (validators) | T067–T073 | Block C (after A shell) |
| **Block C** (extractor+consensus) | T074–T084 | Block CM |
| **Block CM** (code module) | T095–T100 | Block C |
| **Block I** (integration) | T048–T054, T085–T089, T109–T111 | Block O |
| **Block O** (agent logging) | T090–T094 | Block I |
| **Block CFG** | T101–T108 | Block I |
| **Block F** (fixtures) | T039–T040, T041 | Block S |
| **Block D** (docs) | T114–T118 | Polish |

**Recommended MVP slice**: Setup → Foundational → US4 (T029–T041) → US1 cache (T042–T054) → Code module (T095–T100) → stop and validate SC-001/SC-004.

---

## Implementation Strategy

### MVP First (US1 + US4)

1. Complete Phase 1–2 (Setup + Foundational).
2. Complete Phase 3 (US4 schema-gen) + Phase 10 code module stubs.
3. Complete Phase 4 (US1 cache + stage wiring).
4. **STOP and VALIDATE**: `test_e2e_cache_hit.py` + `test_cache.py` green.
5. Add US3 routing, US2 scout, then US5–US7 incrementally.

### Incremental Delivery

| Increment | Delivers | Verify |
|-----------|----------|--------|
| v0 | Foundational loader + FAIL-fast tests | `test_sources_loader.py` |
| v1 | Schema-gen + fixtures SC-006 | `test_schema_gen.py` |
| v2 | Cache-hit extraction (stub module) | `test_e2e_cache_hit.py` |
| v3 | Code module + real git repos | `test_extractor.py` |
| v4 | Scout reads signals | `test_scout_reads_signals.py` |
| v5 | Validators + consensus + agent logs | respective test files |
| v6 | Migrator + docs + CHANGELOG | `test_module_refresh.py` |

### Parallel Team Strategy

- **Dev A**: Block S (T029–T041) + fixtures.
- **Dev B**: Block A/E/M (T009–T024, T042–T047, T055–T066).
- **Dev C**: Block CM + Block C (T074–T100) after Foundational merge.

---

## Cross-spec coordination (Spec 020 ↔ Spec 023)

Per `plan.md` § Cross-spec coordination and `specs/023-flow-separation/plan.md`:

- **`sources_loader.py` reads only `<vault>/modules/<name>/sources.yaml`** for the source-extraction stage. Tasks **MUST NOT** add invocation of `cli/refresh_sources.py`, `./vault refresh-sources`, or `scripts/collect_*.py`.
- **Legacy collector deletion** (removing `scripts/collect_*.py` after a module port) is a **separate manual step** gated on spec 023 FR-015 (`scripts/` survives update) — not automated in 020 tasks.
- **Shared filesystem concern**: `<vault>/scripts/` lifecycle is owned by 023; 020 owns `<vault>/modules/` and `_pipeline/sources/`.
- **FR-013a boundary with `refresh-sources`**: 023's `./vault refresh-sources` verb iterates `<vault>/scripts/collect_*.py` + `reddit_rss.py` allowlist — NOT this per-module `sources.yaml`. The two are runtime-decoupled (see `spec.md` FR-013a "Boundary with spec 023" block and `contracts/sources.yaml.contract.md` § "Relationship to `./vault refresh-sources`"). **No 020 task** implements `refresh-sources`; T120 enforces the boundary via static test.

---

## Notes

- `[P]` = parallelizable (different files, no incomplete-task dependency).
- `[USn]` label only in user-story phases (3–9); Setup/Foundational/Polish omit story labels.
- **FAIL-fast FR-013b**: T018/T021 — never skip-with-WARN on missing identity (pre-PR-20 behaviour is wrong).
- **FR-010 unlisted modules**: lexicographic after listed block (T023).
- **Principle V**: no new runtime deps — subprocess + stdlib only.
- **Trust boundary (D5)**: T108 + T115; no sandbox tasks in 020.
- **028 coordination**: T092 agent-call paths may need v1.1 fields when dispatch telemetry merges — track in umbrella PR.

---

## Task Summary

| Phase | Task IDs | Count |
|-------|----------|-------|
| Setup | T001–T008 | 8 |
| Foundational | T009–T028 | 20 |
| US4 Schema | T029–T041 | 13 |
| US1 Cache | T042–T054 | 13 |
| US3 Discovery | T055–T066 | 12 |
| US5 Validators | T067–T073 | 7 |
| US6 Consensus | T074–T084 | 11 |
| US2 Scout | T085–T089 | 5 |
| US7 Agent logs | T090–T094 | 5 |
| Code module | T095–T100 | 6 |
| CFG | T101–T108, T122–T123 | 10 |
| Polish | T109–T121 | 13 |
| **Total** | **T001–T123** | **123** |

**Note**: Task numbering is non-contiguous (T122–T123 added to Phase 11 / CFG block during pre-implement reconciliation to cover FR-025 `manifest.user_owned` preservation and FR-014a `manifest.default_tier` resolution — coverage gaps surfaced by `/speckit.analyze` 2026-05-27). All other IDs remain in sequence.

**Suggested MVP scope**: T001–T054 + T095–T100 (Setup + Foundational + US4 + US1 + code module).
