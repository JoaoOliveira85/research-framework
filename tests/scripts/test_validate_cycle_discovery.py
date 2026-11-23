"""Tier 3: ``topics_found.discovery`` and ``discovery_checked`` are optional in a
scout report and checked for shape when present (spec 088 FR-003, T003)."""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def vc() -> Any:
    path = REPO_ROOT / "scripts" / "validate_cycle.py"
    spec = importlib.util.spec_from_file_location("_vc_discovery", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def _base(version: str) -> dict[str, Any]:
    if version == "v1":
        return {
            "cycle": 1,
            "phase": "scout",
            "timestamp": "2026-11-23T00:00:00Z",
            "sources_consulted": {},
            "topics_found": {"new": ["A topic"], "existing": [], "total": 1},
            "cost_estimate_usd": 0.0,
            "cumulative_cost_usd": 0.0,
        }
    return {
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
        "topics_found": {"new": []},
    }


def _check(vc: Any, version: str, report: dict[str, Any]) -> list[str]:
    fn = (
        vc.validate_report_structure
        if version == "v1"
        else vc.validate_report_structure_v2
    )
    return fn(report)


ROW = {
    "title": "Cell-based routing",
    "area": "Streaming ingestion",
    "why_new": "appeared in 2026",
    "source_urls": ["https://example.org/a"],
    "published": "2026-09-01",
    "coverage_category": "pattern",
    "proposed_filename": "cell-based-routing.md",
}
CHECKED = {"area": "Streaming ingestion", "queries": ["q1", "q2"], "found": 1}


def _with(version: str, *, rows: Any = ..., checked: Any = ...) -> dict[str, Any]:
    report = _base(version)
    if rows is not ...:
        report["topics_found"]["discovery"] = rows
    if checked is not ...:
        report["discovery_checked"] = checked
    return report


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_reports_with_and_without_discovery_validate(vc: Any, version: str) -> None:
    assert _check(vc, version, _with(version)) == []
    assert _check(vc, version, _with(version, rows=[], checked=[])) == []
    assert _check(vc, version, _with(version, rows=[ROW], checked=[CHECKED])) == []
    # "checked, nothing found" and a null publication date are both valid shapes
    quiet = {**CHECKED, "found": 0, "queries": []}
    assert _check(vc, version, _with(version, checked=[quiet])) == []
    assert _check(vc, version, _with(version, rows=[{**ROW, "published": None}])) == []


@pytest.mark.parametrize("version", ["v1", "v2"])
@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"rows": "nope"}, "topics_found.discovery must be a list"),
        ({"rows": ["x"]}, "topics_found.discovery[0] must be an object"),
        ({"rows": [{**ROW, "title": ""}]}, "'title'"),
        ({"rows": [{**ROW, "title": "  "}]}, "'title'"),
        ({"rows": [{k: v for k, v in ROW.items() if k != "area"}]}, "'area'"),
        ({"rows": [{**ROW, "source_urls": "https://x"}]}, "source_urls"),
        ({"rows": [{**ROW, "source_urls": [1]}]}, "source_urls"),
        ({"rows": [{**ROW, "published": 2026}]}, "published"),
        ({"checked": {"area": "a"}}, "discovery_checked must be a list"),
        ({"checked": ["x"]}, "discovery_checked[0] must be an object"),
        ({"checked": [{**CHECKED, "area": ""}]}, "'area'"),
        ({"checked": [{**CHECKED, "queries": "q"}]}, "queries"),
        ({"checked": [{**CHECKED, "queries": [3]}]}, "queries"),
        ({"checked": [{**CHECKED, "found": -1}]}, "found"),
        ({"checked": [{**CHECKED, "found": "2"}]}, "found"),
        ({"checked": [{**CHECKED, "found": True}]}, "found"),
        ({"checked": [{"area": "a", "queries": []}]}, "found"),
    ],
)
def test_a_malformed_discovery_shape_is_a_structural_error(
    vc: Any, version: str, kwargs: dict[str, Any], fragment: str
) -> None:
    errors = _check(vc, version, copy.deepcopy(_with(version, **kwargs)))
    assert any(fragment in e for e in errors), errors
