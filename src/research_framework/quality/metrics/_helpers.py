"""Shared helpers for quality metric calculators (spec 022 US2)."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from research_framework.vault.frontmatter import (
    FrontmatterParseError,
)
from research_framework.vault.frontmatter import (
    parse_frontmatter as _canonical_parse_frontmatter,
)
from research_framework.vault.frontmatter import (
    parse_frontmatter_str as _canonical_parse_frontmatter_str,
)

HEADING_PATTERN = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
ACRONYM_IN_TITLE = re.compile(r"\(([A-Z]{2,})\)")

UNMEASURED_KEY = "unmeasured"
"""Family-block key mapping a metric name to why it could not be measured."""


def record_ratio(
    block: dict[str, Any],
    name: str,
    numerator: float,
    denominator: float,
    *,
    reason: str,
) -> None:
    """Store ``numerator / denominator`` under *name* — or mark it unmeasured.

    A ratio with an empty denominator is not zero, it is *unmeasured*: no
    acronym ever occurred, no citation resolved, no note was written. Reporting
    those as ``0.0`` made a non-measurement look like a reading, and against the
    ``0.0`` baseline it had been blessed into, like a passing gate (issue #268).
    An unmeasured metric is stored as ``None`` with its reason recorded under
    ``block["unmeasured"]``, so the regression diff can say so instead of
    silently ticking it green.
    """
    if denominator <= 0:
        block[name] = None
        block.setdefault(UNMEASURED_KEY, {})[name] = reason
        return
    block[name] = truncate_float(numerator / denominator)


def truncate_float(value: float) -> float:
    """Truncate *value* to four decimal places (matches determinism contract)."""
    if math.isnan(value) or math.isinf(value):
        return value
    return float(f"{value:.4f}")


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from *path*; return ``{}`` on missing or invalid."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def split_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    try:
        fm, body = _canonical_parse_frontmatter_str(text)
    except FrontmatterParseError:
        return None, text
    if not fm:
        return None, body
    return fm, body


def parse_frontmatter(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        fm, body = _canonical_parse_frontmatter(path)
    except FrontmatterParseError:
        return None, path.read_text(encoding="utf-8")
    if not fm:
        return None, body
    return fm, body


def extract_headings(text: str) -> list[str]:
    return [h.strip() for h in HEADING_PATTERN.findall(text)]


def template_filename(note_type: str) -> str:
    return f"{note_type.replace(' ', '_').lower()}.md"


def resolve_template_path(vault_dir: Path, note_type: str) -> Path | None:
    name = template_filename(note_type)
    dv = vault_dir / "data_vault" / "_templates" / name
    if dv.is_file():
        return dv
    leg = vault_dir / "_templates" / name
    if leg.is_file():
        return leg
    return None


def required_count(cat: dict[str, Any]) -> int:
    if "required_count" in cat:
        return int(cat["required_count"])
    return int(cat.get("target_count", 0))


def current_count(cat: dict[str, Any]) -> int:
    if "current" in cat:
        return int(cat["current"])
    return int(cat.get("met_count", 0))
