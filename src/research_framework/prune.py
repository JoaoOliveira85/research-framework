"""research_framework prune — safely remove vault-local scripts superseded by the framework.

Entry point: prune_vault(vault_root, keep, yes, force)

Snapshot boundary:
  1. Pre-prune snapshot commit (force-adds the prune targets so a reset to it
     restores them). Created with --allow-empty to guarantee two boundary commits
     even when the working tree is already clean.
  2. os.unlink each pruneable file.
  3. Post-prune snapshot commit.

Rollback: git -C <vault> reset --hard <pre-prune snapshot sha>
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .migration.superseded_paths import superseded_paths_present
from .pipeline.vault_git import (
    GitUnavailable,
    is_git_repo,
    snapshot_commit,
    working_tree_dirty,
)

__all__ = ["prune_vault", "PruneResult"]


class PruneResult:
    """Outcome of a prune run."""

    def __init__(
        self,
        removed: list[str],
        skipped: list[str],
        pre_sha: str | None,
        post_sha: str | None,
        smoke_ok: bool,
        smoke_warning: str | None,
        declined: bool = False,
    ) -> None:
        self.removed = removed
        self.declined = declined
        self.skipped = skipped
        self.pre_sha = pre_sha
        self.post_sha = post_sha
        self.smoke_ok = smoke_ok
        self.smoke_warning = smoke_warning


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def _pre_snapshot_commit(
    vault_root: Path, prune_paths: list[str], message: str
) -> str | None:
    """Create a pre-prune snapshot commit, always (--allow-empty if tree is clean).

    Force-adds the prune target paths so they are captured in git even if
    they would otherwise be gitignored. This guarantees that resetting to the
    returned commit restores the pruned files.

    Returns the new commit SHA, or None if git is unavailable.
    """
    if not is_git_repo(vault_root):
        return None

    # Stage everything currently pending
    _run(["git", "add", "-A"], vault_root)
    # Force-add the prune targets (ensures they're tracked even if gitignored)
    existing = [p for p in prune_paths if (vault_root / p).exists()]
    if existing:
        add = _run(["git", "add", "-f", "--", *existing], vault_root)
        if add.returncode != 0:
            # The commit below is --allow-empty, so it would succeed without
            # the targets and prune would delete files no commit holds.
            raise GitUnavailable(
                "git add failed for the prune targets: "
                f"{add.stderr.strip() or add.stdout.strip()}"
            )

    # Always commit, even if nothing staged, so the rollback target exists
    commit = _run(
        ["git", "commit", "--allow-empty", "-q", "-m", message],
        vault_root,
    )
    if commit.returncode != 0:
        raise GitUnavailable(
            f"git commit failed: {commit.stderr.strip() or commit.stdout.strip()}"
        )
    rev = _run(["git", "rev-parse", "HEAD"], vault_root)
    return rev.stdout.strip() if rev.returncode == 0 else None


def _run_smoke_test(vault_root: Path) -> tuple[bool, str | None]:
    """Run `research_framework coverage --vault <vault>` as a smoke test.

    Returns (ok, warning_message).  Exit 1 ("coverage not met") is normal for
    a vault mid-run; exit 2 is a crash we warn about.
    """
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "research_framework",
                "coverage",
                "--vault",
                str(vault_root),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Exit 1 means "coverage not met" — normal; exit 2 is a crash.
        if result.returncode == 2:
            return (
                False,
                f"post-prune smoke test returned exit 2: {result.stderr.strip()[:200]}",
            )
        return True, None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return False, f"post-prune smoke test could not run: {exc}"


def prune_vault(
    vault_root: Path,
    *,
    keep: list[str] | None = None,
    yes: bool = False,
    force: bool = False,
) -> PruneResult:
    """Remove vault-local scripts superseded by the framework.

    Parameters
    ----------
    vault_root:
        Absolute path to the vault root.
    keep:
        Repo-relative paths to exclude from deletion (e.g. ``["scripts/collect_rss.py"]``).
    yes:
        Skip the interactive confirmation prompt.
    force:
        Proceed even if the git working tree is dirty.

    Raises
    ------
    RuntimeError
        If the vault working tree is dirty and *force* is False, or the
        pre-prune snapshot commit fails (nothing is deleted).
    ValueError
        If *vault_root* is not a recognisable vault directory.
    """
    keep_set: set[str] = set(keep or [])

    # --- Validate vault -------------------------------------------------------
    if not vault_root.exists() or not vault_root.is_dir():
        raise ValueError(f"not a directory: {vault_root}")

    corpus_dir = "data_vault"
    if not (vault_root / corpus_dir).exists():
        # Try corpus_dir from spec-parse.json
        import json

        sp = vault_root / "_pipeline" / "spec-parse.json"
        if sp.exists():
            try:
                corpus_dir = json.loads(sp.read_text()).get(
                    "vault_corpus_dir", "data_vault"
                )
            except (json.JSONDecodeError, OSError):
                pass
        if not (vault_root / corpus_dir).exists():
            raise ValueError(f"not a vault (no {corpus_dir}/ directory): {vault_root}")

    # --- Dirty-tree guard -----------------------------------------------------
    if not force and is_git_repo(vault_root) and working_tree_dirty(vault_root):
        raise RuntimeError(
            f"vault working tree is dirty at {vault_root}; "
            "commit/stash first or pass --force."
        )

    # --- Compute prune list ---------------------------------------------------
    candidates = superseded_paths_present(vault_root)
    pruneable = [(p, m) for p, m in candidates if p not in keep_set]
    skipped = [p for p, _ in candidates if p in keep_set]

    if not pruneable:
        print("[prune] nothing to prune")
        return PruneResult(
            removed=[],
            skipped=skipped,
            pre_sha=None,
            post_sha=None,
            smoke_ok=True,
            smoke_warning=None,
        )

    # --- List and confirm -----------------------------------------------------
    print(
        f"[prune] About to delete {len(pruneable)} vault-local file(s) "
        "superseded by framework modules:"
    )
    for rel, module in pruneable:
        print(f"  {rel}  →  {module}")

    if skipped:
        print(f"[prune] Keeping (--keep): {', '.join(skipped)}")

    if not yes:
        try:
            answer = input("Proceed? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print("[prune] aborted")
            # Spec 077 D4/T003: "the operator said no" is a distinct outcome
            # from "there was nothing to prune", and a caller that cannot tell
            # them apart will report a prune that never happened. It is the
            # caller that maps this to an exit code.
            return PruneResult(
                removed=[],
                skipped=skipped,
                pre_sha=None,
                post_sha=None,
                smoke_ok=True,
                smoke_warning=None,
                declined=True,
            )

    prune_paths = [p for p, _ in pruneable]

    # --- Pre-snapshot (always commit, even if tree clean) ---------------------
    pre_sha: str | None = None
    if is_git_repo(vault_root):
        try:
            pre_sha = _pre_snapshot_commit(
                vault_root,
                prune_paths,
                "prune: pre-prune snapshot",
            )
            print(f"[prune] pre-prune snapshot → {pre_sha}")
        except GitUnavailable as exc:
            # The snapshot is the only copy of a gitignored or uncommitted
            # target; deleting without it is unrecoverable.
            raise RuntimeError(
                f"pre-prune git snapshot failed, nothing deleted: {exc}"
            ) from exc

    # --- Delete ---------------------------------------------------------------
    removed: list[str] = []
    for rel in prune_paths:
        abs_path = vault_root / rel
        try:
            os.unlink(abs_path)
            print(f"[prune] rm {rel}")
            removed.append(rel)
        except OSError as exc:
            print(f"[prune] WARNING: could not remove {rel}: {exc}", file=sys.stderr)

    # --- Post-snapshot --------------------------------------------------------
    post_sha: str | None = None
    if is_git_repo(vault_root):
        try:
            post_sha = snapshot_commit(
                vault_root,
                message=f"prune: removed {len(removed)} framework-superseded scripts",
            )
            print(f"[prune] post-prune snapshot → {post_sha or '(nothing to commit)'}")
        except GitUnavailable as exc:
            print(
                f"[prune] WARNING: post-prune git snapshot failed: {exc}",
                file=sys.stderr,
            )

    # --- Smoke test -----------------------------------------------------------
    smoke_ok, smoke_warning = _run_smoke_test(vault_root)
    if not smoke_ok and smoke_warning:
        print(f"[prune] WARNING: {smoke_warning}", file=sys.stderr)

    print(f"\n[prune] done. Removed {len(removed)} file(s).")
    if pre_sha:
        # The snapshot commit itself, not HEAD~2: gitignored targets exist only
        # in the snapshot, and HEAD~2 is one commit too far when the
        # post-prune commit had nothing to record.
        print(f"[prune] Rollback: git -C {vault_root} reset --hard {pre_sha}")

    return PruneResult(
        removed=removed,
        skipped=skipped,
        pre_sha=pre_sha,
        post_sha=post_sha,
        smoke_ok=smoke_ok,
        smoke_warning=smoke_warning,
    )
