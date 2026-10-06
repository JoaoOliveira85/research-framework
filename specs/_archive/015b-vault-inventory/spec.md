# Feature Specification: `research_vault inventory <vault>`

**Feature Branch**: `015b-vault-inventory` *(proposal — not yet branched)*
**Parent**: [015 — Pipeline Consolidation](../015-pipeline-consolidation/spec.md), Stage 1
**Created**: 2026-05-13
**Status**: planned — Draft

## Problem

To consolidate the research loop into the framework
([015 Stages 2-5](../015-pipeline-consolidation/spec.md)) we need to
know what each vault already has and what shape it's in. Today the
answer requires manual inspection:

> feeds-vault has ~4,300 lines of collector / processor scripts spread
> across `scripts/collect_*.py`, `extract.py`, `preprocess.py`,
> `verify.py`, `archive.py`, plus 13 slash commands in
> `.claude/commands/` with various `agent-definition` frontmatter.
> codebase-vault has a different set — `fix_*.py`, `check_*.py`, a
> `scripts/tests/` directory, two vault-specific slash commands, and
> templates that include `service.md`,
> `flow.md`, `decision.md` etc. that feeds-vault doesn't have.

I worked this out by `ls`, `head`, and `wc -l` across both vaults
during the migration pass. That doesn't scale to the next vault, or
the one after, or to any cross-vault analysis we'd want to run. The
framework should know how to look at a vault and produce a structured
inventory.

## Goals

1. **Read-only.** The inventory subcommand never writes to the vault.
2. **Structured output.** JSON (default) or a human-readable summary
   (`--format=text`). JSON is the input to future tooling that
   compares vaults.
3. **Categorised.** Surface the distinction between
   framework-managed paths (in the manifest), user-customised paths
   (overridden defaults), and user-added paths (not in the
   manifest at all).
4. **Fast.** Should be O(seconds) on a 10k-file vault. No LLM calls,
   no network. Filesystem + manifest comparison only.

## Non-goals

- **Not** a diff tool. We're not comparing vault A to vault B in v1;
  we're producing the snapshot each could be diffed against later.
- **Not** a lint tool. We don't tell the user whether their custom
  scripts are good or bad. We just enumerate them.
- **Not** a stats tool for the corpus. The corpus folder
  (`data_vault/` or its `vault.corpus_dir` equivalent —
  [015a](../015a-corpus-folder-name/spec.md)) is summarised as a
  file count + total bytes only. Per-note analysis belongs elsewhere.

## User scenarios

### Story 1 — Snapshot a vault as JSON

```bash
$ research_vault inventory ~/Documents/feeds-vault --format=json > feeds-vault-inv.json
$ jq '.scripts.user_added | length' feeds-vault-inv.json
9
$ jq '.slash_commands.user_added | map(.name)' feeds-vault-inv.json
["scout", "extract", "verify", "report", "pipeline", "discover",
 "ingest", "retrieve", "cleanup", "explore", "research-assistant-v3"]
```

### Story 2 — Human-readable summary

```bash
$ research_vault inventory ~/Documents/codebase-vault --format=text
Vault: Business Knowledge Vault  (corpus: data_vault/ — 157 notes)
─────────────────────────────────────────────────────────────────
Framework manifest entries:        34
  matching disk (LEAVE_ALONE):     19
  pending overwrite:                3
  missing on disk (pending CREATE): 12

Scripts in scripts/ (9 files):
  framework-shipped:      0
  user-added:             9
    check_acronym_links.py        (5.3 KB)
    check_template_compliance.py  (8.1 KB)
    fix_duplicated_content.py     (3.0 KB)
    ...

Slash commands in .claude/commands/ (0):
  framework-default present:      0
  user-customised:                 0
  user-added:                      0

Templates in data_vault/_templates/ (11):
  framework-shipped:               0 (framework ships CHANGELOG.md + concept.md only)
  user-added:                     11
    CHANGELOG.md, concept.md, decision.md, flow.md, market.md,
    process.md, product.md, risk.md, service.md, source.md, team.md

Custom _pipeline/ artefacts:
  _pipeline/lessons-learned.md, _pipeline/post-mortem-phase1.md
  (5 KB and 12 KB respectively — vault-owned process knowledge)

Run with --format=json for the full machine-readable inventory.
```

### Story 3 — Cross-vault analysis

```bash
$ research_vault inventory ~/Documents/feeds-vault --format=json > ai.json
$ research_vault inventory ~/Documents/codebase-vault --format=json > biz.json
$ jq -s '.[0].scripts.user_added + .[1].scripts.user_added |
         group_by(.name) | map(select(length > 1)) | .[].[0].name' ai.json biz.json
# Lists scripts that exist in both vaults — first-class
# promotion candidates for the framework.
```

(The script comparison itself isn't part of v1 — this is shown to
illustrate that the JSON shape supports it.)

## Output schema (sketch)

```json
{
  "vault_root": "/Users/.../feeds-vault",
  "framework_version": 1,
  "vault_spec": {
    "name": "AI Knowledge Vault",
    "owner": "João Oliveira",
    "corpus_dir": "data_vault"
  },
  "manifest_status": {
    "entries_total": 34,
    "matching": 19,
    "pending_overwrite": 3,
    "pending_create": 12
  },
  "corpus": {
    "path": "data_vault",
    "file_count": 4673,
    "total_bytes": 41203200,
    "templates": [
      {"name": "concept.md", "size": 1402, "in_manifest": true, "user_customised": false}
    ]
  },
  "scripts": {
    "path": "scripts",
    "framework_shipped": [
      {"name": "agent_call.py", "size": 12480, "manifest_managed": true}
    ],
    "user_added": [
      {"name": "collect_rss.py", "size": 38120},
      {"name": "collect_youtube.py", "size": 18430}
    ]
  },
  "slash_commands": {
    "path": ".claude/commands",
    "framework_seeded": [
      {"name": "ask",      "user_customised_after_seed": true},
      {"name": "research", "user_customised_after_seed": true},
      {"name": "write",    "user_customised_after_seed": false}
    ],
    "user_added": [
      {"name": "scout",  "size": 10240, "agent_definition": true},
      {"name": "verify", "size": 8120,  "agent_definition": true}
    ]
  },
  "pipeline_state": {
    "spec_parse_present": true,
    "spec_parse_valid":   true,
    "framework_version_in_spec_parse": 1,
    "migration_log_entries": 1,
    "custom_pipeline_files": [
      "_pipeline/lessons-learned.md",
      "_pipeline/post-mortem-phase1.md"
    ]
  },
  "warnings": [
    "11 user-added templates under data_vault/_templates/ — consider promoting common ones to framework",
    "scripts/collect_rss.py is candidate for 014 RSS collector"
  ],
  "generated_at": "2026-05-13T18:00:00Z"
}
```

The schema is the contract; the field set will accrete as we use it.

## Design

### Detection rules

- **Framework-managed** = path appears in
  `dist-templates/scaffold-manifest.json`.
- **User-customised** = path is in the manifest **and**
  `is_user_owned_after_first_write` is true **and** present on disk
  (so the framework seeded it, the user owns it now).
- **User-added** = path is on disk, not in the manifest, and not an
  obvious migrator artefact
  (`_pipeline/.migration-plan.json`, etc.).
- **Pending create / overwrite** = derived from the same diff logic
  the migrator's `assess` uses (`compute_plan`). No new logic.

### Implementation

- New file: `src/research_vault/cli_inventory.py` (or a function in
  `cli.py`'s growing module).
- Reuses `pipeline.migrator.read_vault_baseline` and `compute_plan`
  for the manifest-status numbers — zero duplicated logic.
- Walks `scripts/`, `.claude/commands/`, `data_vault/_templates/`,
  `_pipeline/` to enumerate user-added paths. Uses the manifest
  paths as the "is this framework-shipped" lookup.
- JSON output is the canonical shape; text output is a thin
  prettifier over the same dict.

### CLI

```bash
research_vault inventory <vault> [--format=json|text] [--out PATH]
```

- `--format` defaults to `text` if stdout is a TTY, else `json`.
- `--out` writes to a file instead of stdout.
- Exit codes: 0 success, 2 fatal (not-a-vault, etc.). No "exit 1
  on drift" semantics — this command is read-only and informational.

## Acceptance

- [ ] `research_vault inventory <vault>` produces a valid inventory
      against feeds-vault, codebase-vault, and the test fixture vault.
- [ ] JSON output conforms to the documented schema.
- [ ] Text output reads like the Story 2 example.
- [ ] Zero writes to the vault — confirmed by test fixture `git
      status` after the run.
- [ ] One regression test per category (framework-managed,
      user-customised, user-added).
- [ ] Inventory of both real vaults committed under `specs/015/`
      (e.g. `specs/015/inventory-feeds-vault.json` +
      `specs/015/inventory-codebase-vault.json`) as the dataset
      that informs Stage 2/3 consolidation work.

## Out of scope

- Cross-vault diff (`research_vault inventory diff a b`).
- Promoting user-added artefacts into the framework (separate
  manual work, informed by this output).
- LLM-driven summarisation of vault content. The corpus is summarised
  by counts only.
- Watching for changes (no `inventory --watch`). Run on demand.

## Open questions

- **Should custom slash commands be detected as
  agent-definitions?** Today only the YAML frontmatter
  `type: agent-definition` says so; other slash commands are plain
  Claude Code prompts. v1 trusts the frontmatter; v2 could heuristic.
- **Where does the inventory live?** v1 prints/writes to stdout/file.
  Some users may want it cached at
  `<vault>/_pipeline/.inventory.json` for tooling. Decide based on
  whether 015c (onboarding) wants to read it.
