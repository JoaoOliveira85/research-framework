"""Spec 052 — settings.yaml accepts cursor-agent as a valid default_agent."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from research_framework.pipeline.settings import (
    SettingsError,
    load_vault_settings,
)


def _write_settings(vault_dir: Path, body: str) -> None:
    vault_dir.mkdir(parents=True, exist_ok=True)
    (vault_dir / "settings.yaml").write_text(
        textwrap.dedent(body).strip() + "\n",
        encoding="utf-8",
    )


def test_default_agent_accepts_cursor_agent(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 10
          budget_usd: 5.0
        default_agent: cursor-agent
        """,
    )
    settings = load_vault_settings(tmp_path)
    assert settings.default_agent == "cursor-agent"


def test_default_agent_rejects_unknown(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 10
          budget_usd: 5.0
        default_agent: pizza
        """,
    )
    with pytest.raises(SettingsError) as exc:
        load_vault_settings(tmp_path)
    assert "default_agent" in str(exc.value)
