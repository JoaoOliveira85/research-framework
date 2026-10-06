"""A6 (spec 025 US3): quality-report context-manager guard exit paths."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.pipeline.test_cycle_runner import (
    _make_subproc_run,
    _make_vault,
    _patch_cycle_runner_subprocess,
)

_CYCLE = 1
_CYCLE_3 = f"{_CYCLE:03d}"


def _report_path(vault: Path) -> Path:
    return vault / "_pipeline" / "cycles" / f"cycle-{_CYCLE_3}-quality-report.json"


def _prepare_happy_vault(vault: Path) -> None:
    cycles = vault / "_pipeline" / "cycles"
    (cycles / f"cycle-{_CYCLE_3}-scout.json").write_text("{}")
    (cycles / f"cycle-{_CYCLE_3}-research.json").write_text("{}")
    (vault / "_pipeline" / "vault-metrics.json").write_text("{}")


def _read_report(vault: Path) -> dict:
    return json.loads(_report_path(vault).read_text(encoding="utf-8"))


def test_happy_path_writes_once(tmp_path: Path) -> None:
    from research_framework.pipeline.cycle_runner import run_cycle_steps

    vault = _make_vault(tmp_path)
    _prepare_happy_vault(vault)

    with _patch_cycle_runner_subprocess(_make_subproc_run()):
        rc = run_cycle_steps(vault, _CYCLE)

    assert rc == 0
    assert _report_path(vault).is_file()
    report = _read_report(vault)
    assert report.get("exit_status") == "success"
    assert "exception" not in report or report.get("exception") is None


def test_scout_failure_writes_once(tmp_path: Path) -> None:
    from research_framework.pipeline.cycle_runner import run_cycle_steps

    vault = _make_vault(tmp_path)
    _prepare_happy_vault(vault)

    def _scout_raises(cmd, **kwargs):
        script_name = Path(cmd[1]).name
        if script_name == "agent_call.py" and "--stage" in cmd:
            stage_idx = cmd.index("--stage")
            if cmd[stage_idx + 1] == "scout":
                raise RuntimeError("scout agent failed")
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    with _patch_cycle_runner_subprocess(_scout_raises):
        with pytest.raises(RuntimeError, match="scout agent failed"):
            run_cycle_steps(vault, _CYCLE)

    assert _report_path(vault).is_file()
    report = _read_report(vault)
    assert report.get("exit_status") == "failure"
    assert report.get("exception")


def test_keyboard_interrupt_writes_once(tmp_path: Path) -> None:
    from research_framework.pipeline.cycle_runner import run_cycle_steps

    vault = _make_vault(tmp_path)
    _prepare_happy_vault(vault)

    def _interrupt_on_scout(cmd, **kwargs):
        script_name = Path(cmd[1]).name
        if script_name == "agent_call.py" and "--stage" in cmd:
            stage_idx = cmd.index("--stage")
            if cmd[stage_idx + 1] == "scout":
                raise KeyboardInterrupt
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    with _patch_cycle_runner_subprocess(_interrupt_on_scout):
        with pytest.raises(KeyboardInterrupt):
            run_cycle_steps(vault, _CYCLE)

    assert _report_path(vault).is_file()
    report = _read_report(vault)
    assert report.get("exit_status") == "interrupted"


@pytest.mark.parametrize(
    "scenario",
    ["happy", "scout_failure", "keyboard_interrupt"],
)
def test_write_count_is_exactly_one(tmp_path: Path, scenario: str) -> None:
    from research_framework.pipeline import cycle_runner

    vault = _make_vault(tmp_path)
    _prepare_happy_vault(vault)
    calls: list[tuple[Path, int] | object] = []
    real_write = cycle_runner._write_cycle_quality_report

    def _counting_write(state) -> None:
        calls.append(state)
        return real_write(state)

    if scenario == "happy":
        fake_run = _make_subproc_run()
        run_expectation: object = None
    elif scenario == "scout_failure":

        def _scout_raises(cmd, **kwargs):
            script_name = Path(cmd[1]).name
            if script_name == "agent_call.py" and "--stage" in cmd:
                stage_idx = cmd.index("--stage")
                if cmd[stage_idx + 1] == "scout":
                    raise RuntimeError("scout agent failed")
            mock = MagicMock()
            mock.returncode = 0
            mock.stdout = b""
            return mock

        fake_run = _scout_raises
        run_expectation = pytest.raises(RuntimeError, match="scout agent failed")
    else:

        def _interrupt_on_scout(cmd, **kwargs):
            script_name = Path(cmd[1]).name
            if script_name == "agent_call.py" and "--stage" in cmd:
                stage_idx = cmd.index("--stage")
                if cmd[stage_idx + 1] == "scout":
                    raise KeyboardInterrupt
            mock = MagicMock()
            mock.returncode = 0
            mock.stdout = b""
            return mock

        fake_run = _interrupt_on_scout
        run_expectation = pytest.raises(KeyboardInterrupt)

    with patch.object(
        cycle_runner, "_write_cycle_quality_report", side_effect=_counting_write
    ):
        with _patch_cycle_runner_subprocess(fake_run):
            if run_expectation is not None:
                with run_expectation:
                    cycle_runner.run_cycle_steps(vault, _CYCLE)
            else:
                cycle_runner.run_cycle_steps(vault, _CYCLE)

    assert len(calls) == 1, f"expected exactly one write, got {len(calls)}"
