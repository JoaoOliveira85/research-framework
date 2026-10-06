---
description: "Task list for spec 025 Code Simplification Pass"
---

# Tasks: Code Simplification Pass (Tier A + B Refactor)

**Input**: Design documents from `/specs/_archive/025-simplify-pass/`
**Prerequisites**: `plan.md` (✅ Phase 0/1 committed `9f3428e`), `spec.md`
(Clarified 2026-05-21, commit `3ffa999`), `research.md` (D1–D9 +
O1–O4), `data-model.md` (preserved + new API surfaces), `contracts/`
(6 files), `quickstart.md`.

**Tests**: REQUESTED. Every functional task ships with a test
(spec.md FR-009, plan.md Testing section, Principle III non-
negotiable). Tier-1/2 unit tests for tier A; full sweep + smoke
for tier A merge; smoke + `./build.sh --quality` for tier B merge
(FR-016 + SC-014).

**Organization**: One phase per user story (US1–US9) plus US10
(meta, post-US1+US2) and the cross-cutting setup/foundational/
polish phases. Tier A (US1–US5 + US10) ships pre-022-v1; Tier B
(US6–US9) ships post-022-v1 (FR-016).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies
  on tasks not yet complete).
- **[Story]**: Which user story this task belongs to.
- File paths are exact, relative to repo root.

## Path Conventions

Single-project Python CLI (per plan.md Project Structure):
- Source: `src/research_framework/`
- Tests: `tests/`
- Scripts: `scripts/`
- Dist templates: `dist-templates/`

The 025 worktree is at
`~/src/research-framework-025/`. The B3
sub-branch (US6 only) will live at
`~/src/research-framework-b3/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Capture pre-refactor metrics + verify the 025
worktree is ready. No code changes here; just baselines so we
can later prove behaviour preservation.

- [ ] T001 [P] Capture pre-refactor `./vault --help` output as
  golden file at `tests/cli/fixtures/help_output_pre_025.txt`
  (creates the fixtures directory if needed). Also capture per-
  subcommand `--help` outputs: `research`, `audit`, `vault`,
  `quality` (if it exists) at
  `tests/cli/fixtures/help_<subcommand>_pre_025.txt`. These are
  the SC-009 byte-identical references.

- [ ] T002 [P] Capture pre-refactor LOC metrics for the files
  touched by 025 to a single status report in
  `_pipeline/025-pre-refactor-loc.txt` (not committed; local
  reference): `pipeline/cycle_runner.py`, `cli.py`,
  `pipeline/plan_narrator.py`. Format: `<path> <line_count>`.

- [ ] T003 [P] Inventory existing frontmatter parser call sites
  to a local note `_pipeline/025-frontmatter-sites.txt` (not
  committed). Use:
  `rg -l "yaml\.safe_load.*frontmatter|^---$" --type py src/research_framework/`.
  Confirm count ≥ 12 (FR-010 + SC-007 require migrating ≥ 8).

- [ ] T004 [P] Inventory existing settings loader call sites to
  `_pipeline/025-settings-sites.txt` (not committed). Use:
  `rg -l "yaml\.safe_load.*settings\.yaml" --type py src/research_framework/`.
  Confirm count ≥ 6 (FR-012 + SC-008 require migrating ≥ 6).

- [ ] T005 [P] Inventory existing `_write_cycle_quality_report`
  call sites to `_pipeline/025-quality-report-sites.txt` (not
  committed): `rg -n "_write_cycle_quality_report" src/research_framework/pipeline/cycle_runner.py`.
  Confirm count ≈ 32 (the architect's count; close enough is
  fine). Post-A6, this MUST drop to ≤ 2 (FR-007 + SC-006).

- [ ] T006 Confirm full sweep green and smoke gate green on the
  pre-refactor baseline:
  `pytest -m "not e2e" && ./build.sh`. If either fails, STOP —
  the 025 branch's starting condition is broken; spec 025 cannot
  proceed.

**Checkpoint**: Pre-refactor state captured; downstream tasks
can now compare against these baselines.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Verify the structural prerequisites every user
story will rely on. For 025, this is light — the refactor
doesn't introduce new infrastructure, only reorganises existing
infrastructure.

- [ ] T007 Verify `scripts/agent_call.py` exposes a `dispatch`
  (or equivalently-named) function that accepts a `stage`
  parameter. Read the file; document the exact signature in a
  comment at the top of `tests/pipeline/test_plan_narrator.py`
  (created in T015). If the dispatcher signature differs from
  the contract in `contracts/llm-dispatch.contract.md` § 1,
  reconcile: either the contract was wrong (update contract)
  or the dispatcher needs a small adapter (in that case, add a
  new open item to `research.md` § "Open items" as O5 and
  document the adapter design at task-resolution time).

- [ ] T008 [P] Verify `_pipeline/state.json::in_progress_cycle`
  exists or plan its addition. Check by:
  `rg "in_progress_cycle" src/research_framework/`. If the
  field is read somewhere but never written (or vice versa),
  US4 (A4) needs both sides — flag in T029.

- [ ] T009 [P] Verify the `tests/_helpers/llm_dispatch_allowlist.yaml`
  file path is correct (spec 024 US1 may have shipped under a
  different path). Check spec 024's tasks.md if available:
  `cat ~/src/research-framework-024/specs/024-testing-infrastructure-v2/tasks.md 2>/dev/null | rg "allowlist"`.
  If spec 024 hasn't shipped the file yet, US10's verification
  tasks (T043–T046) are blocked until it does.

**Checkpoint**: Foundational prerequisites verified. Tier A
user stories (US1–US5) can now begin in parallel where
file-conflict-free.

---

## Phase 3: User Story 1 — A1: route `plan_narrator` LLM bypass through `agent_call.py` (Priority: P1) 🎯 Tier A

**Goal**: `pipeline/plan_narrator.py` no longer calls `claude`
(or `codex`) directly via `subprocess.run`; it goes through
`scripts/agent_call.py::dispatch(stage="plan_narrator", ...)`,
producing a cost-sidecar JSON at
`_pipeline/cycles/cycle-NNN/agent-calls/plan_narrator.json` per
the schema in `contracts/llm-dispatch.contract.md` § 3.

**Independent Test**: After the change, run a fake_agent-backed
cycle (`pytest tests/pipeline/test_plan_narrator.py`); confirm
the dispatcher receives the call AND the sidecar JSON appears
in the cycle directory.

### Tests for User Story 1 (write FIRST, ensure they FAIL before implementation)

- [ ] T010 [US1] Create `tests/pipeline/test_plan_narrator.py`
  with `test_dispatch_through_agent_call`: invoke
  `prepend_narrative` (or equivalent narrator entry point); mock
  `scripts.agent_call.dispatch`; assert the mock was called with
  `stage="plan_narrator"`, `tier=` (correct value from
  settings), and a non-empty `prompt`. Test MUST FAIL before
  implementation (the bypass calls subprocess directly, not the
  dispatcher).

- [ ] T011 [P] [US1] Add `test_codex_default_respected` to the
  same file: with `RESEARCH_FRAMEWORK_DEFAULT_AGENT=codex` env
  set, the dispatcher's resolved `agent` (in the sidecar) is
  `"codex"`. Use a real (not mocked) dispatcher with a stub
  agent binary at `tests/_helpers/fake_codex_binary.sh`.

- [ ] T012 [P] [US1] Add `test_sidecar_written`: after a
  narrator call in a fixture cycle directory, the file
  `cycle_dir/agent-calls/plan_narrator.json` exists, parses as
  JSON, and contains the required keys (`stage`, `agent`,
  `tier`, `cost_usd`, `tokens_in`, `tokens_out`, `latency_ms`,
  `started_at`, `completed_at`, `exit_code`) per
  `contracts/llm-dispatch.contract.md` § 3.

### Implementation for User Story 1

- [ ] T013 [US1] Read `scripts/agent_call.py` to confirm the
  stage enum (or free-form acceptance). If there's an explicit
  `VALID_STAGES` allowlist, extend it with `"plan_narrator"`. If
  free-form, no change to `agent_call.py` needed.

- [ ] T014 [US1] Rewrite `pipeline/plan_narrator.py` (or the
  function that owns the direct LLM call — verify with
  `rg "subprocess\\.(run|Popen).*claude|codex" pipeline/plan_narrator.py`).
  Replace the direct subprocess call with
  `agent_call.dispatch(stage="plan_narrator", prompt=prompt,
  tier=settings.stage("plan_narrator").tier, cycle_dir=cycle_dir)`
  per `quickstart.md` § 1.

- [ ] T015 [US1] Update `dist-templates/settings.yaml` (and any
  fixture `settings.yaml` files) to include the new optional
  key `stages.plan_narrator.tier: standard` with comment.
  Vaults without the key get the same default at load time
  (B7 will formalise this); for now, code in `plan_narrator.py`
  uses `.get("plan_narrator", {}).get("tier", "standard")`
  defensive pattern. Once B7 ships, this becomes
  `settings.stage("plan_narrator").tier`.

- [ ] T016 [US1] Delete the allowlist entry for
  `pipeline/plan_narrator.py` from
  `tests/_helpers/llm_dispatch_allowlist.yaml` (if the file
  exists per T009). If spec 024 hasn't shipped the allowlist
  yet, document the deletion as pending in this task's commit
  message and complete it when spec 024 lands.

- [ ] T017 [US1] Run the US1 tests (T010, T011, T012); all
  three MUST now pass. Run the full sweep (`pytest -m "not e2e"`)
  to confirm no regression. Commit as one PR: `feat(025): A1
  route plan_narrator through agent_call.py`.

**Checkpoint**: A1 complete. The narrator's LLM dispatch is no
longer a Principle IV violation. Cost capture works.

---

## Phase 4: User Story 2 — A2: route `probe_retrieval` LLM bypass through `agent_call.py` (Priority: P1) 🎯 Tier A

**Goal**: The probe-retrieval block in `pipeline/cycle_runner.py`
(currently a direct subprocess invocation around lines
1137–1252 at v0.2.33) goes through `agent_call.py::dispatch(
stage="probe_retrieval", ...)`.

**Independent Test**: `pytest tests/pipeline/test_cycle_runner_probe.py`.

### Tests for User Story 2 (write FIRST)

- [ ] T018 [US2] Create `tests/pipeline/test_cycle_runner_probe.py`
  with `test_dispatch_through_agent_call`: similar shape to T010
  but for the probe block. Mock the dispatcher; assert
  `stage="probe_retrieval"`.

- [ ] T019 [P] [US2] Add `test_codex_default_respected` (same
  shape as T011 for narrator).

- [ ] T020 [P] [US2] Add `test_sidecar_written` (same shape as
  T012, with sidecar at `cycle_dir/agent-calls/probe_retrieval.json`).

- [ ] T020a [P] [US2] Add `test_probe_disabled_short_circuits`
  (covers spec.md A2 edge case): with the probe-retrieval
  stage disabled in settings (mechanism depends on how the
  feature is gated — typically `stages.probe_retrieval.enabled:
  false` or the absence of the stage entry), assert
  `agent_call.dispatch` is **never called** for the probe
  stage AND no `cycle_dir/agent-calls/probe_retrieval.json`
  file is created. The cycle MUST still complete successfully
  (no error from the missing probe data). MUST FAIL pre-A2 if
  the current bypass doesn't honour the disable flag; MUST
  PASS post-A2.

### Implementation for User Story 2

- [ ] T021 [US2] If T013 added `"probe_retrieval"` to the stage
  enum, no action needed; otherwise extend it now.

- [ ] T022 [US2] Locate the probe-retrieval block in
  `pipeline/cycle_runner.py` (verify line range with
  `rg -n "probe" pipeline/cycle_runner.py`). Replace the direct
  subprocess invocation with `agent_call.dispatch(
  stage="probe_retrieval", ...)`.

- [ ] T023 [US2] Update `dist-templates/settings.yaml` with
  optional key `stages.probe_retrieval.tier: standard`.

- [ ] T024 [US2] Delete the allowlist entry for the probe block
  from `tests/_helpers/llm_dispatch_allowlist.yaml` (same
  conditional as T016).

- [ ] T025 [US2] Run US2 tests (T018, T019, T020); all pass.
  Run full sweep. Commit as one PR: `feat(025): A2 route
  probe_retrieval through agent_call.py`.

**Checkpoint**: A2 complete. Combined with A1, both known LLM
bypasses are gone. T040 (US10 meta) can now verify the
allowlist is empty.

**Conflict note**: US2 modifies `cycle_runner.py`. US3 (A6,
Phase 5) modifies the same file extensively. **US2 MUST land
before US3 starts**, OR the US3 implementer must integrate the
A2 rewrite as part of US3's diff. Recommend US2 first; it's
small.

---

## Phase 5: User Story 3 — A6: quality-report context-manager guard (Priority: P1) 🎯 Tier A

**Goal**: `pipeline/cycle_runner.py` ensures
`_write_cycle_quality_report` is called **exactly once per
cycle exit** (success / failure / exception / KeyboardInterrupt)
via a `contextlib.contextmanager` wrapper. The 32 scattered
call sites collapse to ≤ 2 (FR-007 + SC-006).

**Independent Test**:
`pytest tests/pipeline/test_cycle_runner_quality_report.py`
parametrised across all 4 exit paths.

### Tests for User Story 3 (write FIRST)

- [ ] T026 [US3] Create
  `tests/pipeline/test_cycle_runner_quality_report.py` with the
  four parametrised exit-path tests:
  - `test_happy_path_writes_once`: scout + research + postprocess
    all succeed; report exists with `exit_status="success"`.
  - `test_scout_failure_writes_once`: scout raises; report exists
    with `exit_status="failure"` and `exception` field populated.
  - `test_keyboard_interrupt_writes_once`: simulate `KeyboardInterrupt`
    mid-cycle; report exists with `exit_status="interrupted"`;
    interrupt propagates to caller.
  - `test_write_count_is_exactly_one`: spy on
    `_write_cycle_quality_report` (mock or counter wrapper);
    assert exactly 1 call across each scenario above.

  All four MUST FAIL pre-A6 (pre-A6 the call count varies:
  may be 0 on uncaught exceptions, or > 1 if multiple cycle
  paths fire).

### Implementation for User Story 3

- [ ] T027 [US3] In `pipeline/cycle_runner.py`, define:
  - `@dataclass class QualityReportState` (mutable; cycle_dir,
    scout, research, postprocess, exit_status, exception
    fields per `data-model.md` § 2.2).
  - `@contextmanager def _quality_report_guard(cycle_dir: Path)`
    yielding the state; `try/except/finally` shape per
    `research.md` D2 + `data-model.md` § 2.2.

- [ ] T028 [US3] Wrap `run_cycle_steps`' body in
  `with _quality_report_guard(cycle_dir) as report_state:`.
  Delete EVERY existing `_write_cycle_quality_report(...)` call
  inside `run_cycle_steps`. For each deletion, replace the local
  data-construction with `report_state.<field> = ...` mutations.

- [ ] T029 [US3] Confirm `rg -c "_write_cycle_quality_report\(" src/research_framework/pipeline/cycle_runner.py`
  returns ≤ 2 (one at `__exit__`, plus at most one optional
  progress log per FR-007 — the default plan is ZERO secondary
  sites, see research.md O3).

- [ ] T030 [US3] Run US3 tests (T026); all four scenarios pass.
  Run full sweep. Specifically verify
  `tests/pipeline/test_cycle_runner.py` (the existing tests)
  still pass UNCHANGED — this is the strongest behaviour-
  preservation proof.

- [ ] T031 [US3] Commit as one PR: `feat(025): A6 quality-
  report context-manager guard`.

**Checkpoint**: A6 complete. `_write_cycle_quality_report`
runs exactly once per cycle exit. Principle I (script-validated
quality gates) is structurally strengthened.

**Conflict note**: US3 touches `cycle_runner.py` extensively.
The remaining Tier A items (US4, US5) don't touch this file, so
US3 can ship at any point in the Tier A sequence after US2.

---

## Phase 6: User Story 4 — A4: auto-detect resume cycle (Priority: P1) 🎯 Tier A

**Goal**: `./vault research --resume` (no `--cycle` flag) reads
`_pipeline/state.json::in_progress_cycle` and resumes the
identified cycle. Explicit `--cycle <N>` overrides; missing
state.json or `in_progress_cycle: null` produces a clear error;
multiple in-progress entries produce a clear error.

**Independent Test**:
`pytest tests/cli/test_research_resume.py` covering the four
spec.md US4 scenarios.

### Tests for User Story 4 (write FIRST)

- [ ] T032 [P] [US4] Create `tests/cli/test_research_resume.py`:
  - `test_resume_auto_detects_cycle`: write state.json with
    `in_progress_cycle: 5`; `./vault research --resume` (via
    `build_parser`/`handle`) resumes cycle 5.
  - `test_explicit_cycle_overrides_auto`: state.json has
    `in_progress_cycle: 5`, but `--cycle 3` resumes cycle 3.
  - `test_no_state_file_errors_clearly`: no state.json + no
    `--cycle` → `SystemExit` with message
    `"no in-progress cycle found"`.
  - `test_corrupted_state_errors_clearly`: state.json contains
    invalid JSON → `SystemExit` with message containing
    `"state.json is corrupted"` and `"use --cycle <N>"`.
  - `test_null_in_progress_errors_clearly`: state.json has
    `in_progress_cycle: null` + no `--cycle` → same error as
    no-state-file case.

  All five MUST FAIL pre-A4 (the auto-detect logic doesn't
  exist).

### Implementation for User Story 4

- [ ] T033 [US4] If T008 confirmed `state.json::in_progress_cycle`
  has a write-side hook, skip to T034. If not (write-side
  missing), add the write-side now: in `cycle_runner.py`'s
  `run_cycle_steps`, at cycle start write `{"in_progress_cycle":
  cycle_num}` to `state.json`; at cycle end (via the context
  manager's `__exit__`) write `{"in_progress_cycle": null}`.
  Reuse the existing `_state_write` helper if present; otherwise
  add a small one. (Atomic write — write to temp then rename.)

- [ ] T034 [US4] Implement the resume handler. Pre-B5 (Tier A
  ships before B5), this lives in `cli.py`'s research handler.
  Post-B5, the handler moves to `cli/research.py`; the move is
  US8's responsibility. Add `_resolve_resume_cycle(args)`:
  reads state.json, returns `int` or raises `SystemExit` with
  the error messages from T032's test expectations. See
  `quickstart.md` § 3 for the exact pattern.

- [ ] T035 [US4] Wire `_resolve_resume_cycle` into the resume
  command's argparse handler: if `args.resume and args.cycle is
  None`, set `args.cycle = _resolve_resume_cycle(args)`.

- [ ] T036 [US4] Run US4 tests (T032); all five pass. Run full
  sweep.

- [ ] T037 [US4] Commit as one PR: `feat(025): A4 auto-detect
  --resume cycle from state.json`.

**Checkpoint**: A4 complete. `--resume` UX matches spec.md US4.
This task is fully orthogonal to US1/US2/US3 (different files);
runs in parallel with them.

---

## Phase 7: User Story 5 — A5: sync stale documentation (Priority: P1) 🎯 Tier A

**Goal**: Three specific doc updates per `research.md` D9:
constitution's `run_cycle.sh` references → current entry
point; ROADMAP QW-2 entry → accurate description;
`build.sh` header comment → current smoke-gate contract. Two
grep-based regression tests enforce the changes.

**Independent Test**: `pytest tests/docs/test_doc_sync.py`.

### Tests for User Story 5 (write FIRST)

- [ ] T038 [P] [US5] Create `tests/docs/test_doc_sync.py`:
  - `test_no_run_cycle_sh_references`: assert
    `rg "run_cycle\\.sh" .specify/ docs/` returns exit 1 (no
    matches). MUST FAIL pre-A5 (the constitution still
    references `run_cycle.sh`).
  - `test_qw2_text_accurate`: read `docs/ROADMAP.md`; assert
    the strings `"files missing"` and `"files never committed"`
    are NOT present in the QW-2 entry. MUST FAIL pre-A5.

### Implementation for User Story 5

- [ ] T039 [US5] Update `.specify/memory/constitution.md`:
  search-and-replace `run_cycle.sh` references per
  `research.md` D9 (rewrite to reference `./vault research` →
  `cli/research.py` → `cycle_runner.run_cycle_steps` →
  `scripts/agent_call.py`). PATCH-level constitution
  amendment per Governance § Versioning policy; prepend a Sync
  Impact Report HTML comment block.

- [ ] T040 [P] [US5] Update `docs/ROADMAP.md`'s QW-2 entry
  per `research.md` D9: rewrite to describe the smoke meta-
  tests as "commented out in build.sh" not "missing files".
  Cross-reference the spec 024 US3 owner.

- [ ] T041 [P] [US5] Update `build.sh` header comment to
  describe the current `SMOKE_TESTS` manifest format. No
  behaviour change — comments only.

- [ ] T042 [US5] Run US5 tests (T038); both pass. Commit as
  one PR: `docs(025): A5 sync stale references to current
  entry points`.

**Checkpoint**: A5 complete. Doc-drift regressions are now
caught by `tests/docs/test_doc_sync.py`.

---

## Phase 8: User Story 10 — Meta: LLM dispatch guard allowlist contains zero entries (Priority: P1) 🎯 Tier A — depends on US1 + US2

**Goal**: The top-level acceptance criterion (SC-003, Q4c
locked 2026-05-21) holds: after A1 + A2 ship,
`tests/_helpers/llm_dispatch_allowlist.yaml` parses to `[]` (or
contains only a header comment).

**Independent Test**: `pytest tests/_helpers/test_llm_dispatch_allowlist.py`.

### Tasks for User Story 10

- [ ] T043 [US10] Verify spec 024 US1's allowlist + guard
  infrastructure has shipped:
  `ls tests/_helpers/llm_dispatch_allowlist.yaml tests/_helpers/test_llm_dispatch_allowlist.py 2>&1`.
  If either is missing, spec 024 hasn't reached the
  prerequisite point — this task is BLOCKED. Coordinate with
  the spec 024 implementer.

- [ ] T044 [US10] Run the guard's empty-allowlist assertion
  test:
  `pytest tests/_helpers/test_llm_dispatch_allowlist.py -v`.
  After T016 + T024 deletions, this MUST pass. If it fails,
  inspect the allowlist for residual entries; trace each one
  back to the production file it allowlisted and confirm A1/A2
  fully covered it.

- [ ] T045 [US10] Run the guard's "no new bypasses" test:
  `pytest tests/_helpers/test_llm_dispatch_guard.py -v` (the
  guard itself, owned by spec 024 US1). MUST pass. This
  confirms the codebase has no unallowlisted direct LLM
  invocations anywhere.

- [ ] T046 [US10] If the allowlist file is now empty (just a
  YAML header comment, no entries), consider whether to retain
  the file or delete it entirely. Recommendation: retain it
  with a comment explaining its purpose (so a future bypass
  knows where the allowlist lives). Commit any cleanup as part
  of the umbrella US10 PR or fold into the prior US1/US2
  commits.

**Checkpoint**: SC-003 (the top-level acceptance criterion)
holds. Tier A is structurally complete; ready for the Tier A
ship gate.

---

## Phase 9: Tier A Ship Gate

**Purpose**: Validate Tier A as a unit before the 022 v1 ship
window opens. Per FR-016, Tier A PRs can merge to main BEFORE
022 v1 ships; this phase is the coordination point.

- [ ] T047 Verify all Tier A user stories are complete:
  - US1 (T010–T017): tests passing, allowlist entry deleted.
  - US2 (T018–T025): tests passing, allowlist entry deleted.
  - US3 (T026–T031): tests passing, ≤ 2 quality-report sites.
  - US4 (T032–T037): tests passing.
  - US5 (T038–T042): tests passing.
  - US10 (T043–T046): allowlist empty, guard green.

- [ ] T048 Run the **Tier-A-relevant subset** of the SC-001..015
  acceptance bar per `quickstart.md` § 11. The 8 SCs listed
  below are the Tier A checks; the 4 unlisted SCs (SC-004,
  SC-005, SC-007, SC-008) are Tier-B-only (cycle_runner LOC,
  cli.py LOC, frontmatter/settings migrations — they don't
  apply pre-Tier-B); SC-013 verifies post-022-v2; SC-014 and
  SC-015 are explicitly Tier-B-only per FR-016 R3 carve-out.
  All Tier A checks pass:
  - SC-001: `pytest` exit 0
  - SC-002: `./build.sh` exit 0
  - SC-003: allowlist empty
  - SC-006: `_write_cycle_quality_report` ≤ 2 call sites
  - SC-009: `./vault --help` byte-identical (Tier A doesn't
    touch this; baseline preserved trivially)
  - SC-010: `--resume` auto-detects
  - SC-011: agent-calls sidecars have `cost_usd > 0`
  - SC-012: zero `run_cycle.sh` references

- [ ] T049 Update `CHANGELOG.md`'s `[Unreleased]` block with
  the Tier A entries (one per user story). Follow the
  per-spec-kit-stage doc-update checklist in CLAUDE.md.

- [ ] T050 If 022 v1 hasn't shipped yet, the Tier A umbrella
  PR can merge to main immediately (FR-016 carve-out for Tier
  A). If 022 v1 is ALREADY shipped, Tier A still ships
  independently — no coupling.

**Checkpoint**: Tier A shipped. The 6 Tier A user stories (US1–
US5 + US10) have landed on main as either one umbrella PR or 6
sub-PRs. The MVP fallback (Q3b: Tier A only) is reachable if
calendar pressure forces deferring Tier B to spec 026.

---

## Phase 10: Tier B Ship Gate (External — Wait for 022 v1)

**Purpose**: Block Tier B PRs from merging until 022 v1 ships
its baselines (FR-016). This is a single coordination task —
no code changes.

- [ ] T051 Verify 022 v1 has shipped to main:
  `git log --oneline origin/main | rg "spec 022 v1|0\.X\.Y"`
  (with the appropriate version). Also verify baseline files
  exist:
  `ls tests/fixtures/quality/baselines/{source-poor,tech-lite,source-rich}.baseline.json`.
  All three files MUST exist. Verify
  `./build.sh --quality` exits 0 on the current main. If yes,
  Tier B is unblocked. If no, this task remains pending —
  Tier B work can be PREPARED (branch creation, scaffolding)
  but no PR can merge until 022 v1 lands.

**Checkpoint**: Tier B gate open. US6–US9 can now merge.

---

## Phase 11: User Story 6 — B3: extract cycle-runner steps (long-lived sub-branch) (Priority: P2) Tier B

**Goal**: `pipeline/cycle_runner.py` shrinks from 2,195 lines to
< 1,500 by extracting three step modules under
`pipeline/steps/`. Per Q3a (locked 2026-05-21), this happens on
a long-lived sub-branch `025-b3-step-extraction` and ships as
ONE big PR. The cycle-runner edit lock contract
(`contracts/cycle-runner-edit-lock.contract.md`) governs
coordination during the sub-branch window.

**Independent Test**: Full sweep
(`pytest tests/pipeline/test_cycle_runner.py`) plus the new
per-step tests; pre-existing tests pass UNCHANGED.

### Sub-branch setup

- [ ] T052 [US6] From the 025 worktree, create the sub-branch
  worktree:
  ```bash
  cd ~/src/research-framework-025
  git worktree add ~/src/research-framework-b3 \
      -b 025-b3-step-extraction
  ```
  All subsequent US6 tasks (T053–T064) happen in
  `~/src/research-framework-b3/`.

- [ ] T053 [US6] Announce the cycle-runner edit lock per
  `contracts/cycle-runner-edit-lock.contract.md` § 2.1. Add the
  `CHANGELOG.md [Unreleased] § Notes for in-flight work` entry;
  commit on the sub-branch.

### Tests for User Story 6 (write FIRST)

- [ ] T054 [US6] Create `tests/pipeline/steps/test_scout.py`
  with one happy-path + one failure-path test for `run_scout`.
  Use fake_agent fixture from `tests/_helpers/`. MUST FAIL
  pre-extraction (the module doesn't exist).

- [ ] T055 [P] [US6] Create `tests/pipeline/steps/test_research.py`
  (same shape, for `run_research`).

- [ ] T056 [P] [US6] Create `tests/pipeline/steps/test_postprocess.py`
  (same shape, for `run_postprocess`).

### Implementation for User Story 6

- [ ] T057 [US6] Create `pipeline/steps/_types.py` with
  `CycleContext`, `ScoutResult`, `ResearchResult`,
  `PostprocessResult`, `AgentDispatchFn` per
  `contracts/step-module-api.contract.md` § 2 + § 4. Frozen
  dataclasses; typed fields aligned with the existing
  `cycle-NNN-{scout,research,postprocess}.json` schemas.

- [ ] T058 [US6] Create `pipeline/steps/__init__.py` re-exporting
  the three `run_*` functions + the type symbols per
  `contracts/step-module-api.contract.md` § 1.

- [ ] T058a [US6] Add a circular-import guard test at
  `tests/pipeline/steps/test_imports.py` (covers spec.md B3
  edge case "cycle-runner step extraction introduces a
  circular import"):
  ```python
  def test_pipeline_steps_imports_resolve():
      import research_framework.pipeline.steps  # noqa: F401

  @pytest.mark.parametrize("mod",
      ["scout", "research", "postprocess"])
  def test_step_module_imports_resolve(mod):
      __import__(f"research_framework.pipeline.steps.{mod}")
  ```
  Run the test; both functions must exit 0. If either raises
  `ImportError`, the step extraction has introduced a cycle —
  resolve via lazy imports inside step bodies (move
  `from research_framework.pipeline.<other_module> import X`
  from the top of the file into the function body, deferring
  the import to call time) before continuing T059.

- [ ] T059 [US6] Extract `run_scout` into
  `pipeline/steps/scout.py`. Copy the relevant code path from
  `cycle_runner.py`; adapt to take `CycleContext` and return
  `ScoutResult`. Switch `run_cycle_steps` to call the new
  function. Verify
  `pytest tests/pipeline/test_cycle_runner.py tests/pipeline/steps/test_scout.py`
  all green.

- [ ] T060 [US6] Extract `run_research` into
  `pipeline/steps/research.py` (same pattern). Verify tests
  green.

- [ ] T061 [US6] Extract `run_postprocess` into
  `pipeline/steps/postprocess.py` (same pattern). Verify tests
  green.

- [ ] T062 [US6] Confirm SC-004:
  `wc -l src/research_framework/pipeline/cycle_runner.py`
  returns < 1500. If not, extract additional non-step helper
  functions into `pipeline/steps/_helpers.py` or
  `pipeline/_cycle_helpers.py`.

- [ ] T063 [US6] Confirm each new step module sits within the
  size guidance (200–400 LOC):
  `wc -l src/research_framework/pipeline/steps/{scout,research,postprocess}.py`.

- [ ] T064 [US6] Run `./build.sh --quality` locally; confirm
  exit 0 (Tier B gate per SC-014).

### Ship the sub-branch

- [ ] T065 [US6] Open the ship PR from
  `025-b3-step-extraction` → `main` (or `025-simplify-pass`).
  PR description follows the by-step format from
  `contracts/cycle-runner-edit-lock.contract.md` § 2.4 + R1
  mitigation 4: list each step extraction as a sub-section with
  before/after diffs from a fixture cycle. Add a
  `CHANGELOG.md [Unreleased] § Refactor` entry naming the user
  story and the LOC delta (e.g. `- B3: extracted scout/research/
  postprocess steps from cycle_runner.py into pipeline/steps/
  (2,195 → <N> lines; +3 new step modules; behaviour-preserving
  per FR-009).`).

- [ ] T066 [US6] After merge, close the lock signal in
  `CHANGELOG.md [Unreleased]` per § 2.4 step 4. Remove the
  worktree:
  `git worktree remove ~/src/research-framework-b3`.

- [ ] T067 [US6] Write the audit-trail addendum to
  `docs/SIMPLIFY-PASS.md` § 6 per
  `contracts/cycle-runner-edit-lock.contract.md` § 5: actual
  branch lifetime, conflicts encountered, lessons.

**Checkpoint**: B3 complete. `cycle_runner.py` is a thin
orchestrator; the three step modules are the testable
seams for future 022 v2 metric hook retargeting.

---

## Phase 12: User Story 7 — B4: shared frontmatter parser (Priority: P2) Tier B

**Goal**: One canonical `vault/frontmatter.py` parser replaces
≥ 8 of the ≥ 12 existing parsers per
`contracts/frontmatter-parser.contract.md`.

**Independent Test**: `pytest tests/vault/test_frontmatter.py`
plus the migrated call sites' existing tests stay green.

### Tests for User Story 7 (write FIRST)

- [ ] T068 [P] [US7] Create `tests/vault/test_frontmatter.py`
  with all 13 tier-1 test cases per
  `contracts/frontmatter-parser.contract.md` § 7:
  `test_parse_empty_frontmatter`,
  `test_parse_no_frontmatter`, `test_parse_well_formed`,
  `test_parse_missing_closing_delimiter_raises`,
  `test_parse_malformed_yaml_raises`,
  `test_parse_unsafe_yaml_rejected`,
  `test_parse_unicode`, `test_parse_nested_keys`,
  `test_parse_multi_doc_yaml`,
  `test_parse_list_frontmatter_rejected`,
  `test_dump_parse_roundtrip`, `test_perf_1mb_file`,
  `test_short_circuit_on_no_frontmatter`. All MUST FAIL pre-
  implementation (the module doesn't exist).

### Implementation for User Story 7

- [ ] T069 [US7] Create `vault/frontmatter.py` implementing
  `parse_frontmatter`, `parse_frontmatter_str`,
  `dump_frontmatter`, `FrontmatterParseError` per
  `contracts/frontmatter-parser.contract.md` § 1 + § 2 + § 3.
  Use `yaml.safe_load` (no new deps); line-by-line scan for
  the closing delimiter (no whole-file regex).

- [ ] T070 [US7] Verify all 13 tests from T068 pass:
  `pytest tests/vault/test_frontmatter.py -v`.

- [ ] T071 [US7] Read `_pipeline/025-frontmatter-sites.txt`
  (T003). Pick the first 8 sites for migration (the easiest /
  most isolated). For each, in a small commit:
  - Replace inline parser with
    `from research_framework.vault.frontmatter import parse_frontmatter`.
  - Use `fm, body = parse_frontmatter(path)`.
  - Run the site's existing tests to confirm no regression.

- [ ] T072 [US7] For any sites NOT migrated (holdouts), add an
  inline comment per `contracts/frontmatter-parser.contract.md`
  § 6 template explaining the specific reason ("needs soft-fail
  for schema-drift detection", etc.). Each holdout's reason must
  be specific and verifiable.

- [ ] T073 [US7] Verify SC-007:
  `rg -l 'from research_framework.vault.frontmatter import' src/research_framework/ | wc -l`
  returns ≥ 8.

- [ ] T074 [US7] Run `./build.sh --quality` locally; confirm
  exit 0.

- [ ] T075 [US7] Commit as one PR: `feat(025): B4 canonical
  frontmatter parser + migrate N call sites`. Add a
  `CHANGELOG.md [Unreleased] § Refactor` entry naming US7 and
  the migration count (e.g. `- B4: introduced vault/frontmatter.py
  canonical parser; migrated N of M+ call sites; remaining
  holdouts documented inline (FR-010 + SC-007).`).

**Checkpoint**: B4 complete. Frontmatter parsing is consistent
across the codebase; future metric calculators can read frontmatter
without re-implementing edge cases.

---

## Phase 13: User Story 8 — B5: split `cli.py` into subpackage (Priority: P2) Tier B

**Goal**: `cli.py` shrinks to < 200 lines (a re-export); the
`cli/` subpackage organises commands into 5–8 group modules per
`contracts/cli-subpackage.contract.md`.

**Independent Test**:
`pytest tests/cli/test_build_parser_stable.py` (the byte-
identical `--help` golden-file test using fixtures from T001).

### Tests for User Story 8 (write FIRST)

- [ ] T076 [US8] Create `tests/cli/test_build_parser_stable.py`:
  - `test_help_byte_identical`: subprocess `./vault --help`;
    diff against `tests/cli/fixtures/help_output_pre_025.txt`
    (from T001). MUST PASS pre-implementation (the refactor
    hasn't started, so trivially identical). MUST CONTINUE to
    pass post-implementation (SC-009).
  - `test_subcommand_help_byte_identical`: parametrised over
    `research`, `audit`, `vault`, `quality`; same diff against
    `help_<subcommand>_pre_025.txt`. Same pass condition.
  - `test_argparse_topology_unchanged`: count and depth of
    subparsers match pre-B5 snapshot.
  - `test_external_import_path`: `from research_framework.cli
    import build_parser` resolves and returns an
    `ArgumentParser`.

- [ ] T077 [P] [US8] Create `tests/cli/test_research_resume.py`
  if not already present from US4 (T032). If US4 has shipped
  pre-B5, the resume tests already exist; B5 must keep them
  green when the resume handler moves from `cli.py` to
  `cli/research.py`.

### Implementation for User Story 8

- [ ] T078 [US8] Create the `cli/` package skeleton:
  `cli/__init__.py` (with stub `build_parser`), `cli/_common.py`
  (empty for now).

- [ ] T079 [US8] Migrate command groups one at a time. After
  each migration, run T076's tests:
  - `cli/research.py`: extract the `research` subcommand and its
    resume handler (US4's `_resolve_resume_cycle` from T034
    moves here).
  - `cli/audit.py`: extract the `audit` subcommand.
  - `cli/vault.py`: extract `write`, `update`, `onboard`,
    `install` subcommands.
  - `cli/quality.py`: extract `quality-baseline-update` (spec
    022 owns; if absent, omit).
  - Plus any other subcommands discovered during migration.

- [ ] T080 [US8] After all migrations, shrink `cli.py` to the
  re-export per `contracts/cli-subpackage.contract.md` § 1:
  ```python
  from research_framework.cli import build_parser, main
  __all__ = ["build_parser", "main"]
  ```

- [ ] T081 [US8] Wire `cli/__init__.py::build_parser` to import
  each `cli/<group>.py` and call its `register(subparsers)`
  function. Preserve pre-B5 subcommand registration order
  (see `contracts/cli-subpackage.contract.md` § 5
  recommendation 1) to keep byte-identical `--help` output.

- [ ] T082 [US8] Verify SC-005:
  `wc -l src/research_framework/cli.py` returns ≤ 200 (the
  re-export will be ~5 lines). Also verify each `cli/*.py` ≤
  250 lines and `cli/__init__.py` ≤ 50 lines.

- [ ] T083 [US8] Run T076 tests; all pass (byte-identical
  `--help`). Run T077 tests; all pass (resume handler works
  from new location). Run full sweep.

- [ ] T084 [US8] Run `./build.sh --quality`; exit 0.

- [ ] T085 [US8] Commit as one PR: `feat(025): B5 split cli.py
  into cli/ subpackage`. Add a `CHANGELOG.md [Unreleased] §
  Refactor` entry naming US8 and the LOC delta (e.g. `- B5: split
  cli.py (1.1k LOC) into cli/ subpackage (5 group modules);
  build_parser() re-exported unchanged; ./vault --help
  byte-identical (FR-011 + SC-005 + SC-009).`).

**Checkpoint**: B5 complete. CLI organisation matches the
`./vault <command>` mental model.

---

## Phase 14: User Story 9 — B7: shared settings loader (Priority: P2) Tier B

**Goal**: Canonical `pipeline/settings.py::load_vault_settings`
returns a typed `VaultSettings` frozen dataclass; ≥ 6 existing
call sites migrate per
`contracts/settings-loader.contract.md`.

**Independent Test**: `pytest tests/pipeline/test_settings_loader.py`.

### Tests for User Story 9 (write FIRST)

- [ ] T086 [P] [US9] Create
  `tests/pipeline/test_settings_loader.py` with all 11 tier-1
  test cases per `contracts/settings-loader.contract.md` § 7:
  happy path, missing required keys, invalid types, unknown
  keys → extras, stage convenience method, YAML parse error,
  missing file, frozen immutability, default values,
  backwards-compat with pre-A1/A2 settings.yaml. All MUST FAIL
  pre-implementation.

### Implementation for User Story 9

- [ ] T087 [US9] Create `pipeline/settings.py` implementing
  `VaultSettings`, `StageSettings`, `SettingsError`,
  `load_vault_settings` per
  `contracts/settings-loader.contract.md` § 1 + § 2 + § 3.
  Frozen dataclasses; explicit validation with clear error
  messages.

- [ ] T088 [US9] Verify T086 tests pass:
  `pytest tests/pipeline/test_settings_loader.py -v`.

- [ ] T089 [US9] Read `_pipeline/025-settings-sites.txt`
  (T004). Pick the first 6 sites for migration. For each, in a
  small commit:
  - Replace inline `yaml.safe_load(...)` of `settings.yaml`
    with
    `from research_framework.pipeline.settings import load_vault_settings`.
  - Use `settings = load_vault_settings(vault_dir)` then
    typed field access.
  - Run the site's existing tests.

- [ ] T090 [US9] Refactor the defensive
  `settings.get("plan_narrator", {}).get("tier", "standard")`
  pattern from T015 (US1) to use the new typed accessor:
  `settings.stage("plan_narrator").tier`. Same for the
  probe_retrieval site from T023 (US2).

- [ ] T091 [US9] For any sites NOT migrated (holdouts), add
  inline comment with specific reason per
  `contracts/settings-loader.contract.md` § 4.

- [ ] T092 [US9] Verify SC-008:
  `rg -l 'from research_framework.pipeline.settings import' src/research_framework/ | wc -l`
  returns ≥ 6.

- [ ] T093 [US9] Run `./build.sh --quality`; exit 0.

- [ ] T094 [US9] Commit as one PR: `feat(025): B7 canonical
  settings loader + migrate N call sites`. Add a
  `CHANGELOG.md [Unreleased] § Refactor` entry naming US9 and
  the migration count (e.g. `- B7: introduced
  pipeline/settings.py canonical loader returning typed
  VaultSettings dataclass; migrated N of M call sites
  (FR-012 + SC-008).`).

**Checkpoint**: B7 complete. Settings access is typed; the
plan_narrator/probe_retrieval tier resolution from A1/A2 now
uses the typed accessor.

---

## Phase 15: Polish & Final Acceptance

**Purpose**: Cross-cutting cleanup, documentation, and the
final SC-001..SC-015 acceptance gate.

- [ ] T095 [P] Run the full SC-001..SC-015 verification per
  `quickstart.md` § 11. Every check must pass. Document any
  exceptions explicitly (e.g. SC-013 is fulfilled by 022 v2
  follow-up, not by 025 itself).

- [ ] T096 [P] Update `specs/_archive/025-simplify-pass/spec.md` status
  header to `**Status:** SHIPPED v0.X.Y (2026-MM-DD)` per the
  per-spec-kit-stage doc-update checklist.

- [ ] T097 [P] Update `docs/ROADMAP.md`:
  - Flip queue entry 1b from `[~]` (in-flight) to `[x]`.
  - Move to "Completed (recent)" block with ship-version + date.
  - If MVP fallback activated (Tier A only), document the
    Tier B carve-out to spec 026.

- [ ] T098 [P] Update `docs/TODO.md`: DELETE any entries
  resolved by the ship (per CLAUDE.md doc-discipline rule).

- [ ] T099 [P] Update `CHANGELOG.md`: consolidate the per-
  user-story entries (added during Tier A T049 and Tier B
  T065/T075/T085/T094) into a single coherent `[0.X.Y] -
  2026-MM-DD` block. Add a fresh `[Unreleased]` heading at the
  top for the next cycle.

- [ ] T099a [P] Bump `pyproject.toml::tool.poetry.version` (or
  the equivalent table — verify the exact path at task time;
  `pyproject.toml` may use `[project]` for PEP 621). Target
  version depends on the ship scope:
  - **Tier A + Tier B (full 025 scope)**: minor bump
    (e.g. `0.2.33` → `0.3.0`) — the cycle-runner step extraction
    and cli.py split are user-visible structural changes
    even though the surface (CLI flags, file formats) is
    preserved.
  - **Tier A only (Q3b MVP fallback)**: patch bump
    (e.g. `0.2.33` → `0.2.34`) — A1/A2/A4/A5/A6 are pure
    refactor + bug-fix.

  The bump MUST land in the SAME commit as the CHANGELOG
  `[Unreleased]` → `[0.X.Y]` block flip from T099, because
  `.github/workflows/release.yml` (per `docs/RELEASE.md`)
  auto-detects on `pyproject.toml` version changes and
  triggers the release flow. If you flip CHANGELOG without
  bumping pyproject.toml, release.yml doesn't fire — the
  ship is invisible to users.

- [ ] T100 [P] Update `CLAUDE.md`'s `Recent Changes` block:
  add the 025 ship entry; prune older entries to the most
  recent 5 ship cycles per the doc-discipline rule.

- [ ] T101 If the B3 long-lived sub-branch shipped successfully
  (US6 T065 merged), audit the lock window outcome per
  `contracts/cycle-runner-edit-lock.contract.md` § 5 — the
  addendum to `docs/SIMPLIFY-PASS.md` § 6 from T067 should be
  present. If absent, write it now.

- [ ] T102 Spec 022 v2 hook retargeting (out of scope for 025
  itself, but flagged for the immediate follow-up): file an
  entry in `docs/TODO.md` or open a tracking issue noting that
  022's metric hooks now need to retarget from the pre-B3
  seams to the new `pipeline/steps/<step>.py` return values.
  Estimated effort: half a day.

**Checkpoint**: Spec 025 is SHIPPED. All success criteria met
(modulo SC-013 which is the planned 022 v2 follow-up).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — runs immediately.
- **Phase 2 (Foundational)**: Depends on Phase 1.
- **Phase 3–7 (Tier A: US1–US5)**: Each depends on Phase 2.
  Inter-phase parallel opportunities:
  - US1 (Phase 3), US4 (Phase 6), US5 (Phase 7) touch
    disjoint files → fully parallel.
  - US2 (Phase 4) and US3 (Phase 5) both touch
    `cycle_runner.py` → US2 first, US3 second (or US3
    integrates A2's changes into its own diff).
- **Phase 8 (US10 meta)**: Depends on Phases 3 + 4 (US1 + US2
  allowlist deletions).
- **Phase 9 (Tier A ship gate)**: Depends on Phases 3–8.
- **Phase 10 (Tier B external gate)**: Coordination only;
  waits for 022 v1 ship.
- **Phase 11 (US6 B3)**: Depends on Phase 10 (Tier B gate).
- **Phase 12–14 (US7 B4, US8 B5, US9 B7)**: Depend on Phase 10.
  Parallel with each other (disjoint files).
- **Phase 15 (Polish)**: Depends on all prior phases.

### User Story Dependencies (recommended sequence)

```text
 Phase 1 (Setup)
  │
  ▼
 Phase 2 (Foundational)
  │
  ├──────────────► US1 (Phase 3) ──┐
  │                                │
  ├──────────────► US2 (Phase 4) ──┼──► US3 (Phase 5) ─┐
  │                                │                    │
  ├──────────────► US4 (Phase 6) ──┤                    │
  │                                │                    │
  └──────────────► US5 (Phase 7) ──┘                    │
                                                         │
                   US10 (Phase 8) ◄─────────depends─────┤
                                                         │
                   Tier A ship gate (Phase 9) ◄─────────┘
                          │
                          ▼
                   022 v1 ships (Phase 10, external)
                          │
                          ├──────────► US6 (Phase 11, sub-branch)
                          │
                          ├──────────► US7 (Phase 12)
                          │
                          ├──────────► US8 (Phase 13)
                          │
                          └──────────► US9 (Phase 14)
                                              │
                                              ▼
                                   Polish (Phase 15)
                                              │
                                              ▼
                                          SHIPPED
```

### Within Each User Story

- Tests MUST be written and FAIL before implementation
  (Principle III: Test-First).
- For B3 (US6) specifically: the cycle-runner edit lock is
  active for the entire sub-branch window (T053 → T066).
  Other work touching `pipeline/cycle_runner.py` is paused.

### Parallel Opportunities

Within Tier A:
- T001..T005 (Setup) all `[P]` — run together.
- T008..T009 (Foundational verifications) `[P]`.
- US1 (Phase 3) + US4 (Phase 6) + US5 (Phase 7) fully parallel
  across implementers.
- US2 (Phase 4) blocks US3 (Phase 5) on `cycle_runner.py`.

Within Tier B:
- US7 (Phase 12) + US8 (Phase 13) + US9 (Phase 14) fully parallel.
- US6 (Phase 11) is the lock holder; other Tier B PRs MAY
  touch their own files freely (the lock is scoped to
  `cycle_runner.py` only). Tier B PRs targeting code in `cli/`,
  `vault/`, or new modules in `pipeline/` are unaffected.

### MVP definition (Q3b — calendar-slip fallback)

If calendar pressure activates the Q3b MVP fallback before
2026-05-29, the MVP cut is **Tier A only** (US1–US5 + US10):

- Phases 1–9 + 15 execute.
- Phases 10–14 (Tier B) defer to a follow-up spec (proposed
  spec 026, scoped from this spec's Tier B user stories).
- Phase 15 (Polish) reflects "Tier A shipped; Tier B deferred"
  in CHANGELOG and ROADMAP.

MVP success criteria:
- SC-001, SC-002, SC-003, SC-006, SC-009, SC-010, SC-011,
  SC-012, SC-013 (modulo 022 v2 timing).
- SC-004, SC-005, SC-007, SC-008, SC-014, SC-015 deferred to
  spec 026.

### Incremental Delivery (Tier A)

Each Tier A user story is a separate PR (US1, US2, US3, US4,
US5 each); US10 is verification-only (no PR of its own, or a
minimal "remove allowlist file" PR if cleanup chosen).
Recommend the 5 Tier A PRs land within a single calendar week
to compound into an early Tier A ship.

### Incremental Delivery (Tier B)

Each Tier B user story is a separate PR (B4, B5, B7 each); B3
ships as ONE big PR from the sub-branch (Q3a locked decision).
Recommend B3 + the 3 small Tier B PRs land within a single
calendar week post-022-v1 to compound into the full 025 ship.

---

## Parallel Example: Tier A initial-week sprint

```bash
# Implementer A (this Cursor session):
Task: T001 (capture --help golden)
Task: T002 (pre-refactor LOC metrics)
Task: T010..T017 (US1 A1 — narrator)
Task: T032..T037 (US4 A4 — resume)

# Implementer B (parallel, separate session/worktree):
Task: T018..T025 (US2 A2 — probe)
Task: T038..T042 (US5 A5 — doc sync)

# Implementer C (parallel, after US2 lands):
Task: T026..T031 (US3 A6 — context manager)

# Coordinator (anyone):
Task: T043..T046 (US10 meta verification — runs last)
Task: T047..T050 (Tier A ship gate)
```

---

## Implementation Strategy

### Phase ordering rationale

- **Phases 1–2 first**: capture baselines; cheap insurance
  against later regressions.
- **Phase 3–7 in any order** (subject to the cycle_runner.py
  file-conflict ordering note in Phase 5): every Tier A item is
  small enough to ship as its own PR; sequencing is dictated
  by reviewer availability + file conflict avoidance, not by
  dependency.
- **Phase 8 mandatory before Phase 9**: SC-003 is the top-level
  acceptance criterion; the ship gate cannot pass without it.
- **Phases 11–14 require 022 v1 first** (FR-016): the smoke
  gate `./build.sh --quality` cannot pass without baselines,
  which 022 v1 produces.

### Risk-bounded delivery (R1, R2, R3 from spec.md)

- **R1 (B3 sub-branch drift)**: Phases 11.T053 (lock open),
  weekly rebase per
  `contracts/cycle-runner-edit-lock.contract.md` § 2.3,
  Phase 11.T065 (5-day ship target), Phase 11.T066–T067 (close).
- **R2 (Tier B behaviour-preservation gap pre-022-v1)**: Phase 10
  blocks Tier B until 022 v1 ships. Per-item migration tests in
  US7/US8/US9.
- **R3 (022 v1 ship slip blocks Tier B)**: Tier A is exempt
  (Phase 9.T050 ships Tier A independent of 022 v1). MVP
  fallback (Q3b) is the contingency.

---

## Notes

- Task IDs are sequential T001..T102 plus three letter-suffix
  tasks added during `/speckit.analyze` (T020a probe-disabled
  edge-case test, T058a circular-import guard, T099a pyproject
  bump). Total: 105 tasks. Tier A encompasses T001–T050 +
  T020a (51 tasks); Tier B encompasses T051–T102 + T058a +
  T099a (54 tasks).
- `[P]` marker means file-disjoint and dependency-free.
- File paths are exact; the implementer SHOULD verify line
  numbers (e.g. probe block "lines ~1137–1252") at task
  execution time because the file may have shifted slightly
  since spec authoring.

### Branching convention (Q4b — per-US sub-branches)

Spec.md Q4b (locked 2026-05-21) requires one umbrella spec-kit
branch `025-simplify-pass` PLUS per-merge-unit sub-branches.
Concretely, each user story ships as a sub-branch off
`025-simplify-pass`:

| User Story | Sub-branch name (recommended) | Notes |
|------------|-------------------------------|-------|
| US1 (A1) | `025-a1-narrator` | Tier A; merges back to `025-simplify-pass` then via the umbrella PR (or directly to `main` if shipping per-US) |
| US2 (A2) | `025-a2-probe` | Tier A; merge order: after US1 (cycle_runner.py conflict) |
| US3 (A6) | `025-a6-quality-report-guard` | Tier A; merge order: after US2 |
| US4 (A4) | `025-a4-resume-autodetect` | Tier A; parallel-safe with US1/US5 |
| US5 (A5) | `025-a5-doc-sync` | Tier A; parallel-safe with all |
| US6 (B3) | `025-b3-step-extraction` | Tier B; **long-lived per Q3a**; ships as ONE big PR (the exception) |
| US7 (B4) | `025-b4-frontmatter-parser` | Tier B; parallel-safe with US8/US9 |
| US8 (B5) | `025-b5-cli-subpackage` | Tier B; parallel-safe with US7/US9 |
| US9 (B7) | `025-b7-settings-loader` | Tier B; parallel-safe with US7/US8 |
| US10 (meta) | (no PR; verification only) | Folded into the umbrella ship gate (Phase 9) |

**Sub-branch lifecycle** for each Tier A US:
1. From `025-simplify-pass`, create the sub-branch:
   `git checkout -b 025-a1-narrator 025-simplify-pass`.
2. Implement the US's tasks (tests-first per Principle III).
3. Open the PR back to `025-simplify-pass` (NOT directly to
   `main`).
4. After review, merge to `025-simplify-pass`.
5. After all Tier A user stories merge to `025-simplify-pass`,
   open the umbrella PR `025-simplify-pass` → `main` (this is
   the Tier A ship PR per Phase 9 T050).

**Alternative**: If reviewer capacity is tight, the
spec-author MAY choose to merge per-US PRs directly to `main`
instead of to `025-simplify-pass`. This is faster but loses
the umbrella-PR audit trail. Default recommendation:
sub-branches → `025-simplify-pass` → umbrella PR → `main`.

For Tier B, the same pattern applies, except B3 ships from
its own long-lived sub-branch worktree (set up by T052) and
its PR goes directly to `main` (NOT to `025-simplify-pass`,
because Tier B PRs ship after the Tier A umbrella has
already merged).

### General hygiene

- Each task's verification step (run tests, `./build.sh
  --quality`) is non-optional; the per-task checklist is the
  unit of completeness, not the PR.
- Avoid: cross-user-story file conflicts beyond those flagged
  (US2/US3 on cycle_runner.py); orphan PRs that miss their
  user story label; CHANGELOG entries that lump multiple user
  stories together (one entry per user story per Tier A; one
  entry per user story per Tier B).
