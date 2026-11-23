"""Tier 3: ``topics_found.updates`` is optional in a scout report and checked
for shape when present (spec 087 FR-001; T005)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def vc() -> Any:
    path = REPO_ROOT / "scripts" / "validate_cycle.py"
    spec = importlib.util.spec_from_file_location("_vc_updates", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def _v1(updates: Any = ...) -> dict:
    found: dict[str, Any] = {"new": ["A topic"], "existing": [], "total": 1}
    if updates is not ...:
        found["updates"] = updates
    return {
        "cycle": 1,
        "phase": "scout",
        "timestamp": "2026-11-23T00:00:00Z",
        "sources_consulted": {},
        "topics_found": found,
        "cost_estimate_usd": 0.0,
        "cumulative_cost_usd": 0.0,
    }


def _v2(updates: Any = ...) -> dict:
    report = {
        "schema_version": "2",
        "cycle": 1,
        "phase": "scout",
        "timestamp": "2026-11-23T00:00:00Z",
        "dimensions_covered": ["technical"],
        "topics_from_code": [],
        "intent_from_confluence": [],
        "proposed_filenames": [],
        "sources_consulted": [],
        "budget_consumed_usd": 0.0,
    }
    if updates is not ...:
        report["topics_found"] = {"new": [], "updates": updates}
    return report


GOOD = [{"note": "kafka-streams", "source_urls": ["https://x"], "summary": "s"}]


@pytest.mark.parametrize("build", ["_v1", "_v2"])
def test_a_scout_report_with_and_without_updates_validates(vc: Any, build: str) -> None:
    check = (
        vc.validate_report_structure
        if build == "_v1"
        else (vc.validate_report_structure_v2)
    )
    make = {"_v1": _v1, "_v2": _v2}[build]

    assert check(make()) == []
    assert check(make([])) == []
    assert check(make(GOOD)) == []


@pytest.mark.parametrize(
    "bad",
    [
        "kafka-streams",
        {"note": "x"},
        ["kafka-streams"],
        [{"source_urls": ["https://x"]}],
        [{"note": ""}],
        [{"note": "   "}],
        [{"note": 7}],
    ],
)
def test_a_malformed_updates_block_is_a_structural_error(vc: Any, bad: Any) -> None:
    for check, make in (
        (vc.validate_report_structure, _v1),
        (vc.validate_report_structure_v2, _v2),
    ):
        errors = check(make(bad))
        assert any("topics_found.updates" in e for e in errors), errors


def _research(rows: Any = ...) -> dict:
    report = {
        "schema_version": "2",
        "cycle": 1,
        "phase": "research",
        "timestamp": "2026-11-23T00:00:00Z",
        "sources_consulted": [],
        "budget_consumed_usd": 0.0,
    }
    if rows is not ...:
        report["update_outcomes"] = rows
    return report


OUTCOME = {
    "note": "kafka-streams",
    "outcome": "revised",
    "sources_consulted": ["https://x"],
    "evidence_url": None,
    "superseded_by": None,
    "change": "new default",
}


def test_update_outcomes_are_optional_and_shape_checked(vc: Any) -> None:
    """Spec 087 T008: ``update_outcomes`` validates with or without the key."""
    assert vc.validate_report_structure_v2(_research()) == []
    assert vc.validate_report_structure_v2(_research([])) == []
    assert vc.validate_report_structure_v2(_research([OUTCOME])) == []
    for outcome in ("confirmed", "revised", "superseded", "retracted"):
        row = {**OUTCOME, "outcome": outcome}
        assert vc.validate_report_structure_v2(_research([row])) == []

    bad_rows = [
        "revised",
        [{**OUTCOME, "outcome": "shrugged"}],
        [{**OUTCOME, "outcome": None}],
        [{**OUTCOME, "note": ""}],
        [{"outcome": "revised"}],
        [{**OUTCOME, "sources_consulted": "https://x"}],
        [{**OUTCOME, "evidence_url": 7}],
        ["not an object"],
    ]
    for rows in bad_rows:
        errors = vc.validate_report_structure_v2(_research(rows))
        assert any("update_outcomes" in e for e in errors), (rows, errors)
    assert any(
        "update_outcomes" in e
        for e in vc.validate_report_structure(
            {**_v1(), "update_outcomes": [{"note": "x", "outcome": "nope"}]}
        )
    )
