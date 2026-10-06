"""Shared CLI helpers."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def force_line_buffered_stdio() -> None:
    """Reconfigure stdout/stderr to line-buffered mode (see cli.py history)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
        except (AttributeError, OSError, ValueError):
            pass


def _run_phase1_gate(vault_dir: Path) -> int | None:
    """Run the generator's own `scripts/` test suite.

    Returns:
        ``None`` when the gate was skipped (running from an installed
        wheel — see below), the subprocess exit code otherwise.

    This gate is a **development-time** safety net: it re-runs the
    generator's `tests/scripts/` suite against the scripts we just copied
    into the new vault, guarding against a maintainer shipping a broken
    script bundle. End users running from the installed wheel should
    never hit it, because:

      1. The wheel does not ship `tests/` — `parents[2]` in production
         resolves to `site-packages/`, which has no test sources.
      2. `pytest` is not in the end-user runtime dependency set; we don't
         force every vault to carry a test runner.

    So we detect "installed package" mode by checking for the test
    directory, and skip cleanly in that case. CI / developer runs (where
    `parents[2]` is the repo root and `tests/scripts/` exists) still get
    the full gate behaviour they've always had.
    """
    import research_framework.cli as cli_pkg

    cli_path = Path(cli_pkg.__file__).resolve()
    if cli_path.name == "__init__.py":
        repo_root = cli_path.parent.parent.parent.parent
    else:
        # Tests patch ``cli.__file__`` to a synthetic ``cli.py`` path.
        repo_root = cli_path.parent.parent
    scripts_tests = repo_root / "tests" / "scripts"
    if not scripts_tests.is_dir():
        print(
            "[phase 1 gate] skipped (installed package — gate only runs "
            "in development mode)"
        )
        return None
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/scripts/", "-v"],
        cwd=repo_root,
    )
    return result.returncode


def _git_init(vault_dir: Path, name: str) -> None:
    """Phase-3 git commit: record final state after all cycles succeeded.

    Idempotent w.r.t. `scaffold._init_vault_git`, which already `git
    init`s and commits the scaffold baseline. Here we only `git add` +
    commit *new* changes accumulated during cycles, and no-op cleanly
    when the tree is clean.
    """
    import shutil

    if not shutil.which("git"):
        print("[phase 3] git not found; skipping git init")
        return
    if not (vault_dir / ".git").exists():
        # Scaffold's init didn't run (e.g. git absent at scaffold time).
        subprocess.run(["git", "init"], cwd=vault_dir, check=False)
    subprocess.run(["git", "add", "."], cwd=vault_dir, check=False)
    # If nothing new to commit, `git commit` exits non-zero; that's fine.
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=research-framework@local",
            "-c",
            "user.name=research-framework",
            "commit",
            "-m",
            f"Phase 3 complete: {name}",
        ],
        cwd=vault_dir,
        check=False,
        capture_output=True,
    )
