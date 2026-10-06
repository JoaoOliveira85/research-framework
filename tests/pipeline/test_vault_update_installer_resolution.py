"""`./vault update` must run the END-USER installer, not the maintainer's.

The update verb fetches the framework as a **git archive** and then runs
`<archive>/install.sh` against the vault. In a git archive, the file at that
path is the *maintainer dev-setup* script — it ignores its arguments and runs
`pip install -e ".[dev]"`, which with CWD set to the vault (where `./vault`
runs) tries to install the operator's vault as a Python project:

    ERROR: file:///…/community-vault does not appear to be a Python
    project: neither 'setup.py' nor 'pyproject.toml' found.

The end-user installer — the one that takes the vault as `$1` and refreshes
vault scaffolding — lives at `dist-templates/install.sh`. Only in a *release
tarball* is it at the archive root.

Net effect before this fix: vault-local `scripts/` and `_templates/` were never
refreshed by any update, version bump or not. It was mistaken for a
`--force` short-circuit problem; that was a second, smaller bug.
"""

from __future__ import annotations

from pathlib import Path

from research_framework.pipeline.vault_update import resolve_installer

_MAINTAINER = """#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
"""

_END_USER = """#!/usr/bin/env bash
# research-framework — end-user installer (bundled with every release tarball).
TARGET="${POSITIONAL_TARGET:-${VAULT_DIR:-${ROOT_DIR}}}"
"""


def _archive(tmp: Path, *, root: str | None, dist: str | None) -> Path:
    a = tmp / "archive"
    a.mkdir()
    if root is not None:
        (a / "install.sh").write_text(root, encoding="utf-8")
    if dist is not None:
        (a / "dist-templates").mkdir()
        (a / "dist-templates" / "install.sh").write_text(dist, encoding="utf-8")
    return a


def test_git_archive_shape_prefers_dist_templates(tmp_path: Path) -> None:
    """The real-world case: both exist, and root is the maintainer script."""
    a = _archive(tmp_path, root=_MAINTAINER, dist=_END_USER)
    assert resolve_installer(a) == a / "dist-templates" / "install.sh"


def test_release_tarball_shape_uses_root(tmp_path: Path) -> None:
    """A release tarball ships the end-user installer at the root."""
    a = _archive(tmp_path, root=_END_USER, dist=None)
    assert resolve_installer(a) == a / "install.sh"


def test_maintainer_script_alone_is_refused(tmp_path: Path) -> None:
    """Better to warn that scaffolding was not refreshed than to run this."""
    a = _archive(tmp_path, root=_MAINTAINER, dist=None)
    assert resolve_installer(a) is None


def test_no_installer_at_all(tmp_path: Path) -> None:
    assert resolve_installer(_archive(tmp_path, root=None, dist=None)) is None


def test_dist_templates_wins_even_if_root_looks_fine(tmp_path: Path) -> None:
    """dist-templates/ is authoritative when present — no ambiguity."""
    a = _archive(tmp_path, root=_END_USER, dist=_END_USER)
    assert resolve_installer(a) == a / "dist-templates" / "install.sh"


def test_this_repo_resolves_to_dist_templates() -> None:
    """Guard against the repo layout drifting away from the assumption."""
    repo = Path(__file__).resolve().parents[2]
    assert resolve_installer(repo) == repo / "dist-templates" / "install.sh"
