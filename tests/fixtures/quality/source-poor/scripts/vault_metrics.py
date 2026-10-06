#!/usr/bin/env python3
"""Vault metrics snapshot.

Produces a JSON snapshot of vault state: note counts, word count distribution, unresolved
wikilinks. Writes to stdout by default, or to --output path.

Always exits 0 (informational, never fails).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

WIKILINK = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]")


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


def _bucket(word_count: int) -> str:
    if word_count < 200:
        return "<200"
    if word_count < 500:
        return "200-499"
    if word_count < 1000:
        return "500-999"
    return "1000+"


def collect(vault: Path) -> dict:
    """Return a metrics snapshot dict."""
    data = vault / "data_vault"
    by_type: dict[str, int] = {}
    by_folder: dict[str, int] = {}
    word_count_buckets: dict[str, int] = {
        "<200": 0,
        "200-499": 0,
        "500-999": 0,
        "1000+": 0,
    }
    unresolved_set: set[str] = set()
    note_count = 0
    known_stems: set[str] = set()

    if data.exists():
        known_stems = {p.stem for p in data.rglob("*.md")}
        for note in data.rglob("*.md"):
            note_count += 1
            fm, body = _parse_frontmatter(note)
            ntype = str((fm or {}).get("type", "unknown"))
            by_type[ntype] = by_type.get(ntype, 0) + 1
            folder = note.parent.name
            by_folder[folder] = by_folder.get(folder, 0) + 1
            word_count_buckets[_bucket(len(body.split()))] += 1
            for target in WIKILINK.findall(body):
                target = target.strip()
                if target and target not in known_stems:
                    unresolved_set.add(target)

    unresolved_references = sorted(unresolved_set)
    return {
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "vault": str(vault),
        "note_count": note_count,
        "active_notes": note_count,
        "by_type": by_type,
        "by_folder": by_folder,
        "word_count_buckets": word_count_buckets,
        "unresolved_wikilinks": len(unresolved_references),
        "unresolved_references": unresolved_references,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect vault metrics snapshot.")
    parser.add_argument("vault", type=Path, help="Path to vault root directory")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional file path; prints to stdout if omitted",
    )
    args = parser.parse_args()

    if not args.vault.exists() or not args.vault.is_dir():
        print(f"ERROR: vault directory not found: {args.vault}", file=sys.stderr)
        return 2

    snapshot = collect(args.vault)
    payload = json.dumps(snapshot, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
