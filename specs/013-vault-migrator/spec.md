---
status: superseded(by ./vault update) — partially-withdrawn
withdrawn_at: 2026-05-20
withdrawn_in: v0.2.33
superseded_by: ./vault update (pip install --upgrade + install.sh)
---

# Spec 013 — Vault Migrator (PARTIALLY WITHDRAWN)

## Status: partially withdrawn (CLI gone, shared infrastructure retained)

The vault migrator's user-facing CLI (`research-framework migrate <vault>
{assess|dry-run|apply}`) was withdrawn in v0.2.33. The supporting
infrastructure that other features (inventory, prune) depended on was
**retained but renamed** so the codebase no longer carries a misleading
"migrator" prefix on shared modules.

## What was deleted

- `research-framework migrate` CLI subcommand + `_cmd_migrate` handler
- `src/research_framework/pipeline/migrator.py` (orchestrator entry-point)
- `src/research_framework/pipeline/migrator_apply.py` (mutating apply layer)
- `tests/cli/test_migrate_cli.py`
- `tests/pipeline/test_migrator_apply.py`
- `tests/pipeline/test_migrator_idempotent.py`
- `tests/pipeline/test_migrator_orchestration.py`
- `tests/pipeline/test_conftest_guardrail.py`
- This directory's `plan.md`, `tasks.md`, `research.md`, `quickstart.md`,
  `lessons-learned.md`, `contracts/cli.md`,
  `contracts/migration-plan.schema.json`, `checklists/requirements.md`
- Migrator-apply guardrail in `tests/conftest.py`

## What was renamed (retained as general infrastructure)

| Old | New | Consumer |
|---|---|---|
| `pipeline/migrator_baseline.py` | `pipeline/scaffold_baseline.py` | `cli_inventory.py` |
| `pipeline/migrator_diff.py` | `pipeline/scaffold_diff.py` | `cli_inventory.py` |
| `pipeline/migrator_git.py` | `pipeline/vault_git.py` | `prune.py` |
| `pipeline/migrator_models.py` | `pipeline/scaffold_models.py` | (data models for the above) |

Tests for the kept modules were renamed in lockstep
(`test_migrator_baseline_scope.py` → `test_scaffold_baseline_scope.py`, etc.).

## What was retained

- `data-model.md` (this directory) — still describes the kept `ScaffoldManifest`,
  `ManifestEntry`, and `VaultBaseline` shapes. Module references in the doc
  use the new names.
- `contracts/scaffold-manifest.schema.json` — live JSON Schema for
  `dist-templates/scaffold-manifest.json`, consumed by
  `scripts/build_scaffold_manifest.py` and `pipeline/scaffold_manifest.py`.
- `tests/fixtures/migrator/` — kept as-is. The directory name is historical;
  the fixtures (pre-005-vault, pre-007-vault, pre-008-vault, current-vault,
  no-specparse-vault) are used by the retained `test_scaffold_baseline_scope.py`
  and `test_scaffold_diff.py`.

## Why the migrator went

- The CLI was never reliable in production. Even on `main` it failed with
  `error: not a vault (no data_vault/ directory)` against its own fixtures.
- The "fresh-install.sh model" the spec was redesigned around (commit
  `98d1792`) made the migrator a thin wrapper around `install.sh`; once
  `install.sh` was made idempotent and per-vault, the wrapper added no value.

## What replaces the migrator CLI

The per-vault `./vault update` command (templates/vault-script.sh.j2):

1. `pip install --upgrade git+https://github.com/JoaoOliveira85/research-framework.git@<ref>`
   into the vault's venv (framework upgrade).
2. Downloads the matching source archive from GitHub and re-runs the bundled
   `install.sh` against `${VAULT_DIR}` to refresh scaffolding (AGENTS.md,
   `.claude/commands/*`, `_templates/`, etc.).

## Reserved number

Spec number `013` is permanently reserved — **DO NOT reuse it for new work**.
Same convention as PEPs/RFCs/ADRs. See `CHANGELOG.md` v0.2.33 for the full
deletion log.
