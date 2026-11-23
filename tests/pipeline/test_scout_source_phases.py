"""Tier 3: a source whose ``phases`` excludes the cycle's mode is left out of the
scout prompt (spec 087 FR-017)."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.generator.templates import render_scout_prompt
from research_framework.spec.schema import SpecConfig


def _spec(mode: str) -> SpecConfig:
    return SpecConfig.from_dict(
        {
            "name": "phases",
            "owner": "tests",
            "research_mode": mode,
            "naming_convention": "slug",
            "data_sources": [
                {"name": "Always Source", "type": "external", "required": True},
                {
                    "name": "Bootstrap Only Source",
                    "type": "external",
                    "required": True,
                    "phases": ["bootstrap"],
                },
                {
                    "name": "Refresh Only Optional",
                    "type": "external",
                    "required": False,
                    "phases": ["refresh"],
                },
            ],
        }
    )


def _prompt(tmp_path: Path, mode: str) -> str:
    vault = tmp_path / mode
    (vault / "_pipeline" / "prompts").mkdir(parents=True)
    return render_scout_prompt(_spec(mode), vault).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("mode", "present", "absent"),
    [
        ("bootstrap", ["Always Source", "Bootstrap Only Source"], ["Refresh Only"]),
        ("refresh", ["Always Source", "Refresh Only Optional"], ["Bootstrap Only"]),
        ("expand", ["Always Source"], ["Bootstrap Only", "Refresh Only"]),
    ],
)
def test_a_source_outside_the_cycles_mode_is_not_in_the_prompt(
    tmp_path: Path, mode: str, present: list[str], absent: list[str]
) -> None:
    prompt = _prompt(tmp_path, mode)
    for name in present:
        assert name in prompt, (mode, name)
    for name in absent:
        assert name not in prompt, (mode, name)
    # the report schema's source keys follow the same filter
    assert ("bootstrap_only_source" in prompt) is (mode == "bootstrap")
