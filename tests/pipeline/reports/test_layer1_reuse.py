"""Layer-1 reuse tests — spec 035 builders must be invoked (spec 040 T006)."""

from __future__ import annotations

from unittest.mock import patch

from research_framework.pipeline.digest import sections  # sequencing gate

from .helpers import render_fixture

pytest_plugins = ["tests.pipeline.reports.helpers"]


def test_digest_sections_importable() -> None:
    assert sections.build_coverage_delta is not None
    assert sections.build_cost_summary is not None
    assert sections.build_source_drift is not None


def test_compose_report_calls_035_builders(reports_vault) -> None:
    with (
        patch(
            "research_framework.pipeline.reports.layer1.build_coverage_delta",
            wraps=sections.build_coverage_delta,
        ) as cov,
        patch(
            "research_framework.pipeline.reports.layer1.build_cost_summary",
            wraps=sections.build_cost_summary,
        ) as cost,
        patch(
            "research_framework.pipeline.reports.layer1.build_source_drift",
            wraps=sections.build_source_drift,
        ) as drift,
    ):
        markdown = render_fixture(reports_vault)
    cov.assert_called_once()
    cost.assert_called_once()
    drift.assert_called_once()
    assert "## Coverage Delta" in markdown
    assert "concepts" in markdown
    assert "## Cost Summary" in markdown
    assert "$0.60" in markdown or "0.60" in markdown
    assert "## Source Quality Drift" in markdown
    assert "youtube-rss" in markdown


def test_no_agent_dispatch(reports_vault, monkeypatch) -> None:
    import subprocess

    calls: list[str] = []
    real_run = subprocess.run

    def _spy(cmd, *args, **kwargs):
        cmd_text = " ".join(str(c) for c in cmd) if isinstance(cmd, list) else str(cmd)
        if "agent_call" in cmd_text or " claude" in cmd_text or " codex" in cmd_text:
            calls.append(cmd_text)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _spy)
    render_fixture(reports_vault)
    assert calls == []
