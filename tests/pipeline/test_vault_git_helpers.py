"""Tests for git boundary helpers used by the migrator apply step."""

import subprocess
from pathlib import Path

import pytest

from research_framework.pipeline.vault_git import (
    GitUnavailable,
    is_git_repo,
    snapshot_commit,
    working_tree_dirty,
)


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    (path / "seed.txt").write_text("seed")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True)


def test_is_git_repo_true(tmp_path):
    _init_repo(tmp_path)
    assert is_git_repo(tmp_path) is True


def test_is_git_repo_false(tmp_path):
    assert is_git_repo(tmp_path) is False


def test_working_tree_dirty_detects_unstaged(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "seed.txt").write_text("changed")
    assert working_tree_dirty(tmp_path) is True


def test_working_tree_dirty_clean(tmp_path):
    _init_repo(tmp_path)
    assert working_tree_dirty(tmp_path) is False


def test_working_tree_dirty_includes_untracked(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "new.txt").write_text("x")
    assert working_tree_dirty(tmp_path) is True


def test_snapshot_commit_creates_commit(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "new.txt").write_text("x")
    sha = snapshot_commit(tmp_path, message="migrator: pre-apply snapshot")
    assert sha is not None and len(sha) == 40
    log = subprocess.run(
        ["git", "-C", str(tmp_path), "log", "-1", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert log.stdout.strip() == "migrator: pre-apply snapshot"


def test_snapshot_commit_clean_tree_returns_none(tmp_path):
    _init_repo(tmp_path)
    assert snapshot_commit(tmp_path, message="noop") is None


def test_git_unavailable_outside_repo(tmp_path):
    with pytest.raises(GitUnavailable):
        snapshot_commit(tmp_path, message="x")
