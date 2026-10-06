"""Tier-2 settings loader tests for spec 033 limits + approval_gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.pipeline.settings import load_vault_settings


def _write_settings(tmp_path: Path, body: str) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(body, encoding="utf-8")
    return vault


def test_limits_settings_loads_cycle_budget_and_codex_fields(tmp_path: Path) -> None:
    vault = _write_settings(
        tmp_path,
        """
pipeline:
  max_cycles: 3
  budget_usd: 5.0
limits:
  cycle_budget_usd: 12.5
  codex_token_budget: 50000
  cycle_wallclock_budget_minutes: 90
  cycle_budget_warn_at: 0.75
  tier_thresholds:
    basic: 0.10
  estimator_calibration:
    claude: 1.20
""",
    )
    settings = load_vault_settings(vault)
    assert settings.limits.cycle_budget_usd == 12.5
    assert settings.limits.codex_token_budget == 50000
    assert settings.limits.cycle_wallclock_budget_minutes == 90
    assert settings.limits.cycle_budget_warn_at == 0.75
    assert settings.limits.tier_thresholds["basic"] == 0.10
    assert settings.limits.estimator_calibration["claude"] == 1.20


def test_approval_gates_loaded_from_top_level_not_limits(tmp_path: Path) -> None:
    vault = _write_settings(
        tmp_path,
        """
pipeline:
  max_cycles: 2
  budget_usd: 1.0
approval_gates:
  - research
limits:
  cycle_budget_usd: 2.0
""",
    )
    settings = load_vault_settings(vault)
    assert settings.approval_gates == ["research"]


def test_budget_usd_alias_migrates_to_cycle_budget_usd(tmp_path: Path) -> None:
    vault = _write_settings(
        tmp_path,
        """
pipeline:
  max_cycles: 2
  budget_usd: 1.0
limits:
  budget_usd: 3.25
""",
    )
    with pytest.warns(DeprecationWarning, match="cycle_budget_usd"):
        settings = load_vault_settings(vault)
    assert settings.limits.cycle_budget_usd == 3.25
