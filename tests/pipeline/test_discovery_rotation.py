"""Spec 088 T001: scope areas and their deterministic rotation (FR-002, SC-002)."""

from __future__ import annotations

import math
from pathlib import Path

from research_framework.pipeline import discovery
from research_framework.spec.schema import SpecConfig
from research_framework.spec.simple import load as load_spec

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "specs"
    / "code-first-vault-spec.md"
)


def _ledger(**last_checked: int | None) -> dict:
    return {
        "schema_version": 1,
        "areas": {a: {"last_checked_cycle": c} for a, c in last_checked.items()},
        "cycles": [],
    }


def test_never_checked_then_oldest_then_spec_order() -> None:
    areas = ["a", "b", "c", "d", "e"]
    # c and e were never checked (no row / null); b was checked at 7, a and d at 3.
    ledger = _ledger(a=3, b=7, d=3, e=None)
    assert discovery.choose_areas(ledger, areas, 5) == ["c", "e", "a", "d", "b"]
    assert discovery.choose_areas(ledger, areas, 3) == ["c", "e", "a"]
    assert discovery.choose_areas(ledger, areas, 0) == []
    assert discovery.choose_areas(ledger, areas, 99) == ["c", "e", "a", "d", "b"]


def test_an_area_no_longer_in_the_spec_is_ignored_but_its_row_stays(
    tmp_path: Path,
) -> None:
    discovery.record_cycle(
        tmp_path,
        cycle=1,
        assigned=["old", "kept"],
        reported=[
            {"area": "old", "queries": ["q"], "found": 1},
            {"area": "kept", "queries": ["q"], "found": 0},
        ],
        kept=1,
        rerouted=0,
        dropped=[],
    )
    ledger = discovery.load_ledger(tmp_path)
    assert discovery.choose_areas(ledger, ["kept", "new"], 5) == ["new", "kept"]
    assert "old" in ledger["areas"]


def test_every_area_is_checked_within_the_expected_cycles(tmp_path: Path) -> None:
    areas = [f"area {i}" for i in range(7)]
    per_cycle = 3
    needed = math.ceil(len(areas) / per_cycle)
    for cycle in range(1, needed + 1):
        ledger = discovery.load_ledger(tmp_path)
        assigned = discovery.choose_areas(ledger, areas, per_cycle)
        assert len(assigned) == len(set(assigned))
        discovery.record_cycle(
            tmp_path,
            cycle=cycle,
            assigned=assigned,
            reported=[{"area": a, "queries": ["q"], "found": 0} for a in assigned],
            kept=0,
            rerouted=0,
            dropped=[],
        )
    rows = discovery.load_ledger(tmp_path)["areas"]
    assert set(rows) == set(areas)
    assert all(rows[a]["times_checked"] >= 1 for a in areas)


def test_simple_and_detailed_specs_both_yield_areas(tmp_path: Path) -> None:
    detailed = load_spec(FIXTURE)
    assert discovery.scope_areas(detailed) == [
        "Platform-owned services (CAT, LDG, BAL, CLR, SET, CFG, RPT, ONB, plus "
        "reference-lookup-tool)",
        "Upstream producers and downstream consumers of those services "
        "(as referenced in code)",
        "Domain concepts referenced 2+ times across Platform repos",
    ]
    simple_path = tmp_path / "research.spec.md"
    simple_path.write_text(
        '---\nname: "Simple Vault"\nowner: "me"\ntopic: "A topic"\n'
        "scope:\n  include:\n    - first area\n    - '  second area  '\n"
        "    - first area\n    - ''\n    - third area\n---\n",
        encoding="utf-8",
    )
    simple = load_spec(simple_path)
    assert discovery.scope_areas(simple) == ["first area", "second area", "third area"]


def test_scope_areas_strip_drop_empty_and_keep_the_first_duplicate() -> None:
    spec = SpecConfig.__new__(SpecConfig)
    spec.scope = type("S", (), {"boundaries": [" b ", "", "a", "b", "  ", "a "]})()
    assert discovery.scope_areas(spec) == ["b", "a"]
