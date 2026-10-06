"""Tier-1 unit tests for coverage metric family (T029, spec 022 US2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline.steps._types import ResearchResult
from research_framework.quality.determinism import canonical_json_dumps
from research_framework.quality.metrics.coverage import compute_coverage_metric
from research_framework.quality.models import CycleOutput, Fixture


def _fixture(tmp_path: Path) -> Fixture:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "research.spec.md").write_text(
        "---\n"
        "name: test-vault\n"
        "coverage_targets:\n"
        "  categories:\n"
        "    - name: services\n"
        "      note_type: service\n"
        "      target_count: 3\n"
        "    - name: concepts\n"
        "      note_type: concept\n"
        "      target_count: 2\n"
        "    - name: flows\n"
        "      note_type: flow\n"
        "      target_count: 3\n"
        "---\n",
        encoding="utf-8",
    )
    targets = {
        "categories": [
            {
                "name": "services",
                "note_type": "service",
                "required_count": 3,
                "current": 4,
            },
            {
                "name": "concepts",
                "note_type": "concept",
                "required_count": 2,
                "current": 2,
            },
            {"name": "flows", "note_type": "flow", "required_count": 3, "current": 3},
            {
                "name": "decisions",
                "note_type": "decision",
                "required_count": 1,
                "current": 0,
            },
            {
                "name": "integrations",
                "note_type": "service",
                "required_count": 2,
                "current": 2,
            },
            {
                "name": "orphan-bucket",
                "note_type": "concept",
                "required_count": 1,
                "current": 1,
            },
        ]
    }
    (vault / "coverage-targets.json").write_text(json.dumps(targets), encoding="utf-8")
    return Fixture(
        name="tech-lite",
        vault_dir=vault,
        spec_path=vault / "research.spec.md",
        settings_path=vault / "settings.yaml",
        coverage_targets_path=vault / "coverage-targets.json",
        fake_agent_responses_dir=vault / "fake_agent_responses",
        note_count_target=18,
        failure_mode="code-derived-topic-discovery",
    )


def _quality_report(path: Path, *, snapshot: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "cycle_number": 1,
                "coverage_snapshot": snapshot,
            }
        ),
        encoding="utf-8",
    )


def test_coverage_metric_byte_identical_across_two_calls(tmp_path: Path) -> None:
    """US2 scenario 1 — same inputs produce byte-identical canonical JSON."""
    fixture = _fixture(tmp_path)
    report = (
        tmp_path / "vault" / "_pipeline" / "cycles" / "cycle-001-quality-report.json"
    )
    _quality_report(
        report,
        snapshot={
            "services": {"target": 3, "met": 4, "fill_pct": 1.0, "delta_this_cycle": 1},
            "concepts": {"target": 2, "met": 2, "fill_pct": 1.0, "delta_this_cycle": 0},
        },
    )
    cycles = [
        CycleOutput(
            fixture_name="tech-lite",
            cycle_number=1,
            exit_code=0,
            quality_report_path=report,
            research_report_path=tmp_path / "missing-research.json",
        )
    ]
    first = canonical_json_dumps(compute_coverage_metric(fixture, cycles))
    second = canonical_json_dumps(compute_coverage_metric(fixture, cycles))
    assert first == second


def test_coverage_metric_scenario_two_fields(tmp_path: Path) -> None:
    """US2 scenario 2 — coverage_pct, notes_per_category, spec_drift are reproducible."""
    fixture = _fixture(tmp_path)
    report = (
        tmp_path / "vault" / "_pipeline" / "cycles" / "cycle-001-quality-report.json"
    )
    _quality_report(
        report,
        snapshot={
            "services": {"target": 3, "met": 4, "fill_pct": 1.0, "delta_this_cycle": 0},
            "concepts": {"target": 2, "met": 2, "fill_pct": 1.0, "delta_this_cycle": 0},
            "flows": {"target": 3, "met": 1, "fill_pct": 0.3333, "delta_this_cycle": 0},
            "decisions": {
                "target": 1,
                "met": 0,
                "fill_pct": 0.0,
                "delta_this_cycle": 0,
            },
            "integrations": {
                "target": 2,
                "met": 2,
                "fill_pct": 1.0,
                "delta_this_cycle": 0,
            },
            "orphan-bucket": {
                "target": 1,
                "met": 1,
                "fill_pct": 1.0,
                "delta_this_cycle": 0,
            },
        },
    )
    cycles = [
        CycleOutput(
            fixture_name="tech-lite",
            cycle_number=1,
            exit_code=0,
            quality_report_path=report,
            research_report_path=tmp_path / "missing-research.json",
        )
    ]
    result = compute_coverage_metric(fixture, cycles)
    assert result["coverage_pct"] == 0.8333
    assert result["notes_per_category"] == {
        "services": 4,
        "concepts": 2,
        "flows": 1,
        "decisions": 0,
        "integrations": 2,
        "orphan-bucket": 1,
    }
    assert result["spec_drift"] == 0.5


@pytest.mark.parametrize("use_typed_seam", [True, False])
def test_coverage_metric_typed_seam_matches_legacy_snapshot(
    tmp_path: Path, use_typed_seam: bool
) -> None:
    """Typed ``ResearchResult.notes_written`` agrees with quality-report snapshot."""
    fixture = _fixture(tmp_path)
    data = fixture.vault_dir / "data_vault" / "01 - Services"
    data.mkdir(parents=True)
    note_a = data / "svc-a.md"
    note_b = data / "svc-b.md"
    for p in (note_a, note_b):
        p.write_text("---\ntitle: S\ntype: service\n---\n\n# S\n", encoding="utf-8")
    report = (
        tmp_path / "vault" / "_pipeline" / "cycles" / "cycle-001-quality-report.json"
    )
    _quality_report(
        report,
        snapshot={
            "services": {
                "target": 3,
                "met": 2,
                "fill_pct": 0.6667,
                "delta_this_cycle": 2,
            },
            "concepts": {"target": 2, "met": 2, "fill_pct": 1.0, "delta_this_cycle": 0},
        },
    )
    research_result = (
        ResearchResult(
            notes_written=[note_a.resolve(), note_b.resolve()],
            notes_rejected=[],
            duration_ms=1,
            cost_usd=0.0,
            raw_json_path=report,
        )
        if use_typed_seam
        else None
    )
    cycles = [
        CycleOutput(
            fixture_name="tech-lite",
            cycle_number=1,
            exit_code=0,
            quality_report_path=report,
            research_report_path=tmp_path / "missing-research.json",
            research_result=research_result,
        )
    ]
    result = compute_coverage_metric(fixture, cycles)
    assert result["notes_per_category"]["services"] == 2
