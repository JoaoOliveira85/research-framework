"""Tests for ``research_framework.pipeline.timings``."""

from __future__ import annotations

import json
import time
from pathlib import Path

from research_framework.pipeline.timings import CycleTimings


def _new_timer(tmp_path: Path, cycle: int = 1) -> CycleTimings:
    pipeline_dir = tmp_path / "_pipeline"
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    return CycleTimings(cycle_num=cycle, pipeline_dir=pipeline_dir)


def test_flush_records_each_lap(tmp_path: Path) -> None:
    timer = _new_timer(tmp_path)
    timer.lap("Preflight")
    time.sleep(0.01)
    timer.lap("Step 1 - scout")
    time.sleep(0.01)
    timer.flush(exit_code=0)

    sidecar = json.loads(timer.sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["cycle"] == 1
    assert sidecar["exit_code"] == 0
    assert sidecar["schema_version"] == "1"
    assert sidecar["started_at"].endswith("Z")
    stages = sidecar["stages"]
    assert [s["stage"] for s in stages] == ["Preflight", "Step 1 - scout"]
    for stage in stages:
        assert stage["duration_s"] is not None
        assert stage["duration_s"] >= 0.0
    # Each per-stage ``duration_s`` and ``total_duration_s`` are independently
    # rounded to 3 decimal places, so the sum of the rounded stage durations
    # can exceed the rounded total by up to ``0.001 * len(stages)``. Compare
    # with that tolerance rather than a strict ``>=``.
    tolerance = 0.001 * len(stages)
    assert sidecar["total_duration_s"] + tolerance >= sum(
        s["duration_s"] for s in stages
    )


def test_flush_is_idempotent_and_rewrites_exit_code(tmp_path: Path) -> None:
    timer = _new_timer(tmp_path, cycle=4)
    timer.lap("Step 1")
    timer.flush(exit_code=2)
    first = json.loads(timer.sidecar_path.read_text(encoding="utf-8"))
    assert first["exit_code"] == 2

    # Second flush should overwrite — the success path in cycle_runner
    # relies on this to correct an abort-path placeholder.
    timer.flush(exit_code=0)
    second = json.loads(timer.sidecar_path.read_text(encoding="utf-8"))
    assert second["exit_code"] == 0
    assert second["stages"][0]["stage"] == "Step 1"


def test_lap_prints_default_banner(tmp_path: Path, capsys) -> None:
    timer = _new_timer(tmp_path)
    timer.lap("Step 0 - pre-cycle metrics")
    out = capsys.readouterr().out
    assert "[Step 0 - pre-cycle metrics]" in out


def test_lap_with_empty_header_suppresses_print(tmp_path: Path, capsys) -> None:
    timer = _new_timer(tmp_path)
    timer.lap("hidden", header="")
    out = capsys.readouterr().out
    assert "hidden" not in out


def test_flush_with_no_laps_still_writes_sidecar(tmp_path: Path) -> None:
    timer = _new_timer(tmp_path, cycle=9)
    timer.flush(exit_code=1)
    data = json.loads(timer.sidecar_path.read_text(encoding="utf-8"))
    assert data["stages"] == []
    assert data["exit_code"] == 1
    assert data["cycle"] == 9


def test_sidecar_path_uses_three_digit_cycle(tmp_path: Path) -> None:
    timer = _new_timer(tmp_path, cycle=7)
    assert timer.sidecar_path.name == "cycle-007-timings.json"
