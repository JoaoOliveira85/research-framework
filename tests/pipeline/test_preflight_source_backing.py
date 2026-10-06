"""Spec 069 FR2 — preflight fails closed on an unbacked source (contract C3-a)."""

from __future__ import annotations

from pathlib import Path

from research_framework.pipeline.preflight import check_all
from research_framework.spec.schema import (
    BudgetConfig,
    CoverageCategory,
    CoverageTargets,
    DataSourceConfig,
    NoteTypeConfig,
    ScopeConfig,
    SpecConfig,
)


def _spec(*sources: DataSourceConfig) -> SpecConfig:
    return SpecConfig(
        name="Sample",
        location=Path("/tmp/sample"),
        owner="Owner",
        scope=ScopeConfig(domain="d", organization="o"),
        note_types=[
            NoteTypeConfig(name="concept", description="d", folder="01 - Concepts")
        ],
        data_sources=list(sources),
        search_dimensions=["domain", "market"],
        coverage_targets=CoverageTargets(
            categories=[CoverageCategory(name="c", note_type="concept", target_count=5)]
        ),
        budget=BudgetConfig(),
    )


def test_unbacked_source_fails_preflight_closed(tmp_path: Path) -> None:
    """C3-a: a required, unbacked source makes preflight fail closed."""
    spec = _spec(DataSourceConfig(name="Web", type="external", required=True))
    result = check_all(spec, tmp_path)
    assert result.overall_status == "fail"
    web = next(s for s in result.sources if s.name == "Web")
    assert web.status == "unreachable"
    assert "no implementation" in web.detail


def test_strategy_hint_source_passes_preflight(tmp_path: Path) -> None:
    """C3-a: a strategy_hint source is ok at preflight (no module/connectivity)."""
    spec = _spec(DataSourceConfig(name="Docs", type="external", kind="strategy_hint"))
    result = check_all(spec, tmp_path)
    docs = next(s for s in result.sources if s.name == "Docs")
    assert docs.status == "ok"
    assert result.overall_status == "pass"
