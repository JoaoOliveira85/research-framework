# Feature Specification: `./vault update` Hardening

**Feature Branch**: `027-vault-update-hardening`
**Created**: 2026-05-22
**Status**: shipped(2026-06-03, PR #99) — SHIPPED (PR #99) — pre-flight guards, Bash 3.2 shim, FR-012 downgrade prompt, corrupted-manifest fallback; registered in `build.sh::SMOKE_TESTS`. **Reconciles with shipped 0.7.0 (Principle X / `vault_commit.py`) + 0.8.0 (spec 051 `--auto-confirm` + stale-venv) — scope is the delta over those, not a reimplementation.**
**Input**: User description: "Spec 013 (vault migrator) was retired in 0.2.33 in favor of rewiring `./vault update` to `pip install --upgrade` + re-run `install.sh`. The rewire was intentionally minimal; known gaps documented in CHANGELOG [0.2.33] 'Known limitations of the current wrapper'. Promote QW-6 from TODO to spec: harden the update path with version pinning/advisory, idempotency, pre-flight dirty-tree guard, pre-snapshot commit (single-step rollback), post-flight smoke check, rollback path documentation, user-owned-file conflict handling, offline fallback, channel/tag policy, and test coverage."

## Clarifications

### Session 2026-06-03 — all recommended *(theme: reconcile with shipped 0.7.0/0.8.0)*

- **Q1 (FR-011 — `./vault rollback` command or documented two-step?) → document the
  two-step** in `docs/RELEASE.md`; no command (deferred). (FR-011 resolved.)
- **Q2 (FR-004 snapshot vs shipped Principle X auto-commit) → reuse
  `pipeline/vault_commit.py`** for the labelled pre-snapshot; no parallel commit
  path. (FR-004 updated.)
- **Q3 (FR-003/FR-005 flags vs shipped 0.8.0 `--auto-confirm`/stale-venv) → align
  with the shipped flags**; add only non-duplicative behavior (snapshot label,
  FR-002 version short-circuit, FR-006 user-owned-file honoring). (FR-003/005
  updated.)
- **Q4 (downgrade / older-remote behavior) → refuse by default**; explicit pinned
  ref + confirm to override. (New FR-012.)

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Operator upgrades a production vault safely (Priority: P1)

A vault operator runs `./vault update` to pull the latest framework version. Today, the command silently re-downloads + re-runs `install.sh` regardless of whether the framework version actually changed; offers no rollback path if the upgrade breaks the vault; and silently clobbers user-owned scaffolding files. The operator needs an upgrade flow that's safe to run on production vaults.

**Why this priority**: `./vault update` is the **primary upgrade surface** for every vault in the wild. Spec 013 was deleted on the bet that pip + install.sh was sufficient — but the minimal wrapper has no safety net. A botched upgrade today is unrecoverable.

**Independent Test**: Construct a fixture vault committed at framework v0.3.0. Bump pyproject to v0.3.1. Run `./vault update`. Verify:
- Pre-update snapshot commit exists in the vault
- Vault still passes `./vault health` after the update
- User-owned files (`CLAUDE.md`, `research.spec.md`) are preserved verbatim
- Operator can run `git reset --hard <pre-snapshot>` + `pip install research-framework==0.3.0` to roll back

**Acceptance Scenarios**:

1. **Given** a clean vault at framework v0.3.0, **When** operator runs `./vault update` and the remote version is v0.3.1, **Then** the vault gets a `snapshot before update v0.3.0->v0.3.1` commit, the upgrade lands as a second commit, and `./vault health` passes.
2. **Given** a vault with a dirty working tree, **When** operator runs `./vault update` without `--force`, **Then** the command refuses with a clear message: "Working tree is dirty. Commit or stash changes, or re-run with `--force`."
3. **Given** an upgrade fails mid-flight, **When** operator inspects the vault, **Then** `git log -1` shows the pre-snapshot commit and the operator can `git reset --hard HEAD` (or HEAD~1) to recover.
4. **Given** the remote version equals the local version, **When** operator runs `./vault update`, **Then** the command short-circuits with "Already at v0.3.1, nothing to do" — no download, no install.sh re-run.

---

### User Story 2 — Operator can roll back a bad upgrade (Priority: P1)

When an upgrade lands and the vault is broken (health check fails, cycles fail, generator output regresses), the operator needs a single-command rollback path.

**Why this priority**: Recovery story is what makes the upgrade flow safe to use. Without a rollback, operators avoid upgrades (technical debt accumulates).

**Acceptance Scenarios**:

1. **Given** a vault that was just upgraded v0.3.0 → v0.3.1 and now fails health checks, **When** operator runs `./vault rollback` (or `git reset --hard <pre-snapshot> && pip install research-framework==<old-version>`), **Then** the vault returns to its pre-upgrade state.
2. **Given** the vault's `_pipeline/state.json` was rewritten during the upgrade, **When** the rollback completes, **Then** `state.json` reflects the pre-upgrade content.

---

### User Story 3 — User-owned files survive upgrades (Priority: P2)

The framework's scaffold manifest marks certain files (`CLAUDE.md`, `research.spec.md`, `settings.yaml`, `.claude/commands/*.md`) as `is_user_owned_after_first_write`. The current update path doesn't honor this — it overwrites everything.

**Why this priority**: User-owned customization is a hard contract per `dist-templates/scaffold-manifest.json`. Silently clobbering it makes the upgrade flow distrusted.

**Acceptance Scenarios**:

1. **Given** a vault where operator has edited `CLAUDE.md` post-install, **When** operator runs `./vault update`, **Then** the edited `CLAUDE.md` is preserved verbatim (not regenerated from template).
2. **Given** a `.local.md` override exists for a generated `.claude/commands/foo.md`, **When** the upgrade runs, **Then** the `.local.md` is preserved and the regenerated `foo.md` doesn't shadow it incorrectly.

---

### User Story 4 — Air-gapped operators can upgrade offline (Priority: P3)

Some vault operators run on isolated machines (no internet). They need a manual upgrade path documented and supported.

**Why this priority**: Low frequency but high impact when needed. Closes a documented limitation.

**Acceptance Scenarios**:

1. **Given** a `research_framework-<version>-py3-none-any.whl` + a local install bundle tarball, **When** operator runs `pip install <wheel>` + `bash <bundle>/install.sh <vault-dir>`, **Then** the upgrade completes equivalently to the online flow.
2. **Given** the documented offline path, **When** operator follows the steps in `docs/RELEASE.md`, **Then** the operator can complete the upgrade without network access.

---

### Edge Cases

- What happens when the remote version is OLDER than the local (operator manually pinned to a higher version)? Refuse, warn, or proceed with downgrade?
- What if the snapshot commit fails because the vault is in a detached-HEAD state or on a branch the operator doesn't own?
- What if the operator's vault venv has additional pip-installed packages (custom plugins)? The `pip install --upgrade` should not clobber those.
- What if `RV_GITHUB_REF` points to a non-existent ref / a deleted branch?
- What's the behaviour when network drops mid-`pip install`?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `./vault update` MUST record the framework version BEFORE the upgrade and print the version diff (e.g., "Upgrading v0.3.0 → v0.3.1") before any mutation.
- **FR-002**: When the local version equals the remote version, `./vault update` MUST short-circuit with "Already at vX.Y.Z, nothing to do" and exit 0 without re-running `install.sh`.
- **FR-003**: `./vault update` MUST refuse to run on a dirty working tree unless `--force` is passed; the refusal message MUST instruct the operator to commit/stash or use `--force`. **(Clarifications Q3)** Align with the **shipped 0.8.0 flag surface** — reuse `--auto-confirm` for prompt suppression rather than adding a competing flag; `--force` covers only the dirty-tree override. Note 0.7.0's Principle X already hard-stops `./vault research` on a dirty *main*; FR-003 extends the dirty-tree guard to `update`, consistent with that.
- **FR-004**: **(Clarifications Q2 — reconcile with shipped 0.7.0, do NOT reimplement.)** The pre-mutation snapshot MUST be created **via `pipeline/vault_commit.py`** (the shipped Principle X commit path), as a labelled pre-snapshot commit (`snapshot before update <old> -> <new>`) that is the immediate parent of the upgrade commit so `git reset --hard HEAD~1` rolls back. A parallel/independent commit mechanism is forbidden (avoids double-commits + divergent dirty-tree semantics with 0.7.0).
- **FR-005**: After `install.sh` returns, `./vault update` MUST run `./vault health` (or equivalent) and surface failures prominently; health failure ⇒ non-zero exit. **(Clarifications Q3)** Spec 051 (0.8.0) already shipped stale-venv detection + a post-install version sanity check on `./vault update` — FR-005 adds only the **non-duplicative** remainder (the health invocation + prominent surfacing); it MUST NOT re-implement the shipped post-install checks.
- **FR-006**: `install.sh` (or the update wrapper) MUST honor the `is_user_owned_after_first_write` flag in `dist-templates/scaffold-manifest.json`. Files flagged user-owned MUST NOT be regenerated; if they exist they MUST be preserved.
- **FR-007**: An offline / air-gapped path MUST be documented in `docs/RELEASE.md` with concrete commands.
- **FR-008**: Channel / tag policy: by default, `./vault update` tracks `main` (current behaviour). `docs/RELEASE.md` SHOULD document pinning to a tagged release via `RV_GITHUB_REF=vX.Y.Z` (recommended for production vaults) and the explicit `RV_GITHUB_REF=main` override.
- **FR-009**: A smoke test `tests/cli/test_vault_update.py` MUST exist that:
  - Runs `./vault update` against a fixture vault using a local file-URL repo
  - Verifies the version metadata changed
  - Verifies `./vault health` still passes
  - Verifies a user-owned file edit survives
- **FR-010**: The smoke test from FR-009 MUST be added to `build.sh::SMOKE_TESTS` (or equivalent) so it gates releases.
- **FR-011**: **Resolved (Clarifications Q1) → document the manual two-step, no command.** `docs/RELEASE.md` documents the rollback as `git reset --hard HEAD~1 && pip install research-framework==<old-version>` (the FR-004 snapshot makes this reliable). A first-class `./vault rollback` command is **deferred** — it adds CLI surface + version-detection logic + tests for marginal ergonomic gain; revisit only if operators ask.
- **FR-012**: **(Clarifications Q4) — refuse downgrades by default.** `./vault update` MUST NOT move the vault to an *older* framework version unless the operator sets an explicit pinned older ref (`RV_GITHUB_REF=<older>` per FR-008) **and** confirms via the shipped `--auto-confirm` flag (headless: suppresses the interactive downgrade prompt) or an interactive TTY prompt when `--auto-confirm` is absent. An accidental downgrade on a production vault during a live-run window is fail-closed-prevented.

### Key Entities

- **Pre-snapshot commit**: A vault-side commit immediately before any framework-driven mutation. Subject format: `snapshot before update <old-version> -> <new-version>`.
- **Update transcript**: A summary printed to stdout (or written to `_pipeline/`) showing version diff, files changed, health check result.
- **Scaffold manifest entry**: Existing `dist-templates/scaffold-manifest.json` entry per file, with `is_user_owned_after_first_write: bool`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Operator can upgrade a vault from any released version N to N+1 with a single `./vault update` command and recover with a single `git reset --hard HEAD~1 && pip install research-framework==N` if needed.
- **SC-002**: Re-running `./vault update` with no remote change exits in <5 seconds (no `pip install --upgrade` invocation, no install.sh re-run).
- **SC-003**: Running `./vault update` on a dirty tree without `--force` exits non-zero in <2 seconds with a clear error message.
- **SC-004**: A user-owned file edit (touch + edit `CLAUDE.md`) survives an upgrade verbatim.
- **SC-005**: `tests/cli/test_vault_update.py` runs in <15 seconds and is in the smoke gate manifest.
- **SC-006**: The "Known limitations of the current wrapper" entry in CHANGELOG [0.2.33] is replaced by an entry in `[0.3.x]` documenting the hardened wrapper.

## Assumptions

- The `scaffold-manifest.json` `is_user_owned_after_first_write` flag is already correctly populated for all files in the dist-templates tree. (Audit during planning.)
- `pip install --upgrade git+...` is the canonical install path (alternative: PyPI publish from queue item #18 / spec 041 — out of scope here).
- The vault has `git init` already done (non-git vaults degrade gracefully per ROADMAP "Git-clean precondition" policy).
- The fixture vault for FR-009 can be a small generated tree (use `tests/_helpers/vault_factory::build_minimal_vault` or equivalent).

## Dependencies

- None on unshipped specs. Builds on:
  - `dist-templates/install.sh` + `scaffold-manifest.json` (existing)
  - `templates/vault-script.sh.j2` `update` case (existing)
  - `./vault health` (existing)
- Touches QW-4 (vault spec git-tracked health warning) thematically — the same `./vault health` integration point. May ship together.

## Acceptance coverage

Evidence populated 2026-06-03 (T035). US1/US3 carry automated CLI
coverage in `tests/cli/test_vault_update.py`; US2/US4 are operator-doc
surfaces (`docs/RELEASE.md`) with no automated path in this spec's scope.

| User Story | Evidence |
|------------|----------|
| US1 — Operator upgrades a production vault safely | `tests/cli/test_vault_update.py` (topology, health-failure, dirty-tree, short-circuit, downgrade-refused cases) |
| US2 — Operator can roll back a bad upgrade | `tests/cli/test_vault_update.py::test_pre_snapshot_then_upgrade_topology` (snapshot precondition enabling rollback) + `docs/RELEASE.md` §rollback |
| US3 — User-owned files survive upgrades | `tests/cli/test_vault_update.py::test_user_owned_file_survives_upgrade` |
| US4 — Air-gapped operators can upgrade offline | _(deferred to tasks.md — air-gapped upgrade is operator-doc-only: `docs/RELEASE.md` §offline; no automated offline test in scope)_ |

## Out of Scope

- Legacy `install.sh` `${VAULT_DIR}` / `ROOT_DIR` positional-argument discard bug — owned by **spec 039 (installer hardening)**, not this spec. 027 is the `./vault update` hardening delta only.
- PyPI publication (queue item #18 / spec 041 — separate concern).
- Cross-version migration of vault content (spec 013 was retired specifically because content migration wasn't needed; the rename-runbook covered the v0.2.x → v0.3.0 jump).
- Multi-vault batch updates (per-vault flow per ROADMAP).
- Automatic version-pinning suggestions (manual today; future enhancement).
