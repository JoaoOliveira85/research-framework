"""Cloud-folder mirror delivery (spec 040 FR-013..015, Q4)."""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from research_framework.pipeline.settings import ReportsSettings

_LOG = logging.getLogger(__name__)
_MAX_RETRIES = 3
_BACKOFF_SECONDS = 1.0


def _report_paths(vault_dir: Path) -> list[Path]:
    paths: list[Path] = []
    pipeline = vault_dir / "_pipeline"
    for name in ("audit-report.md", "audit-report.pdf"):
        path = pipeline / name
        if path.is_file():
            paths.append(path)
    cycles = pipeline / "cycles"
    if cycles.is_dir():
        for path in sorted(cycles.glob("cycle-*-report.md")):
            paths.append(path)
        for path in sorted(cycles.glob("cycle-*-report.pdf")):
            paths.append(path)
    digests = pipeline / "digests"
    if digests.is_dir():
        for path in sorted(digests.glob("*")):
            if path.suffix in {".md", ".pdf"} and path.is_file():
                paths.append(path)
    return paths


def mirror_reports(
    vault_dir: Path,
    *,
    target: str | Path | None,
    settings: ReportsSettings | None = None,
) -> bool:
    """Copy report artifacts to ``target``; return True when any file copied."""
    mirror_target = target
    if mirror_target is None and settings is not None:
        mirror_target = settings.mirror.target
    if not mirror_target:
        return False
    dest_root = Path(mirror_target)
    sources = _report_paths(vault_dir)
    if not sources:
        return False
    last_error: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            dest_root.mkdir(parents=True, exist_ok=True)
            for src in sources:
                rel = src.relative_to(vault_dir)
                dest = dest_root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            return True
        except OSError as exc:
            last_error = exc
            if attempt < _MAX_RETRIES:
                time.sleep(_BACKOFF_SECONDS)
    _LOG.warning("mirror skipped: target unavailable (%s)", last_error)
    return False


__all__ = ["mirror_reports"]
