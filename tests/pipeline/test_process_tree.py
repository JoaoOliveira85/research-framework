"""Tests for the package-level process-tree helpers (spec 050).

These tests guard the helpers used by ``_cycle_helpers._run_script`` and
``source_bridge.extractor.invoke_extractor`` — both of which spawn
long-running subprocesses that may fork grandchildren. The post-mortem
on 2026-05-31 traced the 5-hour zombie cycle to ``proc.kill()`` only
signalling the direct child, leaving grandchildren holding the stdout
pipe and blocking ``communicate()`` indefinitely.

The companion test file
``tests/scripts/test_agent_call_process_tree.py`` covers the same
helpers as duplicated inside ``scripts/agent_call.py`` (which can't
import from the package because it's a self-contained script).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from research_framework.pipeline.process_tree import (
    popen_session,
    signal_process_tree,
    terminate_process_tree,
)


def _spawn_grandchild_script(tmp_path: Path) -> tuple[Path, Path]:
    """Python script that backgrounds a long-running grandchild.

    The grandchild ticks a sentinel file every 100ms. If the parent gets
    killed but the grandchild survives, the sentinel keeps growing — which
    is exactly the regression we're guarding against.
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
class TestPopenSession:
    def test_child_is_session_leader(self):
        proc = popen_session(
            ["sh", "-c", "echo $$ && sleep 0.5"],
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            assert os.getpgid(proc.pid) == proc.pid
        finally:
            proc.kill()
            proc.wait(timeout=3)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only feature")
class TestTerminateProcessTree:
    def test_grandchild_dies_when_tree_is_terminated(self, tmp_path: Path):
        script, sentinel = _spawn_grandchild_script(tmp_path)
        proc = popen_session([sys.executable, str(script)])

        # Wait for the grandchild to actually start writing.
        t0 = time.monotonic()
        while sentinel.stat().st_size == 0 and time.monotonic() - t0 < 5:
            time.sleep(0.1)
        assert sentinel.stat().st_size > 0, "grandchild never started ticking"

        terminate_process_tree(proc)
        size_after_kill = sentinel.stat().st_size

        # Give any lingering grandchild ~1s to land a stray write.
        # If the process group was killed properly, none will.
        time.sleep(1.0)
        assert sentinel.stat().st_size == size_after_kill, (
            "grandchild continued writing after terminate_process_tree — "
            "the process group was NOT killed (regression of spec 050)"
        )

    def test_terminate_returns_within_bounded_wall_clock(self, tmp_path: Path):
        """A stuck subprocess must NOT cause terminate_process_tree to hang.

        Bound: grace_s (2s) + kill_timeout_s (3s) + slack ≈ 8s. Before
        the fix, ``proc.communicate()`` after ``proc.kill()`` could block
        indefinitely on the grandchild's open pipe.
        """
        script, _ = _spawn_grandchild_script(tmp_path)
        proc = popen_session([sys.executable, str(script)])
        time.sleep(0.5)
        t0 = time.monotonic()
        terminate_process_tree(proc)
        elapsed = time.monotonic() - t0
        assert elapsed < 8.0, (
            f"terminate_process_tree took {elapsed:.1f}s — should be bounded by "
            "grace_s + kill_timeout_s ≤ ~5s"
        )

    def test_returns_true_when_proc_already_exited(self):
        proc = popen_session(["true"])
        proc.wait(timeout=3)
        assert terminate_process_tree(proc) is True

    def test_signal_process_tree_is_noop_on_dead_proc(self):
        proc = popen_session(["true"])
        proc.wait(timeout=3)
        # Must not raise even though the pgid is gone.
        signal_process_tree(proc, signal.SIGTERM)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only feature")
class TestSignalProcessTreeSelfKillGuard:
    """Regression: terminate-a-child must never killpg OUR own group or init.

    A bogus ``proc.pid`` that resolves to the caller's own process group —
    or to init's group 1 (e.g. a test ``MagicMock`` whose ``.pid`` coerces
    to 1, so ``getpgid(1) == 1``) — must NOT be killpg'd. Otherwise the call
    suicides the caller. On Linux CI the runner's process tree lives in
    group 1, so ``killpg(1)`` took down the whole smoke-gate job (exit 143).
    """

    def test_refuses_to_killpg_our_own_process_group(self, monkeypatch):
        killed: list[int] = []
        sent: list[int] = []
        monkeypatch.setattr(os, "killpg", lambda pgid, s: killed.append(pgid))

        class _FakeProc:
            pid = os.getpid()  # getpgid(self.pid) == our own group

            def poll(self):
                return None

            def send_signal(self, s):
                sent.append(s)

        signal_process_tree(_FakeProc(), signal.SIGTERM)
        assert killed == [], "must not killpg the caller's own process group"
        assert sent == [signal.SIGTERM], "should fall back to direct send_signal"


# ---------------------------------------------------------------------------
# A process group outlives its leader
# ---------------------------------------------------------------------------

_TICKER = """
import pathlib, signal, sys, time
if sys.argv[2] == "ignore-term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
ticks = pathlib.Path(sys.argv[1])
ticks.with_suffix(".pid").write_text(str(__import__("os").getpid()))
for _ in range(600):  # ~30s: bounded even if a test fails to reap it
    with ticks.open("a") as fh:
        fh.write("tick\\n")
    time.sleep(0.05)
"""

_LEADER = """
import subprocess, sys, time
subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2], sys.argv[3]])
if sys.argv[4] == "exit":
    sys.exit(0)
time.sleep(60)
"""


def _leader_cmd(tmp_path: Path, *, grandchild: str, leader: str) -> tuple[list, Path]:
    """A leader that forks a ticking grandchild into its own process group."""
    ticker = tmp_path / "ticker.py"
    ticker.write_text(_TICKER, encoding="utf-8")
    script = tmp_path / "leader.py"
    script.write_text(_LEADER, encoding="utf-8")
    ticks = tmp_path / "grandchild.ticks"
    cmd = [sys.executable, str(script), str(ticker), str(ticks), grandchild, leader]
    return cmd, ticks


def _wait_for_ticks(ticks: Path) -> None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < 10:
        if ticks.exists() and ticks.stat().st_size > 0:
            return
        time.sleep(0.05)
    pytest.fail("the grandchild never started ticking")


def _still_ticking(ticks: Path) -> bool:
    size = ticks.stat().st_size
    time.sleep(0.5)
    return ticks.stat().st_size != size


def _reap_grandchild(ticks: Path) -> None:
    """Never leave the fake grandchild behind when an assertion fails."""
    try:
        os.kill(int(ticks.with_suffix(".pid").read_text()), signal.SIGKILL)
    except (OSError, ValueError):
        pass


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only feature")
class TestTheGroupOutlivesItsLeader:
    """The leader exiting says nothing about what it spawned.

    ``terminate_process_tree`` used to return as soon as the direct child was
    gone: at once when it had already exited, and before the SIGKILL when it
    died on the SIGTERM. Whatever it had forked stayed alive in the group,
    holding the pipes — the 2026-05-31 zombie cycle.
    """

    def test_a_grandchild_that_ignores_sigterm_is_killed(self, tmp_path: Path):
        cmd, ticks = _leader_cmd(tmp_path, grandchild="ignore-term", leader="stay")
        proc = popen_session(cmd)
        try:
            _wait_for_ticks(ticks)

            assert terminate_process_tree(proc, grace_s=0.5) is True

            assert not _still_ticking(ticks), (
                "the leader died on SIGTERM, so the SIGKILL was skipped and the "
                "grandchild that ignores SIGTERM kept running"
            )
        finally:
            _reap_grandchild(ticks)

    def test_a_group_whose_leader_already_exited_is_terminated(self, tmp_path: Path):
        cmd, ticks = _leader_cmd(tmp_path, grandchild="default", leader="exit")
        proc = popen_session(cmd)
        try:
            proc.wait(timeout=10)
            _wait_for_ticks(ticks)

            assert terminate_process_tree(proc) is True

            assert not _still_ticking(ticks), (
                "terminate_process_tree returned at once because the leader "
                "had exited; its grandchild is still running"
            )
        finally:
            _reap_grandchild(ticks)

    def test_a_remembered_group_that_is_our_own_is_never_signalled(self, monkeypatch):
        killed: list[int] = []
        monkeypatch.setattr(os, "killpg", lambda pgid, s: killed.append(pgid))

        class _FakeProc:
            pid = os.getpid()
            _rf_session_pgid = os.getpgrp()

            def poll(self):
                return 0

            def send_signal(self, s):
                pass

        signal_process_tree(_FakeProc(), signal.SIGTERM)
        assert terminate_process_tree(_FakeProc()) is True
        assert killed == [], "must not killpg the caller's own process group"

    def test_a_test_doubles_pid_is_never_taken_for_a_process_group(self, monkeypatch):
        """``popen_session`` remembers a group only for a child it really started.

        The cycle-runner tests replace ``subprocess.Popen`` with a double whose
        ``pid`` is a plain int. Remembered as a session group, that number is
        what ``terminate_process_tree`` signals: a real SIGTERM, then a SIGKILL,
        to whichever process group on the machine happens to have that id.
        """
        killed: list[int] = []
        monkeypatch.setattr(os, "killpg", lambda pgid, s: killed.append(pgid))

        class _Double:
            pid = 4242
            returncode = 0
            stdin = stdout = stderr = None

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return 0

            def send_signal(self, s):
                pass

        monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kwargs: _Double())

        proc = popen_session(["true"])
        signal_process_tree(proc, signal.SIGTERM)
        assert terminate_process_tree(proc, grace_s=0.2) is True

        assert killed == [], "a test double's pid was signalled as a process group"
