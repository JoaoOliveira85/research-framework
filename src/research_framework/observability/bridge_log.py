"""Per-cycle ``bridge.log`` writer with header/body/footer framing.

Contract: ``specs/048-observability-v1/contracts/bridge-log-format.contract.md``.
Authority: spec 048 FR-006, FR-007, FR-008.

One file per cycle (``<vault>/_pipeline/cycles/cycle-NNN/bridge.log``).
Append-only, line-buffered, UTF-8/LF. Atomic appends via a
``threading.Lock`` so multiple reader threads (one per concurrent
extractor) cannot interleave a single line's bytes.

The framing is line-grammar (not JSON) so operators can ``tail -f``,
``rg`` and ``less`` it without tooling. Each extractor invocation
appears as: 1 header line → 0..N body lines → 1 footer line.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Literal

KillReason = Literal[
    "wall-clock cap",
    "dollar cap",
    "manual interrupt",
    "parent exit",
]

_ALLOWED_KILL_REASONS: frozenset[str] = frozenset(
    {"wall-clock cap", "dollar cap", "manual interrupt", "parent exit"}
)

PayloadVerdict = Literal["ok", "empty", "error"]
_ALLOWED_VERDICTS: frozenset[str] = frozenset({"ok", "empty", "error"})


def _iso_timestamp_ms() -> str:
    """Return ``YYYY-MM-DDTHH:MM:SS.mmm`` per contract § Header regex."""
    now = datetime.now()
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}"


class BridgeLogWriter:
    """Append-only per-cycle bridge log writer.

    Usage::

        with BridgeLogWriter(cycle_dir / "bridge.log") as writer:
            writer.start_extractor("youtube", "VIDEO_ID", pid=12345)
            writer.write_body("[youtube:12345] yt-dlp: extracting...")
            writer.end_extractor(exit_code=0, duration_s=4.328, payload_status="ok")

    Thread-safe via a single ``threading.Lock`` around every file write.
    The lock is shared across all reader threads spawned for concurrent
    extractor subprocesses.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._fh = None  # type: ignore[assignment]
        self._closed = False
        self._opened = False

    def __enter__(self) -> BridgeLogWriter:
        self._open()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def _open(self) -> None:
        if self._opened:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._path.open("a", encoding="utf-8", newline="\n")
        self._opened = True

    @property
    def path(self) -> Path:
        """Absolute filesystem path to the bridge log file."""
        return self._path

    @property
    def closed(self) -> bool:
        """True once :meth:`close` has been called (idempotent)."""
        return self._closed

    def start_extractor(self, module: str, source: str, pid: int) -> None:
        """Write the per-extractor header line (contract § Header regex)."""
        if "," in source or "\n" in source:
            raise ValueError(f"source must not contain comma or newline: {source!r}")
        line = (
            f"=== module: {module}, source: {source}, "
            f"pid: {pid}, started: {_iso_timestamp_ms()} ==="
        )
        self._write_line(line)

    def write_body(self, line: str) -> None:
        """Append one body line verbatim (line is the framework-prefixed form).

        Caller is responsible for adding the ``[<module>:<pid>] `` prefix
        per contract § Body line. This method does NOT strip ANSI escapes
        or trailing whitespace; verbatim preservation is a contract
        invariant.
        """
        self._write_line(line)

    def end_extractor(
        self,
        exit_code: int,
        duration_s: float,
        payload_status: str,
    ) -> None:
        """Write the success-path footer line (contract § Footer-success)."""
        if payload_status not in _ALLOWED_VERDICTS:
            raise ValueError(
                f"payload_status must be one of {sorted(_ALLOWED_VERDICTS)}; "
                f"got {payload_status!r}"
            )
        if exit_code < 0:
            raise ValueError(f"exit_code must be >= 0; got {exit_code}")
        line = (
            f"=== exit: {exit_code}, duration: {duration_s:.3f}s, "
            f"payload_status: {payload_status} ==="
        )
        self._write_line(line)

    def end_extractor_killed(self, reason: str, duration_s: float) -> None:
        """Write the KILLED-path footer line (FR-008, contract § Footer-killed)."""
        if reason not in _ALLOWED_KILL_REASONS:
            raise ValueError(
                f"reason must be one of {sorted(_ALLOWED_KILL_REASONS)}; got {reason!r}"
            )
        line = f"=== KILLED BY FRAMEWORK ({reason}) after {duration_s:.3f}s ==="
        self._write_line(line)

    def close(self) -> None:
        """Close the underlying file handle. Idempotent (FR-006 acceptance)."""
        if self._closed:
            return
        self._closed = True
        if self._fh is not None:
            try:
                self._fh.flush()
            finally:
                self._fh.close()
                self._fh = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_line(self, line: str) -> None:
        """Acquire the lock and append ``line + '\\n'`` atomically."""
        if self._closed:
            raise RuntimeError("BridgeLogWriter is closed")
        if not self._opened:
            self._open()
        assert self._fh is not None
        with self._lock:
            self._fh.write(line)
            self._fh.write("\n")
            self._fh.flush()


__all__ = ["BridgeLogWriter", "KillReason", "PayloadVerdict"]
