"""Build a vault in the pre-083 layout (spec 083 T010 fixture).

Two files were tracked before 083 (the backlog and the coverage targets); every
other state artefact sat untracked at its legacy path under ``_pipeline/``.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

LEGACY_GITIGNORE_STANZA = (
    "# `_pipeline/` is regenerable EXCEPT the two control files below. Git\n"
    "# cannot re-include a path under an excluded directory, hence the\n"
    "# un-ignore / re-exclude / un-exclude sequence.\n"
    "!_pipeline/\n"
    "_pipeline/*\n"
    "!_pipeline/research-backlog.md\n"
    "!_pipeline/coverage-targets.json\n"
)

COVERAGE_V1 = '{"cycle_number": 1, "categories": []}\n'
COVERAGE_V2 = '{"cycle_number": 2, "categories": [], "priority": {"hand_set": 9}}\n'


def git(vault: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(vault), *args], check=True, capture_output=True, text=True
    ).stdout


def legacy_gitignore(corpus: str = "data_vault") -> str:
    return (
        f"# research-framework: track {corpus}/ + the control files; "
        "everything else is ephemeral.\n"
        "/*\n"
        "!.gitignore\n"
        f"!{corpus}/\n"
        f"!{corpus}/**\n"
        "# Operator-authored control files — these are your inputs, so they are\n"
        "# versioned (spec 058 warns when they are not).\n"
        "!research.spec.md\n"
        "!settings.yaml\n" + LEGACY_GITIGNORE_STANZA
    )


def _write_db_with_rows_in_wal(dest: Path) -> None:
    """Leave ``dest`` plus a non-empty ``-wal`` beside it, with no open connection.

    SQLite checkpoints and deletes the WAL when the last connection closes, so
    the files are copied while a connection is still open.
    """
    work = dest.parent / ".db-build"
    work.mkdir()
    conn = sqlite3.connect(work / "sources.db")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("CREATE TABLE s (x)")
        conn.execute("INSERT INTO s VALUES (42)")
        conn.commit()
        shutil.copy2(work / "sources.db", dest)
        shutil.copy2(work / "sources.db-wal", dest.with_name(dest.name + "-wal"))
    finally:
        conn.close()
    shutil.rmtree(work)


def build_legacy_vault(
    tmp_path: Path,
    *,
    git_repo: bool = True,
    cycles: int = 2,
    gitignore: str | None = None,
) -> Path:
    """Return a vault whose state is all at legacy paths.

    Tracked: ``_pipeline/research-backlog.md`` and
    ``_pipeline/coverage-targets.json`` (added in one commit, edited in a
    second so ``git log --follow`` has something to follow). Untracked: the
    propose-rejects file, ``sources.db`` (rows live in its WAL until
    checkpointed), a quarantined note, a per-module facts schema, the archive
    snapshots and approval decisions. Run-control files and ``cycles/`` exist
    too. ``cycles`` completed cycles each carry one 0.5 USD sidecar.
    """
    vault = tmp_path / "legacy-vault"
    pipe = vault / "_pipeline"
    (pipe / "quarantine").mkdir(parents=True)
    (pipe / "sources" / "mod-a").mkdir(parents=True)
    (vault / "data_vault").mkdir()
    (vault / "data_vault" / "note.md").write_text("# n\n", encoding="utf-8")
    (vault / "settings.yaml").write_text("pipeline:\n  max_cycles: 3\n")
    (vault / "research.spec.md").write_text("# spec\n", encoding="utf-8")
    (vault / ".gitignore").write_text(gitignore or legacy_gitignore(), encoding="utf-8")
    (pipe / "research-backlog.md").write_text("# Backlog\n", encoding="utf-8")
    (pipe / "coverage-targets.json").write_text(COVERAGE_V1, encoding="utf-8")
    if git_repo:
        subprocess.run(
            ["git", "init", "-q", "-b", "main", str(vault)],
            check=True,
            capture_output=True,
        )
        git(vault, "config", "user.email", "t@e.com")
        git(vault, "config", "user.name", "T")
        git(vault, "add", "-A")
        git(vault, "commit", "-qm", "initial")
    (pipe / "coverage-targets.json").write_text(COVERAGE_V2, encoding="utf-8")
    if git_repo:
        git(vault, "commit", "-qam", "tune coverage targets")

    (pipe / "propose-rejects.md").write_text("- rejected topic\n", encoding="utf-8")
    (pipe / "archive-snapshots.json").write_text("{}\n", encoding="utf-8")
    (pipe / "approval-decisions.json").write_text("[]\n", encoding="utf-8")
    (pipe / "quarantine" / "orphan.md").write_text("# orphan\n", encoding="utf-8")
    (pipe / "sources" / "mod-a" / "facts-schema.json").write_text(
        json.dumps({"module": "mod-a"}), encoding="utf-8"
    )
    _write_db_with_rows_in_wal(pipe / "sources.db")

    cycles_dir = pipe / "cycles"
    for n in range(1, cycles + 1):
        calls = cycles_dir / f"cycle-{n:03d}" / "agent-calls"
        calls.mkdir(parents=True)
        (calls / "a.json").write_text('{"cost_usd": 0.5}', encoding="utf-8")
        (cycles_dir / f"cycle-{n:03d}-quality-report.json").write_text("{}")
        (cycles_dir / f"cycle-{n:03d}-research.json").write_text(
            json.dumps({"timestamp": f"2026-01-0{n}T00:00:00Z"}), encoding="utf-8"
        )
    (pipe / "BUDGET_PAUSED").write_text("{}", encoding="utf-8")
    (pipe / "pipeline-state.json").write_text("{}", encoding="utf-8")
    return vault
