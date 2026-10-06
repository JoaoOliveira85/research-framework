#!/usr/bin/env python3
"""Add wikilinks to first-occurrence unlinked acronyms in vault notes.

SAFETY: Refuses to modify files without an explicit --apply flag. --dry-run prints the
proposed changes. This matches constitution principle III (no write without dry-run review).

Exit codes:
  0 — success (dry-run or apply completed cleanly)
  1 — post-apply validation still reports violations
  2 — abort (vault missing, invalid args)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from check_acronym_links import (
    _strip_excluded_regions,
    check,
)


def _fix_note(path: Path, acronym: str, dry_run: bool) -> tuple[bool, str]:
    """Wikilink the first bare occurrence of `acronym` in the note body.

    Returns (changed, diff_preview).
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return False, ""
    parts = text.split("---", 2)
    if len(parts) < 3:
        return False, ""
    head = "---" + parts[1] + "---"
    body = parts[2]

    stripped = _strip_excluded_regions(body)
    bare = re.search(rf"(?<![\[\w]){re.escape(acronym)}(?![\]\w])", stripped)
    if not bare:
        return False, ""

    # Map position in stripped body back to original body (approximate — use first match
    # in original body that is NOT already inside [[ ]]).
    pattern = re.compile(rf"(?<![\[\w]){re.escape(acronym)}(?![\]\w])")
    new_body, count = pattern.subn(f"[[{acronym}]]", body, count=1)
    if count == 0:
        return False, ""

    diff = f"--- {path}\n+++ {path}\n@@ wikilink first occurrence of {acronym} @@\n"
    if not dry_run:
        path.write_text(head + new_body, encoding="utf-8")
    return True, diff


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Wikilink first-occurrence acronyms in vault notes."
    )
    parser.add_argument("vault", type=Path, help="Path to vault root directory")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Preview changes without modifying files (default)",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the fix. Required for any file modification.",
    )
    args = parser.parse_args()

    if not args.vault.exists() or not args.vault.is_dir():
        print(f"ERROR: vault directory not found: {args.vault}", file=sys.stderr)
        return 2

    try:
        violations = check(args.vault)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if not violations:
        print("no unlinked acronyms to fix")
        return 0

    dry_run = not args.apply
    mode_label = "DRY-RUN" if dry_run else "APPLY"
    print(f"[{mode_label}] {len(violations)} unlinked acronym(s) found")
    for path, acronym in violations:
        changed, diff = _fix_note(path, acronym, dry_run=dry_run)
        if changed:
            print(diff)

    if dry_run:
        print("\nRun again with --apply to write changes.")
        return 0

    # Re-validate after apply
    post = check(args.vault)
    if post:
        print(f"WARN: {len(post)} violation(s) remain after apply")
        return 1
    print("all fixes applied; validation clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
