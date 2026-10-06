"""Tests for ``scripts/quality_report.py`` (T041, feature 017).

Read-only inspection CLI: ``--cycle N`` prints one cycle summary; ``--all``
aggregates; process always exits 0.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture
def quality_report_script():
    """Load ``quality_report.py`` from ``scripts/`` (added in T047)."""
    script = Path(__file__).resolve().parents[2] / "scripts" / "quality_report.py"
    spec = importlib.util.spec_from_file_location("quality_report_script", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["quality_report_script"] = module
    spec.loader.exec_module(module)
    return module


def _minimal_report_vault(vault: Path, *, cycle: int) -> None:
    cyc = vault / "_pipeline" / "cycles"
    cyc.mkdir(parents=True, exist_ok=True)
    name = f"cycle-{cycle:03d}-quality-report.json"
    doc = {
        "schema_version": "1",
        "cycle_number": cycle,
        "framework_version": "0.2.18",
        "generated_at": "2026-05-15T12:00:00Z",
        "cycle_started_at": "2026-05-15T11:00:00Z",
        "cycle_finished_at": "2026-05-15T12:00:00Z",
        "gates": {},
        "coverage_snapshot": {},
        "notes_written": 0,
        "notes_accepted": 0,
        "notes_rejected": 0,
        "batches": [],
        "queryability_score": 0,
        "queryability_trajectory": "stable",
        "degraded_sources": [],
        "retry_count": 0,
        "aborted": False,
    }
    (cyc / name).write_text(json.dumps(doc), encoding="utf-8")


class TestQualityReportCliCycleMode:
    """``--cycle N`` emits human-readable text."""

    def test_cycle_mode_prints_summary(
        self,
        tmp_path: Path,
        quality_report_script: object,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _minimal_report_vault(tmp_path, cycle=2)
        rc = quality_report_script.main(["--vault", str(tmp_path), "--cycle", "2"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "2" in out or "cycle" in out.lower()


class TestQualityReportCliAllMode:
    """``--all`` aggregates across cycles on disk."""

    def test_all_mode_aggregates(
        self,
        tmp_path: Path,
        quality_report_script: object,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _minimal_report_vault(tmp_path, cycle=1)
        _minimal_report_vault(tmp_path, cycle=2)
        rc = quality_report_script.main(["--vault", str(tmp_path), "--all"])
        assert rc == 0
        out = capsys.readouterr().out
        assert out.strip()


class TestQualityReportCliExitSemantics:
    """Read-only tool exits zero even when data is thin."""

    def test_exit_zero_on_empty_aggregate(
        self,
        tmp_path: Path,
        quality_report_script: object,
    ) -> None:
        (tmp_path / "_pipeline" / "cycles").mkdir(parents=True, exist_ok=True)
        rc = quality_report_script.main(["--vault", str(tmp_path), "--all"])
        assert rc == 0
