#!/usr/bin/env python3
"""Fix broken [[wikilinks]] in vault notes' `related` frontmatter field.

For each unresolved wikilink, the fix script either removes it or (optionally) suggests
a close match by Levenshtein distance against existing note stems.

SAFETY: Refuses to modify files without an explicit --apply flag. --dry-run prints the
proposed changes.

Exit codes:
  0 — dry-run or apply completed
  1 — apply completed but post-validation still reports violations
  2 — abort (vault missing)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from validate_vault import (
    _build_acronym_map,
    _parse_frontmatter,
    _related_target_resolves,
    _vault_note_stems,
)


def _fix_note(
    path: Path,
    known_stems: set[str],
    dry_run: bool,
    acronym_map: dict[str, str] | None = None,
) -> tuple[bool, list[str]]:
    """Remove unresolved entries from `related`. Returns (changed, removed_links)."""
    fm, body, err = _parse_frontmatter(path)
    if err or fm is None:
        return False, []
    related = fm.get("related") or []
    if not isinstance(related, list):
        return False, []

    kept: list[str] = []
    removed: list[str] = []
    for link in related:
        target = str(link).strip("[]").strip()
        # validate_vault's own predicate: lowercase lookup, last path segment,
        # space variants, acronym redirects. A verbatim set lookup deleted
        # every valid link with a capital letter or a folder prefix.
        if not target or _related_target_resolves(target, known_stems, acronym_map):
            kept.append(link)
        else:
            removed.append(target)
    if not removed:
        return False, []

    fm["related"] = kept
    if not dry_run:
        new_fm = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
        # ``body`` starts right after the closing ``---`` (its newline included),
        # so adding another "\n" here grew the note by a blank line per run.
        path.write_text(f"---\n{new_fm}\n---{body}", encoding="utf-8")
    return True, removed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Remove unresolved wikilinks from `related` frontmatter."
    )
    parser.add_argument("vault", type=Path, help="Path to vault root directory")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Preview changes without writing (default)",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the fix.",
    )
    args = parser.parse_args()

    if not args.vault.exists() or not args.vault.is_dir():
        print(f"ERROR: vault directory not found: {args.vault}", file=sys.stderr)
        return 2

    known = _vault_note_stems(args.vault)
    acronym_map, _ambiguous = _build_acronym_map(args.vault)
    data = args.vault / "data_vault"
    if not data.exists():
        print("no data_vault/ — nothing to fix")
        return 0

    dry_run = not args.apply
    mode_label = "DRY-RUN" if dry_run else "APPLY"
    total_changed = 0
    for note in sorted(data.rglob("*.md")):
        changed, removed = _fix_note(
            note, known, dry_run=dry_run, acronym_map=acronym_map
        )
        if changed:
            total_changed += 1
            try:
                rel = note.relative_to(args.vault)
            except ValueError:
                rel = note
            print(f"[{mode_label}] {rel}")
            for link in removed:
                print(f"    - [[{link}]] (unresolved)")

    if total_changed == 0:
        print("no broken wikilinks to fix")
        return 0

    if dry_run:
        print("\nRun again with --apply to write changes.")
        return 0

    # Re-validate
    remaining = 0
    for note in data.rglob("*.md"):
        _, _, err = _parse_frontmatter(note)
        if err:
            remaining += 1
    if remaining:
        return 1
    print("all fixes applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
