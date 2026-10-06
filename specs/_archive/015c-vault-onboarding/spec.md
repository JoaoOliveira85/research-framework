# Feature Specification: `research_vault onboard <vault>`

**Feature Branch**: `015c-vault-onboarding` *(proposal — not yet branched)*
**Parent**: [015 — Pipeline Consolidation](../015-pipeline-consolidation/spec.md), Stage 1
**Created**: 2026-05-13
**Status**: planned — Draft

## Problem

[Lesson 10](../013-vault-migrator/lessons-learned.md#10-vault-recovery-is-a-uniform-flow--promote-it-to-one-command)
observed that bringing an existing vault under the framework's
governance is a uniform 6-step procedure:

1. `git init` + seed commit.
2. Rename corpus folder if it isn't `data_vault/` (becomes
   unnecessary once
   [015a](../015a-corpus-folder-name/spec.md) ships).
3. Draft a `<vault>-spec.md` from existing prose docs (CLAUDE.md /
   AGENTS.md / README.md).
4. `research_vault parse-spec <vault> <spec>` to write
   `_pipeline/spec-parse.json`.
5. `research_vault migrate <vault> assess`.
6. Review, then `research_vault migrate <vault> apply`.

Step 3 needs domain judgment; steps 1, 2, 4, 5, 6 are pure
sequencing. Performing them by hand costs ~30 minutes per vault,
which is fine for two vaults and not fine for "I have other vaults I
want to start working on as soon as possible." The framework should
do the sequencing; the user supplies the judgment.

## Goals

1. A single `research_vault onboard <vault>` subcommand drives the
   uniform recovery flow.
2. The command **proposes**; the user **edits**. Specifically:
   - Step 3 (spec drafting) emits a draft spec for the user to
     review, *not* a finalised one.
   - Steps 1, 2, 4, 5 run automatically (each as a separate, named
     git commit so any individual step is revertable).
   - Step 6 (apply) is the user's explicit decision; `onboard`
     stops after `assess` and prints the next command.
3. **Idempotent.** Running `onboard` twice on the same vault is
   safe — already-done steps are detected and skipped.
4. **No magic.** Each step is visible in stdout with the equivalent
   command the user could have run by hand.

## Non-goals

- **Not** an automated migrator. `onboard` stops at `assess`. The
  user must explicitly run `migrate apply` to mutate the vault.
- **Not** a spec-quality validator beyond what `parse-spec` already
  does. We don't try to LLM-grade the draft spec.
- **Not** a replacement for `research_vault generate` (which creates
  a *new* vault from a spec). `onboard` adopts an *existing* vault
  with no spec.

## User scenarios

### Story 1 — Fresh onboarding (the common path)

```bash
$ research_vault onboard ~/Documents/reference-vault

[onboard 1/5] init git repo in /Users/.../reference-vault …
  $ git -C ~/Documents/reference-vault init -q -b main
  $ git -C ~/Documents/reference-vault add -A
  $ git -C ~/Documents/reference-vault commit -m "vault: pre-onboarding initial state"
  → committed 1,420 files.

[onboard 2/5] check corpus folder …
  Found candidate corpus directories: "Tech Notes/", "data_vault/" not present.
  Renaming "Tech Notes/" → "data_vault/"   (will be overridable in 015a)
  $ git -C ~/Documents/reference-vault mv "Tech Notes" data_vault
  $ git -C ~/Documents/reference-vault commit -m "vault: rename corpus to data_vault/"
  → renamed and committed.

[onboard 3/5] draft research spec from prose docs …
  Read CLAUDE.md (12 KB), AGENTS.md (4 KB), README.md (3 KB).
  Inferred:
    name:        "Tech Knowledge Vault"            (from README first heading)
    owner:       "$USER"                            (no owner field detected)
    growth_mode: "incremental"                     (default)
    scope.include:
      - "01 - Concepts/"  → AI, ML, software architecture
      - "02 - Tools/"     → developer tooling
      ...
  Wrote draft spec: /Users/.../reference-vault/reference-vault-spec.md

  REVIEW REQUIRED — please open and edit this file:
    code ~/Documents/reference-vault/reference-vault-spec.md

  When done, re-run:
    research_vault onboard ~/Documents/reference-vault

[onboard] Stopped at step 3 — waiting for spec review.
```

The user edits the draft, then re-runs:

```bash
$ research_vault onboard ~/Documents/reference-vault

[onboard 1/5] git repo already initialised   ✓
[onboard 2/5] corpus folder is data_vault/   ✓
[onboard 3/5] research spec already drafted at reference-vault-spec.md
  → mtime is more recent than spec-parse.json — re-parsing.

[onboard 4/5] parse spec into _pipeline/spec-parse.json …
  $ research_vault parse-spec ~/Documents/reference-vault reference-vault-spec.md
  wrote /Users/.../reference-vault/_pipeline/spec-parse.json
    name: Tech Knowledge Vault
    owner: João Oliveira
    note_types: 2
    data_sources: 4

[onboard 5/5] run migrator assess …
  migrator: assess framework=? → 1 create=27 overwrite=3 leave-alone=4

  Pending changes:
    create:    27 framework files (settings, prompts, scripts, …)
    overwrite:  3 (CLAUDE.md, AGENTS.md, README.md)
    leave-alone: 4 user-owned files

[onboard] Done. Vault is ready for migration.

To apply the changes, run:
  research_vault migrate ~/Documents/reference-vault apply

Or refine the spec first:
  $EDITOR ~/Documents/reference-vault/reference-vault-spec.md
  research_vault onboard ~/Documents/reference-vault   # re-runs from step 4
```

### Story 2 — Re-running on an already-onboarded vault

```bash
$ research_vault onboard ~/Documents/feeds-vault

[onboard 1/5] git repo already initialised      ✓
[onboard 2/5] corpus folder is data_vault/      ✓
[onboard 3/5] spec at feeds-vault-spec.md            ✓
[onboard 4/5] spec-parse.json present and current ✓
[onboard 5/5] run migrator assess …
  migrator: assess framework=1 → 1 create=0 overwrite=14 leave-alone=20

[onboard] Done. Nothing changed.
```

### Story 3 — Aborting mid-onboarding

```bash
$ research_vault onboard ~/Documents/some-vault
[onboard 1/5] init git repo …
  $ git -C … init   → ✓
  $ git -C … add -A
  $ git -C … commit -m "vault: pre-onboarding initial state"   → ✓

[onboard 2/5] check corpus folder …
  ✗ Multiple candidate corpus directories found:
    - "Tech Notes/" (847 files)
    - "data_vault/"   (12 files)
  Refusing to choose automatically. Decide manually:
    git -C ~/Documents/some-vault mv …
    git -C ~/Documents/some-vault rm -r …
  then re-run `research_vault onboard`.

[onboard] Aborted at step 2. The git seed commit (step 1) is preserved.
```

## Design

### Subcommand surface

```bash
research_vault onboard <vault> [--draft-only] [--no-git]
```

- `<vault>` is a path to an existing directory (anything, doesn't need
  to look like a vault yet).
- `--draft-only` stops after step 3 even if everything else is ready —
  useful for "I just want to see the proposed spec".
- `--no-git` skips git init / commit / mv steps. The user is
  responsible for their own VCS. Discouraged but supported.

No flag to "do step 6 too" — `migrate apply` is a deliberate manual
step.

### State detection

Each step uses cheap on-disk checks to decide whether it has already
been done:

| Step | Already-done if … |
|---|---|
| 1 | `<vault>/.git/` exists. |
| 2 | `<vault>/data_vault/` (or `spec.vault.corpus_dir`) exists. |
| 3 | Any of `<vault>/{<vault_basename>-spec.md, research.spec.md, *-spec.md}` exists. |
| 4 | `<vault>/_pipeline/spec-parse.json` exists AND mtime ≥ spec file mtime. |
| 5 | A `migrator: assess` summary line printed (no persistent state — we always re-run assess; it's cheap). |

### Step 3 — spec drafting heuristics

Reads `CLAUDE.md`, `AGENTS.md`, `README.md` if present (in that
priority order). Extracts:

- **name**: first H1 in README.md, falling back to `<vault>`
  directory name title-cased.
- **owner**: first match for `Owner: …` or `**Owner**: …` in any
  prose doc; falls back to `$USER`.
- **topic / goal / problem**: first paragraph under
  `## Purpose` / `## What This Vault Covers` / first paragraph of
  README, lightly cleaned up.
- **scope.include**: folder names under the corpus dir, with brief
  descriptions from any `## Structure` section.
- **scope.exclude**: bullet list under `## Constraints`,
  `## Out of Scope`, or `## What This Vault Does NOT Cover`.
- **sources**: bullet list under `## Sources` / `## Data Sources`,
  if present.
- **growth_mode**: `incremental` default.

If a section can't be found, the field is filled with a placeholder
like `"# TODO: fill in (read SYSTEM_SPEC.md §1 or set manually)"` so
the user notices.

**Deterministic only — no LLM.** The user explicitly accepts the
heuristic and edits it. The fact that feeds-vault's and codebase-vault's
drafted specs were "good enough but worth tightening later" is the
expected v1 quality bar.

### Step 4 — parse-spec

Delegates to the existing `research_vault parse-spec` subcommand.
Zero new logic.

### Step 5 — assess

Delegates to `research_vault migrate <vault> assess`. Zero new
logic.

### Implementation

- New file: `src/research_vault/onboard.py` orchestrates the five
  steps as separate functions.
- New CLI subcommand `onboard` wired in `cli.py`.
- Each step prints its equivalent shell command before running it,
  so the operation is auditable and the user can replicate by hand
  if they prefer.
- All git operations go through `migrator_git._run` (same code path
  as the migrator's snapshot boundary) for consistency.

## Acceptance

- [ ] `research_vault onboard` runs against a fresh fixture vault
      (no `.git`, no spec, no `_pipeline/spec-parse.json`) and
      stops cleanly at step 3 after drafting the spec.
- [ ] Re-running after the user edits the spec proceeds through
      steps 4-5 and stops at the assess summary.
- [ ] Running again on a fully-onboarded vault is a no-op that
      prints all five steps as `✓`.
- [ ] Each step's git commit has a stable message prefix
      (`vault: pre-onboarding initial state`, `vault: rename corpus
      …`) for grep-ability across vaults.
- [ ] Test: ambiguous corpus folder (two candidates, no
      `data_vault/`) aborts with an actionable error message.
- [ ] [Lesson 10](../013-vault-migrator/lessons-learned.md) is
      annotated as "resolved by 015c" once this ships.
- [ ] The ad-hoc `/tmp/parse_feeds_vault_spec.py` from the recovery
      sessions is deleted (it has no codebase home and is
      superseded by `parse-spec` + `onboard`).

## Out of scope

- **Apply.** The migration is always a deliberate manual step.
- **Spec refinement after onboarding.** Once the spec exists, the
  user edits it directly; `onboard` only drafts the *first*
  version.
- **Multi-vault batch onboarding.** A wrapper script can `for vault
  in …; do research_vault onboard $vault; done` if the user wants
  that; the subcommand operates on one vault at a time.
- **LLM-driven spec drafting.** Deterministic heuristics only in
  v1. An LLM-augmented `onboard --draft-with-llm` could come
  later, but the v1 contract is "we read the prose, fill in what
  we can, and you tell us where we're wrong".

## Open questions

- **What corpus-folder heuristic should `onboard` apply when 015a
  hasn't landed yet?** Tentative: hard-code "rename anything not
  `data_vault/`" until 015a; after 015a, accept the existing name
  and write it into the draft spec instead.
- **Should `onboard` create the `codebase-vault-spec.md` / `feeds-vault-spec.md`
  filename pattern automatically, or always use `research.spec.md`?**
  Tentative: use `<vault-basename>-spec.md` to match how I named
  them by hand for feeds-vault and codebase-vault — explicit > implicit.
- **Should `onboard` add a vault `.gitignore` if none exists?**
  Today's framework scaffold writes one (track `data_vault/` only).
  But the vaults we onboarded didn't have one and the migrator's
  `force_paths` handles the resulting state. Tentative: leave the
  gitignore decision to `migrate apply` — `onboard` is read-mostly.
