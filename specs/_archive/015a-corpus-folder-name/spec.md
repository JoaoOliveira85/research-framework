# Feature Specification: Spec-Driven Corpus Folder Name

**Feature Branch**: `015a-corpus-folder-name` *(proposal — not yet branched)*
**Parent**: [015 — Pipeline Consolidation](../015-pipeline-consolidation/spec.md), Stage 1
**Created**: 2026-05-13
**Status**: planned — Draft

## Problem

The migrator's `_validate_vault()` hard-codes `data_vault/` as the
corpus folder name:

```python
def _validate_vault(vault_root: Path) -> None:
    if not (vault_root / "data_vault").exists():
        raise ValueError(f"Not a vault (no data_vault/ directory): {vault_root}")
```

Real vaults observed:
- `~/Documents/feeds-vault/` → `data_vault/` (matches today's default).
- `~/Documents/codebase-vault/` → `Codebase Vault/` (older convention,
  renamed manually to `data_vault/` during the 2026-05-13 migration
  pass; see [lesson 8](../013-vault-migrator/lessons-learned.md)).
- A user spinning up a "legal-research vault" next quarter may
  reasonably want `corpus/` or `cases/` or the literal `Legal
  Research/` — there's nothing intrinsic about `data_vault/`.

Hard-coding the name forces every vault into either (a) using the
framework's chosen name or (b) being renamed before the migrator will
talk to it. (b) costs the user a `git mv` + commit and a real chance
of breaking references in their tracked files. The framework should
read the corpus folder name from the spec instead.

## Goals

1. The corpus folder name is declared in the spec
   (`spec.vault.corpus_dir`, default `data_vault`).
2. The migrator reads it; the generator writes it; the collectors
   ([014](../014-reusable-collectors/spec.md)) respect it.
3. Existing vaults continue to work — `data_vault` remains the
   default, so anything written without the new spec field behaves
   exactly as today.

## Non-goals

- **Not** a generalisation of every framework-managed folder name.
  `_pipeline/`, `_templates/`, `.claude/`, `raw_data/` stay
  fixed-name in v1. Only the corpus folder is per-vault.
- **Not** a multi-corpus feature. One vault, one corpus folder.
  Multi-corpus is out of scope.
- **Not** a runtime override (no `--corpus-dir` CLI flag). The spec
  is the single source of truth; if you want to change the name,
  edit the spec and re-parse.

## User scenarios

### Story 1 — Spec declares the corpus folder name

**Given** a new vault spec:

```yaml
name: "Legal Research Vault"
owner: "..."
vault:
  corpus_dir: "cases"   # <-- new field, optional
```

**When** the user runs `research_vault generate --spec legal-spec.md`,

**Then** the generator scaffolds the vault with `cases/` (not
`data_vault/`) as the corpus folder; all rendered templates (CLAUDE.md,
AGENTS.md, indices, slash commands) reference `cases/` consistently;
`research_vault migrate <vault> assess` accepts the vault as valid.

### Story 2 — Existing vault retrofitted without the field still works

**Given** feeds-vault (where the corpus folder is `data_vault/` and the
spec doesn't yet declare `vault.corpus_dir`),

**When** the user runs `research_vault migrate ~/Documents/feeds-vault apply`,

**Then** the framework treats the absent `vault.corpus_dir` as
`data_vault` (the historical default) and behaves identically to
today — zero migration cost for existing vaults.

### Story 3 — Existing vault with non-default name migrates cleanly

**Given** a hypothetical vault with corpus folder `notes/` and a spec
that says `vault.corpus_dir: notes`,

**When** the user runs the migrator,

**Then** `_validate_vault` accepts the vault, `_render_manifest_contents`
renders templates that reference `notes/` (not `data_vault/`), and the
migration applies without requiring `git mv`.

This is the scenario [lesson 8](../013-vault-migrator/lessons-learned.md)
explicitly calls out as worth solving.

## Design

### Spec field

Extend the simple spec format with an optional `vault` block:

```yaml
vault:
  corpus_dir: "data_vault"   # default; any non-empty string is valid
```

Validation in `spec/simple.py`:

- Type: string, non-empty.
- Disallow path traversal (`..`, leading `/`, absolute paths).
- Disallow names that collide with framework-managed folders
  (`_pipeline`, `_templates`, `.claude`, `.cursor`, `raw_data`).
- A name that contains spaces or non-ASCII is allowed (the
  codebase-vault precedent is "Codebase Vault"); the framework just
  quotes it correctly everywhere.

Detailed spec format (`spec/parser.py`) accepts the same field at the
top level.

### Compiled spec

`SpecConfig.vault_corpus_dir: str` (defaults to `"data_vault"` when
absent). This is the single read site every consumer uses.

### Migrator changes

- `_validate_vault(vault_root, spec)` reads the spec's
  `vault_corpus_dir` and checks that folder exists (today it
  hard-codes `data_vault`).
- `_load_spec_from_vault` already runs before `_validate_vault` in
  paths that need both; reorder where necessary.
- For backwards compatibility: if `_pipeline/spec-parse.json` is
  absent (a fresh vault that hasn't been parsed yet), fall back to
  the `data_vault/` check so the existing
  "vault doesn't have a spec yet" code path keeps working.

### Generator changes

- `scaffold(spec, vault_dir)` creates the corpus directory using
  `spec.vault_corpus_dir`.
- Every Jinja2 template that references the corpus folder uses
  `{{ spec.vault.corpus_dir }}` (or the compiled
  `{{ corpus_dir }}` context variable).
- Bundled prompts (`_pipeline/prompts/scout-prompt.md`,
  `dfs-prompt.md`) are rendered against the corpus dir name —
  today they hard-code paths in places.

### Manifest changes

The manifest's `path` field stays repo-relative as today; the corpus
folder is **not** managed by the manifest (the framework doesn't own
its contents). So the manifest schema is unchanged; only the
**rendered content** of manifest entries (CLAUDE.md, AGENTS.md, etc.)
varies by `corpus_dir`.

That means `rendered_sha256` becomes per-vault for any entry whose
template references the corpus folder. The manifest's stored SHA
already isn't used for diff under the "fresh install.sh" model — it's
metadata only. So this change is invisible to the migrator's
correctness; it just makes the SHA less stable across vaults with
different corpus names.

### CLI changes

- `research_vault generate --spec ...` honours the new field
  transparently — no user-visible CLI changes.
- `research_vault migrate <vault> assess` likewise.
- `research_vault parse-spec <vault> [spec]` likewise.
- No new commands or flags introduced by this spec.

## Acceptance

- [ ] Spec field implemented in both simple and detailed parsers.
- [ ] `SpecConfig.vault_corpus_dir` populated correctly; defaults to
      `data_vault`.
- [ ] `_validate_vault` reads the spec field.
- [ ] Generator scaffolds the right folder name.
- [ ] All bundled templates reference the corpus folder via the
      spec, not as a literal `data_vault/`.
- [ ] Existing feeds-vault and codebase-vault migrations remain
      no-op idempotent (their specs default to `data_vault`,
      matching their renamed corpus dirs).
- [ ] Test: a fixture vault with `vault.corpus_dir: cases` is
      generated, then migrated, and the migrator never touches
      anything outside `cases/`.
- [ ] [Lesson 8](../013-vault-migrator/lessons-learned.md) is
      annotated as "resolved by 015a" once this ships.

## Acceptance coverage

Backfilled per spec 024 FR-013 (ADR-0008). Maps each user scenario to
the tests that exercise `vault.corpus_dir` / corpus-folder validation.

| User Story | Evidence |
|------------|----------|
| US1 — Spec declares the corpus folder name | `tests/spec/test_simple.py` (vault.corpus_dir parse/round-trip) + `tests/spec/test_validator.py` |
| US2 — Existing vault retrofitted without the field still works | `tests/spec/test_simple.py` (default `data_vault`) + `tests/scripts/test_validate_vault.py` |
| US3 — Existing vault with non-default name migrates cleanly | `tests/spec/test_simple.py` (custom `corpus_dir: cases`) + `tests/scripts/test_validate_vault.py` |

## Out of scope

- Renaming the corpus folder of an existing vault (use `git mv` +
  spec edit + re-parse; same as today).
- Multi-corpus vaults.
- A `--corpus-dir` CLI override that conflicts with the spec.
- Migrating manifest SHAs to be content-independent of the corpus
  name.

## Open questions

- **Should the framework refuse to accept manifest entries whose
  templates hard-code `data_vault/`?** It would catch future
  regressions where someone introduces a template that ignores the
  spec field. Cheap to add as a manifest-build-time check.
- **Should `vault.corpus_dir` ever be writable post-scaffold?** I.e.,
  can a user rename the corpus folder of an existing vault by
  editing the spec? Tentative answer: no — that's a `git mv` plus
  a spec edit, never an automatic operation. The migrator's job is
  scaffolding, not corpus relocation.
