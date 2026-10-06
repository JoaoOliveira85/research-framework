"""Tests for note-type template scaffolding (015d).

Verifies that ``render_all`` writes one ``_templates/<type>.md`` file per
declared note type, and that required sections are rendered into the template.
"""

from __future__ import annotations

from pathlib import Path

from research_framework.generator.templates import render_all
from research_framework.spec.simple import expand, parse_simple

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_FRONTMATTER = """\
---
name: "Test Vault"
owner: "tester"
topic: "A small topic for template tests"
{extra}---

Body.
"""


def _write(tmp_path: Path, extra: str, name: str = "research.spec.md") -> Path:
    path = tmp_path / name
    path.write_text(_BASE_FRONTMATTER.format(extra=extra), encoding="utf-8")
    return path


def _scaffold_and_render(tmp_path: Path, extra: str) -> Path:
    """Parse simple spec, expand to SpecConfig, and run render_all."""
    spec_path = _write(tmp_path, extra=extra)
    simple = parse_simple(spec_path)
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir(parents=True, exist_ok=True)
    (vault_dir / "_templates").mkdir(exist_ok=True)
    (vault_dir / "_pipeline" / "prompts").mkdir(parents=True, exist_ok=True)
    (vault_dir / ".claude" / "commands").mkdir(parents=True, exist_ok=True)
    spec = expand(simple, location=vault_dir)
    render_all(spec, vault_dir)
    return vault_dir


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNoteTypeTemplatesWritten:
    def test_five_note_types_produce_five_templates(self, tmp_path: Path) -> None:
        extra = (
            "note_types:\n"
            "  - case\n"
            "  - statute\n"
            "  - opinion\n"
            "  - jurisdiction\n"
            "  - source\n"
        )
        vault = _scaffold_and_render(tmp_path, extra=extra)
        templates_dir = vault / "_templates"
        for type_name in ("case", "statute", "opinion", "jurisdiction", "source"):
            assert (templates_dir / f"{type_name}.md").is_file(), (
                f"Expected _templates/{type_name}.md to exist"
            )

    def test_historical_default_two_templates(self, tmp_path: Path) -> None:
        """No note_types block → historical default → concept.md + source.md."""
        vault = _scaffold_and_render(tmp_path, extra="")
        templates_dir = vault / "_templates"
        assert (templates_dir / "concept.md").is_file()
        assert (templates_dir / "source.md").is_file()

    def test_required_sections_rendered_in_template(self, tmp_path: Path) -> None:
        extra = (
            "note_types:\n"
            "  - name: opinion\n"
            "    folder: Opinions\n"
            "    required_sections:\n"
            "      - Holding\n"
            "      - Reasoning\n"
            "      - Dissent (if any)\n"
        )
        vault = _scaffold_and_render(tmp_path, extra=extra)
        template_text = (vault / "_templates" / "opinion.md").read_text(
            encoding="utf-8"
        )
        assert "## Holding" in template_text
        assert "## Reasoning" in template_text
        assert "## Dissent (if any)" in template_text

    def test_template_contains_note_type_name(self, tmp_path: Path) -> None:
        extra = "note_types:\n  - myrule\n"
        vault = _scaffold_and_render(tmp_path, extra=extra)
        template_text = (vault / "_templates" / "myrule.md").read_text(encoding="utf-8")
        assert "myrule" in template_text

    def test_changelog_written_for_all_types(self, tmp_path: Path) -> None:
        extra = "note_types:\n  - alpha\n  - beta\n  - gamma\n"
        vault = _scaffold_and_render(tmp_path, extra=extra)
        changelog = (vault / "_templates" / "CHANGELOG.md").read_text(encoding="utf-8")
        assert "alpha.md" in changelog
        assert "beta.md" in changelog
        assert "gamma.md" in changelog
