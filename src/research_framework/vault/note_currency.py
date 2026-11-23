"""The note-currency declaration: when a note was last checked and where it stands.

Spec 087 FR-006..FR-009. This module is the single place the frontmatter field
names and the five standing values are spelled; every reader imports them from
here (``tests/vault/test_note_currency.py`` pins that).

* ``as_of``: the date the note was last checked against its sources.
* ``currency``: its standing, one of :data:`CURRENCY_VALUES`.
* ``supersedes`` / ``superseded_by``: the links between a note and its
  replacement (declared here; read by later tasks).

A note written before the fields existed carries neither. It reads as
``current`` and never due, so adding the fields changes nothing for it.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

AS_OF_FIELD = "as_of"
CURRENCY_FIELD = "currency"
SUPERSEDES_FIELD = "supersedes"
SUPERSEDED_BY_FIELD = "superseded_by"

EMERGING = "emerging"
CURRENT = "current"
DECLINING = "declining"
SUPERSEDED = "superseded"
RETRACTED = "retracted"

CURRENCY_VALUES: tuple[str, ...] = (EMERGING, CURRENT, DECLINING, SUPERSEDED, RETRACTED)

#: Standings that still count toward coverage.
_COUNTABLE = frozenset({EMERGING, CURRENT, DECLINING})
#: Standings a review can apply to: a replaced or withdrawn note is never due.
_REVIEWABLE = _COUNTABLE


def _as_date(value: Any) -> date | None:
    """A frontmatter ``as_of`` value as a date, or None when absent or malformed."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text[:10]) if len(text) >= 10 else None
        except ValueError:
            return None
    return None


def _standing(value: Any) -> str:
    """A frontmatter ``currency`` value as one of the five; unset reads ``current``.

    An unrecognised value also reads as ``current``: a typo must not make a note
    uncountable or silently drop it from review.
    """
    if isinstance(value, str):
        text = value.strip().lower()
        if text in CURRENCY_VALUES:
            return text
    return CURRENT


def effective(frontmatter: Mapping[str, Any] | None) -> tuple[str, date | None]:
    """``(currency, as_of)`` for a note's frontmatter. Never raises on bad input."""
    if not isinstance(frontmatter, Mapping):
        return CURRENT, None
    return (
        _standing(frontmatter.get(CURRENCY_FIELD)),
        _as_date(frontmatter.get(AS_OF_FIELD)),
    )


def countable(frontmatter: Mapping[str, Any] | None) -> bool:
    """False only for a ``superseded`` or ``retracted`` note."""
    return effective(frontmatter)[0] in _COUNTABLE


def is_due(
    frontmatter: Mapping[str, Any] | None,
    review_after_days: int | None,
    today: date,
) -> bool:
    """True when the note is past its review interval.

    Needs an interval, a reviewable standing (``emerging``, ``current`` or
    ``declining``) and a parseable ``as_of`` older than the interval.
    """
    if review_after_days is None or isinstance(review_after_days, bool):
        return False
    if not isinstance(review_after_days, int) or review_after_days <= 0:
        return False
    standing, as_of = effective(frontmatter)
    if standing not in _REVIEWABLE or as_of is None:
        return False
    return as_of < today - timedelta(days=review_after_days)
