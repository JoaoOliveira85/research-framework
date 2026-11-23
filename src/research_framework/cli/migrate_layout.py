"""migrate-layout CLI (spec 083 FR-011)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..pipeline import layout_migration


def cmd_migrate_layout(args: argparse.Namespace) -> int:
    """Move a vault's durable state under ``_pipeline/state/``.

    Exit 0: migrated, or already migrated. Exit 2: refused (vault not found,
    dirty tree without ``--force``, a conflicting destination, a ``.gitignore``
    rule that still hides the state directory) with nothing moved, except the
    last case, which names the rule after moving.
    """
    vault = args.vault
    if vault is None or not Path(vault).is_dir():
        print(f"error: vault not found: {vault}", file=sys.stderr)
        return 2
    result = layout_migration.migrate(
        Path(vault), dry_run=bool(args.dry_run), force=bool(args.force)
    )
    for line in result.messages:
        stream = sys.stderr if line.startswith("error") else sys.stdout
        print(line, file=stream)
    return result.exit_code
