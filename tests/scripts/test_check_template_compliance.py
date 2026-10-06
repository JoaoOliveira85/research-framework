"""Tests for scripts/check_template_compliance.py — template section compliance."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).parent.parent.parent / "scripts" / "check_template_compliance.py"
)


def run_script(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def test_compliant_note_passes(tmp_vault_dir: Path) -> None:
    """Keeping only Valid Concept should pass template compliance."""
    concepts = tmp_vault_dir / "data_vault" / "01 - Concepts"
    for note in concepts.iterdir():
        if note.name != "Valid Concept.md":
            note.unlink()
    result = run_script(str(tmp_vault_dir))
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"


def test_missing_section_fails(tmp_vault_dir: Path) -> None:
    """Missing Section fixture triggers exit 1 naming the section."""
    concepts = tmp_vault_dir / "data_vault" / "01 - Concepts"
    for note in concepts.iterdir():
        if note.name != "Missing Section.md":
            note.unlink()
    result = run_script(str(tmp_vault_dir))
    assert result.returncode == 1
    assert "Missing Section.md" in result.stdout
    assert "Relationships" in result.stdout


def test_templates_dir_missing(tmp_vault_dir: Path) -> None:
    """Vault without _templates dir exits 2."""
    import shutil

    shutil.rmtree(tmp_vault_dir / "_templates")
    result = run_script(str(tmp_vault_dir))
    assert result.returncode == 2


def test_vault_not_found() -> None:
    """Non-existent vault exits 2."""
    result = run_script("/tmp/research_framework-nonexistent-vault-xyz")
    assert result.returncode == 2


def test_a_directory_without_data_vault_is_an_abort_not_a_pass(tmp_path: Path) -> None:
    """A wrong path — the parent folder, `data_vault/` itself — is not a vault.

    The script printed "all notes comply with their templates" and exited 0
    having read no note.
    """
    for args in ([str(tmp_path)], [str(tmp_path), "--check-version"]):
        result = run_script(*args)
        assert result.returncode == 2, f"stdout={result.stdout}"
        assert "data_vault directory not found" in result.stderr
        assert "all notes" not in result.stdout


# ---------------------------------------------------------------------------
# --check-version (M5)
# ---------------------------------------------------------------------------


def _build_versioned_vault(
    tmp_path: Path, *, template_version: str, note_version: str
) -> Path:
    """Minimal vault with one ``concept`` template + one note.

    ``template_version`` is stamped on the ``_templates/concept.md`` template,
    ``note_version`` on the single note in ``data_vault/01 - Concepts/``.
    """
    vault = tmp_path / "v"
    (vault / "_templates").mkdir(parents=True)
    (vault / "data_vault" / "01 - Concepts").mkdir(parents=True)

    (vault / "_templates" / "concept.md").write_text(
        "---\n"
        "type: concept\n"
        f'template_version: "{template_version}"\n'
        "---\n\n"
        "# {{ title }}\n\n"
        "## Overview\n\n",
        encoding="utf-8",
    )
    (vault / "data_vault" / "01 - Concepts" / "note.md").write_text(
        "---\n"
        'title: "Note"\n'
        "type: concept\n"
        f'template_version: "{note_version}"\n'
        "---\n\n"
        "## Overview\n\nBody here.\n",
        encoding="utf-8",
    )
    return vault


def test_check_version_passes_when_versions_match(tmp_path: Path) -> None:
    vault = _build_versioned_vault(
        tmp_path, template_version="1.0.0", note_version="1.0.0"
    )
    result = run_script(str(vault), "--check-version")
    assert result.returncode == 0, result.stdout
    assert "all notes match their template version" in result.stdout


def test_check_version_flags_outdated_note(tmp_path: Path) -> None:
    vault = _build_versioned_vault(
        tmp_path, template_version="1.1.0", note_version="1.0.0"
    )
    result = run_script(str(vault), "--check-version")
    assert result.returncode == 1
    assert "OUTDATED" in result.stdout
    assert "note.md" in result.stdout
    assert "note=1.0.0" in result.stdout
    assert "template=1.1.0" in result.stdout


def test_check_version_flags_missing_version_stamp(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    (vault / "_templates").mkdir(parents=True)
    (vault / "data_vault" / "01 - Concepts").mkdir(parents=True)
    (vault / "_templates" / "concept.md").write_text(
        '---\ntype: concept\ntemplate_version: "1.0.0"\n---\n\n## Overview\n',
        encoding="utf-8",
    )
    (vault / "data_vault" / "01 - Concepts" / "legacy.md").write_text(
        '---\ntitle: "L"\ntype: concept\n---\n\n## Overview\n\nBody.\n',
        encoding="utf-8",
    )
    result = run_script(str(vault), "--check-version")
    assert result.returncode == 1
    assert "OUTDATED" in result.stdout
    assert "note=(missing)" in result.stdout


def test_check_version_skips_unknown_types(tmp_path: Path) -> None:
    """A note whose type has no template is reported by the section check,
    not the version check — version check keeps quiet for those.
    """
    vault = tmp_path / "v"
    (vault / "_templates").mkdir(parents=True)
    (vault / "data_vault" / "99 - Unknown").mkdir(parents=True)
    (vault / "_templates" / "concept.md").write_text(
        '---\ntype: concept\ntemplate_version: "1.0.0"\n---\n\n## Overview\n',
        encoding="utf-8",
    )
    (vault / "data_vault" / "99 - Unknown" / "x.md").write_text(
        '---\ntitle: "x"\ntype: ghost\n---\n\n## Overview\n',
        encoding="utf-8",
    )
    result = run_script(str(vault), "--check-version")
    assert "ghost" in result.stdout or "unknown" in result.stdout.lower()
