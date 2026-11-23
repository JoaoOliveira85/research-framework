"""Tier 3: which areas a cycle's scout is asked about, and that the choice
survives a re-render (spec 088 FR-001, FR-002)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from research_framework.pipeline import discovery
from research_framework.pipeline.orchestrator import _discovery_assignment
from research_framework.spec.schema import SpecConfig

AREAS = [f"area {i}" for i in range(7)]


def _spec() -> SpecConfig:
    return SpecConfig.from_dict(
        {
            "name": "assign",
            "owner": "tests",
            "naming_convention": "slug",
            "scope": {"boundaries": AREAS},
        }
    )


def _settings(vault: Path, split: str, block: str = "") -> None:
    (vault / "settings.yaml").write_text(
        f"pipeline:\n  max_cycles: 5\n  budget_usd: 10.0\n  cycle_split: {split}\n"
        + block,
        encoding="utf-8",
    )


def test_three_areas_a_cycle_least_recently_checked_first(tmp_path: Path) -> None:
    _settings(tmp_path, "{new: 60, updates: 30, discovery: 10}")
    spec = _spec()
    seen: list[str] = []
    for cycle in (1, 2, 3):  # ceil(7 / 3) cycles
        areas, start = _discovery_assignment(tmp_path, spec, cycle)
        assert len(areas) == 3 and start
        seen.extend(areas)
        discovery.record_cycle(
            tmp_path,
            cycle=cycle,
            assigned=areas,
            reported=[{"area": a, "queries": ["q"], "found": 0} for a in areas],
            kept=0,
            rerouted=0,
            dropped=[],
        )
    assert set(seen) == set(AREAS)  # SC-002
    assert seen[:6] == AREAS[:6]  # spec order while none was ever checked


def test_the_window_opens_window_days_before_today(tmp_path: Path) -> None:
    _settings(
        tmp_path,
        "{new: 60, updates: 30, discovery: 10}",
        "  discovery: {areas_per_cycle: 2, window_days: 30}\n",
    )
    areas, start = _discovery_assignment(tmp_path, _spec(), 1)
    assert areas == AREAS[:2]
    expected = dt.datetime.now(dt.UTC).date() - dt.timedelta(days=30)
    assert start == expected.isoformat()


def test_a_rerender_in_the_same_cycle_asks_the_same_areas(tmp_path: Path) -> None:
    _settings(tmp_path, "{new: 60, updates: 30, discovery: 10}")
    first = _discovery_assignment(tmp_path, _spec(), 1)
    # the ledger moves on (an unrelated cycle recorded) but cycle 1 is remembered
    discovery.record_cycle(
        tmp_path,
        cycle=9,
        assigned=AREAS[:3],
        reported=[{"area": a, "queries": [], "found": 0} for a in AREAS[:3]],
        kept=0,
        rerouted=0,
        dropped=[],
    )
    assert _discovery_assignment(tmp_path, _spec(), 1) == first
    assert discovery.read_assignment(tmp_path, 1)["areas"] == first[0]


def test_share_zero_or_no_areas_means_no_pass(tmp_path: Path) -> None:
    _settings(tmp_path, "{new: 70, updates: 30, discovery: 0}")
    assert _discovery_assignment(tmp_path, _spec(), 1) == ([], None)
    assert not discovery.assignment_path(tmp_path, 1).exists()
    _settings(tmp_path, "{new: 60, updates: 30, discovery: 10}")
    bare = SpecConfig.from_dict(
        {"name": "bare", "owner": "tests", "naming_convention": "slug"}
    )
    assert _discovery_assignment(tmp_path, bare, 1) == ([], None)


def test_an_unreadable_ledger_skips_the_pass_without_raising(tmp_path: Path) -> None:
    _settings(tmp_path, "{new: 60, updates: 30, discovery: 10}")
    from research_framework.pipeline import state_layout

    path = state_layout.discovery_ledger_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    assert _discovery_assignment(tmp_path, _spec(), 1) == ([], None)
