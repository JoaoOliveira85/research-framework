# Feature Specification: Testing Infrastructure v2 — Phase 2 + Discipline Layer

**Feature Branch**: `024-testing-infrastructure-v2`
**Created**: 2026-05-21
**Status**: shipped(2026-05-21, version 0.3.0) — **SHIPPED 0.3.0** (coordinated 022+024 release, 2026-05-21). All 7 user stories merged via parallel-agent execution per the architect's phased-serial plan. Wave 0 landed US1 (LLM dispatch guard + allowlist); Wave 2 Sub-A shipped US2 (fake_agent verifier/narrator/probe handlers); Wave 2 Sub-B shipped US3 (smoke meta-tests restored to `build.sh`); Wave 2 Sub-C ran 3 parallel agents shipping US4 (spec acceptance-coverage lint + FR-013 backfill on 015a/017/018), US5 (CHANGELOG regression-link lint + FR-014 backfill across 15 released `### Fixed` blocks), and US6+US7 together (tier-5 cycle e2e + delete legacy synthetic-vault test). `/speckit.clarify` interactive session 2026-05-21 locked decisions on lint-guard discipline + FR-013/014 backfill scope; `/speckit.plan` produced contract files + research.md + data-model.md + quickstart.md; `/speckit.tasks` produced 67 tasks across 10 phases; `/speckit.analyze` surfaced 2 critical + 5 should-fix findings, all resolved in commit `0a8f88d`. See Clarifications block below for the locked decisions.
**Input**: Phase 1 of the testing-strategy refresh shipped on
`docs/testing-strategy-phase1-closeout` (2026-05-21, commits `c94b9e9`
and `d1f8764`). Phase 1 delivered ADR-0008 (pyramid restructure +
marker rename + regression discipline + acceptance coverage convention)
and the active reference doc (`docs/testing-strategy.md`). This spec
owns the **forward work** Phase 1 left for "Phase 2" — the lint
guards, fake-agent stage extensions, smoke meta-test restoration,
and acceptance-coverage adoption. Spec 018 covered the original
testing strategy (now partially superseded by ADR-0008); this spec
is the implementation contract for Phase 2 + the two new
discipline lint guards ADR-0008 introduced.

## Clarifications

### Session 2026-05-21 (interactive `/speckit.clarify`)

The agent drafted seven `[PROPOSED]` starting positions during
`/speckit.specify`. The user ratified six of them in an interactive
clarify pass (the seventh — branch name `024-testing-infrastructure-v2`
— was already locked in by the existing branch at clarify time and
is therefore not re-asked). Three of the six ratifications **diverge
from the proposal** (Q4, Q5, Q6); the divergences expand scope on Q4
and Q5 (full backfill, no allowlist) and contract scope on Q6 (delete
outright instead of rewrite-first). The decisions in this session
supersede the `[PROPOSED]` framing in commit `1b34c2b`.

- **Q1 (accepted): one spec or split?** → **One spec.** All three
  workstreams (lint guards, fake-agent stage extensions, smoke
  meta-tests) share the same exit criterion (full sweep green +
  smoke green + LLM-dispatch allowlist in its intended state) and
  ship in ~3–4 sessions. Splitting would multiply doc-discipline
  overhead.
- **Q2 (moot — already locked in):** branch is
  `024-testing-infrastructure-v2`. `docs/testing-strategy.md` line
  38's stale `refactor/testing-strategy-phase2` reference is
  corrected as part of this spec (FR-011).
- **Q3 (accepted): LLM dispatch guard allowlist size at ship?** →
  **Two-entry allowlist** matching the two known production
  bypasses: `pipeline/plan_narrator.py` and `pipeline/cycle_runner.py`'s
  probe-cache retrieval. Spec 025 Tier A shrinks the allowlist to
  zero. Allowlist entries MUST be explicit + commented so spec 025
  can delete each row with no ambiguity.
- **Q4 (diverges — strict at launch w/ full backfill):** spec
  acceptance coverage guard ships **fully strict at launch**, with
  no allowlist. The three existing specs that declare G/W/T
  acceptance scenarios but lack a `## Acceptance coverage` section
  (015a-corpus-folder-name, 017-vault-quality-fix,
  018-testing-strategy) MUST be backfilled inside this spec's
  scope. Specs without G/W/T scenarios are unaffected by the
  guard.
- **Q5 (diverges — strict at launch w/ full backfill):** CHANGELOG
  regression-link guard ships **fully strict at launch**, with no
  allowlist. Every `### Fixed` bullet under every released version
  block in `CHANGELOG.md` (15 such sections at clarify time) MUST
  be backfilled with `(test: …)`, `(regression test: …)`, or
  `(no test: …)`. `[Unreleased]` is still skipped (annotation
  required only by release time).
- **Q6 (diverges — delete outright):** `tests/pipeline/test_e2e_synthetic_vault.py`
  is **deleted outright** in this spec. The historical coverage
  the file provided is absorbed by US6's tier-5 cycle e2e
  scenarios (`oos_topic`, `partial_yield`, `verifier_reject`),
  which use the new fake-agent stages from US2. No rewrite,
  no `@pytest.mark.regression` markers needed (the e2e scenarios
  carry the regression discipline directly).
- **Q7 (accepted): dogfood?** → **Yes** — this spec's own
  `## Acceptance coverage` section is filled in now (with
  `_(deferred to tasks.md)_` placeholders for each user story
  until `/speckit.tasks` lands). When the lint guard from FR-006
  runs against this very spec, it passes without an allowlist
  entry.

### Background — what Phase 1 already shipped

Commits `c94b9e9` and `d1f8764` on `docs/testing-strategy-phase1-closeout`:

- **ADR-0008**: pyramid restructure (6→7 tiers, `Seam`→`Integration`,
  old tier 4 split into Component-integration + Cycle-e2e). Marker
  rename: `@pytest.mark.integration` → `@pytest.mark.live_llm`.
  Two new markers: `@pytest.mark.regression`, `@pytest.mark.acceptance`.
  Regression discipline (CHANGELOG → test linkage). Spec
  acceptance coverage convention.
- **`docs/testing-strategy.md`**: ~620 lines — the active reference
  doc. Defines tiers, markers, conventions, decision tree, costs.
- **`tests/README.md`**, **`CLAUDE.md`**, **`tests/processors/test_extract.py`**:
  vocabulary + marker updates wired through.
- **`pyproject.toml`**: marker registration updates.
- **Conventions defined but unenforced**: spec acceptance coverage
  (`## Acceptance coverage` section convention) and CHANGELOG
  regression discipline (`(test: ...)` annotation convention) — both
  documented but no lint guards yet. **That's what 024 ships.**

### Relationship to other specs

- **Spec 018** (Testing Strategy, SHIPPED 0.2.23 + partially
  superseded by ADR-0008): provides the *historical* pyramid + the
  original LLM dispatch guard work. 024 builds on 018's foundation.
- **Spec 022** (E2E Quality Harness, DRAFT 2026-05-21): builds on
  the seven-tier pyramid + acceptance-coverage convention. 022's
  spec.md depends on 024's acceptance-coverage lint guard to enforce
  its own `## Acceptance coverage` section.
- **Spec 025** (Code Simplification Pass, DRAFT 2026-05-21): the
  LLM dispatch guard's allowlist is shrunk to zero by 025's Tier A.
  024's guard catches 025-era violations as the refactor proceeds.

### What this spec is NOT

- It is **NOT** the pyramid restructure or the marker rename —
  that's already shipped via ADR-0008.
- It is **NOT** the `docs/testing-strategy.md` doc — that's the
  living reference and not a deliverable of this spec. 024 may
  *update* the doc (tick off Phase 2 checklist boxes) but does
  not re-derive the conventions.
- It is **NOT** the LLM dispatch consolidation (routing
  `plan_narrator` and probe-retrieval through `agent_call.py`).
  That's spec 025 Tier A. 024 makes the *guard* enforce the
  contract; 025 makes the *production code* honour it.
- It is **NOT** the quality-regression harness (spec 022). 024
  ships *correctness* regression discipline (the CHANGELOG
  guard); 022 ships *quality* regression discipline (the
  baseline-diff harness).
- It is **NOT** a quality-metric or fixture-vault layer. Those
  belong to spec 022.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — LLM dispatch guard catches subprocess bypasses (Priority: P1)

A new contributor adds a feature that wants to call `claude` directly
via `subprocess.run([...])` from `pipeline/some_new_module.py`. They
push to a feature branch. The LLM dispatch guard (tier-2 test under
`tests/_helpers/test_llm_dispatch_guard.py`) runs in the fast local
loop and fails with: "Detected direct `claude` invocation in
`pipeline/some_new_module.py:42`; route through
`scripts/agent_call.py` instead. See Constitution Principle IV
(Agent-Script Separation of Concerns)."

**Why this priority**: Without this guard, the project re-accumulates
LLM-bypass technical debt every release. This is the foundational
guard for spec 025 (which clears the *current* debt); without it,
the cleared debt comes back.

**Independent Test**: Add a deliberate `subprocess.run(["claude", ...])`
to a non-allowlisted module on a throwaway branch. Run `pytest
tests/_helpers/test_llm_dispatch_guard.py`. Confirm it fails with the
file + line + remediation message. Remove the deliberate violation,
rerun, confirm it passes.

**Acceptance Scenarios**:

1. **Given** a codebase with **no** direct `claude` or `codex`
   subprocess calls (other than the two production bypasses),
   **When** the guard runs, **Then** it passes.
2. **Given** the two known production bypasses
   (`pipeline/plan_narrator.py`, `pipeline/cycle_runner.py` probe
   retrieval), **When** the guard runs, **Then** it passes because
   both entries are in the allowlist with explicit comments
   pointing at spec 025 Tier A.
3. **Given** a deliberate subprocess violation in a non-allowlisted
   module, **When** the guard runs, **Then** it fails with the file,
   line, command, and remediation message.
4. **Given** the allowlist comment for a row, **When** spec 025 Tier
   A removes that row's production code, **Then** the row in the
   allowlist must also be removed in the same commit (enforced by
   the contract test in `specs/018-testing-strategy/contracts/llm-dispatch-guard.contract.md`).

---

### User Story 2 — fake_agent covers verifier, narrator, probe stages (Priority: P1)

A test author writes a tier-5 cycle e2e exercising the verifier
reject path. They invoke `fake_agent.scenario("verifier", "reject")`
and get a deterministic verifier response that mimics the production
schema (`{verdict: "reject", reasons: [...], severity: "high"}`).
The cycle runner accepts the response and routes the note correctly.

**Why this priority**: Three production stages (verifier, narrator,
probe_retrieval) are *not* currently stubbed in `fake_agent.py`,
which means e2e tests that touch those paths either skip silently
or fall through to live LLM calls. Adding the stubs unlocks
fixture-vault testing for spec 022.

**Independent Test**: Run `pytest tests/_helpers/test_fake_agent_contract.py`
after the stage extensions land and confirm all three new stages
have at least one `happy` scenario, and verifier additionally has
`reject` and `malformed_json` scenarios. Run a tier-5 e2e test that
exercises verifier reject and confirm it passes deterministically.

**Acceptance Scenarios**:

1. **Given** `fake_agent.py` v2, **When** `fake_agent.scenario("verifier",
   "accept")` is called, **Then** it returns a deterministic accept
   response matching the production schema.
2. **Given** `fake_agent.scenario("verifier", "reject")`, **When**
   called, **Then** it returns a deterministic reject response with
   reasons.
3. **Given** `fake_agent.scenario("verifier", "malformed_json")`,
   **When** called, **Then** it returns a deliberately non-JSON
   response (to exercise the parse-tolerance code in
   `pipeline/verifier.py` per ADR-0004).
4. **Given** `fake_agent.scenario("narrator", "happy")`, **When**
   called, **Then** it returns a deterministic short narrative.
5. **Given** `fake_agent.scenario("probe_retrieval", "happy")`,
   **When** called, **Then** it returns deterministic probe results.
6. **Given** the contract test in
   `tests/_helpers/test_fake_agent_contract.py`, **When** it runs,
   **Then** every stage marked "Phase 2 target" in the stage matrix
   has at least one passing scenario.

---

### User Story 3 — Smoke meta-tests restored (Priority: P1)

A release author runs `./build.sh`. The smoke gate now includes the
two previously-commented-out meta-tests that verify the smoke
gate itself is wired correctly:
`tests/build/test_install_wizard_skip_redundant_questions.py` and
`tests/build/test_smoke_gate_enforces_contract_tier.py`. Both were
ROADMAP QW-2 and are now uncommented + passing.

**Why this priority**: A smoke gate that doesn't test itself is one
silent regression away from being broken. The two meta-tests already
exist on disk; this is just removing the comment skips.

**Independent Test**: Run `./build.sh` and grep stdout for both test
names appearing in the pytest output. Verify both pass. Revert the
uncomment and confirm both are skipped.

**Acceptance Scenarios**:

1. **Given** `build.sh` with QW-2 applied, **When** `./build.sh`
   runs, **Then** both meta-tests appear in the pytest output and
   pass.
2. **Given** an intentionally broken smoke gate (e.g. delete a
   `SMOKE_TESTS` manifest entry), **When** `./build.sh` runs,
   **Then** `test_smoke_gate_enforces_contract_tier.py` fails with
   a clear message.
3. **Given** an intentionally broken install wizard,
   **When** `./build.sh` runs, **Then**
   `test_install_wizard_skip_redundant_questions.py` fails with
   a clear message.

---

### User Story 4 — Spec acceptance coverage lint guard + backfill (Priority: P2)

A spec author drafts a new `specs/NNN-name/spec.md` with Given/When/Then
acceptance scenarios but forgets to add the `## Acceptance coverage`
section. The Phase 2 lint guard runs in the fast local loop and
fails with: "Spec `specs/NNN-name/spec.md` declares acceptance
scenarios but has no `## Acceptance coverage` section. See
ADR-0008 § Spec acceptance coverage convention."

The guard ships **fully strict** with no allowlist. Per the clarify
session's Q4 ratification, the three existing specs that declare
G/W/T scenarios but lack a `## Acceptance coverage` section — namely
`015a-corpus-folder-name`, `017-vault-quality-fix`, and
`018-testing-strategy` — are backfilled inside this spec's scope
before the guard goes live. Specs without G/W/T scenarios are
unaffected by the guard.

**Why this priority**: P2 because the convention is *documented* in
ADR-0008 + `docs/testing-strategy.md`; the guard enforces it. A
spec without acceptance coverage isn't catastrophic, just sloppy.
But sloppy compounds — by spec 030 we'd have 8 specs without
coverage. The strict-at-launch posture (Q4 divergence) means we pay
the backfill cost once, now, instead of carrying an allowlist
forever.

**Independent Test**: On a throwaway branch, draft a `specs/999-test/spec.md`
with at least one `**Given** ... **When** ... **Then** ...` scenario
but no `## Acceptance coverage` section. Run `pytest
tests/spec/test_acceptance_coverage_guard.py`. Confirm it fails with
the file path. Add the section and confirm it passes. Then on the
024 ship branch, run the same guard against every existing spec and
confirm zero failures (no allowlist needed).

**Acceptance Scenarios**:

1. **Given** a spec with acceptance scenarios and a complete
   `## Acceptance coverage` table, **When** the guard runs, **Then**
   it passes.
2. **Given** a spec with acceptance scenarios but no
   `## Acceptance coverage` section, **When** the guard runs, **Then**
   it fails with the spec path and a remediation pointer to ADR-0008.
3. **Given** the three backfilled specs (`015a`, `017`, `018`) at
   ship of 024, **When** the guard runs, **Then** all three pass
   without exception.
4. **Given** every other existing spec (those without G/W/T
   scenarios), **When** the guard runs, **Then** it skips them
   silently (no false positives).
5. **Given** spec 022 (drafted same day as 024), **When** the guard
   runs against it, **Then** it passes (proving the convention is
   usable from day one).
6. **Given** any future spec (post-024-ship), **When** the guard
   runs, **Then** there is no allowlist escape hatch — the spec
   author MUST fill in `## Acceptance coverage` to make the guard
   pass.

---

### User Story 5 — CHANGELOG regression-link lint guard + backfill (Priority: P2)

A contributor fixes a bug and adds a `### Fixed` entry to
`CHANGELOG.md`. They forget the `(test: ...)` annotation. The Phase
2 lint guard runs in the fast local loop and fails with: "CHANGELOG
entry for version 0.2.34 § Fixed line 12: `Fixed crash on empty
vault.` — missing `(test: ...)`, `(regression test: ...)`, or
`(no test: ...)` annotation. See ADR-0008 § Regression discipline."

The guard ships **fully strict** with no allowlist. Per the clarify
session's Q5 ratification, every `### Fixed` bullet under every
released version block in `CHANGELOG.md` (15 such sections at
clarify time, ~30–50 individual bullets) MUST be backfilled with
one of the three valid annotations inside this spec's scope before
the guard goes live. `[Unreleased]` is still skipped (annotation
required only by release time).

**Why this priority**: P2 alongside acceptance coverage. Same
discipline pattern as US4 — convention documented in ADR-0008;
guard enforces. The strict-at-launch posture (Q5 divergence) means
we pay the backfill cost once, now, instead of carrying an allowlist
forever. Where a historical bullet truly never had a test (and
never will retroactively get one), the `(no test: …)` annotation
with a one-line rationale is the explicit escape hatch — it's
honest about the coverage gap without hiding it behind an opaque
allowlist row.

**Independent Test**: Add a `### Fixed` line to CHANGELOG under
a future version block without an annotation. Run `pytest
tests/spec/test_changelog_regression_links.py`. Confirm it fails.
Add `(test: path/to/test.py::test_name)`. Confirm it passes. Then
on the 024 ship branch, run the guard against the full CHANGELOG
and confirm zero failures (no allowlist needed).

**Acceptance Scenarios**:

1. **Given** a CHANGELOG entry under a released version block with a
   `(test: ...)` annotation pointing at an existing test, **When**
   the guard runs, **Then** it passes.
2. **Given** a CHANGELOG entry under a released version block with
   `(regression test: ...)` or `(no test: ...)`, **When** the guard
   runs, **Then** it passes.
3. **Given** every `### Fixed` bullet across all released version
   blocks at 024 ship time (post-backfill), **When** the guard runs,
   **Then** it reports zero violations (no allowlist needed).
4. **Given** a CHANGELOG entry under a released version block with
   no annotation, **When** the guard runs, **Then** it fails with
   the version, line number, and offending text.
5. **Given** a CHANGELOG entry under `[Unreleased]`, **When** the
   guard runs, **Then** it skips (Unreleased is in-flight; annotation
   required only by release time).
6. **Given** an entry with `(test: tests/path/missing.py::test_x)`
   pointing at a non-existent test, **When** the guard runs,
   **Then** it fails with "test reference does not exist".
7. **Given** any future released-version `### Fixed` bullet
   (post-024-ship), **When** the guard runs, **Then** there is no
   allowlist escape hatch — the contributor MUST add one of the
   three annotations to make the guard pass.

---

### User Story 6 — Tier-5 cycle e2e wires existing scout scenarios (Priority: P2)

A test author runs `pytest -m e2e tests/integration/test_cycle_e2e.py`.
The tier-5 e2e now covers three scout scenarios that previously had
no integration test:

- `oos_topic` (out-of-scope topic — verifier should reject)
- `partial_yield` (scout yields fewer topics than requested)
- `verifier_reject` (a previously-valid note is later rejected by
  verifier in a re-verification pass)

Each scenario uses the new fake-agent stages from User Story 2.

**Why this priority**: These three failure modes have driven seam
bugs historically but had only unit-level coverage. Cycle-level
coverage prevents the seam-bug class from re-emerging.

**Independent Test**: For each scenario, snapshot the cycle output
and assert the expected `_pipeline/cycle-NNN-research.json` shape.
For `oos_topic`, assert the verifier rejection appears in
`cycle-NNN-quality-report.json`. For `partial_yield`, assert the
SG-002 gate triggers. For `verifier_reject`, assert the note is
moved to `_pipeline/rejected/`.

**Acceptance Scenarios**:

1. **Given** the `oos_topic` scenario, **When** the cycle runs,
   **Then** verifier rejects the note and the rejection is recorded.
2. **Given** the `partial_yield` scenario, **When** the cycle runs,
   **Then** SG-002 fires a diversity-gate warning and the metric is
   recorded.
3. **Given** the `verifier_reject` scenario, **When** the cycle
   runs, **Then** the previously-accepted note is moved to
   `_pipeline/rejected/<note-name>.md`.
4. **Given** the fast local loop (`pytest -m "not e2e"`), **When** it
   runs, **Then** none of the three e2e scenarios are collected.

---

### User Story 7 — Delete `test_e2e_synthetic_vault.py` outright (Priority: P3)

A new contributor opens `tests/pipeline/test_e2e_synthetic_vault.py` looking
for an e2e example. Today they find a bespoke `unittest.mock`-heavy
pattern that predates `fake_agent.py`. Post-024, the file is gone
entirely. The historical coverage it provided — scout/research/note
happy-path plus the smoke-bug regression bed — is absorbed by US6's
tier-5 cycle e2e scenarios (`oos_topic`, `partial_yield`,
`verifier_reject`), which use the new fake-agent stages from US2 and
the `vault_factory.build_minimal_vault` helper.

Per the clarify session's Q6 ratification, **no rewrite is
attempted**. The "delete-as-fallback" option from the original
`[PROPOSED]` answer becomes the primary path — the tier-5 e2e
scenarios in US6 are the canonical replacement, and they carry the
regression discipline directly (no `@pytest.mark.regression`
markers needed because the e2e scenarios themselves ARE the
regression coverage).

**Why this priority**: P3 because the test passes today; this is
debt cleanup. But leaving it in place tempts copy-paste of the
bespoke mock pattern. Deleting outright (rather than rewriting)
saves session time and avoids ending up with two tests covering the
same paths via different shapes.

**Independent Test**: After cleanup, `ls tests/pipeline/test_e2e_synthetic_vault.py`
returns no such file. Confirm the historical coverage is preserved
in `tests/integration/test_cycle_e2e.py` (US6) by inspecting the
three new scenario IDs and tracing each back to the smoke-bug
CHANGELOG entries the deleted file originally covered.

**Acceptance Scenarios**:

1. **Given** the 024 ship commit, **When** `ls tests/pipeline/test_e2e_synthetic_vault.py`
   runs, **Then** the file does not exist.
2. **Given** the deletion, **When** `pytest -m "not e2e"` runs,
   **Then** no test collection errors reference the deleted module
   (no orphan imports, no fixture dependencies).
3. **Given** the US6 tier-5 e2e scenarios at ship, **When** they
   run, **Then** they cover the same scout/research/note happy-path
   plus the smoke-bug regression bed that the deleted file
   originally covered.
4. **Given** the CHANGELOG entries that the deleted file's tests
   originally backed, **When** the US5 guard runs against those
   entries (post-Q5 backfill), **Then** the annotations point at
   the new US6 tier-5 scenarios (the historical chain remains
   traceable).

### Edge Cases

- LLM dispatch guard false positives on non-LLM `subprocess.run(["claude"])`
  (e.g. a shell utility happens to be named `claude`) → guard's
  allowlist supports both file-level and `(file, line)` granularity.
- A spec's `## Acceptance coverage` section exists but all entries
  say `(deferred to tasks.md)` → guard treats as a warning, not a
  failure; gets stricter at `/speckit.plan` complete.
- A CHANGELOG `### Fixed` entry spans multiple lines (e.g. with a
  nested bullet) → guard parses the leading line only; the rest
  is treated as detail.
- `[Unreleased]` block is empty → guard skips silently (no entries
  to annotate).
- `fake_agent` scenario file is added but its schema doesn't match
  the production schema → fake-agent contract test catches it.
- `test_e2e_synthetic_vault.py` rewrite breaks an unrelated test
  due to fixture-namespace collision → run full sweep before
  shipping; expand fixture namespace if needed.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: LLM dispatch guard MUST live at
  `tests/_helpers/test_llm_dispatch_guard.py`, run in the fast
  local loop (`pytest -m "not e2e"`), and ship with a two-entry
  allowlist matching the two production bypasses.
- **FR-002**: LLM dispatch guard allowlist MUST be human-readable
  with comments naming the offending file + line + remediation
  pointer (spec 025 Tier A entry).
- **FR-003**: `fake_agent.py` MUST add scenarios for `verifier`
  (accept, reject, malformed_json), `narrator` (happy), and
  `probe_retrieval` (happy).
- **FR-004**: `tests/_helpers/test_fake_agent_contract.py` MUST be
  extended to assert all three new stages are covered.
- **FR-005**: `build.sh` MUST uncomment the two QW-2 meta-tests
  (`tests/build/test_install_wizard_skip_redundant_questions.py`
  and `tests/build/test_smoke_gate_enforces_contract_tier.py`).
  Both MUST pass.
- **FR-006**: Spec acceptance coverage lint guard MUST live at
  `tests/spec/test_acceptance_coverage_guard.py`, run in the fast
  local loop, and fail on any spec.md with Given/When/Then
  scenarios but no `## Acceptance coverage` section. **No
  allowlist** — strict at launch per Q4.
- **FR-007**: CHANGELOG regression-link lint guard MUST live at
  `tests/spec/test_changelog_regression_links.py`, run in the fast
  local loop, and fail on any released-version `### Fixed` entry
  without `(test: ...)`, `(regression test: ...)`, or `(no test: ...)`
  annotation. **No allowlist** — strict at launch per Q5.
  `[Unreleased]` block is still skipped.
- **FR-008**: Tier-5 cycle e2e MUST cover the `oos_topic`,
  `partial_yield`, and `verifier_reject` scenarios using the new
  fake-agent stages.
- **FR-009**: `tests/pipeline/test_e2e_synthetic_vault.py` MUST be **deleted
  outright** per Q6. No rewrite, no regression-marker stand-in —
  the replacement coverage lives in FR-008's tier-5 e2e
  scenarios.
- **FR-010**: This spec's own `## Acceptance coverage` section MUST
  pass the lint guard from FR-006 once that guard ships (dogfood
  per Q7).
- **FR-011**: Branch name MUST be `024-testing-infrastructure-v2`
  (not `refactor/testing-strategy-phase2`); `docs/testing-strategy.md`
  line 38 MUST be updated accordingly.
- **FR-012**: All Phase 2 checklist boxes in `docs/testing-strategy.md`
  § Phase 2 implementation checklist MUST be ticked off in the same
  commit/PR that lands the corresponding code change.
- **FR-013** *(scope-add from Q4)*: The three existing specs that
  declare G/W/T acceptance scenarios but lack a `## Acceptance
  coverage` section MUST be backfilled inside this spec's scope:
  `specs/_archive/015a-corpus-folder-name/spec.md`,
  `specs/017-vault-quality-fix/spec.md`,
  `specs/018-testing-strategy/spec.md`. Each backfilled section
  MUST follow the same one-row-per-user-story shape as 022, 024,
  and 025; rows MAY use `_(historical — see <link to shipped
  CHANGELOG entry or test path>)_` where the coverage is already
  shipped and traceable.
- **FR-014** *(scope-add from Q5)*: Every `### Fixed` bullet under
  every released version block in `CHANGELOG.md` (15 sections at
  clarify time, see Assumptions for the line-number snapshot) MUST
  be backfilled with one of `(test: …)`, `(regression test: …)`,
  or `(no test: …)`. Where a bullet truly never had a test (and
  retroactively writing one is not feasible), `(no test: …)` MUST
  carry a one-line rationale. `[Unreleased]` is exempt.
- **FR-015** *(scope-clarification from Q6)*: The historical
  coverage that `tests/pipeline/test_e2e_synthetic_vault.py` provided MUST
  be traceable from the relevant CHANGELOG `(test: …)` annotations
  (added by FR-014) to the new US6 tier-5 e2e scenarios (FR-008).
  Any CHANGELOG entry whose `(test: …)` pointer used to reference
  `tests/pipeline/test_e2e_synthetic_vault.py::...` MUST be rewritten to
  point at the equivalent `tests/integration/test_cycle_e2e.py`
  scenario.

### Key Entities

- **LLM dispatch guard allowlist** — a structured file (YAML or
  Python list-of-dicts) at `tests/_helpers/llm_dispatch_allowlist.yaml`
  with entries `{file: ..., line_range: [start, end], reason: ...,
  spec_pointer: ...}`. Ships with two entries (Q3); spec 025 Tier A
  shrinks to zero.
- **fake_agent scenario file** — a JSON file at
  `tests/_helpers/fake_agent_scenarios/<stage>/<scenario>.json`
  with a deterministic response payload matching the production schema.

> **Removed at clarify (Q4 + Q5):** the "acceptance coverage
> allowlist" and "CHANGELOG regression-link allowlist" entities
> proposed in the original draft are intentionally NOT created.
> Both guards ship strict at launch with no allowlist; the full
> backfill (FR-013 + FR-014) eliminates the need for either file.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Full sweep (`pytest`) green at ship.
- **SC-002**: Fast local loop (`pytest -m "not e2e"`) runtime
  delta from 024 ship-day is < 30 seconds vs the pre-024 baseline
  (the new lint guards must be cheap).
- **SC-003**: `./build.sh` smoke green at ship, including the two
  QW-2 meta-tests now uncommented.
- **SC-004**: LLM dispatch guard allowlist contains exactly two
  entries at ship (matching the two known production bypasses).
- **SC-005**: Spec acceptance coverage guard passes against **every
  existing spec** at 024 ship time without an allowlist (Q4 strict
  posture). This includes the three backfilled specs (015a, 017,
  018) and the three sibling drafts (022, 024, 025).
- **SC-006**: CHANGELOG regression-link guard passes against
  **every released version block** at 024 ship time without an
  allowlist (Q5 strict posture). `[Unreleased]` is skipped, as
  designed.
- **SC-007**: `tests/pipeline/test_e2e_synthetic_vault.py` no longer exists
  in the tree at 024 ship time (Q6 delete-outright), and the
  replacement coverage is in place via FR-008's tier-5 e2e
  scenarios.
- **SC-008**: All Phase 2 checklist boxes in
  `docs/testing-strategy.md` are ticked off in the same PR.
- **SC-009**: This spec's `## Acceptance coverage` section passes
  the lint guard from FR-006 against itself (dogfood per Q7).
- **SC-010**: After FR-013 backfill, `015a-corpus-folder-name`,
  `017-vault-quality-fix`, and `018-testing-strategy` each
  contain a populated `## Acceptance coverage` section that maps
  every G/W/T scenario to either a shipped test file path or an
  explicit `_(historical — see …)_` placeholder.
- **SC-011**: After FR-014 backfill, every `### Fixed` bullet under
  every released version block in `CHANGELOG.md` carries one of the
  three valid annotations. Where `(no test: …)` is used, it
  includes a one-line rationale.
- **SC-012**: After FR-015 cross-check, no `(test: …)` annotation
  in `CHANGELOG.md` points at the deleted
  `tests/pipeline/test_e2e_synthetic_vault.py` — all such references are
  rewritten to point at the equivalent
  `tests/integration/test_cycle_e2e.py` scenario.

## Assumptions

- Phase 1 ADR-0008 work has already shipped (commits `c94b9e9`,
  `d1f8764` on `docs/testing-strategy-phase1-closeout` branch).
- `tests/_helpers/fake_agent.py` v2 contract from
  `specs/018-testing-strategy/contracts/fake-agent.contract.md` is
  the authoritative target shape.
- LLM dispatch guard contract from
  `specs/018-testing-strategy/contracts/llm-dispatch-guard.contract.md`
  is the authoritative shape (already updated 2026-05-21 to cite
  Principle IV not Principle V).
- The acceptance-coverage and CHANGELOG-regression conventions in
  `docs/testing-strategy.md` are final (ADR-0008 locked them).
- No new runtime dependencies (Principle V).
- Lint guard runtime budgets are well under 5 seconds each (cheap
  parsing of `spec.md` and `CHANGELOG.md` files; AST scan for LLM
  dispatch).
- **Backfill scope snapshot at clarify (2026-05-21):**
  - FR-013 (acceptance-coverage backfill): 3 specs identified by
    ripgrep search for `**Given** … **When** … **Then** …`
    scenarios without a sibling `## Acceptance coverage` section:
    `015a-corpus-folder-name`, `017-vault-quality-fix`,
    `018-testing-strategy`. All other specs either lack G/W/T
    scenarios (most older specs use freeform acceptance prose) or
    already have an `## Acceptance coverage` section (022, 024,
    025).
  - FR-014 (CHANGELOG annotation backfill): 15 `### Fixed`
    sections at clarify time, at line numbers (relative to commit
    `1b34c2b`): 191, 212, 599, 752, 871, 890, 960, 1069, 1107,
    1194, 1237, 1361, 1414, 1462, 1543. Total bullet count is
    estimated at 30–50 individual lines; `/speckit.plan` should
    confirm by `rg '^- ' CHANGELOG.md` scoped to each section.
  - If new `### Fixed` entries land between clarify and ship, they
    enter at the strict gate from day one (no grandfathering).
  - If new G/W/T-bearing specs land between clarify and ship,
    they too enter at the strict gate (the convention is "all
    new specs comply"; the backfill clears the existing deficit).

## Acceptance coverage

Demonstrates the ADR-0008 spec acceptance coverage convention. This
spec ships the guard that enforces this section; the section is
fully filled by `/speckit.tasks` time.

| User Story | Evidence |
|------------|----------|
| US1 — LLM dispatch guard catches subprocess bypasses | _(deferred to tasks.md; test will be `tests/_helpers/test_llm_dispatch_guard.py`; allowlist at `tests/_helpers/llm_dispatch_allowlist.yaml`)_ |
| US2 — fake_agent covers verifier, narrator, probe stages | _(deferred to tasks.md; contract test in `tests/_helpers/test_fake_agent_contract.py`; scenario files under `tests/_helpers/fake_agent_scenarios/`)_ |
| US3 — Smoke meta-tests restored | _(deferred to tasks.md; verified by `./build.sh` running both restored tests `tests/build/test_install_wizard_skip_redundant_questions.py` and `tests/build/test_smoke_gate_enforces_contract_tier.py`)_ |
| US4 — Spec acceptance coverage lint guard + backfill | _(deferred to tasks.md; guard at `tests/spec/test_acceptance_coverage_guard.py`; FR-013 backfill on `015a`/`017`/`018`; self-referentially proves itself — this very section passes the guard without an allowlist)_ |
| US5 — CHANGELOG regression-link lint guard + backfill | _(deferred to tasks.md; guard at `tests/spec/test_changelog_regression_links.py`; FR-014 backfill on all 15 released-version `### Fixed` sections in `CHANGELOG.md`)_ |
| US6 — Tier-5 cycle e2e wires `oos_topic` / `partial_yield` / `verifier_reject` | _(deferred to tasks.md; tests in `tests/integration/test_cycle_e2e.py`; depends on US2 fake-agent stages)_ |
| US7 — Delete `tests/pipeline/test_e2e_synthetic_vault.py` outright | _(deferred to tasks.md; replacement coverage is the US6 tier-5 e2e scenarios; FR-015 ensures CHANGELOG `(test: …)` annotations get rewritten to point at the US6 scenarios)_ |

## Out of scope (covered by other specs)

- LLM dispatch consolidation (routing the two known bypasses
  through `agent_call.py`) — **spec 025 Tier A (A1, A2)**.
- Auto-detect resume cycle — **spec 025 A4** (was QW-3).
- Constitution + build.sh doc sync — **spec 025 A5**.
- Quality-report context-manager guard — **spec 025 A6**.
- Quality regression baseline harness — **spec 022**.
- Fixture vaults — **spec 022**.
- Cost-as-quality-metric — deferred to v3 (Horizon 3).
