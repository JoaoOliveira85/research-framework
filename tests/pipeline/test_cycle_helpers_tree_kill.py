"""Regression lock: ``_cycle_helpers._run_script`` reaps the whole process
tree (grandchildren included) when its read loop is interrupted.

Spec 051 FR5 / REVIVAL-NOTES #5 (shipped 0.6.2). The package-level helper
``terminate_process_tree`` is exercised directly by
``tests/pipeline/test_process_tree.py``; ``scripts/agent_call.py``'s copy by
``tests/scripts/test_agent_call_process_tree.py``. This file covers the third
tree-kill call site that lacked a dedicated real-grandchild test: the
cleanup-on-interrupt path in ``_run_script``'s ``finally`` block
(``_cycle_helpers.py`` ~:206-218). Before 0.6.2 a parent interrupt left the
direct child's grandchildren (codex sandbox, MCP servers, yt-dlp forks)
holding the stdout pipe open, stalling the cycle for hours.
"""

from __future__ import annotations

import os
import signal
import sys
import textwrap
import time
from pathlib import Path

import pytest

from research_framework.pipeline._helpers import script_runner
from research_framework.pipeline._helpers.script_runner import _run_script


def _spawn_grandchild_script(tmp_path: Path) -> tuple[Path, Path]:
    """A script that backgrounds a long-running grandchild, then blocks.

    The grandchild ticks a sentinel file every 100ms. The script itself emits
    no stdout and sleeps 60s, so ``_run_script``'s ``for raw_line in
    proc.stdout`` loop is blocked (waiting for lines) when the interrupt
    arrives — exactly the production shape.
    """
    sentinel = tmp_path / "grandchild.ticks"
    sentinel.touch()
    grandchild = tmp_path / "grandchild.py"
    grandchild.write_text(
        textwrap.dedent(
            f"""
            import time, pathlib
            p = pathlib.Path({str(sentinel)!r})
            for _ in range(10_000):
                with p.open("ab") as fh:
                    fh.write(b"tick\\n")
                time.sleep(0.1)
            """
        ).lstrip("\n"),
        encoding="utf-8",
    )
    script = tmp_path / "spawn_grandchild.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import subprocess, sys, time
            subprocess.Popen([sys.executable, {str(grandchild)!r}])
            time.sleep(60)
            """
        ).lstrip("\n"),
        encoding="utf-8",
    )
    return script, sentinel


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only feature")
def test_run_script_kills_grandchild_on_interrupt(tmp_path: Path):
    script, sentinel = _spawn_grandchild_script(tmp_path)
    log_file = tmp_path / "stage.log"
    env = os.environ.copy()
    # Keep the 30s heartbeat thread out of the way; irrelevant to a ~1.5s run.
    env["RV_HEARTBEAT_S"] = "9999"

    def _raise_kbd(signum, frame):  # noqa: ANN001 — signal handler signature
        raise KeyboardInterrupt

    old_handler = signal.signal(signal.SIGALRM, _raise_kbd)
    try:
        # Fire a KeyboardInterrupt into _run_script's blocking read loop ~1.5s
        # in — by then the grandchild is ticking and the script is sleeping.
        signal.setitimer(signal.ITIMER_REAL, 1.5)
        with pytest.raises(KeyboardInterrupt):
            _run_script(sys.executable, script, env=env, log_file=log_file)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)

    # Grandchild must be dead: the sentinel stops growing once the tree is
    # reaped. Sample, wait, re-sample — any growth means a survivor.
    assert sentinel.stat().st_size > 0, "grandchild never started ticking"
    size_after_interrupt = sentinel.stat().st_size
    time.sleep(1.0)
    assert sentinel.stat().st_size == size_after_interrupt, (
        "grandchild kept writing after _run_script was interrupted — the "
        "cleanup-on-interrupt path did NOT reap the process tree "
        "(regression of 0.6.2 / spec 051 FR5)"
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only feature")
def test_run_script_interrupt_returns_promptly(tmp_path: Path):
    """The interrupt cleanup must be bounded, not hang on the open pipe.

    Before 0.6.2 the outer read/``wait`` could block indefinitely on the
    grandchild's inherited stdout. Bound: grace (2s) + kill (3s) + slack.
    """
    script, _ = _spawn_grandchild_script(tmp_path)
    log_file = tmp_path / "stage.log"
    env = os.environ.copy()
    env["RV_HEARTBEAT_S"] = "9999"

    def _raise_kbd(signum, frame):  # noqa: ANN001
        raise KeyboardInterrupt

    old_handler = signal.signal(signal.SIGALRM, _raise_kbd)
    t0 = time.monotonic()
    try:
        signal.setitimer(signal.ITIMER_REAL, 1.0)
        with pytest.raises(KeyboardInterrupt):
            _run_script(sys.executable, script, env=env, log_file=log_file)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
    elapsed = time.monotonic() - t0
    assert elapsed < 9.0, (
        f"_run_script interrupt cleanup took {elapsed:.1f}s — should be bounded "
        "by the grandchild start (~1s) + grace + kill window"
    )


# ---------------------------------------------------------------------------
# The wait ends when the script exits, not when its stdout pipe closes
# ---------------------------------------------------------------------------

#: How long the left-behind grandchild holds the pipe. Only a failing run
#: waits it out; a passing one is over in well under a second.
_GRANDCHILD_LIFETIME_S = 12.0
_RETURNED_PROMPTLY_S = 8.0


def _script_that_leaves_a_grandchild(
    tmp_path: Path, *, leaves_the_group: bool = False
) -> tuple[Path, Path]:
    """A helper that exits at once and leaves something holding its stdout.

    The grandchild inherits the helper's stdout — the pipe ``_run_script``
    reads — records its pid and sleeps. The helper waits for that pid, prints
    one line and exits 0.
    """
    pid_file = tmp_path / "grandchild.pid"
    grandchild = tmp_path / "sleeper.py"
    grandchild.write_text(
        textwrap.dedent(
            f"""
            import os, pathlib, time
            if {leaves_the_group!r}:
                os.setsid()
            pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))
            time.sleep({_GRANDCHILD_LIFETIME_S})
            """
        ).lstrip("\n"),
        encoding="utf-8",
    )
    script = tmp_path / "leaves_a_grandchild.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import pathlib, subprocess, sys, time
            subprocess.Popen([sys.executable, {str(grandchild)!r}])
            pid_file = pathlib.Path({str(pid_file)!r})
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if pid_file.exists() and pid_file.read_text():
                    break
                time.sleep(0.05)
            print("helper done", flush=True)
            """
        ).lstrip("\n"),
        encoding="utf-8",
    )
    return script, pid_file


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _is_gone(pid: int, *, within_s: float = 5.0) -> bool:
    """Whether ``pid`` goes away; a killed orphan takes a moment to be reaped."""
    deadline = time.monotonic() + within_s
    while _is_running(pid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


def _kill_the_grandchild(pid_file: Path) -> None:
    """Never leave the sleeper behind, whatever the test concluded."""
    try:
        pid = int(pid_file.read_text())
    except (OSError, ValueError):
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only feature")
def test_what_the_script_left_running_does_not_hold_the_call(tmp_path: Path):
    """A script's exit ends the call, and what it spawned ends with it.

    ``_run_script`` read the script's stdout to EOF before it looked at the
    exit status, and EOF needs every holder of the pipe gone. A helper that
    exited while a process it had started was still running kept the pipeline
    there for that process's whole lifetime — the 2026-05-31 zombie cycle.
    """
    script, pid_file = _script_that_leaves_a_grandchild(tmp_path)
    log_file = tmp_path / "stage.log"
    env = os.environ.copy()
    env["RV_HEARTBEAT_S"] = "9999"

    t0 = time.monotonic()
    try:
        rc = _run_script(sys.executable, script, env=env, log_file=log_file)
        elapsed = time.monotonic() - t0

        assert rc == 0
        assert elapsed < _RETURNED_PROMPTLY_S, (
            f"_run_script returned {elapsed:.1f}s after a script that exits at "
            f"once: it waited for the grandchild ({_GRANDCHILD_LIFETIME_S:.0f}s) "
            "that still held the script's stdout"
        )
        content = log_file.read_text(encoding="utf-8")
        assert "helper done" in content
        assert "exited with code 0" in content
        assert _is_gone(int(pid_file.read_text())), (
            "what the script left in its process group is still running after "
            "the script's clean exit"
        )
    finally:
        _kill_the_grandchild(pid_file)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only feature")
def test_a_descendant_that_left_the_group_does_not_hold_the_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A descendant in a session of its own cannot be killed: the read is bounded.

    It still holds the pipe, so its EOF never comes. The call gives the output
    a bounded time to arrive and moves on with everything the script printed.
    """
    monkeypatch.setattr(script_runner, "_OUTPUT_DRAIN_TIMEOUT_S", 0.5)
    script, pid_file = _script_that_leaves_a_grandchild(tmp_path, leaves_the_group=True)
    log_file = tmp_path / "stage.log"
    env = os.environ.copy()
    env["RV_HEARTBEAT_S"] = "9999"

    t0 = time.monotonic()
    try:
        rc = _run_script(sys.executable, script, env=env, log_file=log_file)
        elapsed = time.monotonic() - t0

        assert rc == 0
        assert elapsed < _RETURNED_PROMPTLY_S, (
            f"_run_script returned {elapsed:.1f}s after a script that exits at "
            "once: it waited for a descendant that left the process group "
            f"({_GRANDCHILD_LIFETIME_S:.0f}s) to close the script's stdout"
        )
        content = log_file.read_text(encoding="utf-8")
        assert "helper done" in content
        assert "exited with code 0" in content
    finally:
        _kill_the_grandchild(pid_file)
