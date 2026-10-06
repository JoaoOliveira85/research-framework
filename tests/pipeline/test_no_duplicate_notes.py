"""Spec 062 FR2 — no duplicate note files; one commit per cycle.

A same-cycle re-emit (e.g. a metadata correction) folds into the single
``research: cycle N`` commit instead of producing a second one, and the shared
``find_duplicate_notes`` detector flags any OS-style ` N.md` fork or
byte-identical content duplicate.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from research_framework.pipeline.vault_commit import begin_run, commit_cycle
from scripts.validate_vault import find_duplicate_notes


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


def _write_note(vault: Path, name: str, text: str) -> Path:
    data = vault / "data_vault"
    data.mkdir(exist_ok=True)
    p = data / name
    p.write_text(text, encoding="utf-8")
    return p


def _cycle_subjects(vault: Path) -> list[str]:
    out = _run("git", "log", "--pretty=%s", cwd=vault).stdout.splitlines()
    return [s for s in out if s.startswith("research: cycle")]


def test_same_cycle_reemit_folds_into_one_commit(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    ctx = begin_run(vault, kind="research")
    note = _write_note(vault, "obp-product.md", "---\ntitle: x\n---\nfirst\n")
    commit_cycle(vault, cycle=6, summary={"notes_added": 1}, ctx=ctx)
    # Re-emit the same note (metadata correction) within the same cycle.
    note.write_text("---\ntitle: x\nupdated: y\n---\nsecond\n", encoding="utf-8")
    commit_cycle(vault, cycle=6, summary={"exit_reason": "re-emit"}, ctx=ctx)

    subjects = _cycle_subjects(vault)
    cycle6 = [s for s in subjects if s.startswith("research: cycle 6")]
    assert len(cycle6) == 1, f"expected one cycle-6 commit, got {subjects}"


def test_distinct_cycles_get_distinct_commits(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    ctx = begin_run(vault, kind="research")
    _write_note(vault, "a.md", "---\ntitle: a\n---\na\n")
    commit_cycle(vault, cycle=1, summary={"notes_added": 1}, ctx=ctx)
    _write_note(vault, "b.md", "---\ntitle: b\n---\nb\n")
    commit_cycle(vault, cycle=2, summary={"notes_added": 1}, ctx=ctx)
    subjects = _cycle_subjects(vault)
    assert any(s.startswith("research: cycle 1") for s in subjects)
    assert any(s.startswith("research: cycle 2") for s in subjects)


def test_find_duplicate_notes_detects_os_sibling(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    data = vault / "data_vault"
    data.mkdir(parents=True)
    (data / "Risk.md").write_text("canonical\n", encoding="utf-8")
    (data / "Risk 2.md").write_text("forked\n", encoding="utf-8")
    findings = find_duplicate_notes(data)
    kinds = {f.kind for f in findings}
    assert "os_sibling" in kinds
    sib = next(f for f in findings if f.kind == "os_sibling")
    assert {p.name for p in sib.paths} == {"Risk.md", "Risk 2.md"}


def test_find_duplicate_notes_detects_content_hash(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    data = vault / "data_vault"
    data.mkdir(parents=True)
    (data / "one.md").write_text("identical body\n", encoding="utf-8")
    (data / "two.md").write_text("identical body\n", encoding="utf-8")
    findings = find_duplicate_notes(data)
    assert any(f.kind == "content_hash" for f in findings)


def test_find_duplicate_notes_clean_vault_empty(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    data = vault / "data_vault"
    data.mkdir(parents=True)
    (data / "a.md").write_text("alpha\n", encoding="utf-8")
    (data / "b.md").write_text("beta\n", encoding="utf-8")
    assert find_duplicate_notes(data) == []
