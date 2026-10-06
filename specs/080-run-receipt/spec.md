# Feature Specification: The run receipt — `_pipeline/runs/<run_id>/`

**Status**: in-progress — every task (T001–T009) is implemented; the header
flips to `shipped(...)` when the PR merges. Closes **#221** (the receipt) and
**#224** (US4, the report's run context) together: #224 is sixty lines on top
of #221's plumbing and there is nothing to feed a report until the receipt
exists. Queued first in the v1.1.0 dependency order ("the weekly pipeline runs
unattended") — the receipt is what #247's fleet view and #249's unattended
mode read next.

**Spec**: `080-run-receipt` · **Extends**: `075-pipeline-runner` (the runner
whose record this is) · **Consumes**: `078-dispatch-surface` FR-015…FR-019
(the cost sidecar) · **Issue**: #221 (owner), #224 (US4) · **Absorbs**:
`078-dispatch-surface` T005 (decided here, FR-010) and `075-pipeline-runner`
T005 (satisfied by #326, recorded under § Absorbed tasks)

---

## Why this spec exists

On 2026-09-01 the weekly runner failed `verify` on seven of eight live vaults
and left, per vault, a seven-line `pipeline-state.json` with `errors: []`
and zero bytes on stderr (#211). The failure-reporting work that followed
(#318, #327, #305) fixed *what* the runner records: `errors[]` is populated,
the verify report is persisted, every agent dispatch tees its output to a
log, phase failures log at `ERROR`. What it did not fix is *where*. After a
run today an operator has to know that the rendered prompts are flat files
under `_pipeline/` (overwritten by the next run), that the agent logs are
`_pipeline/logs/<stage>-<timestamp>.log`, that the verify detail is
`_pipeline/logs/verify-<timestamp>.json`, that the export is under
`_pipeline/exports/`, and that the state file names some of these in its
per-phase `summary` — and that the next `full` discards the whole phase
history (`075` FR-013). No pipeline dispatch writes a cost sidecar at all
(`078` D6), so a weekly run over eight vaults has no framework-owned record
of what it spent. The spec-070 FR6 backstop can name `run-report.md` only for
`cycle` verbs, because the runner never writes one.

The cycle orchestrator has all of this — spec 028's sidecars, spec 048's
observability ladder, `_pipeline/run-report.md`. The weekly runner got none
of it. This spec gives the runner one directory per run that holds
everything an operator needs after an unattended night, and one file in it
that says what the run cost.

A reader with no code access must be able to build the receipt from this
document and know, for every artifact a run produces, exactly where it is.

## Scope

**In scope**: the per-run directory and its layout; the cost sidecar every
runner dispatch requests; the machine receipt (`run.json`) and its human
rendering (`run-report.md`); how `status` reads them; what the report
phase is told about the run (US4, #224); continuity across `full` →
`resume` → `finish`; retention.

**Out of scope, and load-bearing to say so**: budget *enforcement* on the
runner. This spec makes spend *recorded*; `075` FR-006's refusal of
`--budget-cap` stays exactly as it is until a follow-up wires a cap against
the record this spec creates (T009). The triage gate is `081-triage-gate`;
the report agent's *prose* is its own definition (`agents/report.md.j2`,
spec 040) — US4 fixes what the agent is fed, not what it writes. The
multi-cycle orchestrator (`generate`/`cycle`) already has its receipt
(`run_report.py`) and is untouched.

---

## User Scenarios & Testing

### User Story 1 — An unattended night leaves one directory to open (Priority: P1)

An operator whose scheduler ran eight vaults overnight wants to open one
place per vault and see what happened, without knowing the runner's
internals.

1. **Given** a vault, **When** `pipeline <vault> full` runs to its pause,
   **Then** `_pipeline/runs/<run_id>/` exists, where `<run_id>` is the
   `run_id` the state file records, and it holds `run.json`, `run-report.md`,
   `logs/`, `prompts/` and `agent-calls/`.
2. **Given** a completed or failed phase, **When** the operator opens that
   directory, **Then** the phase's rendered prompt, its merged agent output
   and its cost sidecar are each a file under it, named by stage.
3. **Given** a phase that failed, **When** its `ERROR` line is printed,
   **Then** the line names the run directory as well as the state file.
4. **Given** `pipeline <vault> status`, **When** it renders, **Then** it
   names the run directory and the receipt file.

### User Story 2 — Every dispatch leaves a cost sidecar (Priority: P1)

Nothing the runner dispatches may spend money without a record.

1. **Given** the `scout`, `research` or `report` phase dispatches an agent,
   **When** the dispatch completes, **Then** a sidecar exists at
   `agent-calls/<stage>.json` under the run directory, in the
   `078-dispatch-surface` FR-018 shape, with its cost provenance marked.
2. **Given** a dispatch that failed or timed out, **When** the phase closes,
   **Then** the sidecar still exists and carries `status: failed`.
3. **Given** a sidecar the runner cannot read after a dispatch, **When** the
   phase closes, **Then** the phase's recorded cost is `null` and a
   `WARNING` names the missing sidecar — never a silent `0`.
4. **Given** every phase has closed, **When** the receipt is written,
   **Then** it carries the run's total cost as the sum of every sidecar it
   could read, and says how many it could not.

### User Story 3 — A second run does not erase the first (Priority: P1)

1. **Given** a completed run, **When** `full` runs again, **Then** a new run
   directory is allocated and the previous one is byte-unchanged.
2. **Given** `full` has paused at triage, **When** `resume` and then
   `finish` run, **Then** both write into the run directory named by the
   state file's `run_id`, not a new one.
3. **Given** a state file written before this spec shipped (no run
   directory exists for its `run_id`), **When** `resume` or `finish` runs,
   **Then** the directory is created, the receipt records
   `reconstructed: true`, and no phase fails because of it.

### User Story 4 — The report describes the run that just happened (Priority: P2)

On 2026-09-01 one vault's weekly report claimed 45 notes added for a run
whose research phase created 0 (#224). The report agent was never told what
the run did; it reconstructed a narrative from git history.

1. **Given** `finish` reaches the report phase, **When** the report prompt
   is rendered, **Then** its run-context block carries, from the receipt:
   the `run_id`, each phase's status, the collect phase's unsupported
   sources, the scout queue size, the research phase's created/updated
   counts, the verify verdict with its content/tooling flag split and its
   most frequent flag families, and the run's total cost.
2. **Given** a research phase that created zero notes, **When** the report
   prompt is rendered, **Then** the context states that in so many words,
   so a report that claims additions contradicts the facts it was handed.
3. **Given** a verify phase that failed, **When** the report prompt is
   rendered, **Then** the context names the verify report file under the
   run directory rather than a file that does not exist.

### User Story 5 — `status` answers "what did it cost" (Priority: P2)

1. **Given** a run with sidecars, **When** `status` renders as text, **Then**
   each dispatching phase shows its cost and the run shows a total.
2. **Given** `status --json`, **When** it renders, **Then** the object
   carries `run_dir`, `receipt`, a per-phase `cost_usd` and a top-level
   `cost_total_usd`, each `null` where unknown.
3. **Given** no state file, **When** `status` runs, **Then** those keys are
   present and `null`, and the exit code is still 0 (`075` FR-028).

### Edge Cases

- Two `full` runs in the same minute → the second `run_id` MUST NOT collide
  with the first (see FR-002); a directory that already exists for a fresh
  `run_id` is a bug, not something to overwrite.
- The run directory is unwritable → the phase still runs and closes on its
  own artifact check; the receipt is skipped with a `WARNING`. The receipt
  is observational and never changes a phase's status or exit code.
- `--quiet` → suppresses narration only; the receipt, the sidecars and the
  logs are written regardless (`075` FR-003).
- A phase re-driven by hand (`pipeline <vault> scout` after `full`) writes
  into the current run's directory; its earlier log and sidecar for that
  stage get a numeric suffix rather than being overwritten, the same rule
  `078` FR-018 applies to sidecar collisions.

---

## Requirements

### Functional Requirements

**The run directory**

- **FR-001**: `full` MUST allocate `_pipeline/runs/<run_id>/` before its
  first phase runs, where `<run_id>` is the value written to
  `pipeline-state.json`. The directory MUST be derivable from the state file
  alone: `run_dir = <vault>/_pipeline/runs/<run_id>`. No new top-level key
  is added to the state file, whose schema (`pipeline-state.schema.json`,
  `additionalProperties: false`) stays at `framework_version: 1`.
- **FR-002**: `run_id` MUST be unique per vault. The current
  `YYYY-MM-DD-HHMM` form is kept for readability and MUST gain a suffix
  (`-2`, `-3`, …) when the directory already exists.
- **FR-003**: The directory MUST hold, and nothing outside it may be the
  canonical home of: `run.json` (FR-006), `run-report.md` (FR-008),
  `logs/<stage>.log` (the merged agent output `075` FR-024 tees),
  `prompts/<stage>.rendered.md` (the rendered prompt `075` § Prompt sources
  describes), `agent-calls/<stage>.json` (FR-010) and `verify-report.json`
  (the report `075` FR-020's phase persists). `_pipeline/exports/` stays
  where it is — the report agent owns that path — and the receipt records
  the export it found as `latest_export`.
- **FR-004**: `resume` and `finish` MUST write into the directory named by
  the state file's `run_id`. If it does not exist, they MUST create it,
  record `reconstructed: true` in the receipt, and proceed.
- **FR-005**: A re-driven stage within one run MUST NOT overwrite that
  stage's earlier log, prompt or sidecar; the later file takes a numeric
  suffix.

**The receipt**

- **FR-006**: `run.json` MUST be rewritten atomically every time a phase
  closes, and MUST be a pure function of the state file plus the sidecars
  and artifacts on disk — it adds derived facts (durations, costs, paths)
  and restates nothing the operator could not recompute. A test MUST assert
  the derivation is deterministic for a fixed input.
- **FR-007**: `run.json` MUST carry `schema_version` (`"1.0"`), `run_id`,
  `vault` (absolute path), `started_at`, `finished_at` (`null` while
  open), `framework_version` (the package version string, distinct from the
  state file's integer schema version), `reconstructed`, `verbs` (the
  verbs that wrote into this run, in order), `phases` (per phase: `status`,
  `started_at`, `finished_at`, `duration_s`, `cost_usd`, `cost_source`,
  `sidecar`, `log`, `prompt`, `errors`, `summary`), `artifacts`
  (`scout_report`, `research_report`, `verify_report`, `latest_export`,
  `context_tree`, each a path or `null`) and `cost` (`total_usd`,
  `sidecars_read`, `sidecars_missing`). Its JSON Schema MUST live at
  `tests/contracts/run-receipt-1.0.schema.json` and be wired to a test that
  validates a receipt the real runner wrote, the way #326 wired the state
  schema. Evolution of this envelope follows ADR-0013 (additive within a
  major, `schema_version` in the payload).
- **FR-008**: `run-report.md` MUST be a rendering of `run.json` for a human,
  written whenever `run.json` is, and MUST answer three questions in this
  order: which phase failed and why; how long each phase took; what the run
  cost, per phase and in total. It MUST name every artifact path it
  mentions absolutely.
- **FR-009**: A `FAILED` phase's `ERROR` line (`075` FR-021) MUST name the
  run directory in addition to the state file, and the spec-070 FR6 backstop
  hint MUST name `_pipeline/runs/<run_id>/run-report.md` as the record for
  `pipeline` verbs once this spec ships.

**Cost**

- **FR-010**: Every runner dispatch MUST pass
  `--cost-sidecar <run_dir>/agent-calls/<stage>.json` to the dispatcher.
  This decides `078-dispatch-surface` T005 in the affirmative. The sidecar's
  `cycle` field is `1` for every runner dispatch (the runner has no cycle;
  the dispatcher derives `cycle` from a `cycle-NNN` path segment and falls
  back to `1`); joinability to the run is by directory, see D2.
- **FR-011**: `--output-file` is NOT requested. The merged log already holds
  the agent's stdout (`075` FR-024), and `--output-file` is written only on
  exit 0 — it would be absent in exactly the runs an operator needs to read.
- **FR-012**: When the phase closes, the sidecar's `cost_usd` and
  `cost_source` MUST be copied into the phase summary. A sidecar that is
  missing or unparseable MUST yield `cost_usd: null` and a `WARNING` naming
  the expected path — `078` FR-015's rule that no zero is silent applies to
  the reader as much as the writer.
- **FR-013**: `run.json.cost.total_usd` MUST be the sum over readable
  sidecars, `sidecars_missing` MUST count the rest, and a total computed
  with any sidecar missing MUST be presented as a lower bound wherever it is
  rendered (`run-report.md`, `status`).
- **FR-014**: This spec MUST NOT enforce a budget. `075` FR-006 stays; T009
  records the decision on wiring a cap once the record exists.

**What the report is told (US4, #224)**

- **FR-015**: The report phase's run-context block (`075` § Prompt sources)
  MUST be rendered from `run.json`, not reconstructed from the flat
  artifact paths, and MUST carry: `run_id` and the run directory; each
  phase's status; the collect phase's unsupported-source names (`075`
  FR-019); the scout queue size; `notes_created` and `notes_updated`
  counts from the research phase; the verify verdict, its content/tooling
  flag counts (`079` FR-022a…c) and its three most frequent flag families;
  `cost.total_usd`.
- **FR-016**: When the research phase created zero notes, the context MUST
  state that explicitly, in a sentence, before any instruction to summarise
  additions. The report agent's prose remains its own — this is the
  enforcement boundary, and it is the same one `079` D4 records for the
  citation block.
- **FR-017**: The context MUST name the verify report under the run
  directory. The report agent definition's `reads:` entry
  `_pipeline/logs/verify-*.md` names a file the runner has never written
  (D3) and MUST be corrected to the receipt's `verify-report.json` in the
  same change.

**`status`**

- **FR-018**: `status` MUST add `run_dir`, `receipt`, per-phase `cost_usd`
  and `cost_total_usd` to the object it returns, `null` where unknown, and
  MUST render them in text form. These are additions to the `status`
  dictionary, not to the state file.
- **FR-019**: `status` MUST NOT fail when the run directory or `run.json`
  is absent; it reports what the state file alone supports.

**Retention**

- **FR-020**: Run directories MUST NOT be pruned automatically by this
  version of the spec. A `pipeline <vault> prune-runs` verb that keeps the
  newest N and anything younger than an age, with `--dry-run`, is T008 —
  the same cap-and-age shape #307 chose for research branches, so an
  operator learns one retention policy, not two.

### Key entities

| Entity | Where | Shape |
| --- | --- | --- |
| Run directory | `_pipeline/runs/<run_id>/` | one per `full`; `resume`/`finish` append |
| Receipt | `<run_dir>/run.json` | FR-007; schema `tests/contracts/run-receipt-1.0.schema.json` |
| Human receipt | `<run_dir>/run-report.md` | FR-008 |
| Phase log | `<run_dir>/logs/<stage>.log` (`<stage>-N.log` on re-drive) | merged stdout/stderr, was `_pipeline/logs/<stage>-<ts>.log` |
| Rendered prompt | `<run_dir>/prompts/<stage>.rendered.md` | was `_pipeline/<stage>-prompt.rendered.md` |
| Cost sidecar | `<run_dir>/agent-calls/<stage>.json` | `078` FR-018, schema 1.1, `cycle: 1` |
| Verify report | `<run_dir>/verify-report.json` | was `_pipeline/logs/verify-<ts>.json` |
| Run state | `_pipeline/pipeline-state.json` | unchanged (`075` § Key entities); `run_id` is the join key |
| Weekly export | `_pipeline/exports/*.md` | unchanged; newest recorded as `artifacts.latest_export` |

### Relationship to `075-pipeline-runner`

This spec supersedes the *locations* in three rows of `075` § Key entities
(Phase log, Rendered prompt, Verify report) and the path half of `075`
FR-024. It changes none of `075`'s behaviour: the same log is tee'd, the
same prompt is rendered, the same report is persisted — under the run
directory instead of scattered under `_pipeline/`. The tests that pin those
paths today (`tests/pipeline/test_runner_agent_timeout.py::test_the_run_leaves_a_per_phase_log`,
`tests/pipeline/test_runner_failure_reporting.py::test_a_verify_run_writes_its_report_under_pipeline_logs`,
`tests/pipeline/test_runner.py::test_run_scout_renders_and_passes_prompt_file`)
move with the files in the implementing PR; the behaviour they assert is
retained. Spec 015f's "`_pipeline/logs/verify-<date>`" path promise, which
`075` cited, is superseded for the runner by this spec.

## Success Criteria

- **SC-001**: After any run, one directory answers "what happened, how long
  did it take, what did it cost, what did the agents say" without the
  operator knowing a single runner-internal path.
- **SC-002**: No runner dispatch spends money without a sidecar, and no
  missing sidecar is ever read as a free call.
- **SC-003**: A second run cannot erase the record of a first.
- **SC-004**: The report prompt carries the run's own counts, so a report
  that claims notes the run did not create contradicts its own input.

---

## Acceptance coverage

| User story | Evidence |
| --- | --- |
| US1 — An unattended night leaves one directory to open | _(deferred to tasks.md T001, T003, T004)_ |
| US2 — Every dispatch leaves a cost sidecar | _(deferred to tasks.md T002)_ |
| US3 — A second run does not erase the first | _(deferred to tasks.md T003)_ |
| US4 — The report describes the run that just happened | _(deferred to tasks.md T006, T007)_ |
| US5 — `status` answers "what did it cost" | _(deferred to tasks.md T005)_ |

### Testing Requirements

Per-task blocks live in [`tasks.md`](tasks.md), authored before
implementation. The `075` behaviour this spec relocates rather than changes
is pinned today and MUST stay green through the move:

| Retained `075` behaviour | Pinned by |
| --- | --- |
| A dispatch is bounded and its output survives | `tests/pipeline/test_runner_agent_timeout.py::TestAHungAgentIsBounded`, `::TestTheAgentsOutputSurvives` |
| A phase is done only when its artifact exists | `tests/pipeline/test_runner_phase_artifacts.py` |
| A failed phase logs at ERROR and names its record | `tests/pipeline/test_runner_failure_reporting.py::TestPhaseFailuresAreLoggedAtError` |
| The state file validates against its schema | `tests/contracts/test_json_schema_validation.py::test_blank_pipeline_state_validates_against_schema`, `::test_real_saved_pipeline_state_file_validates_after_a_phase_transition` |

---

## Known divergences

Found while writing this spec, from the code at `b3e7217`. Recorded, not
fixed here.

- **D1 — `run_id` is minute-granular and unchecked.** `_make_run_id` returns
  `YYYY-MM-DD-HHMM`; two `full` runs inside one minute share it, and nothing
  today notices because the state file is simply overwritten. FR-002 is the
  fix; the receipt is what makes the collision visible.
- **D2 — The sidecar has no `run_id`.** `078` FR-018's sidecar carries a
  `cycle` number and no run identifier, so a runner sidecar is joinable to
  its run only by the directory it sits in. Adding `run_id` to the sidecar
  is an additive `1.2` change under ADR-0013's policy and belongs to `078`,
  not here.
- **D3 — The report agent reads a file nobody writes.** `agents/report.md.j2`
  declares `reads: _pipeline/logs/verify-*.md`; the runner writes
  `verify-<ts>.json` (and after this spec, `verify-report.json`). The agent
  has been told to read a Markdown summary that has never existed, which is
  one reason its "Vault health" section falls back to "Not available".
- **D4 — The FR6 hint is a static string.** `cli/__init__.py`'s
  `_SILENT_EXIT_HINT` names `pipeline-state.json` for `pipeline` verbs; it
  cannot name a run directory it does not know. FR-009 needs the hint to be
  told the receipt path, or to name the `runs/` directory generically.
- **D5 — Cost totals are lower bounds by construction.** The `claude`
  runtime reports real cost; the others estimate (`078` FR-015). A run
  total mixes provenances and this spec does not pretend otherwise: FR-013
  labels the number, `cost_source` per phase says where each part came
  from.

## Absorbed tasks

- **`078-dispatch-surface` T005** — "decide whether the weekly runner should
  request cost sidecars". Decided: yes (FR-010). `075` FR-006's refusal of
  `--budget-cap` stays until T009 wires a cap against the record.
- **`075-pipeline-runner` T005** — "wire `pipeline-state.schema.json` into
  a test or delete it". Satisfied by #326:
  `tests/contracts/test_json_schema_validation.py` validates both a blank
  state and one the real runner wrote after a phase transition. The
  schema's relocation out of `specs/_archive/` is #295's; this spec adds a
  second contract beside it (FR-007) and requires nothing of the first
  beyond staying wired.

## Open questions

- **Q1 — Retention numbers.** FR-020 defers pruning to T008 and proposes
  #307's shape (cap-N and age). The numbers (N, age) are the operator's
  call; the default proposed is N=5 and 90 days, matching D10 for
  branches.

## Assumptions

- The vault has been generated and its `scripts/agent_call.py` is the
  framework's or a faithful test double (`078` FR-026); a missing
  dispatcher is `075` D3 / T003, not this spec.
- One run active per vault at a time (`075` § Assumptions); this spec adds
  no locking.
- The consumer of `run.json` inside this repo is `status` today and #247's
  fleet view next; the schema is versioned from the first byte so that
  consumer can refuse a shape it does not know.
