"""Tier-6 determinism integration test for all v1 metric families (T032, US2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.quality.determinism import (
    assert_deterministic,
    canonical_json_dumps,
)
from research_framework.quality.metrics import (
    REGISTERED_METRIC_FAMILIES,
    compute_all_metrics,
)
from research_framework.quality.models import CycleOutput, Fixture

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


@pytest.fixture
def tech_lite_stub(tmp_path: Path) -> tuple[Fixture, list[CycleOutput]]:
    """Minimal tech-lite-shaped vault + one synthetic cycle (no real run_cycle_steps)."""
    vault = tmp_path / "tech-lite"
    tmpl = vault / "_templates"
    tmpl.mkdir(parents=True)
    (tmpl / "concept.md").write_text(
        "---\ntype: concept\n---\n\n# T\n\n## Overview\n\n## Key Details\n\n## Relationships\n",
        encoding="utf-8",
    )
    (vault / "research.spec.md").write_text(
        "---\nname: tech-lite\ncoverage_targets:\n  categories:\n"
        "    - {name: services, note_type: service, target_count: 3}\n"
        "    - {name: concepts, note_type: concept, target_count: 2}\n---\n",
        encoding="utf-8",
    )
    (vault / "coverage-targets.json").write_text(
        json.dumps(
            {
                "categories": [
                    {
                        "name": "services",
                        "note_type": "service",
                        "required_count": 3,
                        "current": 3,
                    },
                    {
                        "name": "concepts",
                        "note_type": "concept",
                        "required_count": 2,
                        "current": 2,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    note = vault / "data_vault" / "note.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\ntitle: Note\ntype: concept\n---\n\n# N\n\n## Overview\n\na\n\n"
        "## Key Details\n\nb\n\n## Relationships\n\nc\n",
        encoding="utf-8",
    )
    cyc = vault / "_pipeline" / "cycles"
    cyc.mkdir(parents=True)
    report = cyc / "cycle-001-quality-report.json"
    report.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "retry_count": 0,
                "notes_written": 1,
                "notes_rejected": 0,
                "coverage_snapshot": {
                    "services": {
                        "target": 3,
                        "met": 3,
                        "fill_pct": 1.0,
                        "delta_this_cycle": 0,
                    },
                    "concepts": {
                        "target": 2,
                        "met": 2,
                        "fill_pct": 1.0,
                        "delta_this_cycle": 0,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (cyc / "cycle-001-verifier.json").write_text(
        json.dumps({"verdicts": [{"note_path": "note.md", "status": "verified"}]}),
        encoding="utf-8",
    )
    fixture = Fixture(
        name="tech-lite",
        vault_dir=vault,
        spec_path=vault / "research.spec.md",
        settings_path=vault / "settings.yaml",
        coverage_targets_path=vault / "coverage-targets.json",
        fake_agent_responses_dir=vault / "fake_agent_responses",
        note_count_target=18,
        failure_mode="code-derived-topic-discovery",
    )
    cycles = [
        CycleOutput(
            fixture_name="tech-lite",
            cycle_number=1,
            exit_code=0,
            quality_report_path=report,
            research_report_path=vault / "cycle-001-research.json",
            notes_written=[note],
            sg_trips=[],
        )
    ]
    return fixture, cycles


def test_all_metric_families_registered() -> None:
    names = {f.name for f in REGISTERED_METRIC_FAMILIES}
    assert names == {
        "coverage",
        "cycle_health",
        "note_quality",
        "cost_efficiency",
        # Added 0.10.0: source_health (spec 029) + source_quality (specs 030/055).
        "source_health",
        "source_quality",
    }


def test_current_metrics_byte_identical_across_two_compute_passes(
    tech_lite_stub: tuple[Fixture, list[CycleOutput]],
) -> None:
    """US2 scenario 1 — merged metrics dict is byte-identical except run_timestamp."""
    fixture, cycles = tech_lite_stub
    first = compute_all_metrics(fixture, cycles)
    second = compute_all_metrics(fixture, cycles)
    assert canonical_json_dumps(first) == canonical_json_dumps(second)
    assert_deterministic(first, "tech-lite-all-metrics")
