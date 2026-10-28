# Feature Specification: Durable vault state lives in `_pipeline/state/`

**Status**: planned — specified and clarified from code evidence on
2026-10-28; three owner decisions (D-1, D-2, D-4, § Open decisions) block
`/speckit.plan`. Lands **before** `084` (D-3, agreed with `084`).

**Spec**: `083-durable-state-layout` · **Issue**: #10 · **Coordinates
with**: `084` (#18 — the research backlog becomes
`_pipeline/state/research-backlog.json` with an ignored Markdown view) and
#9 (`_pipeline/spec-parse.json` gains `spec_sha256` / `parser_version`, which
makes it a cache) · **Touches**: `050-vault-auto-commit` (Principle X
commits), `058-vault-spec-health-warning` (the control-file tracking
warning), `080-run-receipt` (`runs/` stays scratch) · **Evidence**:
[`research.md`](research.md) — the full `_pipeline/` inventory

---

## Why this spec exists

A vault's `.gitignore` (`_render_vault_gitignore`,
`src/research_framework/generator/scaffold.py:96`) ignores all of
`_pipeline/` except two files named in an allow-list,
`research-backlog.md` and `coverage-targets.json`. Which files under
`_pipeline/` survive a `git clean`, and which have history, is decided by
that list rather than by where the files live.

The inventory in `research.md` shows the list is short by six. Notes moved
to `_pipeline/quarantine/`, the ledger of sources the agents discovered
(`sources.db`), the operator's own topic rejections (`propose-rejects.md`),
each module's agent-generated facts schema, the archive.org snapshot record
and the log of operator approval decisions are all read by later commands,
none can be recomputed without spending again or asking the operator again,
and none is tracked. Three more facts a later run depends on — the next
cycle number, the lifetime spend that `--max-usd` caps (#239), and the time
since the last cycle that the yield gate uses — are not stored at all: they
are recomputed by scanning `_pipeline/cycles/`, which is ignored. After
`git clean -fdx` a 40-cycle vault restarts at cycle 1 with its lifetime
budget reset to zero.

The issue asks for one tracked directory for durable state, one ignore rule
in place of the allow-list, and an update step that moves existing vaults
without losing history. A reader with no code access must be able to tell,
for any file under `_pipeline/`, whether it is state, and to build the
migration from this document.

## Scope

**In scope**: the definition of state and the four regenerable classes
(`research.md` § The classes); the `_pipeline/state/` directory and what
goes in it; the one-rule `.gitignore`; moving every state writer and reader
to the new paths; storing the three record-derived facts as state (D-1);
the migration of existing vaults, with history, through `./vault update` and
a standalone command; a guard that keeps state from being written elsewhere.
The research backlog is **not** moved by this spec: `084` converts it
(D-3).

**Out of scope**: reorganising regenerable files into `runs/`, `cache/` or
`logs/` subdirectories (the issue gives these as examples; its definition of
done does not need them, and moving ~40 scratch writers is churn with no
behaviour change — a later spec can do it under the same ignore rule); the
research backlog's format (`084`); `spec-parse.json`'s staleness fields
(#9); retention of records (`080` FR-020 owns `runs/`); paths outside
`_pipeline/` that have the same problem (`research.md` finding 11).

---

## User Scenarios & Testing

### User Story 1 — A fresh vault tracks its state and nothing else under `_pipeline/` (Priority: P1)

An operator generates a vault, runs a few cycles and commits. They want
`git status` to show every file whose loss would change a later run, and
no file whose loss would not.

**Why this priority**: it is the issue's first done-criterion and every
other story builds on the layout it fixes.

**Independent test**: scaffold a vault, drive one fake-agent cycle, and
compare `git ls-files _pipeline/` with the state inventory.

### User Story 2 — `git clean -fdx` loses nothing a later run depends on (Priority: P1)

An operator cleans a vault (or clones it to another machine) and
reinstalls. The next research run must continue where the last one
stopped: same next cycle number, same lifetime spend counted against
`--max-usd`, same backlog, same discovered sources, same rejected topics,
same quarantined notes.

**Why this priority**: it is the issue's fourth done-criterion and the one
that cannot be met by tracking files alone (`research.md` § Behaviour
derived from records).

**Independent test**: run two fake-agent cycles, commit, `git clean -fdx`,
reinstall, start a third, and compare its inputs with an uncleaned twin.

### User Story 3 — An existing vault is migrated by `./vault update`, history intact (Priority: P1)

An operator with a vault scaffolded before this spec runs `./vault update`.
Afterwards the vault has the new layout, the previously tracked state files
keep their history under the new path, and previously untracked state
files are tracked from that commit on.

**Why this priority**: the issue's third done-criterion, and most of its
effort estimate; every live vault is an existing vault.

**Independent test**: build a vault with the legacy layout and history,
run the migration, and check paths, `git log --follow` and the commit
shape.

### User Story 4 — No command writes durable state outside `state/` (Priority: P2)

A contributor adds a new durable file under `_pipeline/`. The suite tells
them where it belongs before review does.

**Why this priority**: the issue's second done-criterion; without a guard
the allow-list's failure mode returns as a layout that drifts.

**Independent test**: the guard fails on a fixture writer that builds a
state path outside the layout module.

### User Story 5 — A vault in the old layout says so instead of half-working (Priority: P2)

An operator whose framework was upgraded without the migration (for
example, `pip install -U` instead of `./vault update`) runs a research
verb. It refuses with a message naming the command that migrates, instead
of writing new state to the new paths while old state sits unread at the
old ones.

**Why this priority**: the failure it prevents is silent — a vault that
"works" while ignoring its own backlog and spend history.

**Independent test**: run a mutating verb against a legacy-layout vault
and check the exit code and message; run `status` and check it still
reports.

### Edge Cases

- A state file exists at **both** its legacy path and its new path with
  different content (an interrupted earlier migration, or an operator
  copy) → the migration stops before moving anything, names every
  conflicting pair, exits non-zero, and changes nothing.
- Identical content at both paths → the legacy copy is removed and the
  migration proceeds.
- The vault is not a git repository, or `vault_commit.enabled: false` →
  files are moved on disk, nothing is committed, and the opt-out is logged
  at INFO (Principle X).
- The vault's `.gitignore` was customised by the operator → the migration
  adds the one re-include it needs and leaves the operator's lines alone;
  if `git check-ignore` still reports a state path as ignored afterwards,
  the migration stops and names the line that wins.
- The working tree is dirty → the migration refuses, the same way
  `./vault update` already does, unless `--force` is given.
- `sources.db` is open in WAL mode → its WAL is checkpointed before the
  database is staged; `sources.db-wal` and `sources.db-shm` are never
  tracked (if D-2 keeps the database binary).
- A run is paused (`BUDGET_PAUSED` / `APPROVAL_REQUIRED` / a runner
  `pipeline-state.json` mid-triage) when the migration runs → run-control
  files are not state and are not moved; the paused run resumes against
  the migrated state.
- `_pipeline/settings.yaml` (an operator-authored legacy override) is
  present → it is neither moved nor deleted; the migration warns and names
  the vault-root `settings.yaml` key it belongs under.
- The migration is run twice → the second run reports "already migrated"
  and changes nothing.

---

## Requirements

### Functional Requirements

**The classes and the layout**

- **FR-001**: Every file the framework writes under `_pipeline/` MUST belong
  to exactly one class — state, record, cache, run control or install
  provenance — with the meanings in `research.md` § The classes. A file is
  **state** iff a later command reads it and behaves differently without
  it, and it cannot be recomputed from tracked inputs without spending
  again (agent calls, network side effects) or without the operator's own
  input.
- **FR-002**: State MUST live under `_pipeline/state/` and nowhere else.
  The state set at this spec's ship is:

  | State | New path under `_pipeline/state/` | Legacy path under `_pipeline/` |
  | --- | --- | --- |
  | Research backlog | `research-backlog.json` — **created by `084`, not by this spec** (D-3) | `research-backlog.md` (becomes `084`'s ignored rendered view) |
  | Coverage targets | `coverage-targets.json` | `coverage-targets.json` |
  | Persistent scope rejections | `propose-rejects.md` | `propose-rejects.md` |
  | Source ledger | `sources.db` (or its text form — D-2) | `sources.db` |
  | Quarantined notes | `quarantine/` | `quarantine/` |
  | Module facts schemas | `sources/<module>/facts-schema.json` | `sources/<module>/facts-schema.json` |
  | Archive.org snapshot record | `archive-snapshots.json` | `archive-snapshots.json` |
  | Operator approval decisions | `approval-decisions.json` | `approval-decisions.json` |
  | Cycle ledger (new — D-1) | per D-1 | — (derived from `cycles/` today) |

  Everything else under `_pipeline/` keeps its current path, including
  `research-backlog.md`, which this spec neither moves nor rewrites.
- **FR-003**: A freshly scaffolded vault's `.gitignore` MUST express the
  `_pipeline/` policy as "ignore `_pipeline/` except `state/`", with no
  per-file entries, and MUST also ignore the SQLite sidecars
  (`*.db-wal`, `*.db-shm`) under `state/`.
- **FR-004**: The state paths MUST be declared once, in one module, and
  every writer and reader MUST obtain them from it. The scaffold manifest's
  user-owned patterns, `scripts/vault_health.py::CONTROL_FILE_PATHS`, the
  scout prompt template, the agent definitions and skills that name a
  state path, and the constitution's loop-continuation text MUST name the
  new paths.
- **FR-005**: A guard in the tier-2 battery MUST fail when code under
  `src/` or `scripts/` builds a path to a state artefact other than through
  the FR-004 module, and when a file the scaffold or a fake-agent cycle
  writes under `_pipeline/state/` is not in the FR-002 set.

**Record-derived facts**

- **FR-006**: The next cycle number, the lifetime spend counted by
  `--max-usd`, and the completion time of the last cycle MUST be readable
  from state alone, so that a vault with an empty `_pipeline/cycles/`
  resumes with the same values it had before. How they are stored is
  D-1. Readers that scan `cycles/` today MUST prefer the stored values and
  MAY fall back to the scan only for a vault the migration has not yet
  backfilled.
- **FR-007**: The migration MUST backfill the FR-006 facts from the
  existing `cycles/` directory, so a migrated vault does not lose them on
  its first `git clean`.

**Writers commit what they write**

- **FR-008**: Every command that writes under `_pipeline/state/` MUST leave
  that write committed by the time it exits, under the spec-050 commit
  prefixes, or MUST be covered by the run-start rule D-4 decides. A
  research run MUST NOT silently fold an uncommitted operator edit to state
  into its first cycle commit.

**Migration of existing vaults**

- **FR-009**: The migration MUST be one idempotent operation that moves
  every legacy state path present to its new path — every FR-002 row
  except the research backlog, which it MUST leave untouched for `084`'s
  conversion step — rewrites the
  `_pipeline/` stanza of `.gitignore` (FR-003), and backfills FR-006. It
  MUST support `--dry-run`, which prints the moves and the ignore-file
  change and touches nothing.
- **FR-010**: `./vault update` MUST run the migration on a vault whose shim
  predates this spec, without the shim first being regenerated. (Existing
  shims call `vault_update.sync_vault_scripts` from the newly installed
  package and then the synced `scripts/vault_health.py`; `research.md`
  finding 4.)
- **FR-011**: The migration MUST also be runnable on its own, because
  `./vault update` short-circuits when the installed version is already
  current (`research.md` finding 5). It MUST be listed in `./vault help`
  and the CLI contract table (`077`).
- **FR-012**: In a git-backed vault the migration MUST land as its own
  `framework:` commit on the base branch containing only the moves, the
  `.gitignore` change and the FR-007 backfill — no content change to a
  moved file — so that `git log --follow <new path>` reaches the file's
  first commit at its legacy path. Previously untracked state files enter
  history in that commit.
- **FR-013**: The migration MUST check every move before making any: a
  conflicting destination (Edge Cases) aborts the whole migration with
  nothing moved.
- **FR-014**: When the vault's `.gitignore` is not the shipped rendering,
  the migration MUST add only the re-include it needs and then verify with
  `git check-ignore` that every state path is tracked-eligible; if not, it
  MUST stop and name the winning rule.

**The old layout after this spec ships**

- **FR-015**: A command that writes state MUST refuse, with exit code 2 and
  a message naming the migration command, when it finds state at a legacy
  path and the vault is not migrated. It MUST NOT read the legacy path as a
  fallback.
- **FR-016**: Read-only verbs (`status`, `status --json`, `health` without
  `--apply`) MUST NOT refuse: they report "legacy `_pipeline/` layout —
  run `<migration command>`" and otherwise behave as before (`077`'s
  fail-open rule for `status`).
- **FR-017**: `scripts/vault_health.py`'s control-file tracking check
  (spec 058) MUST check the state directory instead of the two legacy
  files.

**Ordering with `084`**

- **FR-018**: The update-time migration MUST be an ordered list of
  idempotent steps that this spec creates with one step (the layout move)
  and that `084` extends with its backlog conversion, ordered after it.
- **FR-019**: Because the FR-003 rule ignores `_pipeline/research-backlog.md`
  as soon as this spec ships, this spec MUST NOT reach a release tag
  without `084`, **or** its `.gitignore` rendering and migration MUST carry
  one transitional `!_pipeline/research-backlog.md` re-include that `084`
  removes. Without one of the two, a vault scaffolded in the window between
  the releases never tracks its backlog. (Existing vaults are unaffected in
  the window: the file is already in their index, and git does not apply
  ignore rules to tracked files — which is also why `084`'s migration must
  drop the old `.md` from the index when it becomes a view.)

### Key Entities

| Entity | Where | Notes |
| --- | --- | --- |
| State directory | `_pipeline/state/` | tracked; FR-002 is its complete contents |
| Layout module | one module under `src/research_framework/` | FR-004; the only place a state path is spelled |
| Cycle ledger | `_pipeline/state/` (D-1) | FR-006; next cycle, lifetime spend, last completion time |
| Migration | `./vault update` step + a standalone command | FR-009…FR-014; one `framework:` commit |
| `.gitignore` `_pipeline/` stanza | vault root | FR-003; one re-include instead of an allow-list |

## Success Criteria

- **SC-001**: After `git clean -fdx` and a reinstall, a vault's next
  research run starts at the same cycle number, counts the same lifetime
  spend, and reads the same backlog, sources, rejections and quarantine as
  an uncleaned copy.
- **SC-002**: The `_pipeline/` part of a vault's `.gitignore` is the same
  for every vault and does not change when a durable file is added.
- **SC-003**: Every live vault is migrated by one `./vault update`, and the
  history of its two previously tracked state files is unbroken.
- **SC-004**: Adding a durable file outside `state/` fails the suite, not a
  review.

---

## Acceptance

Flat-bullet form (ADR-0012: not guard-enforced; each bullet names the story
it evidences). Test paths are fixed by `tasks.md`.

- **US1** — A vault scaffolded by this version, after one fake-agent cycle
  and a commit, has `git ls-files _pipeline/` equal to the FR-002 paths
  that exist, and `git status --ignored` lists every other `_pipeline/`
  file as ignored.
- **US1** — The scaffolded `.gitignore` names no file under `_pipeline/`.
- **US2** — Two fake-agent cycles, a commit, `git clean -fdx`, a
  reinstall: the third run's resume anchor is cycle 3, its lifetime spend
  equals the uncleaned twin's, and its scout prompt's exclusions, backlog
  and discovered sources are byte-identical to the twin's.
- **US2** — `./vault re-grade` on the cleaned vault finds the quarantined
  notes the twin finds.
- **US3** — A legacy-layout vault with a tracked `research-backlog.md` and
  `coverage-targets.json`, after the migration: every FR-002 legacy path
  except the backlog is absent, every new path exists with identical bytes,
  `_pipeline/research-backlog.md` is byte-identical and still in the index,
  and
  `git log --follow --format=%H _pipeline/state/coverage-targets.json`
  ends at the commit that first added `_pipeline/coverage-targets.json`.
- **US3** — The migration commit's diff contains only renames, additions of
  previously untracked state, the `.gitignore` change and the ledger
  backfill (`git show --stat -M` shows every tracked move as a 100 %
  rename).
- **US3** — Running the migration a second time reports "already
  migrated", exits 0 and creates no commit.
- **US3** — A conflicting destination aborts with exit 2, names the pair,
  and leaves the tree byte-identical.
- **US3** — `./vault update` driven through a shim rendered by the previous
  release migrates the vault.
- **US3** — `--dry-run` prints every move and the ignore-file change and
  leaves the tree byte-identical.
- **US4** — The FR-005 guard fails on a planted
  `vault / "_pipeline" / "propose-rejects.md"` in a fixture module and
  passes on the tree.
- **US5** — `research` / `cycle` / `pipeline full` on a legacy-layout vault
  exit 2 with a message naming the migration command, before any agent is
  dispatched; `status --json` on the same vault exits 0 and carries the
  legacy-layout notice.

---

## Known divergences

Recorded from the code at `bc39eae`, not fixed here unless an FR says so.

- **D1 — The allow-list misses six of eight state artefacts**
  (`research.md` § S). FR-002 is the fix.
- **D2 — Three behaviours read records.** Resume numbering, the lifetime
  cap and the yield cadence scan `cycles/` (`research.md` § Behaviour
  derived from records). FR-006 / D-1.
- **D3 — Nothing rewrites a vault's `.gitignore` after scaffold.** The
  manifest marks it framework-owned, but `scaffold()` writes it only when
  absent and `apply_vault_scaffold_update` has no caller. FR-009 rewrites
  the one stanza this spec owns; a general ignore-file refresh is not
  added.
- **D4 — `begin_run` masks all of `_pipeline/` in its dirty check.**
  Operator edits to tracked state are co-mingled with framework output.
  D-4.
- **D5 — `rejects.json` is read and never written.** `research_plan.py`
  excludes topics from it and `reports/flagged_issues.py` reports from it;
  no writer exists. Not state until something writes it; when something
  does, FR-002 puts it under `state/`.
- **D6 — `_pipeline/settings.yaml` is operator configuration in an ignored
  directory**, read by `source_manager._decay_threshold` as a "holdout".
  Edge Cases: warned about, not moved. Folding it into the vault-root
  `settings.yaml` belongs to `076`.
- **D7 — `cycle-NNN-skill-check.json` is written beside `cycles/`, not in
  it** (40 files at the root of a 40-cycle vault). A record either way;
  left for the scratch reorganisation this spec puts out of scope.
- **D8 — Spec 050 places `run-commit-state.json` in `_pipeline/`**; the
  code keeps it under `.git/` on purpose. The spec text is stale; the code
  is right and is not touched.
- **D9 — `budget-log.md` is a record that a precondition requires.**
  `preconditions.py` refuses a run when it is missing (precondition 4),
  so a `git clean` blocks the next run until a reinstall re-scaffolds it.
  If D-1 adopts a ledger, the precondition should require the ledger
  instead and `budget-log.md` becomes its rendering.

---

## Clarifications

### Session 2026-10-28 (resolved from code evidence, no owner input needed)

- Is `approval-decisions.json` state or a record? → **State.** It is the
  only record of a human decision (`budget_guard.record_approval_decision`),
  and Principle X exists to make such decisions replayable; it is small and
  append-only.
- Is `quarantine/` state, given the notes were tracked under the corpus
  before they were moved? → **State.** `./vault re-grade` reinstates from
  the directory, not from history; tracked, the quarantine move becomes a
  rename in history instead of a deletion.
- Are module watermarks state? → **Cache.** They make re-extraction
  cheaper and drive a WARN-only stagnant-source signal (`069`); losing them
  costs a re-extraction, not a wrong result (ADR-0006).
- Are pause markers and `pipeline-state.json` state? → **Run control.**
  Their loss restarts a paused run from its beginning and re-checks the
  caps (`budget_resume.py`), which is safe; tracking them would commit a
  half-run.
- Is install provenance (`.tmpl-versions.json`, `shim-fingerprint.json`,
  `scaffold-manifest-snapshot.json`, `install_summary.json`) state? →
  **No.** `git clean -fdx` already deletes the shim, `scripts/` and
  `.venv/`, so a reinstall is required and rewrites all four. Where a
  `.tmpl-versions.json` sibling describes a moved file, it follows the file
  into `state/`.
- Do records count against "loses nothing that cannot be regenerated"? →
  **No.** The issue names `_pipeline/runs/` as ignored scratch, and runs
  are records; SC-001 restates the criterion as "nothing a later run
  depends on", and FR-006 removes the one place a later run depended on a
  record.
- Should old paths stay readable as a fallback? → **No** (FR-015). A dual
  read hides an unmigrated vault and keeps two spellings of every path
  alive; refusing with exit 2 (`077`: abort, operator must act) is the
  fail-fast choice, and read-only verbs stay fail-open (FR-016).
- Scratch reorganisation into `runs/` / `cache/` / `logs/`? → **Out of
  scope** (§ Scope). Owner may overrule; it would add one decision about
  the `cycles/` tree and roughly double the change.

---

## Open decisions

Each open one is marked `[NEEDS DECISION]`. Recommendations are the spec
author's, not decided.

- **D-1 — How the record-derived facts become state.** [NEEDS DECISION]
  (a) A new `_pipeline/state/cycle-ledger.json`, one row appended when a
  cycle closes (`cycle`, `finished_at`, `cost_usd`, `sidecars_missing`);
  resume, the lifetime cap and the yield cadence read it; the migration
  backfills it from `cycles/`. (b) Track `cycles/cycle-NNN/agent-calls/`
  and `cycle-NNN-research.json` instead (~35 files per cycle, 1 435 today
  in a 40-cycle vault). (c) Accept the reset and document it.
  **Recommended: (a)** — one small diffable file, and the lifetime cap is a
  spend control (#239) that should not depend on scratch.
- **D-2 — `sources.db` in git.** [NEEDS DECISION] (a) Track the SQLite
  file itself under `state/`, checkpointing its WAL before staging and
  ignoring the `-wal`/`-shm` sidecars (45 kB after 40 cycles; history is
  opaque binary; a research-branch merge conflict on it cannot be
  resolved by hand). (b) Keep the database as an ignored cache and track a
  text export (`state/sources.jsonl`) it is rebuilt from when absent
  (diffable, mergeable; an exporter, an importer and a consistency rule to
  write). (c) Classify it as a record and accept losing discovered
  sources. **Recommended: (a)** for this spec — smallest change that meets
  the definition of done; (b) as a follow-up if binary history proves a
  problem (one writer, sequential runs, so conflicts are unlikely).
- **D-3 — Sequencing with `084` (the backlog).** **Resolved 2026-10-28
  with `084`'s author**: `083` lands first, then `084`. `084` converts
  `_pipeline/research-backlog.md` into the tracked
  `state/research-backlog.json` (copying the original `.md` byte-for-byte
  into `state/` on first migration, since pre-2026-08-27 vaults never
  tracked it) and renders the `.md` as an ignored view, so agent prompts
  keep their path. `083`'s single ignore rule already ignores that view;
  `083`'s migration leaves the backlog alone (FR-009) and creates the
  ordered step list `084` extends (FR-018). Residual constraint: the
  release window (FR-019).
- **D-4 — Uncommitted state edits when a research run starts.** [NEEDS
  DECISION] (a) Status quo: `begin_run` keeps masking `_pipeline/`, and an
  operator's uncommitted state edit is folded into the first cycle commit.
  (b) Unmask `state/`: a dirty state file refuses the run (exit 2) like any
  dirty corpus file; every state writer must then commit (FR-008), and any
  that does not — `./vault health --apply` writing
  `archive-snapshots.json` does not today — blocks unattended runs.
  (c) Before branching, `begin_run` commits pending `state/` changes on the
  base branch as their own `vault: pending state` commit, then proceeds.
  **Recommended: (c)** — operator edits get their own reversible commit
  (Principle X), and no unattended run is blocked by a forgotten commit.

## Assumptions

- `084` and #9 are specified in parallel; this spec relies only on what
  their issues state (backlog → `state/research-backlog.json` with an
  ignored rendered view; `spec-parse.json` is a cache). If either changes
  that, FR-002's table changes with it.
- One run is active per vault at a time (`075` § Assumptions); the
  migration takes no lock and refuses on a dirty tree.
- Live vaults are git repositories (Principle X); the non-git path exists
  for completeness and for test fixtures.
- Fake-agent cycles (`tests/_helpers/fake_agent.py`) write every state
  artefact the acceptance bullets need; where one does not (archive
  snapshots need `health --apply`; facts schemas need a code-bridge
  module), the test writes it through the same writer the framework uses.
