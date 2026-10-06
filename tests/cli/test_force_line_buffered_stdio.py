"""Regression test for the v0.2.23 fix that line-buffers parent stdout/stderr.

Background: Python defaults stdout to line-buffered only when connected to
a TTY. The moment ``./generate.sh | tee run.log`` redirects stdout, it
becomes block-buffered (4–8KB chunks) and the cycle runner's
``[Step N - …]`` orchestration banners arrive in bursts — useless when
diagnosing a crash that happened seconds ago.

``_force_line_buffered_stdio`` is called as the very first action in
:func:`research_framework.cli.main` to restore real-time line flushing
unconditionally.
"""

from __future__ import annotations

import io
import sys
from unittest.mock import patch

from research_framework.cli import _force_line_buffered_stdio


def test_reconfigures_both_stdout_and_stderr() -> None:
    """The helper MUST call ``.reconfigure(line_buffering=True)`` on
    both stdout and stderr. We verify by intercepting both calls.
    """
    calls: list[tuple[str, dict]] = []

    class _RecordingStream:
        def __init__(self, name: str) -> None:
            self.name = name

        def reconfigure(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            calls.append((self.name, kwargs))

    fake_out = _RecordingStream("stdout")
    fake_err = _RecordingStream("stderr")

    with patch.object(sys, "stdout", fake_out), patch.object(sys, "stderr", fake_err):
        _force_line_buffered_stdio()

    assert ("stdout", {"line_buffering": True}) in calls
    assert ("stderr", {"line_buffering": True}) in calls
    assert len(calls) == 2, f"unexpected extra calls: {calls!r}"


def test_swallows_attribute_error_when_stream_lacks_reconfigure() -> None:
    """If stdout has been replaced with a stream that doesn't expose
    ``.reconfigure`` (e.g. captured ``io.StringIO`` in a test harness or
    a subprocess wrapper), the helper MUST NOT crash. Best-effort:
    the fallback is the prior block-buffered behaviour, not worse.
    """
    fake = io.StringIO()  # has no .reconfigure
    with patch.object(sys, "stdout", fake), patch.object(sys, "stderr", fake):
        # MUST NOT raise
        _force_line_buffered_stdio()


def test_swallows_oserror_from_reconfigure() -> None:
    """Some closed/detached streams raise OSError on reconfigure (e.g.
    stdout has been closed by a parent process). Still must not crash.
    """

    class _RaisingStream:
        def reconfigure(self, **_kwargs) -> None:  # type: ignore[no-untyped-def]
            raise OSError("stream is closed")

    fake = _RaisingStream()
    with patch.object(sys, "stdout", fake), patch.object(sys, "stderr", fake):
        _force_line_buffered_stdio()  # MUST NOT raise


def test_main_invokes_force_line_buffered_stdio_on_first_action() -> None:
    """``cli.main`` MUST invoke the helper before parsing args / dispatching.
    Otherwise any early ``print`` or ``argparse`` error message arrives
    block-buffered in the redirected case — the exact diagnostic surface
    a user looks at when a run fails immediately.
    """
    from research_framework import cli

    called = {"count": 0}

    def _spy() -> None:
        called["count"] += 1

    with patch.object(cli, "_force_line_buffered_stdio", _spy):
        # Run with a help-like arg that exits early via SystemExit — we
        # just need to verify the helper fired before parser side effects.
        try:
            cli.main(["--version"])
        except SystemExit:
            pass

    assert called["count"] >= 1, (
        "cli.main MUST call _force_line_buffered_stdio before parsing args"
    )
