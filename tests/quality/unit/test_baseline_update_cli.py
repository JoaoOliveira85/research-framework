"""Tier-1 unit tests for quality-baseline-update CLI (T058–T061 / US4)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from research_framework.quality.baseline_update import update_baseline
from research_framework.quality.determinism import canonical_json_write
from research_framework.quality.models import CurrentJSON
from research_framework.quality.runner import run
from tests.quality.test_quality_harness_regression_gate import (
    _COVERAGE_HASH,
    _FIXED_TS,
    _patch_harness,
    _write_baseline,
)


def _current_json(coverage_pct: float = 0.92) -> CurrentJSON:
    return CurrentJSON(
        schema_version="1.0",
        fixture="tech-lite",
        run_timestamp=_FIXED_TS,
        coverage_targets_hash=_COVERAGE_HASH,
        metrics={
            "coverage": {
                "coverage_pct": coverage_pct,
                "notes_per_category": {"services": 4},
                "spec_drift": 0.12,
            },
            "cycle_health": {
                "cycles_pass": 1,
                "cycles_fail": 0,
                "sg002_trip_count": 0,
                "retry_once_rate": 0.0,
            },
            "note_quality": {
                "template_compliance_pct": 0.95,
                "per_template_section_fill": {"summary": 1.0},
                "acronym_link_pct": 0.88,
            },
        },
    )


def test_no_auto_update_on_improvement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """US4 scenario 1: improvement vs baseline does not auto-overwrite committed gold."""
    baselines_dir, output_dir, fake_cycle = _patch_harness(
        monkeypatch,
        tmp_path,
        coverage_pct=0.92,
    )
    baseline_path = baselines_dir / "tech-lite.baseline.json"
    before = baseline_path.read_bytes()

    code = run(
        fixtures=["tech-lite"],
        output_dir=output_dir,
        color=False,
        cycle_runner=fake_cycle,
    )
    assert code == 0
    assert baseline_path.read_bytes() == before

    report = json.loads(
        (output_dir / "regression-report.json").read_text(encoding="utf-8")
    )
    entry = report["fixtures"]["tech-lite"]["metric_diffs"]["coverage.coverage_pct"]
    assert entry["current"] > entry["baseline"]
    assert report["verdict"] == "pass"
    _ = capsys.readouterr()


def test_confirmed_update_rewrites_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """US4 scenario 2: stdin y overwrites baseline with audit metadata."""
    baselines_dir = tmp_path / "baselines"
    baselines_dir.mkdir(parents=True)
    _write_baseline(baselines_dir, "tech-lite", coverage_pct=0.83)
    baseline_path = baselines_dir / "tech-lite.baseline.json"

    monkeypatch.setattr(
        "research_framework.quality.baseline_update._BASELINES_DIR",
        baselines_dir,
    )
    monkeypatch.setattr(
        "research_framework.quality.baseline_update.collect_fixture_current",
        lambda _name, **_: (_current_json(0.92), False),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    monkeypatch.setattr(
        "research_framework.quality.baseline_update._stdin_is_tty", lambda: True
    )

    code = update_baseline(
        "tech-lite",
        reason="Bless improved coverage after pipeline fix",
        actor="Test User",
        dry_run=False,
        yes=False,
    )
    assert code == 0
    doc = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert doc["last_updated_by"] == "Test User"
    assert doc["last_updated_reason"] == "Bless improved coverage after pipeline fix"
    assert "last_updated" in doc
    assert doc["metrics"]["coverage"]["coverage_pct"] == 0.92
    assert "Wrote baseline" in capsys.readouterr().out


def test_declined_update_preserves_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """US4 scenario 3: stdin n leaves baseline unchanged."""
    baselines_dir = tmp_path / "baselines"
    baselines_dir.mkdir(parents=True)
    _write_baseline(baselines_dir, "tech-lite", coverage_pct=0.83)
    baseline_path = baselines_dir / "tech-lite.baseline.json"
    before = baseline_path.read_bytes()

    monkeypatch.setattr(
        "research_framework.quality.baseline_update._BASELINES_DIR",
        baselines_dir,
    )
    monkeypatch.setattr(
        "research_framework.quality.baseline_update.collect_fixture_current",
        lambda _name, **_: (_current_json(0.92), False),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    monkeypatch.setattr(
        "research_framework.quality.baseline_update._stdin_is_tty", lambda: True
    )

    code = update_baseline(
        "tech-lite",
        reason="Should not apply",
        actor="Test User",
        dry_run=False,
        yes=False,
    )
    assert code == 1
    assert baseline_path.read_bytes() == before
    err = capsys.readouterr().err
    assert "baseline not updated" in err


def test_dry_run_never_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """US4 scenario 4 / Constitution #2: --dry-run shows diff, writes nothing."""
    baselines_dir = tmp_path / "baselines"
    baselines_dir.mkdir(parents=True)
    _write_baseline(baselines_dir, "tech-lite", coverage_pct=0.83)
    baseline_path = baselines_dir / "tech-lite.baseline.json"
    before = baseline_path.read_bytes()
    touched: list[Path] = []

    monkeypatch.setattr(
        "research_framework.quality.baseline_update._BASELINES_DIR",
        baselines_dir,
    )
    monkeypatch.setattr(
        "research_framework.quality.baseline_update.collect_fixture_current",
        lambda _name, **_: (_current_json(0.92), False),
    )

    real_write = canonical_json_write

    def _spy_write(path: Path, payload: dict[str, Any]) -> None:
        if "baselines" in path.parts and path.suffix == ".json":
            touched.append(path)
        real_write(path, payload)

    monkeypatch.setattr(
        "research_framework.quality.baseline_update.canonical_json_write",
        _spy_write,
    )

    code = update_baseline(
        "tech-lite",
        reason="",
        actor="Test User",
        dry_run=True,
        yes=False,
    )
    assert code == 0
    assert baseline_path.read_bytes() == before
    assert not touched


def test_crashed_run_is_never_blessed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``collect_fixture_current`` reports a crashed cycle, and
    ``update_baseline`` discarded that flag: a crashed run's metrics could be
    confirmed (or ``--yes``-ed in CI) into the committed baseline."""
    baselines_dir = tmp_path / "baselines"
    baselines_dir.mkdir(parents=True)
    _write_baseline(baselines_dir, "tech-lite", coverage_pct=0.83)
    baseline_path = baselines_dir / "tech-lite.baseline.json"
    before = baseline_path.read_bytes()
    monkeypatch.setattr(
        "research_framework.quality.baseline_update._BASELINES_DIR",
        baselines_dir,
    )
    monkeypatch.setattr(
        "research_framework.quality.baseline_update.collect_fixture_current",
        lambda _name, **_: (_current_json(0.10), True),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    monkeypatch.setattr(
        "research_framework.quality.baseline_update._stdin_is_tty", lambda: True
    )

    code = update_baseline(
        "tech-lite", reason="r", actor="Test User", dry_run=False, yes=False
    )

    assert code == 2
    assert baseline_path.read_bytes() == before
    assert "crash" in capsys.readouterr().err
