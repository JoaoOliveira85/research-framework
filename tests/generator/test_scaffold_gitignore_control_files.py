"""The scaffold's `.gitignore` must not hide the files spec 058 warns about.

`scaffold.py` wrote `/*` plus a re-include for the corpus only, so
`research.spec.md`, `settings.yaml`, `_pipeline/research-backlog.md` and
`_pipeline/coverage-targets.json` were all git-ignored — the exact set
`vault_health.scan_control_file_git_tracking` (spec 058) then warns about. The
framework was generating the condition it warns about, and on all five of the
operator's live vaults it did: every one reported
`WARN IGNORED research.spec.md` / `settings.yaml`, and hand-edits to those
files were invisible to git.

Asserted against real `git check-ignore`, because gitignore re-inclusion has a
parent-directory rule that is easy to get wrong: a file cannot be re-included
if a parent directory is itself excluded.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

CONTROL_FILES = (
    "research.spec.md",
    "settings.yaml",
    "_pipeline/research-backlog.md",
    "_pipeline/coverage-targets.json",
)

STILL_IGNORED = (
    "scripts/agent_call.py",
    "_pipeline/sources.db",
    "_pipeline/cycles/cycle-001-scout.json",
    "raw_data/2026/01/page.html",
    "update_vault.py",
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )


@pytest.fixture
def scaffolded(tmp_path: Path) -> Path:
    """A real git repo carrying the scaffold's generated .gitignore."""
    from research_framework.generator.scaffold import _render_vault_gitignore

    repo = tmp_path / "vault"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / ".gitignore").write_text(_render_vault_gitignore("data_vault"), "utf-8")

    for rel in CONTROL_FILES + STILL_IGNORED + ("data_vault/01 - X/note.md",):
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    return repo


def _is_ignored(repo: Path, rel: str) -> bool:
    return _git(repo, "check-ignore", "-q", "--", rel).returncode == 0


@pytest.mark.parametrize("rel", CONTROL_FILES)
def test_control_files_are_tracked(scaffolded: Path, rel: str) -> None:
    """Spec 058's control files must be visible to git."""
    assert not _is_ignored(scaffolded, rel), f"{rel} is git-ignored by the scaffold"


@pytest.mark.parametrize("rel", STILL_IGNORED)
def test_regenerable_noise_stays_ignored(scaffolded: Path, rel: str) -> None:
    """The whole point of the `/*` rule is still enforced."""
    assert _is_ignored(scaffolded, rel), f"{rel} should stay out of version history"


def test_corpus_is_tracked(scaffolded: Path) -> None:
    assert not _is_ignored(scaffolded, "data_vault/01 - X/note.md")


def test_git_add_picks_up_exactly_the_intended_set(scaffolded: Path) -> None:
    """End-to-end: `git add -A` (what vault_commit runs) stages the right files."""
    _git(scaffolded, "add", "-A")
    staged = set(_git(scaffolded, "diff", "--cached", "--name-only").stdout.split())

    for rel in CONTROL_FILES:
        assert rel in staged, f"{rel} not staged"
    for rel in STILL_IGNORED:
        assert rel not in staged, f"{rel} wrongly staged"


def test_custom_corpus_dir_is_honoured(tmp_path: Path) -> None:
    from research_framework.generator.scaffold import _render_vault_gitignore

    repo = tmp_path / "v"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / ".gitignore").write_text(_render_vault_gitignore("corpus"), "utf-8")
    (repo / "corpus").mkdir()
    (repo / "corpus" / "n.md").write_text("x", encoding="utf-8")
    assert not _is_ignored(repo, "corpus/n.md")


def test_scan_control_file_git_tracking_is_silent_on_a_fresh_scaffold(
    scaffolded: Path,
) -> None:
    """The spec-058 check and the scaffold must agree (the whole point)."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from vault_health import scan_control_file_git_tracking

    _git(scaffolded, "add", "-A")
    _git(scaffolded, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i")

    assert scan_control_file_git_tracking(scaffolded) == []
