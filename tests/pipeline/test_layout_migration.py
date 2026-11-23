"""Spec 083 T010: the layout migration, on a vault built in the pre-083 layout."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest

from research_framework.cli.migrate_layout import cmd_migrate_layout
from research_framework.generator.scaffold import _render_vault_gitignore
from research_framework.pipeline import cycle_ledger, layout_migration, state_layout
from tests._helpers.legacy_layout import (
    COVERAGE_V2,
    build_legacy_vault,
    git,
    legacy_gitignore,
)

S = state_layout.STATE_DIR


def _tree(vault: Path) -> dict[str, bytes]:
    return {
        p.relative_to(vault).as_posix(): p.read_bytes()
        for p in sorted(vault.rglob("*"))
        if p.is_file() and ".git/" not in p.as_posix()
    }


def _ls(vault: Path) -> list[str]:
    return git(vault, "ls-files").split()


def test_moves_every_state_path_and_leaves_the_backlog(tmp_path: Path) -> None:
    vault = build_legacy_vault(tmp_path)
    first_add = git(
        vault,
        "log",
        "--diff-filter=A",
        "--format=%H",
        "--",
        "_pipeline/coverage-targets.json",
    ).split()[-1]

    result = layout_migration.migrate(vault)

    assert result.exit_code == 0 and result.committed
    for rel in (
        "coverage-targets.json",
        "propose-rejects.md",
        "sources.db",
        "archive-snapshots.json",
        "approval-decisions.json",
        "quarantine/orphan.md",
        "sources/mod-a/facts-schema.json",
        "cycle-ledger.json",
    ):
        assert (vault / S / rel).is_file(), rel
        assert f"{S}/{rel}" in _ls(vault), rel
    # Byte for byte: hand-set priorities survive.
    assert (vault / S / "coverage-targets.json").read_text() == COVERAGE_V2
    assert not state_layout.is_legacy_layout(vault)
    # The backlog and run control are where they were.
    assert (vault / "_pipeline" / "research-backlog.md").is_file()
    assert "_pipeline/research-backlog.md" in _ls(vault)
    assert (vault / "_pipeline" / "BUDGET_PAUSED").is_file()
    assert (vault / "_pipeline" / "pipeline-state.json").is_file()
    # History follows the rename back to the commit that first added the file.
    follow = git(
        vault, "log", "--follow", "--format=%H", "--", f"{S}/coverage-targets.json"
    ).split()
    assert first_add in follow
    # The WAL was folded in before the move: the moved file alone holds the row.
    assert not [t for t in _ls(vault) if t.endswith(("-wal", "-shm"))]
    conn = sqlite3.connect(vault / S / "sources.db")
    try:
        assert conn.execute("SELECT x FROM s").fetchall() == [(42,)]
    finally:
        conn.close()
    assert git(vault, "status", "--porcelain").strip() == ""


def test_the_commit_is_renames_additions_ignore_file_and_ledger_only(
    tmp_path: Path,
) -> None:
    vault = build_legacy_vault(tmp_path)
    (vault / "_pipeline" / "scratch.txt").write_text("x")  # ignored scratch
    result = layout_migration.migrate(vault)
    assert result.committed
    assert git(vault, "log", "-1", "--format=%s").strip() == (
        "framework: migrate _pipeline layout"
    )
    stat = git(vault, "show", "--stat", "-M", "--format=", "HEAD")
    assert (
        "_pipeline/coverage-targets.json => _pipeline/state/coverage-targets.json"
        in stat
        or ("coverage-targets.json" in stat and "=>" in stat)
    )
    changes = git(
        vault, "show", "--name-status", "-M", "--format=", "HEAD"
    ).splitlines()
    renames = [c for c in changes if c.startswith("R")]
    assert any(c.startswith("R100") and "coverage-targets.json" in c for c in renames)
    touched = {c.split("\t")[-1] for c in changes}
    assert ".gitignore" in touched
    assert f"{S}/cycle-ledger.json" in touched
    assert all(
        t == ".gitignore" or t.startswith(S) or t.startswith("_pipeline/coverage")
        for t in touched
    )
    assert "_pipeline/research-backlog.md" not in touched
    assert "scratch.txt" not in " ".join(touched)


def test_second_run_reports_already_migrated(tmp_path: Path) -> None:
    vault = build_legacy_vault(tmp_path)
    layout_migration.migrate(vault)
    head = git(vault, "rev-parse", "HEAD")
    again = layout_migration.migrate(vault)
    assert again.exit_code == 0 and again.committed is None
    assert any("already migrated" in m for m in again.messages)
    assert git(vault, "rev-parse", "HEAD") == head


def test_conflicting_destination_aborts_with_nothing_moved(tmp_path: Path) -> None:
    vault = build_legacy_vault(tmp_path)
    (vault / S).mkdir(parents=True)
    (vault / S / "propose-rejects.md").write_text("- different\n")
    (vault / S / "archive-snapshots.json").write_text('{"x": 1}\n')
    (vault / S / "approval-decisions.json").write_text("[]\n")  # identical
    before = _tree(vault)
    result = layout_migration.migrate(vault, force=True)
    assert result.exit_code == 2
    text = "\n".join(result.messages)
    assert "_pipeline/propose-rejects.md" in text and f"{S}/propose-rejects.md" in text
    assert "_pipeline/archive-snapshots.json" in text
    assert "approval-decisions" not in text
    assert _tree(vault) == before

    # Identical content at both paths: the legacy copy is dropped and it proceeds.
    (vault / S / "propose-rejects.md").write_text("- rejected topic\n")
    (vault / S / "archive-snapshots.json").write_text("{}\n")
    ok = layout_migration.migrate(vault, force=True)
    assert ok.exit_code == 0
    assert not (vault / "_pipeline" / "propose-rejects.md").exists()
    assert not (vault / "_pipeline" / "approval-decisions.json").exists()


def test_dry_run_prints_and_touches_nothing(tmp_path: Path) -> None:
    vault = build_legacy_vault(tmp_path)
    before = _tree(vault)
    head = git(vault, "rev-parse", "HEAD")
    result = layout_migration.migrate(vault, dry_run=True)
    assert result.exit_code == 0
    text = "\n".join(result.messages)
    assert (
        "_pipeline/coverage-targets.json -> _pipeline/state/coverage-targets.json"
        in text
    )
    assert ".gitignore" in text and "backfill 2 row" in text
    assert _tree(vault) == before
    assert git(vault, "rev-parse", "HEAD") == head
    assert not (vault / S).exists()


def test_the_shipped_gitignore_is_replaced_by_the_new_rendering(tmp_path: Path) -> None:
    vault = build_legacy_vault(tmp_path)
    layout_migration.migrate(vault)
    assert (vault / ".gitignore").read_text() == _render_vault_gitignore("data_vault")


def test_customised_gitignore_gets_one_reinclude_or_a_named_winning_rule(
    tmp_path: Path,
) -> None:
    custom = legacy_gitignore() + "# mine\n*.secret\n"
    vault = build_legacy_vault(tmp_path / "a", gitignore=custom)
    result = layout_migration.migrate(vault)
    assert result.exit_code == 0
    text = (vault / ".gitignore").read_text()
    assert text.startswith(custom)  # the operator's lines are untouched
    assert text.count("!_pipeline/state/") == 1
    assert f"{S}/sources.db" in _ls(vault)

    # A rule the re-include cannot beat: `/*` with no `!_pipeline/` above it.
    hostile = "/*\n!.gitignore\n!data_vault/\n!data_vault/**\n!research.spec.md\n!settings.yaml\n"
    vault2 = build_legacy_vault(tmp_path / "b")
    (vault2 / ".gitignore").write_text(hostile)
    git(vault2, "commit", "-qam", "hostile ignore file")
    before = _tree(vault2)
    result = layout_migration.migrate(vault2, force=True)
    assert result.exit_code == 2
    assert _tree(vault2) == before  # nothing moved, ignore file restored
    assert "still ignored by" in "\n".join(result.messages)
    assert ".gitignore:" in "\n".join(result.messages)


def test_ledger_is_backfilled_from_cycles(tmp_path: Path) -> None:
    vault = build_legacy_vault(tmp_path, cycles=3)
    layout_migration.migrate(vault)
    rows = cycle_ledger.load(vault)
    assert [r.cycle for r in rows] == [1, 2, 3]
    assert sum(r.cost_usd for r in rows) == pytest.approx(1.5)
    assert rows[0].finished_at == "2026-01-01T00:00:00Z"
    assert f"{S}/cycle-ledger.json" in _ls(vault)


def test_dirty_tree_refuses_unless_forced(tmp_path: Path) -> None:
    vault = build_legacy_vault(tmp_path)
    (vault / "data_vault" / "note.md").write_text("# edited\n")
    before = _tree(vault)
    refused = layout_migration.migrate(vault)
    assert refused.exit_code == 2
    assert "--force" in "\n".join(refused.messages)
    assert _tree(vault) == before
    forced = layout_migration.migrate(vault, force=True)
    assert forced.exit_code == 0 and forced.committed
    # The unrelated edit is not part of the migration commit.
    assert "data_vault/note.md" not in git(
        vault, "show", "--name-only", "--format=", "HEAD"
    )
    assert "note.md" in git(vault, "status", "--porcelain")


def test_non_git_vault_moves_files_and_logs_the_opt_out(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    vault = build_legacy_vault(tmp_path, git_repo=False)
    with caplog.at_level(logging.INFO, logger="research_framework"):
        result = layout_migration.migrate(vault)
    assert result.exit_code == 0 and result.committed is None
    assert (vault / S / "coverage-targets.json").read_text() == COVERAGE_V2
    assert not (vault / "_pipeline" / "coverage-targets.json").exists()
    assert any("nothing committed" in r.getMessage() for r in caplog.records)
    assert not (vault / ".git").exists()


def test_a_disabled_commit_invariant_moves_files_and_commits_nothing(
    tmp_path: Path,
) -> None:
    vault = build_legacy_vault(tmp_path)
    (vault / "settings.yaml").write_text("vault_commit:\n  enabled: false\n")
    git(vault, "commit", "-qam", "opt out")
    head = git(vault, "rev-parse", "HEAD")
    result = layout_migration.migrate(vault)
    assert result.exit_code == 0 and result.committed is None
    assert git(vault, "rev-parse", "HEAD") == head
    assert (vault / S / "coverage-targets.json").is_file()


def test_run_control_and_legacy_settings_are_left_alone(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    vault = build_legacy_vault(tmp_path)
    (vault / "_pipeline" / "settings.yaml").write_text("limits: {}\n")
    (vault / "_pipeline" / "state.json").write_text("{}")
    (vault / "_pipeline" / "APPROVAL_REQUIRED").write_text("{}")
    with caplog.at_level(logging.WARNING, logger="research_framework"):
        layout_migration.migrate(vault)
    for name in (
        "BUDGET_PAUSED",
        "APPROVAL_REQUIRED",
        "pipeline-state.json",
        "state.json",
        "settings.yaml",
        "research-backlog.md",
    ):
        assert (vault / "_pipeline" / name).is_file(), name
        assert not (vault / S / name).exists(), name
    warned = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("_pipeline/settings.yaml" in w and "settings.yaml" in w for w in warned)


def test_the_cli_verb_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import argparse

    vault = build_legacy_vault(tmp_path)
    ns = argparse.Namespace(vault=vault, dry_run=False, force=False)
    assert cmd_migrate_layout(ns) == 0
    assert cmd_migrate_layout(ns) == 0
    out = capsys.readouterr().out
    assert "already migrated" in out
    missing = argparse.Namespace(vault=tmp_path / "nope", dry_run=False, force=False)
    assert cmd_migrate_layout(missing) == 2
    assert "vault not found" in capsys.readouterr().err
