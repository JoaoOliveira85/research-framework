"""The cycle ledger: three cross-cycle facts kept as state (spec 083 FR-006).

The next cycle number, the lifetime spend that ``--max-usd`` caps and the
completion time of the last cycle used to be recomputed by scanning
``_pipeline/cycles/``, which git ignores. One row per closed cycle now lives in
the ledger file (path from :mod:`state_layout`), so a ``git clean`` of the
scratch tree no longer resets them.

Rule (plan section 3): the ledger is authoritative for the cycles it lists; the
``cycles/`` scan supplies only cycles the ledger lacks (a cycle that crashed
before its row was written, or a vault not yet backfilled). A missing ledger is
an empty one; an unparseable one raises :class:`CycleLedgerError` naming the
file, and no reader falls back to the scan when it does.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import state_layout
from .atomic_write import write_json

_LOG = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_QUALITY_REPORT_RX = re.compile(r"^cycle-(\d+)-quality-report\.json$")
_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"


class CycleLedgerError(RuntimeError):
    """The ledger file exists and cannot be read as a ledger."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"cycle ledger {path} is unreadable: {reason}")


@dataclass(frozen=True)
class CycleRow:
    cycle: int
    finished_at: str
    cost_usd: float
    sidecars_missing: bool
    aborted: bool = False
    """The cycle was abandoned. Its spend counts toward the lifetime cap, but it
    is not a completed cycle: numbering and the cadence ignore it, so the cycle
    is retried and its completed row replaces this one."""


def _parse_row(path: Path, raw: Any) -> CycleRow:
    if not isinstance(raw, dict):
        raise CycleLedgerError(path, f"row is not an object: {raw!r}")
    cycle = raw.get("cycle")
    finished_at = raw.get("finished_at")
    cost = raw.get("cost_usd")
    missing = raw.get("sidecars_missing")
    aborted = raw.get("aborted", False)
    if (
        not isinstance(cycle, int)
        or isinstance(cycle, bool)
        or cycle < 1
        or not isinstance(finished_at, str)
        or not isinstance(cost, int | float)
        or isinstance(cost, bool)
        or not isinstance(missing, bool)
        or not isinstance(aborted, bool)
    ):
        raise CycleLedgerError(path, f"malformed row: {raw!r}")
    return CycleRow(cycle, finished_at, float(cost), missing, aborted)


def load(vault_dir: Path) -> list[CycleRow]:
    """Return the ledger's rows by ascending cycle; a missing file is empty."""
    path = state_layout.cycle_ledger_path(vault_dir)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise CycleLedgerError(path, str(exc)) from exc
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CycleLedgerError(path, f"not valid JSON ({exc})") from exc
    if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA_VERSION:
        raise CycleLedgerError(path, f"expected schema_version {SCHEMA_VERSION}")
    rows = doc.get("cycles")
    if not isinstance(rows, list):
        raise CycleLedgerError(path, "'cycles' is not a list")
    by_cycle = {row.cycle: row for row in (_parse_row(path, r) for r in rows)}
    return [by_cycle[n] for n in sorted(by_cycle)]


def _as_json(row: CycleRow) -> dict[str, Any]:
    doc = asdict(row)
    if not row.aborted:
        del doc["aborted"]  # absent means completed: ordinary rows keep four keys
    return doc


def _write(vault_dir: Path, rows: list[CycleRow]) -> None:
    ordered = sorted(rows, key=lambda row: row.cycle)
    write_json(
        state_layout.cycle_ledger_path(vault_dir),
        {"schema_version": SCHEMA_VERSION, "cycles": [_as_json(r) for r in ordered]},
    )


def append_cycle(
    vault_dir: Path,
    *,
    cycle: int,
    cost_usd: float,
    sidecars_missing: bool,
    finished_at: datetime | None = None,
) -> CycleRow:
    """Record that ``cycle`` closed; the same cycle again replaces its row."""
    when = (finished_at or datetime.now(UTC)).astimezone(UTC)
    row = CycleRow(cycle, when.strftime(_TS_FMT), float(cost_usd), sidecars_missing)
    rows = [r for r in load(vault_dir) if r.cycle != cycle]
    rows.append(row)
    _write(vault_dir, rows)
    return row


def close_cycle(vault_dir: Path, cycle: int) -> CycleRow:
    """Append the row for ``cycle`` from its agent-call sidecars, as of now."""
    cost = sum_sidecar_costs(vault_dir, cycle)
    return append_cycle(
        vault_dir,
        cycle=cycle,
        cost_usd=cost or 0.0,
        sidecars_missing=cost is None,
    )


def record_aborted(vault_dir: Path, cycle: int) -> CycleRow | None:
    """Keep the spend of an abandoned cycle (spec 083 SC-001).

    Only a cycle with sidecars has spend to keep; otherwise nothing is written.
    A later :func:`close_cycle` of the same cycle replaces this row.
    """
    cost = sum_sidecar_costs(vault_dir, cycle)
    if cost is None:
        return None
    when = datetime.now(UTC)
    row = CycleRow(cycle, when.strftime(_TS_FMT), cost, False, aborted=True)
    rows = [r for r in load(vault_dir) if r.cycle != cycle]
    rows.append(row)
    _write(vault_dir, rows)
    return row


def _cycles_dir(vault_dir: Path) -> Path:
    return vault_dir / "_pipeline" / "cycles"


def cycle_aborted(cycles_dir: Path, cycle: int) -> bool:
    """True when ``cycle`` carries a spec-070 F10 abort marker."""
    return (cycles_dir / f"cycle-{cycle:03d}-aborted.json").is_file()


def scan_completed_cycles(vault_dir: Path) -> list[int]:
    """Cycles with a quality report and no abort marker, ascending."""
    cycles_dir = _cycles_dir(vault_dir)
    if not cycles_dir.is_dir():
        return []
    found: set[int] = set()
    for child in cycles_dir.iterdir():
        if not (child.is_file() and child.suffix == ".json"):
            continue
        m = _QUALITY_REPORT_RX.match(child.name)
        if m is None:
            continue
        n = int(m.group(1))
        if n > 0 and not cycle_aborted(cycles_dir, n):
            found.add(n)
    return sorted(found)


def sum_sidecar_costs(vault_dir: Path, cycle_num: int) -> float | None:
    """Sum ``cost_usd`` from a cycle's ``agent-calls/*.json`` sidecars (spec 028).

    ``None`` when the cycle has no sidecars to sum.
    """
    agent_calls = _cycles_dir(vault_dir) / f"cycle-{cycle_num:03d}" / "agent-calls"
    if not agent_calls.is_dir():
        return None
    sidecars = sorted(agent_calls.glob("*.json"))
    if not sidecars:
        return None
    total = 0.0
    for path in sidecars:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            _LOG.warning(f"WARN: cost sidecar {path} unreadable: {e}")
            continue
        total += float(data.get("cost_usd") or 0.0)
    return total


def _parse_ts(ts: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def scan_finished_at(vault_dir: Path, cycle: int) -> datetime | None:
    """``timestamp`` of the cycle's research JSON, else its scout JSON."""
    cycles_dir = _cycles_dir(vault_dir)
    cycle_3 = f"{cycle:03d}"
    for fname in (f"cycle-{cycle_3}-research.json", f"cycle-{cycle_3}-scout.json"):
        path = cycles_dir / fname
        if not path.is_file():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        ts = doc.get("timestamp") if isinstance(doc, dict) else None
        if not isinstance(ts, str):
            continue
        parsed = _parse_ts(ts)
        if parsed is not None:
            return parsed
    return None


def highest_completed_cycle(vault_dir: Path) -> int | None:
    """``max(ledger, scan)``, or ``None`` when neither knows a cycle.

    Aborted ledger rows do not count, and the scan does not second-guess a
    cycle the ledger lists.
    """
    rows = load(vault_dir)
    listed = {row.cycle for row in rows}
    known = [row.cycle for row in rows if not row.aborted] + [
        n for n in scan_completed_cycles(vault_dir) if n not in listed
    ]
    return max(known) if known else None


def lifetime_cost(vault_dir: Path, *, up_to: int) -> float:
    """Spend over cycles ``1..up_to``: ledger rows, plus the scan for the rest."""
    in_ledger = {row.cycle: row for row in load(vault_dir)}
    total = 0.0
    for cycle in range(1, up_to + 1):
        row = in_ledger.get(cycle)
        if row is not None:
            total += row.cost_usd
            continue
        scanned = sum_sidecar_costs(vault_dir, cycle)
        if scanned is not None:
            total += scanned
    return total


def last_finished_at(vault_dir: Path, current_cycle: int) -> datetime | None:
    """Completion time of the highest cycle below ``current_cycle`` that has one."""
    in_ledger = {row.cycle: row for row in load(vault_dir)}
    for prior in range(current_cycle - 1, 0, -1):
        row = in_ledger.get(prior)
        if row is not None and row.aborted:
            continue
        parsed = (
            _parse_ts(row.finished_at)
            if row is not None
            else scan_finished_at(vault_dir, prior)
        )
        if parsed is not None:
            return parsed
    return None


def _backfill_rows(vault_dir: Path) -> list[CycleRow]:
    """The rows :func:`backfill_from_cycles` would add."""
    have = {row.cycle for row in load(vault_dir)}
    cycles_dir = _cycles_dir(vault_dir)
    new: list[CycleRow] = []
    for cycle in scan_completed_cycles(vault_dir):
        if cycle in have:
            continue
        cost = sum_sidecar_costs(vault_dir, cycle)
        when = scan_finished_at(vault_dir, cycle)
        if when is None:
            report = cycles_dir / f"cycle-{cycle:03d}-quality-report.json"
            when = datetime.fromtimestamp(report.stat().st_mtime, UTC)
        new.append(
            CycleRow(
                cycle, when.astimezone(UTC).strftime(_TS_FMT), cost or 0.0, cost is None
            )
        )
        have.add(cycle)
    # Abandoned cycles keep their spend (they get no completed row, so they are
    # retried): any marked-aborted cycle that has sidecars.
    if cycles_dir.is_dir():
        for marker in sorted(cycles_dir.glob("cycle-*-aborted.json")):
            m = re.fullmatch(r"cycle-(\d+)-aborted\.json", marker.name)
            if m is None or int(m.group(1)) in have or int(m.group(1)) < 1:
                continue
            cycle = int(m.group(1))
            cost = sum_sidecar_costs(vault_dir, cycle)
            if cost is None:
                continue
            when = datetime.fromtimestamp(marker.stat().st_mtime, UTC)
            new.append(
                CycleRow(cycle, when.strftime(_TS_FMT), cost, False, aborted=True)
            )
            have.add(cycle)
    return new


def pending_backfill(vault_dir: Path) -> int:
    """How many rows :func:`backfill_from_cycles` would add; writes nothing."""
    return len(_backfill_rows(vault_dir))


def backfill_from_cycles(vault_dir: Path) -> int:
    """Add the rows the ledger lacks for what ``cycles/`` holds (spec 083 FR-007).

    A completed cycle (quality report, no abort marker) gets a normal row. Cost
    and timestamp use the derivations the readers used before the ledger
    existed: the sum of the cycle's sidecars (``0.0`` and ``sidecars_missing``
    when it has none), and the research/scout JSON ``timestamp`` (the quality
    report's mtime when neither carries one). An aborted cycle that has sidecars
    gets an ``aborted`` row, so its spend survives but its number is retried.
    Returns how many rows were added.
    """
    new = _backfill_rows(vault_dir)
    if new:
        _write(vault_dir, [*load(vault_dir), *new])
    return len(new)
