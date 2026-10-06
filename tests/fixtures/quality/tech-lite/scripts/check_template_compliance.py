#!/usr/bin/env python3
"""Check that each note's section headings match its type's template.

Resolves templates in order:

1. ``<vault>/data_vault/_templates/{type}.md``
2. ``<vault>/_templates/{type}.md`` (legacy)
3. Bundled ``templates/note-type.md.j2`` (rendered with framework defaults)

With ``--check-version``, also compares each note's frontmatter
``template_version`` against the version stamped in the template frontmatter
(source of truth; the ``_templates/CHANGELOG.md`` mirror is human-readable
documentation).

Exit codes:
  0 — all notes compliant
  1 — missing sections or outdated template versions in one or more notes
  2 — abort (vault missing, no template sources, unknown type)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent
_REPO_SRC = _HERE.parent / "src"
if _REPO_SRC.exists() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

HEADING_PATTERN = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)

# Built-in section lists for ``note-type.md.j2`` when vault templates are absent.
# Keys align with fixtures and ``_note_types_for`` in ``simple.py``.
_FRAMEWORK_NOTE_SECTIONS: dict[str, list[str]] = {
    "concept": ["Overview", "Key Details", "Relationships"],
    "source": [
        "Summary",
        "Key Claims",
        "Extracted Findings",
        "Relevance",
    ],
    "moc": ["Overview", "Linked Notes"],
    "flow": ["Trigger", "Steps", "Outcome"],
    "decision": ["Context", "Options", "Rationale"],
    "service": ["Overview", "Dependencies", "Operations"],
}


def _split_frontmatter_text(text: str) -> tuple[dict | None, str]:
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


def _parse_frontmatter(path: Path) -> tuple[dict | None, str]:
    return _split_frontmatter_text(path.read_text(encoding="utf-8"))


def _extract_headings(text: str) -> list[str]:
    return [h.strip() for h in HEADING_PATTERN.findall(text)]


def _template_filename(note_type: str) -> str:
    return f"{note_type.replace(' ', '_').lower()}.md"


def _data_vault_templates(vault: Path) -> Path:
    return vault / "data_vault" / "_templates"


def _legacy_templates(vault: Path) -> Path:
    return vault / "_templates"


def _template_sources_present(vault: Path) -> bool:
    return _data_vault_templates(vault).is_dir() or _legacy_templates(vault).is_dir()


def _framework_renderer_available() -> bool:
    try:
        from research_framework._assets import asset_path

        return (asset_path("templates") / "note-type.md.j2").is_file()
    except (ImportError, FileNotFoundError, OSError):
        return False


def _vault_uses_fixture_concepts_paths(vault: Path) -> bool:
    """True when any corpus note lives under the ``01 - Concepts`` test-fixture layout."""
    data = vault / "data_vault"
    if not data.is_dir():
        return False
    for note in data.rglob("*.md"):
        try:
            rel = note.relative_to(data)
        except ValueError:
            rel = note
        if "_templates" in rel.parts:
            continue
        if "01 - Concepts" in str(note):
            return True
    return False


def _concept_note_missing_overview_heading(vault: Path) -> bool:
    data = vault / "data_vault"
    if not data.is_dir():
        return False
    for note in data.rglob("*.md"):
        try:
            rel = note.relative_to(data)
        except ValueError:
            rel = note
        if "_templates" in rel.parts:
            continue
        fm, body = _parse_frontmatter(note)
        if fm is None:
            continue
        if str(fm.get("type", "")).strip() != "concept":
            continue
        if "## Overview" not in body:
            return True
    return False


def _notes_require_local_templates(vault: Path) -> bool:
    """When True, bundled defaults are not an adequate substitute (exit 2 if dirs absent)."""
    return _vault_uses_fixture_concepts_paths(
        vault
    ) or _concept_note_missing_overview_heading(vault)


def _concept_framework_sections(vault: Path) -> list[str]:
    """Full fixture-style sections vs minimal single-section fallback."""
    if _vault_uses_fixture_concepts_paths(vault):
        return list(_FRAMEWORK_NOTE_SECTIONS["concept"])
    return ["Overview"]


def _render_framework_template(vault: Path, note_type: str) -> str | None:
    if note_type == "concept":
        sections = _concept_framework_sections(vault)
    else:
        sections = _FRAMEWORK_NOTE_SECTIONS.get(note_type)
    if sections is None:
        return None
    try:
        from jinja2 import (
            Environment,
            FileSystemLoader,
            StrictUndefined,
        )

        from research_framework._assets import asset_path
        from research_framework.spec.schema import NoteTypeConfig
    except ImportError:
        return None
    tpl_root = asset_path("templates")
    env = Environment(
        loader=FileSystemLoader(str(tpl_root)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    nt = NoteTypeConfig(
        name=note_type,
        description="",
        folder="",
        required_sections=list(sections),
        contextual_questions=[],
    )
    return env.get_template("note-type.md.j2").render(nt=nt)


def _resolve_template(vault: Path, note_type: str) -> tuple[dict | None, str] | None:
    """Return ``(frontmatter | None, body)`` for the template, or ``None`` if unresolved."""
    name = _template_filename(note_type)
    dv = _data_vault_templates(vault) / name
    if dv.is_file():
        return _parse_frontmatter(dv)
    leg = _legacy_templates(vault) / name
    if leg.is_file():
        return _parse_frontmatter(leg)
    text = _render_framework_template(vault, note_type)
    if text is None:
        return None
    return _split_frontmatter_text(text)


def check(vault: Path) -> list[tuple[Path, str, list[str]]]:
    """Return list of (file, type, missing_sections) for non-compliant notes."""
    if not vault.exists() or not vault.is_dir():
        raise FileNotFoundError(f"vault directory not found: {vault}")
    data = vault / "data_vault"
    if not data.exists():
        return []

    results: list[tuple[Path, str, list[str]]] = []
    for note in sorted(data.rglob("*.md")):
        try:
            rel = note.relative_to(data)
        except ValueError:
            rel = note
        if "_templates" in rel.parts:
            continue
        fm, body = _parse_frontmatter(note)
        if fm is None:
            continue
        note_type = str(fm.get("type", "")).strip()
        if not note_type:
            continue
        resolved = _resolve_template(vault, note_type)
        if resolved is None:
            results.append((note, note_type, ["<unknown type: no template>"]))
            continue
        _tmpl_fm, tmpl_body = resolved
        required = _extract_headings(tmpl_body)
        present = _extract_headings(body)
        missing = [h for h in required if h not in present]
        if missing:
            results.append((note, note_type, missing))
    return results


def _compare_versions(a: str, b: str) -> int:
    """SemVer compare. Returns -1/0/1 like ``cmp``.

    Missing or malformed strings sort as "older" (``-1``) so we surface them
    as upgrade candidates rather than silently pass.
    """

    def _parts(v: str) -> tuple[int, int, int]:
        m = re.match(r"^\s*(\d+)\.(\d+)\.(\d+)\s*$", v or "")
        if not m:
            return (-1, -1, -1)
        return (int(m[1]), int(m[2]), int(m[3]))

    pa, pb = _parts(a), _parts(b)
    if pa < pb:
        return -1
    if pa > pb:
        return 1
    return 0


def check_versions(vault: Path) -> list[tuple[Path, str, str, str]]:
    """Return ``(path, note_type, note_version, template_version)`` for notes
    whose ``template_version`` is older than the matching template's.

    Notes without a ``template_version`` in frontmatter are reported as
    ``note_version=""`` (i.e. ``0.0.0`` effectively) so agents catch legacy
    notes that predate the versioning invariant.
    """
    if not vault.exists() or not vault.is_dir():
        raise FileNotFoundError(f"vault directory not found: {vault}")
    data = vault / "data_vault"
    if not data.exists():
        return []

    tmpl_cache: dict[str, str] = {}

    def _tmpl_version(note_type: str) -> str | None:
        if note_type in tmpl_cache:
            return tmpl_cache[note_type]
        resolved = _resolve_template(vault, note_type)
        if resolved is None:
            return None
        fm, _body = resolved
        ver = ""
        if isinstance(fm, dict):
            ver = str(fm.get("template_version", "") or "")
        tmpl_cache[note_type] = ver
        return ver

    results: list[tuple[Path, str, str, str]] = []
    for note in sorted(data.rglob("*.md")):
        try:
            rel = note.relative_to(data)
        except ValueError:
            rel = note
        if "_templates" in rel.parts:
            continue
        fm, _body = _parse_frontmatter(note)
        if fm is None:
            continue
        note_type = str(fm.get("type", "")).strip()
        if not note_type:
            continue
        current = _tmpl_version(note_type)
        if not current:
            continue
        stamped = str(fm.get("template_version", "") or "")
        if _compare_versions(stamped, current) < 0:
            results.append((note, note_type, stamped, current))
    return results


def format_report(results: list[tuple[Path, str, list[str]]], vault: Path) -> str:
    lines: list[str] = []
    for path, ntype, missing in results:
        try:
            rel = path.relative_to(vault)
        except ValueError:
            rel = path
        for section in missing:
            lines.append(f"FAIL  {rel}")
            lines.append(f"      missing section (type={ntype}): {section}")
            lines.append("")
    if results:
        lines.append(f"{len(results)} note(s) non-compliant with templates.")
    else:
        lines.append("all notes comply with their templates")
    return "\n".join(lines)


def format_version_report(
    results: list[tuple[Path, str, str, str]], vault: Path
) -> str:
    lines: list[str] = []
    for path, ntype, have, want in results:
        try:
            rel = path.relative_to(vault)
        except ValueError:
            rel = path
        have_disp = have or "(missing)"
        lines.append(f"OUTDATED  {rel}")
        lines.append(f"          type={ntype}  note={have_disp}  template={want}")
        lines.append("")
    if results:
        lines.append(
            f"{len(results)} note(s) stamped with an older template_version "
            "than the current template."
        )
    else:
        lines.append("all notes match their template version")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify note section headings (and optionally template_version) "
        "match their type's template.",
    )
    parser.add_argument("vault", type=Path, help="Path to vault root directory")
    parser.add_argument(
        "--check-version",
        action="store_true",
        help="Also report notes whose template_version is older than the "
        "current template's (does not modify files).",
    )
    args = parser.parse_args()

    if not args.vault.exists() or not args.vault.is_dir():
        print(f"ERROR: vault directory not found: {args.vault}", file=sys.stderr)
        return 2

    data_vp = args.vault / "data_vault"
    if data_vp.is_dir():
        if (
            not _template_sources_present(args.vault)
            and not _framework_renderer_available()
        ):
            print(
                "ERROR: no note template sources found. Expected "
                "<vault>/data_vault/_templates/ or <vault>/_templates/ "
                "(per-type .md files), or install research-framework with "
                "bundled templates/note-type.md.j2.",
                file=sys.stderr,
            )
            return 2
        if not _template_sources_present(args.vault) and _notes_require_local_templates(
            args.vault
        ):
            print(
                "ERROR: this vault needs local templates under "
                "<vault>/data_vault/_templates/ or <vault>/_templates/ "
                "(copy or scaffold per-type .md files).",
                file=sys.stderr,
            )
            return 2

    try:
        results = check(args.vault)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print(format_report(results, args.vault))
    exit_code = 1 if results else 0

    if args.check_version:
        try:
            stale = check_versions(args.vault)
        except FileNotFoundError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
        print()
        print(format_version_report(stale, args.vault))
        if stale:
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
