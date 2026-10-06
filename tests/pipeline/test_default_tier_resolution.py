"""FR-014a manifest default_tier resolution."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from research_framework.pipeline.settings import (
    SettingsError,
    load_vault_settings,
    resolve_stage_model,
)


def _vault_settings(tmp_path: Path, yaml_body: str):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        textwrap.dedent(yaml_body).strip() + "\n", encoding="utf-8"
    )
    return load_vault_settings(vault)


def test_manifest_default_tier_used_when_executor_omits_tier_and_model(
    tmp_path: Path,
) -> None:
    settings = _vault_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.0
        tiers:
          basic: claude-haiku-4-5
        stages:
          source_extraction:
            enabled: true
        """,
    )
    model = resolve_stage_model(
        settings, "source_extraction", manifest_default_tier="basic"
    )
    assert model == "claude-haiku-4-5"


def test_executor_explicit_tier_overrides_manifest_default(tmp_path: Path) -> None:
    settings = _vault_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.0
        tiers:
          basic: claude-haiku-4-5
          normal: claude-sonnet-5
        stages:
          source_extraction:
            enabled: true
            tier: normal
        """,
    )
    model = resolve_stage_model(
        settings, "source_extraction", manifest_default_tier="basic"
    )
    assert model == "claude-sonnet-5"


def test_executor_tier_and_model_conflict_raises(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        textwrap.dedent(
            """
            pipeline:
              max_cycles: 3
              budget_usd: 1.0
            tiers:
              basic: claude-haiku-4-5
            stages:
              source_extraction:
                enabled: true
                tier: basic
                model: claude-opus-5
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(SettingsError, match="cannot set both model and tier"):
        load_vault_settings(vault)
