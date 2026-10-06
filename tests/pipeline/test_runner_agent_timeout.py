"""``_call_agent`` must be bounded, isolated, and keep what the agent said.

Issue #220.  The pipeline runner dispatched its agent with a bare
``subprocess.run(cmd)`` — no timeout, no process group — and under ``quiet``
used ``capture_output=True`` and then dropped ``result.stdout`` /
``result.stderr`` on the floor.  Three consequences, all of them live in the
weekly run:

* a hung agent hangs the pipeline forever.  This is the documented 2026-05-31
  zombie-pipe postmortem: the inner timeout fired, the agent's grandchildren
  kept the pipe open, and ``agent_call.py`` stayed alive for 3h 17m.
* killing the direct child leaves those grandchildren running, and the pipe
  they hold open means the parent's read never sees EOF.
* the agent's own diagnostics — the thing that says *why* it exited 3 — were
  captured and discarded.

The framework already owns the primitives (``popen_session`` /
``terminate_process_tree``); the pipeline runner just was not using them.

The stand-in agent here is a plain Python script, not
``tests/_helpers/fake_agent``: what is under test is the subprocess boundary
(hanging, forking, writing to stderr), not any LLM behaviour.  No LLM is
reached and nothing is spent.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

import pytest

from research_framework.pipeline.runner import (
    FAILED,
    STATE_FILE,
    _call_agent,
    run_scout,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _vault_with_agent(tmp_path: Path, body: str) -> Path:
    """A vault whose ``scripts/agent_call.py`` is ``body`` and whose scout
    stage has a prompt template to render."""
    script = tmp_path / "scripts" / "agent_call.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(body, encoding="utf-8")

    prompt = tmp_path / "_pipeline" / "prompts" / "scout-prompt.md"
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("Scout cycle {CYCLE_NUM} → {SCOUT_REPORT}\n", encoding="utf-8")
    return tmp_path


def _phase(vault: Path, name: str) -> dict:
    state = json.loads((vault / STATE_FILE).read_text(encoding="utf-8"))
    return state["phases"][name]


_SLEEP_FOREVER = """
import time
while True:
    time.sleep(0.05)
"""

_SPAWN_A_GRANDCHILD_THEN_SLEEP = '''
import subprocess, sys, time
MARKER = "__MARKER__"
subprocess.Popen([sys.executable, "-c", """
import time
for _ in range(600):  # ~30s: bounded even if nothing stops it
    with open("__MARKER__", "a") as fh:
        print("tick", file=fh)
    time.sleep(0.05)
"""])
while True:
    time.sleep(0.05)
'''

_SPAWN_A_GRANDCHILD_THEN_EXIT = '''
import os, subprocess, sys, time
MARKER = "__MARKER__"
subprocess.Popen([sys.executable, "-c", """
import os, time
with open("__MARKER__.pid", "w") as fh:
    fh.write(str(os.getpid()))
for _ in range(400):  # ~20s: bounded even if nothing stops it
    with open("__MARKER__", "a") as fh:
        print("tick", file=fh)
    time.sleep(0.05)
"""])
for _ in range(200):  # leave only once the grandchild is up and ticking
    if os.path.exists(MARKER) and os.path.getsize(MARKER):
        break
    time.sleep(0.05)
print("scout: wrote 0 topics")
'''

_FAIL_LOUDLY = """
import sys
print("scout: reading the coverage targets", flush=True)
print("scout: BOOM — coverage-targets.json is not a mapping", file=sys.stderr, flush=True)
sys.exit(3)
"""

_SUCCEED_QUIETLY = """
print("scout: wrote 0 topics")
"""


@pytest.fixture(autouse=True)
def _short_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RF_PIPELINE_AGENT_TIMEOUT_S", "2")


# ---------------------------------------------------------------------------
# timeout
# ---------------------------------------------------------------------------


class TestAHungAgentIsBounded:
    def test_a_hung_agent_does_not_hang_the_pipeline(self, tmp_path: Path) -> None:
        vault = _vault_with_agent(tmp_path, _SLEEP_FOREVER)

        started = time.monotonic()
        rc = run_scout(vault, quiet=True)
        elapsed = time.monotonic() - started

        assert rc != 0
        assert elapsed < 30, "the weekly pipeline waited forever for this"

    def test_the_timeout_is_the_recorded_reason(self, tmp_path: Path) -> None:
        vault = _vault_with_agent(tmp_path, _SLEEP_FOREVER)

        run_scout(vault, quiet=True)

        rec = _phase(vault, "scout")
        assert rec["status"] == FAILED
        assert any("timed out" in e for e in rec["errors"]), rec["errors"]

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
    def test_the_agents_grandchildren_are_killed_too(self, tmp_path: Path) -> None:
        """A grandchild that survives keeps the stdout pipe open, and the
        parent's read then blocks on an EOF that never comes."""
        marker = tmp_path / "grandchild.log"
        vault = _vault_with_agent(
            tmp_path,
            _SPAWN_A_GRANDCHILD_THEN_SLEEP.replace("__MARKER__", str(marker)),
        )

        run_scout(vault, quiet=True)

        # Without this the test passes on a grandchild that never ran, which
        # it did for as long as its script had a syntax error in it.
        assert marker.exists() and marker.stat().st_size > 0, (
            "the grandchild never started ticking"
        )
        time.sleep(0.5)
        settled = marker.read_bytes()
        time.sleep(0.5)
        after = marker.read_bytes()
        assert after == settled, "the grandchild outlived terminate_process_tree"

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
    def test_what_the_agent_left_running_does_not_outlive_a_clean_exit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exit 0 says nothing about what the agent forked. Only the timeout
        and the interrupt terminated the process group, so after a normal exit
        its descendants ran on, holding the pipe the runner reads."""
        monkeypatch.setenv("RF_PIPELINE_AGENT_TIMEOUT_S", "60")
        marker = tmp_path / "grandchild.log"
        vault = _vault_with_agent(
            tmp_path,
            _SPAWN_A_GRANDCHILD_THEN_EXIT.replace("__MARKER__", str(marker)),
        )

        try:
            outcome = _call_agent(
                vault,
                stage="scout",
                quiet=True,
                prompt_file=vault / "_pipeline" / "prompts" / "scout-prompt.md",
            )

            assert outcome.returncode == 0
            assert outcome.timed_out is False
            settled = marker.read_bytes()
            time.sleep(0.5)
            assert marker.read_bytes() == settled, (
                "the agent exited 0 and what it had forked is still running"
            )
        finally:
            try:
                os.kill(int(Path(f"{marker}.pid").read_text()), signal.SIGKILL)
            except (OSError, ValueError):
                pass


# ---------------------------------------------------------------------------
# captured output
# ---------------------------------------------------------------------------


class TestTheAgentsOutputSurvives:
    def test_a_failing_agents_diagnostic_reaches_the_phase_errors(
        self, tmp_path: Path
    ) -> None:
        vault = _vault_with_agent(tmp_path, _FAIL_LOUDLY)

        rc = run_scout(vault, quiet=True)

        assert rc == 1
        rec = _phase(vault, "scout")
        joined = "\n".join(rec["errors"])
        assert "exited with code 3" in joined
        assert "coverage-targets.json is not a mapping" in joined

    def test_quiet_captures_the_output_instead_of_discarding_it(
        self, tmp_path: Path
    ) -> None:
        """``quiet=True`` used to mean ``capture_output=True`` followed by
        throwing both streams away — the one mode the weekly run uses."""
        vault = _vault_with_agent(tmp_path, _FAIL_LOUDLY)

        outcome = _call_agent(
            vault,
            stage="scout",
            quiet=True,
            prompt_file=vault / "_pipeline" / "prompts" / "scout-prompt.md",
        )

        assert outcome.returncode == 3
        assert "coverage-targets.json is not a mapping" in outcome.output_tail

    def test_the_run_leaves_a_per_phase_log(self, tmp_path: Path) -> None:
        """Spec 080 FR-003 moved this file under the run directory; what it
        must contain — everything the agent said, including the failure the
        operator is looking for — is unchanged."""
        vault = _vault_with_agent(tmp_path, _FAIL_LOUDLY)

        run_scout(vault, quiet=True)

        logs = sorted((vault / "_pipeline" / "runs").glob("*/logs/scout*.log"))
        assert logs, "no framework-owned record of what the agent said"
        text = logs[0].read_text(encoding="utf-8")
        assert "reading the coverage targets" in text
        assert "coverage-targets.json is not a mapping" in text

    def test_the_phase_summary_names_that_log(self, tmp_path: Path) -> None:
        vault = _vault_with_agent(tmp_path, _SUCCEED_QUIETLY)

        run_scout(vault, quiet=True)

        summary = _phase(vault, "scout")["summary"] or {}
        assert Path(summary["agent_log"]).is_file()

    def test_a_successful_agent_still_returns_zero(self, tmp_path: Path) -> None:
        vault = _vault_with_agent(tmp_path, _SUCCEED_QUIETLY)

        outcome = _call_agent(
            vault,
            stage="scout",
            quiet=True,
            prompt_file=vault / "_pipeline" / "prompts" / "scout-prompt.md",
        )

        assert outcome.returncode == 0
        assert outcome.timed_out is False


# ---------------------------------------------------------------------------
# timeout resolution
# ---------------------------------------------------------------------------


class TestTimeoutResolution:
    def test_the_vaults_own_stage_timeout_is_honoured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The operator already sets ``stages.<stage>.timeout_s`` for the inner
        dispatcher.  The runner's outer bound is that plus a grace margin — it
        exists to catch the inner timeout failing to fire, not to pre-empt it."""
        from research_framework.pipeline.runner import _agent_timeout_s

        monkeypatch.delenv("RF_PIPELINE_AGENT_TIMEOUT_S", raising=False)
        (tmp_path / "settings.yaml").write_text(
            "default_executor:\n  timeout_s: 100\nstages:\n  scout:\n"
            "    timeout_s: 900\n",
            encoding="utf-8",
        )

        assert _agent_timeout_s(tmp_path, "scout") > 900
        assert _agent_timeout_s(tmp_path, "report") > 100
        assert _agent_timeout_s(tmp_path, "report") < 900

    def test_a_vault_with_no_settings_still_gets_a_bound(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from research_framework.pipeline.runner import _agent_timeout_s

        monkeypatch.delenv("RF_PIPELINE_AGENT_TIMEOUT_S", raising=False)

        assert _agent_timeout_s(tmp_path, "scout") is not None

    def test_the_bound_can_be_lifted_deliberately(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An operator babysitting a long interactive run needs an escape
        hatch; a silent unbounded default is what caused the bug."""
        from research_framework.pipeline.runner import _agent_timeout_s

        monkeypatch.setenv("RF_PIPELINE_AGENT_TIMEOUT_S", "0")

        assert _agent_timeout_s(tmp_path, "scout") is None

    def test_an_unparseable_override_falls_back_rather_than_crashing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from research_framework.pipeline.runner import _agent_timeout_s

        monkeypatch.setenv("RF_PIPELINE_AGENT_TIMEOUT_S", "half an hour")

        assert _agent_timeout_s(tmp_path, "scout") is not None
