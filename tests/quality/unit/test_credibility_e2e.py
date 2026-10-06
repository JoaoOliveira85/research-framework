"""End-to-end credibility scenarios (spec 055 US3/US4)."""

from __future__ import annotations

from pathlib import Path

import yaml

from research_framework.quality.metrics.source_quality import compute_tier2_source_ratio
from research_framework.quality.models import CycleOutput, Fixture
from research_framework.spec.parser import parse
from research_framework.vault.credibility import (
    Level,
    build_credibility_context,
    effective_level,
)

_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[2] / "fixtures" / "quality" / "credibility"
)


def _load_snippet_spec(tmp_path: Path):
    snippet = yaml.safe_load((_FIXTURE_ROOT / "spec-snippet.yaml").read_text())
    spec_text = (
        "---\n"
        + yaml.safe_dump(
            {
                "name": "cred-e2e",
                "owner": "test",
                "location": str(tmp_path),
                "scope": {"domain": "d", "organization": "o"},
                **snippet,
                "search_dimensions": ["domain"],
                "coverage_targets": {
                    "categories": [
                        {"name": "c", "note_type": "concept", "target_count": 1}
                    ]
                },
                "budget": {"max_usd": 1.0, "max_cycles": 1},
            },
            sort_keys=False,
        )
        + "---\n"
    )
    spec_path = tmp_path / "research.spec.md"
    spec_path.write_text(spec_text, encoding="utf-8")
    return parse(spec_path)


def _note_from_fixture(name: str, tmp_path: Path) -> Path:
    fm = yaml.safe_load((_FIXTURE_ROOT / "notes" / name).read_text())
    rel = f"data_vault/{name.replace('.yaml', '.md')}"
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n\nBody.\n",
        encoding="utf-8",
    )
    return path


def _fixture(tmp_path: Path) -> Fixture:
    return Fixture(
        name="cred-e2e",
        vault_dir=tmp_path,
        spec_path=tmp_path / "research.spec.md",
        settings_path=tmp_path / "settings.yaml",
        coverage_targets_path=tmp_path / "coverage-targets.json",
        fake_agent_responses_dir=tmp_path / "fake_agent_responses",
        note_count_target=1,
        failure_mode="none",
    )


def test_coi_caps_through_resolver_and_metric(tmp_path: Path) -> None:
    spec = _load_snippet_spec(tmp_path)
    ctx = build_credibility_context(spec, tmp_path)
    ctx.role_index.exact["https://arxiv.org/abs/2303.08774"] = "domain"
    note_path = _note_from_fixture("openai-coi.yaml", tmp_path)
    fm = yaml.safe_load(note_path.read_text().split("---")[1])
    citation = fm["source_urls"][0]
    assert effective_level(citation, fm, ctx) is Level.COMMENTARY
    cycle = CycleOutput(
        fixture_name="cred-e2e",
        cycle_number=1,
        exit_code=0,
        quality_report_path=tmp_path / "q.json",
        research_report_path=tmp_path / "r.json",
        notes_written=[note_path],
    )
    ratio = compute_tier2_source_ratio(_fixture(tmp_path), [cycle], ctx)
    assert ratio == 1.0


def test_off_field_downgrade_and_combined_coi(tmp_path: Path) -> None:
    spec = _load_snippet_spec(tmp_path)
    ctx = build_credibility_context(spec, tmp_path)
    ctx.role_index.exact["https://arxiv.org/abs/2303.08774"] = "domain"

    off_path = _note_from_fixture("off-field-leader.yaml", tmp_path)
    off_fm = yaml.safe_load(off_path.read_text().split("---")[1])
    off_citation = off_fm["source_urls"][0]
    assert effective_level(off_citation, off_fm, ctx) is Level.COMMENTARY

    combined = {
        "url": "https://arxiv.org/abs/2303.08774",
        "credibility": "primary",
        "coi": True,
    }
    service_note = {"type": "service"}
    assert effective_level(combined, service_note, ctx) is Level.UNVETTED
