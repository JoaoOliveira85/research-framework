"""Tests for O'Reilly sources.yaml.template FR-015 opt-in tiers."""

from __future__ import annotations

from pathlib import Path

import yaml

TEMPLATE = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "research_framework"
    / "modules"
    / "oreilly"
    / "sources.yaml.template"
)


def test_oreilly_template_requires_explicit_tier_for_broad_queries() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "tiers:" in text
    data = yaml.safe_load(text)
    assert isinstance(data, dict)
    assert "tiers" not in data
    assert "oreilly_queries" in data
