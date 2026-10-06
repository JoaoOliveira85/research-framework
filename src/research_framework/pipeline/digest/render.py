"""Jinja2 render pass for cross-cycle digest (spec 035 FR-012)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from .ranker import format_progress_delta, format_progress_pct
from .scope import DigestScope
from .sections import build_sections

_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_digest(
    vault_dir: Path,
    scope: DigestScope,
    *,
    rendered_at: datetime | None = None,
) -> str:
    sections = build_sections(vault_dir, scope)
    stamp = rendered_at or datetime.now(UTC)
    return (
        _env()
        .get_template("digest.md.j2")
        .render(
            vault_identity=scope.vault_identity,
            start=scope.date_range.start.isoformat(),
            end=scope.date_range.end.isoformat(),
            rendered_at=stamp.astimezone(UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            git_base=scope.git_base,
            git_head=scope.git_head,
            sections=sections,
            format_progress_pct=format_progress_pct,
            format_progress_delta=format_progress_delta,
        )
    )


def strip_rendered_at_line(markdown: str) -> str:
    lines = [
        line for line in markdown.splitlines() if not line.startswith("_rendered-at:")
    ]
    trailing = markdown.endswith("\n")
    out = "\n".join(lines)
    return out + ("\n" if trailing else "")


__all__ = ["render_digest", "strip_rendered_at_line"]
