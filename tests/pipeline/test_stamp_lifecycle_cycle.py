"""Regression test for B.2 — `_stamp_lifecycle_cycle` (spec 050 post-mortem).

Pre-0.7.0 nothing wrote ``lifecycle.created_at_cycle`` on freshly-authored
notes, so the orchestrator's cycle-attribution logic
(``_parse_note_created_at_cycle``) silently returned None for every note
and downstream consumers (coverage updates, deferred-work lists,
cycle-summary writer) underweighted. This test pins the helper that
backfills the field at note-write time.
"""

from __future__ import annotations

from pathlib import Path

from research_framework.pipeline._helpers.state import _stamp_lifecycle_cycle


def _write_note(path: Path, frontmatter: str, body: str = "body\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")


def test_stamps_field_when_missing(tmp_path: Path) -> None:
    note = tmp_path / "n1.md"
    _write_note(note, "title: Hello\ntype: concept\n")
    stamped = _stamp_lifecycle_cycle([note], cycle_num=5)
    assert stamped == 1
    text = note.read_text(encoding="utf-8")
    assert "lifecycle:" in text
    assert "created_at_cycle: 5" in text


def test_respects_pre_existing_value(tmp_path: Path) -> None:
    note = tmp_path / "n2.md"
    _write_note(
        note,
        "title: Hello\nlifecycle:\n  created_at_cycle: 2\n",
    )
    stamped = _stamp_lifecycle_cycle([note], cycle_num=5)
    assert stamped == 0
    assert "created_at_cycle: 2" in note.read_text(encoding="utf-8")


def test_skips_inline_lifecycle_with_field(tmp_path: Path) -> None:
    note = tmp_path / "n3.md"
    _write_note(note, "title: H\nlifecycle: {created_at_cycle: 7, archived: false}\n")
    stamped = _stamp_lifecycle_cycle([note], cycle_num=5)
    assert stamped == 0


def test_ignores_non_markdown_and_missing_files(tmp_path: Path) -> None:
    missing = tmp_path / "no-such.md"
    no_frontmatter = tmp_path / "raw.md"
    no_frontmatter.write_text("just a body\n", encoding="utf-8")
    stamped = _stamp_lifecycle_cycle([missing, no_frontmatter], cycle_num=1)
    assert stamped == 0


def test_only_stamps_files_in_supplied_list(tmp_path: Path) -> None:
    """Helper must NOT walk the vault — it only touches the explicit list."""
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    _write_note(a, "title: A\n")
    _write_note(b, "title: B\n")
    stamped = _stamp_lifecycle_cycle([a], cycle_num=3)
    assert stamped == 1
    assert "created_at_cycle: 3" in a.read_text(encoding="utf-8")
    assert "created_at_cycle" not in b.read_text(encoding="utf-8")
