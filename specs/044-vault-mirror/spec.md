# Feature Specification: Vault Mirror

**Feature Branch**: `044-vault-mirror`
**Created**: 2026-05-27 (promoted from `docs/ROADMAP.md` Horizon 2 "Vault mirror" during post-Wave-1 doc restructure).
**Status**: planned — DRAFT (full spec; awaiting `/speckit.clarify` on 3 open questions). Standalone — small, useful, easy. Can ship as a single PR whenever a small-task window opens.

**Input**: A cycle-end hook that optionally `rsync -a --delete`s the vault tree to a configured destination (a cloud-synced folder, a NAS, another machine). Read-only mirror — nothing reads back from it. Users running unattended cycles want a second-location copy of their vault for backup, for reading on another device (iPad via iCloud Drive, phone via Google Drive Desktop), or for collaborative access via a NAS. Today they have to set up their own cron job; the framework doesn't offer this natively despite being one of the more-requested operator features. Distinct from spec 040's REPORT mirror — this spec mirrors the FULL VAULT TREE.

## Clarifications

### Pending — `/speckit.clarify` session TBD

- **Q1 (FR-005)**: Should the default `exclude` list include `_pipeline/` entirely (mirror is for human-readable notes, not pipeline internals), or just exclude the SQLite WAL/SHM files? Default proposed: SQLite WAL/SHM + `.git/objects/pack/tmp-*` + `_pipeline/cache/`. Keep `_pipeline/cycles/`, `_pipeline/digests/`, `_pipeline/sources.db` (the steady-state SQLite, not WAL/SHM) in the mirror — they're operator-readable artifacts.
- **Q2 (FR-009)**: How loud should mirror failures be? Currently proposed: log a warning + non-blocking. Should `./vault health` ALSO surface a stale-mirror warning if the mirror timestamp is >N days older than the vault? Default proposed: yes — 7-day staleness threshold; configurable via `mirror.staleness_warn_days`.
- **Q3 (FR-013)**: Should this support multiple mirror targets (e.g. iCloud + a NAS simultaneously), or is one target enough for v1? Default proposed: ONE target for v1; multi-target is a v2 spec if requested.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Vault mirror to iCloud Drive enables iPad reading (Priority: P1)

The operator runs unattended cycles on their MacBook. They want to read the vault on iPad. They set `mirror.target: /Users/me/iCloud Drive/feeds-vault-mirror` in `settings.yaml`. At each cycle end, the vault tree is rsync'd to that location; iCloud's Files app syncs it; iPad reads it via Obsidian Mobile pointing at the iCloud-synced folder.

**Why this priority**: This is the FLAGSHIP use case. It unlocks cross-device reading without setting up a server. The 2026-05-15 trial-run operator specifically named "can't read on iPad" as a friction point.

**Independent Test**: Set `mirror.target: /tmp/test-mirror` on a fixture vault. Run a cycle. Verify: `/tmp/test-mirror/<note-files>` exist after cycle end with matching content; subsequent cycles update the mirror; deleted notes in source are also deleted in the mirror.

**Acceptance Scenarios**:

1. **Given** `settings.yaml::mirror.target: /tmp/test-mirror`, **When** a cycle completes, **Then** `/tmp/test-mirror/` contains every note file from the source vault with matching content.
2. **Given** the operator deletes a note in the source vault, **When** the next cycle runs, **Then** the corresponding file is deleted from the mirror (rsync `--delete` semantics).
3. **Given** `mirror.target` is unset (default), **When** a cycle completes, **Then** no mirror operation runs, no log line is emitted (silent noop).
4. **Given** the mirror target is unavailable (network mount disconnected), **When** the cycle completes, **Then** the cycle exits successfully + a warning is logged ("mirror skipped: target unreachable") — cycle is NOT failed.

---

### User Story 2 — Mirror excludes pipeline noise (Priority: P2)

The operator's mirror lives in iCloud — they want notes + readable artifacts (cycle reports, digests), NOT SQLite WAL/SHM files that change every cycle (which would burn iCloud sync bandwidth for zero readable value). The default exclude list ships sensible exclusions.

**Why this priority**: Without sensible defaults, users discover the noise problem only after their iCloud is mid-sync forever. Defaults matter.

**Independent Test**: Run a cycle on a vault with `_pipeline/sources.db-shm` + `_pipeline/sources.db-wal` present. Verify: the mirror does NOT contain those files; verify the mirror DOES contain `_pipeline/sources.db` (the steady-state SQLite).

**Acceptance Scenarios**:

1. **Given** the default `mirror.exclude` list, **When** a cycle mirrors, **Then** `_pipeline/sources.db-shm` / `-wal` are NOT in the mirror.
2. **Given** the default exclude list (Q1's default: SQLite WAL/SHM + cache), **When** a cycle mirrors, **Then** `_pipeline/cycles/cycle-N-report.md` IS in the mirror (operator-readable artifact).
3. **Given** an operator adds a custom path to `mirror.exclude`, **When** a cycle mirrors, **Then** that path is excluded.

---

### User Story 3 — Mirror staleness surfaces via `./vault health` (Priority: P2)

The operator's iCloud Drive was offline for 10 days (laptop didn't run). When they reconnect and run `./vault health`, a warning surfaces: `mirror staleness: 10 days since last successful sync (threshold: 7d). Consider running ./vault research to refresh.`

**Why this priority**: Silent staleness is the worst failure mode — operator believes the mirror is current when it's not. Health-check surfacing is the cheap fix.

**Acceptance Scenarios**:

1. **Given** a mirror that hasn't been refreshed in >7 days, **When** the operator runs `./vault health`, **Then** a "mirror stale" warning fires.
2. **Given** a fresh mirror (refreshed in last 7 days), **When** `./vault health` runs, **Then** no mirror-staleness warning fires (no spurious noise).
3. **Given** `mirror.target` is unset, **When** `./vault health` runs, **Then** no mirror-related warning fires at all.

---

### User Story 4 — Non-blocking mirror failures (Priority: P3)

The operator runs a cycle while connected to a flaky network. The mirror target (a NAS) becomes unreachable mid-rsync. The cycle exits successfully — only a warning is logged. The next cycle re-attempts and succeeds.

**Why this priority**: Cycle success should NEVER hinge on mirror availability. The mirror is a convenience, not a contract.

**Acceptance Scenarios**:

1. **Given** the mirror target is unreachable mid-rsync, **When** the cycle finishes, **Then** the cycle exit code is 0 + a warning is logged.
2. **Given** the next cycle starts with the mirror target available again, **When** it runs, **Then** the mirror catches up successfully — no manual intervention.

---

### Edge Cases

- What if the operator edits a note IN the mirror location? → The edit is clobbered on the next cycle (by design; mirror is read-only / one-way). Document this clearly.
- What if `rsync` itself isn't installed on the host? → Per spec 039 FR-005 default, rsync is a WARN-level dep. Mirror exits non-zero on first attempt with "rsync not found; install via..." then disables itself for the cycle.
- What if the mirror target has insufficient disk space? → rsync fails partway; log the rsync exit code + bytes-written; non-blocking.
- What if `mirror.target` is set to a path inside the vault itself (recursive)? → Detect at startup + refuse with "mirror.target is inside vault root; would cause recursion".
- What if the mirror target is on a network drive that requires authentication? → That's the OS's problem (mount it before the cycle runs); mirror is just rsync.
- What if two cycles' mirrors overlap (long-running cycle, fast-firing schedule)? → Each cycle's rsync is sequential; second cycle's mirror runs after first one completes.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A new `mirror.target: <path>` setting MAY be set in `settings.yaml`. Unset → mirror disabled (default).
- **FR-002**: When `mirror.target` is set, the framework MUST execute `rsync -a --delete <vault_root>/ <target>/` at cycle end (note trailing slashes — rsync's directory semantics matter).
- **FR-003**: `rsync` is a HARD dependency probed by `install.sh` (per spec 039 FR-005). When mirror is enabled but `rsync` is unavailable, mirror is disabled for the cycle with a clear warning.
- **FR-004**: A `mirror.delete: <bool>` setting MAY override the `--delete` behavior (default: true). When false, deleted source files persist in the mirror (additive-only).
- **FR-005**: A `mirror.exclude: [<pattern>, ...]` setting MAY list patterns to exclude from the mirror. Per Q1's default, ships with: `_pipeline/sources.db-shm`, `_pipeline/sources.db-wal`, `_pipeline/cache/`, `.git/objects/pack/tmp-*`. Operator-supplied entries APPEND to the defaults (not replace).
- **FR-006**: Mirror operations MUST be logged in the cycle report: `mirror_status` field with values `succeeded` (with byte-count + duration), `skipped` (with reason), `failed` (with exit code + stderr excerpt).
- **FR-007**: Mirror failures MUST be non-blocking — the cycle exit code MUST NOT reflect mirror status. Mirror is a convenience, not a contract.
- **FR-008**: Mirror operations MUST update a `_pipeline/mirror-state.json` file with: `last_attempt_at` (ISO8601), `last_success_at`, `last_target`, `last_bytes_transferred`. Used for staleness detection.
- **FR-009**: `./vault health` MUST read `_pipeline/mirror-state.json` and surface a "mirror stale" warning when `last_success_at` is >`mirror.staleness_warn_days` (default 7) ago. When `mirror.target` is unset, NO mirror-related output appears.
- **FR-010**: Mirror MUST refuse to run when `mirror.target` is inside the vault root (recursive case) — exit non-zero with "mirror.target inside vault root; would cause recursion". Detected at cycle start, before any rsync invocation.
- **FR-011**: Mirror MUST refuse to run when `mirror.target` is the vault root itself — same recursion-detection.
- **FR-012**: Mirror MUST be silent when disabled (`mirror.target` unset) — no log line, no warning, no health-check output.
- **FR-013**: Per Q3, v1 supports ONE `mirror.target`. Multi-target is a v2 spec if requested.

### Key Entities

- **`mirror.target` setting**: Optional filesystem path in `settings.yaml`. The destination for the vault tree mirror.
- **`mirror.delete` / `mirror.exclude` / `mirror.staleness_warn_days` settings**: Tuning knobs in `settings.yaml`. Defaults chosen to be sensible for cloud-sync folders.
- **`rsync` invocation**: A subprocess call at cycle end: `rsync -a --delete <vault_root>/ <target>/` with `--exclude` flags appended per the merged exclude list.
- **`_pipeline/mirror-state.json`**: A persistent state file tracking the last mirror attempt + last success. Used by `./vault health` for staleness detection.
- **Cycle-report `mirror_status` field**: A structured JSON field in the cycle report capturing `status` + `bytes_transferred` + `duration_ms` + `error` (if any).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After this spec ships, the 2026-05-15 trial-run operator's "can't read on iPad" friction is resolved: setting `mirror.target` + adding the path to iCloud's Obsidian Vault list works end-to-end.
- **SC-002**: Mirror operations complete in <30 seconds for an feeds-vault-sized vault (~500 notes, ~50MB) on the first run; <5 seconds on incremental subsequent runs (only changed files transferred).
- **SC-003**: 0 cycles fail because of mirror errors (mirror failures are non-blocking per FR-007).
- **SC-004**: When `mirror.target` is unset (default), zero log lines / warnings / health-check outputs reference mirror — the feature is invisible until opted into.

## Assumptions

- `rsync` is available on macOS (stock BSD 2.6.9) and every major Linux distro. Spec 039's `install.sh` advises operators when it's missing.
- Cloud-sync clients (iCloud Drive, Google Drive Desktop, Dropbox) handle the actual sync from a filesystem path. We mirror to a path; we don't talk to cloud APIs.
- Operators want ONE mirror target in v1 (per Q3). Multi-target is a v2 problem if it materializes.
- The mirror is read-only from the operator's perspective. Edits in the mirror are clobbered on the next cycle — documented behavior, not a bug.

## Dependencies

- **Hard**: Spec 039 (installer hardening) — `rsync` dep probe lives there.
- **Soft**: Spec 042 (autonomous-mode backend defaults) — unattended cycles need a backup path, mirror is a natural fit.
- **Soft**: Spec 035 (cross-cycle digest) — digests in `_pipeline/digests/` are mirrored by default (operator-readable artifacts).
- **Soft**: Spec 040 (vault reports + delivery) — has its own narrower "reports.mirror" for just the reports; this spec is the FULL VAULT mirror, complementary not overlapping.

## Acceptance coverage

Draft — evidence cells populated by `/speckit.tasks` after `/speckit.clarify`.

| User Story | Evidence |
|---|---|
| US1 — Vault mirror to iCloud Drive enables iPad reading | _(deferred to tasks.md — pending /speckit.clarify on open Q1/Q2/Q3)_ |
| US2 — Mirror excludes pipeline noise | _(deferred to tasks.md — pending /speckit.clarify on open Q1/Q2/Q3)_ |
| US3 — Mirror staleness surfaces via `./vault health` | _(deferred to tasks.md — pending /speckit.clarify on open Q1/Q2/Q3)_ |
| US4 — Non-blocking mirror failures | _(deferred to tasks.md — pending /speckit.clarify on open Q1/Q2/Q3)_ |

## Out of Scope

- Bidirectional sync (Dropbox-style two-way). Mirror is one-way.
- Conflict resolution. If user edits in the mirror location, those edits are clobbered on the next cycle (by design).
- Cloud-provider-specific APIs (Google Drive API, Dropbox API, S3). Mirror writes to a filesystem path; the cloud provider's desktop client handles the sync.
- Encrypted backup (PGP / age-encrypted mirrors). Out of v1; see "eventually parked" items in ROADMAP.
- Multi-target mirrors (per Q3). v1 = one target.
- Git-worktree-based "mirrors" — explicitly rejected per the stub's Section D rationale (worktrees share `.git`, don't auto-sync, wrong tool for "readable copy elsewhere").

---

*Promote to active queue by running `/speckit.clarify` against this draft; the three pending clarifications (Q1-Q3) gate the promotion to `IMPLEMENTABLE`. Standalone — can ship anytime an open-task window appears.*
