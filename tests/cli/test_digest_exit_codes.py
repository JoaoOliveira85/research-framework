"""``digest``'s exit codes say which of three things happened (spec 077 T005).

D6: a malformed `--since` (an operator error) and a valid future date both
raised the same exception, and the handler printed **"No cycles in scope"** to
stderr and exited 1 — which is also the wording a legitimately empty range
prints, on stdout, with exit 0. Three outcomes, one message, two codes that did
not line up with any of them.

The 077 model (FR-012) has a code for each: 0 pass/continue, 1
fail/terminate, 2 usage/abort.
"""

from __future__ import annotations

import argparse
import os
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from research_framework.cli.digest import SinceError, _parse_args_range, cmd_digest
from research_framework.pipeline.digest.scope import resolve_last_period


def _args(**kwargs: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "vault": None,
        "since": None,
        "last_week": False,
        "last_month": False,
        "last_quarter": False,
        "output": None,
    }
    base.update(kwargs)
    return argparse.Namespace(**base)


def _empty_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "_pipeline" / "cycles").mkdir(parents=True)
    return vault


def test_a_malformed_since_is_a_usage_error_naming_the_flag_and_the_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cmd_digest(_args(vault=str(_empty_vault(tmp_path)), since="last-tuesday"))

    assert rc == 2
    err = capsys.readouterr().err
    assert "--since" in err
    assert "last-tuesday" in err
    assert "No cycles in scope" not in err, (
        "the empty-range wording must not stand in for a parse failure"
    )


def test_a_future_since_is_a_usage_error_that_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    future = (date.today() + timedelta(days=30)).isoformat()

    rc = cmd_digest(_args(vault=str(_empty_vault(tmp_path)), since=future))

    assert rc == 2
    err = capsys.readouterr().err
    assert future in err
    assert "future" in err


def test_an_empty_range_is_a_result_not_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 0, on stdout, and it names the window it looked at — otherwise the
    operator cannot tell whether the range was wrong or the vault was quiet."""
    rc = cmd_digest(_args(vault=str(_empty_vault(tmp_path)), last_week=True))

    captured = capsys.readouterr()
    assert rc == 0
    assert "No cycles in scope" in captured.out
    assert captured.err == ""
    assert "to" in captured.out


def test_a_missing_vault_is_still_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cmd_digest(_args(vault=str(tmp_path / "nope")))

    assert rc == 2
    assert "vault not found" in capsys.readouterr().err


def test_since_error_carries_the_operators_input() -> None:
    """The type exists so the message can quote what was typed; a bare
    ``ValueError`` could not, which is how "No cycles in scope" ended up
    standing in for a parse failure."""
    with pytest.raises(SinceError) as excinfo:
        _parse_args_range(_args(since="2026-13-45"))

    assert excinfo.value.value == "2026-13-45"
    assert excinfo.value.reason


@pytest.fixture
def _local_date_is_not_the_utc_date() -> Iterator[None]:
    """Put the process in a zone whose calendar date is not UTC's right now.

    POSIX ``TZ`` strings, so no tz database is needed: ``XXX+12`` is UTC-12
    (a day behind UTC before 12:00 UTC), ``XXX-14`` is UTC+14 (a day ahead
    from 10:00 UTC).
    """
    old = os.environ.get("TZ")
    os.environ["TZ"] = "XXX+12" if datetime.now(UTC).hour < 12 else "XXX-14"
    time.tzset()
    try:
        assert date.today() != datetime.now(UTC).date(), "precondition: TZ applied"
        yield
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()


@pytest.mark.usefixtures("_local_date_is_not_the_utc_date")
def test_the_range_ends_on_the_utc_date_the_cycles_are_bucketed_by() -> None:
    """Cycles fall in a range by their UTC finish date, so "today" is UTC's.

    Anchored on the local date, a cycle that had just finished was outside
    ``--last-week`` whenever the local date was behind UTC's, and ``--since``
    with today's UTC date was refused as a future date.
    """
    utc_today = datetime.now(UTC).date()

    assert _parse_args_range(_args(last_week=True)).end == utc_today
    assert _parse_args_range(_args(since=utc_today.isoformat())).end == utc_today
    assert resolve_last_period("last-week").end == utc_today
