"""Tests for scripts/check_acronym_links.py — first-occurrence wikilink enforcement."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "check_acronym_links.py"


def run_script(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def test_no_acronym_notes_passes(tmp_vault_dir: Path) -> None:
    """Vault with no acronym-title notes exits 0 trivially."""
    concepts = tmp_vault_dir / "data_vault" / "01 - Concepts"
    for note in concepts.iterdir():
        if note.name != "Valid Concept.md":
            note.unlink()
    result = run_script(str(tmp_vault_dir))
    assert result.returncode == 0


def test_unlinked_first_occurrence_fails(tmp_vault_dir: Path) -> None:
    """Unlinked Acronym (UA) fixture triggers exit 1."""
    concepts = tmp_vault_dir / "data_vault" / "01 - Concepts"
    for note in concepts.iterdir():
        if note.name != "Unlinked Acronym (UA).md":
            note.unlink()
    result = run_script(str(tmp_vault_dir))
    assert result.returncode == 1
    assert "UA" in result.stdout


def test_code_block_exclusion(tmp_path: Path) -> None:
    """Acronym appearing only inside code fences does not trigger failure."""
    vault = tmp_path / "vault"
    (vault / "data_vault" / "01 - Concepts").mkdir(parents=True)
    (vault / "_templates").mkdir()

    # A note that *defines* the acronym via its title
    (vault / "data_vault" / "01 - Concepts" / "Known Acronym (KA).md").write_text(
        "---\ntitle: Known Acronym (KA)\ntype: concept\nsummary: s\n"
        "tags: [t]\nsource_urls: [https://x]\nrelated: []\n"
        "created: 2026-04-16\nupdated: 2026-04-16\n---\n\n"
        "# Known Acronym (KA)\n\nBody. The [[KA]] appears here linked.\n"
    )

    # A note that uses the acronym only inside code block
    (vault / "data_vault" / "01 - Concepts" / "Usage.md").write_text(
        "---\ntitle: Usage\ntype: concept\nsummary: s\n"
        "tags: [t]\nsource_urls: [https://x]\nrelated: []\n"
        "created: 2026-04-16\nupdated: 2026-04-16\n---\n\n"
        "# Usage\n\n```\nKA in code block\n```\n\nNothing else.\n"
    )

    result = run_script(str(vault))
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"


def test_a_directory_without_data_vault_is_an_abort_not_a_pass(tmp_path: Path) -> None:
    """A wrong path — the parent folder, `data_vault/` itself — is not a vault.

    The script printed "all acronym first-occurrences are wikilinked" and
    exited 0 having read no note.
    """
    result = run_script(str(tmp_path))
    assert result.returncode == 2, f"stdout={result.stdout}"
    assert "data_vault directory not found" in result.stderr
    assert "all acronym" not in result.stdout
