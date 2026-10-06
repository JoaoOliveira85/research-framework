"""Tests for scripts/validate_vault.py — vault note quality validation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "validate_vault.py"


def run_script(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def test_valid_concept_passes(tmp_vault_dir: Path) -> None:
    """A vault containing only the Valid Concept fixture exits 0."""
    # Remove all negative fixtures — keep only Valid Concept
    concepts = tmp_vault_dir / "data_vault" / "01 - Concepts"
    for note in concepts.iterdir():
        if note.name != "Valid Concept.md":
            note.unlink()
    # Remove the _pipeline state (not the vault itself)
    result = run_script(str(tmp_vault_dir))
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"


def test_a_frontmatter_value_containing_dashes_is_not_a_delimiter(
    tmp_vault_dir: Path,
) -> None:
    """A slug URL (``valid---concept``) does not end the frontmatter."""
    concepts = tmp_vault_dir / "data_vault" / "01 - Concepts"
    for note in concepts.iterdir():
        if note.name != "Valid Concept.md":
            note.unlink()
    valid = concepts / "Valid Concept.md"
    text = valid.read_text(encoding="utf-8")
    assert "https://example.com/valid-concept" in text
    valid.write_text(
        text.replace(
            "https://example.com/valid-concept", "https://example.com/valid---concept"
        ),
        encoding="utf-8",
    )
    result = run_script(str(tmp_vault_dir))
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"


def test_missing_source_urls(tmp_vault_dir: Path) -> None:
    """Missing source_urls fixture triggers exit 1."""
    # Keep only Missing Source.md
    concepts = tmp_vault_dir / "data_vault" / "01 - Concepts"
    for note in concepts.iterdir():
        if note.name != "Missing Source.md":
            note.unlink()
    result = run_script(str(tmp_vault_dir))
    assert result.returncode == 1
    assert "Missing Source.md" in result.stdout
    assert "source_urls" in result.stdout


def test_summary_overflow(tmp_vault_dir: Path) -> None:
    """Summary > 120 chars triggers exit 1."""
    concepts = tmp_vault_dir / "data_vault" / "01 - Concepts"
    for note in concepts.iterdir():
        if note.name != "Long Summary Concept.md":
            note.unlink()
    result = run_script(str(tmp_vault_dir))
    assert result.returncode == 1
    assert "Long Summary" in result.stdout
    assert "summary" in result.stdout


def test_broken_wikilink(tmp_vault_dir: Path) -> None:
    """Unresolved wikilink in related field triggers exit 1."""
    concepts = tmp_vault_dir / "data_vault" / "01 - Concepts"
    for note in concepts.iterdir():
        if note.name != "Broken Wikilink.md":
            note.unlink()
    result = run_script(str(tmp_vault_dir))
    assert result.returncode == 1
    assert "Broken Wikilink.md" in result.stdout
    assert "related" in result.stdout or "Nonexistent Target" in result.stdout


def test_vault_not_found() -> None:
    """Non-existent vault directory exits 2."""
    result = run_script("/tmp/research_framework-nonexistent-vault-xyz")
    assert result.returncode == 2


def test_a_folder_with_no_data_vault_exits_2(tmp_path: Path) -> None:
    """A wrong but existing path (the vault's parent, ``data_vault/`` itself)
    is not a vault with nothing to check: exit 0 there passed zero notes.
    ``check_template_compliance.py`` aborts the same way (commit 3c2e99a)."""
    result = run_script(str(tmp_path))

    assert result.returncode == 2
    assert "data_vault" in result.stderr


def test_multiple_violations_reported(vault_dir: Path) -> None:
    """Full fixture vault reports multiple violations."""
    result = run_script(str(vault_dir))
    assert result.returncode == 1
    # At least 4 distinct violations in the fixture vault
    assert result.stdout.count("FAIL") >= 3


def test_skips_scaffold_index_and_templates(tmp_vault_dir: Path) -> None:
    """Generator-owned ``_index.md`` / ``_templates/*.md`` files don't FAIL.

    v0.2.20 reported 16 false-positive "missing YAML frontmatter"
    violations every cycle against the indexer outputs and the note-type
    templates (placeholder Jinja-style docs without frontmatter). v0.2.21
    teaches the walker to skip them so the report stays focused on real
    agent-written notes.
    """
    concepts = tmp_vault_dir / "data_vault" / "01 - Concepts"
    for note in concepts.iterdir():
        if note.name != "Valid Concept.md":
            note.unlink()

    data_vault = tmp_vault_dir / "data_vault"
    # Generator-owned scaffold files at the data_vault root.
    for name in ("_index.md", "_concepts.md", "_graph.md"):
        (data_vault / name).write_text(
            "# auto-generated index — no frontmatter on purpose\n",
            encoding="utf-8",
        )
    # Templates directory with a couple of placeholder-token notes.
    tmpl_dir = data_vault / "_templates"
    tmpl_dir.mkdir(exist_ok=True)
    for tname in ("concept.md", "service.md"):
        (tmpl_dir / tname).write_text(
            "# {{ title }}\n\n{{ summary }}\n", encoding="utf-8"
        )

    result = run_script(str(tmp_vault_dir))
    assert result.returncode == 0, (
        f"scaffold files leaked into validation:\nstdout={result.stdout}"
    )
    assert "_index.md" not in result.stdout
    assert "_templates" not in result.stdout
