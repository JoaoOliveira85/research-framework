"""Top Discovered Sources section builder (spec 040 FR-002)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research_framework.pipeline.digest.scope import CycleScope, DateRange


@dataclass(frozen=True)
class TopSourceRow:
    name: str
    summary: str
    signal: str
    refs: int
    notes: int
    last_cycle: int


def _try_connect(db_path: Path) -> sqlite3.Connection | None:
    try:
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0)
    except sqlite3.Error:
        return None


def _source_summary(conn: sqlite3.Connection, name: str) -> str:
    row = conn.execute(
        "SELECT url, type FROM sources WHERE name=?",
        (name,),
    ).fetchone()
    if not row:
        return "Newly discovered source"
    url, stype = row
    if url:
        return f"{stype or 'source'} feed at {url}"
    return f"{stype or 'source'} module source"


def build_top_discovered_sources(
    vault_dir: Path,
    cycles: list[CycleScope],
    date_range: DateRange,
) -> list[dict[str, Any]]:
    del date_range
    if not cycles:
        return []
    db_path = vault_dir / "_pipeline" / "sources.db"
    if not db_path.is_file():
        return []
    conn = _try_connect(db_path)
    if conn is None:
        return []
    cycle_nums = sorted(c.number for c in cycles)
    in_scope = set(cycle_nums)
    try:
        candidates: list[TopSourceRow] = []
        for name, first_seen in conn.execute(
            "SELECT name, first_seen_cycle FROM sources ORDER BY name"
        ):
            first = int(first_seen or 0)
            if first not in in_scope:
                continue
            refs = 0
            notes = 0
            last_cycle = first
            for num in cycle_nums:
                row = conn.execute(
                    "SELECT notes_generated, notes_referencing FROM source_cycles "
                    "WHERE name=? AND cycle=?",
                    (name, num),
                ).fetchone()
                gen = int(row[0]) if row else 0
                ref = int(row[1]) if row else 0
                refs += ref
                notes += gen
                if gen > 0 or ref > 0:
                    last_cycle = max(last_cycle, num)
            summary = _source_summary(conn, str(name))
            signal = f"{refs} refs / {notes} notes / cycle {last_cycle}"
            candidates.append(
                TopSourceRow(
                    name=str(name),
                    summary=summary,
                    signal=signal,
                    refs=refs,
                    notes=notes,
                    last_cycle=last_cycle,
                )
            )
    finally:
        conn.close()
    candidates.sort(key=lambda row: (-row.refs, -row.notes, -row.last_cycle, row.name))
    return [
        {
            "name": row.name,
            "summary": row.summary,
            "signal": row.signal,
        }
        for row in candidates[:5]
    ]


__all__ = ["TopSourceRow", "build_top_discovered_sources"]
