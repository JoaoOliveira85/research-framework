# Feature Specification: The weekly pipeline runner

**Status**: shipped(2026-09-07, commit 6935644) — this spec is a *record* of
behaviour that already shipped, written from the code at that commit. It adds
no scope. Where the code and the older documents disagree, the code is
described and the disagreement is filed under § Known divergences.

**Spec**: `075-pipeline-runner` · **Supersedes as the owning document**:
`specs/_archive/015g-pipeline-orchestrator-command/` (SUBSUMED 2026-05-26 by
ADR-0009 and never replaced) · **Epic**: #217 · **Issue**: #275, #50

---

## Why this spec exists

The seven-phase weekly runner is the most-run surface in the framework and
the only one with no owning spec. Its behaviour was documented inside spec
015g, which ADR-0009 subsumed in May 2026 and which has carried a
"design-history, do not plan against it" banner ever since. Four defects
(#218, #219, #222, #223) were then found and fixed against a subsumed spec,
and one of them — #222, a run that researched for 34 seconds, wrote nothing,
and recorded itself `done` — is precisely the class of bug a written
completion contract prevents.

A reader with no code access must be able to build this runner from this
document. That is the bar.

## Scope

**In scope**: the `research-framework pipeline <vault> <command>` verb, its
seven phases, the on-disk artifacts it reads and writes, how it decides a
phase succeeded, how it bounds an agent call, and what it reports.

**Out of scope, and load-bearing to say so**: the *multi-cycle orchestrator*
(`research-framework generate` / `generate --resume` / `cycle`) is a
different runtime. It owns budget enforcement, approval gates, per-call cost
sidecars, and the research-branch git lifecycle. Nothing in this spec applies
to it, and it shares no state file with the runner
(`_pipeline/pipeline-state.json` here, `_pipeline/state.json` there). The two
are routinely conflated because both call themselves "the pipeline"; see
§ Known divergences D1. Cost and budget are specified in `033-cost-enforcement`
and `061-cycle-budget-config`; dispatch is specified in `078-dispatch-surface`.

---

## User Scenarios & Testing

### User Story 1 — A weekly run stops at the human checkpoint (Priority: P1)

An operator runs the week's collection and wants the machine to stop before
it spends money researching topics nobody has looked at.

1. **Given** a vault whose `research.spec.md` declares at least one RSS
   source, **When** the operator runs `pipeline <vault> full`, **Then** the
   runner executes `collect`, `extract` and `scout` in that order, records
   `triage` as `waiting`, leaves `research`, `verify` and `report` at
   `pending`, and returns 0.
2. **Given** that paused run, **When** the operator inspects
   `_pipeline/pipeline-state.json`, **Then** every executed phase carries a
   `status`, `started_at`, `finished_at`, a phase-specific `summary` and an
   `errors` list.
3. **Given** the pause message, **When** the operator reads it, **Then** it
   names the artifact holding the queue (`_pipeline/scout-report.json`) and
   the number of topics that a resume would research.

### User Story 2 — A phase is only "done" when it produced its artifact (Priority: P1)

The runner must not report success it has not earned.

1. **Given** a scout agent that exits 0 but writes no
   `_pipeline/scout-report.json`, **When** the `scout` phase closes,
   **Then** the phase is `failed`, not `done`, and the run returns 1.
2. **Given** a research agent that exits 0 and reports zero notes against a
   **non-empty** topic queue, **When** the `research` phase closes,
   **Then** the phase is `failed`.
3. **Given** a research agent that reports zero notes against an **empty**
   queue, **When** the phase closes, **Then** the phase is `done` and the
   summary records `empty_queue_reason` — an honest nothing is not a failure.
4. **Given** a report agent that exits 0 but leaves `_pipeline/exports/`
   without a `*.md` file, **When** the `report` phase closes, **Then** the
   phase is `failed`.

### User Story 3 — Nothing collected is distinguished from nothing understood (Priority: P2)

1. **Given** a vault declaring only sources the framework has no collector
   for (web, GitHub, arXiv, Reddit, HN), **When** `collect` runs, **Then**
   the phase is `skipped`, each unsupported source is named in the summary
   and logged at WARNING, and the run returns 0.
2. **Given** a vault declaring an RSS feed that legitimately returned no new
   items, **When** `collect` runs, **Then** the phase is `done`, not
   `skipped` — an empty feed is a result, an absent collector is a gap.
3. **Given** a collector that raised, **When** `collect` runs, **Then** the
   phase is `failed`, never `skipped`.

### User Story 4 — A hung agent cannot hang the week (Priority: P1)

1. **Given** an agent subprocess that never exits, **When** the phase's
   timeout elapses, **Then** the runner terminates the agent's whole process
   group, records the timeout as the phase's reason, and returns 1 within a
   bounded wall clock.
2. **Given** that agent spawned grandchildren, **When** the timeout fires,
   **Then** the grandchildren are killed too.
3. **Given** any agent dispatch, **When** it completes or is killed, **Then**
   its merged stdout/stderr is on disk under `_pipeline/logs/` and the phase
   summary names that log file.

### User Story 5 — `status` answers "why did this run fail" (Priority: P2)

1. **Given** a completed or failed run, **When** the operator runs
   `pipeline <vault> status`, **Then** each phase is reported with its
   status, a derived duration, its summary and its recorded errors.
2. **Given** a phase that started and never finished, **When** `status`
   renders it, **Then** its duration is reported as unknown, never as `0`.
3. **Given** `--json`, **When** `status` runs off a TTY, **Then** the output
   is JSON regardless of the terminal, and without the flag it is text
   regardless of the terminal.

### Edge Cases

- No `_pipeline/pipeline-state.json` at all → `status` reports all seven
  phases `pending` with unknown durations, and exits 0.
- A `pipeline-state.json` that is not valid JSON → `status` returns a
  single-key `{"error": ...}` object rather than raising.
- `agent_call.py` is not found in the vault or the framework checkout → the
  dispatch is a no-op that reports success, so a vault without the script is
  not permanently broken (see § Known divergences D3 — this is a deliberate
  carve-out with a real failure mode).
- A phase whose prompt template does not exist in this vault → the dispatch
  fails fast with exit 2 and the phase names the missing source.

---

## Requirements

### Functional Requirements

**Command surface**

- **FR-001**: The runner MUST be reachable as
  `research-framework pipeline <vault> <command>` where `<command>` is one of
  `full`, `collect`, `extract`, `scout`, `resume`, `finish`, `status`.
- **FR-002**: `<vault>` MUST be an existing directory; otherwise the CLI MUST
  exit 2 without touching state.
- **FR-003**: `--quiet` MUST suppress the per-phase narration on stdout
  without suppressing failures, and MUST NOT suppress the log file.
- **FR-004**: `--json` MUST apply to `status` only, and MUST be an explicit
  flag — the output format MUST NOT be inferred from whether stdout is a TTY.
- **FR-005**: The `pipeline` verb group MUST default its log level to `info`
  even when stdout is redirected (every cron/launchd invocation), overridable
  by an explicit `--log-level`.
- **FR-006**: `--budget-cap` MUST be accepted by the parser and MUST always
  be refused with exit 2 and a message naming a surface that does work. No
  pipeline phase records per-call cost, so there is nothing to enforce a cap
  against, and a silently ignored cap is worse than a refused one.

**The phase graph**

- **FR-007**: The phases are exactly, and in this order: `collect`,
  `extract`, `scout`, `triage`, `research`, `verify`, `report`.
- **FR-008**: `full` MUST run `collect`, `extract`, `scout`, then mark
  `triage` `waiting` and stop. It MUST NOT run `research`, `verify` or
  `report`.
- **FR-009**: `collect`, `extract` and `scout` MUST each run exactly their
  own phase.
- **FR-010**: `resume` MUST mark `triage` `done` and run `research` only.
- **FR-011**: `finish` MUST run `verify` then `report`, and MUST NOT run
  `research` under any circumstance — including when the queue is empty.
- **FR-012**: `triage` has no driver. It is a state marker and a human pause
  point: the operator edits `_pipeline/scout-report.json` to defer topics,
  and git holds the original.
- **FR-013**: `full` MUST start from a fresh state record (new `run_id`,
  new `started_at`), discarding the previous run's phase history.
- **FR-014**: `resume` MUST proceed even when `triage` is in an unexpected
  status, logging a warning rather than refusing — the operator, not the
  state file, decides that the checkpoint is passed.

**Phase completion — the #222 contract**

- **FR-015**: A phase's completion MUST be determined by the artifact it was
  supposed to produce, never by the agent subprocess's exit code alone.
- **FR-016**: `scout` is `done` only if the agent exited 0 **and**
  `_pipeline/scout-report.json` parses **and** carries a `topics_found.new`
  list. The queue size MUST be recorded in the phase summary.
- **FR-017**: `research` is `done` only if the agent exited 0 **and** either
  `research-report.json` reports a non-empty `notes_created`/`notes_updated`,
  or the queue was empty and the summary records why.
- **FR-018**: `report` is `done` only if the agent exited 0 **and** at least
  one `*.md` exists under `_pipeline/exports/`. The newest MUST be recorded
  as `latest_export`.
- **FR-019**: `collect` MUST distinguish three outcomes: `failed` (a
  collector raised), `skipped` (every declared source is one no collector
  supports, and nothing was collected), and `done` (including an RSS feed
  that legitimately returned nothing). Each unsupported source MUST be named
  in the summary and logged at WARNING.
- **FR-020**: `verify` MUST be `done` for a `PASS` or `WARN` verdict and
  `failed` for `FAIL` or an exception. It MUST run against the corpus
  directory, not the vault root, and MUST NOT mutate any note (`auto_fix` is
  forced off).
- **FR-021**: A phase that reports `failed` MUST log its errors at ERROR
  level and MUST name the state file that holds the record. `--quiet` MUST
  NOT silence a failure.

**Agent dispatch bounds**

- **FR-022**: Every agent dispatch MUST be bounded by a wall-clock timeout,
  resolved as: the `RF_PIPELINE_AGENT_TIMEOUT_S` environment variable (a
  value `<= 0` meaning "no bound", deliberately); else the vault's own
  `stages.<stage>.timeout_s` or `default_executor.timeout_s` plus a grace
  margin; else a built-in default. An unparseable override MUST fall back,
  not crash.
- **FR-023**: On timeout the runner MUST terminate the agent's entire process
  group (SIGTERM, grace, SIGKILL), not just the direct child, and MUST record
  the timeout as the phase's reason.
- **FR-024**: Every dispatch MUST tee merged stdout/stderr to a per-phase log
  file under `_pipeline/logs/`, and the phase summary MUST name that file. A
  bounded tail of that output MUST reach the phase's `errors` list.
- **FR-025**: The runner MUST read the vault's `settings.yaml` for
  `timeout_s` only, with a tolerant raw parse — a settings file that fails
  full validation MUST NOT prevent the runner from bounding a subprocess.

**State and reporting**

- **FR-026**: The runner MUST persist `_pipeline/pipeline-state.json` through
  an atomic write (temp file in the same directory, fsync, rename), creating
  parent directories as needed, so a killed run never leaves a truncated
  state file.
- **FR-027**: `status` MUST report, per phase: status, a duration derived
  from `started_at`/`finished_at`, the summary, and the errors. A duration
  that cannot be derived MUST be reported as unknown, never as `0`.
- **FR-028**: `status` MUST return 0 for a missing state file and MUST return
  an `error` object rather than raising for an unparseable one.
- **FR-029**: Exit codes: `0` when no phase failed (a `skipped` phase is 0),
  `1` when a phase failed, `2` for usage and environment errors. `full` and
  `finish` MUST return the maximum across the phases they sequence.
- **FR-030**: A non-zero exit MUST always have written a reason to stderr or
  logged at ERROR; the CLI MUST append a pointer to
  `pipeline-state.json` if a verb returns non-zero silently.

### Key Entities

| Entity | Where | Shape |
| --- | --- | --- |
| Run state | `_pipeline/pipeline-state.json` | `{run_id, started_at, framework_version, phases: {<name>: {status, started_at, finished_at, summary, errors}}}` |
| Phase status | inside run state | `pending` \| `in_progress` \| `waiting` \| `done` \| `skipped` \| `failed` |
| Topic queue | `_pipeline/scout-report.json` | `{topics_found: {new: [...], existing: [...]}}` — written by the scout agent, read by `research` |
| Research result | `_pipeline/research-report.json` | `{notes_created: [...], notes_updated: [...]}` |
| Context tree | `_pipeline/extracted/context-tree.md` | written by the extract processor |
| Weekly export | `_pipeline/exports/*.md` | written by the report agent |
| Rendered prompt | `_pipeline/<stage>-prompt.rendered.md` | the stage's prompt source with this run's absolute artifact paths substituted |
| Phase log | `_pipeline/logs/<stage>-<timestamp>.log` | merged agent stdout/stderr |
| Verify report | `_pipeline/logs/verify-<timestamp>.json` | the full per-note verdict detail the state file only summarises |
| Declared sources | `_pipeline/spec-parse.json` → `data_sources[]` | each `{name, type, access_method, ...}` |

### Prompt sources

Three phases dispatch an agent, and each has one prompt source:

| Stage | Source | Substitutions |
| --- | --- | --- |
| `scout` | `_pipeline/prompts/scout-prompt.md` | `{CYCLE_NUM}`, `{SCOUT_REPORT}`, `{RESEARCH_REPORT}` |
| `research` | `_pipeline/prompts/dfs-prompt.md` | same |
| `report` | `.claude/commands/report.md` | same, plus a prepended run-context block naming this run's absolute artifact paths — the report source is an agent definition, not a template with placeholders |

The rendered text is written to `_pipeline/<stage>-prompt.rendered.md` and
that file's path is what the dispatch receives. The verbatim source of each
template is reproduced under `docs/prompts/` and kept honest by
`tests/docs/test_prompt_corpus_is_current.py` (issue #280).

## Success Criteria

- **SC-001**: A run that produced nothing never reports success. Every one of
  the three artifact-bearing phases fails when its artifact is absent,
  unparseable, or empty against a non-empty input.
- **SC-002**: A hung agent cannot extend a run past its resolved timeout plus
  the grace margin, and leaves no orphaned grandchildren.
- **SC-003**: `status` alone is sufficient to answer "which phase failed, how
  long did it take, and what did it say" without reading a log file first.
- **SC-004**: No pipeline phase can spend money without the operator knowing:
  `--budget-cap` is refused rather than silently ignored, and the refusal
  names the surface that does enforce a cap.

---

## Acceptance coverage

| User story | Evidence |
| --- | --- |
| US1 — A weekly run stops at the human checkpoint | `tests/pipeline/test_runner.py::test_full_pipeline_writes_correct_state`, `tests/pipeline/test_runner_triage_prompt.py::test_pause_names_the_real_triage_artifact` |
| US2 — A phase is only "done" when it produced its artifact | `tests/pipeline/test_runner_phase_artifacts.py::test_exit_zero_with_no_report_is_not_done`, `tests/pipeline/test_runner_phase_artifacts.py::test_zero_notes_against_a_non_empty_queue_is_not_done` |
| US3 — Nothing collected is distinguished from nothing understood | `tests/pipeline/test_runner_collect_sources.py::test_declared_web_and_github_sources_make_the_phase_skipped`, `tests/pipeline/test_runner_collect_sources.py::test_an_empty_rss_feed_is_done_not_skipped` |
| US4 — A hung agent cannot hang the week | `tests/pipeline/test_runner_agent_timeout.py::test_a_hung_agent_does_not_hang_the_pipeline`, `tests/pipeline/test_runner_agent_timeout.py::test_the_agents_grandchildren_are_killed_too` |
| US5 — `status` answers "why did this run fail" | `tests/pipeline/test_runner.py::test_reports_errors_persisted_on_a_failed_phase`, `tests/cli/test_pipeline.py::test_status_json_includes_duration_and_errors` |

### Testing Requirements

_Every FR above is pinned by a test that exists today; this section maps the
groups, and the table above carries the per-story evidence the guard checks._

| FR group | Pinned by |
| --- | --- |
| FR-001…FR-005 (command surface) | `tests/cli/test_pipeline.py::TestPipelineParser`, `tests/cli/test_pipeline_verb_log_level.py` |
| FR-006 (`--budget-cap` refusal) | `tests/cli/test_pipeline.py::TestPipelineBudgetCapIsRefused` |
| FR-007…FR-014 (phase graph) | `tests/pipeline/test_runner.py::TestRunFull`, `::TestRunResume`, `::TestIndividualPhases` |
| FR-015…FR-018 (artifact completion) | `tests/pipeline/test_runner_phase_artifacts.py` |
| FR-019 (collect tri-state) | `tests/pipeline/test_runner_collect_sources.py` |
| FR-020 (verify scope) | `tests/pipeline/test_runner_verify_scope.py` |
| FR-021 (failure reporting) | `tests/pipeline/test_runner_failure_reporting.py` |
| FR-022…FR-025 (dispatch bounds) | `tests/pipeline/test_runner_agent_timeout.py`, `tests/pipeline/test_runner_agent_dispatch.py` |
| FR-026 (atomic state) | `tests/pipeline/test_runner.py::TestAtomicWrite` |
| FR-027…FR-029 (status, exit codes) | `tests/pipeline/test_runner.py::TestStatus`, `tests/cli/test_pipeline.py::TestPipelineStatusCLI` |
| FR-030 (non-silent exit) | `tests/cli/test_nonsilent_exit_guard.py` |

---

## Known divergences

Found while writing this spec, from the code at 6935644. Each is recorded,
not fixed here.

- **D1 — Two systems both called "the pipeline."** The runner specified here
  and the multi-cycle orchestrator (`generate`/`cycle`) share a name, a
  `_pipeline/` directory and nothing else — different state files, different
  resume semantics, different budget story. Every document that says "the
  pipeline" without qualifying which is ambiguous.
- **D2 — `finish` and its own agent definition disagree.** The vault-facing
  shim template (`src/research_framework/agents/pipeline.md.j2`) tells the
  operator `finish` "skips research if queue already clear"; `run_finish`
  never runs research at all. The template is stale.
- **D3 — A missing `agent_call.py` reports success.** When the dispatcher
  script cannot be located in either the vault or the framework checkout, the
  dispatch returns exit 0 and the phase proceeds to its artifact check. The
  artifact check then fails, so the run does not report a false success — but
  the recorded reason is "no artifact", not "no dispatcher", which is a
  materially harder thing to diagnose.
- **D4 — The runner ignores the vault's `processors:` block.** `_drive_extract`
  and `_drive_verify` call their processors without the spec's processor
  overrides, so a vault's `research.spec.md` `processors:` configuration has
  no effect on any `pipeline`-verb run. The multi-cycle orchestrator does
  honour it. Nothing documents the asymmetry.
- **D5 — `pipeline-state.json` has a JSON Schema that nothing reads.**
  *Closed.* The schema was wired by #326 and moved to this spec's own
  `contracts/pipeline-state.schema.json` by #295 — 015g is archived, and the
  archive rule forbids a tracked file outside `specs/` opening anything
  inside it. `tests/contracts/test_json_schema_validation.py` validates both a
  blank state and one the real runner wrote.
- **D6 — There is no resume-time "already done" check.** Every verb
  re-invokes its drivers unconditionally; idempotency is delegated entirely
  to the RSS collector's dedupe and the extract processor's
  already-extracted skip. `resume` is a verb name for "the phases after the
  checkpoint", not a mechanism that inspects state to decide what is left.

## Assumptions

- The vault has been generated (`_pipeline/spec-parse.json` and the prompt
  templates exist). The runner does not bootstrap a vault; `generate` does.
- Exactly one run is active per vault at a time. Nothing locks the state file.
