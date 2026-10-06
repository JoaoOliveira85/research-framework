#!/usr/bin/env python3
"""Validate vault notes against the quality bar.

Exit codes:
  0 — all checks passed
  1 — violations found (structural, reportable)
  2 — abort (vault directory missing, malformed frontmatter)

Checks performed:
  - frontmatter completeness (title, type, summary, tags, source_urls, related, created, updated)
  - summary ≤ 120 characters
  - source_urls non-empty
  - related wikilinks resolve to existing notes
  - word count ≥ 200 for non-MOC note types
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

REQUIRED_FIELDS = [
    "title",
    "type",
    "summary",
    "tags",
    "source_urls",
    "related",
    "created",
    "updated",
]
SUMMARY_MAX = 120
MIN_WORD_COUNT_DEFAULT = 200
MOC_TYPES = {"moc", "index"}


@dataclass
class Violation:
    file: Path
    field: str
    message: str


@dataclass
class Warning:
    file: Path
    field: str
    message: str


def _parse_frontmatter(path: Path) -> tuple[dict | None, str, str | None]:
    """Return (frontmatter_dict, body, error_message_or_None)."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None, text, "missing YAML frontmatter"
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, text, "frontmatter delimiters malformed"
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as e:
        return None, text, f"YAML parse error: {e}"
    if not isinstance(fm, dict):
        return None, text, "frontmatter is not a mapping"
    return fm, parts[2], None


def _vault_note_stems(vault: Path) -> set[str]:
    """All note stems (filename without .md) in data_vault/."""
    data = vault / "data_vault"
    if not data.exists():
        return set()
    return {p.stem for p in data.rglob("*.md")}


def _lifecycle_created_at_cycle_warnings(path: Path, fm: dict) -> list[Warning]:
    """R-001 / 017: optional field — warn only, never fail."""
    warnings: list[Warning] = []
    life = fm.get("lifecycle")
    if life is None:
        warnings.append(
            Warning(
                path,
                "lifecycle.created_at_cycle",
                "missing (legacy vaults may omit this field)",
            )
        )
        return warnings
    if not isinstance(life, dict):
        warnings.append(
            Warning(
                path,
                "lifecycle.created_at_cycle",
                "lifecycle must be a mapping when present",
            )
        )
        return warnings
    val = life.get("created_at_cycle")
    if val is None:
        warnings.append(
            Warning(
                path,
                "lifecycle.created_at_cycle",
                "missing (legacy vaults may omit this field)",
            )
        )
        return warnings
    ok_int = isinstance(val, int) and not isinstance(val, bool)
    if not ok_int or val < 1:
        warnings.append(
            Warning(
                path,
                "lifecycle.created_at_cycle",
                f"expected integer ≥ 1, got {val!r}",
            )
        )
    return warnings


def _check_note(
    path: Path, vault: Path, known_stems: set[str]
) -> tuple[list[Violation], list[Warning]]:
    violations: list[Violation] = []
    warnings: list[Warning] = []
    fm, body, err = _parse_frontmatter(path)
    if err or fm is None:
        violations.append(Violation(path, "frontmatter", err or "unknown"))
        return violations, warnings

    warnings.extend(_lifecycle_created_at_cycle_warnings(path, fm))

    for field in REQUIRED_FIELDS:
        if field not in fm:
            violations.append(Violation(path, field, "required field missing"))

    summary = fm.get("summary", "")
    if isinstance(summary, str) and len(summary) > SUMMARY_MAX:
        violations.append(
            Violation(
                path,
                "summary",
                f"{len(summary)} chars (limit: {SUMMARY_MAX})",
            )
        )

    sources = fm.get("source_urls")
    if sources is not None and (not isinstance(sources, list) or len(sources) == 0):
        violations.append(
            Violation(path, "source_urls", "empty (at least one required)")
        )

    related = fm.get("related") or []
    if isinstance(related, list):
        for link in related:
            target = str(link).strip("[]")
            if target and target not in known_stems:
                violations.append(
                    Violation(
                        path,
                        "related",
                        f"[[{target}]] — file not found",
                    )
                )

    note_type = str(fm.get("type", "")).lower()
    if note_type not in MOC_TYPES:
        words = len(body.split())
        if words < MIN_WORD_COUNT_DEFAULT:
            violations.append(
                Violation(
                    path,
                    "word_count",
                    f"{words} words (min: {MIN_WORD_COUNT_DEFAULT})",
                )
            )

    return violations, warnings


def validate(vault: Path) -> tuple[list[Violation], list[Warning]]:
    """Return (violations, warnings) for all notes under data_vault/."""
    if not vault.exists() or not vault.is_dir():
        raise FileNotFoundError(f"vault directory not found: {vault}")
    data = vault / "data_vault"
    if not data.exists():
        return [], []

    known_stems = _vault_note_stems(vault)
    violations: list[Violation] = []
    warnings: list[Warning] = []
    for note in sorted(data.rglob("*.md")):
        if _is_scaffold_path(note, data):
            continue
        v, w = _check_note(note, vault, known_stems)
        violations.extend(v)
        warnings.extend(w)
    return violations, warnings


def _is_scaffold_path(note: Path, data_root: Path) -> bool:
    """Skip generator-owned files that don't carry note frontmatter.

    Excluded:

    - ``_index.md`` / ``_concepts.md`` / ``_graph.md`` and any other
      underscore-prefixed file directly under ``data_vault/`` (these are
      re-built each cycle by ``research_framework.vault.indexer``).
    - Anything under ``data_vault/_templates/`` (Jinja-style note-type
      templates with placeholder tokens, not real notes).

    These files were silently producing 16+ "missing YAML frontmatter"
    FAILs per cycle in v0.2.20, which Step 4 reported but the cycle
    runner correctly ignored — making the report a noise source that
    masked real violations on agent-written notes. Filtering at the
    walk level keeps the report focused on note quality.
    """
    try:
        rel = note.relative_to(data_root)
    except ValueError:
        return False
    if "_templates" in rel.parts:
        return True
    # Underscore-prefixed files at the data-vault root are scaffold artefacts
    # (`_index.md`, `_concepts.md`, `_graph.md`). Deeper-nested files starting
    # with `_` (e.g. a category's `_overview.md`) are still validated — only
    # the root-level generator-owned set is skipped.
    if len(rel.parts) == 1 and rel.parts[0].startswith("_"):
        return True
    return False


def format_warnings(warnings: list[Warning], vault: Path) -> str:
    lines: list[str] = []
    for w in warnings:
        try:
            rel = w.file.relative_to(vault)
        except ValueError:
            rel = w.file
        lines.append(f"WARN  {rel}")
        lines.append(f"      {w.field}: {w.message}")
        lines.append("")
    return "\n".join(lines)


def format_violations(violations: list[Violation], vault: Path) -> str:
    """Human-readable report."""
    lines: list[str] = []
    for v in violations:
        try:
            rel = v.file.relative_to(vault)
        except ValueError:
            rel = v.file
        lines.append(f"FAIL  {rel}")
        lines.append(f"      {v.field}: {v.message}")
        lines.append("")
    if violations:
        lines.append(
            f"{len(violations)} violation(s) found. Fix before proceeding to Phase 3."
        )
    else:
        lines.append("all checks passed")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate vault notes against the quality bar."
    )
    parser.add_argument("vault", type=Path, help="Path to vault root directory")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No-op for validator (kept for script-suite uniformity)",
    )
    args = parser.parse_args()

    try:
        violations, warnings = validate(args.vault)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print(format_violations(violations, args.vault))
    if warnings:
        print()
        print(format_warnings(warnings, args.vault).rstrip())
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
