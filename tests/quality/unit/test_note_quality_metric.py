"""Tier-1 unit tests for note_quality metric family (T031, spec 022 US2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline.steps._types import ResearchResult
from research_framework.quality.determinism import canonical_json_dumps
from research_framework.quality.metrics.note_quality import compute_note_quality_metric
from research_framework.quality.models import CycleOutput, Fixture


def _fixture_with_templates(tmp_path: Path) -> Fixture:
    vault = tmp_path / "vault"
    tmpl = vault / "_templates"
    tmpl.mkdir(parents=True)
    (tmpl / "concept.md").write_text(
        "---\ntype: concept\n---\n\n# T\n\n## Overview\n\n## Key Details\n\n## Relationships\n",
        encoding="utf-8",
    )
    (vault / "coverage-targets.json").write_text(
        json.dumps({"categories": []}),
        encoding="utf-8",
    )
    data = vault / "data_vault" / "01 - Concepts"
    data.mkdir(parents=True)
    (data / "Good Note.md").write_text(
        "---\ntitle: Good Note\ntype: concept\n---\n\n# Good\n\n## Overview\n\nx\n\n"
        "## Key Details\n\ny\n\n## Relationships\n\nz\n",
        encoding="utf-8",
    )
    (data / "Missing Section.md").write_text(
        "---\ntitle: Missing Section\ntype: concept\n---\n\n# Bad\n\n## Overview\n\nx\n\n"
        "## Key Details\n\ny\n",
        encoding="utf-8",
    )
    (data / "Unlinked Acronym (UA).md").write_text(
        "---\ntitle: Unlinked Acronym (UA)\ntype: concept\n---\n\n# UA\n\n## Overview\n\n"
        "UA appears bare here.\n\n## Key Details\n\ny\n\n## Relationships\n\nz\n",
        encoding="utf-8",
    )
    (data / "Linked Acronym (LA).md").write_text(
        "---\ntitle: Linked Acronym (LA)\ntype: concept\n---\n\n# LA\n\n## Overview\n\n"
        "First [[LA]] use.\n\n## Key Details\n\ny\n\n## Relationships\n\nz\n",
        encoding="utf-8",
    )
    return Fixture(
        name="tech-lite",
        vault_dir=vault,
        spec_path=vault / "research.spec.md",
        settings_path=vault / "settings.yaml",
        coverage_targets_path=vault / "coverage-targets.json",
        fake_agent_responses_dir=vault / "fake_agent_responses",
        note_count_target=18,
        failure_mode="code-derived-topic-discovery",
    )


def test_note_quality_byte_identical_across_two_calls(tmp_path: Path) -> None:
    fixture = _fixture_with_templates(tmp_path)
    note_paths = sorted((fixture.vault_dir / "data_vault").rglob("*.md"))
    report = (
        tmp_path / "vault" / "_pipeline" / "cycles" / "cycle-001-quality-report.json"
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("{}", encoding="utf-8")
    cycles = [
        CycleOutput(
            fixture_name="tech-lite",
            cycle_number=1,
            exit_code=0,
            quality_report_path=report,
            research_report_path=tmp_path / "r.json",
            notes_written=note_paths,
        )
    ]
    first = canonical_json_dumps(compute_note_quality_metric(fixture, cycles))
    second = canonical_json_dumps(compute_note_quality_metric(fixture, cycles))
    assert first == second


def test_note_quality_per_template_section_fill_binary(tmp_path: Path) -> None:
    """US2 scenario 4 — sections are filled or MISSING; fill rates are deterministic."""
    fixture = _fixture_with_templates(tmp_path)
    note_paths = sorted((fixture.vault_dir / "data_vault").rglob("*.md"))
    report = (
        tmp_path / "vault" / "_pipeline" / "cycles" / "cycle-001-quality-report.json"
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("{}", encoding="utf-8")
    cycles = [
        CycleOutput(
            fixture_name="tech-lite",
            cycle_number=1,
            exit_code=0,
            quality_report_path=report,
            research_report_path=tmp_path / "r.json",
            notes_written=note_paths,
        )
    ]
    result = compute_note_quality_metric(fixture, cycles)
    assert set(result.keys()) == {
        "template_compliance_pct",
        "per_template_section_fill",
        "acronym_link_pct",
    }
    fill = result["per_template_section_fill"]
    assert fill["Overview"] == 1.0
    assert fill["Key Details"] == 1.0
    assert fill["Relationships"] == 0.75
    assert result["template_compliance_pct"] == 0.75
    assert result["acronym_link_pct"] == 0.0


@pytest.mark.parametrize("use_typed_seam", [True, False])
def test_note_quality_typed_seam_matches_legacy_notes_written(
    tmp_path: Path, use_typed_seam: bool
) -> None:
    fixture = _fixture_with_templates(tmp_path)
    note_paths = sorted((fixture.vault_dir / "data_vault").rglob("*.md"))
    report = (
        tmp_path / "vault" / "_pipeline" / "cycles" / "cycle-001-quality-report.json"
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("{}", encoding="utf-8")
    research_result = (
        ResearchResult(
            notes_written=note_paths,
            notes_rejected=[],
            duration_ms=1,
            cost_usd=0.0,
            raw_json_path=report,
        )
        if use_typed_seam
        else None
    )
    cycles = [
        CycleOutput(
            fixture_name="tech-lite",
            cycle_number=1,
            exit_code=0,
            quality_report_path=report,
            research_report_path=tmp_path / "r.json",
            notes_written=[] if use_typed_seam else note_paths,
            research_result=research_result,
        )
    ]
    typed = compute_note_quality_metric(fixture, cycles)
    assert typed["template_compliance_pct"] == 0.75
