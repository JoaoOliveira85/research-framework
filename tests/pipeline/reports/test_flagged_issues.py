"""Flagged Issues section tests (spec 040 T008)."""

from __future__ import annotations

from research_framework.pipeline.digest.scope import enumerate_cycles
from research_framework.pipeline.reports.flagged_issues import build_flagged_issues

from .helpers import FIXTURE_RANGE, render_fixture

pytest_plugins = ["tests.pipeline.reports.helpers"]


def test_flagged_issues_sorted(reports_vault) -> None:
    cycles = enumerate_cycles(reports_vault, FIXTURE_RANGE)
    rows = build_flagged_issues(reports_vault, cycles, date_range=FIXTURE_RANGE)
    assert rows
    severities = [row["severity"] for row in rows]
    assert severities.index("high") < severities.index("medium")


def test_flagged_issues_render_in_report(reports_vault) -> None:
    markdown = render_fixture(reports_vault)
    assert "## Flagged Issues" in markdown
    assert "reddit" in markdown
    assert "Bad Note.md" in markdown
    assert "facts-schema" in markdown.lower() or "schema_gen" in markdown


def test_flagged_issues_empty_message(tmp_path) -> None:
    vault = tmp_path / "clean"
    vault.mkdir()
    (vault / "_pipeline").mkdir()
    from research_framework.pipeline.reports.layer1 import compose_report

    markdown = compose_report(vault)
    assert "No flagged issues this cycle." in markdown
