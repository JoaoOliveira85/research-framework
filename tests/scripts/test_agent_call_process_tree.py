"""Process-tree timeout enforcement for ``scripts/agent_call.py`` (spec 050).

The bug we're guarding against (post-mortem 2026-05-30, feeds-vault cycle 3):

    ``subprocess.run(..., timeout=N)`` and bare ``proc.kill()`` only signal
    the DIRECT child. If that child spawned grandchildren (codex's sandbox,
    MCP servers, headless scrapers, ...), those keep running AND keep the
    inherited stdout/stderr pipes open. The next ``communicate()`` then
    blocks forever waiting for EOF on the pipe. A nominal 60-minute
    timeout became a 5-hour zombie cycle.

The fix:

    1. Launch every subprocess with ``start_new_session=True``.
    2. On timeout, ``os.killpg(pgid, SIGKILL)`` the entire group.
    3. Bound the second ``communicate()`` so even a setsid-escaped
       grandchild can't hang the pipeline.

These tests use real subprocesses (a shell that forks a long-running
grandchild) because mocking process groups would defeat the test. They
are deliberately bounded — each test asserts the wall-clock budget so
a regression that re-introduces the hang fails fast instead of stalling
CI for an hour.
"""

from __future__ import annotations

import importlib.util
import json
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
    terminate_process_tree,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "agent_call.py"


def _load_module():
    """Load agent_call.py as a module without executing argparse main."""
    spec = importlib.util.spec_from_file_location("agent_call_pt", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["agent_call_pt"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def agent_call():
    return _load_module()


# ---------------------------------------------------------------------------
# Helpers — small shell scripts that exercise the parent/grandchild pattern.
# ---------------------------------------------------------------------------


def _write_script(tmp_path: Path, name: str, body: str) -> Path:
    """Write a sh script to ``tmp_path/name`` and chmod +x it."""
    p = tmp_path / name
    p.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    p.chmod(0o755)
    return p


@pytest.fixture
def grandchild_script(tmp_path: Path) -> tuple[Path, Path]:
    """A shell script that backgrounds a grandchild then sleeps.

    The grandchild appends a tick to ``sentinel`` every 100ms until killed.
    The parent shell sleeps far longer than any test will allow. This
    matches the codex / MCP shape: a foreground process whose children
    outlive it on bare ``proc.kill()``.
    """
    sentinel = tmp_path / "grandchild.ticks"
    sentinel.touch()
    script = _write_script(
        tmp_path,
        "spawn_grandchild.sh",
        f"""
        #!/bin/sh
        # Grandchild: append a tick every 100ms forever.
        (while true; do
            printf 'tick\\n' >> {sentinel}
            sleep 0.1
        done) &
        # Parent: stay alive long enough that the timeout must fire.
        sleep 60
        """,
    )
    return script, sentinel


@pytest.fixture
def chatty_script(tmp_path: Path) -> Path:
    """A script that prints output then sleeps. Used to verify the
    timeout path still captures stdout produced BEFORE the kill."""
    return _write_script(
        tmp_path,
        "chatty.sh",
        """
        #!/bin/sh
        printf 'hello\\n'
        sleep 30
        """,
    )


@pytest.fixture
def quick_script(tmp_path: Path) -> Path:
    """Happy path: script exits cleanly well within timeout."""
    return _write_script(
        tmp_path,
        "quick.sh",
        """
        #!/bin/sh
        printf 'done\\n'
        exit 0
        """,
    )


# ---------------------------------------------------------------------------
# _popen_session — process-group leader on POSIX
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only feature")
class TestPopenSession:
    def test_child_is_session_leader(self, agent_call):
        proc = agent_call._popen_session(
            ["sh", "-c", "echo $$ && sleep 0.5"],
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            assert os.getpgid(proc.pid) == proc.pid
        finally:
            proc.kill()
            proc.wait(timeout=3)

    def test_grandchild_inherits_pgid(self, agent_call, tmp_path):
        sentinel = tmp_path / "grandchild.pid"
        # ``sleep 30 & echo $! > sentinel`` writes the background sleep's
        # PID. ``$!`` is the most-recent backgrounded job, which is the
        # actual grandchild from agent_call.py's perspective.
        script = _write_script(
            tmp_path,
            "report_pgid.sh",
            f"""
            #!/bin/sh
            sleep 30 &
            echo $! > {sentinel}
            wait
            """,
        )
        proc = agent_call._popen_session([str(script)])
        try:
            t0 = time.monotonic()
            while not sentinel.exists() and time.monotonic() - t0 < 5:
                time.sleep(0.05)
            assert sentinel.exists(), "script never wrote the grandchild pid"
            grandchild_pid = int(sentinel.read_text().strip())
            assert os.getpgid(grandchild_pid) == proc.pid
        finally:
            agent_call._terminate_process_tree(proc)


# ---------------------------------------------------------------------------
# _terminate_process_tree — actually kills grandchildren
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only feature")
class TestTerminateProcessTree:
    def test_grandchild_dies_when_tree_is_terminated(
        self, agent_call, grandchild_script
    ):
        script, sentinel = grandchild_script
        proc = agent_call._popen_session([str(script)])
        # Wait for the grandchild to actually start ticking.
        t0 = time.monotonic()
        while sentinel.read_text() == "" and time.monotonic() - t0 < 5:
            time.sleep(0.1)
        assert sentinel.read_text() != "", "grandchild never started ticking"

        agent_call._terminate_process_tree(proc)
        size_after_kill = sentinel.stat().st_size

        # Give any zombie tick ~1s to land. If the kill was effective,
        # no further ticks should appear.
        time.sleep(1.0)
        assert sentinel.stat().st_size == size_after_kill, (
            "grandchild kept writing after _terminate_process_tree — "
            "the process group was NOT killed"
        )

    def test_returns_true_when_proc_already_exited(self, agent_call):
        proc = agent_call._popen_session(["true"])
        proc.wait(timeout=3)
        assert agent_call._terminate_process_tree(proc) is True

    def test_signal_process_tree_is_noop_on_dead_proc(self, agent_call):
        proc = agent_call._popen_session(["true"])
        proc.wait(timeout=3)
        # Must not raise even though the pgid is gone.
        agent_call._signal_process_tree(proc, signal.SIGTERM)


# ---------------------------------------------------------------------------
# A process group outlives its leader
# ---------------------------------------------------------------------------

_TICKER = """
import os, pathlib, signal, sys, time
if sys.argv[2] == "ignore-term":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if sys.argv[2] == "setsid":
    os.setsid()
ticks = pathlib.Path(sys.argv[1])
ticks.with_suffix(".pid").write_text(str(os.getpid()))
for _ in range(600):  # ~30s: bounded even if a test fails to reap it
    with ticks.open("a") as fh:
        fh.write("tick\\n")
    time.sleep(0.05)
"""

_LEADER = """
import os, subprocess, sys, time
subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2], sys.argv[3]])
print("leader started", flush=True)
if sys.argv[4] == "exit":
    for _ in range(200):  # leave only once the grandchild is up and ticking
        if os.path.exists(sys.argv[2]) and os.path.getsize(sys.argv[2]):
            break
        time.sleep(0.05)
    sys.exit(0)
time.sleep(60)
"""


def _leader_cmd(tmp_path: Path, *, grandchild: str, leader: str) -> tuple[list, Path]:
    """A leader that forks a ticking grandchild into its own process group.

    The grandchild inherits the leader's stdout and stderr, which is what
    makes it a pipe-holder when the caller captures them.
    """
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

    ``_terminate_process_tree`` used to return as soon as the direct child
    was gone: at once when it had already exited, and before the SIGKILL when
    it died on the SIGTERM. Whatever it had forked stayed alive in the group,
    holding the pipes — the 2026-05-31 zombie cycle.
    """

    def test_a_grandchild_that_ignores_sigterm_is_killed(self, agent_call, tmp_path):
        cmd, ticks = _leader_cmd(tmp_path, grandchild="ignore-term", leader="stay")
        proc = agent_call._popen_session(cmd, stdout=subprocess.DEVNULL)
        try:
            _wait_for_ticks(ticks)

            assert agent_call._terminate_process_tree(proc, grace_s=0.5) is True

            assert not _still_ticking(ticks), (
                "the leader died on SIGTERM, so the SIGKILL was skipped and the "
                "grandchild that ignores SIGTERM kept running"
            )
        finally:
            _reap_grandchild(ticks)

    def test_a_group_whose_leader_already_exited_is_terminated(
        self, agent_call, tmp_path
    ):
        cmd, ticks = _leader_cmd(tmp_path, grandchild="default", leader="exit")
        proc = agent_call._popen_session(cmd, stdout=subprocess.DEVNULL)
        try:
            proc.wait(timeout=10)
            _wait_for_ticks(ticks)

            assert agent_call._terminate_process_tree(proc) is True

            assert not _still_ticking(ticks), (
                "_terminate_process_tree returned at once because the leader "
                "had exited; its grandchild is still running"
            )
        finally:
            _reap_grandchild(ticks)

    def test_a_remembered_group_that_is_our_own_is_never_signalled(
        self, agent_call, monkeypatch
    ):
        killed: list[int] = []
        monkeypatch.setattr(os, "killpg", lambda pgid, s: killed.append(pgid))

        class _FakeProc:
            pid = os.getpid()
            _rf_session_pgid = os.getpgrp()

            def poll(self):
                return 0

            def send_signal(self, s):
                pass

        agent_call._signal_process_tree(_FakeProc(), signal.SIGTERM)
        assert agent_call._terminate_process_tree(_FakeProc()) is True
        assert killed == [], "must not killpg the caller's own process group"


# ---------------------------------------------------------------------------
# _run_in_session_with_timeout — the subprocess.run replacement
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only feature")
class TestRunInSessionWithTimeout:
    def test_happy_path_returns_completedprocess(self, agent_call, quick_script):
        result = agent_call._run_in_session_with_timeout(
            [str(quick_script)],
            capture_output=True,
            timeout=5,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "done"
        assert result.stderr == ""

    def test_timeout_raises_within_bounded_wall_clock(
        self, agent_call, grandchild_script
    ):
        """The KEY regression test for the post-mortem.

        Without the tree-kill fix, this test would hang for ~60 seconds
        (the parent script's sleep) PLUS the grandchild's lifetime,
        because ``proc.communicate()`` would block on the pipe held by
        the orphaned grandchild even after the timeout killed the parent.

        With the fix, the entire call must return within roughly:
            timeout (1.0s) + grace (2.0s) + kill_timeout (3.0s) + slack
        """
        script, _ = grandchild_script
        t0 = time.monotonic()
        with pytest.raises(subprocess.TimeoutExpired):
            agent_call._run_in_session_with_timeout(
                [str(script)],
                capture_output=True,
                timeout=1.0,
            )
        elapsed = time.monotonic() - t0
        # If the tree-kill regresses, this number balloons to >60s.
        # Bound at 10s — plenty of headroom for grace + kill + drain.
        assert elapsed < 10.0, (
            f"_run_in_session_with_timeout took {elapsed:.1f}s "
            "(should be ~1s + grace + kill ≤ 10s). The process-tree "
            "kill has regressed — a grandchild is keeping the pipe open."
        )

    def test_timeout_captures_partial_stdout_before_kill(
        self, agent_call, chatty_script
    ):
        """On timeout, whatever the child printed BEFORE the kill must
        still surface via TimeoutExpired.output. Without this, debugging
        a stuck stage is impossible because the partial trace is lost.
        """
        try:
            agent_call._run_in_session_with_timeout(
                [str(chatty_script)],
                capture_output=True,
                timeout=1.0,
            )
            pytest.fail("expected TimeoutExpired")
        except subprocess.TimeoutExpired as exc:
            captured = exc.output or ""
            assert "hello" in captured, (
                "stdout produced before the kill was lost on timeout"
            )

    def test_stdin_input_is_delivered(self, agent_call, tmp_path):
        """The ``input=`` path used by ``dispatch()`` and ``run()`` to
        pipe rendered prompts to the subprocess must keep working."""
        sentinel = tmp_path / "got.txt"
        script = _write_script(
            tmp_path,
            "cat_input.sh",
            f"""
            #!/bin/sh
            cat > {sentinel}
            """,
        )
        result = agent_call._run_in_session_with_timeout(
            [str(script)],
            input="hello from stdin\n",
            timeout=5,
        )
        assert result.returncode == 0
        assert sentinel.read_text(encoding="utf-8") == "hello from stdin\n"

    def test_no_timeout_means_no_watchdog(self, agent_call, quick_script):
        """When ``timeout=None`` we must not spawn a watchdog. This
        guards against a regression where we'd accidentally hang on
        ``watchdog.join()`` for None-timeout long-running calls."""
        t0 = time.monotonic()
        result = agent_call._run_in_session_with_timeout(
            [str(quick_script)],
            capture_output=True,
            timeout=None,
        )
        elapsed = time.monotonic() - t0
        assert result.returncode == 0
        assert elapsed < 5.0


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only feature")
class TestTheCallEndsWhenTheAgentDoes:
    """Nothing the agent spawned may keep the call open, or outlive it.

    ``_run_in_session_with_timeout`` armed its watchdog for the timeout only.
    When the direct child exited first, nothing was signalled and
    ``communicate()`` waited on the pipe for as long as any descendant held
    it — the agent had finished and ``agent_call.py`` sat there as a zombie.
    """

    def test_a_grandchild_holding_the_pipe_does_not_keep_the_call_open(
        self, agent_call, tmp_path
    ):
        cmd, ticks = _leader_cmd(tmp_path, grandchild="default", leader="exit")
        try:
            t0 = time.monotonic()
            result = agent_call._run_in_session_with_timeout(
                cmd, capture_output=True, timeout=60
            )
            elapsed = time.monotonic() - t0

            assert result.returncode == 0
            assert "leader started" in result.stdout
            assert elapsed < 15.0, (
                f"the agent exited at once but the call took {elapsed:.1f}s — it "
                "waited on a pipe held by the agent's grandchild"
            )
            assert not _still_ticking(ticks), "the grandchild outlived the call"
        finally:
            _reap_grandchild(ticks)

    def test_a_grandchild_that_left_the_group_cannot_keep_the_call_open(
        self, agent_call, tmp_path
    ):
        """It cannot be killed (no ``psutil``), so the read must be bounded."""
        cmd, ticks = _leader_cmd(tmp_path, grandchild="setsid", leader="exit")
        try:
            t0 = time.monotonic()
            result = agent_call._run_in_session_with_timeout(
                cmd, capture_output=True, timeout=60
            )
            elapsed = time.monotonic() - t0

            assert result.returncode == 0
            assert "leader started" in result.stdout
            assert elapsed < 15.0, (
                f"the call took {elapsed:.1f}s waiting for an EOF that a "
                "process outside the group was never going to send"
            )
        finally:
            _reap_grandchild(ticks)

    def test_a_timeout_is_bounded_even_when_the_pipe_holder_escaped(
        self, agent_call, tmp_path
    ):
        cmd, ticks = _leader_cmd(tmp_path, grandchild="setsid", leader="stay")
        try:
            t0 = time.monotonic()
            with pytest.raises(subprocess.TimeoutExpired) as excinfo:
                agent_call._run_in_session_with_timeout(
                    cmd, capture_output=True, timeout=1.0
                )
            elapsed = time.monotonic() - t0

            assert "leader started" in (excinfo.value.output or "")
            assert elapsed < 15.0, (
                f"the timeout fired but the call took {elapsed:.1f}s — it kept "
                "reading a pipe held by a process that left the group"
            )
        finally:
            _reap_grandchild(ticks)


# ---------------------------------------------------------------------------
# The streaming runtimes (claude, cursor-agent) are supervised the same way
# ---------------------------------------------------------------------------

_RESULT_EVENT = (
    '{"type": "result", "subtype": "success", "is_error": false, '
    '"result": "done", "total_cost_usd": 0.25, '
    '"usage": {"input_tokens": 3, "output_tokens": 4}}'
)

# Each stand-in ends on its own well inside a minute, so a regression shows up
# as a red test, never as a suite that hangs or a process left behind.
_SILENT_AGENT = """
import sys, time
sys.stdin.read()
time.sleep(20)
"""

_AGENT_THAT_NEVER_READS_ITS_PROMPT = """
import time
time.sleep(20)
"""

_AGENT_THAT_FLOODS_STDERR = f"""
import signal, sys
signal.alarm(20)  # a write blocked on a full pipe dies here
sys.stdin.read()
sys.stderr.write("x" * 300_000)
sys.stderr.flush()
print({_RESULT_EVENT!r}, flush=True)
"""


def _agent_that_leaves_a_grandchild(ticker: Path, ticks: Path) -> str:
    """Reports its result and exits, leaving a grandchild holding its stdout."""
    return f"""
import os, subprocess, sys, time
sys.stdin.read()
subprocess.Popen([sys.executable, {str(ticker)!r}, {str(ticks)!r}, "default"])
for _ in range(200):  # leave only once the grandchild is up and ticking
    if os.path.exists({str(ticks)!r}) and os.path.getsize({str(ticks)!r}):
        break
    time.sleep(0.05)
print({_RESULT_EVENT!r}, flush=True)
"""


def _fake_claude(tmp_path: Path, monkeypatch, body: str) -> None:
    """Point ``CLAUDE_BIN`` at a stand-in for the claude CLI that runs ``body``."""
    impl = tmp_path / "fake_claude.py"
    impl.write_text(body, encoding="utf-8")
    stub = _write_script(
        tmp_path,
        "claude",
        f"""
        #!/bin/sh
        exec "{sys.executable}" "{impl}" "$@"
        """,
    )
    monkeypatch.setenv("CLAUDE_BIN", str(stub))
    monkeypatch.delenv("RESEARCH_FRAMEWORK_DEFAULT_AGENT", raising=False)


def _claude_vault(tmp_path: Path, *, timeout_s: int) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "default_executor:\n"
        "  type: cli\n"
        "  runtime: claude\n"
        "  model: sonnet\n"
        f"  timeout_s: {timeout_s}\n",
        encoding="utf-8",
    )
    return vault


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only feature")
class TestStreamingCallsAreSupervised:
    """``dispatch()`` and ``run()`` on a stream-json runtime.

    Both read the agent's stdout on the thread that was also the clock. The
    deadline was looked at when a line arrived, so an agent that went quiet
    was never timed out; the prompt was written and stderr was left unread on
    that same thread, so either pipe filling up stopped everything.
    """

    def test_dispatch_times_out_an_agent_that_has_gone_silent(
        self, agent_call, tmp_path, monkeypatch
    ):
        _fake_claude(tmp_path, monkeypatch, _SILENT_AGENT)
        vault = _claude_vault(tmp_path, timeout_s=1)

        t0 = time.monotonic()
        result = agent_call.dispatch("scout", "hi", agent="claude", vault_dir=vault)
        elapsed = time.monotonic() - t0

        assert elapsed < 15.0, (
            f"a 1s timeout took {elapsed:.1f}s: the deadline is only checked "
            "when the agent prints a line, and it printed none"
        )
        assert result.exit_code == 2
        assert result.stderr == "timed out"

    def test_run_times_out_an_agent_that_has_gone_silent(
        self, agent_call, tmp_path, monkeypatch
    ):
        _fake_claude(tmp_path, monkeypatch, _SILENT_AGENT)
        vault = _claude_vault(tmp_path, timeout_s=1)
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("hi\n", encoding="utf-8")
        sidecar = tmp_path / "cycle-001" / "agent-calls" / "scout.json"

        t0 = time.monotonic()
        rc = agent_call.run(vault, "scout", prompt_file, cost_sidecar=sidecar)
        elapsed = time.monotonic() - t0

        assert elapsed < 15.0, f"a 1s timeout took {elapsed:.1f}s"
        assert rc == 2
        recorded = json.loads(sidecar.read_text(encoding="utf-8"))
        assert recorded["timed_out"] is True
        assert recorded["status"] == "failed"

    def test_dispatch_times_out_an_agent_that_never_reads_its_prompt(
        self, agent_call, tmp_path, monkeypatch
    ):
        """A prompt larger than the pipe must not be written on the clock's thread."""
        _fake_claude(tmp_path, monkeypatch, _AGENT_THAT_NEVER_READS_ITS_PROMPT)
        vault = _claude_vault(tmp_path, timeout_s=1)

        t0 = time.monotonic()
        result = agent_call.dispatch(
            "scout", "a line of prompt\n" * 60_000, agent="claude", vault_dir=vault
        )
        elapsed = time.monotonic() - t0

        assert elapsed < 15.0, (
            f"a 1s timeout took {elapsed:.1f}s: the call was stuck writing a "
            "prompt nobody was reading"
        )
        assert result.exit_code == 2
        assert result.stderr == "timed out"

    def test_dispatch_reads_stderr_while_the_agent_is_still_running(
        self, agent_call, tmp_path, monkeypatch
    ):
        """More than a pipe's worth of stderr used to deadlock the call."""
        _fake_claude(tmp_path, monkeypatch, _AGENT_THAT_FLOODS_STDERR)
        vault = _claude_vault(tmp_path, timeout_s=60)

        t0 = time.monotonic()
        result = agent_call.dispatch("scout", "hi", agent="claude", vault_dir=vault)
        elapsed = time.monotonic() - t0

        assert elapsed < 15.0, (
            f"the call took {elapsed:.1f}s: the agent was blocked writing to a "
            "stderr pipe that is only read after it exits"
        )
        assert result.exit_code == 0
        assert result.cost_usd == pytest.approx(0.25)
        assert len(result.stderr) == 300_000

    def test_run_ends_when_the_agent_does_even_if_a_grandchild_holds_the_pipe(
        self, agent_call, tmp_path, monkeypatch
    ):
        """The 2026-05-31 zombie cycle, on the claude path."""
        ticker = tmp_path / "ticker.py"
        ticker.write_text(_TICKER, encoding="utf-8")
        ticks = tmp_path / "grandchild.ticks"
        _fake_claude(
            tmp_path, monkeypatch, _agent_that_leaves_a_grandchild(ticker, ticks)
        )
        vault = _claude_vault(tmp_path, timeout_s=60)
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("hi\n", encoding="utf-8")
        sidecar = tmp_path / "cycle-001" / "agent-calls" / "scout.json"

        try:
            t0 = time.monotonic()
            rc = agent_call.run(vault, "scout", prompt_file, cost_sidecar=sidecar)
            elapsed = time.monotonic() - t0

            assert elapsed < 15.0, (
                f"the agent exited at once but the call took {elapsed:.1f}s — it "
                "kept reading a pipe held by the agent's grandchild"
            )
            assert rc == 0
            recorded = json.loads(sidecar.read_text(encoding="utf-8"))
            assert recorded["status"] == "ok"
            assert recorded["cost_usd"] == pytest.approx(0.25)
            assert not _still_ticking(ticks), "the grandchild outlived the call"
        finally:
            _reap_grandchild(ticks)

    def test_a_consumer_that_fails_ends_the_call_instead_of_waiting_it_out(
        self, agent_call, tmp_path
    ):
        """Output that cannot be delivered is not worth an hour of agent time."""
        script = _write_script(
            tmp_path,
            "one_line_then_busy.sh",
            """
            #!/bin/sh
            printf 'first line\\n'
            sleep 20
            """,
        )

        def consumer(line: str) -> None:
            raise RuntimeError("stdout is gone")

        t0 = time.monotonic()
        with pytest.raises(RuntimeError, match="stdout is gone"):
            agent_call._supervise_child(
                [str(script)], timeout=60, on_stdout_line=consumer
            )
        elapsed = time.monotonic() - t0

        assert elapsed < 15.0, (
            f"the consumer failed on the first line and the call still took "
            f"{elapsed:.1f}s: the agent was left to run to its end"
        )


# ---------------------------------------------------------------------------
# Being terminated ourselves: the agent must not be left running
# ---------------------------------------------------------------------------


def _agent_that_runs_on(pidfile: Path, *, ignores_sigterm: bool = False) -> str:
    """Says where it is, then keeps going (for 20 s) whatever happens to its parent."""
    return f"""
import os, signal, sys, time
if {ignores_sigterm!r}:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
with open({str(pidfile)!r}, "w") as fh:
    fh.write(str(os.getpid()))
sys.stdin.read()
time.sleep(20)
"""


def _spawn_agent_call(tmp_path: Path, vault: Path, *extra: str) -> subprocess.Popen:
    """``agent_call.py`` as a process of its own, started the way the runner does."""
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("hi\n", encoding="utf-8")
    return popen_session(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--vault",
            str(vault),
            "--stage",
            "scout",
            "--prompt-file",
            str(prompt_file),
            *extra,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _agent_pid(pidfile: Path) -> int:
    t0 = time.monotonic()
    while time.monotonic() - t0 < 15:
        if pidfile.exists() and pidfile.read_text():
            return int(pidfile.read_text())
        time.sleep(0.05)
    pytest.fail("the fake agent never started")


def _is_gone(pid: int, *, within: float = 3.0) -> bool:
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def _kill_quietly(*pids: int) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only feature")
class TestBeingTerminatedStopsTheAgent:
    """A stage timeout must stop the agent, not only the wrapper around it.

    The agent CLI runs in a session of its own, so the SIGTERM a parent sends
    to ``agent_call.py``'s process group (the runner on a stage timeout or
    Ctrl+C) never reaches it. ``agent_call.py`` died on the spot and the agent
    carried on: spending, and writing into a vault the pipeline had moved on
    from.
    """

    @pytest.mark.parametrize("path", ["streaming", "plain"])
    def test_terminating_agent_call_stops_the_agent(self, tmp_path, monkeypatch, path):
        pidfile = tmp_path / "agent.pid"
        _fake_claude(tmp_path, monkeypatch, _agent_that_runs_on(pidfile))
        vault = _claude_vault(tmp_path, timeout_s=60)
        sidecar = tmp_path / "cycle-001" / "agent-calls" / "scout.json"
        extra = ["--cost-sidecar", str(sidecar)] if path == "streaming" else []

        proc = _spawn_agent_call(tmp_path, vault, *extra)
        agent = _agent_pid(pidfile)
        try:
            terminate_process_tree(proc)

            assert _is_gone(agent), (
                "agent_call.py was terminated and the agent it had started is "
                "still running"
            )
            assert proc.returncode == -signal.SIGTERM, (
                "being terminated must still look like death by SIGTERM to "
                f"whoever sent it, got {proc.returncode}"
            )
        finally:
            _kill_quietly(agent, proc.pid)

    def test_an_agent_that_ignores_sigterm_is_killed_within_the_parents_grace(
        self, tmp_path, monkeypatch
    ):
        """The parent SIGKILLs us 2 s after its SIGTERM: be done before that."""
        pidfile = tmp_path / "agent.pid"
        _fake_claude(
            tmp_path, monkeypatch, _agent_that_runs_on(pidfile, ignores_sigterm=True)
        )
        vault = _claude_vault(tmp_path, timeout_s=60)

        proc = _spawn_agent_call(tmp_path, vault)
        agent = _agent_pid(pidfile)  # written once SIGTERM is being ignored
        try:
            terminate_process_tree(proc)

            assert _is_gone(agent), (
                "the agent ignored the forwarded SIGTERM and nothing killed it "
                "before agent_call.py went away"
            )
            assert proc.returncode == -signal.SIGTERM, (
                "agent_call.py was still cleaning up when its parent's SIGKILL "
                f"arrived (returncode {proc.returncode})"
            )
        finally:
            _kill_quietly(agent, proc.pid)

    def test_an_interrupt_during_the_grace_period_still_kills_the_group(
        self, agent_call, tmp_path, monkeypatch
    ):
        """A second Ctrl+C, or our own SIGTERM landing while a timeout is being
        enforced, unwinds out of the middle of the termination."""
        ticker = tmp_path / "ticker.py"
        ticker.write_text(_TICKER, encoding="utf-8")
        ticks = tmp_path / "agent.ticks"

        def interrupted(proc, **kwargs):
            _wait_for_ticks(ticks)  # it is up, and from here on ignores SIGTERM
            agent_call._signal_process_tree(proc, signal.SIGTERM)
            raise KeyboardInterrupt

        monkeypatch.setattr(agent_call, "_terminate_process_tree", interrupted)
        try:
            with pytest.raises(KeyboardInterrupt):
                agent_call._supervise_child(
                    [sys.executable, str(ticker), str(ticks), "ignore-term"],
                    timeout=0.5,
                )

            assert not _still_ticking(ticks), (
                "the termination was interrupted in its grace period and the "
                "agent, which ignores SIGTERM, was left running"
            )
        finally:
            _reap_grandchild(ticks)

    def test_the_handler_is_not_installed_for_in_process_callers(
        self, agent_call, tmp_path
    ):
        """``main()`` and ``dispatch()`` also run inside a host process, whose
        signal handling is not ours to replace."""
        before = signal.getsignal(signal.SIGTERM)

        assert agent_call.main(["--vault", str(tmp_path / "nope"), "--stage", "x"]) == 2

        assert signal.getsignal(signal.SIGTERM) is before


# ---------------------------------------------------------------------------
# End-to-end: ``run()`` honours the tree-kill (the actual codex path)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only feature")
class TestRunDispatchUsesTreeKill:
    def test_run_with_stuck_subprocess_returns_within_budget(
        self, agent_call, tmp_path
    ):
        """End-to-end version of the post-mortem scenario.

        We build a vault whose ``default_executor`` points at a python
        script that forks a grandchild via ``subprocess.Popen`` and then
        sleeps far longer than the configured timeout. We assert that
        ``run()`` returns the timeout exit code within ~10s. Before the
        fix this test would have hung for ~60s + drain because the
        orphaned grandchild kept the stdout pipe open.
        """
        # Python script that mimics the codex shape: a parent that spawns
        # a long-running grandchild and then itself sleeps. We use
        # ``type: script`` + ``runtime: python`` so ``_build_command``
        # resolves to ``[sys.executable, script_path]``.
        grandchild_py = tmp_path / "spawn_grandchild.py"
        grandchild_py.write_text(
            textwrap.dedent(
                """
                import subprocess, sys, time
                # Spawn a grandchild that lives well past any reasonable timeout.
                subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(120)"],
                )
                # Parent: also sleep, longer than the test budget.
                time.sleep(60)
                """
            ).lstrip("\n"),
            encoding="utf-8",
        )
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "settings.yaml").write_text(
            f"""
            default_executor:
              type: script
              runtime: python
              script_path: {grandchild_py}
              timeout_s: 1
            stages: {{}}
            """,
            encoding="utf-8",
        )
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("doesn't matter\n", encoding="utf-8")

        t0 = time.monotonic()
        rc = agent_call.run(
            vault,
            "any_stage",
            prompt_file,
        )
        elapsed = time.monotonic() - t0
        assert rc == 2, "timeout exit code must be 2"
        assert elapsed < 10.0, (
            f"run() took {elapsed:.1f}s after a timeout — the process tree "
            "is not being killed (regression of the 2026-05-30 post-mortem fix)"
        )
