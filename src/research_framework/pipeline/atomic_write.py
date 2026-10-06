"""Canonical atomic file writes (spec 023 FR-018).

Readers never observe torn files: write to a same-directory temp file, fsync,
then ``os.replace``. NFS and non-POSIX caveats: best-effort parent fsync only.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any


def _best_effort_fsync_parent(path: Path) -> None:
    try:
        dir_fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except (AttributeError, OSError):
        pass
    finally:
        os.close(dir_fd)


def _atomic_replace(path: Path, temp_path: Path, *, mode: int | None) -> None:
    preserved: int | None = None
    if mode is None and path.is_file():
        preserved = stat.S_IMODE(path.stat().st_mode)
    os.replace(temp_path, path)
    effective = mode if mode is not None else preserved
    if effective is not None:
        path.chmod(effective)


def write_bytes(path: Path, data: bytes, *, mode: int | None = None) -> None:
    if path.exists() and path.is_dir():
        raise IsADirectoryError(f"refusing to write bytes to directory: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".atomic-", suffix=".tmp")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _atomic_replace(path, temp_path, mode=mode)
        _best_effort_fsync_parent(path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def write_text(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
    mode: int | None = None,
) -> None:
    write_bytes(path, text.encode(encoding), mode=mode)


def write_json(
    path: Path,
    obj: Any,
    *,
    indent: int = 2,
    trailing_newline: bool = True,
) -> None:
    payload = json.dumps(obj, indent=indent)
    if trailing_newline:
        payload += "\n"
    write_text(path, payload)
