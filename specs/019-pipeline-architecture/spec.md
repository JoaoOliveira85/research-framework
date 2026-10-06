# Feature Specification: Pipeline Architecture & Seam-Bug Elimination

**Feature Branch**: `019-pipeline-architecture`
**Created**: 2026-05-17
**Status**: **SHIPPED 0.2.31 (2026-05-18) — partial.** The two
silent-failure seam-bug fixes that motivated the spec landed in
0.2.31: verifier prompt inlines the JSON output contract +
`pipeline/verifier._extract_json_blob` parser (ADR-0004) and
`pipeline/wikilinks.auto_fix_moved_wikilinks` wired as cycle_runner
Step 3c (ADR-0005). The broader "architectural seam elimination"
work continued through specs 024 (testing infra v2) and 025
(simplify pass), both SHIPPED in 0.3.0/0.3.1. The smoke-gate
mandatory clause (ADR-0007) traces back to this spec. Anything
still labelled "pending" in this doc has either shipped under
024/025 or been queued under the correctness-sweep specs (026-034,
drafted 2026-05-22).
**Input**: User-driven feedback after five consecutive seam-bug releases
(0.2.21 → 0.2.27) on top of feature 017, plus architectural concerns about
code-bias, vault-shape strategy, GitHub PR underuse, and recurring quality
issues.

## Clarifications

### Session 2026-05-17

- Q: Which test files should the extended smoke gate enforce? → A: Union of `tests/scripts/test_*_contract.py`, `tests/scripts/test_validate_cycle_*.py`, `tests/pipeline/test_preconditions*.py`, `tests/pipeline/test_full_cycle_e2e.py`, `tests/pipeline/test_multi_cycle_e2e.py`. Plus all of `tests/_helpers/`.
- Q: Should H3's fix accept BOTH `next_action`+`termination_reason` AND `termination_condition`? → A: Validator accepts both; prompt is updated to emit only `termination_condition`; old aliases logged with `DeprecationWarning` for one minor version, removed in 0.3.0.
- Q: Vault Blueprint `intent_thread` shape? → A: `{name, summary, anchor_notes: [note_filename], contributing_dimensions: [dimension_name]}`. Anchor notes may be empty for a thread that's purely intent-derived (no code anchor yet).
- Q: H4 (`_resume` skipping Phase 3) — should the fix run Phase 3 on EVERY resume or only when the resume completes the final cycle? → A: Only when the resume completes the final cycle (or completes via condition A/B/C termination), to avoid duplicating the gate on every intermediate resume.
- Q: Should US3-US6 be in scope for 0.2.28 or deferred to a later release? → A: Deferred. 0.2.28 ships ONLY US1 (extended smoke gate) + US2 (four HIGH-severity seam fixes). US3-US6 require a daylight design pass with user input; this spec captures them but doesn't implement.

## Context

The user has reported, across the last 8 days of testing:

1. The vault is **too code-biased**. Their `reference-vault-v4` `flows/` folder is
   full of literal Kafka topics and REST endpoints because the scout-prompt's
   "Source-of-Truth Rule (CODE-FIRST)" instructs the agent to walk repos
   first and consult Confluence only "to answer 'why does this exist'" for
   topics code already surfaced. This contradicts the spec's `out_of_scope`
   rule excluding product-specific business rules — but the contradiction
   is enforced nowhere.
2. **No vault-shape strategy.** The pipeline jumps from cycle-0 setup
   straight to scout. There is no design phase that asks "what should the
   final vault look like?" so subsequent stages have no north-star to
   measure cycle output against. The agents default to conservative,
   low-yield decisions because they can't evaluate "does this topic
   advance the plan?".
3. **GitHub PRs are listed as `role: intent, priority: 2` in the spec**
   but the scout prompt uses them only in Step 2 ("Collect intent for
   each code topic") — i.e., as decoration for topics code already found,
   never as the driver. PRs never produce a topic on their own.
4. **Verifier is single-agent** and a vault with 56 `validate_vault.py`
   FAILs was allowed to ship because SG-004 maps those failures to WARN,
   not FAIL.
5. **Five seam bugs in eight days** (BatchResult serialization,
   TTY/line-buffering, budget field aliasing, resume preconditions,
   `source_file` URL ↔ `local_path` shape). Every one was a contract
   mismatch between two correct components that the existing test suite
   didn't exercise together. The 018 testing strategy was supposed to
   prevent this class, but its smoke gate only runs two e2e tests
   (`test_full_cycle_e2e.py` + `test_multi_cycle_e2e.py`) — none of the
   tier-2 contract test files in `tests/scripts/` ship-block.

Code review surfaced **four additional HIGH-severity seams** still latent
in 0.2.27, and confirmed every concern above is grounded in the code, not
a misunderstanding.

This spec captures the work to address those root causes.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Seam-bug shipping safety (Priority: P1)

A maintainer ships a fix and reasonably expects the build to catch
prompt↔validator contract drift, spec-shape variants, and resume-path
regressions before the wheel is built. Today the smoke gate runs ONLY
two cycle-level e2e files; tier-2 contract tests live outside the gate
and are easy to skip in CI. Five seam-bug shipments in eight days is the
evidence.

**Why this priority**: This is the highest-leverage change. It doesn't
remove a bug; it prevents the next family of bugs from shipping. Every
other concern in this spec touches large code; this one touches CI.

**Independent Test**: Add a deliberately broken contract test (e.g.
prompt example renames `budget_consumed_usd` to `spend_dollars`) and
verify `./build.sh` refuses to produce a tarball with an error that
identifies the specific tier-2 test that detected the drift.

**Acceptance Scenarios**:

1. **Given** a 0.2.25-style bug (prompt example diverges from validator
   field names), **When** `./build.sh` runs, **Then** the build aborts
   before producing a wheel, with a message naming the failing tier-2
   contract test.
2. **Given** a 0.2.26-style bug (resume precondition incorrectly blocks
   a vault), **When** `./build.sh` runs, **Then** the build aborts with
   a message naming the failing tier-2 resume test.
3. **Given** a 0.2.27-style bug (spec with `url` + `local_path` produces
   `source_file` validator can't match), **When** `./build.sh` runs,
   **Then** the build aborts with a message naming the failing
   parameterised contract test.
4. **Given** all four outstanding HIGH-severity seams from this spec's
   code-review section are unfixed, **When** `./build.sh` runs **Then**
   the build aborts with FOUR distinct test failures (one per seam).

---

### User Story 2 - Surgical fix of the four outstanding HIGH-severity seams (Priority: P1)

The code-review surfaced four latent seam bugs in 0.2.27 (in addition to
the five already fixed). Each is exactly the same shape as a previously
shipped bug. They should be fixed in the same release as US1's gate so
the gate has something to enforce.

**Why this priority**: These will become the SIXTH–NINTH consecutive
shipped seam bugs if they're not fixed before 0.2.28 ships. They are
small, well-understood, and the tests should be straightforward.

**Independent Test**: For each of the four seams, write a tier-2 contract
test that fails on the unpatched code and passes on the patched code.

**Acceptance Scenarios**:

1. **Given** a DFS research report with only `cumulative_cost_usd` set
   (no `budget_consumed_usd`), **When** `validate_cycle.py` evaluates
   termination Condition C, **Then** the budget cap check uses the
   `cumulative_cost_usd` value (not silently defaults to 0). [H1]
2. **Given** a v2 scout report with empty `sources_consulted` (or a
   wrong-shape `sources_consulted`), **When** `validate_cycle.py`
   validates the report, **Then** an ERROR is raised naming the missing
   or malformed required source. [H2]
3. **Given** a DFS report using the prompt's example field names
   (`next_action` + `termination_reason`) instead of `termination_condition`,
   **When** `validate_cycle.py` evaluates termination, **Then** the
   correct termination condition fires (A/B/C). [H3]
4. **Given** a vault completing its final cycle via `--resume`, **When**
   `run_cycles` returns, **Then** Phase 3 (coverage gate, code-first
   gate, reindex, generate-report) runs to completion — same as a fresh
   `generate` would. [H4]

---

### User Story 3 - Vault Blueprint stage + goal hierarchy (Priority: P2)

Before the first scout cycle, a one-shot "Blueprint" stage emits
`_pipeline/vault-blueprint.json` describing the target vault topology:
folder × dimension matrix, estimated note count per cell, intent threads
that tie notes together, and a completion target the orchestrator can
measure cycles against. Subsequent stages consume the blueprint as their
north-star input.

**User clarification (2026-05-18, post-0.2.28)** — the "intent thread"
the user keeps asking about is a **measured progress signal**, not just
a descriptive document. Specifically:

- Every level of the pipeline has an explicit, written-down goal:
  - **Vault goal** — the user's research outcome (from
    `research.spec.md`).
  - **Pipeline goal** — convergence on the vault goal within budget.
  - **Cycle goal** — measurable contribution this cycle is supposed to
    make toward the pipeline goal (e.g. "fill the missing 4 cells in
    the `services × kafka` matrix").
  - **Agent goal** — what each invoked agent is being asked to produce
    *this turn* (already implicit in the prompts; surface it
    explicitly).
- After each cycle, the orchestrator emits a measured delta against the
  blueprint: cells filled, intent threads completed, distance to
  done. This goes into the cycle report and is the input to the
  next cycle's prompt.
- The orchestrator gets an active auditor role: read the cycle delta,
  detect drift (e.g. "the scout has surfaced 0 new topics in the
  current focus dimension for two cycles"), and re-tune downstream
  prompts in-cycle. Today the orchestrator is a passive runner.
- A "pause-not-halt" escape hatch: when the orchestrator's audit
  detects severe drift (e.g. blueprint shows 80 % of work in a
  dimension we keep failing to source), the pipeline writes a
  structured question to `_pipeline/needs-user-input.json` and exits
  cleanly; user answers, `--resume` picks up. This is opt-in
  (`gates.pause_on_drift: true`) and the question always carries
  the orchestrator's recommended next step so the user can just
  approve.
- (Optional, lower priority) Per-stage / per-dimension **weights**
  the user can tune in `research.spec.md` so the scout prioritises
  the dimensions the user cares about more — feeds the blueprint's
  prioritised cell list.

**Why this priority**: This is the single largest architectural change
in this spec. It addresses the user's "no north star" concern directly
and unblocks the intent-first reordering in US4. It should ship behind
a feature flag so existing vaults aren't affected.

**Independent Test**: Generate a fresh vault with `--blueprint=enabled`;
verify `_pipeline/vault-blueprint.json` exists, conforms to its contract
schema, and is referenced by the scout prompt as the target topology.

**Acceptance Scenarios**:

1. **Given** a fresh `research.spec.md`, **When** `generate` runs with
   blueprint enabled, **Then** a `_pipeline/vault-blueprint.json` is
   produced BEFORE cycle 1's scout starts.
2. **Given** an existing vault without a blueprint (legacy), **When**
   `generate --resume` runs, **Then** the pipeline proceeds without a
   blueprint and prints a one-line breadcrumb encouraging the user to
   migrate.
3. **Given** a vault with a blueprint, **When** the scout prompt is
   rendered, **Then** the blueprint's intent threads + per-category
   targets appear as the "target topology" section the agent must use
   for prioritisation.

---

### User Story 4 - Per-vault code role (Priority: P2)

Flip the scout's source-priority — but make the flip *per-vault*, not
global. The scout's behaviour with respect to code depends on the role
the user assigns to code in `research.spec.md`.

**User clarification (2026-05-18, post-0.2.28)** — the original
"intent-first vs code-first" framing was wrong. Code's role is
*context-dependent*:

- **Reference vault** (what the user is currently running): code is a
  *guide*, not a source of truth. The agent should extract from code
  ONLY the language / framework / dependency / architecture /
  convention signals, then use those signals to drive online research
  about THOSE specific technologies. ("This repo uses Kafka, so go
  research Kafka topics — not RabbitMQ.")
- **Codebase vault**: code is the source of truth for what the
  business actually does (vs. the wiki, which often lags). The agent
  reads code for business logic and validates that logic against
  external sources (Confluence, PRs).
- **Discovery vault** (a vault about a public API or product): code
  is a *discovery signal* (enumerate what surfaces exist) and the
  online docs are the source of truth.

To express this, `research.spec.md` gets a new top-level field
`code_role` with values:

- `guide` — extract technology / architecture / convention signals
  only; treat code itself as non-authoritative. Reference vault default.
- `source_of_truth` — code is canonical; external sources validate
  / explain. Codebase vault default.
- `discovery_signal_only` — enumerate file / class / endpoint names
  to seed search; do not read code bodies. Public-API vault default.

The scout prompt branches on `code_role`. Today's hardwired "code is
primary, intent is secondary" becomes the `source_of_truth` path; the
new `guide` path emits topics from external sources first and uses
code only to filter ("don't propose Spring Boot topics — this vault
runs on Quarkus").

In addition, the agent should declare *which kinds of information*
it derived from code in the scout report (`code_extracts`: list of
`technology` | `architecture` | `business_logic` | `convention` |
`pr_discussion` | `none`). The validator checks that
`code_role: guide` reports include the right extract types and
don't smuggle business logic back in.

**Why this priority**: Addresses the user's #1 architectural complaint
(too code-biased, ignores PRs as intent). Bigger semantic change than
US3 but lower-risk to implement once US3 ships (blueprint can express
"this thread is intent-driven, that thread is code-driven").

**Independent Test**: Stage a spec where `intent` sources contain
references to a concept that NEVER appears in any enumerated repo. Run
one cycle. Verify the scout report includes that concept under
`topics_found.new` (current pipeline cannot do this — concept must
appear in code first).

**Acceptance Scenarios**:

1. **Given** a spec with `role: intent, priority: 1` PR source, **When**
   the scout prompt is rendered, **Then** Step 1 walks intent sources
   first and Step 2 anchors topics in code.
2. **Given** an intent source surfaces a concept absent from code,
   **When** the scout report is generated, **Then** that concept is in
   `topics_found.new` with an empty `source_code_topic_ids` and the
   validator does NOT reject the report for "intent without parent
   code topic".
3. **Given** an existing code-first spec (`role: behaviour, priority: 1`),
   **When** generate runs, **Then** the existing code-first flow is
   used unchanged (backwards compatibility — intent-first is opt-in).

---

### User Story 5 - Agent-owns-its-output correction (Priority: P2)

The 0.2.29 scout-validation correction loop is the canonical pattern.
US5 generalises it: whichever agent produced a quality-gate failure
gets handed the validator's named errors as a directive and is asked
to fix THE SPECIFIC FILES IT PRODUCED. The pipeline does not
forward-fix the agent's output; the orchestrator does not silently
absorb violations.

**User clarification (2026-05-18, post-0.2.28)** — concretely:

- SG-004 / `validate_vault.py` failures map to a per-note correction
  loop: for each note the validator rejects, send the note + the
  validator's named error back to the note-writer with the same
  directive shape the scout uses in 0.2.29. Cap at N retries per
  note (default 2; configurable).
- If after the retry cap the note still fails, the pipeline **deletes
  or quarantines** the note (moves it to `_pipeline/quarantine/<note>`
  with a `quarantine-reason.json` sibling) and surfaces it in the
  cycle report and the final run report so the user knows what was
  dropped. We do NOT keep broken files in the vault to "fix later" —
  that's what produced the user's "the cycle ran and the vault is
  broken" experience.
- Soft mode (current SG-004 = WARN) stays available behind a setting
  for users who want the pre-0.2.29 behaviour. Default flips to the
  new agent-owns-it loop with quarantine.

**Why this priority**: Direct quality-of-output concern. Without this,
the user's experience of "the pipeline ran for 5 cycles but the vault
is broken" recurs.

**Independent Test**: Run a cycle against a vault with seeded
frontmatter violations under each mode. Hard mode: cycle aborts at
SG-004. Soft mode: cycle proceeds with WARN (current behaviour).

**Acceptance Scenarios**:

1. **Given** `settings.yaml` sets `gates.sg004.mode: hard`, **When** a
   cycle's note-writer batch produces a note with a frontmatter
   violation, **Then** SG-004 FAILs the batch and the correction loop
   runs.
2. **Given** `settings.yaml` sets `gates.sg004.mode: soft` (default for
   backwards compat), **When** the same violation occurs, **Then**
   SG-004 emits WARN and the batch proceeds (current behaviour
   preserved).

---

### User Story 6 - End-of-pipeline qualitative consensus (Priority: P3)

**User clarification (2026-05-18, post-0.2.28)** — reframe from
per-stage consensus to a SINGLE end-of-pipeline qualitative gate:
after all cycles complete (and before the user sees the final report),
run N (default 5) agents in parallel with the same prompt: "Read the
final vault. Does this match the spec? List what's missing." Majority
vote decides whether to declare the pipeline done or schedule one more
cycle to fill the named gaps. This is cheaper than per-stage consensus
and addresses the user's actual concern ("am I really done?") without
N×ing the per-stage agent costs.

(The previous per-stage consensus framing is retained below as an
alternative implementation; both are options in the daylight design
pass.)

For two stages where divergence between agents matters most — Vault
Blueprint (US3) and Verifier — run N agents in parallel and require
consensus before accepting. Cheap stages (scout, DFS, note-writer)
remain single-agent.

**Why this priority**: The user named this directly. Lower priority
than US3-US5 because it's an *additional safeguard* on top of, not a
replacement for, the architectural fixes. Cost concern: every extra
agent invocation is real money.

**Independent Test**: Stage a synthetic verifier scenario where 1 of
3 verifiers wrongly accepts a malformed note. Consensus mode rejects;
single-agent mode (today) accepts.

**Acceptance Scenarios**:

1. **Given** Verifier consensus mode is enabled with N=3, **When** all
   3 verifiers agree on a note, **Then** the note is accepted/rejected
   accordingly.
2. **Given** Verifier consensus mode with N=3, **When** verifiers split
   2-1, **Then** the majority decision is recorded with the minority
   reasoning logged for audit.
3. **Given** Blueprint consensus mode with N=3, **When** topologies
   diverge, **Then** a tiebreaker agent merges the agreement set
   dimension-by-dimension and emits the merged blueprint.

---

### Edge Cases

- A vault with NO intent sources at all (pure code-driven research):
  intent-first scout must gracefully fall back to behaviour-first.
- A vault whose `local_path` repos don't exist on disk (e.g., a
  reviewer's machine): preflight already downgrades on resume; the
  Blueprint stage must not block here either.
- A spec that lists 0 priority-1 sources (no primary defined): today's
  validator rejects; with intent-first option, must accept any
  priority-1 source regardless of role.
- A resume run that catches the first-ever Blueprint stage failing
  mid-emit: blueprint should be atomically written or rolled back so a
  partial JSON doesn't poison subsequent cycles.
- A consensus stage where all N agents fail (cost overrun, timeout):
  graceful degradation to N-1 agents, then to single-agent, with a
  warning rather than an abort.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The build pipeline MUST refuse to produce a release tarball
  when any tier-2 contract test fails. (US1)
- **FR-002a (0.2.29)**: When `validate_cycle.py` exits 2 on a scout
  report due to recoverable structural errors (missing required source,
  off-repo source_file, missing summary field), the cycle runner MUST
  drive a correction loop: read the validator's sidecar errors, build
  a `build_directive` from them, re-render the scout prompt, re-run
  the scout, re-validate. Cap at `MAX_SCOUT_VALIDATION_RETRIES = 1`
  (configurable). Abort only after the cap is exhausted. (US2 H2-escalation /
  shipped 0.2.29)
- **FR-002b (0.2.29)**: `validate_cycle.py` MUST emit a
  `<report>.validation.json` sidecar on every exit code containing
  `status`, `reason`, `errors`, `warnings`, `metrics_delta`,
  `report_path`, `schema_version`. The sidecar is the contract the
  correction loop reads; stdout-scraping is forbidden. (US2 H2-escalation /
  shipped 0.2.29)
- **FR-002c (0.2.29 wizard)**: `install.sh` MUST consult
  `settings.yaml` for `default_executor.runtime` and skip the runtime
  prompt when it's declared and the binary is on PATH. Same for
  destination folder via `settings.output_dir` and the spec's
  `location` field. The wizard MUST print a one-line banner explaining
  the inferred value so the user knows their setting was honoured.
  (US-wizard / shipped 0.2.29)
- **FR-002**: Tier-2 contract tests MUST be parameterised over realistic
  spec shape variants (URL-only repos, URL+local_path repos, web-fetch
  access methods, intent-primary specs). (US1)
- **FR-003**: The DFS research-phase budget cap check MUST honor the
  same three field-name aliases (`budget_consumed_usd`,
  `cumulative_cost_usd`, `cost_estimate_usd`) that the structural
  validator already accepts. (US2 / H1)
- **FR-004**: The v2 cycle validator MUST validate `sources_consulted`
  for both scout and research reports (required sources must appear;
  missing sources rejected with named error). (US2 / H2)
- **FR-005**: The DFS validator MUST accept either the prompt's example
  field names (`next_action`, `termination_reason`) OR the canonical
  `termination_condition` and map them to the same termination logic.
  Prompt and validator MUST converge on one canonical name in 0.2.28+.
  (US2 / H3)
- **FR-006**: `cli._resume` MUST run Phase 3 (coverage gate, code-first
  gate, reindex, generate-report) on the final cycle, same as a fresh
  `generate` would. (US2 / H4)
- **FR-007**: When a Vault Blueprint is enabled, a one-shot Blueprint
  stage MUST run before the first cycle and emit
  `_pipeline/vault-blueprint.json` conforming to a documented schema.
  (US3)
- **FR-008**: When a Vault Blueprint exists, the scout-prompt MUST
  render the blueprint's intent threads and per-category targets as
  the "target topology" section. (US3)
- **FR-009**: Vaults without a Blueprint MUST continue to function with
  the existing code-first flow (backwards compatibility). (US3)
- **FR-010**: The scout prompt MUST support `role: intent, priority: 1`
  as a valid primary source, walked first in Step 1. (US4)
- **FR-011**: The spec validator MUST accept specs whose primary source
  has `role: intent` (current validator hard-fails on this). (US4)
- **FR-012**: Intent-only topics (no `source_code_topic_ids`) MUST be
  valid in the scout report when the spec is intent-first. (US4)
- **FR-013**: `settings.yaml` MUST expose `gates.sg004.mode`
  (`hard` | `soft`, default `soft` for backwards compat). (US5)
  — **still DEFERRED** at 2026-09-06 (US5 was never implemented).
- **FR-014**: In `hard` mode, SG-004 MUST FAIL the batch on
  `validate_vault.py` non-zero exit and trigger the correction loop.
  (US5) — **still DEFERRED**. A narrower slice shipped in
  `[Unreleased]` under issue #293: SG-004 FAILs on a `duplicate`
  violation unconditionally, because constitutional Principle VI is
  non-negotiable and cannot be behind a soft/hard setting. Every other
  finding still WARNs, so this spec's `soft` default — and the
  backwards-compat reason for it — is intact and FR-013/FR-014 remain
  open as written. See `specs/017-vault-quality-fix/spec.md`
  §9b's SG-004 amendment note.
- **FR-015**: `settings.yaml` MUST expose `consensus.stages` (list of
  stage names to run in consensus mode) and `consensus.n` (number of
  agents per consensus run, default 1). (US6)
- **FR-016**: Stages in consensus mode MUST gracefully degrade to N-1
  agents on individual agent failure rather than aborting the cycle.
  (US6)
- **FR-017**: Consensus decisions MUST be persisted to
  `_pipeline/consensus/<cycle>-<stage>-<id>.json` for audit. (US6)

### Key Entities

- **Vault Blueprint**: JSON document describing target vault topology.
  Fields: `target_folders` (list of {folder, dimension, target_count}),
  `intent_threads` (list of {name, summary, anchor_notes,
  contributing_dimensions}), `completion_target` (overall vault
  shape), `schema_version`. Lifecycle: written once before cycle 1;
  read by every subsequent stage; never mutated post-creation.
- **Consensus Record**: JSON document recording N agents' independent
  outputs for one consensus stage invocation. Fields: `stage`, `cycle`,
  `n`, `outputs[i]`, `decision`, `dissenting_outputs`. Lifecycle:
  written by the consensus dispatcher; read by audit tooling; never
  mutated.
- **Tier-2 Contract Test**: A pytest test in `tests/scripts/` or
  `tests/pipeline/` that exercises ONE producer-consumer contract
  (e.g., scout-prompt ↔ validate_cycle) with realistic, parameterised
  shape variants. Distinguishing trait: must be in the `build.sh`
  smoke-gate path.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Zero seam-bug shipments in the 30 days following 0.2.28
  ship. (Measure: count of "seam bug" CHANGELOG entries in the
  patch-version stream after 0.2.28.) (US1)
- **SC-002**: The four outstanding HIGH-severity seams from this spec's
  code review (H1–H4) are all closed in 0.2.28, with a regression test
  per seam in the smoke gate. (US2)
- **SC-003**: `./build.sh` smoke-gate test count grows from "2 e2e
  files" today to "all tier-1 and tier-2 contract tests" — measured
  as the union of `tests/scripts/`, `tests/_helpers/`, and
  `tests/pipeline/test_*_contract*.py` running before the wheel is
  packed. (US1)
- **SC-004**: A vault generated with Blueprint enabled has a non-empty
  `_pipeline/vault-blueprint.json` AND the cycle-001 scout prompt
  references at least one intent thread from the blueprint. (US3)
- **SC-005**: A spec whose primary source is `role: intent, priority: 1`
  passes `validate_spec.py --strict` and produces a scout that walks
  the intent source in Step 1. (US4)
- **SC-006**: With `gates.sg004.mode: hard`, a deliberately corrupted
  note frontmatter triggers an SG-004 FAIL and the correction loop
  produces a fixed note within 2 retries. (US5)
- **SC-007**: Consensus stage with N=3 verifiers on a synthetic 2-vs-1
  split produces a majority decision AND persists the dissenting
  output to `_pipeline/consensus/`. (US6)

## Assumptions

- The user's primary near-term need is "ship 0.2.28 with US1 + US2"
  (gate + four HIGH-severity fixes). US3-US6 are larger architectural
  work that benefits from a daylight design pass with user input.
- Backwards compatibility is a hard requirement: existing vaults
  (`0.2.16` ← `0.2.27`) must continue to function without changes.
  No flag-day migrations.
- Feature flags (settings.yaml keys) are the chosen mechanism for
  opt-in to new behaviour (Blueprint, intent-first, SG-004 hard,
  consensus). Default-off everywhere except the gate (US1) which
  always enforces.
- The 018 testing strategy's tier definitions are correct; only the
  smoke-gate scope was too narrow. This spec extends the gate, it
  doesn't replace the strategy.
- Cost ceiling: implementing US1+US2 in 0.2.28 should add ≤10% to the
  current full test sweep time (~5 min). US3+US5 add a one-time
  blueprint cost (~$0.50 per vault). US6 (consensus) can triple the
  cost of the consensus-enabled stages and so MUST be opt-in only.
- The existing `--blueprint=enabled`, `gates.sg004.mode`, and
  `consensus.*` settings.yaml keys do NOT exist yet; this spec
  introduces them.
- The four code-review-discovered HIGH-severity seams (H1–H4) are real
  bugs latent in shipped 0.2.27 code, not test-side false alarms.
  They must be fixed regardless of whether US3-US6 are pursued.
