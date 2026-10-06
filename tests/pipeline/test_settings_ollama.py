"""Spec 047 v1 — settings.yaml accepts ollama as a valid default_agent, and the
shipped settings.ollama.yaml profile loads cleanly."""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import pytest

from research_framework.pipeline.settings import (
    SettingsError,
    load_vault_settings,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_settings(vault_dir: Path, body: str) -> None:
    vault_dir.mkdir(parents=True, exist_ok=True)
    (vault_dir / "settings.yaml").write_text(
        textwrap.dedent(body).strip() + "\n",
        encoding="utf-8",
    )


def test_default_agent_accepts_ollama(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        """
        pipeline:
          max_cycles: 10
          budget_usd: 5.0
        default_agent: ollama
        """,
    )
    settings = load_vault_settings(tmp_path)
    assert settings.default_agent == "ollama"


def test_default_agent_error_lists_ollama(tmp_path: Path) -> None:
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
    assert "ollama" in str(exc.value)


def test_shipped_ollama_profile_loads(tmp_path: Path) -> None:
    """The committed settings.ollama.yaml must be a loadable vault settings file
    that parses into real structure (not just a non-None object)."""
    profile = REPO_ROOT / "settings.ollama.yaml"
    assert profile.is_file()
    shutil.copy(profile, tmp_path / "settings.yaml")
    settings = load_vault_settings(tmp_path)
    # Structural proof the profile parsed: pipeline + per-stage blocks loaded.
    assert settings.max_cycles == 20
    assert "note_writer" in settings.stages
