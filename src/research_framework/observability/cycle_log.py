"""Per-cycle ``cycle.log`` FileHandler lifecycle (spec 048 v1.1 D2)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_LOG = logging.getLogger(__name__)

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

__all__ = ["cycle_log_handler"]


class _FrameworkNamespaceFilter(logging.Filter):
    """Only tee records emitted under the ``research_framework`` package."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.name == "research_framework" or record.name.startswith(
            "research_framework."
        )


@contextmanager
def cycle_log_handler(vault_dir: Path, cycle_n: int) -> Iterator[None]:
    """Attach a per-cycle ``FileHandler``; detach + close on every exit path."""
    cycle_3 = f"{cycle_n:03d}"
    log_path = vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle_3}" / "cycle.log"
    handler: logging.FileHandler | None = None
    root = logging.root
    saved_root_level = root.level
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        handler.setLevel(logging.DEBUG)
        handler.addFilter(_FrameworkNamespaceFilter())
        if saved_root_level == logging.NOTSET or saved_root_level > logging.INFO:
            root.setLevel(logging.INFO)
        root.addHandler(handler)
    except OSError as exc:
        _LOG.warning("cycle_log: could not open %s: %s", log_path, exc)
        handler = None
    try:
        yield
    finally:
        if handler is not None:
            root.removeHandler(handler)
            handler.close()
        root.setLevel(saved_root_level)
