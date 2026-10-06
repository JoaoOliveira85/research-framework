---
description: "Task list for spec 027 — ./vault update Hardening (QW-6)"
---

# Tasks: `./vault update` Hardening

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Feature**: `./vault update` Hardening (QW-6) | **Branch**: `027-vault-update-hardening` | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Design**: [research.md](./research.md), [quickstart.md](./quickstart.md), [checklists/requirements.md](./checklists/requirements.md)

**Scope theme**: *reconcile, don't reimplement* — DELTA over shipped 0.7.0 (`vault_commit.py`) + 0.8.0 (spec 051 `install.sh`). **Do NOT** re-implement stale-venv rebuild, post-install importable-version check, or the existing post-upgrade `commit_framework_change` call.

**Tests**: REQUIRED (Constitution Principle III). **TDD is mandatory — tests written and seen to FAIL before impl.** Run tests/lint via `.venv/bin/python -m pytest` / `.venv/bin/python -m ruff` (NOT bare `python` — base env has a stale editable install).

**Organization**: One phase per user story (P1→P3). US1 is the 🎯 MVP (safe upgrade). US2 is rollback documentation only (no `./vault rollback` command). FR-009/FR-010 span US1/US3 tests + Polish smoke-gate wiring.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no incomplete-task dependency)
- **[USn]**: User story from spec.md (US1–US4)
- Exact repo-relative file paths in every task; FR references inline

## Path Conventions

Single-project layout: package under `src/research_framework/`, tests under `tests/`, vault shim template at `templates/vault-script.sh.j2`, installer at `dist-templates/install.sh`, manifest at `dist-templates/scaffold-manifest.json`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm branch, green baseline, and test scaffold before any production edits.

- T001 Confirm on branch `027-vault-update-hardening` with clean working tree (`git status`); capture baseline via `.venv/bin/python -m pytest -m "not e2e" -q` and dual lint gates `.venv/bin/python -m ruff check .` + `.venv/bin/python -m ruff format --check .` (both must be green before starting)
- T002 [P] Create `tests/cli/test_vault_update.py` skeleton: module docstring, shared fixtures for a hermetic local file-URL “remote” repo + `tests/_helpers/vault_factory.build_minimal_vault` upgrade fixture (no network, no live agents) per plan.md §Test approach (FR-009)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Public dirty-tree API + empty orchestrator module. **Blocks all user stories.**

**⚠️ CRITICAL**: No US1–US4 work until T006 checkpoint is green.

- T003 Add public `is_working_tree_dirty(vault: Path) -> bool` in `src/research_framework/pipeline/vault_commit.py` — one-line wrapper over existing private `_is_dirty`; no behaviour change to 0.7.0 commit paths (FR-003; deps: T001)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_vault_commit.py::test_is_working_tree_dirty_is_public_export`
    - Behavior: Import from `research_framework.pipeline.vault_commit`; assert callable is exported on the public module surface (not underscored).
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_vault_commit.py::test_is_working_tree_dirty_true_on_dirty_vault`
    - Behavior: Init tmp git vault, touch an untracked file; assert `is_working_tree_dirty(vault)` is True and matches `_is_dirty(vault)` on the same tree.
    - Tier: 2
  - **Test 3**: `tests/pipeline/test_vault_commit.py::test_is_working_tree_dirty_false_on_clean_vault`
    - Behavior: Init tmp git vault with clean index/worktree; assert `is_working_tree_dirty(vault)` is False and matches `_is_dirty(vault)`.
    - Tier: 2

  **TDD discipline**: required

- T004 [P] Add failing tests in `tests/pipeline/test_vault_commit.py` asserting `is_working_tree_dirty` is exported and matches `_is_dirty` on a dirty/clean tmp git vault — must FAIL until T003 lands (FR-003; deps: T001)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_vault_commit.py::test_is_working_tree_dirty_is_public_export`
    - Behavior: Red-phase test; MUST fail (ImportError or AttributeError) until T003 lands the public wrapper.
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_vault_commit.py::test_is_working_tree_dirty_true_on_dirty_vault`
    - Behavior: Red-phase test; MUST fail until T003; asserts parity with `_is_dirty` on a dirty tmp vault.
    - Tier: 2
  - **Test 3**: `tests/pipeline/test_vault_commit.py::test_is_working_tree_dirty_false_on_clean_vault`
    - Behavior: Red-phase test; MUST fail until T003; asserts parity with `_is_dirty` on a clean tmp vault.
    - Tier: 2

  **TDD discipline**: required

- T005 Create `src/research_framework/pipeline/vault_update.py` with module docstring, `Decision` dataclass (`action`, `message`, `exit_code`), and `__all__` stub — no logic yet (FR-001; deps: T003)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_vault_update_decide.py::test_vault_update_module_importable`
    - Behavior: Import `research_framework.pipeline.vault_update`; assert module loads without error.
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_vault_update_decide.py::test_decision_dataclass_fields`
    - Behavior: Construct `Decision(action=..., message=..., exit_code=...)`; assert all three fields round-trip on the dataclass instance.
    - Tier: 2

  **TDD discipline**: required

- T006 **Checkpoint**: T003–T005 green; `is_working_tree_dirty` importable from `vault_commit`; `vault_update` importable

**Checkpoint**: Foundation ready — user story phases may begin.

---

## Phase 3: User Story 1 — Operator upgrades a production vault safely (Priority: P1) 🎯 MVP

**Goal**: Hardened `./vault update` with archive-first version resolution, short-circuit, dirty-tree guard (`--force` override), labelled pre-snapshot, downgrade refusal, version diff print, and post-install `./vault health` — reusing shipped Principle X + install.sh surfaces.

**Independent Test**: Fixture vault at framework v0.3.0, target v0.3.1 via local file-URL repo. `./vault update` yields `snapshot before update 0.3.0 -> 0.3.1` as `HEAD~1` of `framework: upgrade to 0.3.1`, `./vault health` passes, dirty tree refused without `--force`, re-run short-circuits in <5 s.

### Tests (write first — must FAIL)

- T007 [P] [US1] Write `tests/pipeline/test_vault_update_decide.py`: unit coverage for `compare_versions` (same/upgrade/downgrade), `snapshot_title(old,new)`, and `decide(...)` truth-table for FR-002 noop + FR-012 downgrade-refuse/unless-pinned+confirmed branches (FR-001, FR-002, FR-012; deps: T005)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_vault_update_decide.py::test_compare_versions_classifies_same_upgrade_downgrade`
    - Behavior: Assert `compare_versions` returns `same`/`upgrade`/`downgrade` for equal, newer-target, and older-target version pairs (semver-ish tuple compare per plan.md).
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_vault_update_decide.py::test_snapshot_title_matches_fr004_label`
    - Behavior: Assert `snapshot_title("0.3.0", "0.3.1")` equals `snapshot before update 0.3.0 -> 0.3.1` (FR-004 subject format).
    - Tier: 2
  - **Test 3**: `tests/pipeline/test_vault_update_decide.py::test_decide_noop_when_local_equals_target`
    - Behavior: Call `decide` with equal local/target; assert `Decision.action == "noop"`, exit 0, and FR-002 short-circuit message shape.
    - Tier: 2
  - **Test 4**: `tests/pipeline/test_vault_update_decide.py::test_decide_refuses_downgrade_unless_pinned_and_confirmed`
    - Behavior: Call `decide` with target < local; assert refuse unless both `pinned_ref` and `confirmed` are set (FR-012).
    - Tier: 2

  **TDD discipline**: required

- T008 [P] [US1] Add `test_short_circuit_when_already_current` to `tests/cli/test_vault_update.py` — local == target ⇒ exit 0, no pip/install.sh side effects, completes <5 s (FR-002, SC-002, FR-009; deps: T002)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_vault_update.py::test_short_circuit_when_already_current`
    - Behavior: Hermetic fixture vault + local file-URL remote at same version; run `./vault update`; assert exit 0, stdout contains "Already at" / "nothing to do", no pip/install.sh subprocess side effects (mock or spy), wall-clock < 5 s (SC-002). No live agents.
    - Tier: 3

  **TDD discipline**: required

- T009 [P] [US1] Add `test_dirty_tree_refused_without_force` to `tests/cli/test_vault_update.py` — dirty vault ⇒ non-zero + clear message, no snapshot/install; `--force` stub allows proceed (FR-003, SC-003; deps: T002)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_vault_update.py::test_dirty_tree_refused_without_force`
    - Behavior: Dirty working tree on fixture vault; run `./vault update` without `--force`; assert non-zero exit in < 2 s (SC-003), message instructs commit/stash or `--force`, and no pre-snapshot commit or install.sh invocation occurs.
    - Tier: 3
  - **Test 2**: `tests/cli/test_vault_update.py::test_dirty_tree_proceeds_with_force_flag`
    - Behavior: Same dirty fixture; run `./vault update --force`; assert update proceeds past the dirty guard (may stub pip/install to keep hermetic).
    - Tier: 3

  **TDD discipline**: required

- T010 [P] [US1] Add `test_pre_snapshot_then_upgrade_topology` to `tests/cli/test_vault_update.py` — after upgrade, `git log` shows labelled pre-snapshot as immediate parent of upgrade commit (FR-004, FR-001; deps: T002)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_vault_update.py::test_pre_snapshot_then_upgrade_topology`
    - Behavior: Upgrade fixture vault v0.3.0→v0.3.1 via `./vault update`; parse `git log`; assert `snapshot before update 0.3.0 -> 0.3.1` is `HEAD~1` of the `framework: upgrade to 0.3.1` commit (FR-004 topology). Uses `vault_factory.build_minimal_vault`; no network.
    - Tier: 3

  **TDD discipline**: required

- T011 [P] [US1] Add `test_downgrade_refused_by_default` to `tests/cli/test_vault_update.py` — target < local ⇒ refuse; explicit pinned ref + confirm ⇒ proceed (FR-012; deps: T002)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_vault_update.py::test_downgrade_refused_by_default`
    - Behavior: Fixture vault at newer local version with remote/archive targeting older version; run `./vault update` without pinned ref + confirm; assert non-zero refuse. Re-run with explicit `RV_GITHUB_REF` pin + `--auto-confirm`; assert proceed (FR-012).
    - Tier: 3

  **TDD discipline**: required

- T012 [P] [US1] Add `test_health_failure_surfaces_nonzero` to `tests/cli/test_vault_update.py` — stub failing `./vault health` ⇒ update exits non-zero with prominent message (FR-005; deps: T002)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_vault_update.py::test_health_failure_surfaces_nonzero`
    - Behavior: Stub or replace `./vault health` to exit non-zero during update; assert `./vault update` exits non-zero and stderr/stdout surfaces the health failure prominently (FR-005). No live agents.
    - Tier: 3

  **TDD discipline**: required

### Implementation

- T013 [US1] Implement in `src/research_framework/pipeline/vault_update.py`: `resolve_local_version(vault)`, `resolve_target_version(archive_or_ref)` via stdlib `tomllib` on archive `pyproject.toml`, `compare_versions`, `snapshot_title`, `decide(local, target, *, force, pinned_ref, confirmed) -> Decision` (FR-001, FR-002, FR-012; deps: T007)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_vault_update_decide.py::test_resolve_local_version_from_vault_venv`
    - Behavior: Fixture vault with known installed `research_framework.__version__`; assert `resolve_local_version` returns that version string via the vault venv interpreter.
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_vault_update_decide.py::test_resolve_target_version_from_archive_pyproject`
    - Behavior: Point at a tmp archive/tree containing `pyproject.toml` with a known `version`; assert `resolve_target_version` parses it via stdlib `tomllib` (FR-001).
    - Tier: 2
  - **Test 3**: `tests/pipeline/test_vault_update_decide.py::test_decide_proceed_on_upgrade`
    - Behavior: Call `decide` with target > local; assert proceed action and exit 0 unless other guards apply.
    - Tier: 2

  **TDD discipline**: required

- T014 [US1] Reorder `templates/vault-script.sh.j2` `update` case per plan.md §Verb edit: parse `--force` locally (do NOT forward to `install.sh`); fetch archive first; invoke `vault_update.decide` + `vault_commit.is_working_tree_dirty` via venv Python; print version diff; pre-snapshot `commit_framework_change(title=snapshot_title(...))`; existing pip install + `dist-templates/install.sh` re-run (forward `--auto-confirm` only); run `./vault health`; existing post `_vault_autocommit` (FR-001, FR-002, FR-003, FR-004, FR-005, FR-012; deps: T013, T003)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_vault_update.py::test_short_circuit_when_already_current`
    - Behavior: End-to-end via rendered `./vault` shim; verifies verb invokes `decide` noop path before any mutation (FR-002).
    - Tier: 3
  - **Test 2**: `tests/cli/test_vault_update.py::test_pre_snapshot_then_upgrade_topology`
    - Behavior: End-to-end via rendered shim; verifies pre-snapshot `commit_framework_change` runs before pip/install and yields FR-004 commit topology.
    - Tier: 3
  - **Test 3**: `tests/cli/test_vault_update.py::test_dirty_tree_refused_without_force`
    - Behavior: End-to-end via rendered shim; verifies verb calls `is_working_tree_dirty` and refuses without `--force` (FR-003).
    - Tier: 3
  - **Test 4**: `tests/cli/test_vault_update.py::test_health_failure_surfaces_nonzero`
    - Behavior: End-to-end via rendered shim; verifies `./vault health` invocation after install.sh and non-zero surfacing on failure (FR-005).
    - Tier: 3

  **TDD discipline**: required

- T015 [US1] Regenerate/refresh fixture vault `./vault` shims under test fixtures so integration tests exercise the rendered template from `templates/vault-script.sh.j2` (deps: T014)
- T016 [US1] Green T007–T012; verify SC-002 (<5 s short-circuit) and SC-003 (<2 s dirty refusal) on CI-local hardware (deps: T014, T015)
- T017 **Checkpoint**: US1 complete — safe upgrade path independently testable

---

## Phase 4: User Story 2 — Operator can roll back a bad upgrade (Priority: P1)

**Goal**: Document the supported rollback paths; no new CLI command (Clarification Q1).

**Independent Test**: Operator reads `docs/RELEASE.md` and can execute `git reset --hard HEAD~1` + `pip install research-framework==<old>` after a botched upgrade.

- [ ] T018 [US2] Rewrite the “Updating an existing vault” rollback subsection in `docs/RELEASE.md`: two-step (`git reset --hard HEAD~1` + `pip install research-framework==<old-version>`) **and** vault-tree-only `git revert HEAD`; drop stale “Known limitations of the current wrapper” prose (FR-011; deps: T017)
- [ ] T019 **Checkpoint**: US2 complete — rollback docs match FR-004 commit topology from US1

---

## Phase 5: User Story 3 — User-owned files survive upgrades (Priority: P2)

**Goal**: Honour `is_user_owned_after_first_write` wherever manifest-tracked files are rewritten during update/scaffold refresh.

**Independent Test**: Edit `settings.yaml` (manifest `true`), run `./vault update`, assert byte-identical content (SC-004). **Note**: spec prose cites `CLAUDE.md` but manifest marks it `false` — test canonical file is `settings.yaml` per research.md §5.

### Tests (write first — must FAIL)

- T020 [P] [US3] Write `tests/pipeline/test_vault_update_user_owned.py`: `is_user_owned(manifest, rel_path)` matrix against `dist-templates/scaffold-manifest.json` entries flagged `true`/`false` (FR-006; deps: T005)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_vault_update_user_owned.py::test_is_user_owned_true_for_manifest_flagged_paths`
    - Behavior: Load real `dist-templates/scaffold-manifest.json`; for a representative path with `is_user_owned_after_first_write: true` (e.g. `settings.yaml`), assert `is_user_owned` returns True.
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_vault_update_user_owned.py::test_is_user_owned_false_for_non_flagged_paths`
    - Behavior: For a manifest entry explicitly `false`, assert `is_user_owned` returns False.
    - Tier: 2
  - **Test 3**: `tests/pipeline/test_vault_update_user_owned.py::test_is_user_owned_matrix_matches_scaffold_manifest`
    - Behavior: Iterate manifest entries; assert helper agrees with each entry's `is_user_owned_after_first_write` flag (FR-006 contract matrix).
    - Tier: 2

  **TDD discipline**: required

- T021 [P] [US3] Add `test_user_owned_file_survives_upgrade` to `tests/cli/test_vault_update.py` — mutate `settings.yaml`, run update, assert byte-identical (FR-006, SC-004, FR-009; deps: T002, T017)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_vault_update.py::test_user_owned_file_survives_upgrade`
    - Behavior: Edit `settings.yaml` bytes in fixture vault; run `./vault update`; re-read file and assert byte-identical content (SC-004, FR-006). Uses `settings.yaml`, not `CLAUDE.md`.
    - Tier: 3

  **TDD discipline**: required

- T036 [P] [US3] Add direct FR-006 enforcement-site test invoking the scaffold/regenerate rewrite path (`src/research_framework/generator/scaffold.py` and/or `src/research_framework/cli/regenerate_shim.py`) with a manifest user-owned file (e.g. `settings.yaml`) present and edited — assert content preserved verbatim; must NOT rely vacuously on `./vault update` alone (research B1: update path does not re-scaffold) (FR-006; deps: T022)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/generator/test_scaffold.py::test_scaffold_preserves_user_owned_settings_yaml`
    - Behavior: Invoke scaffold rewrite/regenerate path on a vault with edited `settings.yaml`; assert file bytes unchanged verbatim (FR-006 enforcement site — NOT vacuous `./vault update` alone).
    - Tier: 3
  - **Test 2**: `tests/cli/test_regenerate_shim.py::test_regenerate_shim_preserves_user_owned_settings_yaml`
    - Behavior: Run regenerate-shim CLI/path with edited `settings.yaml`; assert content preserved verbatim per manifest guard.
    - Tier: 3

  **TDD discipline**: required

### Implementation

- T022 [US3] Implement `is_user_owned(manifest, rel_path) -> bool` in `src/research_framework/pipeline/vault_update.py`, loading manifest from `dist-templates/scaffold-manifest.json` or vault copy (FR-006; deps: T020)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_vault_update_user_owned.py::test_is_user_owned_true_for_manifest_flagged_paths`
    - Behavior: Unit test passes after implementation; MUST NOT hardcode path list — read from manifest.
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_vault_update_user_owned.py::test_is_user_owned_false_for_non_flagged_paths`
    - Behavior: Negative case for non-user-owned manifest entries.
    - Tier: 2

  **TDD discipline**: required

- T023 [US3] Wire `is_user_owned` guard into manifest rewrite paths: consult before overwriting in `src/research_framework/generator/scaffold.py` (and any update-triggered scaffold sync); `regenerate-shim` path via `src/research_framework/cli/regenerate_shim.py` where applicable — skip overwrite when user-owned (FR-006; deps: T022). **Do not** change `dist-templates/install.sh` stale-venv or version-check blocks (051 shipped).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/generator/test_scaffold.py::test_scaffold_skips_overwrite_when_user_owned`
    - Behavior: Trigger scaffold file write for a user-owned path; assert existing bytes on disk are not replaced.
    - Tier: 3
  - **Test 2**: `tests/cli/test_regenerate_shim.py::test_regenerate_shim_skips_user_owned_overwrite`
    - Behavior: Trigger regenerate-shim rewrite; assert user-owned `settings.yaml` (or equivalent) is skipped, not clobbered.
    - Tier: 3

  **TDD discipline**: required

- T024 [US3] Green T020–T021, T036 (deps: T023)
- T025 **Checkpoint**: US3 complete — user-owned regression locked

---

## Phase 6: User Story 4 — Air-gapped operators can upgrade offline (Priority: P3)

**Goal**: Document offline upgrade + channel/tag override policy.

**Independent Test**: Operator follows `docs/RELEASE.md` offline steps with wheel + bundle tarball; no network required.

- [ ] T026 [P] [US4] Document offline/air-gap upgrade in `docs/RELEASE.md`: `pip install research_framework-<ver>-py3-none-any.whl` + `bash <bundle>/install.sh` concrete commands (FR-007; deps: T018)
- [ ] T027 [P] [US4] Document channel/tag override in `docs/RELEASE.md`: `RV_GITHUB_REF=vX.Y.Z` pin, `RV_GITHUB_REF=main` dev tip, recommended tag-pin workflow (FR-008 SHOULD — docs-first; keep existing `main` default unless plan explicitly adds tag resolution in T014) (FR-008; deps: T018)
- [ ] T028 [US4] Add `[Unreleased]` entry to `CHANGELOG.md` documenting hardened `./vault update` wrapper, superseding CHANGELOG [0.2.33] “Known limitations” narrative (SC-006; deps: T018)
- [ ] T029 **Checkpoint**: US4 complete — operator docs cover offline + channel policy

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Smoke gate, lint/format gates, full suite, doc evidence.

- T030 Add `tests/cli/test_vault_update.py` to `build.sh::SMOKE_TESTS` array with comment citing spec 027 FR-010 / SC-005 (<15 s); verify pre-flight existence loop passes (FR-010; deps: T024) — **DONE 2026-06-03**: registered with provenance comment; new meta-test `tests/build/test_smoke_gate.py::test_vault_update_registered_in_smoke_tests` pins entry + comment; existing `test_smoke_gate_enforces_contract_tier::*_files_actually_exist_on_disk` confirms the path resolves.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/build/test_smoke_gate.py::test_vault_update_registered_in_smoke_tests`
    - Behavior: Parse or grep `build.sh::SMOKE_TESTS`; assert `tests/cli/test_vault_update.py` is present with a comment citing spec 027 FR-010 / SC-005 (FR-010 release gate).
    - Tier: 2

  **TDD discipline**: not required

- T031 [P] Run `.venv/bin/python -m ruff check .` — zero errors (separate gate) — **DONE**: green (fast loop at rebase + new test file).
- T032 [P] Run `.venv/bin/python -m ruff format --check .` — zero drift (separate gate from T031) — **DONE**: green.
- T033 Run full fast loop `.venv/bin/python -m pytest -m "not e2e" -q` green (deps: T030) — **DONE**: fast loop green at rebase onto main; new meta-test + registered CLI test + acceptance guard re-verified (17 passed) after the build.sh/spec edits.
- T034 [P] Validate operator walkthrough in `specs/027-vault-update-hardening/quickstart.md` against implemented `./vault update` behaviour (deps: T029) — **DONE**: reviewed; quickstart (happy/already-current/dirty/`--force`/rollback/channel-pin/downgrade/user-owned/offline) matches the shipped CLI test cases + `docs/RELEASE.md` references. No drift.
- T035 Populate Acceptance coverage evidence cells in `specs/027-vault-update-hardening/spec.md` (US1→`tests/cli/test_vault_update.py` topology/health/dirty/short-circuit tests; US2→`docs/RELEASE.md`; US3→`test_user_owned_file_survives_upgrade`; US4→`docs/RELEASE.md` offline section) (deps: T033) — **DONE**: cells populated (US1/US3 automated CLI tests; US2/US4 doc-backed guard-valid forms).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — **BLOCKS** all user stories
- **US1 (Phase 3)**: Depends on Foundational — 🎯 MVP; no dependency on US2–US4
- **US2 (Phase 4)**: Depends on US1 checkpoint (docs reference FR-004 topology shipped in US1)
- **US3 (Phase 5)**: Depends on US1 checkpoint (update verb must exist); independent of US2/US4
- **US4 (Phase 6)**: Depends on US2 RELEASE.md rewrite (T018) — extends same doc section
- **Polish (Phase 7)**: Depends on US1 + US3 minimum (smoke test needs full upgrade + user-owned cases); US2/US4 doc tasks should land before T034/T035

### User Story Dependencies

| Story | Priority | Depends on | Delivers |
| --- | --- | --- | --- |
| US1 | P1 🎯 MVP | Phase 2 | FR-001, FR-002, FR-003, FR-004, FR-005, FR-012 + core integration tests |
| US2 | P1 | US1 | FR-011 rollback documentation |
| US3 | P2 | US1 | FR-006 user-owned guard + regression test |
| US4 | P3 | US2 doc base | FR-007, FR-008, SC-006 |

### Within Each User Story

- Tests MUST be written and observed FAIL before implementation (T007–T012 before T013–T014; T020–T021 before T022–T023)
- `vault_update.py` pure functions before `vault-script.sh.j2` verb reorder
- Do not edit `dist-templates/install.sh` for 051-shipped behaviour (stale-venv, post-install version check)

### FR Coverage Map

| FR | Tasks |
| --- | --- |
| FR-001 | T007, T010, T013, T014 |
| FR-002 | T007, T008, T013, T014 |
| FR-003 | T003, T004, T009, T014 |
| FR-004 | T010, T014 |
| FR-005 | T012, T014 |
| FR-006 | T020, T021, T022, T023, T036 |
| FR-007 | T026 |
| FR-008 | T027 |
| FR-009 | T002, T008–T012, T021 |
| FR-010 | T030 |
| FR-011 | T018 |
| FR-012 | T007, T011, T013, T014 |
| SC-006 | T028 |

---

## Parallel Opportunities

- **Phase 1**: T002 parallel with T001 once branch confirmed
- **Phase 2**: T004 parallel with T005 after T003 (different files)
- **US1 tests**: T007–T012 all [P] after T002 + T005 exist
- **US3 tests**: T020 parallel with T021 prep
- **US4 docs**: T026 parallel with T027
- **Polish**: T031 parallel with T032; T034 parallel with T033 once green

### Parallel Example: US1 test-first batch

```bash
# After T002 + T005, launch all US1 red tests together:
.venv/bin/python -m pytest tests/pipeline/test_vault_update_decide.py tests/cli/test_vault_update.py -v
# Expect FAIL until T013–T014 land
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 Setup + Phase 2 Foundational
2. Complete Phase 3 US1 (T007–T017) — **STOP and validate** upgrade safety independently
3. Optionally ship US2 rollback docs immediately after (small doc-only increment)
4. Add US3 user-owned guard before declaring QW-6 closed for feeds-vault update gate

### Incremental Delivery

1. Setup + Foundational → dirty API + module skeleton ready
2. US1 → integration tests green → **MVP safe upgrade**
3. US2 → rollback docs
4. US3 → user-owned regression
5. US4 → offline/channel docs + CHANGELOG
6. Polish → smoke gate + lint + evidence cells

### Parallel Team Strategy

With two developers after Foundational:

- **Dev A**: US1 implementation (`vault_update.py` + verb reorder)
- **Dev B**: US1 integration tests (T008–T012) + US3 unit tests (T020) in parallel
- Serialize `templates/vault-script.sh.j2` and `vault_update.py` edits; serialize `docs/RELEASE.md` across US2/US4

---

## Notes

- **Reconcile scope**: post-upgrade `_vault_autocommit`, `--auto-confirm` forwarding, stale-venv rebuild, and install.sh importable-version check are **already shipped** — touch only if a regression test proves breakage
- **FR-006 test file**: use `settings.yaml`, not `CLAUDE.md` (manifest is source of truth)
- **FR-008**: SHOULD not MUST — default `RV_GITHUB_REF=main` may remain; document tag-pin as recommended path unless product opts into tag-default resolution in T014
- **install.sh positional arg**: research.md B1 notes vault dir arg is currently discarded — out of scope to fix installer ROOT_DIR semantics; FR-006 targets scaffold rewrite guards, not install.sh re-scaffold
- Foreman `### Testing Requirements` blocks authored 2026-06-03 (ADR-0010 test-design pre-step); implementer MUST NOT edit these blocks during `/speckit.implement`
