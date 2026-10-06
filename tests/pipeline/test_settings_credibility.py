"""Tier-2 tests for ``settings.yaml::credibility`` (spec 066 FR3)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from research_framework.pipeline.settings import (
    CredibilitySettings,
    SettingsError,
    load_vault_settings,
)


def _write_settings(vault_dir: Path, body: str) -> None:
    vault_dir.mkdir(parents=True, exist_ok=True)
    (vault_dir / "settings.yaml").write_text(
        textwrap.dedent(body).strip() + "\n",
        encoding="utf-8",
    )


def test_credibility_absent_block_defaults(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.5
        """,
    )
    settings = load_vault_settings(tmp_path)
    assert settings.credibility == CredibilitySettings()
    assert settings.credibility.unknown_domain_policy == "warn"
    assert settings.credibility.trusted_domains == ()


def test_credibility_parses_policy_and_trusted(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.5
        credibility:
          unknown_domain_policy: reject
          trusted_domains:
            - { domain: "internal.companyhost.com", tier: tier_1 }
            - { domain: "*.companyhost.com", tier: tier_2, match_type: host_suffix }
        """,
    )
    settings = load_vault_settings(tmp_path)
    cred = settings.credibility
    assert cred.unknown_domain_policy == "reject"
    assert len(cred.trusted_domains) == 2
    assert cred.trusted_domains[0]["domain"] == "internal.companyhost.com"


def test_credibility_rejects_bad_policy(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.5
        credibility:
          unknown_domain_policy: nuke
        """,
    )
    with pytest.raises(SettingsError):
        load_vault_settings(tmp_path)


def test_credibility_rejects_entry_without_domain(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.5
        credibility:
          trusted_domains:
            - { tier: tier_1 }
        """,
    )
    with pytest.raises(SettingsError):
        load_vault_settings(tmp_path)


def test_credibility_rejects_entry_without_tier(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.5
        credibility:
          trusted_domains:
            - { domain: "x.com" }
        """,
    )
    with pytest.raises(SettingsError):
        load_vault_settings(tmp_path)


def test_credibility_not_a_mapping(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.5
        credibility: "warn"
        """,
    )
    with pytest.raises(SettingsError):
        load_vault_settings(tmp_path)
