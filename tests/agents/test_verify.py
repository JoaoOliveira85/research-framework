"""Tests for the verify agent Jinja2 template."""

from __future__ import annotations

import yaml
from jinja2 import Environment, FileSystemLoader

from research_framework.agents import TEMPLATES_DIR


def _make_spec(vault_corpus_dir: str = "data_vault"):
    """Return a minimal fake spec object for template rendering."""

    class FakeNoteType:
        def __init__(self, name: str, folder: str) -> None:
            self.name = name
            self.folder = folder

    class FakeCommands:
        research = "research"

    class FakeSettings:
        commands = FakeCommands()

    class FakeSpec:
        name = "Test Vault"
        owner = "test-owner"
        note_types = [
            FakeNoteType("concept", "01-concepts"),
            FakeNoteType("learning", "14-learning"),
        ]
        data_sources: list = []
        scope_include: list = []
        scope_exclude: list = []
        # #256: verify.md.j2's `related:` frontmatter names the research
        # command via `spec.settings.commands.research` (it is one of the
        # three renameable commands) rather than a hardcoded "research.md".
        settings = FakeSettings()

    spec = FakeSpec()
    spec.vault_corpus_dir = vault_corpus_dir
    return spec


def _render(vault_corpus_dir: str = "data_vault") -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        keep_trailing_newline=True,
    )
    template = env.get_template("verify.md.j2")
    return template.render(spec=_make_spec(vault_corpus_dir), today="2026-05-13")


class TestVerifyTemplate:
    def test_frontmatter_is_valid_yaml(self):
        rendered = _render()
        # Extract frontmatter between the first pair of `---` delimiters.
        parts = rendered.split("---\n", 2)
        assert len(parts) >= 3, (
            "Expected YAML frontmatter delimiters in rendered output"
        )
        frontmatter_text = parts[1]
        fm = yaml.safe_load(frontmatter_text)
        assert isinstance(fm, dict), "Frontmatter did not parse to a dict"
        assert fm["type"] == "agent-definition"
        assert fm["agent_name"] == "verify"
        assert fm["version"] == "1.0"
        assert fm["updated"] == "2026-05-13"
        assert fm["_template_version"] == 1

    def test_corpus_dir_present_in_body(self):
        rendered = _render()
        assert "data_vault/" in rendered

    def test_no_unrendered_jinja_markers(self):
        rendered = _render()
        assert "{{" not in rendered
        assert "}}" not in rendered

    def test_custom_corpus_dir_replaces_default(self):
        rendered = _render(vault_corpus_dir="cases")
        assert "cases/" in rendered
        assert "data_vault/" not in rendered

    def test_vault_name_substituted(self):
        rendered = _render()
        assert "Test Vault" in rendered

    def test_owns_log_pattern_in_frontmatter(self):
        rendered = _render()
        parts = rendered.split("---\n", 2)
        fm = yaml.safe_load(parts[1])
        assert "_pipeline/logs/verify-*.md" in fm["owns"]

    def test_reads_corpus_dir_in_frontmatter(self):
        rendered = _render()
        parts = rendered.split("---\n", 2)
        fm = yaml.safe_load(parts[1])
        reads = fm["reads"]
        assert any("data_vault" in r for r in reads)

    def test_reads_corpus_dir_custom_in_frontmatter(self):
        rendered = _render(vault_corpus_dir="cases")
        parts = rendered.split("---\n", 2)
        fm = yaml.safe_load(parts[1])
        reads = fm["reads"]
        assert any("cases" in r for r in reads)
        assert not any("data_vault" in r for r in reads)


class TestTier0Invocation:
    """Step 1 is the only executable instruction in the command; if it names
    something the framework does not ship, Tier 0 is broken by construction in
    every generated vault (issue #253)."""

    def test_does_not_invoke_the_retired_verify_script(self):
        rendered = _render()
        assert "scripts/verify.py" not in rendered
        assert "verify.py" not in rendered

    def test_invokes_the_verify_processor_module(self):
        rendered = _render()
        assert "python -m research_framework.processors.verify" in rendered

    def test_passes_the_corpus_dir_not_the_vault_root(self):
        """PR #210 scoped the processor to the corpus; grading the vault root
        walks .claude/, README.md and .venv/ as if they were notes."""
        rendered = _render(vault_corpus_dir="cases")
        assert "python -m research_framework.processors.verify cases" in rendered

    def test_requests_json_and_suppresses_auto_fix(self):
        """The command parses stdout as JSON and promises never to mutate
        notes; both have to be on the invocation it actually prints."""
        rendered = _render()
        line = next(
            ln
            for ln in rendered.splitlines()
            if "research_framework.processors.verify" in ln
        )
        assert "--json" in line
        assert "--no-fix" in line
