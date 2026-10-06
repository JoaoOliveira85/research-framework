"""Tier-6 acceptance tests for spec 022 US1 — baseline regression gate (T016–T019)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from research_framework.quality.determinism import canonical_json_write
from research_framework.quality.models import CycleOutput, Fixture, MetricFamily
from research_framework.quality.runner import run

pytestmark = [pytest.mark.e2e, pytest.mark.slow, pytest.mark.acceptance]

_FIXED_TS = "2026-05-21T12:00:00Z"
_COVERAGE_HASH = "sha256:deadbeef"


def _minimal_fixture(tmp_path: Path, name: str = "tech-lite") -> Fixture:
    vault = tmp_path / name
    vault.mkdir(parents=True)
    for rel in (
        "research.spec.md",
        "settings.yaml",
        "coverage-targets.json",
    ):
        (vault / rel).write_text("{}\n", encoding="utf-8")
    (vault / "fake_agent_responses").mkdir()
    return Fixture(
        name=name,
        vault_dir=vault,
        spec_path=vault / "research.spec.md",
        settings_path=vault / "settings.yaml",
        coverage_targets_path=vault / "coverage-targets.json",
        fake_agent_responses_dir=vault / "fake_agent_responses",
        note_count_target=18,
        failure_mode="code-derived-topic-discovery",
    )


def _baseline_metrics(coverage_pct: float = 0.83) -> dict[str, dict[str, Any]]:
    return {
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
    }


def _write_baseline(
    baselines_dir: Path,
    fixture: str,
    *,
    coverage_pct: float = 0.83,
    coverage_hash: str = _COVERAGE_HASH,
) -> Path:
    path = baselines_dir / f"{fixture}.baseline.json"
    payload = {
        "schema_version": "1.0",
        "fixture": fixture,
        "baseline_commit": "abc123",
        "last_updated": _FIXED_TS,
        "last_updated_by": "test",
        "last_updated_reason": "test baseline",
        "coverage_targets_hash": coverage_hash,
        "metrics": _baseline_metrics(coverage_pct),
    }
    canonical_json_write(path, payload)
    return path


def _stub_metric_families(
    coverage_pct: float = 0.83,
) -> list[MetricFamily]:
    def coverage_compute(
        _fixture: Fixture, _cycles: list[CycleOutput]
    ) -> dict[str, Any]:
        return {
            "coverage_pct": coverage_pct,
            "notes_per_category": {"services": 4},
            "spec_drift": 0.12,
        }

    def cycle_health_compute(
        _fixture: Fixture, _cycles: list[CycleOutput]
    ) -> dict[str, Any]:
        return {
            "cycles_pass": 1,
            "cycles_fail": 0,
            "sg002_trip_count": 0,
            "retry_once_rate": 0.0,
        }

    def note_quality_compute(
        _fixture: Fixture, _cycles: list[CycleOutput]
    ) -> dict[str, Any]:
        return {
            "template_compliance_pct": 0.95,
            "per_template_section_fill": {"summary": 1.0},
            "acronym_link_pct": 0.88,
        }

    return [
        MetricFamily(
            name="coverage",
            compute_fn=coverage_compute,
            metrics=["coverage_pct", "notes_per_category", "spec_drift"],
            baseline_subset={
                "coverage_pct": "higher_is_better",
                "spec_drift": "lower_is_better",
            },
        ),
        MetricFamily(
            name="cycle_health",
            compute_fn=cycle_health_compute,
            metrics=[
                "cycles_pass",
                "cycles_fail",
                "sg002_trip_count",
                "retry_once_rate",
            ],
            baseline_subset={
                "cycles_pass": "higher_is_better",
                "cycles_fail": "lower_is_better",
                "sg002_trip_count": "lower_is_better",
            },
        ),
        MetricFamily(
            name="note_quality",
            compute_fn=note_quality_compute,
            metrics=[
                "template_compliance_pct",
                "per_template_section_fill",
                "acronym_link_pct",
            ],
            baseline_subset={
                "template_compliance_pct": "higher_is_better",
                "acronym_link_pct": "higher_is_better",
            },
        ),
    ]


def _patch_harness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    coverage_pct: float = 0.83,
    coverage_hash: str = _COVERAGE_HASH,
    fixture_name: str = "tech-lite",
) -> tuple[Path, Path]:
    """Wire tmp baselines, single fixture, stub metrics and cycle runner."""
    baselines_dir = tmp_path / "baselines"
    output_dir = tmp_path / "_pipeline" / "quality"
    baselines_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    # Committed baseline gold standard (scenario regressions vary *current* via stub).
    _write_baseline(
        baselines_dir,
        fixture_name,
        coverage_pct=0.83,
        coverage_hash=coverage_hash,
    )

    fixture = _minimal_fixture(tmp_path, fixture_name)

    monkeypatch.setattr(
        "research_framework.quality.runner._BASELINES_DIR",
        baselines_dir,
    )
    monkeypatch.setattr(
        "research_framework.quality.runner._utc_now_iso",
        lambda: _FIXED_TS,
    )
    monkeypatch.setattr(
        "research_framework.quality.runner.resolve_fixture",
        lambda _name: fixture,
    )
    monkeypatch.setattr(
        "research_framework.quality.runner.REGISTERED_FIXTURES",
        {fixture_name: "code-derived-topic-discovery"},
    )
    families = _stub_metric_families(coverage_pct=coverage_pct)
    monkeypatch.setattr(
        "research_framework.quality.runner.REGISTERED_METRIC_FAMILIES",
        families,
    )
    monkeypatch.setattr(
        "research_framework.quality.metrics.REGISTERED_METRIC_FAMILIES",
        families,
    )

    def fake_cycle(
        vault_dir: Path,
        cycle_num: int,
        budget_cap: float = 10.0,
        max_cycles: int = 5,
        scripts_dir: Path | None = None,
    ) -> int:
        _ = vault_dir, cycle_num, budget_cap, max_cycles, scripts_dir
        return 0

    monkeypatch.setattr(
        "research_framework.quality.runner.coverage_targets_hash",
        lambda _path: coverage_hash,
    )
    return baselines_dir, output_dir, fake_cycle


@pytest.mark.parametrize("fixture_name", ["tech-lite"])
def test_no_change_run_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fixture_name: str
) -> None:
    """T016 / US1 scenario 1: identical metrics → exit 0, zero regressions/warnings."""
    _baselines, output_dir, fake_cycle = _patch_harness(
        monkeypatch, tmp_path, fixture_name=fixture_name
    )
    code = run(
        fixtures=[fixture_name],
        output_dir=output_dir,
        color=False,
        cycle_runner=fake_cycle,
    )
    assert code == 0
    report_path = output_dir / "regression-report.json"
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["verdict"] == "pass"
    fx = report["fixtures"][fixture_name]
    assert fx["verdict"] == "pass"
    assert fx["summary"] == "0 regressions, 0 warnings"


def test_20pct_drop_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """T017 / US1 scenario 2: 20% coverage drop → exit 1, metric named in report."""
    _baselines, output_dir, fake_cycle = _patch_harness(
        monkeypatch,
        tmp_path,
        coverage_pct=0.664,
    )
    code = run(
        fixtures=["tech-lite"],
        output_dir=output_dir,
        color=False,
        cycle_runner=fake_cycle,
    )
    assert code == 1
    report = json.loads(
        (output_dir / "regression-report.json").read_text(encoding="utf-8")
    )
    assert report["verdict"] == "fail"
    diffs = report["fixtures"]["tech-lite"]["metric_diffs"]
    assert "coverage.coverage_pct" in diffs
    entry = diffs["coverage.coverage_pct"]
    assert entry["verdict"] == "fail"
    assert entry["baseline"] == 0.83
    assert entry["current"] == pytest.approx(0.664, rel=1e-3)


def test_10pct_drop_warns(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """T018 / US1 scenario 3: 10% drop → exit 0, warn in report and stdout."""
    _baselines, output_dir, fake_cycle = _patch_harness(
        monkeypatch,
        tmp_path,
        coverage_pct=0.747,
    )
    import io
    import sys

    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    code = run(
        fixtures=["tech-lite"],
        output_dir=output_dir,
        color=False,
        cycle_runner=fake_cycle,
    )
    assert code == 0
    report = json.loads(
        (output_dir / "regression-report.json").read_text(encoding="utf-8")
    )
    assert report["verdict"] == "warn"
    entry = report["fixtures"]["tech-lite"]["metric_diffs"]["coverage.coverage_pct"]
    assert entry["verdict"] == "warn"
    out = buf.getvalue()
    assert "WARN" in out or "warn" in out.lower()


def test_explicit_baseline_update_applies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """T019 / US1 scenario 4: blessed baseline rewrite → next run uses new gold."""
    baselines_dir, output_dir, fake_cycle = _patch_harness(
        monkeypatch,
        tmp_path,
        coverage_pct=0.664,
    )
    code_fail = run(
        fixtures=["tech-lite"],
        output_dir=output_dir,
        color=False,
        cycle_runner=fake_cycle,
    )
    assert code_fail == 1

    _write_baseline(baselines_dir, "tech-lite", coverage_pct=0.664)
    families = _stub_metric_families(coverage_pct=0.664)
    monkeypatch.setattr(
        "research_framework.quality.runner.REGISTERED_METRIC_FAMILIES",
        families,
    )
    monkeypatch.setattr(
        "research_framework.quality.metrics.REGISTERED_METRIC_FAMILIES",
        families,
    )
    code_ok = run(
        fixtures=["tech-lite"],
        output_dir=output_dir,
        color=False,
        cycle_runner=fake_cycle,
    )
    assert code_ok == 0
    report = json.loads(
        (output_dir / "regression-report.json").read_text(encoding="utf-8")
    )
    assert report["verdict"] == "pass"
    assert report["fixtures"]["tech-lite"]["summary"] == "0 regressions, 0 warnings"
