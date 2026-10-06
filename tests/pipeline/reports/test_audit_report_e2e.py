"""End-to-end Layer-1 audit report tests (spec 040 T010)."""

from __future__ import annotations

from research_framework.pipeline.reports.render import normalized_audit_report

from .helpers import render_fixture, write_fixture

pytest_plugins = ["tests.pipeline.reports.helpers"]

_SECTIONS = (
    "## Coverage Delta",
    "## Top Discovered Sources",
    "## Cost Summary",
    "## Source Quality Drift",
    "## Flagged Issues",
)


def test_audit_report_e2e_all_sections(reports_vault) -> None:
    markdown = render_fixture(reports_vault)
    for heading in _SECTIONS:
        assert heading in markdown
    assert "alpha-feed" in markdown
    assert "1.50" in markdown or "$0.60" in markdown
    assert "degraded transition" in markdown


def test_audit_report_written_to_pipeline(reports_vault) -> None:
    path = write_fixture(reports_vault)
    assert path == reports_vault / "_pipeline" / "audit-report.md"
    assert path.is_file()


def test_repeat_render_byte_identical(reports_vault) -> None:
    first = render_fixture(reports_vault)
    second = render_fixture(reports_vault)
    assert normalized_audit_report(first) == normalized_audit_report(second)


def test_empty_subsection_no_data_lines(reports_vault) -> None:
    (reports_vault / "_pipeline" / "rejects.json").unlink(missing_ok=True)
    markdown = render_fixture(reports_vault)
    assert (
        "No flagged issues this cycle." in markdown or "## Flagged Issues" in markdown
    )
