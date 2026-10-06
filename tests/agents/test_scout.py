"""Tests for the scout agent Jinja2 template."""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from jinja2 import Environment, FileSystemLoader

from research_framework.agents import TEMPLATES_DIR


@pytest.fixture()
def env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        keep_trailing_newline=True,
    )


@pytest.fixture()
def fake_spec() -> SimpleNamespace:
    return SimpleNamespace(
        name="Test Vault",
        owner="Test Owner",
        vault_corpus_dir="test_notes",
        note_types=[
            SimpleNamespace(
                name="Concepts",
                folder="02 - Concepts",
                description="Concept notes",
                required_sections=["Summary", "Details"],
            ),
            SimpleNamespace(
                name="Companies",
                folder="03 - Companies",
                description="Company profiles",
                required_sections=["Overview"],
            ),
        ],
        scope_include=["AI tooling", "LLM research"],
        scope_exclude=["Sports", "Finance"],
        data_sources=[
            {
                "name": "Import AI",
                "type": "newsletter",
                "role": "high-signal weekly digest",
            },
            {"name": "Hacker News", "type": "community", "role": "broad tech pulse"},
            {
                "name": "Anthropic Blog",
                "type": "blog",
                "role": "primary vendor updates",
            },
        ],
        # #256: scout.md.j2's `related:` frontmatter names the research
        # command via `spec.settings.commands.research` (it is one of the
        # three renameable commands) rather than a hardcoded "research.md".
        settings=SimpleNamespace(commands=SimpleNamespace(research="research")),
    )


@pytest.fixture()
def rendered(env: Environment, fake_spec: SimpleNamespace) -> str:
    tmpl = env.get_template("scout.md.j2")
    return tmpl.render(spec=fake_spec, today="2026-05-13")


def test_starts_with_yaml_frontmatter(rendered: str) -> None:
    """Rendered output must open with a YAML frontmatter block."""
    assert rendered.startswith("---\n"), "Output must start with '---'"
    # Find the closing ---
    after_open = rendered[4:]
    assert "---" in after_open, "Frontmatter block must be closed with '---'"


def test_frontmatter_fields(rendered: str) -> None:
    """Frontmatter must contain expected fixed fields."""
    front = rendered.split("---")[1]
    assert "type: agent-definition" in front
    assert "agent_name: scout" in front
    assert 'version: "1.0"' in front
    assert 'updated: "2026-05-13"' in front
    assert "_template_version: 1" in front


def test_contains_vault_name(rendered: str) -> None:
    """Rendered output must include the vault display name from the spec."""
    assert "Test Vault" in rendered


def test_corpus_dir_used_not_literal(rendered: str) -> None:
    """Corpus dir from spec must appear; hard-coded 'data_vault/' must not."""
    assert "test_notes/" in rendered or "test_notes" in rendered
    assert "data_vault" not in rendered


def test_data_sources_rendered(rendered: str) -> None:
    """All data sources from the spec must appear in the output."""
    assert "Import AI" in rendered
    assert "Hacker News" in rendered
    assert "Anthropic Blog" in rendered
    assert "high-signal weekly digest" in rendered
    assert "broad tech pulse" in rendered
    assert "primary vendor updates" in rendered


def test_note_types_rendered(rendered: str) -> None:
    """Note types from the spec must be referenced in the output."""
    assert "Concepts" in rendered
    assert "Companies" in rendered


def test_no_unrendered_jinja_markers(rendered: str) -> None:
    """No raw {{ ... }} or {% ... %} markers must remain in the output."""
    assert not re.search(r"\{\{.*?\}\}", rendered), "Unrendered {{ }} expression found"
    assert not re.search(r"\{%.*?%\}", rendered), "Unrendered {% %} tag found"


def test_owns_frontmatter_uses_corpus_dir(rendered: str) -> None:
    """The 'owns' frontmatter entry must reference the spec corpus dir."""
    front = rendered.split("---")[1]
    assert "test_notes/00 - MOC/Topic Radar" in front


def test_reads_frontmatter_uses_corpus_dir(rendered: str) -> None:
    """The 'reads' frontmatter entries must reference the spec corpus dir."""
    front = rendered.split("---")[1]
    assert "test_notes/AGENTS.md" in front
    assert "test_notes/00 - MOC/*.md" in front


def test_owner_appears_in_body(rendered: str) -> None:
    """The spec owner must appear in the agent body prose."""
    assert "Test Owner" in rendered
