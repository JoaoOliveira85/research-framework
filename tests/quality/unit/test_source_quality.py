"""Unit tests for source_quality metrics (spec 030 / 055)."""

from __future__ import annotations

from pathlib import Path

import yaml

from research_framework.quality.metrics.source_quality import (
    _unique_note_paths,
    compute_tier2_source_ratio,
)
from research_framework.quality.models import CycleOutput, Fixture
from research_framework.spec.schema import (
    BudgetConfig,
    CoverageCategory,
    CoverageTargets,
    DataSourceConfig,
    NoteTypeConfig,
    ScopeConfig,
    SpecConfig,
)
from research_framework.vault.credibility import build_credibility_context


def _write_note(vault: Path, rel: str, fm: dict) -> Path:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    body = fm.pop("_body", "Body.\n")
    path.write_text(
        "---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n\n" + body,
        encoding="utf-8",
    )
    return path


def _fixture(vault: Path, spec: SpecConfig) -> Fixture:
    spec_path = vault / "research.spec.md"
    spec_path.write_text("---\nname: f\n---\n", encoding="utf-8")
    return Fixture(
        name="cred-unit",
        vault_dir=vault,
        spec_path=spec_path,
        settings_path=vault / "settings.yaml",
        coverage_targets_path=vault / "coverage-targets.json",
        fake_agent_responses_dir=vault / "fake_agent_responses",
        note_count_target=1,
        failure_mode="none",
    )


def _ctx(vault: Path, spec: SpecConfig):
    return build_credibility_context(spec, vault)


def test_tier2_source_ratio_deterministic(tmp_path: Path) -> None:
    spec = SpecConfig(
        name="f",
        location=tmp_path,
        owner="o",
        scope=ScopeConfig(domain="d", organization="o"),
        note_types=[
            NoteTypeConfig(
                name="concept",
                description="d",
                folder="f",
                authoritative_role="domain",
            )
        ],
        data_sources=[
            DataSourceConfig(name="HN", type="external", role="domain", priority=2)
        ],
        search_dimensions=["d"],
        coverage_targets=CoverageTargets(
            categories=[CoverageCategory(name="c", note_type="concept", target_count=1)]
        ),
        budget=BudgetConfig(),
    )
    ctx = _ctx(tmp_path, spec)
    ctx.role_index.exact["https://a.example/1"] = "domain"
    ctx.role_index.exact["https://a.example/2"] = "domain"

    note1 = _write_note(
        tmp_path,
        "data_vault/n1.md",
        {
            "type": "concept",
            "source_urls": [
                {"url": "https://a.example/1", "credibility": "primary"},
                {"url": "https://a.example/2", "credibility": "commentary"},
            ],
        },
    )
    note2 = _write_note(
        tmp_path,
        "data_vault/n2.md",
        {
            "type": "concept",
            "source_urls": [
                {"url": "https://a.example/1", "credibility": "corroborated"},
            ],
        },
    )
    cycle = CycleOutput(
        fixture_name="cred-unit",
        cycle_number=1,
        exit_code=0,
        quality_report_path=tmp_path / "q.json",
        research_report_path=tmp_path / "r.json",
        notes_written=[note1, note2],
    )
    ratio = compute_tier2_source_ratio(_fixture(tmp_path, spec), [cycle], ctx)
    assert ratio == 0.3333
    assert compute_tier2_source_ratio(_fixture(tmp_path, spec), [], ctx) == 0.0


def test_tier2_ratio_moves_on_level_flip(tmp_path: Path) -> None:
    spec = SpecConfig(
        name="f",
        location=tmp_path,
        owner="o",
        scope=ScopeConfig(domain="d", organization="o"),
        note_types=[
            NoteTypeConfig(
                name="concept",
                description="d",
                folder="f",
                authoritative_role="domain",
            )
        ],
        data_sources=[
            DataSourceConfig(name="HN", type="external", role="domain", priority=2)
        ],
        search_dimensions=["d"],
        coverage_targets=CoverageTargets(
            categories=[CoverageCategory(name="c", note_type="concept", target_count=1)]
        ),
        budget=BudgetConfig(),
    )
    ctx = _ctx(tmp_path, spec)
    ctx.role_index.exact["https://a.example/1"] = "domain"

    note = _write_note(
        tmp_path,
        "data_vault/n1.md",
        {
            "type": "concept",
            "source_urls": [
                {"url": "https://a.example/1", "credibility": "primary"},
                {"url": "https://a.example/1", "credibility": "commentary"},
            ],
        },
    )
    cycle = CycleOutput(
        fixture_name="cred-unit",
        cycle_number=1,
        exit_code=0,
        quality_report_path=tmp_path / "q.json",
        research_report_path=tmp_path / "r.json",
        notes_written=[note],
    )
    fixture = _fixture(tmp_path, spec)
    low = compute_tier2_source_ratio(fixture, [cycle], ctx)
    note.write_text(
        note.read_text().replace("credibility: primary", "credibility: commentary"),
        encoding="utf-8",
    )
    high = compute_tier2_source_ratio(fixture, [cycle], ctx)
    assert high > low


def test_metrics_skip_phantom_notes_written_paths(tmp_path: Path) -> None:
    """notes_written may list a deduped path the writer never materialised.

    The note-writer records a deduped target (e.g. ``<slug>-2.md``) when a new
    note collapses onto an existing one; that path can be absent on disk. The
    source-citation metrics must skip it rather than crash with
    FileNotFoundError (regression for the spec-055 quality-gate crash).
    """
    spec = SpecConfig(
        name="f",
        location=tmp_path,
        owner="o",
        scope=ScopeConfig(domain="d", organization="o"),
        note_types=[
            NoteTypeConfig(
                name="concept",
                description="d",
                folder="f",
                authoritative_role="domain",
            )
        ],
        data_sources=[
            DataSourceConfig(name="HN", type="external", role="domain", priority=2)
        ],
        search_dimensions=["d"],
        coverage_targets=CoverageTargets(
            categories=[CoverageCategory(name="c", note_type="concept", target_count=1)]
        ),
        budget=BudgetConfig(),
    )
    ctx = _ctx(tmp_path, spec)
    ctx.role_index.exact["https://a.example/1"] = "domain"

    real_note = _write_note(
        tmp_path,
        "data_vault/n1.md",
        {
            "type": "concept",
            "source_urls": [
                {"url": "https://a.example/1", "credibility": "commentary"},
            ],
        },
    )
    phantom = tmp_path / "data_vault" / "n1-2.md"
    assert not phantom.exists()
    cycle = CycleOutput(
        fixture_name="cred-unit",
        cycle_number=1,
        exit_code=0,
        quality_report_path=tmp_path / "q.json",
        research_report_path=tmp_path / "r.json",
        notes_written=[real_note, phantom],
    )
    fixture = _fixture(tmp_path, spec)

    # The phantom path is filtered out; only the materialised note is read.
    assert _unique_note_paths([cycle]) == [real_note]
    # The gated metric resolves over the real note instead of crashing on the
    # missing file (commentary on-field → Tier-2; 1/1).
    assert compute_tier2_source_ratio(fixture, [cycle], ctx) == 1.0
