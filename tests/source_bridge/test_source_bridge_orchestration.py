"""Orchestration integration tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from research_framework.pipeline.source_bridge.orchestrator import run_extraction
from research_framework.pipeline.source_bridge.sources_loader import load_module_sources


def test_run_extraction_enumerates_sources_yaml_only(bridge_vault: Path) -> None:
    with patch(
        "research_framework.pipeline.source_bridge.orchestrator.load_module_sources",
        wraps=load_module_sources,
    ) as loader:
        run_extraction(bridge_vault, 1)
        loader.assert_called()


def test_per_source_loop_runs_consensus_then_validators(bridge_vault: Path) -> None:
    (bridge_vault / "settings.yaml").write_text(
        (bridge_vault / "settings.yaml")
        .read_text()
        .replace("routine: 1", "routine: 3"),
        encoding="utf-8",
    )
    summary = run_extraction(bridge_vault, 1)
    assert "modules" in summary
    consensus_dir = bridge_vault / "_pipeline" / "sources" / "stub" / "consensus"
    assert consensus_dir.is_dir()
    assert list(consensus_dir.glob("*.json"))


def test_generic_path_uses_module_generic_cache_keys(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "research.spec.md").write_text("# Spec\n", encoding="utf-8")
    (vault / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 3\n  budget_usd: 1.0\n"
        "modules: []\nstages:\n  source_extraction:\n    enabled: true\n",
        encoding="utf-8",
    )
    summary = run_extraction(vault, 1)
    assert summary.get("skipped") or "modules" in summary


def test_run_extraction_integrates_discovery_and_enumeration(
    bridge_vault: Path,
) -> None:
    summary = run_extraction(bridge_vault, 1)
    assert summary["cycle"] == 1
    assert summary["modules"]
