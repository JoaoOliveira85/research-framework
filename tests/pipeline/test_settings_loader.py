"""Tier-1 tests for ``pipeline.settings`` (spec 025 US9 B7, contract § 7)."""

from __future__ import annotations

import dataclasses
import textwrap
from pathlib import Path

import pytest

from research_framework.pipeline.settings import (
    SettingsError,
    StageSettings,
    load_vault_settings,
)


def _write_settings(vault_dir: Path, body: str) -> None:
    vault_dir.mkdir(parents=True, exist_ok=True)
    (vault_dir / "settings.yaml").write_text(
        textwrap.dedent(body).strip() + "\n",
        encoding="utf-8",
    )


def test_load_well_formed(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 10
          budget_usd: 5.0
          backlog_promotion_threshold: 3
        stages:
          scout:
            tier: basic
          verifier:
            tier: expert
            enabled: false
        dimensions:
          - technical
        default_agent: codex
        """,
    )
    settings = load_vault_settings(tmp_path)
    assert settings.max_cycles == 10
    assert settings.budget_usd == 5.0
    assert settings.backlog_promotion_threshold == 3
    assert settings.stages["scout"] == StageSettings(tier="basic")
    assert settings.stages["verifier"] == StageSettings(tier="expert", enabled=False)
    assert settings.dimensions == ["technical"]
    assert settings.default_agent == "codex"


def test_missing_required_max_cycles(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
        pipeline:
          budget_usd: 1.0
        """,
    )
    with pytest.raises(SettingsError) as exc:
        load_vault_settings(tmp_path)
    assert exc.value.key == "max_cycles"


def test_missing_required_budget_usd(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
        """,
    )
    with pytest.raises(SettingsError) as exc:
        load_vault_settings(tmp_path)
    assert exc.value.key == "budget_usd"


def test_invalid_tier_value(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.0
        stages:
          scout:
            tier: elite
        """,
    )
    with pytest.raises(SettingsError) as exc:
        load_vault_settings(tmp_path)
    assert exc.value.key == "stages.scout.tier"


@pytest.mark.regression
@pytest.mark.parametrize(
    ("block", "value", "key"),
    [
        ("tier_thresholds", "abc", "limits.tier_thresholds.basic"),
        ("tier_thresholds", "null", "limits.tier_thresholds.basic"),
        ("estimator_calibration", "[1]", "limits.estimator_calibration.basic"),
    ],
)
def test_a_non_numeric_limits_factor_is_a_settings_error(
    tmp_path: Path, block: str, value: str, key: str
) -> None:
    """Spec 076 FR-005: one error type. These two maps went through a bare
    ``float()``, so a typo raised ``ValueError`` / ``TypeError`` past every
    caller that degrades on ``SettingsError``."""
    _write_settings(
        tmp_path,
        f"""
        pipeline:
          max_cycles: 3
          budget_usd: 1.0
        limits:
          {block}:
            basic: {value}
        """,
    )
    with pytest.raises(SettingsError) as exc:
        load_vault_settings(tmp_path)
    assert exc.value.key == key


def test_numeric_limits_factors_still_load(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.0
        limits:
          tier_thresholds:
            basic: 2
            flagship: "7.5"
        """,
    )
    assert load_vault_settings(tmp_path).limits.tier_thresholds == {
        "basic": 2.0,
        "flagship": 7.5,
    }


def test_unknown_keys_in_extras(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.0
        custom_flag: true
        output_dir: /tmp/out
        """,
    )
    settings = load_vault_settings(tmp_path)
    assert settings.extras["custom_flag"] is True
    assert settings.extras["output_dir"] == "/tmp/out"


def test_stage_convenience_method(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.0
        stages:
          scout:
            tier: basic
        """,
    )
    settings = load_vault_settings(tmp_path)
    assert settings.stage("plan_narrator") == StageSettings(tier="standard")
    assert settings.stage("scout").tier == "basic"


def test_yaml_parse_error(tmp_path: Path) -> None:
    (tmp_path / "settings.yaml").write_text("pipeline: [\n", encoding="utf-8")
    with pytest.raises(SettingsError) as exc:
        load_vault_settings(tmp_path)
    assert "YAML parse error" in str(exc.value)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SettingsError) as exc:
        load_vault_settings(tmp_path)
    assert "settings.yaml not found" in str(exc.value)
    assert exc.value.vault_dir == tmp_path


def test_frozen_immutability(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.0
        """,
    )
    settings = load_vault_settings(tmp_path)
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.max_cycles = 99  # type: ignore[misc]


def test_default_values(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 2.5
        """,
    )
    settings = load_vault_settings(tmp_path)
    assert settings.backlog_promotion_threshold == 2
    assert settings.dimensions == []
    assert settings.default_agent == "claude"
    assert settings.stages == {}
    assert settings.extras == {}


def test_consensus_n_rejects_non_integer_tier_value(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.0
        stages:
          source_extraction:
            enabled: true
            consensus:
              tiers:
                routine: "three"
        """,
    )
    with pytest.raises(SettingsError) as exc:
        load_vault_settings(tmp_path)
    assert "integer" in str(exc.value).lower()


def test_consensus_n_values_must_be_odd(tmp_path: Path) -> None:
    _write_settings(
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
          source_extraction:
            enabled: true
            consensus:
              tiers:
                routine: 2
        """,
    )
    with pytest.raises(SettingsError) as exc:
        load_vault_settings(tmp_path)
    assert "odd" in str(exc.value).lower()


def test_backwards_compat_existing_vault(tmp_path: Path) -> None:
    """v0.2.33-era vault: required pipeline keys, no plan_narrator/probe stages."""
    _write_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 5
          budget_usd: 10.0
          backlog_promotion_threshold: 2
          note_writer_batch_size: 6
        default_executor:
          runtime: claude
          model: sonnet
        stages:
          verifier:
            enabled: true
            tier: expert
        """,
    )
    settings = load_vault_settings(tmp_path)
    assert settings.stage("plan_narrator").tier == "standard"
    assert settings.stage("probe_retrieval").tier == "standard"
    assert settings.stage("probe_retrieval").enabled is True
    assert settings.extras["default_executor"]["runtime"] == "claude"
