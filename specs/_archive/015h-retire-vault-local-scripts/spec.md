# Feature Specification: Retire Vault-Local Scripts

**Feature Branch**: `015h-retire-vault-local-scripts` *(proposal — not yet branched)*
**Parent**: [015 — Pipeline Consolidation](../015-pipeline-consolidation/spec.md), Stage 5 (final)
**Created**: 2026-05-13
**Status**: shipped(2026-05-21, commit e73b6de) — SHIPPED — the `superseded_paths.py` mechanism (`src/research_framework/migration/superseded_paths.py`) that retires vault-local scripts is in-tree. Dependencies (014 / 015e / 015f / 015g) all resolved. Header flipped 2026-06-01 (ROADMAP QW-7).

## Problem

Once stages 014, 015e, 015f, 015g have all landed, every meaningful
piece of the research loop lives in the framework:

- Collectors → `research_vault.collectors` (014).
- Agent definitions → `research_vault.agents` templates rendered
  into `.claude/commands/` (015e).
- Processors → `research_vault.processors` (015f).
- Orchestrator → `research_vault pipeline …` (015g).

At that point, the vault-local `scripts/*.py` files (originally
~4,300 lines in feeds-vault, ~2,000 in codebase-vault) are
**duplicate** of the framework code. They worked when the framework
had no equivalent; they're dead weight now.

This spec proposes:

1. Detecting the dead weight via `research_vault inventory`.
2. Adding an opt-in `migrate apply --prune` flag that removes
   manifest-superseded paths.
3. Documenting the per-vault retire procedure (commit local
   changes, opt into framework versions, run `--prune`, verify
   pipeline still works).

## Goals

1. **No surprise deletions.** `--prune` is opt-in, named explicitly,
   and lists every path it would delete before doing so.
2. **Per-script granularity.** The user can retire `extract.py`
   while keeping a custom `collect_*.py` they don't want
   promoted yet.
3. **Rollback exists.** The migrator's snapshot-commit boundary
   already gives `git reset --hard HEAD~2` rollback; `--prune`
   uses the same plumbing.

## Non-goals

- **Not** automatic. The user explicitly invokes `--prune` per
  vault.
- **Not** a forced retirement timeline. Vaults can keep their
  local scripts indefinitely; pruning is a feature, not a policy.
- **Not** retirement of vault-customised `.claude/commands/*.md`.
  Those stay user-owned forever; this spec only retires *scripts*
  that the framework has superseded.

## User scenarios

### Story 1 — Audit before pruning

```bash
$ research_vault inventory ~/Documents/feeds-vault --format=text | grep -A20 "Pruneable"

Pruneable (framework now supersedes these):
  scripts/collect_rss.py           — framework has research_vault.collectors.rss
  scripts/collect_youtube.py       — framework has research_vault.collectors.youtube
  scripts/reddit_rss.py            — framework has research_vault.collectors.reddit
  scripts/extract.py               — framework has research_vault.processors.extract
  scripts/verify.py                — framework has research_vault.processors.verify
  scripts/preprocess.py            — framework has research_vault.processors.preprocess
  scripts/archive.py               — framework has research_vault.processors.archive

To remove these:
  research_vault migrate ~/Documents/feeds-vault apply --prune
```

The inventory grows a "Pruneable" section that lists local scripts
where a framework equivalent now exists. The mapping
`scripts/<name>.py → research_vault.<module>.<submodule>` is a
table in the framework, updated as new modules ship.

### Story 2 — Prune

```bash
$ research_vault migrate ~/Documents/feeds-vault apply --prune

[migrator] About to delete 7 vault-local files superseded by framework modules:
  scripts/collect_rss.py
  scripts/collect_youtube.py
  scripts/reddit_rss.py
  scripts/extract.py
  scripts/verify.py
  scripts/preprocess.py
  scripts/archive.py
Proceed? [y/N] y

[migrator] pre-apply snapshot   → committed (includes the prune subjects so HEAD~1 restores them)
[migrator] applying scaffold changes …
[migrator] pruning superseded scripts:
  rm scripts/collect_rss.py
  rm scripts/collect_youtube.py
  ...
[migrator] post-apply snapshot → committed

Pipeline check:
  $ research_vault pipeline ~/Documents/feeds-vault status
  → status reads cleanly. Pipeline operational with framework modules.

Done. Rollback: git -C ~/Documents/feeds-vault reset --hard HEAD~2
```

### Story 3 — Mixed retirement

```bash
$ research_vault migrate ~/Documents/feeds-vault apply --prune --keep scripts/collect_oreilly.py

# Keeps the oreilly collector because the framework doesn't ship one yet.
# Removes everything else superseded.
```

## Design

### Pruneability detection

A path is pruneable if **all** of:

- It exists in the vault.
- It is not in the scaffold manifest (i.e., not framework-shipped
  to begin with).
- There is an entry in the framework's `_SUPERSEDED_BY` map
  matching the path's basename.

The `_SUPERSEDED_BY` map lives at
`research_vault/migration/superseded_paths.py`:

```python
_SUPERSEDED_BY: dict[str, str] = {
    "scripts/collect_rss.py":     "research_vault.collectors.rss",
    "scripts/collect_youtube.py": "research_vault.collectors.youtube",
    "scripts/reddit_rss.py":      "research_vault.collectors.reddit",
    "scripts/reddit_scraper.py":  "research_vault.collectors.reddit",
    "scripts/collect_oreilly.py": "research_vault.collectors.oreilly",
    "scripts/extract.py":         "research_vault.processors.extract",
    "scripts/preprocess.py":      "research_vault.processors.preprocess",
    "scripts/verify.py":          "research_vault.processors.verify",
    "scripts/archive.py":         "research_vault.processors.archive",
}
```

The map grows as new framework modules ship. **A path appears here
only after the framework module is well-tested against at least
one real vault.**

### `migrate apply --prune` flow

1. `compute_plan(...)` as usual.
2. Compute the prune list = (`_SUPERSEDED_BY` keys that exist on
   disk) − (`--keep` paths).
3. Confirm with the user (skip on `--yes`).
4. Pre-snapshot commit (force-adds the prune-list files so HEAD~1
   can restore them — same `force_paths` mechanism as today).
5. Apply scaffold changes (writes).
6. Apply prune (`os.unlink` each file).
7. Post-snapshot commit (force-adds the prune-list deletions).
8. Run a smoke test (`research_vault pipeline <vault> status`) to
   confirm the vault still functions; warn if not.

### Inventory integration

[015b inventory](../015b-vault-inventory/spec.md) gains a
`pruneable` section in its JSON output:

```json
"pruneable": [
  {"path": "scripts/collect_rss.py", "superseded_by": "research_vault.collectors.rss"}
]
```

Text output gets the "Pruneable" section shown in Story 1.

## Acceptance

- [ ] `_SUPERSEDED_BY` map exists; updated as collectors / processors
      land.
- [ ] `research_vault migrate apply --prune` works end-to-end.
- [ ] `--keep PATH` excludes a path from the prune list.
- [ ] Pre/post snapshots capture the deleted files so `HEAD~2`
      rollback restores them.
- [ ] Smoke test (`pipeline status`) runs at the end and warns on
      failure.
- [ ] feeds-vault and codebase-vault retire successfully — their
      pipelines run on framework code afterwards.
- [ ] [015 Stage 5](../015-pipeline-consolidation/spec.md)
      acceptance checklist items marked done.

## Out of scope

- Automatic detection of "this vault's local script is *richer*
  than the framework's equivalent — don't prune". The user judges.
- Auto-migrating vault-local script configuration into the spec.
  The user transcribes (with [015c onboarding](../015c-vault-onboarding/spec.md) helping where it can).
- Deleting `.claude/commands/*.md`. Slash commands stay user-owned.

## Open questions

- **Should `--prune` happen as a separate `research_vault prune
  <vault>` subcommand instead of a flag on `migrate apply`?**
  Tentative: separate subcommand. Less surprise, clearer
  audit trail. The migrator stays focused on scaffold; pruning
  is a different action.
- **What if the user has edited the local script?** Detect via git
  log against the version that was originally shipped (if any)
  and warn before deleting. If the script was never shipped (it's
  entirely user-authored), there's no baseline — refuse unless
  `--force`.
- **What's the rollout sequence?** Don't add a path to
  `_SUPERSEDED_BY` until at least one real vault is running on
  the framework module for that path *successfully* for ≥7 days
  (or 5 pipeline runs). Treat this as a quality gate, not a
  policy enforced in code.
