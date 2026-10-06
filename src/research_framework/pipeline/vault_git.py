"""Git boundary helpers for the migrator's pre/post snapshot commits."""

from __future__ import annotations

import subprocess
from pathlib import Path

__all__ = [
    "GitUnavailable",
    "is_git_repo",
    "working_tree_dirty",
    "snapshot_commit",
    "head_content",
]


class GitUnavailable(RuntimeError):
    """Raised when a git operation is requested outside a repo or without git."""


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def is_git_repo(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        r = _run(["git", "rev-parse", "--is-inside-work-tree"], path)
    except FileNotFoundError:
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


def working_tree_dirty(
    path: Path,
    *,
    ignore_paths: frozenset[str] | None = None,
) -> bool:
    """True if the working tree has unstaged, staged, or untracked changes.

    *ignore_paths* lets a caller exclude specific repo-relative paths from
    the dirtiness check — used by the migrator to ignore its own
    artefacts (e.g. ``_pipeline/.migration-plan.json``) that a prior
    ``assess`` may have left untracked.
    """
    if not is_git_repo(path):
        raise GitUnavailable(f"not a git repo: {path}")
    r = _run(["git", "status", "--porcelain"], path)
    raw = r.stdout
    if not raw.strip():
        return False
    if not ignore_paths:
        return True
    # Porcelain format: two status chars + space + path. Strip the prefix
    # before comparing. Untracked entries appear as "?? path".
    for line in raw.splitlines():
        if len(line) < 4:
            continue
        rel = line[3:].strip()
        # Handle rename-format "OLD -> NEW"; compare the new path.
        if " -> " in rel:
            rel = rel.split(" -> ", 1)[1]
        if rel not in ignore_paths:
            return True
    return False


def head_content(path: Path, rel_path: str) -> str | None:
    """Return *rel_path*'s content as committed at HEAD, or ``None``.

    ``None`` covers every case where there's nothing safe to recover: not a
    git repo, no commits yet, or the path wasn't tracked at HEAD (i.e. it's
    new this cycle, not a rewrite of something that already existed). Used to
    recover a note's last-known-good body when a rejected rewrite has already
    overwritten it on disk — see ``orchestrator._quarantine_rejected_notes``.
    """
    if not is_git_repo(path):
        return None
    r = _run(["git", "show", f"HEAD:{rel_path}"], path)
    if r.returncode != 0:
        return None
    return r.stdout


def snapshot_commit(
    path: Path,
    *,
    message: str,
    force_paths: list[str] | None = None,
) -> str | None:
    """Stage everything and commit. Returns the new commit SHA or None if nothing to commit.

    If *force_paths* is given, also force-add those repo-relative paths (using
    ``git add -f``) so that paths normally excluded by ``.gitignore`` are still
    captured. This is required for the migrator's pre/post boundary to work on
    vaults whose ``.gitignore`` excludes the framework files the migrator
    writes.
    """
    if not is_git_repo(path):
        raise GitUnavailable(f"not a git repo: {path}")
    _run(["git", "add", "-A"], path)
    if force_paths:
        existing = [p for p in force_paths if (path / p).exists()]
        if existing:
            _run(["git", "add", "-f", "--", *existing], path)
    status = _run(["git", "status", "--porcelain"], path)
    if not status.stdout.strip():
        return None
    commit = _run(["git", "commit", "-q", "-m", message], path)
    if commit.returncode != 0:
        raise GitUnavailable(
            f"git commit failed: {commit.stderr.strip() or commit.stdout.strip()}"
        )
    rev = _run(["git", "rev-parse", "HEAD"], path)
    return rev.stdout.strip() if rev.returncode == 0 else None
