"""Tests for fake_repo helper."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests._helpers.fake_repo import FakeRepo


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_fake_repo_checkout_returns_controlled_head_sha(tmp_path: Path) -> None:
    repo = FakeRepo(tmp_path / "repo")
    first = repo.head_sha()
    second = repo.amend_readme("changed\n")
    assert first != second
    assert len(second) == 40
