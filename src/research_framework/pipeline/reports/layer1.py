"""Layer-1 audit report composition (spec 040 FR-001..008)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from research_framework.pipeline.atomic_write import write_text
from research_framework.pipeline.digest.scope import (
    DateRange,
    DigestScope,
    build_scope,
    earliest_cycle_date,
    enumerate_cycles,
)
from research_framework.pipeline.digest.sections import (
    _load_coverage_targets,
    build_cost_summary,
    build_coverage_delta,
    build_source_drift,
)
from research_framework.pipeline.settings import VaultSettings, load_vault_settings

from .flagged_issues import build_flagged_issues
from .render import render_audit_report
from .top_sources import build_top_discovered_sources


def resolve_report_date_range(
    vault_dir: Path,
    *,
    up_to_cycle: int | None = None,
) -> DateRange:
    """All completed cycles through ``up_to_cycle`` (or all cycles when unset)."""
    from datetime import timedelta

    today = date.today()
    start_day = earliest_cycle_date(vault_dir) or today
    probe_end = today + timedelta(days=365)
    wide = DateRange(start=start_day, end=probe_end)
    cycles = enumerate_cycles(vault_dir, wide)
    if up_to_cycle is not None:
        cycles = [c for c in cycles if c.number <= up_to_cycle]
    if not cycles:
        return DateRange(start=start_day, end=today)
    days = [c.finished_at.astimezone(UTC).date() for c in cycles]
    return DateRange(start=min(days), end=max(days))


def _budget_cap(settings: VaultSettings | None) -> float | None:
    if settings is None:
        return None
    if settings.limits.cycle_budget_usd is not None:
        return float(settings.limits.cycle_budget_usd)
    return float(settings.budget_usd)


def _section_context(
    vault_dir: Path,
    scope: DigestScope,
    *,
    settings: VaultSettings | None = None,
) -> tuple[dict, list[str]]:
    footer: list[str] = list(scope.warnings)
    categories, target_warn = _load_coverage_targets(vault_dir)
    footer.extend(target_warn)
    coverage_delta = build_coverage_delta(categories, scope.cycles)
    cost_summary, cost_warn = build_cost_summary(vault_dir, scope.cycles)
    footer.extend(cost_warn)
    source_drift, drift_warn, omit_drift = build_source_drift(
        vault_dir, scope.cycles, scope.date_range
    )
    footer.extend(drift_warn)
    top_sources = build_top_discovered_sources(
        vault_dir, scope.cycles, scope.date_range
    )
    flagged = build_flagged_issues(vault_dir, scope.cycles, date_range=scope.date_range)
    ctx = {
        "vault_identity": scope.vault_identity,
        "start": scope.date_range.start.isoformat(),
        "end": scope.date_range.end.isoformat(),
        "git_base": scope.git_base,
        "git_head": scope.git_head,
        "coverage_delta": coverage_delta,
        "top_sources": top_sources,
        "cost_summary": cost_summary,
        "source_drift": source_drift,
        "omit_source_drift_section": omit_drift,
        "flagged_issues": flagged,
        "footer_warnings": footer,
        "budget_usd": _budget_cap(settings),
    }
    return ctx, footer


def compose_report(
    vault_dir: Path,
    *,
    date_range: DateRange | None = None,
    up_to_cycle: int | None = None,
    rendered_at: datetime | None = None,
    settings: VaultSettings | None = None,
) -> str:
    """Render ``audit-report.md`` markdown using spec 035 section builders."""
    dr = date_range or resolve_report_date_range(vault_dir, up_to_cycle=up_to_cycle)
    scope = build_scope(vault_dir, dr)
    if up_to_cycle is not None:
        scope.cycles = [c for c in scope.cycles if c.number <= up_to_cycle]
    if settings is None:
        try:
            settings = load_vault_settings(vault_dir)
        except Exception:
            settings = None
    ctx, _footer = _section_context(vault_dir, scope, settings=settings)
    return render_audit_report(rendered_at=rendered_at, **ctx)


def compose_cycle_block(
    vault_dir: Path,
    cycle_num: int,
    *,
    rendered_at: datetime | None = None,
    settings: VaultSettings | None = None,
) -> str:
    """Deterministic Layer-1 block scoped to a single cycle (FR-007)."""
    wide = resolve_report_date_range(vault_dir, up_to_cycle=cycle_num)
    scope = build_scope(vault_dir, wide)
    scoped = [c for c in scope.cycles if c.number == cycle_num]
    if not scoped:
        return "## Layer 1 metrics\n\nNo data in scope.\n"
    single = DigestScope(
        vault_dir=scope.vault_dir,
        date_range=DateRange(
            start=scoped[0].finished_at.astimezone(UTC).date(),
            end=scoped[0].finished_at.astimezone(UTC).date(),
        ),
        cycles=scoped,
        git_base=scope.git_base,
        git_head=scope.git_head,
        vault_identity=scope.vault_identity,
        warnings=list(scope.warnings),
    )
    if settings is None:
        try:
            settings = load_vault_settings(vault_dir)
        except Exception:
            settings = None
    ctx, _footer = _section_context(vault_dir, single, settings=settings)
    header = f"## Layer 1 metrics — cycle {cycle_num:03d}\n\n"
    body = render_audit_report(rendered_at=rendered_at, **ctx)
    return header + body


def write_audit_report(
    vault_dir: Path,
    markdown: str,
    *,
    path: Path | None = None,
) -> Path:
    dest = path or (vault_dir / "_pipeline" / "audit-report.md")
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_text(dest, markdown)
    return dest


__all__ = [
    "compose_cycle_block",
    "compose_report",
    "resolve_report_date_range",
    "write_audit_report",
]
