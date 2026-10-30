"""Issue #45: agent-written notes with unquoted ``: `` are repaired in-cycle,
and an unrepairable block FAILs SG-005 with the YAML error (no silent skip)."""

from __future__ import annotations

from pathlib import Path

from research_framework.pipeline._helpers.state import _repair_note_frontmatter
from research_framework.pipeline.gates_step import SG005_frontmatter_completeness
from research_framework.pipeline.wikilinks import _write_redirect_stub
from research_framework.vault.frontmatter import parse_frontmatter

_BAD = (
    "---\n"
    "coverage_category: Concepts\n"
    "source_urls:\n"
    "  - https://example.com\n"
    "summary: HTTP Strict Transport Security: a response header.\n"
    "---\n"
    "Body\n"
)


def test_repair_makes_note_pass_sg005(tmp_path: Path) -> None:
    note = tmp_path / "HSTS.md"
    note.write_text(_BAD, encoding="utf-8")
    assert SG005_frontmatter_completeness([note]).status == "FAIL"
    assert _repair_note_frontmatter([note]) == [note]
    assert SG005_frontmatter_completeness([note]).status == "PASS"
    fm, _ = parse_frontmatter(note)
    assert fm["summary"] == "HTTP Strict Transport Security: a response header."
    assert _repair_note_frontmatter([note]) == []


def test_unrepairable_note_fails_sg005_naming_yaml_error(tmp_path: Path) -> None:
    note = tmp_path / "Bad.md"
    note.write_text(
        "---\ncoverage_category: C\nsummary: ok\ntags: [unclosed\n---\nB\n",
        encoding="utf-8",
    )
    assert _repair_note_frontmatter([note]) == []
    result = SG005_frontmatter_completeness([note])
    assert result.status == "FAIL"
    assert "valid YAML frontmatter" in (result.correction_hint or "")


def test_redirect_stub_frontmatter_survives_colon_in_stem(tmp_path: Path) -> None:
    folder = tmp_path / "data_vault" / "01 - Concepts"
    folder.mkdir(parents=True)
    stem = "HSTS: Strict Transport"
    (folder / f"{stem}.md").write_text("---\ntitle: x\n---\nb\n", encoding="utf-8")
    assert _write_redirect_stub(tmp_path, "HSTS", stem) is True
    fm, _ = parse_frontmatter(folder / "hsts.md")
    assert fm["redirect_to"] == stem
