"""Unit tests for pipeline.steps.postprocess.run_postprocess (spec 025 US6 T056)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from research_framework.pipeline.cycle_runner import _load_yaml_settings
from research_framework.pipeline.steps import (
    CycleContext,
    ResearchResult,
    run_postprocess,
)
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


def _research_result(vault: Path) -> ResearchResult:
    path = vault / "_pipeline/cycles/cycle-001-research.json"
    return ResearchResult(
        notes_written=[],
        notes_rejected=[],
        duration_ms=0,
        cost_usd=0.0,
        raw_json_path=path,
    )


def test_run_postprocess_happy_path(tmp_path: Path) -> None:
    """Postprocess returns validator exit code 0 when research report exists."""
    vault = _make_vault(tmp_path)
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True, exist_ok=True)
    (cycles / "cycle-001-research.json").write_text("{}", encoding="utf-8")
    (vault / "_pipeline" / "vault-metrics.json").write_text("{}", encoding="utf-8")

    def _fake_run(cmd, **kwargs):
        script = Path(cmd[1]).name if len(cmd) > 1 else ""
        mock = MagicMock()
        mock.stdout = b""
        mock.returncode = 0 if script == "validate_cycle.py" else 0
        return mock

    with _patch_cycle_runner_subprocess(_fake_run):
        result = run_postprocess(_ctx(vault), _research_result(vault))

    assert result.exit_code == 0
    assert result.raw_json_path.is_file()


def test_run_postprocess_missing_research_report(tmp_path: Path) -> None:
    """Postprocess fails when cycle research JSON was never written."""
    vault = _make_vault(tmp_path)
    (vault / "_pipeline" / "vault-metrics.json").write_text("{}", encoding="utf-8")
    research_json = vault / "_pipeline/cycles/cycle-001-research.json"
    if research_json.is_file():
        research_json.unlink()

    def _fake_run(cmd, **kwargs):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    with _patch_cycle_runner_subprocess(_fake_run):
        result = run_postprocess(_ctx(vault), _research_result(vault))

    assert result.exit_code == 2
