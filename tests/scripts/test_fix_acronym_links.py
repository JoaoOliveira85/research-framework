"""Tests for scripts/fix_acronym_links.py — the first-occurrence wikilink fixer."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "fix_acronym_links.py"


def run_script(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def _vault_defining_ka(tmp_path: Path) -> Path:
    """A vault whose one note registers the acronym KA through its title."""
    vault = tmp_path / "vault"
    concepts = vault / "data_vault" / "01 - Concepts"
    concepts.mkdir(parents=True)
    (concepts / "Known Acronym (KA).md").write_text(
        "---\ntitle: Known Acronym (KA)\ntype: concept\n---\n\n"
        "The [[KA]] is linked here.\n",
        encoding="utf-8",
    )
    return vault


def test_apply_links_the_body_not_a_frontmatter_value_below_dashes(
    tmp_path: Path,
) -> None:
    """A `---` inside a value is not the closing delimiter.

    The fixer split on the first `---` substring, so a slug URL ended the
    frontmatter there and the rest of it counted as body. The first bare
    acronym in that rest was wikilinked — `summary: [[KA]] in practice`, which
    no longer parses as YAML — and the body's occurrence was left bare.
    """
    vault = _vault_defining_ka(tmp_path)
    note = vault / "data_vault" / "01 - Concepts" / "Usage.md"
    frontmatter = (
        "---\n"
        "title: Usage\n"
        "source_urls:\n"
        "- https://example.com/kafka---a-guide\n"
        "summary: KA in practice\n"
        "---\n"
    )
    note.write_text(frontmatter + "\nKA is used here.\n", encoding="utf-8")

    result = run_script(str(vault), "--apply")

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert note.read_text(encoding="utf-8") == (
        frontmatter + "\n[[KA]] is used here.\n"
    )


def test_apply_links_the_occurrence_the_checker_flagged(tmp_path: Path) -> None:
    """The checker skips code, URLs and `(KA)` definitions; so must the fixer.

    The fixer linked the first raw occurrence instead. In the defining note
    that was the heading's `(KA)`: `# Known Acronym ([[KA]])` satisfied the
    checker, exit 0, and the prose it had flagged stayed bare. Without the
    heading the URL came next, `https://example.com/[[KA]]/intro`.
    """
    vault = tmp_path / "vault"
    concepts = vault / "data_vault" / "01 - Concepts"
    concepts.mkdir(parents=True)
    note = concepts / "Known Acronym (KA).md"
    head = "---\ntitle: Known Acronym (KA)\ntype: concept\n---\n\n"
    excluded = (
        "# Known Acronym (KA)\n\n"
        "See https://example.com/KA/intro and `KA` and:\n\n"
        "```\nKA = 1\n```\n\n"
    )
    note.write_text(head + excluded + "KA is used here.\n", encoding="utf-8")

    result = run_script(str(vault), "--apply")

    assert result.returncode == 0, result.stdout + result.stderr
    assert note.read_text(encoding="utf-8") == (
        head + excluded + "[[KA]] is used here.\n"
    )


def test_a_directory_without_data_vault_is_an_abort_not_a_pass(tmp_path: Path) -> None:
    """The fixer reads the vault through the checker, and must not answer
    "no unlinked acronyms to fix" for a folder that holds no corpus."""
    result = run_script(str(tmp_path), "--apply")
    assert result.returncode == 2, f"stdout={result.stdout}"
    assert "data_vault directory not found" in result.stderr
