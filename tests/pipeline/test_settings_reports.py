"""Tier-2 tests for ``settings.yaml::reports`` (spec 040 T003)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from research_framework.pipeline.settings import (
    ReportsMirrorSettings,
    ReportsSettings,
    ReportsSmtpSettings,
    SettingsError,
    load_vault_settings,
)


def _write_settings(vault_dir: Path, body: str) -> None:
    vault_dir.mkdir(parents=True, exist_ok=True)
    (vault_dir / "settings.yaml").write_text(
        textwrap.dedent(body).strip() + "\n",
        encoding="utf-8",
    )


def _minimal_pipeline() -> str:
    return """
    pipeline:
      max_cycles: 3
      budget_usd: 1.5
    """


def test_reports_absent_block_defaults(tmp_path: Path) -> None:
    _write_settings(tmp_path, _minimal_pipeline())
    settings = load_vault_settings(tmp_path)
    assert settings.reports == ReportsSettings(
        mirror=ReportsMirrorSettings(),
        smtp=ReportsSmtpSettings(),
    )


def test_reports_partial_block_unset_fields_default(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.5
        reports:
          mirror:
            target: /tmp/mirror
          smtp:
            enabled: true
        """,
    )
    settings = load_vault_settings(tmp_path)
    assert settings.reports.mirror.target == "/tmp/mirror"
    assert settings.reports.smtp.enabled is True
    assert settings.reports.smtp.recipient is None
    assert settings.reports.smtp.server is None
    assert settings.reports.smtp.port is None
    assert settings.reports.smtp.from_address is None


def test_reports_types_coerced_and_validated(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.5
        reports:
          smtp:
            enabled: false
            recipient: ops@example.com
            server: smtp.example.com
            port: 587
            from: vault@example.com
        """,
    )
    settings = load_vault_settings(tmp_path)
    smtp = settings.reports.smtp
    assert smtp.enabled is False
    assert smtp.recipient == "ops@example.com"
    assert smtp.server == "smtp.example.com"
    assert smtp.port == 587
    assert smtp.from_address == "vault@example.com"


def test_reports_invalid_smtp_port_raises(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 3
          budget_usd: 1.5
        reports:
          smtp:
            port: not-an-int
        """,
    )
    with pytest.raises(SettingsError, match="reports.smtp.port"):
        load_vault_settings(tmp_path)
