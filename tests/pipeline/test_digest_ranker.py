"""Ranker unit tests (spec 035 FR-007)."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from research_framework.pipeline.digest import build_digest
from research_framework.pipeline.digest.ranker import (
    NoteScore,
    composite_score,
    rank_notes,
)
from research_framework.pipeline.digest.scope import DateRange

from .digest_helpers import (
    FIXTURE_RANGE,
    FIXTURE_RENDERED_AT,
    normalized_digest,
)

pytest_plugins = ["tests.pipeline.digest_helpers"]

_RANGE = DateRange(start=date(2026, 6, 1), end=date(2026, 6, 7))


@pytest.mark.parametrize(
    (
        "inbound",
        "cited",
        "deltas",
        "written",
        "expected_total",
        "expected_drift",
        "expected_fresh",
    ),
    [
        (3, ["youtube-rss"], {"youtube-rss": 3}, "2026-06-06T14:00:00Z", 6, 1, 2),
        (1, [], {}, "2026-06-01T10:00:00Z", 1, 0, 0),
        (2, ["a", "b"], {"a": 1, "b": 0}, "2026-06-04T12:00:00Z", 4, 1, 1),
    ],
)
def test_composite_score(
    inbound: int,
    cited: list[str],
    deltas: dict[str, int],
    written: str,
    expected_total: int,
    expected_drift: int,
    expected_fresh: int,
) -> None:
    first_written = datetime.fromisoformat(written.replace("Z", "+00:00"))
    total, inb, drift, fresh = composite_score(
        inbound_links=inbound,
        cited_sources=cited,
        referencing_deltas=deltas,
        first_written=first_written,
        date_range=_RANGE,
    )
    assert (total, inb, drift, fresh) == (
        expected_total,
        inbound,
        expected_drift,
        expected_fresh,
    )


def test_composite_score_tiebreaker_note_path() -> None:
    scores = rank_notes(
        [
            NoteScore("b.md", "B", "[[B]]", 3, 3, 0, 0, "b"),
            NoteScore("a.md", "A", "[[A]]", 3, 3, 0, 0, "a"),
        ]
    )
    assert [s.rel_path for s in scores] == ["a.md", "b.md"]


def test_strongest_signals_top5_deterministic(digest_vault: Path) -> None:

    rendered = datetime.fromisoformat(FIXTURE_RENDERED_AT)
    first, _ = build_digest(
        digest_vault, date_range=FIXTURE_RANGE, rendered_at=rendered
    )
    second, _ = build_digest(
        digest_vault, date_range=FIXTURE_RANGE, rendered_at=rendered
    )
    assert normalized_digest(first) == normalized_digest(second)
    assert "Alpha Signal" in first
    assert first.index("Alpha Signal") < first.index("Peer Note B")
