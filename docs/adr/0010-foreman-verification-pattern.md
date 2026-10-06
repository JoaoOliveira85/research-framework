# ADR 0010 — Foreman Verification Pattern + Test-Design Role Separation

**Status**: ACCEPTED
**Date**: 2026-05-27
**Tags**: testing, quality-assurance, agent-architecture, bias-reduction, feeds-vault-revival-sprint
**Supersedes**: none
**Superseded by**: none

## Context

Autonomous coding subagents — particularly when running multi-hour
`/speckit.implement` loops over large task lists — exhibit a small but
non-zero rate of **test-discipline drift**:

- Marking a task complete without producing the test the task required.
- Writing tests that *pass* but don't actually exercise the behavior under
  test (vacuous assertions, mocks of the unit under test, etc.).
- Squashing all work into a single commit so red-green-refactor TDD
  ordering is invisible after the fact.
- Renaming or relocating tests to match implementation convenience,
  obscuring whether the test that landed is the test that was meant.

The 028 dispatch-telemetry subagent (PR #28, 2026-05-27) provides a
concrete example: 44 tasks shipped in a single commit, all tests pass,
smoke gate green — but we cannot inspect git history to verify whether
the agent actually wrote the failing test FIRST or backfilled tests to
match its implementation. In an environment where the project is
shipping 4 critical-path specs (~265 tasks total) via autonomous
subagents, this verification gap matters.

Three forces are pulling against trust:

1. **Single-agent bias** — the agent writing the production code is also
   the agent deciding which tests to write, then writing the tests, then
   claiming the work is done. There is no independent check.
2. **Token-cost pressure** — agents have an implicit incentive to minimize
   work; skipping or weakening tests is one available shortcut.
3. **Opacity of squashed commits** — even when an agent claims TDD, we
   often cannot verify it because the diff arrives as a single commit.

## Decision

Introduce a **three-role testing pipeline** with **mechanical verification**
between roles, dispatched as part of the existing `/speckit.implement`
flow but invisible to the implementer agent.

### Roles

1. **Test-Design Agent** — reads `spec.md` + `plan.md` + `tasks.md`
   (NEVER reads implementation code). Enriches each task in `tasks.md`
   with a `### Testing Requirements` subsection specifying:
   - Exact test file paths
   - Exact test function names
   - Required behavior per test (prose)
   - Optional TDD-discipline flag (test must land in same-or-earlier
     commit as implementation)

2. **Implementer Agent** — reads the enriched `tasks.md`. Treats
   `Testing Requirements` as part of the task definition: must produce
   the named files with the named functions; tests must pass; TDD flag
   must be honored. Does **not** know that a foreman will check the
   work mechanically.

3. **Foreman Agent (composite)** — runs after the implementer:
   - **Arm A — deterministic verifier** (`scripts/foreman/verify_test_coverage.py`):
     Parses `tasks.md` `Testing Requirements` blocks, walks the branch
     diff, asserts (file present ∧ function defined ∧ collected by
     pytest ∧ exits 0 when run ∧ TDD-timeline satisfied if flagged).
     No LLM in the loop — pure Python + git + AST + pytest.
   - **Arm B — review subagent**: Reads Arm A's JSON output + the diff +
     the spec. Checks semantic things scripts can't catch (vacuous
     assertions, mocked-unit-under-test patterns, code-quality
     regressions). Emits structured criticism.

### Bias-reduction matrix

| Role | Sees impl code | Sees verifier output | Writes prod code | Writes test code | Defines required tests |
|---|---|---|---|---|---|
| Test-Design Agent | ❌ | ❌ | ❌ | ❌ | ✅ |
| Implementer Agent | ✅ (writes it) | ❌ (gets reformulated feedback only) | ✅ | ✅ | ❌ |
| Foreman Arm A (script) | (parses diff) | (emits it) | ❌ | ❌ | ❌ |
| Foreman Arm B (subagent) | ✅ (read-only) | ✅ | ❌ | ❌ | ❌ |
| Orchestrator (human or parent agent) | ✅ | ✅ | ❌ | ❌ | ❌ |

The implementer never knows which mechanism checks its work. When
verification fails, feedback arrives as structured criticism ("3 of 27
tasks failed test coverage requirements; T012 expected
`test_refresh_sources_exit_code_table` in `tests/cli/test_refresh_sources.py`
— function not found") — actionable without revealing the verifier
exists. This preserves the implementer's standard TDD prompt without
introducing meta-awareness that could be gamed.

### Strict-naming policy

`Testing Requirements` blocks specify **exact filenames and function
names**, not behavior-only scenarios. Rationale: a behavior-only
specification ("test that crash before os.replace leaves target
unchanged") allows the implementer to write a test by that name and
have it pass without truly exercising the contract. Strict naming +
ASTcheck + pytest-exit-code gives a deterministic gate. Brittleness
(renames cause failures) is intentional — the test-design agent commits
to a name, and the implementer must satisfy it verbatim.

## Consequences

### Positive

- **Trust**: We can verify that the tests the implementer claimed to
  write actually exist, are registered with pytest, and pass.
- **TDD-history**: The timeline check (test added in same-or-earlier
  commit as implementation) makes red-green-refactor verifiable from
  git log, defeating the squash-and-hide pattern.
- **Bias reduction**: No single agent decides what tests should exist
  AND writes them AND verifies them. The decision/implementation/check
  axes are split across three independent agents (two LLM + one script).
- **Reusability**: Pattern applies to any future `/speckit.implement`
  dispatch, not just the Feeds-Vault Revival Sprint.

### Negative

- **Per-spec setup cost**: Test-design subagent adds ~20–45 min of
  wall-clock per spec (small fraction of the ~3–8 hour implementation
  budget).
- **Brittleness**: Strict-naming means a legitimate rename in the test
  file fails the verifier until `tasks.md` is updated. We accept this:
  the test-design agent owns the names, and changes go through it.
- **Tasks.md as live document**: `Testing Requirements` blocks make
  `tasks.md` part of the verification contract, not just a checklist.
  This is consistent with spec-kit's existing treatment of `tasks.md`
  as the implementation contract, but readers should not edit
  `Testing Requirements` blocks once an implementer subagent has started.

### Neutral

- No new runtime dependencies (Principle V + Technology Constraints
  remain intact). The verifier is `scripts/foreman/` dev tooling.
- The pattern is opt-in per spec: if a `tasks.md` has no
  `Testing Requirements` blocks, the verifier reports
  "no requirements declared" and the foreman does no work.

## Implementation notes

- **Format spec**: `docs/foreman.md` — the exact markdown convention
  for `Testing Requirements` blocks (parser contract).
- **Verifier script**: `scripts/foreman/verify_test_coverage.py` —
  CLI: `python -m scripts.foreman.verify_test_coverage --tasks <path> --workdir <path> [--json]`
  exit 0 = all pass, exit 1 = at least one task failed verification,
  exit 2 = parser error / malformed tasks.md.
- **Verifier tests**: `tests/foreman/test_verify_test_coverage.py`
  — covers parser, missing-file detection, missing-function detection,
  failing-test detection, TDD-timeline check (pass + fail cases).
- **Subagent prompts**: `.agents/skills/test-designer/SKILL.md` and
  `.agents/skills/foreman/SKILL.md` — prompt templates for the two
  LLM-driven roles.
- **CLAUDE.md**: brief mention of the pattern in the Testing section,
  plus a `Recent Changes` entry.

## Adoption

- Foreman + test-design infrastructure ships on branch `feat/foreman-pattern`.
- Retro-applied to spec 028 (already shipped as PR #28): the test-design
  subagent generates Testing Requirements blindly (without reading the
  PR #28 code); the verifier runs against PR #28's branch. Results
  inform whether 028 needs follow-up work or is genuinely TDD-clean.
- Going forward, all `/speckit.implement` dispatches in the Feeds-Vault
  Revival Sprint (specs 023, 033, 020) use the three-role pattern.
- Long-term: the per-spec-kit-stage checklist in `CLAUDE.md` adds
  "Test-Design Agent run before /speckit.implement" as a step.

## Related decisions

- **ADR-0007** (Smoke gate is mandatory): the foreman is a *pre-PR*
  gate; the smoke gate (`./build.sh`) remains the *pre-merge* gate.
  They are complementary, not redundant — the foreman verifies test
  *coverage discipline*, the smoke gate verifies *system behavior*.
- **ADR-0008** (Testing pyramid restructure): the `Testing Requirements`
  block annotates tier-2/3/5 informationally on each `**Test N**` line
  so the implementer and reviewer can verify the test landed at the
  appropriate tier. The verifier itself does NOT route tests by tier —
  it invokes ``pytest <node-id>`` in default mode and trusts the
  test file's own pytest markers (``@pytest.mark.e2e`` etc.) to drive
  any tier-specific fixtures. Adding tier-aware routing inside the
  verifier is a deliberate non-goal (Copilot review on PR #29 caught
  the prior wording as an overpromise).
- **Constitution Principle III** (TDD-ish): the foreman makes
  Principle III mechanically verifiable rather than vibes-based.
