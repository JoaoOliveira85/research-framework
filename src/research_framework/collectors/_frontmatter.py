"""Markdown + YAML frontmatter writer for raw collected items.

Replaces ``write_pipeline_file`` / ``format_pipeline_subreddit`` from feeds-vault.

Usage::

    from research_framework.collectors._frontmatter import write

    write(
        path,
        fm={"source_kind": "rss", "source_id": "...", ...},
        body="article text here",
    )
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml as _yaml

    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


def _render_frontmatter(fm: dict[str, Any]) -> str:
    """Render a frontmatter dict to a YAML block (between ``---`` delimiters)."""
    if _HAS_YAML:
        body = _yaml.dump(
            fm, default_flow_style=False, allow_unicode=True, sort_keys=False
        )
    else:
        # Minimal hand-rolled serialiser — only handles str/int/bool/None scalars
        lines = []
        for k, v in fm.items():
            if v is None:
                lines.append(f"{k}: null")
            elif isinstance(v, bool):
                lines.append(f"{k}: {str(v).lower()}")
            elif isinstance(v, (int, float)):
                lines.append(f"{k}: {v}")
            else:
                escaped = str(v).replace('"', '\\"')
                lines.append(f'{k}: "{escaped}"')
        body = "\n".join(lines) + "\n"
    return f"---\n{body}---\n"


def write(path: Path, fm: dict[str, Any], body: str) -> None:
    """Write a markdown file at *path* with YAML frontmatter *fm* and *body*.

    Creates parent directories as needed.  Overwrites any existing file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    content = _render_frontmatter(fm) + "\n" + body.rstrip() + "\n"
    path.write_text(content, encoding="utf-8")
