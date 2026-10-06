"""Spec 062 FR2 — zero untracked content under data_vault/ after a cycle commit.

The spec-050 auto-commit does ``git add -A``, so a normal writing cycle leaves
nothing untracked. A ` N.md` fork that appears after the commit (a Principle-X
leak) is detected by the post-commit sweep, which the orchestrator turns into a
constrained exit.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from research_framework.pipeline.vault_commit import (
    _untracked_under,
    begin_run,
    commit_cycle,
)


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args), cwd=str(cwd), check=True, capture_output=True, text=True
    )


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    _run("git", "init", "-b", "main", cwd=vault)
    _run("git", "config", "user.email", "t@e.com", cwd=vault)
    _run("git", "config", "user.name", "T", cwd=vault)
    (vault / "README.md").write_text("# v\n", encoding="utf-8")
    _run("git", "add", "-A", cwd=vault)
    _run("git", "commit", "-m", "initial", cwd=vault)
    return vault


def test_writing_cycle_leaves_zero_untracked(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    ctx = begin_run(vault, kind="research")
    data = vault / "data_vault"
    data.mkdir()
    (data / "note-a.md").write_text("---\ntitle: a\n---\nbody\n", encoding="utf-8")
    (data / "note-b.md").write_text("---\ntitle: b\n---\nbody\n", encoding="utf-8")
    result = commit_cycle(vault, cycle=1, summary={"notes_added": 2}, ctx=ctx)
    assert result.untracked_paths == []


def test_post_commit_fork_is_detected(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    ctx = begin_run(vault, kind="research")
    data = vault / "data_vault"
    data.mkdir()
    (data / "Risk.md").write_text("---\ntitle: r\n---\nbody\n", encoding="utf-8")
    commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
    # A fork appears AFTER the cycle commit (the rc1 ` 2.md` symptom).
    (data / "Risk 2.md").write_text("---\ntitle: r\n---\nforked\n", encoding="utf-8")
    untracked = _untracked_under(vault, "data_vault")
    assert any(p.endswith("Risk 2.md") for p in untracked), untracked


def test_untracked_detection_scoped_to_data_vault(tmp_path: Path) -> None:
    """An untracked file under _pipeline/ is NOT a data_vault leak."""
    vault = _make_vault(tmp_path)
    begin_run(vault, kind="research")
    pipe = vault / "_pipeline"
    pipe.mkdir()
    (pipe / "scratch.json").write_text("{}\n", encoding="utf-8")
    assert _untracked_under(vault, "data_vault") == []
