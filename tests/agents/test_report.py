"""Tests for the report agent Jinja2 template."""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from jinja2 import Environment, FileSystemLoader

from research_framework.agents import TEMPLATES_DIR


def _make_spec(
    *,
    name: str = "Test Vault",
    owner: str = "test-owner",
    vault_corpus_dir: str = "data_vault",
    note_types: list[dict] | None = None,
    scope_include: list[str] | None = None,
    scope_exclude: list[str] | None = None,
) -> SimpleNamespace:
    if note_types is None:
        note_types = [
            {"name": "concept", "folder": "concepts"},
            {"name": "source", "folder": "sources"},
            {"name": "project", "folder": "projects"},
            {"name": "log", "folder": "logs"},
        ]
    nt_objects = [SimpleNamespace(**nt) for nt in note_types]
    return SimpleNamespace(
        name=name,
        owner=owner,
        vault_corpus_dir=vault_corpus_dir,
        note_types=nt_objects,
        scope_include=scope_include or [],
        scope_exclude=scope_exclude or [],
    )


@pytest.fixture()
def env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        keep_trailing_newline=True,
    )


@pytest.fixture()
def rendered(env: Environment) -> str:
    spec = _make_spec()
    return env.get_template("report.md.j2").render(spec=spec, today="2026-05-13")


def test_metrics_section_has_one_line_per_note_type(rendered: str) -> None:
    """The note-counts block must contain exactly one bullet per note type (4 in fixture)."""
    # The metrics section produces lines like: "- **Concept**: count notes in `data_vault/concepts/`"
    bullet_pattern = re.compile(
        r"^- \*\*\w[\w ]*\*\*: count notes in `data_vault/", re.MULTILINE
    )
    matches = bullet_pattern.findall(rendered)
    assert len(matches) == 4, (
        f"Expected 4 note-type bullets, found {len(matches)}.\nMatches: {matches}"
    )


def test_no_unrendered_jinja_markers(rendered: str) -> None:
    """No {{ }} or {% %} markers should survive rendering."""
    assert "{{" not in rendered, "Unrendered Jinja2 expression found in output"
    assert "{%" not in rendered, "Unrendered Jinja2 block tag found in output"


def test_custom_corpus_dir_used_throughout() -> None:
    """When spec.vault_corpus_dir is custom, that path appears in the output."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        keep_trailing_newline=True,
    )
    spec = _make_spec(
        vault_corpus_dir="my_notes",
        note_types=[
            {"name": "concept", "folder": "concepts"},
            {"name": "source", "folder": "sources"},
        ],
    )
    output = env.get_template("report.md.j2").render(spec=spec, today="2026-05-13")

    # Should appear in reads frontmatter, git log commands, find command, bullets, Metadata
    occurrences = output.count("my_notes")
    assert occurrences >= 4, (
        f"Expected corpus dir 'my_notes' to appear at least 4 times, found {occurrences}"
    )
    # Old default must not appear
    assert "data_vault" not in output, (
        "Default corpus dir 'data_vault' leaked into custom-corpus render"
    )


def test_the_report_agent_reads_the_receipts_verify_report(rendered: str) -> None:
    """Spec 080 D3 / T007.

    The definition declared `reads: _pipeline/logs/verify-*.md` and told the
    agent to look for "the most recent" one. No such file has ever existed:
    the runner wrote `verify-<ts>.json`, and since spec 080 it writes
    `<run_dir>/verify-report.json`. An agent told to read a file nobody writes
    reports "Not available" on runs that verified perfectly well — which is
    exactly what the 2026-09-01 reports did.
    """
    assert "verify-report.json" in rendered
    assert "_pipeline/runs/" in rendered
    assert "_pipeline/logs/verify-" not in rendered, (
        "the Markdown verify summary has never been written by anything"
    )
