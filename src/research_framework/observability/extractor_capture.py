"""Per-extractor reader thread that drains stderr into ``bridge.log`` live.

Authority: spec 048 FR-007 (line-buffered guarantee + ``[<module>:<pid>] ``
disambiguating prefix) and the
``contracts/bridge-log-format.contract.md`` Body-line regex.

The thread is daemon=True so it terminates when the parent process exits
hard (Ctrl-C, wall-clock kill). Callers MUST join the thread after
``proc.wait()`` returns to ensure all buffered stderr has been drained
before the footer line is written.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import subprocess

    from .bridge_log import BridgeLogWriter


def _format_body_line(module: str, pid: int, raw_line: str) -> str:
    """Return ``[<module>:<pid>] <raw stderr line>`` per contract."""
    return f"[{module}:{pid}] {raw_line.rstrip(chr(10)).rstrip(chr(13))}"


def start_capture(
    proc: subprocess.Popen[str],
    module: str,
    source_id: str,
    writer: BridgeLogWriter,
    *,
    transcript: list[str] | None = None,
) -> threading.Thread:
    """Spawn a daemon thread that drains ``proc.stderr`` into ``writer``.

    Each stderr line is prefixed with ``[<module>:<pid>] `` and forwarded
    to ``writer.write_body``. If ``transcript`` is supplied (a list), the
    raw line (without the prefix) is also appended to it, so the calling
    site can re-use the captured stderr for downstream error messages
    (preserving the pre-spec-048 behaviour where ``proc.stderr.read()``
    fed the ExtractorError message body).

    Returns the running thread; the caller MUST ``.join(timeout=...)``
    after ``proc.wait()`` returns. The thread exits when ``proc.stderr``
    is closed by the subprocess.
    """
    pid = proc.pid

    def _drain() -> None:
        if proc.stderr is None:
            return
        for raw_line in proc.stderr:
            if not raw_line:
                continue
            if transcript is not None:
                transcript.append(raw_line)
            try:
                writer.write_body(_format_body_line(module, pid, raw_line))
            except (RuntimeError, OSError):
                # Writer closed mid-cycle (cycle aborted); stop draining.
                return

    thread = threading.Thread(
        target=_drain,
        name=f"bridge-capture-{module}-{pid}",
        daemon=True,
    )
    # source_id retained as a function parameter for the public surface
    # (contract: caller passes it for diagnostic value); not currently
    # used inside the thread body, but kept so future per-source filtering
    # (e.g. v1.1's `vault status`) doesn't need a signature change.
    del source_id
    thread.start()
    return thread


__all__ = ["start_capture"]
