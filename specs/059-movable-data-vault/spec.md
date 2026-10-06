# Feature Specification: Movable `data_vault/` (data outside the vault root)

**Feature Branch**: `059-movable-data-vault`
**Created**: 2026-06-03
**Status**: planned — Draft — ⚠️ PARKED / DESIGN-SPACE — clarified (non-gating tensions) 2026-06-03; still blocked from `/speckit.plan` on the Principle-X gate below
**Input**: User description: "Run /speckit.specify for the un-specced 'Movable data_vault/ (outside vault root via symlink)' item parked on docs/ROADMAP.md."

> **Origin**: `docs/ROADMAP.md` → "Eventually — Parked" → *Movable `data_vault/`*.
> This spec is the live home; the ROADMAP entry is annotated `(now spec 059, design-space)`.

> ⚠️ **This item is PARKED on purpose.** The ROADMAP says: *revisit when there's a
> concrete reason the data must primarily live outside (storage tier, encryption,
> sharing)*. It is drafted here at the user's request to capture the design space, but it
> **must not proceed to `/speckit.plan` until the Principle X interaction (below) is
> resolved** — that is the gating concern, not a detail.

## Overview

Today a vault is a single directory: small **control files** (`research.spec.md`,
`settings.yaml`, `research-backlog.md`, `coverage-targets.json`, `_pipeline/…`) plus the
bulky **`data_vault/`** that holds the actual notes. Some operators have a legitimate
reason to want the *data* to physically live **outside** the vault root while the vault
still behaves as one unit:

- **Storage tier** — keep a large note corpus on a bigger/cheaper volume than the working
  tree.
- **Encryption** — place note data on an encrypted volume.
- **Sharing** — keep note data on a shared/synced location while control files stay local.

The immediate "I just want a copy elsewhere" need is already met by the **vault mirror**
(spec 044). This spec is the *harder* case: the **primary** data living elsewhere, with
the framework resolving it transparently.

**The gating tension — Principle X.** Since spec 050 (constitution v1.4.0), *vault history
is append-only git* (NON-NEGOTIABLE): every framework operation that mutates a vault lands
as a git commit in the vault's work tree. If `data_vault/` is symlinked to a location
**outside** that work tree, the note mutations are no longer captured by the vault's git —
which would **violate Principle X**. Any viable design for this feature must keep relocated
data under append-only git history. Resolving *how* is the prerequisite for planning, and
  the reason this stays parked until a concrete need justifies the complexity.

## Clarifications

### Session 2026-06-03

This spec is **PARKED**. This clarify pass resolved the three *non-gating* tensions so the
design space is fully captured, and **deliberately left the gating Principle-X tension
open** — resolving it would un-park the feature, which is an Ask-First, principle-interacting
decision (it touches a NON-NEGOTIABLE principle), so it is left for a human to ratify.

- **Q — Configuration surface (symlink vs `settings.yaml` path vs both)?** → The relocation
  is recorded as an explicit, git-tracked pointer in `settings.yaml` (e.g.
  `data_vault.location:`), which is **authoritative**. An on-disk symlink MAY realize it, but
  the `settings.yaml` value is the source of truth that satisfies FR-005 (discoverable +
  reproducible across machines). Inference from a bare symlink alone is rejected (not
  reliably discoverable in git history).
- **Q — Concrete trigger that justifies un-parking?** → A **storage-tier or encrypted-volume**
  need (the bulky corpus must live on a bigger / cheaper / encrypted volume). "Sharing" does
  **not** un-park this spec — it is redirected to spec 044 (mirror) or the operator's own
  sync layer (already Out of Scope). This narrows the viable Principle-X resolutions.
- **Q — Migration: onboard-time only, or move an existing vault's data out?** → First viable
  version is **onboard-time only** — the external location is chosen when the vault is
  created. "Move an existing in-root vault's data out" is a higher-risk follow-up
  (data-loss surface) and is deferred; not in the first cut.
- **Q — (GATING) How does relocated data stay under Principle X append-only history?** →
  **STILL OPEN.** The three candidates in the Blocking question stand. *Non-binding
  recommendation* for whoever un-parks: **option 1** (the external location is itself a git
  repo the framework commits to) is the only candidate that preserves Principle X robustly
  across separate volumes + encryption + machine moves; option 2 constrains *where* data may
  live (defeating the storage/encryption motivation) and option 3 (bind-mount) is the least
  portable. **This remains the gate** — the feature MUST NOT proceed to `/speckit.plan`
  until a human ratifies a resolution.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Keep the bulky data on a separate volume (Priority: P1)

As a vault operator with a large or sensitive note corpus, I want `data_vault/` to
physically reside outside the vault root (on a bigger / encrypted / shared volume) while
the framework still treats it as the vault's data, so I can manage storage, encryption, or
sharing independently of the small git-tracked control files.

**Why this priority**: It is the feature's reason to exist. Without it there is nothing to
build.

**Independent Test**: Configure a vault whose `data_vault/` resolves to an external
location, run a normal read/write verb, and confirm notes are read and written at the
external location with no behavioural difference.

**Acceptance Scenarios**:

1. **Given** a vault configured with an external `data_vault/` location, **When** a verb
   reads or writes notes, **Then** the data is read/written at the external location and
   the result is identical to an in-root layout.
2. **Given** the same vault, **When** the operator inspects the vault root, **Then** the
   control files remain in the root (and in git) regardless of where the data lives.

---

### User Story 2 - Every verb resolves the relocation transparently (Priority: P2)

As an operator, I want all framework verbs (`research`, `ask`, `write`, `audit`, `update`,
`sync`) to resolve the relocated data automatically, so I never have to special-case the
layout per command.

**Why this priority**: A relocation that only some verbs honour is a data-corruption trap.
Important, but only meaningful once US1 exists.

**Independent Test**: Exercise each verb against a relocated-data vault and confirm
identical behaviour to an in-root vault.

**Acceptance Scenarios**:

1. **Given** a relocated-data vault, **When** any verb runs, **Then** it resolves the
   external location with no per-command configuration.

---

### User Story 3 - Fail loud when the external location is missing (Priority: P1)

As an operator who moves between machines (or whose external volume isn't mounted), I want
the framework to refuse to run — loudly and cleanly — when the external data location is
unavailable, so I never get a silent partial run or destroyed data.

**Why this priority**: The failure mode here is **data loss / corruption**, which is
catastrophic — so this is co-P1 with US1 even though it's a guardrail. A movable data store
that fails silently is worse than no feature.

**Independent Test**: Point the vault at an external location that does not exist, run a
verb, and confirm a clean non-zero refusal with a clear message — and that nothing was
written or deleted.

**Acceptance Scenarios**:

1. **Given** a vault whose external data location is missing/unmounted, **When** any verb
   runs, **Then** it refuses with a clear error and makes no mutation.
2. **Given** a dangling symlink for `data_vault/`, **When** a verb runs, **Then** the
   framework treats it as unavailable (US3 refusal), never as an empty vault.

---

### Edge Cases

- **External location missing / volume unmounted / dangling symlink** → loud refusal, no
  mutation (US3). Must never be read as "empty vault, start fresh".
- **External location is read-only** → refusal on write verbs with a clear message.
- **Principle X**: a note mutation must still produce append-only git history — the spec is
  not viable if relocation silently drops vault commits.
- **Portability**: an external path valid on one machine may not exist on another → the
  layout must be reproducible/documented and fail loud rather than silently diverge.
- **`git clean` / path resolution** following the symlink must not escape and delete
  unintended files.

## Requirements *(mandatory)*

> These requirements describe the *target* behaviour. **FR-003 is the gating requirement**
> — if it cannot be satisfied, the feature does not proceed.

### Functional Requirements

- **FR-001**: The framework MUST allow a vault's `data_vault/` content to physically reside
  **outside the vault root**, configured **explicitly** (not inferred).
- **FR-002**: Every framework verb MUST resolve the relocated data location
  **transparently** — read/write behaviour identical to an in-root `data_vault/`.
- **FR-003** *(gating)*: Relocation MUST **preserve Principle X** — note mutations in the
  relocated data MUST still be captured as **append-only git history**. A design that drops
  vault commits is non-viable.
- **FR-004**: If the external data location is **unavailable** (missing, unmounted, dangling
  symlink, or read-only for writes), the framework MUST **fail loudly and refuse to run**,
  making **no mutation** — never a silent partial run and never "treat as empty vault".
- **FR-005**: The relocation MUST be **recorded in the vault's control files** (which stay
  in the vault root / git), so the intended layout is discoverable and reproducible.
- **FR-006**: Relocation MUST NOT require any new runtime dependency (Principle V).

### Key Entities *(include if feature involves data)*

- **Vault root**: holds the control files (`research.spec.md`, `settings.yaml`,
  `research-backlog.md`, `coverage-targets.json`, `_pipeline/…`); stays put and git-tracked.
- **Relocated data store**: the `data_vault/` note content, physically external.
- **Location pointer**: the explicit, git-tracked record (config and/or symlink) of where
  the data lives.
- **Append-only history surface**: whatever mechanism keeps the relocated data under
  Principle X (the gating design question).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With `data_vault/` relocated outside the root, 100% of verbs behave
  identically to an in-root layout (no behavioural diff observable to the operator).
- **SC-002**: **Principle X is preserved** — every note mutation against a relocated-data
  vault produces append-only git history, verified the same way an in-root vault is.
- **SC-003**: An unavailable external location produces a clean non-zero refusal with a
  clear message and **zero** mutations/deletions (no silent partial run, no "empty vault").
- **SC-004**: The relocation is recorded in git-tracked control files such that the layout
  is reproducible and the discrepancy is detectable on a machine where the location is
  absent.

## Assumptions

- **PARKED**: pursue only when a concrete need (storage tier / encryption / sharing) makes
  the complexity worth it. This spec captures the design space ahead of that trigger.
- **Distinct from spec 044 (vault mirror)**: mirror is a *copy elsewhere*; this is the
  *primary* data living elsewhere. If the user's real need is "a copy elsewhere", 044
  already covers it without symlink complexity.
- **Hard interaction with Principle X** (spec 050 / constitution v1.4.0): keeping relocated
  data under append-only git history is the gating design question and a **prerequisite to
  `/speckit.plan`**.
- **No new runtime dependency** (Principle V).
- The control files always remain in the vault root; only the bulky note data relocates.

## Out of Scope

- Mirroring / backup to a second location (spec 044 owns that).
- Multi-machine sync of the external location (the operator's storage/sync layer owns that).
- Relocating the **control files** outside the root (they stay; only `data_vault/` moves).
- Any non-git vault story (Principle X assumes git-backed vaults).

## Blocking question for `/speckit.clarify` (must resolve before `/speckit.plan`)

How does relocated data stay under **Principle X** append-only history? Candidate
resolutions (each with different complexity/UX):

1. **External location is itself a git repo** the framework commits to (two coordinated
   repos: control-files repo + data repo). Strongest invariant; most complex.
2. **Symlink that still resolves inside one git work tree** (e.g. the work tree spans both)
   — simplest, but constrains *where* the data can live (may not satisfy the encryption /
   separate-volume need).
3. **Bind-mount / filesystem-level relocation** transparent to git (the work tree path is
   unchanged; only the underlying storage moves) — preserves Principle X for free but pushes
   complexity to the OS/storage layer and is the least portable.

Until one of these is chosen, the feature stays parked.

## Acceptance coverage

| User Story | Evidence |
|------------|----------|
| US1 — Keep the bulky data on a separate volume | _(deferred to tasks.md — PARKED pending the Principle-X decision; tests land if/when unparked)_ |
| US2 — Every verb resolves the relocation transparently | _(deferred to tasks.md — PARKED pending the Principle-X decision; tests land if/when unparked)_ |
| US3 — Fail loud when the external location is missing | _(deferred to tasks.md — PARKED pending the Principle-X decision; tests land if/when unparked)_ |
