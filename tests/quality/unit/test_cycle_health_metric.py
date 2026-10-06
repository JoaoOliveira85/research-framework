"""Tier-1 unit tests for cycle_health metric family (T030, spec 022 US2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline.steps._types import (
    ResearchResult,
    SafetyGateTrip,
    ScoutResult,
    VerifierRejection,
)
from research_framework.quality.determinism import canonical_json_dumps
from research_framework.quality.metrics.cycle_health import compute_cycle_health_metric
from research_framework.quality.models import CycleOutput, Fixture


def _minimal_fixture(tmp_path: Path) -> Fixture:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "coverage-targets.json").write_text(
        json.dumps({"categories": []}),
        encoding="utf-8",
    )
    return Fixture(
        name="source-poor",
        vault_dir=vault,
        spec_path=vault / "research.spec.md",
        settings_path=vault / "settings.yaml",
        coverage_targets_path=vault / "coverage-targets.json",
        fake_agent_responses_dir=vault / "fake_agent_responses",
        note_count_target=17,
        failure_mode="gap-pursuit-substitution",
    )


def _write_quality_report(
    path: Path,
    *,
    retry_count: int = 0,
    notes_written: int = 0,
    notes_rejected: int = 0,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "cycle_number": int(path.name.split("-")[1]),
                "retry_count": retry_count,
                "notes_written": notes_written,
                "notes_rejected": notes_rejected,
            }
        ),
        encoding="utf-8",
    )


def _write_verifier_manifest(path: Path, verdicts: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"cycle": 1, "verdicts": verdicts}),
        encoding="utf-8",
    )


def test_cycle_health_byte_identical_across_two_calls(tmp_path: Path) -> None:
    fixture = _minimal_fixture(tmp_path)
    report = (
        tmp_path / "vault" / "_pipeline" / "cycles" / "cycle-001-quality-report.json"
    )
    _write_quality_report(report, retry_count=1, notes_written=10, notes_rejected=2)
    verifier = tmp_path / "vault" / "_pipeline" / "cycles" / "cycle-001-verifier.json"
    _write_verifier_manifest(
        verifier,
        [
            {"note_path": "a.md", "status": "verified"},
            {"note_path": "b.md", "status": "rejected"},
        ],
    )
    cycles = [
        CycleOutput(
            fixture_name="source-poor",
            cycle_number=1,
            exit_code=0,
            quality_report_path=report,
            research_report_path=tmp_path / "r.json",
            sg_trips=["SG-002"],
        )
    ]
    first = canonical_json_dumps(compute_cycle_health_metric(fixture, cycles))
    second = canonical_json_dumps(compute_cycle_health_metric(fixture, cycles))
    assert first == second


def test_cycle_health_sg002_and_retry_once_rate(tmp_path: Path) -> None:
    """US2 scenario 3 — SG-002 trips and retry-once rate from synthetic CycleOutput."""
    fixture = _minimal_fixture(tmp_path)
    cyc_dir = tmp_path / "vault" / "_pipeline" / "cycles"
    r1 = cyc_dir / "cycle-001-quality-report.json"
    r2 = cyc_dir / "cycle-002-quality-report.json"
    r3 = cyc_dir / "cycle-003-quality-report.json"
    _write_quality_report(r1, retry_count=0)
    _write_quality_report(r2, retry_count=1)
    _write_quality_report(r3, retry_count=0)
    cycles = [
        CycleOutput(
            fixture_name="source-poor",
            cycle_number=1,
            exit_code=0,
            quality_report_path=r1,
            research_report_path=tmp_path / "r1.json",
            sg_trips=["SG-002"],
        ),
        CycleOutput(
            fixture_name="source-poor",
            cycle_number=2,
            exit_code=1,
            quality_report_path=r2,
            research_report_path=tmp_path / "r2.json",
            sg_trips=["SG-002", "SG-003"],
        ),
        CycleOutput(
            fixture_name="source-poor",
            cycle_number=3,
            exit_code=0,
            quality_report_path=r3,
            research_report_path=tmp_path / "r3.json",
            sg_trips=[],
        ),
    ]
    result = compute_cycle_health_metric(fixture, cycles)
    assert result["cycles_pass"] == 2
    assert result["cycles_fail"] == 1
    assert result["sg002_trip_count"] == 2
    assert result["retry_once_rate"] == 0.3333


def test_verifier_reject_rate_from_verifier_manifest(tmp_path: Path) -> None:
    """US3 scenario 3 depends on verifier_reject_rate in cycle_health output."""
    fixture = _minimal_fixture(tmp_path)
    cycles_dir = tmp_path / "vault" / "_pipeline" / "cycles"
    reports = []
    for i in range(1, 4):
        report = cycles_dir / f"cycle-{i:03d}-quality-report.json"
        _write_quality_report(report, notes_written=4, notes_rejected=0)
        verifier = cycles_dir / f"cycle-{i:03d}-verifier.json"
        _write_verifier_manifest(
            verifier,
            [
                {"note_path": "n1.md", "status": "verified"},
                {"note_path": "n2.md", "status": "verified"},
                {"note_path": "n3.md", "status": "verified"},
                {"note_path": "n4.md", "status": "verified"},
                {"note_path": "n5.md", "status": "rejected"},
            ],
        )
        reports.append(
            CycleOutput(
                fixture_name="source-rich",
                cycle_number=i,
                exit_code=0,
                quality_report_path=report,
                research_report_path=tmp_path / f"r{i}.json",
            )
        )
    result = compute_cycle_health_metric(fixture, reports)
    assert "verifier_reject_rate" in result
    assert result["verifier_reject_rate"] == 0.2


@pytest.mark.parametrize("use_typed_seam", [True, False])
def test_cycle_health_sg002_typed_seam_matches_legacy_strings(
    tmp_path: Path, use_typed_seam: bool
) -> None:
    fixture = _minimal_fixture(tmp_path)
    report = (
        tmp_path / "vault" / "_pipeline" / "cycles" / "cycle-001-quality-report.json"
    )
    _write_quality_report(report, retry_count=0)
    scout_result = (
        ScoutResult(
            topics_found=[],
            sg_trips=[
                SafetyGateTrip(gate_id="SG-002", status="FAIL", message="diversity"),
                SafetyGateTrip(gate_id="SG-003", status="WARN", message="other"),
            ],
            duration_ms=1,
            cost_usd=0.0,
            raw_json_path=report,
        )
        if use_typed_seam
        else None
    )
    cycles = [
        CycleOutput(
            fixture_name="source-poor",
            cycle_number=1,
            exit_code=0,
            quality_report_path=report,
            research_report_path=tmp_path / "r.json",
            sg_trips=[] if use_typed_seam else ["SG-002"],
            scout_result=scout_result,
        )
    ]
    result = compute_cycle_health_metric(fixture, cycles)
    assert result["sg002_trip_count"] == 1


def test_cycle_health_verifier_reject_rate_from_typed_research_result(
    tmp_path: Path,
) -> None:
    fixture = _minimal_fixture(tmp_path)
    report = (
        tmp_path / "vault" / "_pipeline" / "cycles" / "cycle-001-quality-report.json"
    )
    _write_quality_report(report)
    note = tmp_path / "vault" / "data_vault" / "n1.md"
    note.parent.mkdir(parents=True)
    note.write_text("---\ntitle: N\ntype: concept\n---\n", encoding="utf-8")
    rejected = tmp_path / "vault" / "data_vault" / "n2.md"
    rejected.write_text("---\ntitle: R\ntype: concept\n---\n", encoding="utf-8")
    cycles = [
        CycleOutput(
            fixture_name="source-rich",
            cycle_number=1,
            exit_code=0,
            quality_report_path=report,
            research_report_path=tmp_path / "r.json",
            research_result=ResearchResult(
                notes_written=[note],
                notes_rejected=[VerifierRejection(note_path=rejected, reason="bad")],
                duration_ms=1,
                cost_usd=0.0,
                raw_json_path=report,
            ),
        )
    ]
    result = compute_cycle_health_metric(fixture, cycles)
    assert result["verifier_reject_rate"] == 0.5
