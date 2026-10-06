# Feature Specification: Vault Control-File Git-Tracking Health Warning

**Feature Branch**: `058-vault-spec-health-warning`
**Created**: 2026-06-03
**Status**: shipped(2026-07-01, PR #183) — SHIPPED [Unreleased] (PR #183, squash `c24cd22`, 2026-07-01). All 15
tasks complete — `./vault health` warns (advisory, never fails) when a
git-backed vault's control files are untracked or git-ignored.
**Input**: User description: "Run /speckit.specify for the un-specced QW-4 'vault-spec git-tracked health warning' idea in docs/TODO.md."

> **Origin**: `docs/TODO.md` → "Implementation details" → *QW-4 — vault-spec
> git-tracked health warning* (also ROADMAP quick-win QW-4). This spec is the live
> home; the QW-4 entries are annotated `(now spec 058)`.

## Clarifications

### Session 2026-06-03

- **Q1 (absent vs untracked)** → **Defer absence** to existing missing-file / precondition checks (`preconditions.py`, `./vault audit` validators). This check runs **only for control files that exist on disk** and reports tracking status (untracked / ignored).
- **Q2 (configurable file set)** → **Fixed four paths for v1** (vault-relative paths in `contracts/control-file-tracking.contract.md` §1). No `settings.yaml` knob; extensibility is a follow-up.
- **Q3 (`--fix` affordance)** → **Warn-only for v1**. No auto-`git add`, no `--fix` flag. Remediation is operator-driven (`git add` + commit per Principle X).
- **Q4 (placement)** → **`scripts/vault_health.py`** invoked by **`./vault health`** (`templates/vault-script.sh.j2`). **Not** `validate_vault.py` (note-body validator; consumed by `./vault audit`, not the fast health path).

## Overview

A vault's ability to **evolve** depends on a small set of control files living in git:
`research.spec.md` (parsed by the regenerator, `/ask`, `update`, and audit),
`settings.yaml`, `research-backlog.md`, and `coverage-targets.json`. If any of these is
**untracked** or **git-ignored** in a git-backed vault, the loss is silent until it
bites: a `git clean -fdx` or a fresh clone wipes the file, and with it the vault's
ability to be updated, regenerated, audited, or even understood by a future agent. The
2026-05-26 feeds-vault archaeology found exactly this class of footgun.

Since Principle X (spec 050) now makes vault history append-only git — vaults are
git-backed **by default** — an untracked control file is a live data-loss risk, not a
theoretical one. This feature extends the existing **vault health** surface to emit a
**warning** (never a hard failure) when, for a git-backed vault, any critical control
file is untracked or ignored, naming each at-risk file and why. Non-git vaults skip the
check silently.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Warn when a control file isn't in git (Priority: P1)

As a vault operator, when I run the vault health check on a git-backed vault, I want a
warning that lists any critical control file (`research.spec.md`, `settings.yaml`,
`research-backlog.md`, `coverage-targets.json`) that is untracked or git-ignored, so I can
add it to git before a clean or fresh clone destroys my vault's ability to evolve.

**Why this priority**: This is the whole feature — surfacing a silent, destructive risk
before it strikes. It is the MVP.

**Independent Test**: In a git-backed vault, leave `research.spec.md` untracked, run the
health check, and confirm a warning names that file; track it and confirm the warning
clears.

**Acceptance Scenarios**:

1. **Given** a git-backed vault where `research.spec.md` is untracked, **When** the health
   check runs, **Then** it emits a warning naming `research.spec.md` as untracked.
2. **Given** a git-backed vault where `settings.yaml` matches a `.gitignore` rule, **When**
   the health check runs, **Then** it emits a warning naming `settings.yaml` as ignored.
3. **Given** a git-backed vault where all four control files are tracked, **When** the
   health check runs, **Then** it emits no control-file-tracking warning.

---

### User Story 2 - Stay silent on non-git vaults (Priority: P2)

As an operator of a vault that is not under git, I want this check skipped silently,
because the data-loss-on-clean risk doesn't apply and I don't want spurious warnings.

**Why this priority**: Prevents the feature from becoming noise for a whole class of
vaults. Important, but only meaningful alongside US1.

**Independent Test**: Run the health check in a directory that is not a git work tree and
confirm the check produces no output.

**Acceptance Scenarios**:

1. **Given** a vault root that is not inside a git work tree, **When** the health check
   runs, **Then** the control-file-tracking check produces no warning and no error.

---

### User Story 3 - Advisory, actionable, never blocking (Priority: P3)

As an operator, I want the warning to be advisory (a WARN, not a hard FAIL) and to name
each at-risk file plus the reason (untracked vs ignored), so it never blocks a cycle and I
know exactly what to fix.

**Why this priority**: Determines that the check is safe to run in any flow. Lowest
priority because it refines US1's behaviour rather than adding new capability.

**Independent Test**: Trigger the warning and confirm the health command's overall
pass/fail status is unchanged, and that each warned file carries its reason.

**Acceptance Scenarios**:

1. **Given** a warning fires, **When** the health command completes, **Then** its overall
   exit/pass status is unchanged by this check alone (advisory only).
2. **Given** multiple at-risk files, **When** the warning is emitted, **Then** each file is
   listed with its reason (untracked or ignored).

---

### Edge Cases

- **Vault not under git** → check skipped silently (US2).
- **Control file absent entirely** (not merely untracked) → **skipped** by this check
  (FR-002a); `preconditions.py` / `./vault audit` own missing-file detection.
- **File ignored by a parent/global `.gitignore`** → detected and warned as ignored.
- **File tracked but with uncommitted edits** → NOT this check's concern (Principle X /
  spec 050 owns commit state); no warning.
- **Some control files tracked, others not** → warn only for the at-risk ones.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: For a **git-backed** vault, the health check MUST emit a **warning** when any
  critical control file is **untracked** or **git-ignored**.
- **FR-002**: The critical control-file set MUST be exactly the four vault-relative
  paths in `contracts/control-file-tracking.contract.md` §1:
  `research.spec.md`, `settings.yaml`, `_pipeline/research-backlog.md`,
  `_pipeline/coverage-targets.json`.
- **FR-002a**: A control file that **does not exist** on disk MUST be **skipped**
  (no warning from this check). Absence is owned by existing precondition / audit
  surfaces, not this feature.
- **FR-003**: For a vault **not** under git, the check MUST be **skipped silently** (no
  warning, no error).
- **FR-004**: The check MUST be a **WARNING only** — it MUST NOT, by itself, fail the
  health command, block a cycle, or change the command's exit status.
- **FR-005**: Each warning MUST name the **specific file(s)** and the **reason**
  (untracked vs ignored) so remediation is unambiguous.
- **FR-006**: A control file that is **properly tracked** MUST NOT produce a warning (no
  false positives).
- **FR-007**: The check MUST be **deterministic** — the same vault/git state yields the
  same warnings every run (Principle IV).

### Key Entities *(include if feature involves data)*

- **Critical control-file set**: the fixed four vault-relative paths (contract §1) a
  vault needs in git to remain evolvable.
- **Tracking status**: per file → {tracked | untracked | ignored}, derived from the
  vault's git state.
- **Health warning**: an advisory record naming an at-risk file and its reason; does not
  affect the command's pass/fail.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a git-backed vault with an untracked `research.spec.md`, the health check
  emits exactly one control-file warning naming it; with all four control files tracked it
  emits zero.
- **SC-002**: In a non-git vault, the check produces zero output.
- **SC-003**: Triggering the warning never changes the health command's overall pass/fail
  exit status.
- **SC-004**: Both conditions are covered — an untracked file and an ignored file each
  produce a correctly-labelled warning.
- **SC-005**: The check is deterministic — identical vault/git state yields identical
  warnings across repeated runs.

## Assumptions

- This **extends** `scripts/vault_health.py` / **`./vault health`** only — not
  `validate_vault.py` / `./vault audit`.
- It is **more relevant post-Principle-X (spec 050)**: vaults are git-backed by default, so
  untracked control files are a live data-loss risk on `git clean` / fresh clone.
- The control-file set mirrors what the regenerator, `/ask`, `update`, and audit actually
  parse; it is **fixed for v1** (configurability is a clarify tension).
- **Absent** control files are **skipped** here (FR-002a); tracked by preconditions /
  audit elsewhere.
- "git-backed" means the vault root resolves inside a git work tree.
- **No new runtime dependency** (Principle V); the check is **deterministic** (Principle
  IV).

## Out of Scope

- Auto-remediation (`git add`, `--fix`) — warn-only for v1; `--fix` deferred to a
  follow-up spec / QW-4b.
- Checking commit freshness or dirty-tree state (Principle X / spec 050 owns commit
  behaviour).
- A configurable/extensible critical-file set (fixed for v1).
- Any behaviour for non-git vaults (intentionally skipped).

## Acceptance coverage

| User Story | Evidence |
|------------|----------|
| US1 — Warn when a control file isn't in git | _(deferred to tasks.md — implement-ready 2026-06-03; tests land with /speckit.implement)_ |
| US2 — Stay silent on non-git vaults | _(deferred to tasks.md — implement-ready 2026-06-03; tests land with /speckit.implement)_ |
| US3 — Advisory, actionable, never blocking | _(deferred to tasks.md — implement-ready 2026-06-03; tests land with /speckit.implement)_ |
