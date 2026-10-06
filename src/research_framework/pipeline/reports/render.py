"""Jinja2 render pass for audit reports (spec 040)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from research_framework.pipeline.digest.ranker import (
    format_progress_delta,
    format_progress_pct,
)
from research_framework.pipeline.digest.render import strip_rendered_at_line

_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_audit_report(
    *,
    vault_identity: str,
    start: str,
    end: str,
    git_base: str,
    git_head: str,
    coverage_delta: list[tuple[str, float, float, float]],
    top_sources: list[dict[str, Any]],
    cost_summary: dict[str, Any],
    source_drift: list[dict[str, Any]],
    omit_source_drift_section: bool,
    flagged_issues: list[dict[str, Any]],
    footer_warnings: list[str],
    budget_usd: float | None,
    rendered_at: datetime | None = None,
) -> str:
    stamp = rendered_at or datetime.now(UTC)
    total = float(cost_summary.get("total_usd") or 0.0)
    utilization_pct = (
        (total / budget_usd) * 100.0 if budget_usd and budget_usd > 0 else 0.0
    )
    return (
        _env()
        .get_template("audit-report.md.j2")
        .render(
            vault_identity=vault_identity,
            start=start,
            end=end,
            rendered_at=stamp.astimezone(UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            git_base=git_base,
            git_head=git_head,
            coverage_delta=coverage_delta,
            top_sources=top_sources,
            cost_summary=cost_summary,
            source_drift=source_drift,
            omit_source_drift_section=omit_source_drift_section,
            flagged_issues=flagged_issues,
            footer_warnings=footer_warnings,
            budget_usd=budget_usd,
            utilization_pct=utilization_pct,
            format_progress_pct=format_progress_pct,
            format_progress_delta=format_progress_delta,
        )
    )


def normalized_audit_report(markdown: str) -> str:
    return strip_rendered_at_line(markdown)


__all__ = ["normalized_audit_report", "render_audit_report"]
