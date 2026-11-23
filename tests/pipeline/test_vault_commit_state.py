"""Spec 083 T009: writers commit what they write under ``_pipeline/state/``."""

from __future__ import annotations

import logging
import sqlite3
import subprocess
from pathlib import Path

import pytest

from research_framework.generator.scaffold import _render_vault_gitignore
from research_framework.pipeline import cycle_ledger, state_layout
from research_framework.pipeline.vault_commit import (
    begin_run,
    commit_command_output,
    commit_cycle,
)

TARGETS = "_pipeline/state/coverage-targets.json"


def _git(vault: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(vault), *args], check=True, capture_output=True, text=True
    ).stdout


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "_pipeline" / "state").mkdir(parents=True)
    _git(tmp_path, "init", "-b", "main", str(vault))
    _git(vault, "config", "user.email", "t@e.com")
    _git(vault, "config", "user.name", "T")
    (vault / ".gitignore").write_text(
        _render_vault_gitignore("data_vault"), encoding="utf-8"
    )
    (vault / TARGETS).write_text('{"cycle_number": 1}\n', encoding="utf-8")
    _git(vault, "add", "-A")
    _git(vault, "commit", "-m", "initial")
    return vault


def test_pending_state_edit_gets_its_own_commit_before_the_run_branch(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    before = _git(vault, "rev-parse", "main").strip()
    (vault / TARGETS).write_text('{"cycle_number": 7}\n', encoding="utf-8")

    ctx = begin_run(vault, kind="research")

    assert ctx is not None
    after = _git(vault, "rev-parse", "main").strip()
    assert after != before
    assert _git(vault, "rev-list", "--count", f"{before}..main").strip() == "1"
    assert _git(vault, "log", "-1", "--format=%s", "main").strip() == (
        "vault: pending state"
    )
    assert _git(vault, "show", "--name-only", "--format=", "main").split() == [TARGETS]
    assert _git(vault, "merge-base", "main", ctx.branch).strip() == after
    assert _git(vault, "rev-parse", ctx.branch).strip() == after


def test_scratch_under_pipeline_is_still_masked(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    before = _git(vault, "rev-parse", "main").strip()
    (vault / "_pipeline" / "cycles").mkdir()
    (vault / "_pipeline" / "cycles" / "x.json").write_text("{}", encoding="utf-8")

    ctx = begin_run(vault, kind="research")

    assert ctx is not None
    assert _git(vault, "rev-parse", "main").strip() == before  # nothing committed
    assert "x.json" not in _git(vault, "ls-files")


def test_scratch_is_not_swept_into_the_pending_state_commit(tmp_path: Path) -> None:
    """Even where scratch is not ignored, only state paths are committed."""
    vault = _make_vault(tmp_path)
    (vault / ".gitignore").write_text("", encoding="utf-8")
    _git(vault, "commit", "-qam", "drop ignore rules")
    (vault / "_pipeline" / "cycles").mkdir()
    (vault / "_pipeline" / "cycles" / "x.json").write_text("{}", encoding="utf-8")
    (vault / TARGETS).write_text('{"cycle_number": 2}\n', encoding="utf-8")

    begin_run(vault, kind="research")

    assert _git(vault, "show", "--name-only", "--format=", "main").split() == [TARGETS]


def test_a_resumed_run_makes_no_pending_state_commit(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    ctx = begin_run(vault, kind="research")
    assert ctx is not None
    main_before = _git(vault, "rev-parse", "main").strip()
    (vault / TARGETS).write_text('{"cycle_number": 9}\n', encoding="utf-8")

    again = begin_run(vault, kind="research", resume=True)

    assert again is not None and again.branch == ctx.branch
    assert _git(vault, "rev-parse", "main").strip() == main_before
    assert _git(vault, "log", "-1", "--format=%s").strip() == "initial"


def test_opted_out_vault_commits_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    vault = _make_vault(tmp_path)
    (vault / "settings.yaml").write_text(
        "vault_commit:\n  enabled: false\n", encoding="utf-8"
    )
    head = _git(vault, "rev-parse", "HEAD").strip()
    (vault / TARGETS).write_text('{"cycle_number": 3}\n', encoding="utf-8")

    with caplog.at_level(logging.INFO, logger="research_framework"):
        assert begin_run(vault, kind="research") is None

    assert _git(vault, "rev-parse", "HEAD").strip() == head
    lines = [r for r in caplog.records if "vault_commit" in r.getMessage()]
    assert len(lines) == 1 and lines[0].levelno == logging.INFO
    assert "not committed" in lines[0].getMessage()


def test_command_commit_carries_state_and_a_checkpointed_database(
    tmp_path: Path,
) -> None:
    vault = _make_vault(tmp_path)
    db = state_layout.sources_db_path(vault)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (x)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    try:
        assert db.with_name(db.name + "-wal").stat().st_size > 0  # rows live in WAL
        result = commit_command_output(vault, command="ask", summary="q")
    finally:
        conn.close()
    assert result.ok and result.sha
    tracked = _git(vault, "ls-files").split()
    assert "_pipeline/state/sources.db" in tracked
    assert not [t for t in tracked if t.endswith(("-wal", "-shm"))]
    # The committed file alone holds the row (WAL was folded in first).
    committed = tmp_path / "committed.db"
    committed.write_bytes(
        subprocess.run(
            ["git", "-C", str(vault), "show", "HEAD:_pipeline/state/sources.db"],
            check=True,
            capture_output=True,
        ).stdout
    )
    check = sqlite3.connect(committed)
    try:
        assert check.execute("SELECT x FROM t").fetchall() == [(1,)]
    finally:
        check.close()


@pytest.mark.e2e
def test_a_cycle_commit_carries_the_state_it_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from research_framework.pipeline.cycle_runner import run_cycle_steps
    from tests._helpers import fake_cli_binary
    from tests._helpers.vault_factory import build_minimal_vault

    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    vault = build_minimal_vault(
        tmp_path,
        num_categories=1,
        num_targets_per_category=3,
        max_cycles=1,
        install_fake_agent=False,
    )
    fake_cli_binary.activate(monkeypatch, tmp_path / "bin")
    (vault / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 1\n  budget_usd: 10.0\n"
        "default_executor:\n  runtime: claude\n  model: sonnet\n  timeout_s: 60\n",
        encoding="utf-8",
    )
    (vault / ".gitignore").write_text(
        _render_vault_gitignore("data_vault"), encoding="utf-8"
    )
    if not (vault / ".git").exists():
        _git(tmp_path, "init", "-b", "main", str(vault))
    _git(vault, "config", "user.email", "t@e.com")
    _git(vault, "config", "user.name", "T")
    _git(vault, "add", "-A")
    _git(vault, "commit", "-qm", "initial", "--allow-empty")

    ctx = begin_run(vault, kind="research")
    assert ctx is not None
    run_cycle_steps(vault, cycle_num=1, budget_cap=10.0, max_cycles=1)
    cycle_ledger.close_cycle(vault, 1)
    # A live database with rows still in its WAL.
    conn = sqlite3.connect(state_layout.sources_db_path(vault))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS t (x)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    try:
        result = commit_cycle(vault, cycle=1, summary={"short": "fake"}, ctx=ctx)
    finally:
        conn.close()

    assert result.ok
    assert _git(vault, "status", "--porcelain", "--", "_pipeline/state").strip() == ""
    tracked = _git(vault, "ls-files").split()
    assert "_pipeline/state/cycle-ledger.json" in tracked
    assert not [t for t in tracked if t.endswith(("-wal", "-shm"))]
    assert not [t for t in tracked if "agent-calls" in t or "/cycles/" in t]
