"""Top Discovered Sources ranking tests (spec 040 T007)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from research_framework.pipeline.digest.scope import DateRange, enumerate_cycles
from research_framework.pipeline.reports.top_sources import build_top_discovered_sources

from .helpers import FIXTURE_RANGE

pytest_plugins = ["tests.pipeline.reports.helpers"]


def _tiebreaker_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    db = vault / "_pipeline" / "sources.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE sources (
            name TEXT PRIMARY KEY, type TEXT, role TEXT, url TEXT,
            first_seen_cycle INTEGER, locked INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active', consecutive_empty_cycles INTEGER DEFAULT 0
        );
        CREATE TABLE source_cycles (
            name TEXT, cycle INTEGER,
            notes_generated INTEGER DEFAULT 0,
            topics_covered INTEGER DEFAULT 0,
            tags_generated INTEGER DEFAULT 0,
            notes_referencing INTEGER DEFAULT 0,
            PRIMARY KEY (name, cycle)
        );
        """
    )
    for name in ("alpha-feed", "beta-feed"):
        conn.execute(
            "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?)",
            (name, "rss", "domain", f"https://{name}.example/rss", 2, 0, "active", 0),
        )
        conn.executemany(
            "INSERT INTO source_cycles VALUES (?,?,?,?,?,?)",
            [(name, 2, 1, 0, 0, 5), (name, 3, 0, 0, 0, 2)],
        )
    conn.commit()
    conn.close()
    for num in (1, 2, 3):
        qr = vault / "_pipeline" / "cycles" / f"cycle-{num:03d}-quality-report.json"
        qr.parent.mkdir(parents=True, exist_ok=True)
        qr.write_text(
            f'{{"cycle_finished_at":"2026-06-0{num}T12:00:00Z"}}\n',
            encoding="utf-8",
        )
    return vault


def test_top_sources_name_ascending_tiebreaker(tmp_path: Path) -> None:
    vault = _tiebreaker_vault(tmp_path)
    cycles = enumerate_cycles(vault, FIXTURE_RANGE)
    rows = build_top_discovered_sources(vault, cycles, FIXTURE_RANGE)
    assert [row["name"] for row in rows[:2]] == ["alpha-feed", "beta-feed"]


def test_top_sources_fewer_than_five(reports_vault) -> None:
    cycles = enumerate_cycles(reports_vault, FIXTURE_RANGE)
    rows = build_top_discovered_sources(reports_vault, cycles, FIXTURE_RANGE)
    assert 0 < len(rows) <= 5


def test_top_sources_empty_when_no_db(tmp_path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "_pipeline").mkdir()
    rows = build_top_discovered_sources(
        vault, [], DateRange(start=FIXTURE_RANGE.start, end=FIXTURE_RANGE.end)
    )
    assert rows == []


def test_top_sources_zero_rows_message_in_report(reports_vault) -> None:
    db = reports_vault / "_pipeline" / "sources.db"
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM sources")
    conn.commit()
    conn.close()
    from .helpers import render_fixture

    markdown = render_fixture(reports_vault)
    assert "## Top Discovered Sources" in markdown
    assert "No data in scope." in markdown
