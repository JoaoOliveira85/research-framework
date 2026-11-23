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


def _parse_row(path: Path, raw: Any) -> CycleRow:
    if not isinstance(raw, dict):
        raise CycleLedgerError(path, f"row is not an object: {raw!r}")
    cycle = raw.get("cycle")
    finished_at = raw.get("finished_at")
    cost = raw.get("cost_usd")
    missing = raw.get("sidecars_missing")
    if (
        not isinstance(cycle, int)
        or isinstance(cycle, bool)
        or cycle < 1
        or not isinstance(finished_at, str)
        or not isinstance(cost, int | float)
        or isinstance(cost, bool)
        or not isinstance(missing, bool)
    ):
        raise CycleLedgerError(path, f"malformed row: {raw!r}")
    return CycleRow(cycle, finished_at, float(cost), missing)


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


def _write(vault_dir: Path, rows: list[CycleRow]) -> None:
    ordered = sorted(rows, key=lambda row: row.cycle)
    write_json(
        state_layout.cycle_ledger_path(vault_dir),
        {"schema_version": SCHEMA_VERSION, "cycles": [asdict(r) for r in ordered]},
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
    """``max(ledger, scan)``, or ``None`` when neither knows a cycle."""
    known = [row.cycle for row in load(vault_dir)] + scan_completed_cycles(vault_dir)
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
        parsed = (
            _parse_ts(row.finished_at)
            if row is not None
            else scan_finished_at(vault_dir, prior)
        )
        if parsed is not None:
            return parsed
    return None


def backfill_from_cycles(vault_dir: Path) -> int:
    """Add a row for every completed cycle under ``cycles/`` the ledger lacks.

    Cost and timestamp use the derivations the readers used before the ledger
    existed: the sum of the cycle's sidecars (``0.0`` and ``sidecars_missing``
    when it has none), and the research/scout JSON ``timestamp`` (the quality
    report's mtime when neither carries one). Aborted cycles get no row: a row
    would make the next cycle number skip a cycle that must be retried.
    Returns how many rows were added.
    """
    rows = load(vault_dir)
    have = {row.cycle for row in rows}
    added = 0
    for cycle in scan_completed_cycles(vault_dir):
        if cycle in have:
            continue
        cost = sum_sidecar_costs(vault_dir, cycle)
        when = scan_finished_at(vault_dir, cycle)
        if when is None:
            report = _cycles_dir(vault_dir) / f"cycle-{cycle:03d}-quality-report.json"
            when = datetime.fromtimestamp(report.stat().st_mtime, UTC)
        rows.append(
            CycleRow(
                cycle, when.astimezone(UTC).strftime(_TS_FMT), cost or 0.0, cost is None
            )
        )
        added += 1
    if added:
        _write(vault_dir, rows)
    return added
