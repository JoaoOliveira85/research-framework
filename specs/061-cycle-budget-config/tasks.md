# Tasks: Cycle-budget configuration consolidation

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Status (2026-06-06)**: ✅ **SHIPPED 1.0.0rc3** (PR #126, squash `2d217be`). All
phases (FR1–FR5 + polish) implemented; Arm A foreman verifier passed; `ruff` clean,
2406 fast-loop tests + `build.sh --quality` (3/3 fixtures, 0 regressions) green.

**Input**: Design documents from `specs/061-cycle-budget-config/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, quickstart.md ✅

**Tests**: INCLUDED — Principle III (Test-First) is NON-NEGOTIABLE; each FR's tests are
written before its implementation. (The foreman test-design subagent will enrich this
file with `### Testing Requirements` blocks before `/speckit.implement`, per ADR-0010.)

**Organization**: grouped by **functional requirement** (FR1–FR5; this spec uses FRs,
not user stories). Order follows plan.md "Phase Sequencing".

## Format: `[ID] [P?] [FR] Description`

- **[P]**: parallelizable (different files, no dependency on an incomplete task)
- **[FRn]**: the functional requirement this task serves

---

## Phase 1: Setup

- T001 Confirm a green baseline on `rc3-spec-drafts`: `pytest -m "not e2e"` and `ruff check .` both pass before edits (so any failure later is attributable to this work).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the single precedence resolver consumed by FR1/FR3/FR4 (research.md D3).
**⚠️ CRITICAL**: FR1/FR3/FR4 cannot be wired until the resolver exists.

- T002 [P] Write `tests/cli/test_budget_resolver.py` (RED) pinning the resolver `src/research_framework/cli/_budget_resolve.py` (created in T003): assert the ladder `flag > pipeline.max_cycles > default`; deprecated `cycles.initial_max` warn-and-honour ONLY when `pipeline.max_cycles` absent; both-present ⇒ canonical wins + WARNING; `max_usd` resolves the same way; `max_cycles ≤ 0` raises.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-05. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_budget_resolver.py::test_flag_beats_pipeline_max_cycles_and_default`
    - Behavior: Call `resolve_cycle_budget` with `flag_max_cycles=8`, settings `pipeline.max_cycles=12`, no deprecated keys; assert `max_cycles==8` and `max_cycles_source=="flag"`. Pins FR3/D3 ladder top tier.
    - Tier: 2
  - **Test 2**: `tests/cli/test_budget_resolver.py::test_pipeline_max_cycles_beats_builtin_default`
    - Behavior: No flag; settings carry only `pipeline.max_cycles=12`; assert effective `max_cycles==12`, source `"settings"`.
    - Tier: 2
  - **Test 3**: `tests/cli/test_budget_resolver.py::test_deprecated_initial_max_warn_and_honour_only_when_canonical_absent`
    - Behavior: Settings with ONLY `cycles.initial_max=6` (no `pipeline.max_cycles`); assert `max_cycles==6`, deprecated alias honoured, and `deprecated_keys_seen` contains `"cycles.initial_max"`. MUST NOT drop the deprecated value when canonical absent (FR1 grace).
    - Tier: 2
  - **Test 4**: `tests/cli/test_budget_resolver.py::test_both_present_canonical_wins_deprecated_not_honoured`
    - Behavior: Settings with `pipeline.max_cycles=12` AND `cycles.initial_max=6`; assert `max_cycles==12` (NOT 6), canonical source wins, deprecated key listed but NOT applied — rc1 bug inversion (data-model.md).
    - Tier: 2
  - **Test 5**: `tests/cli/test_budget_resolver.py::test_max_usd_resolves_same_precedence_ladder`
    - Behavior: Mirror the max_cycles ladder for `max_usd` via flag > settings > default; assert both value and `max_usd_source` (Q3/FR3).
    - Tier: 2
  - **Test 6**: `tests/cli/test_budget_resolver.py::test_max_cycles_zero_or_negative_raises_usage_error`
    - Behavior: Pass flag or settings value `0` and `-1`; assert resolver raises a usage error (caller maps to exit 2) — MUST NOT coerce to positive (data-model.md).
    - Tier: 2

  **TDD discipline**: required

- T003 Create `src/research_framework/cli/_budget_resolve.py`: `BudgetResolution` dataclass (`max_cycles`, `max_cycles_source`, `max_usd`, `max_usd_source`, `deprecated_keys_seen`) + `resolve_cycle_budget(settings, *, flag_max_cycles, flag_max_usd)` implementing the data-model.md ladder; make T002 GREEN.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-05. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_budget_resolver.py::test_flag_beats_pipeline_max_cycles_and_default`
    - Behavior: Same as T002 Test 1 — implementation MUST make this pass without changing the test's assertions.
    - Tier: 2
  - **Test 2**: `tests/cli/test_budget_resolver.py::test_pipeline_max_cycles_beats_builtin_default`
    - Behavior: Same as T002 Test 2.
    - Tier: 2
  - **Test 3**: `tests/cli/test_budget_resolver.py::test_deprecated_initial_max_warn_and_honour_only_when_canonical_absent`
    - Behavior: Same as T002 Test 3.
    - Tier: 2
  - **Test 4**: `tests/cli/test_budget_resolver.py::test_both_present_canonical_wins_deprecated_not_honoured`
    - Behavior: Same as T002 Test 4.
    - Tier: 2
  - **Test 5**: `tests/cli/test_budget_resolver.py::test_max_usd_resolves_same_precedence_ladder`
    - Behavior: Same as T002 Test 5.
    - Tier: 2
  - **Test 6**: `tests/cli/test_budget_resolver.py::test_max_cycles_zero_or_negative_raises_usage_error`
    - Behavior: Same as T002 Test 6.
    - Tier: 2

  **TDD discipline**: required

**Checkpoint**: resolver unit-tested in isolation; FR phases can proceed.

---

## Phase 3: FR1 — One canonical settings key + deprecate `cycles.*`

**Goal**: `pipeline.max_cycles` is the sole canonical per-cycle-budget key; `cycles.initial_max`/`update_max` warn-and-honour for a grace period.
**Independent Test**: a settings file with only the deprecated key migrates + warns; both-present ⇒ canonical wins + warns.

- T004 [P] [FR1] Write `tests/pipeline/test_cycle_budget_settings.py` (RED): canonical-only / deprecated-only (migrated + 1 WARNING naming `pipeline.max_cycles`) / both-present (canonical wins + WARNING) / neither (built-in default).
- T005 [FR1] In `src/research_framework/_assets.py` `load_cycle_limits_from_settings`: emit a single `logging.WARNING` naming `pipeline.max_cycles` when `cycles.initial_max`/`update_max` is present, and route the value through the canonical field instead of silently overriding (confirm `pipeline/settings.py::VaultSettings.max_cycles` stays the typed canonical home — no schema change). Make T004 GREEN.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-05. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_budget_settings.py::test_canonical_only_uses_pipeline_max_cycles`
    - Behavior: Load settings with only `pipeline.max_cycles`; effective budget equals that value; zero WARNING records about deprecated keys (FR1 canonical-only acceptance).
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_cycle_budget_settings.py::test_deprecated_only_migrates_with_single_warning`
    - Behavior: Settings with ONLY `cycles.initial_max=6`; assert effective `max_cycles==6` via canonical redirect AND exactly one `logging.WARNING` whose message names `pipeline.max_cycles`. MUST use `caplog`, not stdout capture (FR1).
    - Tier: 2
  - **Test 3**: `tests/pipeline/test_cycle_budget_settings.py::test_both_present_canonical_wins_with_warning`
    - Behavior: Both `pipeline.max_cycles=12` and `cycles.initial_max=6`; effective==12; one WARNING that deprecated value was NOT used (FR1 / rc1 scenario).
    - Tier: 2
  - **Test 4**: `tests/pipeline/test_cycle_budget_settings.py::test_neither_key_uses_builtin_default`
    - Behavior: Settings omit both canonical and deprecated cycle keys; assert built-in default (≈20 per FR5/Q4) applies with source `"default"`.
    - Tier: 2

  **TDD discipline**: required

**Checkpoint**: deprecated keys never silently win again.

---

## Phase 4: FR2 — Remove the per-cycle budget + dollar cap from the spec schema

**Goal**: the spec carries no run-control budget; a leftover `max_cycles:`/`max_usd:` is silently ignored exactly like any unknown key (research.md D2 — no new code).
**Independent Test**: a spec with a stray `budget:` block parses fine and the values have zero effect.

- T006 [P] [FR2] Write `tests/spec/test_schema_budget_removed.py` (RED): a spec with `budget.max_cycles`/`budget.max_usd`/top-level `max_cycles` parses successfully and those values are NOT honoured (effective budget comes from settings/flag/default) — identical to an arbitrary `pizza:` key.
- T007 [FR2] In `src/research_framework/spec/schema.py`: remove `BudgetConfig.max_cycles`, `BudgetConfig.max_usd`, and top-level `SpecConfig.max_cycles` (leave `from_dict` `.get()`-based — it already drops unknowns). Make T006 GREEN.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-05. Do not edit during implementation._

  - **Test 1**: `tests/spec/test_schema_budget_removed.py::test_stray_budget_max_cycles_parses_with_zero_effect`
    - Behavior: Parse frontmatter containing `budget.max_cycles: 999`; assert parse succeeds (no validator error), schema carries no honoured field, and effective budget resolved elsewhere is NOT 999 — identical to unknown `pizza:` key (FR2/Q2).
    - Tier: 2
  - **Test 2**: `tests/spec/test_schema_budget_removed.py::test_stray_budget_max_usd_parses_with_zero_effect`
    - Behavior: Same as Test 1 for `budget.max_usd: 999`; no error, no effect on dollar-cap resolution (Q3).
    - Tier: 2
  - **Test 3**: `tests/spec/test_schema_budget_removed.py::test_stray_top_level_max_cycles_silently_ignored`
    - Behavior: Top-level `max_cycles: 12` parses fine; value dropped at `from_dict` with zero runtime effect — MUST assert no error AND no effect (FR2 acceptance).
    - Tier: 2
  - **Test 4**: `tests/spec/test_schema_budget_removed.py::test_budget_config_schema_fields_removed`
    - Behavior: Assert `BudgetConfig`/`SpecConfig` no longer expose `max_cycles` or `max_usd` attributes after schema removal (FR2 field deletion).
    - Tier: 2

  **TDD discipline**: required
- T008 [P] [FR2] In `src/research_framework/spec/simple.py`: stop emitting a `budget:` block (no `max_cycles`/`max_usd`).
- T009 [P] [FR2] Remove the cycle budget / dollar cap from `examples/*.spec.md`, `examples/research.spec.md`, and the detailed reference spec (`examples/detailed-vault-spec.md`); add the equivalent to their settings counterparts where one exists.
- T010 [FR2] In `src/research_framework/cli/research_generate.py`: delete the `spec.budget.max_cycles`/`spec.max_cycles` mutation block (the `cycles.initial_max` print at ~:106-114); the budget now comes from the resolver (wired in FR3).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-05. Do not edit during implementation._

  - **Test 1**: `tests/spec/test_schema_budget_removed.py::test_generate_path_does_not_mutate_spec_max_cycles_fields`
    - Behavior: Given a parsed spec (with stray budget fields if present), exercise the generate budget-resolution entry path and assert spec budget/max_cycles fields are unchanged in-place; effective budget MUST come from resolver output threaded to orchestrator, not spec mutation (FR2; rc1 root cause).
    - Tier: 3

  **TDD discipline**: required

**Checkpoint**: the spec no longer defines run-control budget; old specs still parse.

---

## Phase 5: FR3 — `--max-cycles N` last-word flag

**Goal**: a `--max-cycles` flag on generate/resume/phase3 is the top of the ladder.
**Independent Test**: flag beats settings beats default; invalid `N` → exit 2.

- T011 [P] [FR3] Write `tests/cli/test_max_cycles_flag.py` (RED): flag>settings; flag>default; absent flag falls through; `--max-cycles 0`/negative → exit 2 with a clear message.
- T012 [FR3] Add `--max-cycles` (and, per Q3, `--max-usd`) to the `generate` subparser in `src/research_framework/cli/_parser.py`.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-05. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_max_cycles_flag.py::test_generate_parser_declares_max_cycles_option`
    - Behavior: Parse argv containing `generate ... --max-cycles 5`; assert argparse recognises the flag and surfaces `max_cycles=5` to the handler (FR3 CLI surface).
    - Tier: 2
  - **Test 2**: `tests/cli/test_max_cycles_flag.py::test_generate_parser_declares_max_usd_option`
    - Behavior: Parse argv with `--max-usd 50.0`; assert flag is registered per Q3 on the generate subparser.
    - Tier: 2
  - **Test 3**: `tests/cli/test_max_cycles_flag.py::test_resume_and_phase3_parsers_declare_max_cycles`
    - Behavior: Assert `research resume` and `research phase3` subparsers also accept `--max-cycles` and `--max-usd` (plan D3 — all three entry points).
    - Tier: 2

  **TDD discipline**: required

- T013 [FR3] In `src/research_framework/cli/research_generate.py`: call `resolve_cycle_budget(...)` and thread `max_cycles`/`max_usd` into `run_cycles(...)`; same for `src/research_framework/cli/research_resume.py` and `src/research_framework/cli/research_phase3.py` (add the flags + call the resolver). Make T011 GREEN.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-05. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_max_cycles_flag.py::test_flag_beats_settings`
    - Behavior: Invoke generate/resume entry with `--max-cycles 3` and settings `pipeline.max_cycles=12`; assert threaded effective `max_cycles==3`, source `"flag"` (FR3 acceptance).
    - Tier: 3
  - **Test 2**: `tests/cli/test_max_cycles_flag.py::test_flag_beats_default`
    - Behavior: `--max-cycles 4` with minimal settings omitting cycle keys; assert effective==4, source `"flag"`.
    - Tier: 3
  - **Test 3**: `tests/cli/test_max_cycles_flag.py::test_absent_flag_falls_through_to_settings_then_default`
    - Behavior: Without flag: (a) settings `pipeline.max_cycles=12` ⇒ 12/settings; (b) no keys ⇒ built-in default — two parametrized cases (FR3).
    - Tier: 3
  - **Test 4**: `tests/cli/test_max_cycles_flag.py::test_invalid_max_cycles_zero_or_negative_exits_2`
    - Behavior: `--max-cycles 0` and `--max-cycles -1` each produce exit code 2 with a clear positive-integer message; MUST NOT start a run (FR3).
    - Tier: 2

  **TDD discipline**: required

- T014 [FR3] In `src/research_framework/pipeline/orchestrator.py`: delete the `budget_cap = spec.budget.max_usd` / `max_cycles = spec.budget.max_cycles` reads (~:517-518); take both from the threaded params.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-05. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_max_cycles_flag.py::test_orchestrator_uses_threaded_params_not_spec_budget`
    - Behavior: Stub/spy `run_cycles` during generate with settings `pipeline.max_cycles=7` and a spec carrying stray `budget.max_cycles=999`; assert orchestrator receives `max_cycles=7` from threaded params and does NOT honour spec budget fields (FR2/FR4 D4).
    - Tier: 3

  **TDD discipline**: required

**Checkpoint**: one documented last-word flag; the orchestrator is fully param-driven.

---

## Phase 6: FR4 — Overrides are LOUD and recorded

**Goal**: an override is a `logging.WARNING` (not a bare print) and the run report records `{configured, source, actual, exit_status}`; a constrained exit is first-class.
**Independent Test**: re-running the rc1 12→6 scenario surfaces a WARNING + run-report `cycle_budget`, not a buried print.

- T015 [P] [FR4] Write `tests/pipeline/test_run_report_budget_provenance.py` (RED): run report carries `cycle_budget {configured, source, actual, exit_status}`; a `max_cycles`-reached run ⇒ `exit_status="constrained"` and `actual==configured`; a clean run ⇒ `"complete"` and `actual≤configured`.
- T016 [FR4] Replace the resolution-time override `print` with a `logging.WARNING` via the spec-048 `_LOG` (suppressible by `--log-level error`) in `src/research_framework/cli/research_generate.py` (the old `cycles.initial_max` print is removed there; the loud WARNING now comes from the resolver it calls, also on resume/phase3 call sites).

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-05. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_cycle_budget_settings.py::test_budget_override_emits_logging_warning_not_print`
    - Behavior: Trigger a deprecated-key or precedence override during resolution; capture via `caplog` at WARNING and assert a log record names the override — MUST NOT appear on stdout as a bare `print` (FR4; rc1 buried-line fix).
    - Tier: 2
  - **Test 2**: `tests/pipeline/test_cycle_budget_settings.py::test_override_warning_suppressed_at_log_level_error`
    - Behavior: Same override with `--log-level error`; assert zero WARNING records while resolution still applies the effective budget (FR4 acceptance).
    - Tier: 2

  **TDD discipline**: required

- T017 [FR4] In `src/research_framework/pipeline/run_report.py`: add the additive `cycle_budget` object (JSON) + a "Cycle budget:" headline line in `run-report.md`, populated from the resolver + actual cycle count. Make T015 GREEN.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-05. Do not edit during implementation._

  - **Test 1**: `tests/pipeline/test_run_report_budget_provenance.py::test_run_report_json_includes_cycle_budget_provenance`
    - Behavior: After run finalisation, load run-report JSON; assert nested `cycle_budget` with keys `{configured, source, actual, exit_status}` per data-model.md Entity 2 (FR4).
    - Tier: 3
  - **Test 2**: `tests/pipeline/test_run_report_budget_provenance.py::test_max_cycles_reached_reports_constrained_exit`
    - Behavior: Harness a run stopped at max_cycles cap; assert `exit_status=="constrained"` and `actual==configured` — MUST NOT report `"complete"` (FR4/SC-002).
    - Tier: 3
  - **Test 3**: `tests/pipeline/test_run_report_budget_provenance.py::test_clean_completion_reports_complete_with_actual_lte_configured`
    - Behavior: Clean-exit run with fewer cycles than cap; assert `exit_status=="complete"` and `actual <= configured` (data-model.md invariant).
    - Tier: 3
  - **Test 4**: `tests/pipeline/test_run_report_budget_provenance.py::test_run_report_markdown_includes_cycle_budget_headline`
    - Behavior: Assert `run-report.md` contains a human "Cycle budget:" line echoing configured/source/actual/exit (FR4 markdown surface).
    - Tier: 3

  **TDD discipline**: required

- T018 [P] [FR4] In `pipeline/orchestrator.py` (~:806): reword the user-facing hint from "bump `budget.max_cycles`/`budget.max_usd`" to name `pipeline.max_cycles` + `--max-cycles`.

  ### Testing Requirements

  _Authored by test-design agent on 2026-06-05. Do not edit during implementation._

  - **Test 1**: `tests/cli/test_max_cycles_flag.py::test_constrained_exit_hint_names_pipeline_max_cycles_and_flag`
    - Behavior: Trigger the orchestrator user-facing hint for max_cycles reached; assert hint references `pipeline.max_cycles` and `--max-cycles`, and does NOT mention `budget.max_cycles` or `budget.max_usd` (FR4 reword).
    - Tier: 3

  **TDD discipline**: not required

**Checkpoint**: this is the provenance signal spec 063 §4.1 GA-004 consumes.

---

## Phase 7: FR5 — Sane shipped default; seeds agree

**Goal**: the two shipped seeds carry one canonical value (≈20) that never silently truncates a bootstrap; baselines hold.
**Independent Test**: `grep max_cycles settings*.yaml` shows one canonical value, no disagreement; `./build.sh --quality` shows no baseline movement.

- T019 [FR5] In `settings.yaml` and `settings.codex.yaml`: set `pipeline.max_cycles` to the agreed generous default (≈20) with a comment; remove the `cycles.initial_max`/`update_max` seed values (deprecated).
- T020 [FR5] Refresh the changed-seed sha in `dist-templates/scaffold-manifest.json`.
- T021 [FR5] Run `./build.sh --quality`; confirm the 3 spec-022 fixtures show **zero** baseline movement (if a baseline legitimately moves, re-cut intentionally and note why in the commit).

---

## Phase 8: Polish & Cross-Cutting

- T022 [P] Run `ruff check .` and `ruff format --check .` (both gates) — fix any new findings.
- T023 Run `pytest -m "not e2e"`; then the quickstart.md repro of the rc1 12→6 scenario to confirm SC-002 (loud + recorded).
- T024 [P] Confirm CHANGELOG `[Unreleased]`/`[1.0.0rc3]` notes the schema break (spec `budget.max_cycles`/`max_usd` removed) + the new `--max-cycles` flag (user-visible surface change).

---

## Dependencies & Execution Order

- **Setup (T001)** → **Foundational (T002–T003, the resolver)** blocks FR1/FR3/FR4.
- **FR1 (T004–T005)**, **FR2 (T006–T010)** are independent of each other (settings vs schema) and can run in parallel after the resolver.
- **FR3 (T011–T014)** depends on the resolver (T003) and on FR2's CLI de-mutation (T010).
- **FR4 (T015–T018)** depends on FR3 (the resolver call sites it instruments).
- **FR5 (T019–T021)** depends on FR1 (canonical key) being the read path.
- **Polish (T022–T024)** last.

### Parallel opportunities

- T004 ∥ T006 (different test files) once T003 lands.
- T008 ∥ T009 (simple.py vs example specs).
- Within FR4, T018 ∥ T015 (orchestrator hint vs test authoring).

## Implementation Strategy

**MVP = FR1 + FR2 + FR3 + FR4** (the silent-precedence root cause + loud reporting —
this is what gates the reference-vault re-run). FR5 (seed value) is a one-line config
change validated by the quality harness. Ship the whole spec together as part of
1.0.0rc3; FR4's `cycle_budget` provenance must land before 063's GA-004 gate.
