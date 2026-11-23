"""Tier 3: ``vault_health`` lists scope areas the discovery pass has never
checked, or not checked for too long (spec 088 FR-010; T005)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from research_framework.pipeline import discovery
from research_framework.spec.schema import ScopeConfig
from tests._helpers.vault_factory import build_minimal_vault

ROOT = Path(__file__).resolve().parents[2]
AREAS = [f"area {i}" for i in range(6)]


@pytest.fixture(scope="module")
def vh() -> Any:
    path = ROOT / "scripts" / "vault_health.py"
    spec = importlib.util.spec_from_file_location("_vault_health_discovery", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def _vault(tmp_path: Path, split: str = "") -> Path:
    vault = build_minimal_vault(
        tmp_path,
        num_categories=1,
        max_cycles=1,
        spec_overrides={
            "scope": ScopeConfig(
                domain="d", organization="o", out_of_scope=[], boundaries=AREAS
            )
        },
    )
    if split:
        settings = vault / "settings.yaml"
        settings.write_text(
            settings.read_text(encoding="utf-8").replace(
                "pipeline:\n", f"pipeline:\n  cycle_split: {split}\n", 1
            ),
            encoding="utf-8",
        )
    return vault


def _record(vault: Path, cycle: int, areas: list[str]) -> None:
    discovery.record_cycle(
        vault,
        cycle=cycle,
        assigned=areas,
        reported=[{"area": a, "queries": ["q"], "found": 0} for a in areas],
        kept=0,
        rerouted=0,
        dropped=[],
    )


def test_health_lists_areas_never_checked(vh: Any, tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _record(vault, 1, AREAS[:3])

    report = vh.run(vault, offline=True)

    found = report.discovery
    assert found.never_checked == tuple(AREAS[3:])
    assert found.stale == () and found.threshold == 2 * 2  # 2 x ceil(6 / 3)
    text = vh.render_report(report, vault)
    assert "## Discovery" in text and "### never checked (3)" in text
    assert "- area 3" in text and "- area 0" not in text
    # advisory: it never changes the exit code
    assert report.unresolved_count == 0


def test_health_lists_areas_not_checked_for_too_long(vh: Any, tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _record(vault, 1, AREAS[:3])
    _record(vault, 2, AREAS[3:])
    for cycle in range(3, 8):  # area 0..2 last checked at cycle 1: 6 cycles ago
        _record(vault, cycle, AREAS[3:])

    found = discovery.health(vault)

    assert found is not None and found.cycle == 7
    assert found.never_checked == ()
    assert found.stale == tuple((a, 6) for a in AREAS[:3])
    text = vh.render_report(vh.run(vault, offline=True), vault)
    assert "### not checked for more than 4 cycles (3)" in text
    assert "- area 0 (6 cycles ago)" in text


def test_a_vault_with_discovery_off_shows_nothing(vh: Any, tmp_path: Path) -> None:
    vault = _vault(tmp_path, split="{new: 70, updates: 30, discovery: 0}")
    _record(vault, 1, AREAS[:1])
    assert discovery.health(vault) is None
    report = vh.run(vault, offline=True)
    assert report.discovery is None
    assert "## Discovery" not in vh.render_report(report, vault)


def test_a_vault_that_never_ran_a_cycle_shows_nothing(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    assert discovery.health(vault) is None
    (vault / "_pipeline" / "state" / "discovery-ledger.json").write_text("{x")
    assert discovery.health(vault) is None  # an unreadable ledger never fails health
    assert json.dumps(discovery.cycle_summary(vault, 1)) == "null"
