"""One-shot, idempotent repair for spec-029 Bug 2's durable harm (FR-008).

The path-substring attribution bug inflated ``consecutive_empty_cycles`` and
wrongly auto-archived still-cited sources. This script recomputes ``cited_now``
from the **current** ``data_vault/`` frontmatter (FR-003 predicate, shared with
``source_manager``) and, for each source:

  (a) un-archives ``status='archived' AND cited_now > 0``;
  (b) resets ``consecutive_empty_cycles=0`` where ``cited_now > 0``;
  (c) leaves genuinely-uncited sources (``cited_now == 0``) untouched.

``--dry-run`` (default) prints a per-source diff and mutates nothing.
``--apply`` writes **only** ``sources.db`` — never the note tree. A second
``--apply`` is a no-op (idempotent). On a vault that never ran the buggy code,
the dry-run reports zero changes (no false positives).

See specs/029-source-manager-correctness/spec.md FR-008 / SC-005.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from research_framework.pipeline.source_manager import _count_notes_referencing


def _db_path(vault: Path) -> Path:
    return vault / "_pipeline" / "sources.db"


def reconcile(vault: Path, *, apply: bool = False) -> list[dict]:
    """Recompute current citations and repair wrongful archival.

    Returns the list of change records (empty when nothing needs fixing). Each
    record: ``{name, cited_now, was_status, was_empty, unarchived, empty_reset}``.
    Dry-run (``apply=False``) computes and reports the same set without writing.
    """
    db = _db_path(vault)
    if not db.exists():
        return []

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT name, url, status, consecutive_empty_cycles FROM sources"
        ).fetchall()

        changes: list[dict] = []
        for row in rows:
            name = row["name"]
            url = row["url"] or ""
            status = row["status"]
            empty = int(row["consecutive_empty_cycles"] or 0)

            cited_now = _count_notes_referencing(vault, name, url)
            if cited_now == 0:
                continue  # genuinely uncited — leave untouched (FR-008c)

            unarchive = status == "archived"
            reset_empty = empty > 0
            if not (unarchive or reset_empty):
                continue  # already healthy — nothing to do (idempotent)

            changes.append(
                {
                    "name": name,
                    "cited_now": cited_now,
                    "was_status": status,
                    "was_empty": empty,
                    "unarchived": unarchive,
                    "empty_reset": reset_empty,
                }
            )

        if apply and changes:
            for change in changes:
                if change["unarchived"]:
                    conn.execute(
                        "UPDATE sources SET status='active' WHERE name=?",
                        (change["name"],),
                    )
                if change["empty_reset"]:
                    conn.execute(
                        "UPDATE sources SET consecutive_empty_cycles=0 WHERE name=?",
                        (change["name"],),
                    )
            conn.commit()

        return changes
    finally:
        conn.close()


def _render(vault: Path, changes: list[dict], *, apply: bool) -> str:
    verb = "APPLIED" if apply else "DRY-RUN (no changes written)"
    lines = [f"# reconcile_source_metrics — {verb}", f"Vault: {vault}", ""]
    if not changes:
        lines.append("No wrongly-archived or inflated-empty-streak sources found.")
        return "\n".join(lines) + "\n"
    lines.append(
        "| Source | cited_now | was_status | was_empty | un-archive | reset-empty |"
    )
    lines.append(
        "|--------|-----------|------------|-----------|------------|-------------|"
    )
    for c in changes:
        lines.append(
            f"| {c['name']} | {c['cited_now']} | {c['was_status']} | {c['was_empty']} | "
            f"{'yes' if c['unarchived'] else 'no'} | {'yes' if c['empty_reset'] else 'no'} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Repair spec-029 wrongful source archival (FR-008).",
    )
    parser.add_argument("--vault", required=True, help="Vault root path")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the repairs to sources.db (default: dry-run).",
    )
    args = parser.parse_args(argv)

    vault = Path(args.vault).expanduser().resolve()
    if not _db_path(vault).exists():
        print(f"error: no sources.db under {vault}/_pipeline/", file=sys.stderr)
        return 2

    changes = reconcile(vault, apply=args.apply)
    print(_render(vault, changes, apply=args.apply), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
