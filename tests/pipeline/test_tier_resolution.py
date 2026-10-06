"""D7 tier resolution tests."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from research_framework.pipeline.settings import SettingsError, load_vault_settings


def _write(vault_dir: Path, body: str) -> None:
    vault_dir.mkdir(parents=True, exist_ok=True)
    (vault_dir / "settings.yaml").write_text(
        textwrap.dedent(body).strip() + "\n", encoding="utf-8"
    )


def test_schema_gen_executor_resolves_tier_to_model(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.0
        tiers:
          basic: claude-haiku-4-5
          normal: claude-sonnet-5
          flagship: claude-opus-5
        stages:
          schema_gen:
            tier: basic
        """,
    )
    settings = load_vault_settings(tmp_path)
    assert settings.resolve_model("schema_gen") == "claude-haiku-4-5"


def test_source_extraction_executor_resolves_tier(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.0
        tiers:
          basic: gpt-mini
          normal: gpt-normal
          flagship: gpt-flagship
        stages:
          source_extraction:
            tier: normal
            enabled: true
        """,
    )
    settings = load_vault_settings(tmp_path)
    assert settings.resolve_model("source_extraction") == "gpt-normal"


def test_tier_and_model_mutually_exclusive_raises(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.0
        tiers:
          basic: haiku
          normal: sonnet
          flagship: opus
        stages:
          schema_gen:
            tier: basic
            model: sonnet
        """,
    )
    with pytest.raises(SettingsError):
        load_vault_settings(tmp_path)


def test_unknown_tier_name_raises_at_load(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.0
        tiers:
          basic: haiku
          normal: sonnet
          flagship: opus
        stages:
          schema_gen:
            tier: nonexistent
        """,
    )
    with pytest.raises(SettingsError) as exc:
        load_vault_settings(tmp_path)
    assert "Unknown tier" in str(exc.value)


def test_tier_resolution_per_research_section_three(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.0
        tiers:
          basic: model-a
          normal: model-b
          flagship: model-c
        stages:
          schema_gen:
            tier: flagship
          scout:
            model: legacy-sonnet
        """,
    )
    settings = load_vault_settings(tmp_path)
    assert settings.resolve_model("schema_gen") == "model-c"
    assert settings.stage("scout").extras.get("model") == "legacy-sonnet"
