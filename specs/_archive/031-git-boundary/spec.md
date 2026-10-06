# Feature Specification: Project-Wide Git Boundary Helper

> **🗄️ TOMBSTONED — SUBSUMED BY spec 050 (decided 2026-06-03).** The core of 031
> — *a single shared git-boundary helper so no workflow writes to a dirty vault* —
> **shipped in spec 050 (v0.7.0, Principle X)** as `pipeline/vault_commit.py`. A
> 2026-06-03 code audit at the 053 base confirmed 050 chose a **stricter, better
> model than 031 proposed**: a clean-`main` **HARD STOP** (exit 2 via
> `VaultCommitDirtyError`) instead of 031's "snapshot the dirty state and proceed",
> and a branch-based lifecycle (`research/<timestamp>` → squash-merge on rc=0 /
> retain on rc=1 / rewind on rc=2) instead of 031's pre-snapshot + side-branch
> model. 050 also already delivers non-git graceful degradation (`_ensure_repo`)
> and the no-git-config-mutation guarantee. **So US1, FR-002, FR-004, FR-005,
> FR-006, FR-007, FR-008, FR-009 are all superseded.**
>
> **Residual (the part 050 did NOT ship)** — the *enforcement lint* (031's
> US2/SC-004: nothing stops raw vault-mutating git outside `vault_commit.py`, and
> the audit found **6** modules doing raw git incl. a second module `vault_git.py`),
> plus the `commit_command_output`/`commit_framework_change` coverage gap — has been
> **refiled as spec 050 follow-up F5** (see
> `specs/050-vault-auto-commit/spec.md` §"Future (deferred follow-ups)"). A whole
> spec for a single lint + a consolidation pass is heavier than the residual
> warrants; F5 is the right-sized home.
>
> **Do NOT plan or implement against 031.** Kept below as design-history (its
> failure-mode analysis informed 050's hard-stop choice). See
> `specs/050-vault-auto-commit/spec.md` and Principle X in
> `.specify/memory/constitution.md`.

**Feature Branch**: `031-git-boundary`
**Created**: 2026-05-22
**Status**: superseded(by spec 050) — 🗄️ **TOMBSTONED — SUBSUMED BY spec 050 (2026-06-03)**; residual (enforcement lint + module consolidation + coverage gap) refiled as **spec 050 F5**. (Was: Draft.)
**Input**: User description: "Generalizes spec-013's FR-016 git boundary from migrator-only to EVERY workflow that mutates a vault folder or its data_vault/ child. The invariant: no workflow ever writes to a folder that has uncommitted changes. If the working tree is dirty when a workflow starts, the workflow commits the dirty state as a pre-<workflow> snapshot BEFORE doing anything else. Then the workflow's own writes land as a second, conventionally-prefixed commit. Branch-on-failure for autonomous flows (cron, scheduler) — partial state preserved on side branch; main reset to pre-snapshot. Single shared git_boundary.py helper to enforce policy at one point."

> **⚠️ The sections below are HISTORICAL (pre-tombstone, 2026-05-22).** They are
> preserved for design-history only and do NOT reflect the shipped reality (spec
> 050). Where 031 says "snapshot dirty state and proceed", 050 actually HARD-STOPS
> on a dirty main. Read them as the analysis that *led to* 050, not as a plan.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Autonomous workflow doesn't clobber user drafts (Priority: P1)

A cron-driven research cycle starts at 3am. The user was editing notes in the vault at midnight and left the working tree dirty (a few `data_vault/` files with unstaged changes). Without this spec, the autonomous cycle writes new notes on top of the dirty state, and the user's drafts are silently lost. With this spec, the cycle SEES the dirty tree, commits it as `pre-research-2026-05-23T03:00:00Z` snapshot, then runs the cycle's writes on top.

**Why this priority**: This is the failure mode that the 2026-05-13 production audit surfaced. Autonomous flows are the future of the framework (cron + iOS Shortcuts + assistant-framework). Without the boundary, all autonomous flows are too risky to enable.

**Independent Test**: Construct a fixture vault with a dirty working tree (1 unstaged file). Invoke a workflow that should be governed by the boundary (e.g., `./vault research --autonomous`). After the run:
- `git log` shows: `pre-research-<timestamp>` commit with the dirty file, then the workflow's own commit on top
- The originally-dirty file's content is preserved in the snapshot commit
- The workflow's writes are visible on HEAD

**Acceptance Scenarios**:

1. **Given** a dirty working tree, **When** an autonomous workflow starts, **Then** the dirty state is committed as `pre-<workflow>-<timestamp>` BEFORE any workflow writes happen.
2. **Given** a clean working tree, **When** an autonomous workflow starts, **Then** no pre-snapshot commit is created (no false commits on a clean tree).
3. **Given** an autonomous workflow fails mid-run, **When** the user inspects the vault, **Then** the partial state is on a side branch `<workflow>/<date>-failed-<reason>` and `main` is reset to the pre-snapshot.
4. **Given** an INTERACTIVE workflow (user invoked `./vault research` directly), **When** the workflow fails mid-run, **Then** the partial state stays on `main` and the user is shown how to roll back.

---

### User Story 2 — Single point of policy enforcement across all workflows (Priority: P1)

Currently, some workflows have their own git logic (the deleted spec-013 migrator had `git_boundary` logic). Spec 027 will add similar logic for `./vault update`. The cycle runner doesn't have any today. Without a shared helper, the policy fragments and each workflow's edge cases get re-discovered.

**Why this priority**: Code-organization correctness. Avoids the trap of "the migrator did it this way, the updater did it that way, the cycle runner did it yet another way".

**Acceptance Scenarios**:

1. **Given** workflows: `./vault research`, `./vault update`, `./vault audit`, `./vault maintain`, and the indexer / wikilink-fix tools, **When** any of them mutates files in the vault, **Then** they all go through the shared `git_boundary.py` helper.
2. **Given** a new workflow is added to the framework, **When** the developer follows the contributing guide, **Then** they wire their workflow into `git_boundary.py` rather than implementing their own commit logic.

---

### User Story 3 — Non-git vaults degrade gracefully (Priority: P2)

Some users won't `git init` their vault. The framework must still run — but warn loudly on first invocation that no safety net exists.

**Why this priority**: Opt-in safety. Don't refuse to run; just be honest about the lack of guarantees.

**Acceptance Scenarios**:

1. **Given** a vault without `.git/`, **When** a workflow with the boundary starts, **Then** the workflow prints a one-time warning ("vault is not git-tracked; no safety net for partial failures") and proceeds.
2. **Given** the warning, **When** the user runs `git init` in the vault, **Then** subsequent workflow invocations get the full boundary protection without re-warning.

---

### Edge Cases

- What if the vault is on a detached HEAD when the workflow starts?
- What if the pre-snapshot commit would conflict with a stashed change?
- What if the user has staged-but-not-committed changes? Same boundary or different?
- What if `git commit` itself fails (e.g., commit-hook failure)? The workflow MUST refuse to proceed.
- What's the side-branch naming for nested workflows (audit calls research)?
- How does this interact with spec 026 fixture isolation (the harness vaults are git-tracked subfolders of `tests/fixtures/quality/` — the boundary should NOT apply to them).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A `src/research_framework/vault/git_boundary.py` module MUST exist as the single shared enforcement point for the git-boundary policy.
- **FR-002**: The helper API MUST include at minimum: `with_git_boundary(vault_dir, workflow_name, mode) -> ContextManager`. The context manager: snapshots dirty state on entry, runs workflow body, finalizes on exit.
- **FR-003**: Each workflow that mutates a vault folder MUST go through `with_git_boundary`. Workflows in scope: `./vault research`, `./vault update`, `./vault audit`, `./vault maintain`, `./vault reindex`, any indexer/wikilink-fix tools, the bridge-rebuild path from spec 020.
- **FR-004**: The boundary MUST distinguish AUTONOMOUS mode (cron, scheduler, no TTY) from INTERACTIVE mode (user invoked directly). On failure: autonomous → side-branch + reset main; interactive → leave on main + user-facing rollback instructions.
- **FR-005**: Mode detection MAY be: (a) explicit `--autonomous` flag passed by the caller; (b) `isatty()` detection; (c) env var like `RESEARCH_AUTONOMOUS=1`. [NEEDS CLARIFICATION: which is canonical? Recommend (a) explicit flag with (b) as a safety net for cron jobs that forget the flag.]
- **FR-006**: The snapshot commit message MUST follow the format: `pre-<workflow>-<ISO8601-timestamp>`. The workflow's own commit(s) MUST use the conventional prefix (`research:`, `audit:`, `maintenance:`, `update:`).
- **FR-007**: On AUTONOMOUS failure, the side branch name MUST follow: `<workflow>/<YYYY-MM-DD>-failed-<short-reason>` (where short-reason is a slug like `verifier-rejection` or `source-timeout`).
- **FR-008**: Non-git vaults MUST trigger a one-time warning per session, not a refusal. Subsequent runs in the same session SHOULD NOT re-warn (idempotent warning).
- **FR-009**: The helper MUST NOT touch the user's git config (per security rules). All commits MUST use whatever the user's configured identity is.
- **FR-010**: A regression test MUST exist for each scenario: dirty tree + autonomous + success / dirty tree + autonomous + failure / dirty tree + interactive + success / dirty tree + interactive + failure / clean tree + success / non-git vault.
- **FR-011**: A "planned changes" report MAY be supported (2026-05-20 triage item #22, `docs/TODO.md#restoration-notes`): before the workflow runs, write a `<workflow>-intent.md` to `_pipeline/` declaring what the workflow plans to do, committed as part of the pre-snapshot. This is required for auditability of autonomous maintenance. [NEEDS CLARIFICATION: ship intent reports in v1 of this spec, or defer?]
- **FR-012**: The helper MUST integrate with the spec 027 `./vault update` pre-snapshot logic — they should be the same code path, not parallel implementations.

### Key Entities

- **`with_git_boundary` context manager**: API surface for workflows. Yields a `BoundaryHandle` with `record_planned_changes()`, `finalize_success()`, `finalize_failure(reason)`.
- **Pre-snapshot commit**: A commit before any workflow mutation, capturing the dirty state of the vault.
- **Side branch (autonomous failures only)**: `<workflow>/<date>-failed-<reason>`. Contains the partial state.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every workflow in scope (FR-003) has a test that exercises the boundary in both autonomous + interactive modes.
- **SC-002**: For autonomous workflows: an injected mid-run failure results in the vault's `main` branch being reset to the pre-snapshot, with the partial state preserved on a discoverable side branch.
- **SC-003**: For interactive workflows: an injected mid-run failure leaves the vault on `main` with the partial state visible to the user.
- **SC-004**: No workflow under `pipeline/`, `cli/`, `scripts/` invokes raw `git commit` or `git stash` for vault mutations — all such calls are mediated by `git_boundary.py`. Static lint check enforces this.
- **SC-005**: A new vault workflow added without going through `git_boundary.py` is caught by the lint in SC-004 + a code-review checklist item.

## Assumptions

- The vault has a `.git/` directory in most production cases (per ROADMAP precondition policy). Non-git vaults are best-effort.
- `git` CLI is available (already a hard dependency of `install.sh`).
- The user's git identity is configured (`git config user.email` / `user.name` non-empty). If not, the boundary surfaces a clear error before doing anything destructive.
- The boundary policy lands BEFORE spec 027 implementation, so spec 027 consumes the helper rather than implementing its own.

## Dependencies

- Spec 027 (vault update) — overlaps on pre-snapshot logic; ship boundary first OR co-ship.
- Spec 020 (source modules) — bridge-rebuild path needs the boundary if it mutates vault state.
- Soft on spec 023 (flow separation) — VaultHandle abstraction may interact with the boundary helper's API shape.

## Acceptance coverage

Draft — evidence cells will be populated by `/speckit.tasks` for
this spec. Listed for the ADR-0008 guard so the spec is accepted
into the queue (the guard refuses any G/W/T-bearing spec without
this section).

| User Story | Evidence |
|------------|----------|
| US1 — Autonomous workflow doesn't clobber user drafts | _(deferred to tasks.md — populated by `/speckit.tasks`)_ |
| US2 — Single point of policy enforcement across all workflows | _(deferred to tasks.md — populated by `/speckit.tasks`)_ |
| US3 — Non-git vaults degrade gracefully | _(deferred to tasks.md — populated by `/speckit.tasks`)_ |

## Out of Scope

- Promoting this to a constitutional "Always Do" principle. Per ROADMAP "Likely follow-on" — separate explicit action after the helper ships.
- A "git boundary" for non-vault writes (e.g., framework-side template generation, scaffold-manifest updates). Different concern.
- Multi-vault transactional commits (one boundary across N vaults). Each vault is its own boundary.
- Cross-machine snapshot replication. Spec 023 / Horizon 2 may revisit.
