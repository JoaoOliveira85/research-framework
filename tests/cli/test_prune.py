"""Tests for `research_framework prune` CLI sub-command."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
FIXTURE_VAULT = Path(__file__).parent.parent / "fixtures" / "vault"


def _run_prune(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "research_framework", "prune", *args],
        capture_output=True,
        text=True,
        env=env,
        **kwargs,
    )


def _run_inventory(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "research_framework", "inventory", *args],
        capture_output=True,
        text=True,
        env=env,
        **kwargs,
    )


def _make_minimal_vault(tmp_path: Path) -> Path:
    """Clone the fixture vault into tmp_path."""
    dst = tmp_path / "vault"
    shutil.copytree(FIXTURE_VAULT, dst)
    return dst


def _git_init_vault(vault: Path) -> None:
    """Initialise a git repo in *vault* with an initial commit."""
    subprocess.run(["git", "init", str(vault)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(vault), "add", "."], capture_output=True, check=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(vault),
            "-c",
            "user.email=test@test",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "init",
        ],
        capture_output=True,
        check=True,
    )


# ---------------------------------------------------------------------------
# 1. No pruneable paths — vault has no superseded scripts
# ---------------------------------------------------------------------------


def test_no_pruneable_paths_exits_0(tmp_path: Path) -> None:
    vault = _make_minimal_vault(tmp_path)
    result = _run_prune([str(vault), "--yes"])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "nothing to prune" in result.stdout


# ---------------------------------------------------------------------------
# 2. Prune with --yes — removes file + two snapshot commits
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not shutil.which("git"), reason="git not available")
def test_prune_removes_file_and_creates_boundary_commits(tmp_path: Path) -> None:
    vault = _make_minimal_vault(tmp_path)
    _git_init_vault(vault)

    # Plant a superseded script
    scripts_dir = vault / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    target = scripts_dir / "collect_rss.py"
    target.write_text("# vault-local rss collector\n")

    # Commit the planted file so the tree is clean before prune
    subprocess.run(["git", "-C", str(vault), "add", "."], capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(vault),
            "-c",
            "user.email=test@test",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "add local script",
        ],
        capture_output=True,
    )

    result = _run_prune([str(vault), "--yes"])
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    # File is gone
    assert not target.exists(), "prune should have removed collect_rss.py"

    # Two boundary commits were created (pre + post)
    log = subprocess.run(
        ["git", "-C", str(vault), "log", "--oneline", "-5"],
        capture_output=True,
        text=True,
    )
    log_lines = log.stdout.strip().splitlines()
    messages = " ".join(log_lines[:2])
    assert "prune" in messages.lower(), f"Expected prune commits in log:\n{log.stdout}"

    # HEAD~2 rollback restores the file
    subprocess.run(
        ["git", "-C", str(vault), "reset", "--hard", "HEAD~2"],
        capture_output=True,
        check=True,
    )
    assert target.exists(), "HEAD~2 rollback should restore collect_rss.py"


@pytest.mark.skipif(not shutil.which("git"), reason="git not available")
def test_failed_pre_snapshot_aborts_before_deleting(tmp_path: Path) -> None:
    """The pre-prune snapshot is the only copy of a gitignored target.

    A failed snapshot commit (here: a pre-commit hook that rejects it) used to
    print a WARNING and delete anyway, so an untracked script was lost for
    good while the verb exited 0.
    """
    vault = _make_minimal_vault(tmp_path)
    (vault / ".gitignore").write_text("scripts/\n", encoding="utf-8")
    _git_init_vault(vault)
    target = vault / "scripts" / "collect_rss.py"
    target.parent.mkdir(exist_ok=True)
    target.write_text("# operator-edited, never committed\n", encoding="utf-8")
    hook = vault / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)

    result = _run_prune([str(vault), "--yes"])

    assert result.returncode == 2, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert target.exists(), "prune deleted a file it had failed to snapshot"
    assert "snapshot" in result.stderr


@pytest.mark.skipif(not shutil.which("git"), reason="git not available")
def test_a_target_the_snapshot_could_not_add_is_not_deleted(tmp_path: Path) -> None:
    """The snapshot commit is ``--allow-empty``, so it succeeds even when the
    ``git add -f`` before it failed — and the target was then deleted with no
    copy anywhere, the rollback hint pointing at a commit that never held it.

    ``core.safecrlf`` makes ``git add`` refuse a CRLF file outright, which
    fails the add without failing the commit.
    """
    vault = _make_minimal_vault(tmp_path)
    (vault / ".gitignore").write_text("scripts/\n", encoding="utf-8")
    _git_init_vault(vault)
    for key, value in (
        ("user.email", "test@test"),
        ("user.name", "Test"),
        ("core.autocrlf", "input"),
        ("core.safecrlf", "true"),
    ):
        subprocess.run(
            ["git", "-C", str(vault), "config", key, value],
            capture_output=True,
            check=True,
        )
    target = vault / "scripts" / "collect_rss.py"
    target.parent.mkdir(exist_ok=True)
    original = b"# operator-edited, never committed\r\nprint(1)\r\n"
    target.write_bytes(original)

    result = _run_prune([str(vault), "--yes"])

    assert target.exists(), "prune deleted a file its snapshot does not contain"
    assert target.read_bytes() == original
    assert result.returncode == 2, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "snapshot" in result.stderr


@pytest.mark.skipif(not shutil.which("git"), reason="git not available")
def test_printed_rollback_restores_a_gitignored_target(tmp_path: Path) -> None:
    """The snapshot force-adds gitignored targets, so only the snapshot commit
    itself holds them; the printed ``HEAD~2`` is the commit *before* it."""
    vault = _make_minimal_vault(tmp_path)
    (vault / ".gitignore").write_text("scripts/\n", encoding="utf-8")
    _git_init_vault(vault)
    target = vault / "scripts" / "collect_rss.py"
    target.parent.mkdir(exist_ok=True)
    target.write_text("# never committed\n", encoding="utf-8")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "PYTHONPATH": str(REPO_ROOT / "src"),
    }

    result = subprocess.run(
        [sys.executable, "-m", "research_framework", "prune", str(vault), "--yes"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert not target.exists()
    rollback = next(line for line in result.stdout.splitlines() if "Rollback:" in line)
    ref = rollback.split("--hard", 1)[1].split()[0]

    subprocess.run(
        ["git", "-C", str(vault), "reset", "--hard", ref],
        capture_output=True,
        check=True,
    )
    assert target.exists(), f"printed rollback did not restore the file: {rollback}"


# ---------------------------------------------------------------------------
# 3. Dirty tree refuses without --force
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not shutil.which("git"), reason="git not available")
def test_dirty_tree_refuses_without_force(tmp_path: Path) -> None:
    vault = _make_minimal_vault(tmp_path)
    _git_init_vault(vault)

    # Dirty the tree (uncommitted change)
    (vault / "data_vault" / "dirty.md").write_text("dirty\n")

    # Plant a pruneable script so prune would otherwise proceed
    scripts_dir = vault / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    (scripts_dir / "collect_rss.py").write_text("# rss\n")

    result = _run_prune([str(vault), "--yes"])
    assert result.returncode != 0, "Expected non-zero exit on dirty tree"
    stderr_lower = result.stderr.lower()
    assert "dirty" in stderr_lower or "error" in stderr_lower, (
        f"Expected dirty-tree error in stderr:\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# 4. --force proceeds despite dirty tree
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not shutil.which("git"), reason="git not available")
def test_force_proceeds_on_dirty_tree(tmp_path: Path) -> None:
    vault = _make_minimal_vault(tmp_path)
    _git_init_vault(vault)

    # Dirty the tree
    (vault / "data_vault" / "dirty.md").write_text("dirty\n")

    # Plant a pruneable script
    scripts_dir = vault / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    target = scripts_dir / "collect_rss.py"
    target.write_text("# rss\n")

    result = _run_prune([str(vault), "--yes", "--force"])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert not target.exists(), "prune --force should have removed collect_rss.py"


# ---------------------------------------------------------------------------
# 5. --keep excludes a path from deletion
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not shutil.which("git"), reason="git not available")
def test_keep_flag_excludes_path(tmp_path: Path) -> None:
    vault = _make_minimal_vault(tmp_path)
    _git_init_vault(vault)

    # Plant two pruneable scripts
    scripts_dir = vault / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    rss = scripts_dir / "collect_rss.py"
    extract = scripts_dir / "extract.py"
    rss.write_text("# rss\n")
    extract.write_text("# extract\n")

    subprocess.run(["git", "-C", str(vault), "add", "."], capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(vault),
            "-c",
            "user.email=test@test",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "add scripts",
        ],
        capture_output=True,
    )

    result = _run_prune([str(vault), "--yes", "--keep", "scripts/collect_rss.py"])
    assert result.returncode == 0, f"stderr: {result.stderr}"

    # collect_rss.py is kept; extract.py is removed
    assert rss.exists(), "collect_rss.py should be kept by --keep"
    assert not extract.exists(), "extract.py should have been pruned"


# ---------------------------------------------------------------------------
# 6. Inventory includes pruneable section
# ---------------------------------------------------------------------------


def test_inventory_includes_pruneable_section_json(tmp_path: Path) -> None:
    vault = _make_minimal_vault(tmp_path)

    # No superseded scripts → pruneable list is empty but key is present
    result = _run_inventory([str(vault), "--format=json"])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    inv = json.loads(result.stdout)
    assert "pruneable" in inv, "inventory JSON must include 'pruneable' key"
    assert isinstance(inv["pruneable"], list)


def test_inventory_pruneable_populated_when_script_present(tmp_path: Path) -> None:
    vault = _make_minimal_vault(tmp_path)
    scripts_dir = vault / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    (scripts_dir / "collect_rss.py").write_text("# rss\n")

    result = _run_inventory([str(vault), "--format=json"])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    inv = json.loads(result.stdout)
    pruneable = inv["pruneable"]
    assert len(pruneable) >= 1
    paths = [e["path"] for e in pruneable]
    assert "scripts/collect_rss.py" in paths
    # Check that superseded_by is present and correct
    entry = next(e for e in pruneable if e["path"] == "scripts/collect_rss.py")
    assert entry["superseded_by"] == "research_framework.collectors.rss"


def test_inventory_text_includes_pruneable_section(tmp_path: Path) -> None:
    vault = _make_minimal_vault(tmp_path)
    scripts_dir = vault / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    (scripts_dir / "collect_rss.py").write_text("# rss\n")

    result = _run_inventory([str(vault), "--format=text"])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "Pruneable" in result.stdout
    assert "collect_rss.py" in result.stdout
