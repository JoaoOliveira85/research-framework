"""Cross-cycle digest package (spec 035)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .render import render_digest
from .scope import CycleScope, DateRange, DigestScope, build_scope


@dataclass(frozen=True)
class DigestResult:
    exit_code: int
    message: str
    output_path: Path | None
    markdown: str | None


def build_digest(
    vault_dir: Path,
    *,
    date_range: DateRange,
    rendered_at: datetime | None = None,
) -> tuple[str, DigestScope]:
    scope = build_scope(vault_dir, date_range)
    markdown = render_digest(vault_dir, scope, rendered_at=rendered_at)
    return markdown, scope


def default_output_path(vault_dir: Path, date_range: DateRange) -> Path:
    start = date_range.start.isoformat()
    end = date_range.end.isoformat()
    return vault_dir / "_pipeline" / "digests" / f"digest-{start}--{end}.md"


def run_digest(
    vault_dir: Path,
    *,
    date_range: DateRange,
    output_path: Path | None = None,
    rendered_at: datetime | None = None,
) -> DigestResult:
    scope = build_scope(vault_dir, date_range)
    if not scope.cycles:
        return DigestResult(
            exit_code=0, message="No cycles in scope", output_path=None, markdown=None
        )

    markdown, _scope = build_digest(
        vault_dir, date_range=date_range, rendered_at=rendered_at
    )
    dest = output_path or default_output_path(vault_dir, date_range)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(markdown, encoding="utf-8")
    return DigestResult(
        exit_code=0, message=str(dest), output_path=dest, markdown=markdown
    )


__all__ = [
    "CycleScope",
    "DateRange",
    "DigestResult",
    "DigestScope",
    "build_digest",
    "build_scope",
    "default_output_path",
    "run_digest",
]
