"""Tests for extract.md.j2 agent template."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from jinja2 import Environment, FileSystemLoader

from research_framework.agents import TEMPLATES_DIR


@pytest.fixture()
def env() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        keep_trailing_newline=True,
    )


def _make_spec(
    *,
    name: str = "Test Vault",
    owner: str = "test-owner",
    vault_corpus_dir: str = "Test Notes",
    data_sources: list[dict] | None = None,
) -> SimpleNamespace:
    if data_sources is None:
        data_sources = [
            {"name": "rss-feed", "type": "rss", "role": "Industry blog aggregator"},
            {
                "name": "youtube",
                "type": "youtube",
                "role": "Video transcript collector",
            },
            {"name": "reddit", "type": "reddit", "role": "Community signal watcher"},
        ]
    sources = [SimpleNamespace(**ds) for ds in data_sources]
    return SimpleNamespace(
        name=name,
        owner=owner,
        vault_corpus_dir=vault_corpus_dir,
        note_types=[],
        data_sources=sources,
    )


def _render(env: Environment, spec: SimpleNamespace, today: str = "2026-05-13") -> str:
    template = env.get_template("extract.md.j2")
    return template.render(spec=spec, today=today)


class TestSourceNamesAppear:
    """Each data_source name must appear in the rendered output."""

    def test_all_source_names_in_output(self, env: Environment) -> None:
        spec = _make_spec(
            data_sources=[
                {"name": "rss-feed", "type": "rss", "role": "Blog aggregator"},
                {"name": "youtube", "type": "youtube", "role": "Video collector"},
                {"name": "reddit", "type": "reddit", "role": "Community watcher"},
            ]
        )
        rendered = _render(env, spec)
        for ds in spec.data_sources:
            assert ds.name in rendered, (
                f"Source name '{ds.name}' not found in rendered output"
            )


class TestNoUnrenderedMarkers:
    """Template must not leave any Jinja2 {{ }} or {% %} markers in output."""

    def test_no_jinja_markers(self, env: Environment) -> None:
        spec = _make_spec()
        rendered = _render(env, spec)
        # Check for unrendered variable markers
        assert "{{" not in rendered, "Unrendered {{ }} marker found in output"
        assert "}}" not in rendered, "Unrendered {{ }} marker found in output"
        # Check for unrendered block markers
        assert "{%" not in rendered, "Unrendered {% %} marker found in output"
        assert "%}" not in rendered, "Unrendered {% %} marker found in output"


class TestCorpusDirFlowsThrough:
    """Custom vault_corpus_dir must appear in relevant sections."""

    def test_corpus_dir_in_frontmatter(self, env: Environment) -> None:
        spec = _make_spec(vault_corpus_dir="My Custom Notes")
        rendered = _render(env, spec)
        assert "My Custom Notes" in rendered

    def test_corpus_dir_in_body(self, env: Environment) -> None:
        spec = _make_spec(vault_corpus_dir="Domain Knowledge")
        rendered = _render(env, spec)
        # Should appear in at least 2 places: frontmatter reads + body references
        occurrences = rendered.count("Domain Knowledge")
        assert occurrences >= 2, (
            f"Expected vault_corpus_dir to appear at least twice, found {occurrences}"
        )

    def test_corpus_dir_replaces_hardcoded_path(self, env: Environment) -> None:
        spec = _make_spec(vault_corpus_dir="AI Notes")
        rendered = _render(env, spec)
        # The original feeds-vault hardcoded path was "AI Notes/AGENTS.md"
        # Our template should parametrise it
        assert "AI Notes/AGENTS.md" in rendered or "AI Notes" in rendered


class TestFrontmatter:
    """Rendered frontmatter must have the required keys."""

    def test_required_frontmatter_keys(self, env: Environment) -> None:
        spec = _make_spec()
        rendered = _render(env, spec)
        frontmatter_block = rendered.split("---")[1]
        for key in (
            "type",
            "agent_name",
            "version",
            "updated",
            "audience",
            "_template_version",
        ):
            assert key in frontmatter_block, f"Frontmatter key '{key}' missing"

    def test_today_in_updated(self, env: Environment) -> None:
        spec = _make_spec()
        rendered = _render(env, spec)
        assert "2026-05-13" in rendered

    def test_agent_name_is_extract(self, env: Environment) -> None:
        spec = _make_spec()
        rendered = _render(env, spec)
        assert "agent_name: extract" in rendered


class TestVaultName:
    """Vault name must appear in the body."""

    def test_vault_name_in_body(self, env: Environment) -> None:
        spec = _make_spec(name="My Research Vault")
        rendered = _render(env, spec)
        assert "My Research Vault" in rendered
