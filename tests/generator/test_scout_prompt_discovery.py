"""Tier 3: the scout prompt's discovery section (spec 088 FR-001, FR-003, FR-011)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from research_framework.generator.templates import render_scout_prompt
from research_framework.spec.parser import parse
from research_framework.spec.schema import SpecConfig

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "specs"
    / "code-first-vault-spec.md"
)
GOLDEN = Path(__file__).parent / "golden"

AREAS = [
    "Streaming ingestion for risk data",
    "Idempotent consumers and replay",
    "Schema evolution in event contracts",
]


def _plain_spec() -> SpecConfig:
    return SpecConfig.from_dict(
        {
            "name": "plain",
            "owner": "tests",
            "naming_convention": "slug",
            "data_sources": [
                {"name": "Always Source", "type": "external", "required": True},
                {"name": "Extra", "type": "external", "required": False},
            ],
        }
    )


def _spec(kind: str) -> SpecConfig:
    return parse(FIXTURE) if kind == "code-first" else _plain_spec()


def _render(tmp_path: Path, kind: str, **extra: object) -> str:
    vault = tmp_path / kind
    (vault / "_pipeline" / "prompts").mkdir(parents=True)
    path = render_scout_prompt(
        _spec(kind),
        vault,
        target_topics=["Alpha.md"],
        existing_notes=["Kafka Streams.md"],
        rejected_topics=["Thermodynamics"],
        **extra,  # type: ignore[arg-type]
    )
    return path.read_text(encoding="utf-8")


def _without_version(prompt: str) -> str:
    return re.sub(
        r"^_template_version: \d+$", "_template_version: N", prompt, flags=re.M
    )


def _section(prompt: str) -> str:
    return prompt.split("## Discovery pass")[1].split("\n## ")[0]


@pytest.mark.parametrize("kind", ["code-first", "plain"])
def test_section_lists_the_assigned_areas_and_the_window(
    tmp_path: Path, kind: str
) -> None:
    prompt = _render(
        tmp_path, kind, discovery_areas=AREAS, discovery_window_start="2026-05-27"
    )
    section = _section(prompt)
    for area in AREAS:
        assert f"- {area}" in section
    assert "2026-05-27" in section
    for question in ("appeared or changed", "contested", "practitioners now solve"):
        assert question in section
    assert "NOT from this vault's existing note titles" in section
    assert "still reported" in section and "topics_found.updates" in section
    assert "publication date" in section
    assert "do not count toward" in section
    assert "topics_found.new" in section.split("do not count toward")[1]
    # the report shape is documented in the output schema, once per schema block
    assert prompt.count('"discovery_checked"') == 1
    assert prompt.count('"discovery": [') == 1
    assert '"why_new"' in prompt and '"published"' in prompt


@pytest.mark.parametrize("kind", ["code-first", "plain"])
@pytest.mark.parametrize("empty", [{}, {"discovery_areas": []}])
def test_no_areas_means_no_section(
    tmp_path: Path, kind: str, empty: dict[str, object]
) -> None:
    prompt = _render(tmp_path, kind, **empty)
    assert "Discovery pass" not in prompt
    assert "discovery" not in prompt.lower()
    # byte-identical to the template as it rendered before spec 088
    golden = (GOLDEN / f"scout-prompt-{kind}.before-088.md").read_text(encoding="utf-8")
    assert _without_version(prompt) == golden


def test_the_window_start_alone_does_not_open_the_section(tmp_path: Path) -> None:
    prompt = _render(tmp_path, "plain", discovery_window_start="2026-05-27")
    assert "Discovery pass" not in prompt


def test_refresh_mode_keeps_the_section_and_does_not_contradict_it(
    tmp_path: Path,
) -> None:
    spec = _plain_spec()
    spec.research_mode = "refresh"
    vault = tmp_path / "v"
    (vault / "_pipeline" / "prompts").mkdir(parents=True)
    prompt = render_scout_prompt(
        spec, vault, discovery_areas=AREAS, discovery_window_start="2026-05-27"
    ).read_text(encoding="utf-8")
    assert "NO new topics are wanted" in prompt
    section = _section(prompt)
    assert all(f"- {a}" in section for a in AREAS)
    assert "will not be dispatched in this mode" in section
    assert "welcome" in section
    expand = _render(tmp_path, "plain", discovery_areas=AREAS)
    assert "will not be dispatched" not in expand
