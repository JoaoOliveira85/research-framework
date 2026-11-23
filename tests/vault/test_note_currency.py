"""Tier 1: the note-currency declaration (spec 087 FR-006..FR-009)."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from research_framework.vault import note_currency as nc

TODAY = date(2026, 11, 23)
REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "fm",
    [
        {},
        {"currency": "", "as_of": ""},
        {"currency": None, "as_of": None},
        {"title": "x"},
    ],
)
def test_missing_fields_read_as_current_and_never_due(fm: dict) -> None:
    assert nc.effective(fm) == ("current", None)
    assert nc.countable(fm) is True
    assert nc.is_due(fm, 1, TODAY) is False


@pytest.mark.parametrize("bad", [None, "text", 7, [], ["as_of"]])
def test_effective_never_raises_on_bad_input(bad: object) -> None:
    assert nc.effective(bad) == ("current", None)  # type: ignore[arg-type]
    assert nc.countable(bad) is True  # type: ignore[arg-type]
    assert nc.is_due(bad, 30, TODAY) is False  # type: ignore[arg-type]


def test_as_of_accepts_a_date_a_datetime_and_an_iso_string() -> None:
    expected = date(2026, 1, 5)
    assert nc.effective({"as_of": expected})[1] == expected
    assert nc.effective({"as_of": datetime(2026, 1, 5, 9, 30)})[1] == expected
    assert nc.effective({"as_of": "2026-01-05"})[1] == expected


@pytest.mark.parametrize("value", nc.CURRENCY_VALUES)
def test_only_superseded_and_retracted_are_uncountable(value: str) -> None:
    assert nc.countable({"currency": value}) is (
        value not in ("superseded", "retracted")
    )


def test_the_five_values() -> None:
    assert nc.CURRENCY_VALUES == (
        "emerging",
        "current",
        "declining",
        "superseded",
        "retracted",
    )


@pytest.mark.parametrize(
    ("interval", "as_of", "currency", "due"),
    [
        (None, "2020-01-01", "current", False),  # no interval
        (30, "2026-11-01", "current", False),  # inside the interval
        (30, "2026-10-24", "current", False),  # exactly on the boundary
        (30, "2026-10-23", "current", True),  # one day past
        (30, "2020-01-01", "emerging", True),
        (30, "2020-01-01", "current", True),
        (30, "2020-01-01", "declining", True),
        (30, "2020-01-01", "superseded", False),
        (30, "2020-01-01", "retracted", False),
        (30, "2020-01-01", None, True),  # unset standing reads current
        (30, "not-a-date", "current", False),  # malformed: never due, no raise
        (30, "2026-13-45", "current", False),
        (30, "", "current", False),
        (30, None, "current", False),
        (0, "2020-01-01", "current", False),  # a non-positive interval is no interval
        (-5, "2020-01-01", "current", False),
        (True, "2020-01-01", "current", False),
    ],
)
def test_due_needs_an_interval_a_live_standing_and_an_old_as_of(
    interval: object, as_of: object, currency: object, due: bool
) -> None:
    fm: dict = {"as_of": as_of}
    if currency is not None:
        fm["currency"] = currency
    assert nc.is_due(fm, interval, TODAY) is due  # type: ignore[arg-type]


#: ``superseded_by`` here names a framework FILE that a newer one replaced
#: (the vault-migration path map and its inventory report), which has nothing
#: to do with the note frontmatter field. It is an output key of
#: ``cli_inventory`` and left alone.
_UNRELATED_SUPERSEDED_BY = {
    "src/research_framework/cli_inventory.py",
    "src/research_framework/migration/superseded_paths.py",
}


def test_every_reader_takes_the_field_names_from_the_module() -> None:
    """Tier 2: ``superseded_by`` is spelled in exactly one source file."""
    own = (REPO / "src/research_framework/vault/note_currency.py").resolve()
    offenders = [
        str(path.relative_to(REPO))
        for root in ("src", "scripts")
        for path in (REPO / root).rglob("*.py")
        if path.resolve() != own and "superseded_by" in path.read_text("utf-8")
    ]
    offenders = [o for o in offenders if o not in _UNRELATED_SUPERSEDED_BY]
    assert offenders == []
