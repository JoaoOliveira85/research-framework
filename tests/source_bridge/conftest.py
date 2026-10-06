"""Shared fixtures for source_bridge tests."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


@pytest.fixture
def minimal_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "research.spec.md").write_text("# Spec\n", encoding="utf-8")
    (vault / "settings.yaml").write_text(
        textwrap.dedent(
            """
            pipeline:
              max_cycles: 3
              budget_usd: 1.0
            tiers:
              basic: claude-haiku-4-5
              normal: claude-sonnet-5
              flagship: claude-opus-5
            modules: [stub]
            stages:
              source_extraction:
                enabled: true
                tier: basic
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return vault


@pytest.fixture
def bridge_vault(tmp_path: Path) -> Path:
    """Vault with stub module + sources.yaml for orchestration tests."""
    import yaml

    from tests._helpers.fake_module import write_fake_extractor

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "research.spec.md").write_text("# Spec\nbody\n", encoding="utf-8")
    (vault / "settings.yaml").write_text(
        textwrap.dedent(
            """
            pipeline:
              max_cycles: 3
              budget_usd: 1.0
            tiers:
              basic: claude-haiku-4-5
              normal: claude-sonnet-5
              flagship: claude-opus-5
            modules: [stub]
            stages:
              source_extraction:
                enabled: true
                tier: basic
                consensus:
                  tiers:
                    routine: 1
                    important: 3
                    critical: 5
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    mod = vault / "modules" / "stub"
    mod.mkdir(parents=True)
    (mod / "manifest.yaml").write_text(
        yaml.dump(
            {
                "name": "stub",
                "version": "0.1.0",
                "description": "test",
                "triggers": [{"type": "path_pattern", "pattern": ".*"}],
                "entry_point": "extractor.py",
                "preflight": {"entry_point": "preflight.py", "timeout_seconds": 30},
                "default_value_tier": "routine",
                "schema_examples": "few-shot.md",
            }
        ),
        encoding="utf-8",
    )
    (mod / "sources.yaml").write_text(
        yaml.dump({"sources": [{"path": "/tmp/repo", "value_tier": "routine"}]}),
        encoding="utf-8",
    )
    write_fake_extractor(mod)
    return vault
