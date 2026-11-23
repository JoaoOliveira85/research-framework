"""Spec 083 T005 — ``sources.db`` is tracked as a file, so its WAL must be empty
before a commit stages it (plan § 4)."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from research_framework.pipeline import source_manager
from research_framework.pipeline import state_layout as L


def test_checkpoint_leaves_an_empty_wal(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    # A connection that stays open is what keeps rows in the WAL after commit.
    live = source_manager._connect(vault)
    with live:
        live.execute(
            "INSERT INTO sources(name, type, role, url, locked, status) "
            "VALUES ('Kept', 'external', 'intent', '', 0, 'active')"
        )
    wal = Path(f"{L.sources_db_path(vault)}-wal")
    assert wal.is_file() and wal.stat().st_size > 0

    source_manager.checkpoint(vault)

    assert wal.stat().st_size == 0
    bare = tmp_path / "bare" / L.sources_db_path(vault).name
    bare.parent.mkdir()
    shutil.copy(L.sources_db_path(vault), bare)  # no sidecars travel with it
    with sqlite3.connect(bare) as conn:
        assert conn.execute("SELECT name FROM sources").fetchall() == [("Kept",)]
    live.close()


def test_checkpoint_on_a_vault_without_a_database_is_a_no_op(tmp_path: Path) -> None:
    source_manager.checkpoint(tmp_path)
    assert not L.sources_db_path(tmp_path).exists()
