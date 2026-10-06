"""Unit tests for pipeline.steps.research.run_research (spec 025 US6 T055)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from research_framework.pipeline.cycle_runner import _load_yaml_settings
from research_framework.pipeline.steps import CycleContext, ScoutResult, run_research
from research_framework.pipeline.steps._types import ScoutedTopic
from tests.pipeline.test_cycle_runner import _make_vault, _patch_cycle_runner_subprocess


def _ctx(vault: Path) -> CycleContext:
    pipeline = vault / "_pipeline"
    cycles = pipeline / "cycles"
    return CycleContext(
        vault_dir=vault,
        cycle_num=1,
        cycle_dir=cycles / "cycle-001",
        settings=_load_yaml_settings(vault / "settings.yaml"),
        scripts_dir=vault / "scripts",
        pipeline_dir=pipeline,
        cycles_dir=cycles,
        prompts_dir=pipeline / "prompts",
        python_bin="python3",
        env={"RV_PYTHON": "python3"},
    )


def test_run_research_happy_path(tmp_path: Path) -> None:
    """Research step runs note_writer when dfs prompt exists."""
    vault = _make_vault(tmp_path)
    cycles = vault / "_pipeline" / "cycles"
    research_path = cycles / "cycle-001-research.json"
    calls: list[str] = []

    def _fake_run(cmd, **kwargs):
        script = Path(cmd[1]).name if len(cmd) > 1 else ""
        if script == "agent_call.py" and "--stage" in cmd:
            stage = cmd[cmd.index("--stage") + 1]
            calls.append(stage)
            if stage == "note_writer":
                research_path.parent.mkdir(parents=True, exist_ok=True)
                research_path.write_text(
                    json.dumps({"notes_created": []}), encoding="utf-8"
                )
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    scout = ScoutResult(
        topics_found=[ScoutedTopic(title="Alpha")],
        sg_trips=[],
        duration_ms=1,
        cost_usd=0.0,
        raw_json_path=cycles / "cycle-001-scout.json",
        exit_code=0,
    )

    with _patch_cycle_runner_subprocess(_fake_run):
        result = run_research(_ctx(vault), scout)

    assert "note_writer" in calls
    assert result.raw_json_path.is_file()


def test_run_research_missing_dfs_skips_note_writer(tmp_path: Path) -> None:
    """Missing dfs-prompt.md aborts research before note_writer runs."""
    vault = _make_vault(tmp_path, dfs_prompt=False)
    scout = ScoutResult(
        topics_found=[],
        sg_trips=[],
        duration_ms=0,
        cost_usd=0.0,
        raw_json_path=vault / "_pipeline/cycles/cycle-001-scout.json",
        exit_code=0,
    )
    calls: list[str] = []

    def _fake_run(cmd, **kwargs):
        if len(cmd) > 1 and Path(cmd[1]).name == "agent_call.py" and "--stage" in cmd:
            calls.append(cmd[cmd.index("--stage") + 1])
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    with _patch_cycle_runner_subprocess(_fake_run):
        run_research(_ctx(vault), scout)

    assert "note_writer" not in calls


def test_run_research_reports_its_own_abort(tmp_path: Path) -> None:
    """The phase's exit code reaches the caller instead of being dropped."""
    scout = ScoutResult(
        topics_found=[],
        sg_trips=[],
        duration_ms=0,
        cost_usd=0.0,
        raw_json_path=tmp_path / "vault/_pipeline/cycles/cycle-001-scout.json",
        exit_code=0,
    )

    def _fake_run(cmd, **kwargs):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    aborted = _make_vault(tmp_path / "aborted", dfs_prompt=False)
    with _patch_cycle_runner_subprocess(_fake_run):
        assert run_research(_ctx(aborted), scout).exit_code == 2

    ran = _make_vault(tmp_path / "ran")
    with _patch_cycle_runner_subprocess(_fake_run):
        assert run_research(_ctx(ran), scout).exit_code == 0
