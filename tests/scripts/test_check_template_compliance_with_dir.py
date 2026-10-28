"""Template lookup reads the vault-root `_templates/` then falls back (T084, #20).

Note templates are framework-owned and live only at the vault root; a leftover
`data_vault/_templates/` is not consulted.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_template_compliance.py"


def _run(vault: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(vault)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def _write_conflicting_templates_and_note(vault: Path) -> None:
    """Vault note satisfies the root template; a stale corpus copy disagrees."""
    dv_tmpl = vault / "data_vault" / "_templates"
    root_tmpl = vault / "_templates"
    concepts = vault / "data_vault" / "concepts"
    dv_tmpl.mkdir(parents=True, exist_ok=True)
    root_tmpl.mkdir(parents=True, exist_ok=True)
    concepts.mkdir(parents=True, exist_ok=True)

    (dv_tmpl / "concept.md").write_text(
        "## Stale Corpus Section\n\n",
        encoding="utf-8",
    )
    (root_tmpl / "concept.md").write_text(
        "---\ntype: concept\n---\n\n## Custom Root Section\n\n",
        encoding="utf-8",
    )
    (concepts / "sample.md").write_text(
        "---\n"
        'title: "Sample"\n'
        "type: concept\n"
        'source_urls: ["https://example.com/a"]\n'
        'summary: "Short summary for validation."\n'
        "---\n\n"
        "## Custom Root Section\n\n"
        "Body.\n",
        encoding="utf-8",
    )


def test_reads_root_templates_and_ignores_the_corpus_copy(tmp_path: Path) -> None:
    vault = tmp_path / "v_pref"
    _write_conflicting_templates_and_note(vault)
    result = _run(vault)
    assert result.returncode == 0, (result.stdout, result.stderr)


def test_fallback_to_framework_templates_when_no_template_dirs(tmp_path: Path) -> None:
    """No `data_vault/_templates/` and no vault `/_templates/`: bundled note-type.j2.

    Pre-T086 this exits 2 (missing template dir). Post-T086 uses framework assets.
    """
    vault = tmp_path / "v_pkg"
    concepts = vault / "data_vault" / "concepts"
    concepts.mkdir(parents=True)
    (concepts / "note.md").write_text(
        "---\n"
        'title: "N"\n'
        "type: concept\n"
        'source_urls: ["https://example.com/q"]\n'
        'summary: "S for template compliance."\n'
        "---\n\n"
        "## Overview\n\n"
        "Body with enough text.\n",
        encoding="utf-8",
    )

    result = _run(vault)
    assert result.returncode == 0, (result.stdout, result.stderr)


def test_both_template_dirs_missing_exits_2_without_traceback(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "v_none"
    _write_conflicting_templates_and_note(vault)
    shutil.rmtree(vault / "data_vault" / "_templates")
    shutil.rmtree(vault / "_templates")

    result = _run(vault)
    assert result.returncode == 2
    assert "Traceback" not in result.stderr


def test_a_missing_section_is_judged_against_the_root_template(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "v_root_only"
    _write_conflicting_templates_and_note(vault)
    note = vault / "data_vault" / "concepts" / "sample.md"
    note.write_text(
        note.read_text().replace("## Custom Root Section", "## Other Heading")
    )

    result = _run(vault)

    assert result.returncode == 1, (result.stdout, result.stderr)
    assert "Custom Root Section" in result.stdout
