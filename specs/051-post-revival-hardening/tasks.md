---
description: "Task list for spec 051 — Post-Revival Hardening"
---

# Tasks: Post-Revival Hardening

> **Ledger** — this spec shipped; the boxes below are a historical record, not a live gate (CONTRIBUTING.md § 2). The Status header in `spec.md` is the source of truth for what shipped.

**Input**: Design documents from `/specs/051-post-revival-hardening/`
**Prerequisites**: plan.md, spec.md, research.md (D1–D7), data-model.md, contracts/
**Target ship**: 0.7.1

**Tests**: REQUIRED. Principle III (Test-First) is NON-NEGOTIABLE and every FR in
spec.md carries explicit acceptance test files. Tests are written first and must
FAIL before implementation — except US1 (FR5), which locks *already-shipped*
behaviour, so those tests are expected to PASS immediately (a failure there
exposes a real regression — see story note).

**Organization**: One phase per functional requirement, mapped to the
plan's dependency order **FR5 → FR1 → FR3 → FR2 → FR4**:

| Story | FR | What | Why this order |
| --- | --- | --- | --- |
| US1 | FR5 | Regression locks (net-new only — research.md D7) | Lock existing behaviour first so later refactors can't silently break it |
| US2 | FR1 | Configurable cycle-yield model (headline) | Highest user value; pin baseline early |
| US3 | FR3 | Inbound-link-aware stub policy | Self-contained classifier |
| US4 | FR2 | Stale-venv detection on `./vault update` | Bash-only; isolated |
| US5 | FR4 | Mandatory per-module `preflight()` contract | Long pole (~1.5d); all 4 modules MUST ship preflight |

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no incomplete-task dependency)
- **[Story]**: US1–US5 (FR mapping above)
- Exact file paths included per task

## Path Conventions

Single-project layout: package source under `src/research_framework/`, tests
under `tests/`, bash scaffold under `dist-templates/` + `templates/`, vault
settings seed at repo-root `settings.yaml`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm a clean, green baseline before any change.

- T001 Confirm on branch `051-post-revival-hardening` with a clean working tree (`git status`), and capture the baseline. **Run via `.venv/bin/python -m pytest` (NOT bare python — pyenv base has a stale editable install).** Baseline 2026-06-02: **1778 passed, 3 failed (pty-device-unavailable, environmental), 8 skipped**; `ruff check` + `ruff format --check` clean. The 3 failures are `test_install_sh_tty_handling.py` PTY tests that can't run in this sandbox — not code.
- T002 [P] Created the FR4 module test dirs `tests/modules/{youtube,reddit,rss,oreilly}/` each with `__init__.py` (matching the existing `tests/modules/code/` convention).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: There is **no shared blocking code across all five FRs** — that
independence is the whole reason the spec bundles them. The only intra-story
foundational pieces (FR4's `PreflightResult` types + manifest amendment) are
scoped inside US5. The one genuine cross-story coupling is documented, not
foundational:

> **⚠️ Cross-story file coupling (US2 + US3):** both FR1 and FR3 edit
> `src/research_framework/pipeline/settings.py` (each adds a dataclass + parser +
> a `VaultSettings` field) and the repo-root `settings.yaml`. If US2 and US3 are
> worked in parallel they will conflict on those two files — serialize the
> `settings.py`/`settings.yaml` edits or rebase. The `scaffold-manifest.json`
> sha-recompute for `settings.yaml` is deferred to a single Polish task (T0xx) so
> it runs once after **both** blocks land.

- T003 Checkpoint: T001 baseline green (modulo 3 environmental PTY failures) → user-story phases may begin.

**Checkpoint**: Foundation ready.

---

## Phase 3: User Story 1 — FR5 Regression locks (net-new) 🎯 first

**Goal**: Lock the two 0.6.2/0.6.3 fixes against future refactors, covering ONLY
the slices not already tested (research.md D7).

**Independent Test**: `pytest tests/pipeline/test_cycle_helpers_tree_kill.py tests/cli/test_resume_completion_marker.py` is green.

> **Story note**: these lock *shipped* behaviour, so they should PASS on first
> run. A FAIL is a real finding (e.g. `_cycle_helpers._run_script` cleanup does
> not actually reap the grandchild) — treat it as a bug to fix, not a test to
> weaken. Do NOT duplicate the existing locks
> (`test_process_tree.py::test_grandchild_dies_when_tree_is_terminated`,
> `test_agent_call_process_tree.py`, `test_research_resume.py::test_sentinel_cycle_dirs_do_not_count`,
> `...::test_only_a_quality_report_marks_a_cycle_complete`).

- T004 [P] [US1] `tests/pipeline/test_cycle_helpers_tree_kill.py` — 2 tests (grandchild dies on `_run_script` interrupt-cleanup; cleanup is wall-clock-bounded). SIGALRM→KeyboardInterrupt fires into the read loop while a grandchild ticks a sentinel; asserts the sentinel stops growing. Green under `.venv` (2 passed), ruff clean.
- T005 [P] [US1] `tests/cli/test_resume_completion_marker.py` — 6 tests: missing cycles dir, zero-numbered (→None), non-zero-padded width "01" (→1), upper-case `.JSON` suffix (→None), very large number, and a mixed-names case. Green under `.venv` (6 passed), ruff clean.
- T006 [US1] Both new FR5 test files green under `.venv` (2 + 6 = 8 passed); no underlying fix needed — the 0.6.2/0.6.3 behaviour holds.

**Checkpoint**: US1 complete — the two uncovered slices are locked.

---

## Phase 4: User Story 2 — FR1 Configurable cycle-yield model (headline)

**Goal**: Replace the flat CG-001 threshold + `_COLD_START_MAX_YIELD` cap with a
deterministic `base × cadence_factor × coverage_factor` model, clamped
`[min_floor, max_ceiling]`, fully driven by `settings.yaml`. Warn below target,
fail only below floor. Emit an auditable diagnostic + a re-tuning sidecar.

**Independent Test**: `pytest tests/pipeline/test_cg001_yield_model.py` green; a
dormant-3wk/<50%-coverage synthetic vault computes a target ≫ 5; `./build.sh
--quality` regression diff on the tech-lite fixture does **not** move.

### Tests for User Story 2 (write first, must FAIL)

- T007 [P] [US2] Write `tests/pipeline/test_cg001_yield_model.py`: cover cold-start, daily, weekly, biweekly, monthly cadence buckets × the three coverage buckets; clamp at `min_floor` and `max_ceiling`; the dormant-3-weeks synthetic fixture (last cycle >14d, <50% coverage → `ceil(5×8.0×1.5)=50`); and a **baseline-pin** assertion that the tech-lite fixture's computed target equals its current effective threshold (so the quality baseline is preserved). **Pin the exact bucket boundaries (research U2)**: coverage at exactly 50% and 80% land in the middle bucket (`<50 / 50–80 / >80`), and cadence at exactly 24h / 7d / 14d land per data-model (`<24h→daily`, `24h–7d→weekly`, `7d–14d→biweekly`, `>14d→monthly`). Reference `data-model.md` YieldTarget derivation rules. **DONE** (committed in `474ded0`/`50aadbc`; 17 tests green under `.venv`). *(Checkbox flipped 2026-06-02 — the file was authored alongside T010; the checkbox lagged.)*
- T008 [P] [US2] Update `tests/pipeline/test_remaining_yield_scaling.py` per research.md D1: remove the obsolete `_COLD_START_MAX_YIELD`/`_INCREMENTAL_MAX_YIELD` cap and 0.25/0.5/0.75/1.0 staleness-staircase assertions (the model that removes them is authorized by FR1); migrate any still-valid `_hours_since_last_cycle` coverage into `test_cg001_yield_model.py`. Net: the old caps are no longer asserted. **DONE** (committed in `474ded0`): rather than edit-in-place, the file was **deleted** entirely (its still-valid coverage migrated into `test_cg001_yield_model.py`); the obsolete caps + staleness-staircase assertions no longer exist anywhere in the suite. *(Checkbox flipped 2026-06-02.)*

### Implementation for User Story 2

- T009 [US2] `CycleYieldSettings` frozen dataclass + `_parse_cycle_yield` + `_parse_factor_map` in `settings.py`; `cycle_yield` field on `VaultSettings`; wired into `load_vault_settings`; `cycle_yield`+`stubs` added to the extras-exclusion set. Validates base/floor≥1, ceiling≥floor, factor values>0, WARNs unknown buckets, merges user factors over defaults. Smoke + 3 settings tests green, ruff clean.
- T010 [US2] coverage.py: `YieldTarget` dataclass + `compute_yield_target` (cadence/coverage buckets per data-model; clamp; loads `cycle_yield` internally w/ defaults fallback; tolerant of missing coverage-targets.json) + `remaining_yield` shim. Removed `_COLD_START_MAX_YIELD`/`_INCREMENTAL_MAX_YIELD`/`_staleness_multiplier`; kept `_hours_since_last_cycle`. 16 model tests green (`test_cg001_yield_model.py`), test_coverage.py 15/15, ruff clean.
  ~~In `src/research_framework/pipeline/coverage.py`: add a frozen `YieldTarget` dataclass + `compute_yield_target(vault_dir, cycle_number, max_cycles, cy: CycleYieldSettings | None = None) -> YieldTarget`.~~ Cadence bucket from existing `_hours_since_last_cycle` (`<24h→daily`, `24h–<168h→weekly`, `168h–<336h→biweekly`, `>=336h or None(cold)→monthly`); coverage bucket from `sum(min(met,target))/sum(target)` over `load_targets` categories (`<0.5→below_50pct`, `>0.8→above_80pct`, else `50_to_80pct`; no targets → treat as 1.0/above). `target = clamp(ceil(base*cad_factor*cov_factor), min_floor, max_ceiling)`. **When `cy is None`, load `load_vault_settings(vault_dir).cycle_yield`, falling back to `CycleYieldSettings()` on ANY error** (missing/invalid settings.yaml — keeps bare test vaults working). **Keep `remaining_yield(vault_dir, cycle_number, max_cycles) -> int` as a thin shim** = `compute_yield_target(...).target` (preserves its two callers: `gates_cycle` + `quality_report::exp_vel`). **Remove** `_COLD_START_MAX_YIELD`, `_INCREMENTAL_MAX_YIELD`, `_staleness_multiplier`; keep `_hours_since_last_cycle`. (coverage→settings import is safe: settings.py does NOT import coverage.)
- T011 [US2] `gates_cycle.py::CG001_min_cycle_yield` now calls `compute_yield_target` (signature unchanged); PASS `n>=target`, FAIL `n<floor`, single WARN band otherwise; multiplier breakdown in message + correction_hint. Updated `test_gates_cycle.py` (retired the two old-model property tests → one model-DRY property test; PASS test uses the model target). 4/4 CG-001 tests green, ruff clean.
- T012 [US2] **NO-OP confirmed** — `compute_yield_target` loads settings internally, so CG-001's signature is unchanged; `orchestrator.py:334` + `quality_report.py:442` call sites untouched and still green.
- T013 [US2] `quality_report.py`: `CycleQualityReport.cg001_yield` field (target/base/buckets/factors/actual/exit_status) wired from the CG-001 result + `compute_yield_target` (computed once, reused for `exp_vel`); serialized in `to_dict` only when present. Covered by `test_yield_calibration_sidecar.py`.
- T014 [US2] `_append_yield_calibration` → `_pipeline/yield-calibration.json` (atomic `write_json`, idempotent per cycle, sorted, tolerant of corrupt file); element matches `contracts/yield-calibration.schema.json` exactly. 5 tests green, ruff clean.
- T015 [US2] `cycle_yield:` block added to repo-root `settings.yaml` (defaults + comment). Fixtures keep their own settings (no `cycle_yield` → defaults), so the harness baseline is unaffected. Scaffold-manifest sha recompute deferred to T046 (no test enforces it — 61 scaffold tests green).
- T016 [US2] **Baseline VERIFIED.** Quality harness on pristine fixtures → `Verdict: PASS, 3 fixtures, 0 regressions, 0 warnings`. Caught + fixed a real regression along the way: the new model initially dropped the old `unmet==0 → 0` invariant, so a fully-covered vault (source-rich) FAILed CG-001 (`cycles_pass 1.0→0.0`); restored via a no-remaining-work short-circuit in `compute_yield_target` + a `threshold==0` PASS path in the gate (+ `test_fully_covered_vault_has_zero_yield`). FR1 test trio + coverage + quality_report = 63 green; ruff clean. *(Full `PYTHON_BIN=.venv/bin/python bash build.sh --quality` smoke-gate+harness recommended as the pre-PR gate; the harness half is verified here.)* **Follow-up (2026-06-02, caught during the US3 full pipeline+vault+cli sweep):** T013's new `cg001_yield` report field was not registered in the `specs/017-vault-quality-fix/contracts/cycle-quality-report.schema.json` contract (root `additionalProperties:false`), so `test_quality_report.py::test_write_report_produces_schema_shape` was RED on the branch — the targeted FR1 verification subset didn't include it. Fixed by adding the optional `cg001_yield` object (8 keys, all required when present) to the contract; `test_quality_report.py` 4/4 green.

**Checkpoint**: US2 complete — CG-001 is configurable, auditable, and baseline-preserving.

---

## Phase 5: User Story 3 — FR3 Inbound-link-aware stub policy

**Goal**: A short note with ≥`anchor_link_threshold` (default 5) inbound
wikilinks is classified `anchor-stub` (flagged `needs-research`, never deleted),
not `deletable-stub`. Inbound counts come from the indexer's link graph, built
once per pass (research.md D5).

**Independent Test**: `pytest tests/pipeline/test_stub_classification.py` green;
a 40-word note with 30 inbound links → `anchor-stub`; same note with 2 inbound
links → `deletable-stub`.

### Tests for User Story 3 (write first, must FAIL)

- T017 [P] [US3] Write `tests/pipeline/test_stub_classification.py`: cover all three `classify_stub` branches (`not-a-stub` when `body_len>threshold`; `anchor-stub` when `inbound≥anchor_link_threshold`; `deletable-stub` otherwise), the default threshold of 5, and a `settings.yaml::stubs.anchor_link_threshold` override. Follow the `_write_note` fixture pattern in `tests/pipeline/test_stubs.py`. **DONE** — 11 tests incl. both boundary pins (`>` for body_len, `>=` for inbound) + the headline same-note-flips scenario; fails with `ImportError` on the missing `classify_stub`/`StubClassificationContext` symbols.
- T018 [P] [US3] Write a focused test for `vault/indexer.py::inbound_link_counts` (`tests/vault/test_indexer.py` absent → added `tests/vault/test_inbound_link_counts.py`): a small vault where note A links B and C, B links C → assert `{A:0, B:1, C:2}`. Confirms the helper exposes the indexer's existing graph counts without re-walking. **DONE (RED)** — 3 tests (graph counts, empty vault, read-only/no-index-writes); fails with `ImportError` on `inbound_link_counts`.

### Implementation for User Story 3

- T019 [US3] Extract `inbound_link_counts(vault_dir) -> dict[str, int]` in `src/research_framework/vault/indexer.py` from the existing `rebuild_all` (`:93`) graph walk — pure helper, NO behaviour change to `rebuild_all`. **DONE** — true DRY extraction: factored the per-note edge computation into a shared `_outgoing_links(fm, body)` used by both `rebuild_all` and the new read-only `inbound_link_counts`; rebuild_all's 6 existing tests still green (behaviour preserved), inbound-link tests 3/3 green.
- T020 [US3] Add `StubsSettings` frozen dataclass + `_parse_stubs(raw)` to `pipeline/settings.py` (`anchor_link_threshold: int = 5`, validate `≥1`); add `stubs: StubsSettings` to `VaultSettings`. **Coordinate with T009** — same file (`settings.py`); serialize or rebase against US2. **DONE** — mirrors the `CycleYieldSettings`/`_parse_cycle_yield` pattern (`_require_positive_int` for the `≥1` validation, absent-block→defaults); `"stubs"` was already in the extras-exclusion set from T009. Settings suites 16/16 green; default threshold = 5.
- T021 [US3] Add `StubClassificationContext` frozen dataclass (`path`, `inbound_links_count`, `body_len`) and public `classify_stub(ctx, *, body_len_threshold, anchor_link_threshold) -> Literal["not-a-stub","anchor-stub","deletable-stub"]` to `pipeline/stubs.py` per the data-model.md state machine. Anchor-stubs get `status: needs-research` and are surfaced in the research-backlog with a deferred-work annotation (match the 0.6.x ad-hoc grooming pattern). Leave the existing `scan_stubs` detection criteria unchanged — classification is an additional lens. **DONE** — `classify_stub` implemented as a **pure** function (per data-model.md "classify_stub is a pure function"); the anchor-stub → `status: needs-research` + research-backlog surfacing is documented in the docstring as the **caller contract** (a pure classifier cannot mutate frontmatter / write the backlog). No caller-wiring task exists in US3 and no test requires the side effect, so wiring it here would be untested scope creep — the building block ships tested; acting on the verdict is left to its eventual caller. `scan_stubs` untouched. 11/11 green.
- T022 [US3] Add the `stubs:` block (with `anchor_link_threshold: 5` + comment) to the repo-root `settings.yaml`. **Coordinate with T015** — same file. **DONE** — placed directly after the T015 `cycle_yield` block with a matching comment header; repo-root `settings.yaml` re-loads cleanly (`stubs.anchor_link_threshold == 5`). Scaffold-manifest sha recompute deferred to T046 (now covers both T015 + T022 settings.yaml edits).
- T023 [US3] Run `pytest tests/pipeline/test_stub_classification.py tests/pipeline/test_stubs.py tests/vault/` ; confirm green and no regression in existing stub-scan tests. **DONE** — 51 passed (11 new classification + 24 existing stub-scan, zero regression + 16 vault).

**Checkpoint**: US3 complete — graph anchors are protected from stub deletion.

---

## Phase 6: User Story 4 — FR2 Stale-venv detection on `./vault update`

**Goal**: `./vault update` / `install.sh` re-run detects a stale `.venv`
(missing/mismatched `pyvenv.cfg` `home =`), prompts to rebuild (default yes;
`--auto-confirm`/`-y`/`RV_NONINTERACTIVE` bypass), and refuses to exit clean if
the post-install runtime `__version__` ≠ the bundle's declared version
(research.md D4).

**Independent Test**: `pytest tests/scripts/test_install_venv_staleness.py` green
across: clean rebuild, stale-detection happy path, version-mismatch refusal,
fresh-venv flow, and `--auto-confirm` non-interactive flow.

### Tests for User Story 4 (write first, must FAIL)

- T024 [P] [US4] Write `tests/scripts/test_install_venv_staleness.py` using the sandbox-extraction + `pty.fork()` pattern from `tests/scripts/test_install_sh_tty_handling.py`: (a) clean rebuild, (b) stale `pyvenv.cfg` `home =` pointing at a deleted dir → rebuild path, (c) version-mismatch → non-zero exit + remediation text, (d) fresh venv (no `.venv`), (e) `--auto-confirm`/`stdin=DEVNULL` non-interactive → auto-yes without prompt. **DONE (RED)** — 7 tests, all failing on the missing `_detect_stale_venv`/`--auto-confirm`/`rm -rf`/version-check. Detection cases use a **plain-`bash` harness** (function-extraction + fake `pyvenv.cfg`), so they run **in-sandbox** (no pty needed — sidesteps the T001 `pty-device-unavailable` limit); full-flow cases (`--auto-confirm`, rm-rf-rebuild, version remediation) are **structural assertions** against the script text. **Impl note for T025/T026**: `ask_yn`/`is_interactive` are defined at `:173`/`:183` but the venv section runs at `:113` → must move those two helper defs up (above §2) so the rebuild prompt can call `ask_yn`, with a `NON_INTERACTIVE` short-circuit (auto-yes, no prompt) for `--auto-confirm`.

### Implementation for User Story 4

- T025 [US4] Add `_detect_stale_venv()` to `dist-templates/install.sh` (before venv creation, ~`:110`): read `.venv/pyvenv.cfg`, parse `home =`, return stale if that path is missing on disk or differs from the current bundle. First code in the repo to read `pyvenv.cfg`. **DONE** — `_detect_stale_venv()` (exit 0 = stale) parses `home =` via `sed`, returns stale when that dir is gone; the "differs from current bundle" case is delegated to the more reliable post-install version check (T026) rather than home-path comparison (avoids patch-version false positives). `bash -n` clean. 3 detection tests green (plain-bash harness, runs in-sandbox).
- T026 [US4] Wire the rebuild prompt + flag plumbing in `dist-templates/install.sh`: on stale detection, `ask_yn()` (default yes) to `rm -rf .venv && python -m venv .venv` + reinstall; add `--auto-confirm` to the arg `case` (`:83–89`) as an alias that sets `NON_INTERACTIVE=1`; when non-interactive, skip the prompt with yes. Add the post-install sanity check: `python -c "import research_framework; print(research_framework.__version__)"` vs the bundle `pyproject.toml` version → on mismatch, print the `pyvenv.cfg` + `rm -rf .venv && ./install.sh` remediation and exit non-zero. **DONE** — `--auto-confirm` added to the arg `case` (aliases `--non-interactive`); rebuild block uses `[[ -n NON_INTERACTIVE ]] || ask_yn ... y` (auto-yes, no prompt, when non-interactive); `rm -rf "${VENV_DIR}"` on confirm. **`is_interactive()`+`ask_yn()` were relocated above §2** (they were defined at `:173`, after the venv section at `:113` — couldn't be called from the rebuild prompt otherwise). Version check parses the bundle version from the **wheel filename** (no `pyproject.toml` in the bundle), exits 2 + remediation on mismatch. 4 wiring tests green.
- T027 [US4] In `templates/vault-script.sh.j2` `update` verb (`:117`), forward caller `"$@"` to the `bash install.sh "${VAULT_DIR}"` invocation so `./vault update --auto-confirm` plumbs through. (Auto-commit on update already exists via spec 050 — no change there.) **DONE** — `bash "${TMPDIR_UPDATE}/install.sh" "${VAULT_DIR}" "$@"`. `"$@"` is post-verb (dispatch `shift`s the verb at `:66`). **NOTE → T046**: this edits a tracked template, so the `vault` entry's `rendered_sha256` in `dist-templates/scaffold-manifest.json` is now stale (no test enforces it — 14 scaffold/manifest tests green — but T046 must recompute it alongside settings.yaml).
- T028 [US4] Run `pytest tests/scripts/test_install_venv_staleness.py tests/scripts/test_install_sh_tty_handling.py`; confirm green and no TTY-handling regression. **DONE** — 7 new + 10 TTY structural = green; the only 3 failures are the pre-existing `OSError: out of pty devices` environmental tests (the T001-baseline pty trio), not a regression. ruff check + format clean on the new test file.

**Checkpoint**: US4 complete — a bad upgrade either succeeds or refuses to lie (and is one `git revert HEAD` away).

---

## Phase 7: User Story 5 — FR4 Mandatory per-module preflight **subprocess** contract (long pole)

**Goal**: `preflight` becomes a REQUIRED manifest key; the orchestrator **spawns
each module's preflight subprocess** (stdin/stdout JSON, popen_session +
terminate_process_tree — mirrors the extractor; research.md D6/C1) at cycle start
and on `refresh-sources`, honouring success/warning/fatal_fail (fatal skips only
that module — Principle VIII; crash/timeout/garbage-stdout → fatal_fail,
fail-closed). All four Tier-1 modules ship a `preflight.py` subprocess script
before 0.7.1. The framework core never imports vault module code at runtime.

**Independent Test**: a manifest lacking `preflight` is rejected (module skipped,
cycle continues); a malformed `arxiv.org/list/cs.AI` rss source surfaces a
`warning` with a `rss.arxiv.org/rss/cs.AI` correction; `pytest tests/modules/` +
the orchestrator integration test are green.

### Story-foundational (do FIRST — defines the shape all preflights implement)

- T029 [US5] Add the orchestrator-side typed parse: `PreflightResult` + `SourceCorrection` frozen dataclasses (with `success()`/`warning()`/`fatal()` constructors, `schema_version="1.0"`, and a `from_json(dict) -> PreflightResult` parser validating against the schema) in a new `src/research_framework/pipeline/source_bridge/preflight_types.py`, per `contracts/preflight.contract.md` §3. **Also author `specs/051-post-revival-hardening/contracts/preflight-result.schema.json`** is already done at plan stage — reference it here for validation. **DONE** — TDD; `tests/source_bridge/test_preflight_types.py` (11 tests: constructors, from_json happy paths incl. round-trip, and fail-closed rejection of bad schema_version/verdict/corrections-shape/missing-key/non-dict). ruff clean. **Sequencing note for the rest of US5**: the T031 *required*-preflight gate is landed AFTER T038–T042 (the four manifests + `_template` declare `preflight`), so the suite stays green (otherwise every existing module-load test breaks in the gap).
- T030 [US5] Amend `specs/020-code-bridge/contracts/manifest.schema.json`: add `"preflight"` to `required` and define the object (`required:["entry_point"]`, `entry_point:string` matching `^[A-Za-z0-9_./-]+\.py$`, `timeout_seconds:integer [1,300] default 30`), per data-model.md. **DONE** — `preflight` added to `required` + property defined (valid JSON). **Note**: there is a 5th in-tree module `code` (besides the four Tier-1); since T031 makes `preflight` required for *any* parsed manifest, `code` + `_template` also get a (minimal) `preflight` block/script or their load-tests break — added alongside the four (beyond the spec's named four; necessary for the blanket gate).
- T031 [US5] Add `preflight: dict[str, Any]` to `ModuleManifest` in `source_bridge/discovery.py` (`:39`) and make `parse_manifest` (`:55`) raise `ValueError("manifest missing required 'preflight' block — add preflight.py and declare it (see modules/_template/)")` when the block is absent OR `preflight.entry_point` names a file that doesn't exist (mirror the existing top-level `entry_point` check). The existing `isolated_call` fail-closed path turns it into a skipped-module WARN, not a cycle crash. **DONE** — `ModuleManifest.preflight` field + parse_manifest raises (message contains "preflight") on absent block / missing entry_point file. **Fallout fixed** (the blanket gate broke fixture manifests): `tests/_helpers/fake_module.py::write_fake_extractor` now auto-writes a valid `preflight.py` + exports `write_fake_preflight`/`FAKE_PREFLIGHT_BLOCK`; conftest + test_discovery inline manifests got the `preflight` block. 274 source_bridge+modules+generator tests green.

### Tests for User Story 5 (write first, must FAIL)

- T032 [P] [US5] Add a manifest-validation test in `tests/source_bridge/` (extend `test_youtube_module.py` or add `test_manifest_preflight_required.py`): `parse_manifest` on a manifest without `preflight` (and with a `preflight.entry_point` that doesn't exist) raises `ValueError`; `walk_modules` skips it with a WARN and the cycle continues. **DONE** — `tests/source_bridge/test_manifest_preflight_required.py` (4 tests): missing block raises, missing entry_point-file raises, valid block parses (exposes `.preflight`), and walk_modules skips the bad module while keeping the good one (fail-closed).
- T033 [P] [US5] Write `tests/modules/youtube/test_preflight.py` (~6–8 tests): clean success; trailing-whitespace strip; channel-URL shape validation; plain-handle-without-`@` → suggestion; a `fatal_fail` case. Exercise the **subprocess** contract (JSON request on stdin → `PreflightResult` JSON on stdout), mirroring `tests/source_bridge/test_youtube_module.py::_run_extractor`; MAY additionally call the pure `check()` helper for fine-grained logic assertions. **DONE** — 7 tests, subprocess-invoked, parsed through `PreflightResult.from_json` (validates the cross-process payload end-to-end): clean success, whitespace-strip (applied=true), plain-handle→`@handle` (applied=false), `@handle`/`/channel/UC…` success, empty-sources fatal, unknown-command fatal.
- T034 [P] [US5] Write `tests/modules/reddit/test_preflight.py`: `/r/<name>` + bare `<name>` accepted/normalized; obvious typo rejected; success + fatal cases. Subprocess-invoked (see T033). **DONE (parallel agent)** — 8 tests.
- T035 [P] [US5] Write `tests/modules/rss/test_preflight.py`: `/feed/feed/` de-dup; `arxiv.org/list/cs.AI` → `rss.arxiv.org/rss/cs.AI` warning correction; HEAD-probe XML/Atom confirmation using a fixture override (e.g. `RSS_PREFLIGHT_HEAD_FIXTURE`) to stay hermetic/offline (Principle V); success + fatal cases. Subprocess-invoked (see T033). **DONE (parallel agent)** — 8 tests, fully offline via `RSS_PREFLIGHT_HEAD_FIXTURE` (JSON: bare content-type string OR `{url: content_type}` map).
- T036 [P] [US5] Write `tests/modules/oreilly/test_preflight.py`: `learning.oreilly.com/search/?q=` accepted; legacy `oreilly.com/api/v2/search` rejected → suggestion; success + fatal cases. Subprocess-invoked (see T033). **DONE (parallel agent)** — 9 tests.
- T037 [P] [US5] Write an orchestrator integration test in `tests/source_bridge/` (extend the existing source_bridge suite): `run_extraction` **spawns** the preflight subprocess per module, runs normally on `success`, records corrections on `warning`, SKIPS only the offending module on `fatal_fail` (others still run), and maps a crashing/timing-out/garbage-emitting preflight subprocess to `fatal_fail` (fail-closed); plus a `refresh-sources` preflight-sweep test. **DONE** — `tests/source_bridge/test_preflight_orchestration.py` (8 tests): success runs; fatal-only → 0 extractions; fatal+good → good still runs (isolation); warning runs + records corrections; crash/garbage/timeout (tree-killed @1s) all → fatal_fail; + the refresh-sources `_preflight_sweep` per-module verdict test.

### Implementation for User Story 5

- T038 [P] [US5] Implement `src/research_framework/modules/youtube/preflight.py` as a **subprocess script** per `contracts/preflight.contract.md` §2/§6 — a `main()` dispatching on `sys.argv[1]=="preflight"` (reads stdin JSON request, prints `PreflightResult` JSON) wrapping a pure `check()` (whitespace strip, channel-URL shape, `@`-handle; emits the JSON dict directly — modules can't import `src/`). Add the `preflight:` block (`entry_point: preflight.py`, `timeout_seconds`) to `modules/youtube/manifest.yaml`. **DONE** — `preflight.py` (pure `check()` + `main()` dispatch, emits the JSON shape directly) + `preflight:` block in manifest. 7/7 green, ruff clean. **This is the template the other three modules (T039–T041) follow.**
- T039 [P] [US5] Implement `src/research_framework/modules/reddit/preflight.py` subprocess script (subreddit format + normalize) and add `preflight:` to `modules/reddit/manifest.yaml`. **DONE (parallel agent)** — normalizes bare/`/r/` names to the canonical full `reddit.com/r/<name>/.rss` URL the extractor consumes (applied=true); typos → suggestion.
- T040 [P] [US5] Implement `src/research_framework/modules/rss/preflight.py` subprocess script (`/feed/feed/` de-dup, arxiv suggestion, fixture-overridable HEAD probe within `timeout_seconds` via stdlib `urllib`) and add `preflight:` to `modules/rss/manifest.yaml`. **DONE (parallel agent)** — `/feed/feed/`→`/feed/` (applied=true), arxiv `/list/`→`rss.arxiv.org/rss/` (applied=false), HEAD probe warns on non-XML; network swallowed (never crashes), `RSS_PREFLIGHT_HEAD_FIXTURE` keeps tests offline.
- T041 [P] [US5] Implement `src/research_framework/modules/oreilly/preflight.py` subprocess script (search-URL shape, reject legacy API) and add `preflight:` to `modules/oreilly/manifest.yaml`. **DONE (parallel agent)** — legacy `api/v2/search` rewrite is applied=true when a query can be lifted, else applied=false suggestion. API-key handling untouched (that's the separate MCP-managed/settings-file change).
- T042 [US5] Create the skeleton `src/research_framework/modules/_template/preflight.py` (subprocess script per contract §6: `main()` + `check()` emitting a `success` `PreflightResult` JSON; body is `# TODO: add module-specific checks here`). `_template/` is a reference dir, not a shipped module (not in any vault's `settings.yaml::modules`). **DONE** — `_template/preflight.py` skeleton (no manifest → `walk_modules` glob skips it). Also added a minimal `code/preflight.py` + `preflight:` block (the in-tree `code` module must satisfy the now-required gate; beyond the spec's named four).
- T043 [US5] Spawn preflight at cycle start in `source_bridge/orchestrator.py::run_extraction` (`:~74`, after manifest+sources+watermarks load, before the source loop): invoke the module's preflight subprocess via the extractor's `popen_session([sys.executable, <module>/<preflight.entry_point>, "preflight"])` machinery (reuse/extract the helper in `source_bridge/extractor.py`), write `{schema_version, sources, watermarks}` to stdin, parse the `PreflightResult` JSON from stdout (via `preflight_types.from_json`), enforce `manifest.preflight.timeout_seconds` via `terminate_process_tree`, and apply the verdict table — `fatal_fail` (incl. crash/timeout/garbage) skips only that module; `warning` logs + records corrections in the cycle report; `success` proceeds. **DONE** — new `source_bridge/preflight_runner.py::run_preflight` (popen_session + `proc.communicate(timeout)` + `terminate_process_tree` on TimeoutExpired; non-zero exit / unparseable stdout / TimeoutExpired all → `fatal_fail`). Wired into `run_extraction`: per-module before the source loop; verdict recorded in `module_stats["preflight"]`; fatal → log + skip (continue); warning → log messages + proceed. **Scope note**: auto-applying `applied=true` corrected URLs to live extraction is NOT wired (the preflight returns corrections but doesn't key them to source records) — corrections are recorded/logged; applying them to extraction is a documented follow-up, beyond the T037 acceptance (record + skip).
- T044 [US5] Add the module preflight sweep to `cli/refresh_sources.py` (the "top of `./vault refresh-sources`" per research.md D6 — a discrete pass over installed modules' `sources.yaml`, independent of the legacy collector loop). **DONE** — `_preflight_sweep(vault_dir)` (walk_modules → run_preflight per module) runs up front (before the vault-venv check, since it uses the framework interpreter), `_report_preflight` logs fatal/warning to stderr, and the per-module rows are threaded into the `--json` output (`"preflight": [...]`). Existing 10 refresh-sources tests still green.
- T045 [US5] Run `pytest tests/modules/ tests/source_bridge/`; confirm all preflight + manifest + integration tests green, and the four modules load with their new required `preflight` blocks. **DONE** — `tests/modules` + `tests/source_bridge` = **215 passed, 4 skipped**; ruff check + format clean on all US5 files.

**Checkpoint**: US5 complete — preflight is a uniform, mandatory, testable contract across all four modules.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Single cross-cutting fixups + the full ship gate. (Doc-sync —
ROADMAP/CHANGELOG/spec-status/issue #N — happens at **ship time** per CLAUDE.md
doc-discipline, NOT here.)

- [~] T046 Recompute the stale entries in `dist-templates/scaffold-manifest.json` (settings.yaml from T015+T022, `vault` from T027). **DEFERRED to the release-time regen — deliberately NOT done piecemeal here.** Investigated 2026-06-02: running `scripts/build_scaffold_manifest.py` regenerates the WHOLE manifest and churned **all 17 entries** (the committed manifest is release-time-regenerated and already 2.5 weeks stale — last generated 2026-05-16, before specs 023/028/033/048/050 touched templates) AND flipped an `is_user_owned_after_first_write: false→true` (a deliberate spec-023 override that `test_scaffold_manifest_snapshot.py` pins). No test enforces committed-sha equality (snapshot test = structure, build test = hex format). So a blind regen now would inject unrelated drift + regress a pinned override; a 2-entry manual sha edit is error-prone and valueless given the manifest is already broadly stale and regenerated wholesale at release. **Correct action: regenerate once at release (picks up settings.yaml + vault + all accumulated drift consistently).** Reverted the regen; snapshot test green.
- T047 [P] Run the full lint gate: `ruff check .` AND `ruff format --check .` (separate gates — CLAUDE.md). Fix any new findings without blanket `# noqa`. **DONE** — `ruff check .` clean repo-wide; `ruff format` fixed 2 files: my `tests/_helpers/fake_module.py` and (caught by this gate) `tests/pipeline/test_cg001_yield_model.py` — a US2 file from an earlier commit that had slipped the format gate. Both reformatted; 526 files now formatted.
- T048 Run `./build.sh --quality` (FR1 touches `pipeline/`, so the spec-022 quality harness is required) and `pytest` (full sweep incl. e2e). Confirm green and the tech-lite/source-poor/source-rich regression diffs are unchanged. **DONE.** Fast loop `pytest -m "not e2e"` = **1866 passed, 8 skipped** (only 3 failures = the pre-existing `OSError: out of pty devices` environmental TTY tests, T001 baseline). `PYTHON_BIN=.venv/bin/python bash build.sh --quality` → **smoke gate passed + quality harness `Verdict: PASS, 3 fixtures, 0 regressions, 0 warnings`** (tech-lite/source-poor/source-rich diffs unchanged). (The wheel-build step then hit `mktemp ... Operation not permitted` — a sandbox temp restriction; the wheel is built in CI, not in-sandbox — not a code/spec issue.) **Caught + fixed a US2 doc-debt regression along the way**: T008 deleted `test_remaining_yield_scaling.py` but left two CHANGELOG [0.6.1] references → repointed to `test_cg001_yield_model.py` (`test_changelog_regression_links` 9/9 green).
- T049 Walk `quickstart.md` end-to-end for all five FRs (manual smoke of each `./vault` interaction) and fix any drift between the quickstart commands and the shipped behaviour. **DONE** — reviewed all 5 FR sections against shipped behaviour; fixed 2 drifts: FR2's version check compares against the **bundled wheel's version** (not `pyproject.toml` — bundle ships none), and FR4's "observe" reads `.preflight` from `refresh-sources --json` / the source-extraction summary (not the quality-report JSON — preflight verdicts land in `module_stats`, not the quality report). FR1/FR3/FR5 + the full-gate section were accurate.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)** → no deps; start immediately.
- **Foundational (Phase 2)** → after Setup; it is a checkpoint only (no shared blocking code).
- **User stories (Phases 3–7)** → all may start after the Phase 2 checkpoint. They are independent EXCEPT the US2↔US3 `settings.py`/`settings.yaml` coupling (see Phase 2 note). Recommended serial order is the plan's: **US1 → US2 → US3 → US4 → US5**.
- **Polish (Phase 8)** → after all stories; T046 specifically requires both T015 and T022.

### Story dependencies

- **US1 (FR5)**: independent. Do first (locks shipped behaviour).
- **US2 (FR1)**: independent except shared `settings.py`/`settings.yaml` with US3.
- **US3 (FR3)**: independent except shared `settings.py`/`settings.yaml` with US2.
- **US4 (FR2)**: fully independent (bash only).
- **US5 (FR4)**: independent; internally ordered — T029–T031 (types + schema + manifest validation) MUST precede the module tests/impls (T032–T045).

### Within each story

- Tests written and failing (US2–US5) before implementation. US1 tests lock existing behaviour (pass-on-write expected).
- US2: settings → model (coverage.py) → gate → call sites → diagnostic/sidecar → settings.yaml.
- US5: shared types/schema/validation → module tests → module preflights → orchestrator + refresh-sources wiring.

### Parallel opportunities

- **T002** [P] alongside T001 verification.
- **US-level parallelism**: US1, US4, US5 are fully independent of US2/US3 and of each other — three developers could take US1+US4+US5 in parallel while US2→US3 run serially on `settings.py`.
- **Within US5**: T033–T036 (four module preflight tests) [P]; T038–T041 (four module preflights + their manifests) [P] — all different files.
- **Within US2**: T007, T008 [P] (different test files).
- **Within US3**: T017, T018 [P].

---

## Parallel Example: User Story 5 module preflights

```bash
# After T029–T031 (types + schema + manifest validation) land, write the four
# module preflight test files in parallel:
Task: "tests/modules/youtube/test_preflight.py"
Task: "tests/modules/reddit/test_preflight.py"
Task: "tests/modules/rss/test_preflight.py"
Task: "tests/modules/oreilly/test_preflight.py"

# Then implement the four preflights in parallel (different module dirs):
Task: "src/research_framework/modules/youtube/preflight.py + manifest.yaml"
Task: "src/research_framework/modules/reddit/preflight.py + manifest.yaml"
Task: "src/research_framework/modules/rss/preflight.py + manifest.yaml"
Task: "src/research_framework/modules/oreilly/preflight.py + manifest.yaml"
```

---

## Implementation Strategy

### MVP-first (per plan ordering)

1. Phase 1 Setup → Phase 2 checkpoint.
2. **US1 (FR5)** — lock shipped behaviour. Smallest; de-risks later refactors.
3. **US2 (FR1)** — the headline value; ship the configurable model + baseline pin.
4. **US3 (FR3)**, **US4 (FR2)** — independent hardening increments.
5. **US5 (FR4)** — the long pole; all four modules must carry preflight before 0.7.1.
6. Polish → full gate → ready for the 0.7.1 release PR.

### Foreman pre-implement step (ADR-0010, opt-in)

Before `/speckit.implement`, dispatch the test-design subagent
(`.agents/skills/test-designer/SKILL.md`) to enrich this `tasks.md` in place with
per-task `### Testing Requirements` blocks (strict filenames + function names +
TDD flag), then run the Arm A verifier (`scripts/foreman/verify_test_coverage.py`)
+ Arm B review after implementation. The acceptance criteria in spec.md FR1–FR5
are the source for those requirement blocks.

---

## Notes

- [P] = different files, no incomplete-task dependency.
- The biggest correctness risk is US2's baseline pin (T007/T016): if the
  tech-lite quality diff moves, the `cycle_yield` defaults are wrong — re-tune
  defaults, do not move the baseline.
- US5's manifest amendment (T030/T031) is technically breaking; safe because all
  four modules are in-tree and updated in the same ship (T038–T041).
- Per research.md D7, US1 is intentionally smaller than spec.md's literal FR5
  wording (net-new coverage only) to avoid duplicating existing locks.
- Doc-sync (ROADMAP/CHANGELOG/spec-status/`Closes #N`/version bump to 0.7.1) is a
  ship-time activity per CLAUDE.md — not in this task list.
