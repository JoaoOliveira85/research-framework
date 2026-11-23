"""Outside-in discovery: scope areas, their rotation and the ledger (spec 088).

Each cycle the scout is handed a few of the spec's scope areas, least recently
checked first, and asked what is new in them without starting from the vault's
own note titles. This module holds the deterministic pieces: which lines of the
spec are areas, which areas a cycle gets, and the ledger that remembers what was
checked. A scope area that was checked and had nothing new is recorded as such,
so "checked, nothing found" differs from "never checked".

The ledger lives at :func:`state_layout.discovery_ledger_path`. Per-cycle records
are the source of truth: the per-area figures are recomputed from them on every
write, so recording the same cycle twice replaces its record and nothing is
counted twice.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..spec.schema import SpecConfig
from . import state_layout
from .atomic_write import write_json

SCHEMA_VERSION = 1

Ledger = dict[str, Any]


class DiscoveryLedgerError(RuntimeError):
    """The ledger file exists and cannot be read as a ledger."""

    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"discovery ledger {path} is unreadable: {reason}")


def scope_areas(spec: SpecConfig) -> list[str]:
    """The spec's scope lines: stripped, in spec order, first duplicate kept.

    A simple-format spec's ``scope.include`` is expanded into
    ``scope.boundaries``, so one source serves both formats.
    """
    seen: set[str] = set()
    areas: list[str] = []
    for line in spec.scope.boundaries:
        text = str(line).strip()
        if text and text not in seen:
            seen.add(text)
            areas.append(text)
    return areas


def empty_ledger() -> Ledger:
    return {"schema_version": SCHEMA_VERSION, "areas": {}, "cycles": []}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def load_ledger(vault_dir: Path) -> Ledger:
    """Read the ledger; a missing file is an empty one, a broken one raises."""
    path = state_layout.discovery_ledger_path(vault_dir)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return empty_ledger()
    except OSError as exc:
        raise DiscoveryLedgerError(path, str(exc)) from exc
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DiscoveryLedgerError(path, f"not valid JSON ({exc})") from exc
    if not isinstance(doc, dict) or doc.get("schema_version") != SCHEMA_VERSION:
        raise DiscoveryLedgerError(path, f"expected schema_version {SCHEMA_VERSION}")
    areas, cycles = doc.get("areas"), doc.get("cycles")
    if not isinstance(areas, dict) or not all(
        isinstance(row, dict) for row in areas.values()
    ):
        raise DiscoveryLedgerError(path, "'areas' is not an object of objects")
    if not isinstance(cycles, list) or not all(
        isinstance(rec, dict) and _is_int(rec.get("cycle")) for rec in cycles
    ):
        raise DiscoveryLedgerError(path, "'cycles' is not a list of cycle records")
    return doc


def _area_rows(cycles: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Recompute every area's figures from the per-cycle records."""
    rows: dict[str, dict[str, Any]] = {}
    for record in sorted(cycles, key=lambda rec: rec["cycle"]):
        reported: dict[str, int] = {}
        for item in record.get("reported") or []:
            area = item.get("area")
            if isinstance(area, str):
                found = item.get("found")
                reported[area] = reported.get(area, 0) + (
                    found if _is_int(found) and found > 0 else 0
                )
        for area in record.get("assigned") or []:
            row = rows.setdefault(
                area,
                {
                    "last_checked_cycle": None,
                    "times_checked": 0,
                    "found_total": 0,
                    "last_found_cycle": None,
                    "times_assigned_not_reported": 0,
                },
            )
            if area not in reported:
                row["times_assigned_not_reported"] += 1
                continue
            row["last_checked_cycle"] = record["cycle"]
            row["times_checked"] += 1
            row["found_total"] += reported[area]
            if reported[area] > 0:
                row["last_found_cycle"] = record["cycle"]
    return rows


def record_cycle(
    vault_dir: Path,
    *,
    cycle: int,
    assigned: list[str],
    reported: list[dict[str, Any]],
    kept: int,
    rerouted: int,
    dropped: list[dict[str, str]],
) -> Ledger:
    """Record what ``cycle`` assigned and what the scout reported; atomic.

    Recording the same cycle again replaces that cycle's record. An assigned
    area absent from ``reported`` counts as assigned-not-reported and is not
    marked checked; one reported with ``found: 0`` is checked.
    """
    ledger = load_ledger(vault_dir)
    record = {
        "cycle": cycle,
        "assigned": list(assigned),
        "reported": [dict(item) for item in reported],
        "kept": kept,
        "rerouted": rerouted,
        "dropped": [dict(item) for item in dropped],
    }
    cycles = [rec for rec in ledger["cycles"] if rec["cycle"] != cycle]
    cycles.append(record)
    cycles.sort(key=lambda rec: rec["cycle"])
    # Rows for areas no cycle assigned cannot exist; rows that earlier cycles
    # created are recomputed from those cycles, so none is ever dropped.
    doc: Ledger = {
        "schema_version": SCHEMA_VERSION,
        "areas": _area_rows(cycles),
        "cycles": cycles,
    }
    write_json(state_layout.discovery_ledger_path(vault_dir), doc)
    return doc


def choose_areas(ledger: Ledger, areas: list[str], n: int) -> list[str]:
    """Up to ``n`` of ``areas``: never checked first, then oldest check.

    Ties keep spec order. An area the spec no longer lists is not offered (its
    ledger row stays).
    """
    rows = ledger.get("areas", {})

    def last_checked(area: str) -> int | None:
        value = rows.get(area, {}).get("last_checked_cycle")
        return value if _is_int(value) else None

    ranked = sorted(
        enumerate(areas),
        key=lambda pair: (
            last_checked(pair[1]) is not None,
            last_checked(pair[1]) or 0,
            pair[0],
        ),
    )
    return [area for _, area in ranked[: max(n, 0)]]
