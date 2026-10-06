---
spec_number: 071
title: Archived vaults — freeze content, keep everything else
status: SHIPPED v1.0.0 (2026-08-27, PR #195, squash 6785400)
target_version: 1.0.0
created: 2026-08-27
---

**Status:** shipped(2026-08-27, PR #195) — SHIPPED v1.0.0 (PR #195, squash `6785400`) — applied to `codebase-vault`.

# Feature Specification: archived vaults

## Why

A vault can be *finished*. Its notes are still worth querying, indexing,
digesting and re-grading, and it should still take framework upgrades — but
nothing should ever write research content into it again.

Before this there was no way to say that. The only options were to delete the
vault, move it somewhere the tooling could not see, or rely on nobody typing
`./vault research` in the wrong directory. None of those survive a cron entry,
a stale shim, or a script that iterates over `~/Documents/vaults/*`.

Raised by the operator 2026-08-27 for `codebase-vault`: *"instruct the pipeline
to do no content updates under no circumstance … the vault can still be
queried, of course, and we can still update it to the latest build."*

## The contract

`settings.yaml`:

```yaml
archived: true
```

**Refused** — every path that writes research content:

- `./vault research`
- `research-framework generate` (fresh)
- `research-framework generate --resume`
- any direct `orchestrator.run_cycles(...)` call

Exit code **2**, with a message naming the vault, what still works, and the
one-line change that reverses it.

**Unaffected** — everything else:

- read/query: `ask`, `status`, `digest`, `health`, `audit`, `coverage`
- maintenance: `re-grade`, `wikilinks`, `reindex`, `refresh-sources`
- lifecycle: `update`, `regenerate-shim`

## Requirements

**FR1 — the flag is a typed setting.** `settings.yaml::archived`, boolean,
default `false`. Absent ⇒ not archived. Exposed as `VaultSettings.archived`.

**FR2 — enforcement is an invariant, not a CLI courtesy.** The guard lives in
`orchestrator.run_cycles`, so it holds for every caller — a stale vault shim, a
cron entry, a script, a test harness. A second check at the CLI entry point
exists only so the operator reads "archived" rather than whichever unrelated
config error is hit first; both call the same `is_archived`.

**FR3 — refuse before any side effect.** `run_cycles` opens a git branch and
writes a run report early. The guard precedes `begin_run`, so an archived vault
comes away with neither.

**FR4 — the flag must hold when the rest of settings does not.** `is_archived`
reads the key with a direct YAML load rather than through
`load_vault_settings`. The typed loader validates the *whole* file, so a vault
missing (say) `pipeline.max_cycles` raises before `archived` is reached — and an
archived vault is exactly the one whose pipeline config nobody has kept current.
`codebase-vault` is in that state: its settings predate spec 061, and routing
the check through the typed loader made the flag **silently inert on the one
vault it was written for**. Caught in implementation, not review.

**FR5 — only a literal `true` archives.** A missing file, unreadable file,
unparseable YAML, or a typo all read as *not* archived: those are different
failures and are surfaced on their own terms. Defaulting to "archived" on a
parse error would strand a working vault. The typed loader separately *rejects*
a non-boolean value outright, so a typo is not silently tolerated wherever
settings do load.

## Applied

`codebase-vault` is archived as of 2026-08-27, with an explanatory comment block
in its `settings.yaml` and the previous file kept at
`settings.yaml.pre-archive-bak`. Verified live: `is_archived` → `True`,
`run_cycles` → exit 2 with no branch opened.

## Not in scope

- A `./vault archive` verb. One line in `settings.yaml` with a comment is
  clearer than a verb that writes the same line, and it is self-documenting in
  the file the operator already reads.
- Making archived vaults read-only on disk. The flag is about the *pipeline*,
  not filesystem permissions; the operator still edits their own notes.
