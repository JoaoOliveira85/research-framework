"""Bundled settings template contract tests."""

from __future__ import annotations

from research_framework._assets import default_settings_path


def test_dist_templates_include_tiers_block() -> None:
    body = default_settings_path().read_text(encoding="utf-8")
    assert "tiers:" in body
    assert "basic:" in body
    assert "normal:" in body
    assert "flagship:" in body


def test_dist_templates_default_source_extraction_disabled() -> None:
    body = default_settings_path().read_text(encoding="utf-8")
    assert "source_extraction:" in body
    assert "enabled: false" in body
    assert "modules:" in body
