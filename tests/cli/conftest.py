"""Shared fixtures for the spec-063 acceptance-harness CLI tests.

The acceptance verb writes its scorecard under ``<vault>/_pipeline/acceptance/``,
so tests always operate on a tmp copy of the committed fixtures (never the
fixtures in-tree).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ACCEPTANCE_FIXTURES = Path(__file__).parent.parent / "fixtures" / "acceptance"


def _copy(src: Path, dst: Path) -> Path:
    shutil.copytree(src, dst)
    return dst


def _git(path: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(path), *args], check=True, capture_output=True, text=True
    )


@pytest.fixture
def snapshot_vault(tmp_path: Path) -> Path:
    """A writable copy of the rc1 codebase snapshot (reproduces every defect).

    Deliberately NOT a git repo — the static fixture cannot carry a nested
    ``.git``; GA-003 reports advisory WARN on it, and the dedicated GA-003
    topology tests build a real repo in tmp.
    """
    return _copy(ACCEPTANCE_FIXTURES / "rc1-codebase-snapshot", tmp_path / "snapshot")


@pytest.fixture
def clean_vault(tmp_path: Path) -> Path:
    """A writable copy of the clean twin, as a clean git repo (passes every gate).

    One ``research: cycle 1`` commit, clean tree — so GA-003 (Principle X) PASSes.
    """
    vault = _copy(ACCEPTANCE_FIXTURES / "clean-twin", tmp_path / "clean")
    _git(vault, "init")
    _git(vault, "config", "user.email", "t@example.com")
    _git(vault, "config", "user.name", "t")
    _git(vault, "add", "-A")
    _git(vault, "commit", "-m", "research: cycle 1")
    return vault
