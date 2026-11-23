"""Tier 1: DG-001 checks every discovery row and drops the bad ones with their
reason (spec 088 FR-004)."""

from __future__ import annotations

from datetime import date

import pytest

from research_framework.pipeline import discovery
from research_framework.pipeline.gates_step import DG001_discovery_rows

TODAY = date(2026, 11, 23)
START = date(2026, 5, 27)  # 180 days earlier
AREAS = ["Streaming ingestion", "Idempotent consumers"]


def _row(**over: object) -> dict:
    row = {
        "title": "Cell-based routing",
        "area": AREAS[0],
        "why_new": "appeared this year",
        "source_urls": ["https://example.org/a"],
        "published": "2026-09-01",
        "coverage_category": "pattern",
        "proposed_filename": "cell-based-routing.md",
    }
    row.update(over)
    return row


def _drop(row: object) -> str:
    (verdict,) = discovery.evaluate_rows([row], AREAS, START, TODAY)
    assert not verdict.ok
    return verdict.reason


def test_a_good_row_passes() -> None:
    (verdict,) = discovery.evaluate_rows([_row()], AREAS, START, TODAY)
    assert verdict.ok and verdict.reason == ""


@pytest.mark.parametrize(
    ("over", "fragment"),
    [
        ({"area": "A different area"}, "not assigned"),
        ({"area": "streaming ingestion"}, "not assigned"),  # the text is exact
        ({"area": None}, "not assigned"),
        ({"source_urls": []}, "no source"),
        ({"source_urls": ["", "  "]}, "no source"),
        ({"source_urls": "https://x"}, "no source"),
        ({"published": "2026-05-26"}, "before the window"),
        ({"published": "2026-11-24"}, "after today"),
        ({"published": "last spring"}, "malformed publication date"),
        ({"published": "2026-13-45"}, "malformed publication date"),
        ({"published": "20260901"}, "malformed publication date"),
        ({"published": None}, "no publication date"),
        ({"published": 2026}, "no publication date"),
        ({"title": ""}, "empty title"),
        ({"title": "   "}, "empty title"),
        ({"title": None}, "empty title"),
    ],
)
def test_each_bad_row_is_dropped_with_its_reason(
    over: dict[str, object], fragment: str
) -> None:
    assert fragment in _drop(_row(**over))


def test_a_row_that_is_not_an_object_is_dropped() -> None:
    assert "not an object" in _drop("a bare string")
    assert "not an object" in _drop(None)


def test_the_window_is_inclusive_at_both_ends() -> None:
    rows = [_row(published=START.isoformat()), _row(published=TODAY.isoformat())]
    assert all(v.ok for v in discovery.evaluate_rows(rows, AREAS, START, TODAY))
    # a timestamp keeps its date part
    (v,) = discovery.evaluate_rows(
        [_row(published="2026-09-01T10:00:00Z")], AREAS, START, TODAY
    )
    assert v.ok


def test_the_gate_warns_and_never_fails() -> None:
    verdicts = discovery.evaluate_rows(
        [_row(), _row(title="Bad", source_urls=[]), _row(title="")],
        AREAS,
        START,
        TODAY,
    )
    result = DG001_discovery_rows(verdicts)
    assert result.gate_id == "DG-001"
    assert result.status == "WARN" and result.metric_value == 2
    assert "Bad: no source" in result.message and "?: empty title" in result.message
    assert DG001_discovery_rows(verdicts[:1]).status == "PASS"
    assert DG001_discovery_rows([]).status == "PASS"
