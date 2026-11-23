"""Spec 088 T001: the discovery ledger (FR-008, FR-009)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline import discovery, state_layout


def _record(vault: Path, cycle: int, assigned: list[str], reported: list[dict]):
    return discovery.record_cycle(
        vault,
        cycle=cycle,
        assigned=assigned,
        reported=reported,
        kept=1,
        rerouted=2,
        dropped=[{"title": "T", "reason": "no source"}],
    )


def test_a_missing_file_is_an_empty_ledger(tmp_path: Path) -> None:
    assert discovery.load_ledger(tmp_path) == {
        "schema_version": 1,
        "areas": {},
        "cycles": [],
    }
    assert not state_layout.discovery_ledger_path(tmp_path).exists()


def test_checked_with_nothing_found_is_distinct_from_never_checked(
    tmp_path: Path,
) -> None:
    _record(
        tmp_path,
        4,
        ["quiet", "silent"],
        [{"area": "quiet", "queries": ["q1", "q2"], "found": 0}],
    )
    areas = discovery.load_ledger(tmp_path)["areas"]
    assert areas["quiet"] == {
        "last_checked_cycle": 4,
        "times_checked": 1,
        "found_total": 0,
        "last_found_cycle": None,
        "times_assigned_not_reported": 0,
    }
    assert areas["silent"]["last_checked_cycle"] is None
    assert areas["silent"]["times_checked"] == 0


def test_assigned_but_not_reported_does_not_advance_the_area(tmp_path: Path) -> None:
    _record(tmp_path, 1, ["a"], [{"area": "a", "queries": ["q"], "found": 2}])
    _record(tmp_path, 2, ["a"], [])
    row = discovery.load_ledger(tmp_path)["areas"]["a"]
    assert row["last_checked_cycle"] == 1
    assert row["times_checked"] == 1
    assert row["times_assigned_not_reported"] == 1
    assert row["found_total"] == 2
    assert row["last_found_cycle"] == 1


def test_recording_a_cycle_twice_replaces_it(tmp_path: Path) -> None:
    _record(tmp_path, 1, ["a"], [{"area": "a", "queries": ["q"], "found": 3}])
    _record(tmp_path, 2, ["a"], [{"area": "a", "queries": ["q"], "found": 1}])
    first = _record(tmp_path, 2, ["a"], [{"area": "a", "queries": ["q"], "found": 1}])
    again = _record(tmp_path, 2, ["a"], [{"area": "a", "queries": ["q"], "found": 1}])
    assert first == again
    assert [c["cycle"] for c in again["cycles"]] == [1, 2]
    row = again["areas"]["a"]
    assert (row["times_checked"], row["found_total"], row["last_found_cycle"]) == (
        2,
        4,
        2,
    )
    # A re-record with a different outcome recomputes, rather than adds to, the area.
    changed = _record(tmp_path, 2, ["a"], [])
    row = changed["areas"]["a"]
    assert (row["times_checked"], row["last_checked_cycle"]) == (1, 1)
    assert row["times_assigned_not_reported"] == 1


def test_the_cycle_record_keeps_every_field(tmp_path: Path) -> None:
    _record(tmp_path, 3, ["a"], [{"area": "a", "queries": ["q"], "found": 1}])
    on_disk = json.loads(state_layout.discovery_ledger_path(tmp_path).read_text())
    assert on_disk["cycles"] == [
        {
            "cycle": 3,
            "assigned": ["a"],
            "reported": [{"area": "a", "queries": ["q"], "found": 1}],
            "kept": 1,
            "rerouted": 2,
            "dropped": [{"title": "T", "reason": "no source"}],
        }
    ]


@pytest.mark.parametrize(
    "text",
    [
        "{not json",
        "[]",
        '{"schema_version": 2, "areas": {}, "cycles": []}',
        '{"schema_version": 1, "areas": [], "cycles": []}',
        '{"schema_version": 1, "areas": {}, "cycles": [1]}',
    ],
)
def test_an_unparseable_ledger_raises_a_typed_error_naming_the_file(
    tmp_path: Path, text: str
) -> None:
    path = state_layout.discovery_ledger_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    with pytest.raises(discovery.DiscoveryLedgerError, match="discovery-ledger.json"):
        discovery.load_ledger(tmp_path)
    with pytest.raises(discovery.DiscoveryLedgerError):
        _record(tmp_path, 1, ["a"], [])
    assert path.read_text(encoding="utf-8") == text
