#!/usr/bin/env python3
"""Check that each acronym's first body occurrence is wikilinked.

Acronyms are harvested from note titles containing parenthetical abbreviations, e.g.
"Content Delivery Network (CDN)" registers CDN. For every note, the first occurrence of each
acronym in the body must appear as [[ACRONYM]] (or [[ACRONYM|alias]]) — not bare.

Occurrences inside ``` code fences ```, inline `code`, and URLs are ignored.

Exit codes:
  0 — all acronym first-occurrences are wikilinked
  1 — one or more unlinked first-occurrences found
  2 — abort (vault missing)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

ACRONYM_IN_TITLE = re.compile(r"\(([A-Z]{2,})\)")


def _parse_frontmatter(path: Path) -> tuple[dict | None, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, text
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None, text
    if not isinstance(fm, dict):
        return None, text
    return fm, parts[2]


def _strip_excluded_regions(body: str) -> str:
    """Remove code fences, inline code, URLs, and parenthetical acronym definitions."""
    # Fenced code blocks
    body = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    # Inline code
    body = re.sub(r"`[^`]*`", "", body)
    # URLs (http/https)
    body = re.sub(r"https?://\S+", "", body)
    # Parenthetical acronym definitions: "(ABC)" — these are introductions, not uses
    body = re.sub(r"\([A-Z]{2,}\)", "", body)
    return body


def _harvest_acronyms(vault: Path) -> set[str]:
    acronyms: set[str] = set()
    for note in (vault / "data_vault").rglob("*.md"):
        fm, _ = _parse_frontmatter(note)
        if fm and "title" in fm:
            for match in ACRONYM_IN_TITLE.findall(str(fm["title"])):
                acronyms.add(match)
    return acronyms


def check(vault: Path) -> list[tuple[Path, str]]:
    """Return list of (note_path, acronym) for unlinked first occurrences."""
    if not vault.exists() or not vault.is_dir():
        raise FileNotFoundError(f"vault directory not found: {vault}")
    data = vault / "data_vault"
    if not data.exists():
        return []

    acronyms = _harvest_acronyms(vault)
    violations: list[tuple[Path, str]] = []

    for note in sorted(data.rglob("*.md")):
        fm, body = _parse_frontmatter(note)
        if fm is None:
            continue
        stripped = _strip_excluded_regions(body)
        for acronym in acronyms:
            wikilinked = re.search(
                rf"\[\[{re.escape(acronym)}(?:\|[^\]]+)?\]\]", stripped
            )
            bare = re.search(rf"(?<![\[\w]){re.escape(acronym)}(?![\]\w])", stripped)
            if bare and (not wikilinked or bare.start() < wikilinked.start()):
                violations.append((note, acronym))
    return violations


def format_report(violations: list[tuple[Path, str]], vault: Path) -> str:
    lines: list[str] = []
    for path, acronym in violations:
        try:
            rel = path.relative_to(vault)
        except ValueError:
            rel = path
        lines.append(f"FAIL  {rel}")
        lines.append(f"      acronym: {acronym} (first occurrence not wikilinked)")
        lines.append("")
    if violations:
        lines.append(f"{len(violations)} unlinked first-occurrence(s) found.")
    else:
        lines.append("all acronym first-occurrences are wikilinked")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check acronym first-occurrence wikilinks in vault notes."
    )
    parser.add_argument("vault", type=Path, help="Path to vault root directory")
    args = parser.parse_args()

    try:
        violations = check(args.vault)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print(format_report(violations, args.vault))
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
