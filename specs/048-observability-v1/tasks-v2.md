---
description: "Task list for spec 048 v2 — Source-Consideration Ledger (MVP cut)"
---

# Tasks: Observability v2 — Source-Consideration Ledger (v2)

**Feature**: Source-Consideration Ledger (read-only post-run diagnostic) | **Branch**: `048-v2-source-ledger` | **Spec**: `specs/048-observability-v1/spec.md` § v2 scope | **Plan**: `plan-v2.md` | **Design**: `research-v2.md`, `data-model-v2.md`, `contracts/source-ledger-v2.contract.md`, `quickstart-v2.md`

**Prerequisites**: Locked plan-v2 + v2 design docs (2026-06-03). v1 `tasks.md` is SHIPPED — do not modify.

**Scope (binding)**: MVP = **FR-017 + FR-019 + FR-020 state machine** as `scripts/source_ledger.py` — zero pipeline change. **FR-018** (MCP routing-derived instrumentation), **FR-020-as-pipeline-gate**, and **FR-021** (health-header surfacing) are deferred per `plan-v2.md § Out of scope`.

**Organization**: v2 scope has no explicit user stories in `spec.md`; stories below are derived from `plan-v2.md`'s three implementation groups mapped to FRs:

| Story | FR(s) | Title | Priority |
| --- | --- | --- | --- |
| US1 | FR-020 | Deterministic verdict state machine (`resolve_verdict`) | P1 🎯 MVP |
| US2 | FR-017 | Per-cycle join + `cycle-NNN-source-ledger.json` artifact | P2 |
| US3 | FR-017, FR-019 | Run roll-up, CLI surface, fail-loud exit codes | P3 |

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Parallelizable — different files, no dependency on an incomplete task in the same phase.
- **[Story]**: US1, US2, US3 per the table above. Setup, Foundational, and Polish tasks carry no story label.
- Every task cites the FR number(s) it satisfies and lists exact file path(s).
- **TDD is mandatory** — tests are written and seen to **FAIL** before the implementation that makes them pass (Constitution Principle III; ADR-0010 foreman pattern applies at `/speckit.implement`, not here).
- Run tests/lint via `.venv/bin/python -m pytest` / `.venv/bin/python -m ruff` (**NOT** bare `python` — the base env has a stale editable install).

## Path Conventions

Single-project layout: package under `src/research_framework/`, maintainer tools under `scripts/`, tests under `tests/scripts/` (Tier 2), synthetic vault trees under `tests/fixtures/source_ledger/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm branch + capture a green baseline before any new code.

- [x] T001 Confirm on branch `048-v2-source-ledger` with a clean working tree (`git status`; `git rev-parse --show-toplevel` must print the worktree root). Capture baseline: `.venv/bin/python -m pytest -m "not e2e" -q` green; `.venv/bin/python -m ruff check .` and `.venv/bin/python -m ruff format --check .` both clean. Record pass count in the commit message body if opening an impl PR later.
- [x] T002 [P] Create empty test module `tests/scripts/test_source_ledger.py` with module docstring referencing `contracts/source-ledger-v2.contract.md` and Tier-2 placement (same tier as `tests/scripts/test_raw_capture.py`). No tests yet — import smoke only.
- [x] T003 [P] Scaffold fixture root `tests/fixtures/source_ledger/` with subdirs `used/`, `skipped_relevance/`, `access_fail/`, `quality_reject/`, `pipeline_drop/`, `not_reached/`, `reconcile/` (each will hold a minimal synthetic vault `_pipeline/` tree). Add `tests/fixtures/source_ledger/README.md` one-liner describing the layout.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared datatypes, script skeleton, and fixture helpers that all three user stories depend on. No verdict logic or join logic yet.

**⚠️ CRITICAL**: Do not start Phase 3+ until T009 is green.

- [x] T004 Define shared types in `scripts/source_ledger.py`: `Verdict` (`str` enum — six values per `contracts/source-ledger-v2.contract.md` §4), `VerdictSignals` (input bundle for the state machine per `data-model-v2.md` Entity 2), `SourceLedgerEntry` (`@dataclass` per Entity 1), `FAILURE_VERDICTS` frozenset, and `VERDICT_PRECEDENCE` ordered list (D2). Export `resolve_verdict` as a stub raising `NotImplementedError`. (FR-020 schema only)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_verdict_enum_has_six_members`
    - Behavior: Import `Verdict`; assert exactly the six contract §4 values exist (`USED`, `QUALITY_REJECT`, `ACCESS_FAIL`, `SKIPPED_RELEVANCE`, `PIPELINE_DROP`, `NOT_REACHED`).
    - Tier: 2
  - **Test 2**: `tests/scripts/test_source_ledger.py::test_failure_verdicts_frozenset`
    - Behavior: Import `FAILURE_VERDICTS`; assert it equals `{ACCESS_FAIL, PIPELINE_DROP, QUALITY_REJECT}` per `data-model-v2.md` Entity 2.
    - Tier: 2
  - **Test 3**: `tests/scripts/test_source_ledger.py::test_resolve_verdict_stub_raises_not_implemented`
    - Behavior: Call `resolve_verdict` with minimal `VerdictSignals`; assert `NotImplementedError` until T018 lands.
    - Tier: 2

  **TDD discipline**: required

- [x] T005 [P] Add `tests/scripts/conftest.py` (or extend if present) with helpers: `fixture_vault(path: Path) -> Path` (returns vault root), `run_ledger(vault, *args) -> subprocess.CompletedProcess` invoking `scripts/source_ledger.py` via `.venv/bin/python`, and `load_ledger_json(cycle_path) -> dict`. (shared test infra)
- [x] T006 [P] Author minimal shared spec fragment `tests/fixtures/source_ledger/_shared/research.spec.md` (3–4 `data_sources` entries spanning `behaviour`/`intent`/`domain`, mixed `required`, distinct `priority`) reused by all per-verdict fixtures. (fixture infra)
- [x] T007 [P] Implement `scripts/source_ledger.py::main(argv)` argparse skeleton per contract §1 (`--vault`, `--cycle`, `--write-rollup`, `--json`) with usage/structural validation only: missing `--vault` or absent `research.spec.md` → exit `2`. No ledger build yet. (FR-017/FR-019 CLI surface stub)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_cli_missing_vault_exits_2`
    - Behavior: Invoke `run_ledger` with no `--vault`; assert process exit code `2` per contract §2.
    - Tier: 2
  - **Test 2**: `tests/scripts/test_source_ledger.py::test_cli_missing_spec_exits_2`
    - Behavior: Point `--vault` at a temp dir lacking `research.spec.md`; assert exit code `2`.
    - Tier: 2

  **TDD discipline**: required

- [x] T008 [P] Add `tests/scripts/test_source_ledger.py::test_cli_missing_vault_exits_2` and `test_cli_missing_spec_exits_2` — assert exit code `2` from the T007 skeleton. Run first; expect FAIL until T007 lands. (contract §2 exit code 2)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_cli_missing_vault_exits_2`
    - Behavior: Commit failing test first; assert exit `2` when `--vault` omitted (contract §2).
    - Tier: 2
  - **Test 2**: `tests/scripts/test_source_ledger.py::test_cli_missing_spec_exits_2`
    - Behavior: Commit failing test first; assert exit `2` when `research.spec.md` absent (contract §2).
    - Tier: 2

  **TDD discipline**: not required

- [x] T009 Checkpoint: `.venv/bin/python -m pytest tests/scripts/test_source_ledger.py -v` green for T008; ruff clean on touched files.

**Checkpoint**: Foundation ready — user story phases may begin.

---

## Phase 3: User Story 1 — Deterministic verdict state machine (Priority: P1) 🎯 MVP

**Goal**: Ship the pure FR-020 decision function `resolve_verdict(signals) -> Verdict` plus run-roll-up precedence collapse `collapse_verdict(per_cycle: list[Verdict]) -> Verdict` with zero filesystem coupling so a later FR-020-in-pipeline promotion is a lift, not a rewrite.

**Independent Test**: `.venv/bin/python -m pytest tests/scripts/test_source_ledger.py -k "resolve_verdict or collapse_verdict" -v` — each terminal verdict and the D2 precedence order asserted in isolation.

### Tests (write first — must FAIL before impl)

- [x] T010 [P] [US1] Add `tests/scripts/test_source_ledger.py::test_resolve_verdict_used` — signals with `notes_generated > 0`, `notes_referencing > 0` → `Verdict.USED`. (FR-020 row 1)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_resolve_verdict_used`
    - Behavior: Pure-function call with `notes_generated=2`, `notes_referencing=1`; assert `Verdict.USED` (contract §4 row 1 / FR-020 terminal state 1).
    - Tier: 2

  **TDD discipline**: not required

- [x] T011 [P] [US1] Add `test_resolve_verdict_quality_reject` — `notes_generated > 0`, `notes_referencing == 0`, `quality_rejected=True` → `QUALITY_REJECT`. (FR-020 row 2)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_resolve_verdict_quality_reject`
    - Behavior: Signals with notes generated but zero referencing and `quality_rejected=True`; assert `Verdict.QUALITY_REJECT` (contract §4 row 2).
    - Tier: 2

  **TDD discipline**: not required

- [x] T012 [P] [US1] Add `test_resolve_verdict_access_fail` — `fetch_attempted=True`, `fetch_outcome="failed"` → `ACCESS_FAIL`. (FR-020 row 3)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_resolve_verdict_access_fail`
    - Behavior: Signals with `fetch_attempted=True`, `fetch_outcome="failed"`; assert `Verdict.ACCESS_FAIL` (contract §4 row 3).
    - Tier: 2

  **TDD discipline**: not required

- [x] T013 [P] [US1] Add `test_resolve_verdict_skipped_relevance` — non-empty `reason`, no fetch, zero notes → `SKIPPED_RELEVANCE`; assert `reason` preserved in entry builder helper when wired later. (FR-020 row 4)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_resolve_verdict_skipped_relevance`
    - Behavior: Non-empty agent `reason`, zero notes, no fetch; assert `Verdict.SKIPPED_RELEVANCE` (contract §4 row 4 — trusts agent reason incl. on required sources).
    - Tier: 2

  **TDD discipline**: not required

- [x] T014 [P] [US1] Add `test_resolve_verdict_pipeline_drop` — `notes_generated == 0`, empty `reason`, `stage_ran=True` → `PIPELINE_DROP`. (FR-020 row 5; FR-019 failure class)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_resolve_verdict_pipeline_drop`
    - Behavior: Zero notes, empty reason, `stage_ran=True`; assert `Verdict.PIPELINE_DROP` (contract §4 row 5 — FR-019 failure verdict).
    - Tier: 2

  **TDD discipline**: not required

- [x] T015 [P] [US1] Add `test_resolve_verdict_not_reached` — no scout/research signal (`stage_ran=False`, all zero) → `NOT_REACHED`. (FR-020 row 6)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_resolve_verdict_not_reached`
    - Behavior: `stage_ran=False`, all counters zero; assert `Verdict.NOT_REACHED` (contract §4 row 6).
    - Tier: 2

  **TDD discipline**: not required

- [x] T016 [P] [US1] Add `test_resolve_verdict_precedence_total_order` — parametrize conflicting signal combinations; assert the documented order wins: `USED > QUALITY_REJECT > ACCESS_FAIL > SKIPPED_RELEVANCE > PIPELINE_DROP > NOT_REACHED`. (FR-020 D2)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_resolve_verdict_precedence_total_order`
    - Behavior: Parametrize at least three conflicting signal bundles; assert highest-precedence verdict wins per contract §4 run-roll-up order.
    - Tier: 2

  **TDD discipline**: not required

- [x] T017 [P] [US1] Add `test_collapse_verdict_run_rollup` — per-cycle verdict lists collapse to the highest-precedence member (e.g. `[PIPELINE_DROP, USED, NOT_REACHED] → USED`). (FR-020 D2 run roll-up)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_collapse_verdict_run_rollup`
    - Behavior: Call `collapse_verdict` with mixed per-cycle lists; assert e.g. `[PIPELINE_DROP, USED, NOT_REACHED]` → `USED` (contract §4 D2).
    - Tier: 2

  **TDD discipline**: not required

### Implementation

- [x] T018 [US1] Implement `resolve_verdict(signals: VerdictSignals) -> Verdict` in `scripts/source_ledger.py` per `data-model-v2.md` Entity 2 terminal-state table + contract §4. Treat scout `searched`/`reason` as input evidence only (D1 — never terminal authority). (FR-020; depends T010–T017 failing)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_resolve_verdict_used`
    - Behavior: All six terminal-state rows exercised via T010–T015; scout `searched`/`reason` are inputs only (D1).
    - Tier: 2
  - **Test 2**: `tests/scripts/test_source_ledger.py::test_resolve_verdict_precedence_total_order`
    - Behavior: Conflicting signals resolve via documented total order (contract §4).
    - Tier: 2

  **TDD discipline**: required

- [x] T019 [US1] Implement `collapse_verdict(verdicts: list[Verdict]) -> Verdict` using `VERDICT_PRECEDENCE` in `scripts/source_ledger.py`. (FR-020 D2; depends T018)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_collapse_verdict_run_rollup`
    - Behavior: `collapse_verdict` returns highest-precedence member using `VERDICT_PRECEDENCE` (contract §4 D2).
    - Tier: 2

  **TDD discipline**: required

- [x] T020 [US1] Checkpoint: `.venv/bin/python -m pytest tests/scripts/test_source_ledger.py -k "resolve_verdict or collapse_verdict" -v` all green.

**Checkpoint**: FR-020 pure core complete — join work (US2) can begin.

---

## Phase 4: User Story 2 — Per-cycle source ledger join + artifact (Priority: P2)

**Goal**: For each reached cycle, join the six read-only input artifacts into one reconciled `SourceLedgerEntry` list and write `_pipeline/cycles/cycle-NNN-source-ledger.json` deterministically. Partial/aborted runs degrade to `NOT_REACHED`, never crash (D4).

**Independent Test**: Point the script at each synthetic fixture under `tests/fixtures/source_ledger/<verdict>/` with `--cycle N`; assert the emitted JSON matches contract §3 invariants (one entry per declared source, correct terminal `verdict`, `reason` non-null iff `SKIPPED_RELEVANCE`, `reconciled: true`).

### Tests (write first — must FAIL before impl)

- [x] T021 [P] [US2] Build `tests/fixtures/source_ledger/used/` — minimal vault with `research.spec.md`, `_pipeline/sources.db` (`source_cycles` row with `notes_generated=2`, `notes_referencing=1`), `cycle-001-scout.json` (`sources_consulted` row), stub research/quality artifacts. (FR-017 fixture)
- [x] T022 [P] [US2] Build fixtures `tests/fixtures/source_ledger/skipped_relevance/`, `access_fail/`, `quality_reject/`, `pipeline_drop/`, `not_reached/` — each encodes only the signals needed for its terminal verdict per contract §4. (FR-017 fixtures)
- [x] T023 [P] [US2] Build `tests/fixtures/source_ledger/reconcile/` — declared set in spec must match ledger entry names exactly; include a negative variant helper for exit-2 testing in US3. (reconciliation invariant)
- [x] T024 [P] [US2] Add parametrized `tests/scripts/test_source_ledger.py::test_build_cycle_ledger_terminal_verdicts` over the six verdict fixtures — asserts `entries[].verdict`, `reason` rule, and `reconciled is True`. (FR-017, FR-020)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_build_cycle_ledger_terminal_verdicts`
    - Behavior: Parametrize over six fixture dirs; assert each declared source gets exactly one contract §4 verdict; `reason` non-null iff `SKIPPED_RELEVANCE`; `reconciled is True`.
    - Tier: 2

  **TDD discipline**: not required

- [x] T025 [P] [US2] Add `test_build_cycle_ledger_reconciliation_invariant` on `reconcile/` fixture — `len(entries) == len(spec.data_sources)` and name sets equal. (FR-017 acceptance criterion)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_build_cycle_ledger_reconciliation_invariant`
    - Behavior: On `reconcile/` fixture, assert `{e["name"] for e in entries} == spec.data_sources names` (contract §5).
    - Tier: 2

  **TDD discipline**: not required

- [x] T026 [P] [US2] Add `test_partial_run_missing_scout_not_reached` — vault with spec + empty/missing scout for cycle 2 → all sources `NOT_REACHED` for that cycle; script exits 0 when no required failures. (D4)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_partial_run_missing_scout_not_reached`
    - Behavior: Missing scout artifact for a cycle; assert all sources `NOT_REACHED`, script exit `0` when no required failure verdicts (contract §7 D4).
    - Tier: 2

  **TDD discipline**: not required

- [x] T027 [P] [US2] Add `test_cycle_ledger_json_deterministic` — run builder twice on `used/`; assert byte-identical JSON (stable key order, entries sorted by `(priority, name)` per contract §3). (FR-017)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_cycle_ledger_json_deterministic`
    - Behavior: Invoke ledger writer twice on same inputs; assert byte-identical output (contract §3 determinism invariant).
    - Tier: 2

  **TDD discipline**: not required

### Implementation

- [x] T028 [US2] Implement `load_declared_sources(vault: Path) -> list[DataSourceConfig]` in `scripts/source_ledger.py` via `research_framework.spec.schema` + `research.spec.md` parse (role/required/priority/name). (FR-017; depends T004)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_build_cycle_ledger_reconciliation_invariant`
    - Behavior: Declared sources from spec drive one ledger entry each with correct `role`/`required`/`priority` fields (contract §3 + §5).
    - Tier: 2

  **TDD discipline**: required

- [x] T029 [US2] Implement per-cycle signal collectors in `scripts/source_ledger.py`: `_scout_signals(cycle_dir)`, `_source_db_signals(vault, cycle)`, `_incident_signals(cycle_dir)`, `_capture_failure_signals(vault, cycle)` (reuse `research_framework.pipeline.cycle_summary._aggregate_capture_failures`), `_quality_signals(cycle_dir)`. Each defensive on missing/malformed artifacts (WARN, no signal). (FR-017 join; depends T028)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_build_cycle_ledger_terminal_verdicts`
    - Behavior: Each of six verdict fixtures proves the correct collector fusion; missing/malformed inputs degrade to no signal, never crash (contract §7).
    - Tier: 2
  - **Test 2**: `tests/scripts/test_source_ledger.py::test_partial_run_missing_scout_not_reached`
    - Behavior: Missing scout yields `NOT_REACHED` for all sources without raising (contract §7).
    - Tier: 2

  **TDD discipline**: required

- [x] T030 [US2] Implement `build_cycle_ledger(vault: Path, cycle: int) -> list[SourceLedgerEntry]` — fuse collectors into `VerdictSignals`, call `resolve_verdict`, populate `evidence` map per `data-model-v2.md`. (FR-017, FR-020; depends T018, T029)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_build_cycle_ledger_terminal_verdicts`
    - Behavior: Join produces correct terminal verdict per source with populated `evidence` provenance map (`data-model-v2.md` Entity 1).
    - Tier: 2
  - **Test 2**: `tests/scripts/test_source_ledger.py::test_build_cycle_ledger_reconciliation_invariant`
    - Behavior: One entry per declared source after join (contract §5).
    - Tier: 2

  **TDD discipline**: required

- [x] T031 [US2] Implement `write_cycle_ledger(vault: Path, cycle: int, entries: list[SourceLedgerEntry]) -> Path` — emit `_pipeline/cycles/cycle-{NNN:03d}-source-ledger.json` with `schema_version`, `kind`, `reconciled`, sorted entries; use atomic write pattern consistent with `research_framework.pipeline.atomic_write.write_json`. (FR-017; spec 053 gate-consumable artifact; depends T030)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_cycle_ledger_json_deterministic`
    - Behavior: Written JSON matches contract §3 schema (`schema_version`, `kind`, `reconciled`, sorted entries); atomic write leaves no partial file on fault.
    - Tier: 2
  - **Test 2**: `tests/scripts/test_source_ledger.py::test_build_cycle_ledger_terminal_verdicts`
    - Behavior: Output path is `_pipeline/cycles/cycle-{NNN:03d}-source-ledger.json` with all six verdict enum values representable.
    - Tier: 2

  **TDD discipline**: required

- [x] T032 [US2] Wire `--cycle N` path in `scripts/source_ledger.py::main` to T031 only (no run roll-up yet). (FR-017; depends T031)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_build_cycle_ledger_terminal_verdicts`
    - Behavior: `run_ledger(fixture, "--cycle", "1")` writes only the per-cycle JSON; no run roll-up emitted (contract §1 `--cycle` semantics).
    - Tier: 2

  **TDD discipline**: required

- [x] T033 [US2] Checkpoint: `.venv/bin/python -m pytest tests/scripts/test_source_ledger.py -k "cycle_ledger or reconciliation or partial_run or deterministic" -v` green; manually inspect one fixture JSON against contract §3.

**Checkpoint**: Per-cycle ledger artifact ships — **spec 053 trunk-inversion gate can consume `cycle-NNN-source-ledger.json`**.

---

## Phase 5: User Story 3 — Run roll-up, CLI, and FR-019 fail-loud (Priority: P3)

**Goal**: Aggregate per-cycle ledgers into a `RunRollup` (per-source collapsed verdict, per-`role` histogram, `required_failures` list), render human table to stdout / optional `_pipeline/source-ledger-run.md` / `--json`, and exit non-zero when any **required** source has a failure verdict (`ACCESS_FAIL`, `PIPELINE_DROP`, `QUALITY_REJECT`) — uniformly, no special "unexplained silence" path (SL-Q2).

**Independent Test**: On a fixture with a required `ACCESS_FAIL` or `PIPELINE_DROP`, assert exit `1`, WARN block names the source; on all-required-OK fixture assert exit `0`.

### Tests (write first — must FAIL before impl)

- [x] T034 [P] [US3] Add `tests/scripts/test_source_ledger.py::test_build_run_rollup_by_role_histogram` — multi-cycle `used/` + mixed fixtures; assert `by_role` counts match collapsed verdicts. (FR-020 per-role reporting)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_build_run_rollup_by_role_histogram`
    - Behavior: Multi-cycle fixture; assert `by_role` histogram counts match collapsed verdicts per `data-model-v2.md` Entity 3.
    - Tier: 2

  **TDD discipline**: not required

- [x] T035 [P] [US3] Add `test_fr019_exit_0_when_all_required_ok` — all required sources `USED` or explained `SKIPPED_RELEVANCE`; assert process exit `0`. (FR-019)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_fr019_exit_0_when_all_required_ok`
    - Behavior: Required sources all `USED` or `SKIPPED_RELEVANCE`; assert CLI exit `0` (contract §2).
    - Tier: 2

  **TDD discipline**: not required

- [x] T036 [P] [US3] Add `test_fr019_exit_1_on_required_access_fail`, `test_fr019_exit_1_on_required_pipeline_drop`, `test_fr019_exit_1_on_required_quality_reject` — one required failure each; assert exit `1` and `required_failures` contains the source name. (FR-019 uniform failure)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_fr019_exit_1_on_required_access_fail`
    - Behavior: Required source with `ACCESS_FAIL`; assert exit `1` and source named in roll-up (contract §2 + §6 FR-019 block).
    - Tier: 2
  - **Test 2**: `tests/scripts/test_source_ledger.py::test_fr019_exit_1_on_required_pipeline_drop`
    - Behavior: Required source with `PIPELINE_DROP` (zero contribution + no reason); assert exit `1` uniformly — not a special category (SL-Q2).
    - Tier: 2
  - **Test 3**: `tests/scripts/test_source_ledger.py::test_fr019_exit_1_on_required_quality_reject`
    - Behavior: Required source with `QUALITY_REJECT`; assert exit `1` and `required_failures` contains source name.
    - Tier: 2

  **TDD discipline**: not required

- [x] T037 [P] [US3] Add `test_optional_source_failure_does_not_affect_exit` and `test_required_not_reached_exit_0` — optional (`required: false`) failure or required `NOT_REACHED` must not drive exit `1`. (FR-019; contract §4 row 6)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_optional_source_failure_does_not_affect_exit`
    - Behavior: Optional source `ACCESS_FAIL` with all required sources OK; assert exit `0` (contract §2 — optional never drives exit).
    - Tier: 2
  - **Test 2**: `tests/scripts/test_source_ledger.py::test_required_not_reached_exit_0`
    - Behavior: Required source collapsed to `NOT_REACHED`; assert exit `0` (contract §4 row 6 — WARN in roll-up, not a failure verdict).
    - Tier: 2

  **TDD discipline**: not required

- [x] T038 [P] [US3] Add `test_exit_2_on_reconciliation_break` — force declared/ledger name mismatch; assert exit `2` and `reconciled: false` in output. (contract §5)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_exit_2_on_reconciliation_break`
    - Behavior: Symmetric difference between declared and ledger sets; assert exit `2` and `reconciled: false` (contract §5).
    - Tier: 2

  **TDD discipline**: not required

- [x] T039 [P] [US3] Add `test_render_rollup_markdown_matches_contract` — `--write-rollup` on `access_fail/` fixture; snapshot the `## ⚠ Required-source failures (FR-019)` block structure per contract §6. (FR-017 roll-up)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_render_rollup_markdown_matches_contract`
    - Behavior: `--write-rollup` produces markdown with table, `## By role`, and `## ⚠ Required-source failures (FR-019)` block (contract §6).
    - Tier: 2

  **TDD discipline**: not required

- [x] T040 [P] [US3] Add `test_cli_json_stdout` — `--json` emits serializable `RunRollup` dict matching `data-model-v2.md` Entity 3 fields. (FR-017)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_cli_json_stdout`
    - Behavior: `--json` stdout parses as JSON with `vault`, `cycles_covered`, `entries`, `by_role`, `required_failures`, `reconciled` (`data-model-v2.md` Entity 3).
    - Tier: 2

  **TDD discipline**: not required

### Implementation

- [x] T041 [US3] Implement `build_run_rollup(vault: Path, cycles: list[int]) -> RunRollup` in `scripts/source_ledger.py` — load per-cycle ledgers (or rebuild via T030), collapse with T019, compute `by_role`, `required_failures`, `reconciled`. (FR-017, FR-020; depends T019, T030)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_build_run_rollup_by_role_histogram`
    - Behavior: Roll-up collapses per-cycle verdicts via precedence; `by_role` histogram populated (contract §6 + D2).
    - Tier: 2
  - **Test 2**: `tests/scripts/test_source_ledger.py::test_fr019_exit_0_when_all_required_ok`
    - Behavior: `required_failures` empty when all required sources non-failure verdicts.
    - Tier: 2

  **TDD discipline**: required

- [x] T042 [US3] Implement `compute_exit_code(rollup: RunRollup) -> int` — `0` if no required failure verdicts; `1` if any; `2` on structural/reconciliation errors. (FR-019; depends T041)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_fr019_exit_0_when_all_required_ok`
    - Behavior: Exit `0` when no required source in `FAILURE_VERDICTS`, including required `NOT_REACHED` (contract §2 + §4 row 6).
    - Tier: 2
  - **Test 2**: `tests/scripts/test_source_ledger.py::test_fr019_exit_1_on_required_access_fail`
    - Behavior: Exit `1` on required `ACCESS_FAIL` (contract §2).
    - Tier: 2
  - **Test 3**: `tests/scripts/test_source_ledger.py::test_fr019_exit_1_on_required_pipeline_drop`
    - Behavior: Exit `1` on required `PIPELINE_DROP` — same path as other failures (SL-Q2).
    - Tier: 2
  - **Test 4**: `tests/scripts/test_source_ledger.py::test_fr019_exit_1_on_required_quality_reject`
    - Behavior: Exit `1` on required `QUALITY_REJECT`; completes coverage of all three `FAILURE_VERDICTS` (contract §2 + `data-model-v2.md` Entity 2).
    - Tier: 2
  - **Test 5**: `tests/scripts/test_source_ledger.py::test_exit_2_on_reconciliation_break`
    - Behavior: Exit `2` when reconciliation invariant breaks (contract §5).
    - Tier: 2

  **TDD discipline**: required

- [x] T043 [US3] Implement renderers in `scripts/source_ledger.py`: `render_rollup_table(rollup) -> str` (contract §6 markdown table + By role + FR-019 WARN block), `render_rollup_json(rollup) -> str`. (FR-017)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_render_rollup_markdown_matches_contract`
    - Behavior: Human table includes Source/Role/Req/Verdict columns plus FR-019 WARN block (contract §6).
    - Tier: 2
  - **Test 2**: `tests/scripts/test_source_ledger.py::test_cli_json_stdout`
    - Behavior: `render_rollup_json` output matches Entity 3 field set.
    - Tier: 2

  **TDD discipline**: required

- [x] T044 [US3] Implement `--write-rollup` writer to `<vault>/_pipeline/source-ledger-run.md` (atomic text write; does **not** edit `run_report.py`). (FR-017)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_render_rollup_markdown_matches_contract`
    - Behavior: `--write-rollup` creates `_pipeline/source-ledger-run.md` with contract §6 structure; does not modify `run_report.py` output.
    - Tier: 2

  **TDD discipline**: required

- [x] T045 [US3] Complete `scripts/source_ledger.py::main` default path: discover all reached cycles under `_pipeline/cycles/`, write per-cycle JSONs (T031), build roll-up (T041), print table unless `--json`, honor `--write-rollup`, return T042 exit code. (FR-017, FR-019; depends T032, T041–T044)

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-03. Do not edit during implementation._

  - **Test 1**: `tests/scripts/test_source_ledger.py::test_fr019_exit_0_when_all_required_ok`
    - Behavior: Default CLI path (no flags) discovers cycles, builds roll-up, prints table, exits `0`.
    - Tier: 2
  - **Test 2**: `tests/scripts/test_source_ledger.py::test_optional_source_failure_does_not_affect_exit`
    - Behavior: End-to-end subprocess via `run_ledger`; optional failures do not change exit code.
    - Tier: 2
  - **Test 3**: `tests/scripts/test_source_ledger.py::test_required_not_reached_exit_0`
    - Behavior: End-to-end subprocess; required `NOT_REACHED` yields exit `0` (contract §4 row 6).
    - Tier: 2
  - **Test 4**: `tests/scripts/test_source_ledger.py::test_cli_json_stdout`
    - Behavior: `--json` suppresses human table; JSON roll-up on stdout only (contract §1).
    - Tier: 2
  - **Test 5**: `tests/scripts/test_source_ledger.py::test_fr019_exit_1_on_required_access_fail`
    - Behavior: End-to-end subprocess via `run_ledger` on `access_fail/` fixture; assert exit `1` and FR-019 block on stdout (contract §6).
    - Tier: 2

  **TDD discipline**: required

- [x] T046 [US3] Add module docstring to `scripts/source_ledger.py` documenting FR-018 MCP blind spot (contract §8) and deferred FR-021 surfacing — no new doc files. (operational caveat)
- [x] T047 [US3] Checkpoint: full `tests/scripts/test_source_ledger.py` green; manual smoke per `quickstart-v2.md` §1 on one fixture.

**Checkpoint**: Operator-facing MVP complete — FR-017 + FR-019 + FR-020 delivered read-only.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Lint gates, full-suite regression, quickstart validation.

- [x] T048 [P] Run `.venv/bin/python -m ruff check .` — zero errors on all touched files (`scripts/source_ledger.py`, `tests/scripts/test_source_ledger.py`, `tests/scripts/conftest.py`, fixtures if any `.py`). (quality gate)
- [x] T049 [P] Run `.venv/bin/python -m ruff format --check .` — zero diffs (**separate** gate from T048; both required before PR). (quality gate)
- [x] T050 Run `.venv/bin/python -m pytest tests/scripts/test_source_ledger.py -v` — full module green. (Tier 2)
- [x] T051 Run `.venv/bin/python -m pytest -m "not e2e" -q` — no regressions repo-wide. (integration)
- [x] T052 [P] Walk `quickstart-v2.md` §1–§3 commands against a synthetic fixture vault; fix any drift in script flags/help text only (do not edit quickstart in this task unless script behaviour was wrong). (docs validation)
- [x] T053 Confirm zero imports from `scripts/source_ledger.py` into `src/research_framework/pipeline/` (zero pipeline change structural check — grep/`ast` guard optional in test or manual note). (scope guard)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately.
- **Phase 2 (Foundational)**: Depends on Phase 1 — **blocks all user stories**.
- **Phase 3 (US1 / FR-020)**: Depends on Phase 2 — blocks US2/US3 (join calls `resolve_verdict`).
- **Phase 4 (US2 / FR-017 per-cycle)**: Depends on US1 — blocks US3 roll-up (needs per-cycle JSON builder).
- **Phase 5 (US3 / FR-019 + roll-up)**: Depends on US2.
- **Phase 6 (Polish)**: Depends on US3 checkpoint.

### User Story Dependencies

- **US1 (P1)**: After Foundational; no dependency on US2/US3.
- **US2 (P2)**: After US1 (`resolve_verdict` must exist).
- **US3 (P3)**: After US2 (needs `build_cycle_ledger` / per-cycle JSON writer).

### Within Each User Story

- Tests (T010–T017, T024–T027, T034–T040) MUST fail before implementation tasks in that story.
- Foundational types (T004) before state machine (T018) before join (T030) before roll-up (T041) before CLI completion (T045).

### FR Coverage

| FR | Status in this task list |
| --- | --- |
| FR-017 | US2 + US3 — per-cycle JSON, run roll-up, CLI |
| FR-019 | US3 — `required_failures`, exit codes 0/1/2 |
| FR-020 | US1 — state machine + precedence; consumed by US2/US3 |
| FR-018 | **Deferred** — blocked on spec 054 `managed`; documented in T046 + contract §8 |
| FR-021 | **Deferred** — health-header / `vault status` promotion |

### Cross-spec dependency (downstream consumer)

**Spec 053** (source authority strategy) trunk-inversion gate reads **`cycle-NNN-source-ledger.json`** — stable schema in `contracts/source-ledger-v2.contract.md` is the wire contract; US2 checkpoint (T033) is the hand-off point. Do not break field names or verdict enum without coordinating spec 053.

---

## Parallel Opportunities

- Phase 1: T002 ∥ T003
- Phase 2: T005 ∥ T006 ∥ T007 (after T004); T008 depends T007
- US1 tests: T010–T017 all parallel once T004 exists
- US2 fixtures: T021–T023 parallel; tests T024–T027 parallel after fixtures
- US3 tests: T034–T040 parallel once US2 green
- Polish: T048 ∥ T049 ∥ T052

---

## Implementation Strategy

### MVP First (minimum incremental)

1. Phase 1 + Phase 2 → shared skeleton green (T009)
2. Phase 3 (US1) → FR-020 pure core (T020)
3. **STOP optional** — state machine is importable for early unit testing

### Operator MVP (target before live runs)

1. Phases 1–2
2. US1 → US2 → **stop at T033** if time-boxed — delivers gate-consumable per-cycle JSON for spec 053
3. US3 (T047) → full FR-019 CI exit signal + roll-up table

### Full delivery

Phases 1–6 sequentially; estimated ~1.5–2 days wall-clock per `plan-v2.md`.

### Deferred promotion (out of scope for these tasks)

- FR-018 MCP `ACCESS_FAIL` discrimination → spec 054 + follow-on tasks
- FR-020 in-pipeline gate wiring → lift `resolve_verdict` into `pipeline/`
- FR-021 health-header surfacing → depends FR-013 / `vault status`
- Opt-in hard-fail via spec-033 `approval_gates` → post-MVP
- `build.sh::SMOKE_TESTS` membership → revisit when FR-019 becomes a release gate

---

## Notes

- Assumption resolved: v2 `spec.md` has no user-story headings — stories mapped from `plan-v2.md` task groups (state machine → per-cycle join → roll-up/CLI).
- Assumption resolved: run roll-up lands in stdout + optional `_pipeline/source-ledger-run.md`, **not** embedded in `run_report.py` (zero pipeline change; FR-021 deferred).
- Assumption resolved: `QUALITY_REJECT` requires quality-report signal tying rejection to the source — implement via gate/note metadata available in `cycle-NNN-quality-report.json` (collector detail left to implementer; test fixture in T022 pins expected behaviour).
- Known limitation documented, not tested as pass: MCP sources may read `PIPELINE_DROP`/`SKIPPED_RELEVANCE` until FR-018/spec 054 ships (contract §8).
