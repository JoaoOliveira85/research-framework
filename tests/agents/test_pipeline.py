"""Tests for the pipeline orchestrator shim template."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader

from research_framework.agents import TEMPLATES_DIR

TODAY = "2026-05-13"

FAKE_SPEC = SimpleNamespace(
    name="Test Vault",
    owner="test-owner",
    location="/Users/test/Documents/test-vault",
    vault_corpus_dir="Test Notes",
    note_types=["concept", "person", "project"],
    data_sources=["rss", "youtube", "reddit"],
    # #256: pipeline.md.j2's `related:` frontmatter names the research
    # command via `spec.settings.commands.research` (it is one of the three
    # renameable commands) rather than a hardcoded "research.md".
    settings=SimpleNamespace(commands=SimpleNamespace(research="research")),
)

ALL_MODES = ["full", "collect", "extract", "scout", "resume", "finish", "status"]


@pytest.fixture(scope="module")
def rendered() -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        keep_trailing_newline=True,
    )
    template = env.get_template("pipeline.md.j2")
    return template.render(spec=FAKE_SPEC, today=TODAY)


def test_frontmatter_is_valid_yaml(rendered: str) -> None:
    """Frontmatter block between the --- delimiters must parse as valid YAML."""
    assert rendered.startswith("---"), "rendered output must start with ---"
    parts = rendered.split("---", 2)
    assert len(parts) >= 3, "expected at least two --- delimiters"
    frontmatter_text = parts[1]
    data = yaml.safe_load(frontmatter_text)
    assert isinstance(data, dict), "frontmatter must be a YAML mapping"


def test_frontmatter_required_keys(rendered: str) -> None:
    parts = rendered.split("---", 2)
    data = yaml.safe_load(parts[1])
    assert data["type"] == "agent-definition"
    assert data["agent_name"] == "pipeline"
    assert data["updated"] == TODAY
    assert data["_template_version"] == 1


def test_all_modes_present(rendered: str) -> None:
    """Every one of the seven pipeline modes must appear in the output."""
    for mode in ALL_MODES:
        assert mode in rendered, f"mode '{mode}' not found in rendered template"


def test_framework_command_literal(rendered: str) -> None:
    """The string 'research_framework pipeline' must appear as a command literal."""
    assert "research_framework pipeline" in rendered


def test_vault_location_is_not_baked_in(rendered: str) -> None:
    """The shim must NOT bake spec.location — a moved vault would keep pointing
    at where it used to live (issue #254: one live vault's /pipeline still
    named a directory that had been renamed months earlier)."""
    assert FAKE_SPEC.location not in rendered


def test_vault_resolved_at_runtime(rendered: str) -> None:
    """Every framework invocation resolves the vault from the environment."""
    assert "VAULT_DIR" in rendered, "shim must resolve the vault at run time"
    for mode in ALL_MODES:
        assert f'research_framework pipeline "${{VAULT_DIR:-$PWD}}" {mode}' in rendered


def test_no_known_limitation_disclaimer(rendered: str) -> None:
    """research/report were wired by PR #209; the shim must not disclaim them."""
    assert "Known limitation" not in rendered
    assert "unwired stub" not in rendered
    assert "./vault research" not in rendered


def test_vault_name_substituted(rendered: str) -> None:
    """spec.name must appear in the rendered output."""
    assert FAKE_SPEC.name in rendered


def test_no_unrendered_jinja_markers(rendered: str) -> None:
    """No {{ }} or {% %} markers should remain after rendering."""
    assert "{{" not in rendered, "found unrendered {{ in output"
    assert "}}" not in rendered, "found unrendered }} in output"
    assert "{%" not in rendered, "found unrendered {% in output"
    assert "%}" not in rendered, "found unrendered %} in output"


def test_corpus_dir_substituted(rendered: str) -> None:
    """spec.vault_corpus_dir must appear (used in frontmatter reads list)."""
    assert FAKE_SPEC.vault_corpus_dir in rendered


def test_template_is_reasonably_short(rendered: str) -> None:
    """Shim should be well under 200 lines — not the 410-line original."""
    lines = rendered.splitlines()
    assert len(lines) <= 200, f"template too long: {len(lines)} lines (target ≤ 200)"
