"""Issue #268 — a metric with nothing to divide is unmeasured, not 0.0.

Seven of the ten gated metrics read ``0.0`` against ``0.0`` baselines. Some of
those zeros are real readings (no spec drift; no verifier rejection among notes
that were verified). Others were empty denominators dressed up as measurements:
no acronym ever occurred, no citation's credibility resolved, no note was
written, the verifier never ran. Those now report ``None`` with a reason, so
the regression summary names them instead of ticking them green.
"""

from __future__ import annotations

import io
from pathlib import Path

from research_framework.quality.baseline import diff_against_baseline
from research_framework.quality.metrics._helpers import UNMEASURED_KEY, record_ratio
from research_framework.quality.metrics.cycle_health import compute_cycle_health_metric
from research_framework.quality.metrics.note_quality import compute_note_quality_metric
from research_framework.quality.models import (
    BaselineJSON,
    CurrentJSON,
    CycleOutput,
    Fixture,
)
from research_framework.quality.report import print_regression_summary


def _fixture(tmp_path: Path) -> Fixture:
    return Fixture(
        name="x",
        vault_dir=tmp_path,
        spec_path=tmp_path / "research.spec.md",
        settings_path=tmp_path / "settings.yaml",
        coverage_targets_path=tmp_path / "coverage-targets.json",
        fake_agent_responses_dir=tmp_path / "fake_agent_responses",
        note_count_target=1,
        failure_mode="test",
    )


def test_record_ratio_marks_an_empty_denominator_unmeasured() -> None:
    block: dict = {}

    record_ratio(block, "ratio", 0, 0, reason="nothing_to_divide")

    assert block["ratio"] is None
    assert block[UNMEASURED_KEY] == {"ratio": "nothing_to_divide"}


def test_record_ratio_keeps_a_real_zero_a_zero() -> None:
    block: dict = {}

    record_ratio(block, "ratio", 0, 7, reason="nothing_to_divide")

    assert block["ratio"] == 0.0
    assert UNMEASURED_KEY not in block


def test_no_notes_written_is_not_zero_percent_template_compliance(
    tmp_path: Path,
) -> None:
    result = compute_note_quality_metric(_fixture(tmp_path), [])

    assert result["template_compliance_pct"] is None
    assert result["acronym_link_pct"] is None
    assert result[UNMEASURED_KEY]["template_compliance_pct"] == "no_notes_written"


def test_a_verifier_that_never_ran_is_not_a_zero_reject_rate(tmp_path: Path) -> None:
    """Every source-poor cycle aborts at SG-002, before the note-writer."""
    aborted = [
        CycleOutput(
            fixture_name="source-poor",
            cycle_number=n,
            exit_code=2,
            quality_report_path=tmp_path / f"cycle-{n:03d}-quality-report.json",
            research_report_path=tmp_path / f"cycle-{n:03d}-research.json",
        )
        for n in (1, 2, 3)
    ]

    result = compute_cycle_health_metric(_fixture(tmp_path), aborted)

    assert result["cycles_fail"] == 3, "the aborts themselves are a real count"
    assert result["verifier_reject_rate"] is None
    assert result[UNMEASURED_KEY]["verifier_reject_rate"] == "verifier_never_invoked"


def _report_for(metrics: dict) -> tuple:
    current = CurrentJSON(
        schema_version="1.0",
        fixture="x",
        run_timestamp="2026-01-01T00:00:00Z",
        coverage_targets_hash="sha256:deadbeef",
        metrics=metrics,
    )
    baseline = BaselineJSON(
        schema_version="1.0",
        fixture="x",
        baseline_commit="abc",
        last_updated="2026-01-01T00:00:00Z",
        last_updated_by="test",
        last_updated_reason="test",
        coverage_targets_hash="sha256:deadbeef",
        metrics={"note_quality": {"acronym_link_pct": 0.0}},
    )
    report = diff_against_baseline(current, baseline)
    return report, report.fixtures["x"]


def test_an_unmeasured_gated_metric_is_named_not_silently_dropped() -> None:
    report, fx = _report_for(
        {
            "note_quality": {
                "acronym_link_pct": None,
                UNMEASURED_KEY: {"acronym_link_pct": "no_acronym_occurrences_in_notes"},
            }
        }
    )

    assert "note_quality.acronym_link_pct" not in fx.metric_diffs, (
        "a non-measurement carries no verdict"
    )
    assert fx.unmeasured["note_quality.acronym_link_pct"] == (
        "no_acronym_occurrences_in_notes"
    )
    assert "1 unmeasured" in fx.summary

    stream = io.StringIO()
    print_regression_summary(report, stream, color=False)
    printed = stream.getvalue()
    assert "UNMEASURED: no_acronym_occurrences_in_notes" in printed


def test_a_fully_measured_run_reports_no_unmeasured_metrics() -> None:
    _report, fx = _report_for({"note_quality": {"acronym_link_pct": 0.0}})

    assert fx.unmeasured == {}
    assert fx.summary == "0 regressions, 0 warnings"
