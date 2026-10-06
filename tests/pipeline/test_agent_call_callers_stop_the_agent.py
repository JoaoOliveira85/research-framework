"""A caller that gives up on ``agent_call.py`` stops the agent, not only the wrapper.

``agent_call.py`` runs the agent CLI in a session of its own and forwards a
SIGTERM to it. A SIGKILL it cannot forward: nothing can. The callers that put
a timeout of their own on the wrapper used ``subprocess.run(timeout=…)``, which
SIGKILLs the direct child when the time is up. The wrapper died and the agent
it had started ran on — spending, and writing into a vault the caller had
moved on from.

Real processes all the way down: the real ``scripts/agent_call.py`` and a
stand-in for the ``claude`` binary (``CLAUDE_BIN``) that says where it is and
outlives the caller's timeout. No LLM is involved.
"""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

import pytest

from research_framework.benchmark import runner as benchmark_runner
from research_framework.benchmark.matrix import Cell
from research_framework.pipeline.verifier import run_verifier_stage

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "benchmark"

#: The caller's timeout. Long enough for the wrapper to have started the
#: agent, on a busy machine too; the agent itself would run for 20 s.
_CALLER_TIMEOUT_S = 3
_AGENT_LIFETIME_S = 20


def _an_agent_that_outlives_the_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Point ``CLAUDE_BIN`` at a stand-in that records its pid and carries on."""
    pidfile = tmp_path / "agent.pid"
    impl = tmp_path / "fake_claude.py"
    impl.write_text(
        "import os, sys, time\n"
        f"with open({str(pidfile)!r}, 'w') as fh:\n"
        "    fh.write(str(os.getpid()))\n"
        "sys.stdin.read()\n"
        f"time.sleep({_AGENT_LIFETIME_S})\n",
        encoding="utf-8",
    )
    stub = tmp_path / "claude"
    stub.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{impl}" "$@"\n', encoding="utf-8"
    )
    stub.chmod(0o755)
    monkeypatch.setenv("CLAUDE_BIN", str(stub))
    monkeypatch.delenv("RESEARCH_FRAMEWORK_DEFAULT_AGENT", raising=False)
    return pidfile


def _agent_pid(pidfile: Path) -> int:
    if not (pidfile.exists() and pidfile.read_text()):
        pytest.fail(
            "the stand-in agent had not started when the caller's "
            f"{_CALLER_TIMEOUT_S}s timeout fired — nothing was tested"
        )
    return int(pidfile.read_text())


def _is_gone(pid: int, *, within_s: float = 5.0) -> bool:
    deadline = time.monotonic() + within_s
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def _kill_the_agent(pidfile: Path) -> None:
    """Never leave the stand-in behind, whatever the test concluded."""
    try:
        os.kill(int(pidfile.read_text()), signal.SIGKILL)
    except (OSError, ValueError):
        pass


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only feature")
def test_a_verifier_timeout_stops_the_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pidfile = _an_agent_that_outlives_the_timeout(tmp_path, monkeypatch)
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "default_executor:\n"
        "  type: cli\n"
        "  runtime: claude\n"
        "  model: sonnet\n"
        "  timeout_s: 60\n",
        encoding="utf-8",
    )
    note_rel = "data_vault/01 - Concepts/Alpha.md"
    note = vault / note_rel
    note.parent.mkdir(parents=True)
    note.write_text("---\ntitle: Alpha\n---\n\nBody text.\n", encoding="utf-8")

    try:
        summary = run_verifier_stage(
            vault,
            1,
            {"notes_created": [note_rel], "notes_updated": []},
            scripts_dir=REPO_ROOT / "scripts",
            settings={"stages": {"verifier": {"timeout_s": _CALLER_TIMEOUT_S}}},
        )

        assert [v.status for v in summary.verdicts] == ["pending"]
        assert _is_gone(_agent_pid(pidfile)), (
            "the verifier timed out and killed agent_call.py; the agent it had "
            "started is still running"
        )
    finally:
        _kill_the_agent(pidfile)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only feature")
def test_a_benchmark_cell_timeout_stops_the_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``live_dispatch`` with a stand-in binary: hermetic, though the path is live."""
    pidfile = _an_agent_that_outlives_the_timeout(tmp_path, monkeypatch)
    cell = Cell(task="verifier", executor="claude", model="sonnet")

    try:
        out = benchmark_runner.live_dispatch(
            cell,
            fixture_dir=BENCHMARK_FIXTURE,
            cell_dir=tmp_path / cell.key,
            timeout_s=_CALLER_TIMEOUT_S,
        )

        assert out.status == "failed"
        assert out.reason == f"timed out after {_CALLER_TIMEOUT_S}s"
        assert _is_gone(_agent_pid(pidfile)), (
            "the benchmark cell timed out and killed agent_call.py; the agent "
            "it had started is still running"
        )
    finally:
        _kill_the_agent(pidfile)
