"""Spec 069 FR1 — validator gate for declared-source backing (contracts C2/C1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.spec.schema import (
    BudgetConfig,
    CoverageCategory,
    CoverageTargets,
    DataSourceConfig,
    NoteTypeConfig,
    ScopeConfig,
    SpecConfig,
    SpecValidationError,
)
from research_framework.spec.validator import validate


def _spec_with_sources(*sources: DataSourceConfig) -> SpecConfig:
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


def test_unbacked_source_is_validation_error(tmp_path: Path) -> None:
    """C2-a / C1-c: a description-only source with no kind → hard error naming it."""
    spec = _spec_with_sources(DataSourceConfig(name="Web", type="external"))
    with pytest.raises(SpecValidationError) as exc:
        validate(spec, vault_dir=tmp_path)
    assert any("Web" in m and "no implementation" in m for m in exc.value.messages)


def test_strategy_hint_source_passes(tmp_path: Path) -> None:
    """C1-b: a description-only source annotated strategy_hint validates."""
    spec = _spec_with_sources(
        DataSourceConfig(name="Docs", type="external", kind="strategy_hint")
    )
    validate(spec, vault_dir=tmp_path)


def test_backed_source_passes(tmp_path: Path) -> None:
    """C1-a: a backed source (recognized access_method) passes the validator gate.

    (Pure repo-URL → module-trigger backing is covered at the source_is_backed
    level in test_trigger_matching; here we avoid tripping the unrelated
    code-first repo invariants.)"""
    spec = _spec_with_sources(
        DataSourceConfig(name="Feed", type="external", access_method="rss")
    )
    validate(spec, vault_dir=tmp_path)


def test_backing_skipped_without_vault_context() -> None:
    """Omitting vault_dir skips the backing check (back-compat for unit callers)."""
    spec = _spec_with_sources(DataSourceConfig(name="Web", type="external"))
    validate(spec)  # no raise
