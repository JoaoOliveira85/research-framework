# Feature Specification: The triage gate

**Status**: planned — queued third in the v1.1.0 dependency order, after
`080-run-receipt` and #224; precondition of #249 (unattended mode), whose
`--auto-approve top:N` is meaningless until an approval set exists.

**Spec**: `081-triage-gate` · **Extends**: `075-pipeline-runner` (FR-010,
FR-012, FR-014 — the `triage` phase and `resume`) and `077-cli-contract`
(the `pipeline` verb gains a subcommand) · **Issue**: #334 (deferred from
#240 by #305)

---

## Why this spec exists

The weekly runner has exactly one human checkpoint. `full` stops at
`triage`, prints the size of the queue, and tells the operator that
`resume` "researches every entry in that list, in one pass, with no further
prompt: there is no approve/defer gate yet (issue #240)". That sentence is
true, and it was written by #305 precisely because the previous one sent
operators to a Topic Radar the runner never writes. But a checkpoint an
operator cannot act on except by hand-editing a JSON file is a status flip
with a warning attached. `resume` marks `triage` done without reading any
approval (`075` FR-010, FR-014); on 2026-09-01 one vault's scout found 107
topics and the research phase was asked for all of them in a single pass.

#305 deferred the gate on purpose: a generated triage artifact, a new verb,
and a refusal in `resume` change the contract across three stages, which
CONTRIBUTING § 3 says wants a spec rather than a patch. This is that spec.
Its shape is the one four independent reviewers converged on in #240:
generate a triage artifact from the scout report, add
`pipeline triage --approve/--defer/--top N/--all`, carry deferred topics
into `research-backlog.md`, make `resume` refuse an empty approval set, and
let unattended mode opt in with `--auto-approve top:N`.

A reader with no code access must be able to build the gate from this
document, and an operator must be able to run a week without editing JSON.

## Scope

**In scope**: the triage artifact and its schema; the `pipeline <vault>
triage` subcommand and its selectors; what `resume` reads and refuses; the
research queue the research phase is handed; carry-over of deferred topics
into the backlog and back into the next run's triage; the counts `status`
reports; the unattended approval policy hook.

**Out of scope**: per-topic cost estimation (an "estimated cost" column
needs `080`'s sidecars and spec 033's estimator; the column is optional and
`null` until a follow-up fills it — T007); the unattended verb itself
(#249 composes this gate, it does not define it); the scout agent's
judgement of novelty (the artifact carries what the scout report says).

---

## User Scenarios & Testing

### User Story 1 — The operator sees the queue and decides (Priority: P1)

1. **Given** `full` has paused at triage, **When** the operator runs
   `pipeline <vault> triage` with no selector, **Then** every topic in
   `topics_found.new` is listed with a stable index, its name, its source,
   its novelty as the scout reported it, and its current decision
   (`pending`, `approved`, `deferred`, `carried_over`), and the exit code is
   0.
2. **Given** that list, **When** the operator runs
   `triage --approve 1,3,5 --defer 2`, **Then** `_pipeline/triage.json`
   records those decisions, every unmentioned topic stays `pending`, and
   the verb prints `N approved / M deferred / P pending`.
3. **Given** a queue of 107 topics, **When** the operator runs
   `triage --top 5`, **Then** the first five in scout order are approved and
   the remaining 102 are deferred — not left pending — so the decision is
   complete in one command.
4. **Given** `--all`, **When** it runs, **Then** every topic is approved and
   the artifact records that the operator chose so.
5. **Given** `--json`, **When** any of the above runs, **Then** the output is
   the artifact itself, never inferred from a TTY (`077` FR-019).

### User Story 2 — `resume` refuses to research what nobody approved (Priority: P1)

1. **Given** no `_pipeline/triage.json`, **When** `resume` runs, **Then** it
   exits 2 without dispatching, and the message names
   `pipeline <vault> triage` and `--all` as the one-command way through.
2. **Given** a triage artifact with zero approved topics and a non-empty
   queue, **When** `resume` runs, **Then** it exits 2 the same way.
3. **Given** the scout report changed after the decision was recorded (a
   re-run `scout`), **When** `resume` runs, **Then** it refuses with exit 2
   and says the queue no longer matches the decision.
4. **Given** an approved set, **When** `resume` runs, **Then** the research
   agent is handed only the approved topics, and `triage` is `done` with
   the counts in its summary.
5. **Given** the scout queue itself is empty, **When** `resume` runs, **Then**
   it proceeds and the research phase records `empty_queue_reason` as `075`
   FR-017 already requires — an honest nothing is not an unapproved
   something.

### User Story 3 — A deferred topic is carried, not lost (Priority: P2)

1. **Given** topics were deferred, **When** `resume` runs, **Then** each is
   appended to `_pipeline/research-backlog.md` with its provenance: the
   `run_id` that deferred it, the date, and its source.
2. **Given** a backlog with carried topics, **When** the next `full` pauses
   and the operator runs `triage`, **Then** those topics appear in the list
   marked `carried_over` with the run they came from, after the new scout
   topics, and count toward `K carried over`.
3. **Given** a carried topic is deferred again, **When** the backlog is
   written, **Then** it is not duplicated; its entry records both runs.

### User Story 4 — `status` shows the gate, not just a phase name (Priority: P2)

1. **Given** a decision was recorded, **When** `status` renders, **Then** the
   `triage` line reads `N approved / M deferred / K carried over`, in text
   and in `--json`.
2. **Given** `full` paused and no decision exists yet, **When** `status`
   renders, **Then** `triage` is `waiting` and the line says how many
   topics await a decision.

### User Story 5 — Unattended approval is explicit and bounded (Priority: P2)

1. **Given** `resume --auto-approve top:5`, **When** it runs with no prior
   decision, **Then** the first five topics are approved, the rest are
   deferred into the backlog, the artifact records `decided_by:
   "auto:top:5"`, and research proceeds.
2. **Given** `--auto-approve` with no bound (`all` or nothing), **When**
   `resume` runs, **Then** it exits 2: unattended approval of everything is
   the single-shot pass this spec exists to end.
3. **Given** a decision already recorded by an operator, **When**
   `resume --auto-approve top:5` runs, **Then** the operator's decision
   wins and the flag is reported as ignored.

### Edge Cases

- `--approve` or `--defer` naming an index outside the list → exit 2,
  nothing written.
- `--all` together with `--approve`, `--defer` or `--top` → exit 2 (one
  selector per invocation; `--approve` and `--defer` may combine).
- `--top 0` or a negative value → exit 2.
- `triage` before any `full` (no scout report) → exit 2 naming the missing
  `_pipeline/scout-report.json`.
- The scout report's `topics_found.new` carries entries that are strings
  rather than objects → they are listed by their text, with `source` and
  `novelty` shown as unknown; the gate does not refuse a queue it can read.
- The hand-edit protocol #305 documented (delete entries from
  `topics_found.new`) still changes the *queue*; it no longer constitutes
  approval. `resume` after a hand edit and no `triage` still refuses.

---

## Requirements

### Functional Requirements

**The artifact**

- **FR-001**: The triage artifact MUST be `_pipeline/triage.json`, written
  atomically, with `schema_version` (`"1.0"`), `run_id` (the state file's),
  `source` (the scout report path), `queue_digest` (a digest of
  `topics_found.new` as read), `decided_at`, `decided_by` (`"operator"` or
  `"auto:top:N"`), `counts` (`approved`, `deferred`, `pending`,
  `carried_over`) and `topics[]`, each `{index, topic, source, novelty,
  decision, carried_from}` where `decision` is one of `pending`,
  `approved`, `deferred` and `carried_from` is a `run_id` or `null`.
- **FR-002**: `index` MUST be stable for the life of the artifact: 1-based,
  scout order first, carried-over topics after, and never renumbered by a
  later `triage` invocation on the same queue.
- **FR-003**: `queue_digest` MUST be recomputed from the scout report on
  every read; a mismatch MUST invalidate the decision (US2.3).
- **FR-004**: Its JSON Schema MUST live at
  `tests/contracts/triage-1.0.schema.json` and be validated against an
  artifact the real verb wrote. Evolution follows ADR-0013.

**The verb**

- **FR-005**: `pipeline <vault> triage` MUST be a `pipeline` subcommand
  (`077` FR-004's list and the `--help` golden change visibly, as `077`
  SC-003 intends), accepting `--approve <indices>`, `--defer <indices>`,
  `--top N`, `--all`, `--json`. With no selector it lists and writes
  nothing.
- **FR-006**: `--approve`/`--defer` take comma-separated 1-based indices
  and MAY be combined; `--top N` approves the first N and defers the rest;
  `--all` approves everything. Any other combination is a usage error,
  exit 2, nothing written.
- **FR-007**: Decisions MUST be idempotent and cumulative on an unchanged
  queue: a second `--approve 4` adds to the set; a topic MAY move between
  `approved` and `deferred` by naming it again.
- **FR-008**: Exit codes follow `077` FR-012: 0 when a decision was listed or
  recorded; 2 for a missing scout report, an index out of range, a bad
  selector combination or a bad vault. There is no exit-1 outcome — an
  empty queue lists as empty and exits 0.
- **FR-009**: `--json` MUST print the artifact (or, with no selector, what
  the artifact would be) and MUST NOT be inferred from TTY-ness.

**`resume` and the research queue**

- **FR-010**: `resume` MUST refuse with exit 2 when no triage artifact
  exists, when its `queue_digest` does not match the scout report, or when
  `counts.approved` is 0 against a non-empty queue. The refusal MUST name
  `pipeline <vault> triage` and `--all`, and MUST be written to stderr
  (`077` FR-017).
- **FR-011**: When the scout queue itself is empty, `resume` MUST proceed;
  `075` FR-017's `empty_queue_reason` covers the result.
- **FR-012**: `resume` MUST write `_pipeline/research-queue.json` holding
  only the approved topics, in the same `{topics_found: {new: [...]}}`
  shape as the scout report, and the rendered research prompt MUST name
  that file as the queue. The prompt template's contract does not change;
  the file it is pointed at does.
- **FR-013**: `resume` MUST mark `triage` `done` with the four counts in
  its summary and MUST NOT proceed from `pending` without a decision — this
  supersedes `075` FR-014's "proceed anyway" for the no-decision case only;
  an unexpected *status* still proceeds with a warning.

**Carry-over**

- **FR-014**: Every deferred topic MUST be appended to
  `_pipeline/research-backlog.md` under a heading naming the `run_id`,
  with its source and the date, in a form the next run's triage can parse
  back (one topic per line, provenance in a trailing parenthetical).
- **FR-015**: The next `triage` MUST list carried topics after the new
  scout topics, marked `carried_over` with `carried_from`, and MUST count
  them in `counts.carried_over`.
- **FR-016**: A topic deferred twice MUST have one backlog entry naming
  both runs, not two entries.

**`status`**

- **FR-017**: `status` MUST render the `triage` phase as `N approved / M
  deferred / K carried over` once a decision exists, and as `waiting (T
  topics await a decision)` before one does, in text and `--json`.

**Unattended approval**

- **FR-018**: `resume --auto-approve top:N` MUST, when no decision exists,
  approve the first N topics in artifact order, defer the rest into the
  backlog, and record `decided_by: "auto:top:N"`. `N` MUST be a positive
  integer; `all` and a bare flag MUST be refused with exit 2.
- **FR-019**: An operator's recorded decision MUST take precedence over
  `--auto-approve`; the flag is then reported as ignored at `WARNING`.

**The pause**

- **FR-020**: `full`'s pause message (`075` US1.3, #305) MUST name
  `pipeline <vault> triage` as the next step and MUST stop saying there is
  no gate. The generated `/pipeline` agent definition MUST say the same
  (the #240 test that pins the two surfaces together extends to this).

### Key entities

| Entity | Where | Shape |
| --- | --- | --- |
| Triage artifact | `_pipeline/triage.json` | FR-001; schema `tests/contracts/triage-1.0.schema.json` |
| Research queue | `_pipeline/research-queue.json` | `{topics_found: {new: [approved…]}}` — the scout report's shape, approved subset |
| Backlog | `_pipeline/research-backlog.md` | `## Deferred by run <run_id> (<date>)` then `- <topic> (source: …; runs: …)` |
| Scout report | `_pipeline/scout-report.json` | unchanged (`075` § Key entities); read-only for this spec |
| Decision counts | `pipeline-state.json` → `phases.triage.summary` | `{approved, deferred, pending, carried_over}` |

### Exit codes (this spec's additions to `077`)

| Verb | 0 | 2 |
| --- | --- | --- |
| `pipeline triage` | listed, or decision recorded | no scout report; index out of range; bad selector combination; bad vault |
| `pipeline resume` | (unchanged) | no decision; stale decision; empty approval set against a non-empty queue; unbounded `--auto-approve` |

## Success Criteria

- **SC-001**: An operator can approve, defer or cap a queue with one
  command and never edit a JSON file.
- **SC-002**: The research phase cannot be handed a topic nobody approved,
  and a decision cannot silently outlive the queue it was made on.
- **SC-003**: A deferred topic is found again next week, with the run that
  deferred it.
- **SC-004**: Unattended runs research a bounded, recorded set, or nothing.

---

## Acceptance coverage

| User story | Evidence |
| --- | --- |
| US1 — The operator sees the queue and decides | _(deferred to tasks.md T001)_ |
| US2 — `resume` refuses to research what nobody approved | _(deferred to tasks.md T002)_ |
| US3 — A deferred topic is carried, not lost | _(deferred to tasks.md T003)_ |
| US4 — `status` shows the gate, not just a phase name | _(deferred to tasks.md T004)_ |
| US5 — Unattended approval is explicit and bounded | _(deferred to tasks.md T005)_ |

### Testing Requirements

Per-task blocks live in [`tasks.md`](tasks.md), authored before
implementation. Behaviour this spec changes on purpose, and the tests that
pin the old behaviour today — each is rewritten, not deleted, in the
implementing PR:

| Today | Pinned by | After this spec |
| --- | --- | --- |
| `resume` proceeds from any triage status | `tests/pipeline/test_runner.py::test_resume_transitions_triage_to_done` | proceeds only with a decision (FR-010, FR-013) |
| The research prompt names `scout-report.json` as the queue | `tests/pipeline/test_runner.py::test_research_prompt_names_the_queue_artifact_the_pipeline_writes`, `tests/pipeline/test_runner_agent_dispatch.py::test_the_rendered_research_prompt_points_at_the_queue_artifact` | names `research-queue.json` (FR-012) |
| The pause says there is no gate | `tests/pipeline/test_runner_triage_prompt.py::test_pause_names_the_real_triage_artifact` | names the `triage` verb (FR-020) |
| The `pipeline` subcommand list and `--help` golden | `tests/cli/test_pipeline.py::TestPipelineParser::test_all_subcommands_accepted`, `tests/cli/test_build_parser_stable.py::test_help_byte_identical` | gain `triage` (FR-005) |

---

## Known divergences

- **D1 — `resume` is the only verb that changes a phase it did not run.**
  It flips `triage` to `done` (`075` FR-010) because `triage` has no
  driver (`075` FR-012). This spec keeps that shape — the decision is the
  driver's work, `resume` records its outcome — rather than making
  `triage` a phase with an agent.
- **D2 — Novelty is whatever the scout said.** The scout report's entries
  are not schema-checked beyond `topics_found.new` being a list (`075`
  FR-016); a `novelty` field may be absent. The artifact shows unknown
  rather than inventing a value.
- **D3 — The backlog is Markdown for a human and parsed by a machine.**
  Principle VIII's stub-as-fuel rule already treats a non-empty
  `research-backlog.md` as a continuation trigger on the cycle side; this
  spec writes a line shape it can read back. A JSON sidecar beside it
  would be more honest and is left to the implementation to propose if the
  line grammar proves brittle.
- **D4 — Cost per topic is not here.** #240's fourth reviewer asked for
  "est. cost" per topic. It needs `080`'s sidecars for a baseline and the
  spec-033 estimator for a projection; the column is optional in the
  artifact and T007 fills it.

## Assumptions

- The vault was generated by this framework and `full` has run at least
  once; the gate has nothing to gate before scout has written a queue.
- One operator per vault per week; the artifact carries no locking and no
  multi-user attribution beyond `decided_by`.
- The research agent honours the queue file it is pointed at, as it does
  today for `scout-report.json` (`075` § Prompt sources).
