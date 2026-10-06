"""Tier-2 tests for pipeline.atomic_write (spec 023 FR-018)."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from research_framework.pipeline import atomic_write


def test_write_text_os_replace_is_final_syscall(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    calls: list[str] = []

    real_replace = os.replace

    def tracking_replace(src: str | os.PathLike, dst: str | os.PathLike) -> None:
        calls.append("replace")
        real_replace(src, dst)

    with (
        patch(
            "research_framework.pipeline.atomic_write.os.replace",
            side_effect=tracking_replace,
        ),
        patch(
            "research_framework.pipeline.atomic_write.os.fsync",
            side_effect=lambda _fd: calls.append("fsync"),
        ),
    ):
        atomic_write.write_text(target, "payload")

    assert calls.count("replace") == 1
    assert calls.index("replace") > calls.index("fsync")
    assert target.read_text(encoding="utf-8") == "payload"


def test_write_json_fault_before_os_replace_preserves_destination(
    tmp_path: Path,
) -> None:
    target = tmp_path / "doc.json"
    original = b'{"keep": true}\n'
    target.write_bytes(original)

    with patch(
        "research_framework.pipeline.atomic_write.os.replace",
        side_effect=OSError("injected"),
    ):
        with pytest.raises(OSError, match="injected"):
            atomic_write.write_json(target, {"new": 1})

    assert target.read_bytes() == original
    assert not list(tmp_path.glob(".atomic-*.tmp"))


def test_write_json_crash_mid_write_never_leaves_destination_truncated(
    tmp_path: Path,
) -> None:
    """issue #312: the failure that produced an empty ``cycle-001-scout.json``
    is a crash while the *content* is still being written — before the temp
    file is even complete, let alone renamed. Injecting the fault inside the
    write (not at ``os.replace``, which the fault-before-replace tests above
    already cover) proves the destination is never touched until the temp
    file holds the full payload."""
    target = tmp_path / "cycle-001-scout.json"
    original = b'{"topics_found": {"new": []}}\n'
    target.write_bytes(original)

    class _ExplodingHandle:
        def __init__(self, real_fd: int) -> None:
            self._real_fd = real_fd

        def __enter__(self) -> _ExplodingHandle:
            return self

        def __exit__(self, *exc_info: object) -> None:
            os.close(self._real_fd)

        def write(self, _data: bytes) -> int:
            raise OSError("injected mid-write crash")

    real_fdopen = os.fdopen

    def exploding_fdopen(fd: int, mode: str = "r", *args: object, **kwargs: object):
        if mode == "wb":
            return _ExplodingHandle(fd)
        return real_fdopen(fd, mode, *args, **kwargs)

    with patch(
        "research_framework.pipeline.atomic_write.os.fdopen",
        side_effect=exploding_fdopen,
    ):
        with pytest.raises(OSError, match="injected mid-write crash"):
            atomic_write.write_json(target, {"topics_found": {"new": ["x"]}})

    # The destination is exactly the last complete write — never empty,
    # never a half-written fragment of the new payload.
    assert target.read_bytes() == original
    assert target.read_bytes() != b""
    assert not list(tmp_path.glob(".atomic-*.tmp"))


def test_write_bytes_fault_before_os_replace_preserves_destination(
    tmp_path: Path,
) -> None:
    target = tmp_path / "bin.dat"
    original = b"\x00\x01\x02"
    target.write_bytes(original)

    with patch(
        "research_framework.pipeline.atomic_write.os.replace",
        side_effect=OSError("injected"),
    ):
        with pytest.raises(OSError, match="injected"):
            atomic_write.write_bytes(target, b"\xff\xfe")

    assert target.read_bytes() == original


def test_concurrent_reader_never_sees_invalid_json(tmp_path: Path) -> None:
    target = tmp_path / "shared.json"
    stop = threading.Event()
    errors: list[Exception] = []

    def writer() -> None:
        for i in range(200):
            if stop.is_set():
                return
            atomic_write.write_json(target, {"n": i})

    def reader() -> None:
        for _ in range(150):
            if stop.is_set():
                return
            if not target.exists():
                continue
            raw = target.read_bytes()
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                errors.append(exc)
                stop.set()
                return
            if json.loads(raw.decode("utf-8")) != parsed:
                errors.append(ValueError("parse mismatch"))
                stop.set()
                return

    wt = threading.Thread(target=writer)
    rt = threading.Thread(target=reader)
    wt.start()
    rt.start()
    wt.join(timeout=30)
    rt.join(timeout=30)
    stop.set()
    assert not errors


def test_write_text_applies_mode_after_replace(tmp_path: Path) -> None:
    target = tmp_path / "shim"
    atomic_write.write_text(target, "#!/bin/sh\necho ok\n", mode=0o755)
    assert oct(target.stat().st_mode & 0o777) == oct(0o755)


def test_write_bytes_best_effort_parent_fsync(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "out.json"

    with patch(
        "research_framework.pipeline.atomic_write._best_effort_fsync_parent"
    ) as parent_fsync:
        atomic_write.write_bytes(target, b"{}")

    parent_fsync.assert_called_once_with(target)
    assert target.read_bytes() == b"{}"


def test_write_bytes_preserves_existing_file_mode(tmp_path: Path) -> None:
    target = tmp_path / "cycle.json"
    target.write_bytes(b"{}")
    target.chmod(0o640)
    atomic_write.write_bytes(target, b'{"n": 1}\n')
    assert oct(target.stat().st_mode & 0o777) == oct(0o640)
