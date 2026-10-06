"""Shared helpers for research_framework processors.

Path conventions, frontmatter I/O, and content hashing used by all four
processor modules (extract, preprocess, verify, archive).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path conventions  (contract — matches raw-item.schema.json)
# ---------------------------------------------------------------------------


def raw_dir(vault: Path) -> Path:
    """<vault>/_pipeline/raw/"""
    return vault / "_pipeline" / "raw"


def raw_item_path(vault: Path, source_kind: str, source_id: str) -> Path:
    """<vault>/_pipeline/raw/<source_kind>/<source_id>.md"""
    return raw_dir(vault) / source_kind / f"{source_id}.md"


def extracted_dir(vault: Path) -> Path:
    """<vault>/_pipeline/extracted/"""
    return vault / "_pipeline" / "extracted"


def excerpts_dir(vault: Path) -> Path:
    """<vault>/_pipeline/extracted/excerpts/"""
    return extracted_dir(vault) / "excerpts"


def logs_dir(vault: Path) -> Path:
    """<vault>/_pipeline/logs/"""
    return vault / "_pipeline" / "logs"


def archive_dir(vault: Path) -> Path:
    """<vault>/_pipeline/archive/"""
    return vault / "_pipeline" / "archive"


def archive_item_path(
    vault: Path, year_month: str, source_kind: str, source_id: str
) -> Path:
    """<vault>/_pipeline/archive/<YYYY-MM>/<source_kind>/<source_id>.md"""
    return archive_dir(vault) / year_month / source_kind / f"{source_id}.md"


# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    # Holdout from spec 025 B4 canonical parser migration.
    # Reason: raw-item processors use a line-scalar parser (``dict[str, str]``),
    # not full YAML; switching would change validation for pipeline raw files.
    #
    # SCOPE — ``_pipeline`` RAW ITEMS ONLY (``extract``, ``archive``).  This is
    # NOT a YAML parser: it flattens lists to strings, drops nesting (a nested
    # key wins over the top-level one of the same name), and strips quotes.
    # Reading a vault NOTE with it and writing the result back destroys
    # frontmatter — that is exactly what ``verify`` did until it was moved to
    # ``vault.frontmatter``.  For notes, use that canonical codec.
    """Return (metadata_dict, body).  Handles simple key: value YAML."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_block = text[3:end].strip()
    body = text[end + 4 :].lstrip()
    metadata: dict[str, str] = {}
    for line in fm_block.splitlines():
        line = line.strip()
        if ":" in line and not line.startswith("-"):
            key, _, val = line.partition(":")
            metadata[key.strip()] = val.strip().strip('"').strip("'")
    return metadata, body


def write_frontmatter(path: Path, metadata: dict[str, Any], body: str) -> None:
    """Write a file with YAML frontmatter (key: value, no quoting of simple values)."""
    fm_lines = ["---"]
    for key, val in metadata.items():
        if isinstance(val, str) and any(c in val for c in ':"{}[]|>&*!,%@`'):
            fm_lines.append(f'{key}: "{val}"')
        else:
            fm_lines.append(f"{key}: {val}")
    fm_lines.append("---")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(fm_lines) + "\n\n" + body.strip() + "\n", encoding="utf-8"
    )


def read_raw_item(path: Path) -> tuple[dict[str, str], str]:
    """Read a raw pipeline item; return (frontmatter_dict, body)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return {}, ""
    return parse_frontmatter(text)


# ---------------------------------------------------------------------------
# Content hashing
# ---------------------------------------------------------------------------


def content_hash(text: str) -> str:
    """Return SHA-256 hex digest of the given text."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


# ---------------------------------------------------------------------------
# Raw-item schema validation
# ---------------------------------------------------------------------------

_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "specs"
    / "015f-processors-in-framework"
    / "contracts"
    / "raw-item.schema.json"
)

_REQUIRED_FIELDS = ("source_kind", "source_id", "collected_at")


def validate_raw_item(
    metadata: dict[str, Any], path: Path | str | None = None
) -> list[str]:
    """Validate frontmatter against the raw-item contract.

    Returns a list of error strings (empty = valid).  Intentionally lightweight
    (no jsonschema dep) — checks only required fields and collected_at format.
    """
    errors: list[str] = []
    label = str(path) if path else "<unknown>"
    for field in _REQUIRED_FIELDS:
        if not metadata.get(field):
            errors.append(f"{label}: missing required frontmatter field '{field}'")
    collected_at = metadata.get("collected_at", "")
    if collected_at and not _looks_like_date(collected_at):
        errors.append(
            f"{label}: 'collected_at' must start with YYYY-MM-DD, got {collected_at!r}"
        )
    return errors


def _looks_like_date(s: str) -> bool:
    import re

    return bool(re.match(r"^\d{4}-\d{2}-\d{2}", s))


# ---------------------------------------------------------------------------
# Processor config defaults
# ---------------------------------------------------------------------------

PROCESSOR_DEFAULTS: dict[str, Any] = {
    "extract": {
        "enabled": True,
        "model": "claude-haiku-4-5",
        "context_tree_target": "_pipeline/extracted/context-tree.md",
        "workers": 5,
        "haiku_max_chars": 720_000,
    },
    "preprocess": {
        "enabled": True,
        "dedupe_strategy": "content_hash",  # or "url"
        "source_types": ["youtube", "reddit", "web"],
    },
    "verify": {
        "enabled": True,
        "haiku_first_pass": True,
        "sonnet_deep_review": True,
        "fail_threshold": 0.20,
        "auto_fix": True,
    },
    "archive": {
        "enabled": True,
        "after_days": 90,
    },
}


def processor_config(
    spec_processors: dict[str, Any] | None, name: str
) -> dict[str, Any]:
    """Merge spec processor config with defaults for the given processor name."""
    defaults = dict(PROCESSOR_DEFAULTS.get(name, {}))
    if spec_processors and name in spec_processors:
        user = spec_processors[name] or {}
        defaults.update({k: v for k, v in user.items() if v is not None})
    return defaults
