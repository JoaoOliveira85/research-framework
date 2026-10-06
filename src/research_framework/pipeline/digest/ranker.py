"""Deterministic ranker + gap helpers (spec 035 FR-006..FR-008)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .scope import DateRange


@dataclass(frozen=True)
class NoteScore:
    rel_path: str
    title: str
    wikilink: str
    score: int
    inbound_links: int
    source_drift_bonus: int
    freshness_points: int
    summary: str


@dataclass(frozen=True)
class GapEntry:
    category: str
    kind: str
    progress_start: float
    progress_end: float
    target: float
    last_cycle: int


def freshness_points(first_written: datetime, date_range: DateRange) -> int:
    start_dt = datetime.combine(date_range.start, datetime.min.time(), tzinfo=UTC)
    end_dt = datetime.combine(date_range.end, datetime.max.time(), tzinfo=UTC)
    span = max(1.0, (end_dt - start_dt).total_seconds())
    ratio = (first_written.astimezone(UTC) - start_dt).total_seconds() / span
    if ratio >= 0.75:
        return 2
    if ratio >= 0.5:
        return 1
    return 0


def source_drift_bonus(
    cited_sources: list[str], referencing_deltas: dict[str, int]
) -> int:
    return sum(1 for name in cited_sources if referencing_deltas.get(name, 0) > 0)


def composite_score(
    *,
    inbound_links: int,
    cited_sources: list[str],
    referencing_deltas: dict[str, int],
    first_written: datetime,
    date_range: DateRange,
) -> tuple[int, int, int, int]:
    drift = source_drift_bonus(cited_sources, referencing_deltas)
    fresh = freshness_points(first_written, date_range)
    return inbound_links + drift + fresh, inbound_links, drift, fresh


def rank_notes(scores: list[NoteScore], *, limit: int = 5) -> list[NoteScore]:
    return sorted(scores, key=lambda s: (-s.score, s.rel_path))[:limit]


_FULL_PCT = 100.0


def coverage_progress(report: dict[str, Any], category: str) -> float:
    """Return *category*'s coverage in *report* as a percentage (0–100).

    The cycle quality report stores ``fill_pct`` as a fraction — ``met /
    target`` clamped to 0..1 (spec 017 ``cycle-quality-report.schema.json``;
    CG-005 and ``status`` read it that way). This adapter used to hand the
    fraction through unchanged to formatters that print a percentage, so a
    half-filled category rendered as "0.5%". A row without ``fill_pct`` is
    derived from its ``met`` / ``target`` counts rather than read as a count.
    """
    snap = report.get("coverage_snapshot")
    if not isinstance(snap, dict):
        return 0.0
    row = snap.get(category)
    if not isinstance(row, dict):
        return 0.0
    try:
        if "fill_pct" in row:
            fraction = float(row["fill_pct"])
        else:
            target = float(row.get("target") or 0)
            fraction = float(row.get("met") or 0) / target if target > 0 else 0.0
    except (TypeError, ValueError):
        return 0.0
    return fraction * _FULL_PCT


def detect_gaps(
    *,
    categories: list[dict[str, Any]],
    first_report: dict[str, Any],
    last_report: dict[str, Any],
    last_cycle: int,
) -> list[GapEntry]:
    regressed: list[GapEntry] = []
    stagnant: list[GapEntry] = []
    for cat in categories:
        name = str(cat.get("name") or "")
        if not name:
            continue
        target = float(cat.get("target_count") or cat.get("target") or 0)
        start = coverage_progress(first_report, name)
        end = coverage_progress(last_report, name)
        if end < start:
            regressed.append(
                GapEntry(name, "regressed", start, end, target, last_cycle)
            )
        elif end == start and end < _FULL_PCT and target > 0:
            # "Below the category target" is a fill below 100%. Comparing the
            # fill with the target COUNT flagged every met category (1.0 < 4).
            stagnant.append(GapEntry(name, "stagnant", start, end, target, last_cycle))
    return regressed + stagnant


def format_progress_pct(value: float) -> str:
    if abs(value - round(value)) < 0.01:
        return f"{int(round(value))}%"
    return f"{value:.1f}%"


def format_progress_delta(value: float) -> str:
    sign = "+" if value > 0 else ""
    return sign + format_progress_pct(value)


__all__ = [
    "GapEntry",
    "NoteScore",
    "composite_score",
    "coverage_progress",
    "detect_gaps",
    "format_progress_delta",
    "format_progress_pct",
    "freshness_points",
    "rank_notes",
    "source_drift_bonus",
]
