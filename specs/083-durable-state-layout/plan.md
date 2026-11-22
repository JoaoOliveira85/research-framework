# Implementation Plan: Durable vault state lives in `_pipeline/state/`

**Spec**: [`spec.md`](spec.md) · **Evidence**: [`research.md`](research.md)
(inventory taken at `bc39eae`; re-checked against `1961f9a`, v2.0.1, on
2026-11-22 — the eight state artefacts and the three record-derived readers
are where the inventory says, line numbers moved) · **Tasks**:
[`tasks.md`](tasks.md)

## Summary

Move seven of the eight state artefacts under `_pipeline/state/` (the
backlog waits for `084`), add the cycle ledger, replace the `.gitignore`
allow-list with one re-include, migrate existing vaults in one `framework:`
commit, and refuse to run on an unmigrated vault. No behaviour changes for a
migrated vault except the three facts that used to reset with `cycles/`.

## Technical context

- Python 3.11+, stdlib + `pyyaml` + `jinja2` only (Principle V: no new
  dependency). `sqlite3` and `git` are already used.
- Size at `1961f9a`: about 40 files under `src/` and `scripts/` name a state
  path; about 100 test files do (60 for `coverage-targets.json` alone). Most
  of the diff is path substitution; the new logic is the layout module, the
  ledger, the run-start commit, the migration and the guard.
- Vault-local `scripts/` already import `research_framework` (the vault's
  venv has it), so they can use the layout module.

## Constitution check

| Principle | How this plan meets it |
| --- | --- |
| I — script-validated gates | The migration verifies with `git check-ignore`; the guard is a script in the battery. No model decides anything here. |
| III — test-first | Every task in `tasks.md` carries its tests, authored before implementation. |
| V — no new dependency | stdlib only. |
| X — append-only git | The migration is one `framework:` commit of renames; pending state edits get their own commit (D-4); nothing is rewritten. |
| XII — inspection does not mutate | `status` and `health` (without `--apply`) only report the legacy layout; `--dry-run` touches nothing. |
| XIII — nothing accepted and ignored | A legacy vault is refused with exit 2 by every state-writing verb, never half-read. |

## Design decisions

1. **One layout module**: `src/research_framework/pipeline/state_layout.py`.
   It holds `STATE_DIR` (`_pipeline/state`), one accessor per artefact
   (`coverage_targets_path(vault)`, `propose_rejects_path`,
   `sources_db_path`, `quarantine_dir`, `facts_schema_path(vault, module)`,
   `archive_snapshots_path`, `approval_decisions_path`,
   `cycle_ledger_path`), and a registry `STATE_ARTEFACTS` of
   `(name, new_rel, legacy_rel, kind)` rows that the migration, the guard,
   the health check and the scaffold manifest all read. It is the only file
   allowed to spell a state path (FR-004, FR-005).
2. **`.gitignore` stanza** (FR-003, FR-019):

   ```gitignore
   !_pipeline/
   _pipeline/*
   !_pipeline/state/
   _pipeline/state/*.db-wal
   _pipeline/state/*.db-shm
   # Transitional until spec 084 converts the backlog; 084 removes this line.
   !_pipeline/research-backlog.md
   ```

   The last line is FR-019's transitional re-include, chosen over holding
   the release: `084` is a separate change, and without the line a vault
   scaffolded between the two never tracks its backlog.
3. **Cycle ledger**: `src/research_framework/pipeline/cycle_ledger.py`, a
   JSON document `{"schema_version": 1, "cycles": [{"cycle", "finished_at",
   "cost_usd", "sidecars_missing"}]}` written atomically when a cycle closes
   (the point where `orchestrator._append_budget_log` runs today). Readers:
   `cli/research_resume._resolve_resume_cycle`,
   `orchestrator._cumulative_sidecar_cost`,
   `coverage._hours_since_last_cycle`. **Rule**: the ledger is authoritative
   for the cycles it lists; the `cycles/` scan supplies only cycles the
   ledger lacks (a cycle that crashed before its row was written, or a vault
   not yet backfilled). Next cycle = `max(ledger, scan) + 1`.
4. **`sources.db`**: tracked as a file. One helper checkpoints the WAL
   (`PRAGMA wal_checkpoint(TRUNCATE)`) before any commit that stages it; the
   two sidecars are ignored by the stanza above.
5. **Run start (D-4)**: `vault_commit.begin_run` stops masking
   `_pipeline/state/`. Before it branches, if `git status --porcelain --
   _pipeline/state` is non-empty it commits those paths on the base branch
   as `vault: pending state`. The rest of `_pipeline/` stays masked.
6. **Migration**: `src/research_framework/pipeline/layout_migration.py`
   exposes `MIGRATION_STEPS`, an ordered list of idempotent steps (FR-018);
   this spec adds one, `move_state_into_state_dir`. A step has `plan(vault)`
   (returns moves, conflicts, the ignore-file change, the backfill) and
   `apply(plan)`. Tracked files move with `git mv`; untracked ones are moved
   and added. All moves are checked before any is made (FR-013). The whole
   thing lands as one `framework: migrate _pipeline layout` commit
   (FR-012). A customised `.gitignore` gets only the re-include, then
   `git check-ignore` decides (FR-014).
7. **Entry points** (FR-010, FR-011): a CLI verb `research-framework
   migrate-layout <vault> [--dry-run] [--force]`, exposed as `./vault
   migrate-layout`; and a call from `vault_update.sync_vault_scripts`, the
   one post-upgrade hook every existing shim already runs, so a vault whose
   shim predates this spec is still migrated by `./vault update`.
8. **Legacy detection** (FR-015, FR-016): a vault is legacy when any legacy
   state path other than the backlog exists on disk.
   `state_layout.require_migrated(vault)` raises a typed error that the
   state-writing verbs turn into exit 2 with the command to run; `status`
   and `health` print the notice and carry on.
9. **Guard** (FR-005): `scripts/guards/state_paths.py`, in `run_all.py`,
   fails on any string literal naming a state artefact's basename under
   `src/` or `scripts/` outside the layout module; a tier-2 test plants one
   to prove it fires. A tier-5 test asserts a fake-agent cycle leaves
   nothing under `_pipeline/state/` that is not in the registry.
10. **Precondition 4** (spec D9): require the cycle ledger's directory, not
    `budget-log.md`; the log is re-created when missing.

## What is not done here

The backlog (084), the scratch reorganisation, `_pipeline/settings.yaml`
(warned about, 076 owns it), `rejects.json` (no writer exists).

## Order and risk

Tasks T001–T006 are path moves with no behaviour change and can be reviewed
as renames. T007–T009 change behaviour (ledger, run start). T010–T012 are
the migration and the refusal, which every live vault will go through once:
they are rehearsed on copies of real vaults before release (T015). The
release that carries this needs a `### Migration notes` block: one
`./vault update` (or `./vault migrate-layout`) per vault, on a clean tree.
