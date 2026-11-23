"""Spec 083 T002 — the `_pipeline/` stanza of a vault's `.gitignore` (FR-003, FR-019)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from research_framework.generator.scaffold import _render_vault_gitignore
from research_framework.pipeline import state_layout as L


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )


def _pipeline_lines(body: str) -> list[str]:
    return [
        line
        for line in body.splitlines()
        if "_pipeline" in line and not line.lstrip().startswith("#")
    ]


def test_pipeline_stanza_names_no_file() -> None:
    body = _render_vault_gitignore("data_vault")
    assert _pipeline_lines(body) == [
        "!_pipeline/",
        "_pipeline/*",
        f"!{L.STATE_DIR}/",
        f"{L.STATE_DIR}/*.db-wal",
        f"{L.STATE_DIR}/*.db-shm",
    ]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    _git(root, "init", "-q")
    (root / ".gitignore").write_text(_render_vault_gitignore("data_vault"), "utf-8")
    return root


def _ignored(repo: Path, rel: str) -> bool:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    return _git(repo, "check-ignore", "-q", "--", rel).returncode == 0


@pytest.mark.parametrize(
    "rel",
    [
        "_pipeline/state/coverage-targets.json",
        "_pipeline/state/sources.db",
        "_pipeline/state/quarantine/x.md",
        "_pipeline/state/sources/rss/facts-schema.json",
        "_pipeline/state/research-backlog.json",
    ],
)
def test_git_tracks_state(repo: Path, rel: str) -> None:
    assert not _ignored(repo, rel), f"{rel} is ignored"


@pytest.mark.parametrize(
    "rel",
    [
        "_pipeline/cycles/cycle-001-scout.json",
        "_pipeline/spec-parse.json",
        "_pipeline/research-backlog.md",
        "_pipeline/research-backlog.md.overwritten",
        "_pipeline/coverage-targets.json",
        "_pipeline/sources.db",
        "_pipeline/state/sources.db-wal",
        "_pipeline/state/sources.db-shm",
    ],
)
def test_git_ignores_the_rest(repo: Path, rel: str) -> None:
    assert _ignored(repo, rel), f"{rel} is not ignored"


def test_git_tracks_the_backlog_store_and_ignores_its_view(repo: Path) -> None:
    """Spec 084 acceptance 11, with real ``git check-ignore``."""
    from research_framework.pipeline import backlog

    store = L.research_backlog_path(Path()).as_posix()
    assert backlog.create_empty(repo)
    assert _git(repo, "check-ignore", "-q", "--", store).returncode != 0
    view = backlog.view_path(repo).relative_to(repo).as_posix()
    assert (repo / view).is_file()
    assert _git(repo, "check-ignore", "-q", "--", view).returncode == 0
    _git(repo, "add", "-A")
    staged = set(_git(repo, "diff", "--cached", "--name-only").stdout.split())
    assert store in staged
    assert view not in staged
