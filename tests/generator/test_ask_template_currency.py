"""Tier 3: the ask command tells the agent about currency (spec 087 FR-019;
T010)."""

from __future__ import annotations

from pathlib import Path

from research_framework.generator.templates import render_all
from research_framework.spec.simple import expand, parse_simple

_SPEC = """\
---
name: "Ask Vault"
owner: "tester"
topic: "A topic"
note_types:
  - name: concept
    folder: "01 - Concepts"
    review_after_days: 90
  - name: source
    folder: "02 - Sources"
---

Body.
"""


def _ask(tmp_path: Path) -> str:
    path = tmp_path / "research.spec.md"
    path.write_text(_SPEC, encoding="utf-8")
    vault = tmp_path / "vault"
    for sub in ("_templates", "_pipeline/prompts", ".claude/commands"):
        (vault / sub).mkdir(parents=True)
    render_all(expand(parse_simple(path), location=vault), vault)
    return (vault / ".claude" / "commands" / "ask.md").read_text(encoding="utf-8")


def test_ask_is_told_to_follow_superseded_by_and_flag_past_review(
    tmp_path: Path,
) -> None:
    text = _ask(tmp_path)

    assert "never present a superseded or retracted note as current" in text.lower()
    assert "superseded_by" in text
    assert "answer from" in text and "successor" in text
    assert "retracted" in text
    assert "past its review interval" in text
    assert "as_of" in text
    # the intervals the vault declares are spelled out for the agent
    assert "`concept`: 90 days" in text
    assert "`source`: " not in text  # a type with no interval is not listed
