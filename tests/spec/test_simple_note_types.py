"""Tests for note_types support in the simple spec format (015d)."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.spec.schema import SpecValidationError
from research_framework.spec.simple import (
    _pluralise,
    expand,
    parse_simple,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_FRONTMATTER = """\
---
name: "Test Vault"
owner: "tester"
topic: "A small topic for expansion tests"
{extra}---

Body.
"""


def _write(tmp_path: Path, extra: str = "", name: str = "research.spec.md") -> Path:
    path = tmp_path / name
    path.write_text(_BASE_FRONTMATTER.format(extra=extra), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Pluralisation helper
# ---------------------------------------------------------------------------


class TestPluralise:
    def test_policy(self) -> None:
        assert _pluralise("policy") == "Policies"

    def test_process(self) -> None:
        assert _pluralise("process") == "Processes"

    def test_case(self) -> None:
        assert _pluralise("case") == "Cases"

    def test_box(self) -> None:
        assert _pluralise("box") == "Boxes"

    def test_dish(self) -> None:
        assert _pluralise("dish") == "Dishes"

    def test_source(self) -> None:
        assert _pluralise("source") == "Sources"

    def test_concept(self) -> None:
        assert _pluralise("concept") == "Concepts"

    def test_statute(self) -> None:
        assert _pluralise("statute") == "Statutes"

    def test_pitch(self) -> None:
        # ends in 'ch' → + 'es'
        assert _pluralise("pitch") == "Pitches"


# ---------------------------------------------------------------------------
# Historical default — no note_types block
# ---------------------------------------------------------------------------


class TestHistoricalDefault:
    def test_no_note_types_block_gives_concept_source(self, tmp_path: Path) -> None:
        path = _write(tmp_path, extra="")
        simple = parse_simple(path)
        assert simple.note_types == []

        spec = expand(simple, location=tmp_path / "vault")
        names = [nt.name for nt in spec.note_types]
        assert "concept" in names
        assert "source" in names

    def test_empty_note_types_list_gives_historical_default(
        self, tmp_path: Path
    ) -> None:
        path = _write(tmp_path, extra="note_types: []\n")
        simple = parse_simple(path)
        assert simple.note_types == []

        spec = expand(simple, location=tmp_path / "vault")
        names = [nt.name for nt in spec.note_types]
        assert "concept" in names
        assert "source" in names


# ---------------------------------------------------------------------------
# Short form — 10 string entries
# ---------------------------------------------------------------------------


class TestShortFormNoteTypes:
    def test_ten_string_entries_produce_ten_note_types(self, tmp_path: Path) -> None:
        extra = (
            "note_types:\n"
            "  - case\n"
            "  - statute\n"
            "  - opinion\n"
            "  - jurisdiction\n"
            "  - source\n"
            "  - brief\n"
            "  - treaty\n"
            "  - regulation\n"
            "  - policy\n"
            "  - court\n"
        )
        path = _write(tmp_path, extra=extra)
        simple = parse_simple(path)
        assert len(simple.note_types) == 10

        spec = expand(simple, location=tmp_path / "vault")
        assert len(spec.note_types) == 10

    def test_auto_numbered_folders(self, tmp_path: Path) -> None:
        extra = "note_types:\n  - case\n  - statute\n  - opinion\n"
        path = _write(tmp_path, extra=extra)
        simple = parse_simple(path)
        spec = expand(simple, location=tmp_path / "vault")

        folders = {nt.name: nt.folder for nt in spec.note_types}
        assert folders["case"] == "01 - Cases"
        assert folders["statute"] == "02 - Statutes"
        assert folders["opinion"] == "03 - Opinions"

    def test_string_names_carried_through(self, tmp_path: Path) -> None:
        extra = "note_types:\n  - concept\n  - source\n"
        path = _write(tmp_path, extra=extra)
        simple = parse_simple(path)
        spec = expand(simple, location=tmp_path / "vault")
        names = [nt.name for nt in spec.note_types]
        assert names == ["concept", "source"]


# ---------------------------------------------------------------------------
# Long form — mapping entries
# ---------------------------------------------------------------------------


class TestLongFormNoteTypes:
    def test_long_form_name_required(self, tmp_path: Path) -> None:
        extra = (
            "note_types:\n"
            "  - name: opinion\n"
            "    folder: Opinions\n"
            "    required_sections:\n"
            "      - Holding\n"
            "      - Reasoning\n"
        )
        path = _write(tmp_path, extra=extra)
        simple = parse_simple(path)
        spec = expand(simple, location=tmp_path / "vault")
        assert len(spec.note_types) == 1
        nt = spec.note_types[0]
        assert nt.name == "opinion"

    def test_long_form_custom_folder_preserved(self, tmp_path: Path) -> None:
        extra = "note_types:\n  - name: opinion\n    folder: Opinions\n"
        path = _write(tmp_path, extra=extra)
        simple = parse_simple(path)
        spec = expand(simple, location=tmp_path / "vault")
        nt = spec.note_types[0]
        assert nt.folder == "Opinions"

    def test_long_form_required_sections_carried_through(self, tmp_path: Path) -> None:
        extra = (
            "note_types:\n"
            "  - name: opinion\n"
            "    folder: Opinions\n"
            "    required_sections:\n"
            "      - Holding\n"
            "      - Reasoning\n"
            "      - Dissent (if any)\n"
        )
        path = _write(tmp_path, extra=extra)
        simple = parse_simple(path)
        spec = expand(simple, location=tmp_path / "vault")
        nt = spec.note_types[0]
        assert nt.required_sections == ["Holding", "Reasoning", "Dissent (if any)"]

    def test_long_form_without_folder_gets_auto_folder(self, tmp_path: Path) -> None:
        extra = "note_types:\n  - name: opinion\n"
        path = _write(tmp_path, extra=extra)
        simple = parse_simple(path)
        spec = expand(simple, location=tmp_path / "vault")
        nt = spec.note_types[0]
        assert nt.folder == "01 - Opinions"


# ---------------------------------------------------------------------------
# Mixed short/long form
# ---------------------------------------------------------------------------


class TestMixedForms:
    def test_mixed_short_and_long_form(self, tmp_path: Path) -> None:
        extra = (
            "note_types:\n"
            "  - case\n"
            "  - name: opinion\n"
            "    folder: Opinions\n"
            "    required_sections:\n"
            "      - Holding\n"
            "  - statute\n"
            "  - source\n"
        )
        path = _write(tmp_path, extra=extra)
        simple = parse_simple(path)
        spec = expand(simple, location=tmp_path / "vault")
        assert len(spec.note_types) == 4
        names = [nt.name for nt in spec.note_types]
        assert names == ["case", "opinion", "statute", "source"]

    def test_mixed_auto_idx_skips_explicit_folders(self, tmp_path: Path) -> None:
        """Short-form entries after a long-form entry with explicit folder
        should still auto-increment from the right index (long form with
        explicit folder does NOT consume an auto_idx slot)."""
        extra = (
            "note_types:\n"
            "  - case\n"  # → 01 - Cases (auto_idx=1, then auto_idx=2)
            "  - name: opinion\n"
            "    folder: Opinions\n"  # explicit → no auto_idx consumed
            "  - statute\n"  # → 02 - Statutes (auto_idx=2, then auto_idx=3)
        )
        path = _write(tmp_path, extra=extra)
        simple = parse_simple(path)
        spec = expand(simple, location=tmp_path / "vault")
        folders = {nt.name: nt.folder for nt in spec.note_types}
        assert folders["case"] == "01 - Cases"
        assert folders["opinion"] == "Opinions"
        assert folders["statute"] == "02 - Statutes"


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


class TestNoteTypeValidation:
    def test_duplicate_names_rejected(self, tmp_path: Path) -> None:
        extra = "note_types:\n  - case\n  - case\n"
        path = _write(tmp_path, extra=extra)
        with pytest.raises(SpecValidationError, match="duplicate"):
            parse_simple(path)

    def test_duplicate_across_short_and_long_form(self, tmp_path: Path) -> None:
        extra = "note_types:\n  - case\n  - name: case\n    folder: Custom\n"
        path = _write(tmp_path, extra=extra)
        with pytest.raises(SpecValidationError, match="duplicate"):
            parse_simple(path)

    def test_invalid_name_space_rejected(self, tmp_path: Path) -> None:
        extra = "note_types:\n  - foo bar\n"
        path = _write(tmp_path, extra=extra)
        with pytest.raises(SpecValidationError, match="invalid"):
            parse_simple(path)

    def test_invalid_name_special_chars_rejected(self, tmp_path: Path) -> None:
        extra = "note_types:\n  - foo@bar\n"
        path = _write(tmp_path, extra=extra)
        with pytest.raises(SpecValidationError, match="invalid"):
            parse_simple(path)

    def test_long_form_missing_name_rejected(self, tmp_path: Path) -> None:
        extra = (
            "note_types:\n"
            "  - folder: Opinions\n"
            "    required_sections:\n"
            "      - Holding\n"
        )
        path = _write(tmp_path, extra=extra)
        with pytest.raises(SpecValidationError, match="missing 'name'"):
            parse_simple(path)

    def test_non_string_non_mapping_entry_rejected(self, tmp_path: Path) -> None:
        extra = "note_types:\n  - 123\n"
        path = _write(tmp_path, extra=extra)
        with pytest.raises(SpecValidationError):
            parse_simple(path)

    def test_hyphen_and_underscore_valid(self, tmp_path: Path) -> None:
        """Names with hyphens and underscores should be accepted."""
        extra = "note_types:\n  - my-type\n  - another_type\n"
        path = _write(tmp_path, extra=extra)
        simple = parse_simple(path)
        assert len(simple.note_types) == 2
