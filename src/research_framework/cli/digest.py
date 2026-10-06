"""``vault digest`` CLI verb (spec 035)."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from ..pipeline.digest import DateRange, run_digest
from ..pipeline.digest.scope import (
    build_scope,
    clamp_since,
    parse_iso_date,
    resolve_last_period,
)


class SinceError(ValueError):
    """``--since`` is not a date this verb can use.

    Spec 077 D6/T005: a malformed ``--since`` and a valid future date both
    raised a bare ``ValueError``, and the caller printed "No cycles in scope"
    and exited 1 — the same words a legitimately empty range prints on stdout
    with exit 0. Three different outcomes, one message. This type carries the
    operator's own input so the message can name it.
    """

    def __init__(self, value: str, reason: str) -> None:
        super().__init__(reason)
        self.value = value
        self.reason = reason


def _today() -> date:
    """Today on the clock the cycles are bucketed by: UTC (`_cycle_in_range`)."""
    return datetime.now(UTC).date()


def _parse_args_range(args: argparse.Namespace) -> DateRange:
    today = _today()
    if getattr(args, "last_week", False):
        return resolve_last_period("last-week", today=today)
    if getattr(args, "last_month", False):
        return resolve_last_period("last-month", today=today)
    if getattr(args, "last_quarter", False):
        return resolve_last_period("last-quarter", today=today)
    since_raw = getattr(args, "since", None)
    if since_raw:
        raw = str(since_raw)
        try:
            start = parse_iso_date(raw)
        except ValueError as exc:
            raise SinceError(raw, f"not an ISO date (YYYY-MM-DD): {exc}") from exc
        if start > today:
            raise SinceError(raw, f"is in the future; today is {today.isoformat()}")
        return DateRange(start=start, end=today)
    return resolve_last_period("last-week", today=today)


def cmd_digest(args: argparse.Namespace) -> int:
    vault = getattr(args, "vault", None)
    if vault is None:
        print("error: --vault is required", file=sys.stderr)
        return 2
    vault_dir = Path(vault).expanduser().resolve()
    if not vault_dir.is_dir():
        print(f"error: vault not found: {vault_dir}", file=sys.stderr)
        return 2

    try:
        date_range = _parse_args_range(args)
    except SinceError as exc:
        # 2, not 1: the operator typed something this verb cannot use, which
        # is the usage class in the 077 exit-code model. The message names the
        # flag AND the value, which the old one did neither of.
        print(f"error: --since {exc.value!r} {exc.reason}", file=sys.stderr)
        return 2

    date_range = DateRange(
        start=clamp_since(vault_dir, date_range.start),
        end=date_range.end,
    )
    if not build_scope(vault_dir, date_range).cycles:
        # A legitimately empty range is a RESULT, not an error: stdout, exit 0.
        print(
            f"No cycles in scope ({date_range.start.isoformat()} to "
            f"{date_range.end.isoformat()})"
        )
        return 0

    output = getattr(args, "output", None)
    output_path = Path(output).expanduser().resolve() if output else None
    result = run_digest(
        vault_dir,
        date_range=date_range,
        output_path=output_path,
        rendered_at=datetime.now(UTC),
    )
    if result.output_path:
        print(result.output_path)
    return result.exit_code


__all__ = ["SinceError", "cmd_digest"]
