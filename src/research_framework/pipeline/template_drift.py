"""Per-file template-version reader; shared by vault_audit and the migrator."""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.vault.frontmatter import (
    FrontmatterParseError,
    parse_frontmatter,
)

__all__ = ["read_template_version"]

_TEMPLATE_VERSION_KEY = "_template_version"
_SIBLING_JSON = ".tmpl-versions.json"


def _parse_md_frontmatter(path: Path) -> dict | None:
    try:
        fm, _body = parse_frontmatter(path)
    except (OSError, FrontmatterParseError):
        return None
    return fm or None


def read_template_version(path: Path) -> int | None:
    """Return the recorded template version for a scaffold file, or None.

    For markdown files: reads ``_template_version`` from YAML frontmatter.
    For other files: reads the file's name from a sibling ``.tmpl-versions.json``.
    Returns None when the version is absent or the metadata is malformed.
    """
    if path.suffix.lower() == ".md":
        fm = _parse_md_frontmatter(path)
        if fm is None:
            return None
        val = fm.get(_TEMPLATE_VERSION_KEY)
        if isinstance(val, int):
            return val
        return None

    sibling = path.parent / _SIBLING_JSON
    if not sibling.exists():
        return None
    try:
        data = json.loads(sibling.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    val = data.get(path.name)
    if isinstance(val, int):
        return val
    return None
