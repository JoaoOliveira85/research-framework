"""CLI tests for scripts/prune_research_branches.py (issue #307).

`tests/pipeline/test_branch_retention.py` covers the underlying
`pipeline.branch_retention` module directly; this file only checks the
standalone CLI wrapper's argument handling and output shape end to end,
mirroring `tests/scripts/test_preflight_sources.py`'s pattern for a shipped
`scripts/*.py` maintenance CLI.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "prune_research_branches.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    assert SCRIPT.is_file(), f"expected {SCRIPT} to exist"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _make_repo_with_branches(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    _git("init", "-b", "main", cwd=vault)
    _git("config", "user.email", "t@t.com", cwd=vault)
    _git("config", "user.name", "t", cwd=vault)
    (vault / "f0.txt").write_text("x\n", encoding="utf-8")
    _git("add", "-A", cwd=vault)
    _git("commit", "-m", "initial", cwd=vault)

    # A landed branch (hand-rolled marker, matching vault_commit's format).
    _git("branch", "research/2026-01-01-0000", cwd=vault)
    (vault / "f1.txt").write_text("x\n", encoding="utf-8")
    _git("add", "-A", cwd=vault)
    _git(
        "commit",
        "-m",
        "research run: t\n\n**Branch:** research/2026-01-01-0000\n",
        cwd=vault,
    )

    # An unlanded branch — no landing commit anywhere on main.
    _git("branch", "research/2026-02-01-0000", cwd=vault)
    return vault


def test_script_exists() -> None:
    assert SCRIPT.is_file()


def test_list_reports_landed_and_unlanded(tmp_path: Path) -> None:
    vault = _make_repo_with_branches(tmp_path)
    proc = _run(str(vault), "list")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "research/2026-01-01-0000\tlanded" in proc.stdout
    assert "research/2026-02-01-0000\tUNLANDED" in proc.stdout


def test_list_on_a_vault_with_no_research_branches(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _git("init", "-b", "main", cwd=vault)
    _git("config", "user.email", "t@t.com", cwd=vault)
    _git("config", "user.name", "t", cwd=vault)
    (vault / "f.txt").write_text("x\n", encoding="utf-8")
    _git("add", "-A", cwd=vault)
    _git("commit", "-m", "initial", cwd=vault)

    proc = _run(str(vault), "list")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "no research/* branches" in proc.stdout


def test_prune_dry_run_by_default_deletes_nothing(tmp_path: Path) -> None:
    vault = _make_repo_with_branches(tmp_path)
    proc = _run(str(vault), "prune", "--keep-last", "0")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "would delete: research/2026-01-01-0000" in proc.stdout
    assert "pass --yes to actually delete" in proc.stdout

    branches = subprocess.run(
        ["git", "branch", "--list", "research/*"],
        cwd=str(vault),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "research/2026-01-01-0000" in branches  # still there


def test_prune_yes_deletes_only_the_landed_branch(tmp_path: Path) -> None:
    vault = _make_repo_with_branches(tmp_path)
    proc = _run(str(vault), "prune", "--keep-last", "0", "--yes")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "deleted: research/2026-01-01-0000" in proc.stdout
    assert "kept (unlanded, never touched): research/2026-02-01-0000" in proc.stdout

    branches = subprocess.run(
        ["git", "branch", "--list", "research/*"],
        cwd=str(vault),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "research/2026-01-01-0000" not in branches
    assert "research/2026-02-01-0000" in branches


def test_rejects_non_directory_vault(tmp_path: Path) -> None:
    proc = _run(str(tmp_path / "does-not-exist"), "list")
    assert proc.returncode == 2
    assert "not a directory" in proc.stderr


# ---------------------------------------------------------------------------
# Issue #307 / D10: the manual verb keeps working and now carries the age
# rule; its defaults come from the vault's own settings, not a hardcoded 5.
# ---------------------------------------------------------------------------


def _write_settings(vault: Path, text: str) -> None:
    (vault / "settings.yaml").write_text(text, encoding="utf-8")
    _git("add", "settings.yaml", cwd=vault)
    _git("commit", "-m", "test: settings", cwd=vault)


def test_prune_defaults_come_from_the_vault_settings(tmp_path: Path) -> None:
    vault = _make_repo_with_branches(tmp_path)
    _write_settings(vault, "vault_commit:\n  retention:\n    keep_last: 0\n")
    proc = _run(str(vault), "prune")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "would delete: research/2026-01-01-0000 (cap)" in proc.stdout
    assert "keep_last=0" in proc.stdout


def test_prune_max_age_days_flag(tmp_path: Path) -> None:
    vault = _make_repo_with_branches(tmp_path)
    # The landed branch's tip is dated "now": a 1-day ceiling keeps it, so a
    # cap of 0 is what would delete it — and the reason column must say cap,
    # not age.
    proc = _run(str(vault), "prune", "--keep-last", "0", "--max-age-days", "1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "would delete: research/2026-01-01-0000 (cap)" in proc.stdout
    assert "max_age_days=1" in proc.stdout


def test_prune_rejects_invalid_max_age(tmp_path: Path) -> None:
    vault = _make_repo_with_branches(tmp_path)
    proc = _run(str(vault), "prune", "--max-age-days", "0")
    assert proc.returncode == 2
    assert "max-age-days" in proc.stderr


def test_list_shows_age_in_days(tmp_path: Path) -> None:
    vault = _make_repo_with_branches(tmp_path)
    proc = _run(str(vault), "list")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "age=0d" in proc.stdout
