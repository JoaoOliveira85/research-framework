"""``kill <pid>`` of the CLI stops what it was running, then dies of that signal.

The agent wrapper (``agent_call.py``) and the agent CLI each run in a session
of their own, so a SIGTERM sent to the pipeline process reaches neither of
them. Python's default for SIGTERM is to die on the spot, without running a
single ``finally``: the pipeline was gone and the stage it had dispatched ran
on — spending, and writing into the vault — with nothing left to supervise it.

Real processes all the way down: the real CLI, the real
``scripts/agent_call.py`` and a stand-in for the ``claude`` binary
(``CLAUDE_BIN``) that says where it is and stays. No LLM is involved. Only
pids this test started are ever signalled.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from research_framework import cli
from tests._helpers.vault_factory import build_minimal_vault, install_bundled_skill

REPO_ROOT = Path(__file__).resolve().parents[2]

_AGENT_LIFETIME_S = 30


def _an_agent_that_stays(tmp_path: Path) -> tuple[Path, Path]:
    """A ``claude`` that records its own pid and its parent's — the wrapper's."""
    pidfile = tmp_path / "agent.pid"
    impl = tmp_path / "fake_claude.py"
    impl.write_text(
        "import os, sys, time\n"
        f"with open({str(pidfile)!r}, 'w') as fh:\n"
        "    fh.write(f'{os.getpid()} {os.getppid()}')\n"
        "sys.stdin.read()\n"
        f"time.sleep({_AGENT_LIFETIME_S})\n",
        encoding="utf-8",
    )
    stub = tmp_path / "claude"
    stub.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{impl}" "$@"\n', encoding="utf-8"
    )
    stub.chmod(0o755)
    return stub, pidfile


def _agent_and_wrapper(pidfile: Path, cli: subprocess.Popen[bytes]) -> tuple[int, int]:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if pidfile.exists():
            pids = pidfile.read_text().split()
            if len(pids) == 2:
                return int(pids[0]), int(pids[1])
        if cli.poll() is not None:
            pytest.fail(f"the CLI exited ({cli.returncode}) before the agent started")
        time.sleep(0.05)
    pytest.fail("the stand-in agent never started")


def _is_gone(pid: int, *, within_s: float = 5.0) -> bool:
    deadline = time.monotonic() + within_s
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def _kill_quietly(*pids: int | None) -> None:
    for pid in pids:
        if pid is None:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only feature")
@pytest.mark.parametrize("verb", ["cycle", "pipeline"])
def test_terminating_the_cli_stops_the_wrapper_and_the_agent(
    tmp_path: Path, verb: str
) -> None:
    """Both runtimes: ``cycle`` (``_run_script``) and ``pipeline`` (``_dispatch_agent``)."""
    vault = build_minimal_vault(
        tmp_path,
        num_categories=1,
        num_targets_per_category=3,
        max_cycles=1,
        install_fake_agent=False,
    )
    install_bundled_skill(vault, "scout")
    stub, pidfile = _an_agent_that_stays(tmp_path)
    env = {**os.environ, "CLAUDE_BIN": str(stub)}
    env.pop("RESEARCH_FRAMEWORK_DEFAULT_AGENT", None)
    argv = {
        "cycle": ["cycle", "--vault", str(vault), "--cycle", "1", "--budget-cap", "50"],
        "pipeline": ["pipeline", str(vault), "scout"],
    }[verb]

    agent: int | None = None
    wrapper: int | None = None
    with (tmp_path / "cli.log").open("wb") as log:
        cli = subprocess.Popen(
            [sys.executable, "-m", "research_framework.cli", *argv],
            cwd=REPO_ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            agent, wrapper = _agent_and_wrapper(pidfile, cli)

            os.kill(cli.pid, signal.SIGTERM)  # what ``kill <pid>`` sends
            returncode = cli.wait(timeout=60)

            assert _is_gone(wrapper), (
                "the CLI was terminated and agent_call.py, which it had "
                "started, is still running"
            )
            assert _is_gone(agent), (
                "the CLI was terminated and the agent its stage had started "
                "is still running"
            )
            assert returncode == -signal.SIGTERM, (
                "being terminated must still look like death by SIGTERM to "
                f"whoever sent it, got {returncode}"
            )
        finally:
            _kill_quietly(agent, wrapper, cli.pid)


# ---------------------------------------------------------------------------
# ``main`` also runs inside host processes: their SIGTERM is not ours to keep
# ---------------------------------------------------------------------------


class _OneVerb:
    """A parser whose only verb reports the SIGTERM handler it ran under."""

    def __init__(self) -> None:
        self.during: object = None

    def parse_args(self, _argv: list[str] | None) -> argparse.Namespace:
        return argparse.Namespace(func=self._verb)

    def _verb(self, _args: argparse.Namespace) -> int:
        self.during = signal.getsignal(signal.SIGTERM)
        return 0


def test_main_puts_the_sigterm_disposition_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = _OneVerb()
    monkeypatch.setattr(cli, "build_parser", lambda: parser)
    before = signal.getsignal(signal.SIGTERM)

    assert cli.main([]) == 0

    assert parser.during is cli._on_sigterm, "the verb did not run under the unwind"
    assert signal.getsignal(signal.SIGTERM) is before
    assert issubclass(cli._Terminated, KeyboardInterrupt), (
        "a terminated cycle is recorded as interrupted only because the unwind "
        "is a KeyboardInterrupt"
    )


def test_main_does_not_replace_a_hosts_sigterm_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser = _OneVerb()
    monkeypatch.setattr(cli, "build_parser", lambda: parser)

    def _hosts_handler(_signum: int, _frame: object) -> None:
        return None

    before = signal.signal(signal.SIGTERM, _hosts_handler)
    try:
        assert cli.main([]) == 0

        assert parser.during is _hosts_handler
        assert signal.getsignal(signal.SIGTERM) is _hosts_handler
    finally:
        signal.signal(signal.SIGTERM, before)
