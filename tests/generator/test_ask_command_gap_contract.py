"""Issue #15 — the rendered ``/ask`` and ``/research`` commands start no run.

``/ask`` used to instruct the agent to run
``research-framework cycle ... --budget-cap 2.0`` whenever the vault could not
answer an in-scope question: the agent started a paid run and chose its cap.
The agent now reports the gap on one ``VAULT-GAP:`` line that the framework
reads (``pipeline/ask_escalation.py``), and neither command names a framework
command at all.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from research_framework.agents import render_agent
from research_framework.pipeline.ask_escalation import (
    GAP_LINE_PREFIX,
    Gap,
    parse_gap_line,
)
from research_framework.spec.parser import parse

_SPEC = Path(__file__).resolve().parents[1] / "fixtures/specs/code-first-vault-spec.md"

#: Every way a rendered command could invoke the framework: its CLI, the
#: vault shim, the module, or a pipeline slash command that starts a run.
_FRAMEWORK_COMMANDS = (
    re.compile(r"research-framework\s+[a-z]"),
    re.compile(r"\./vault\b"),
    re.compile(r"research_framework\.cli"),
    re.compile(r"-m\s+research_framework"),
    re.compile(r"/pipeline\b"),
    re.compile(r"--budget-cap"),
    re.compile(r"--target-topics"),
)


@pytest.fixture(scope="module")
def rendered() -> dict[str, str]:
    spec = parse(_SPEC)
    return {name: render_agent(name, spec) for name in ("ask", "research")}


@pytest.mark.parametrize("command", ["ask", "research"])
def test_the_rendered_command_names_no_framework_command(
    rendered: dict[str, str], command: str
) -> None:
    text = rendered[command]
    hits = [rx.pattern for rx in _FRAMEWORK_COMMANDS if rx.search(text)]
    assert not hits, f"/{command} names a framework command: {hits}"


def test_ask_tells_the_agent_to_report_a_gap_on_the_contract_line(
    rendered: dict[str, str],
) -> None:
    assert GAP_LINE_PREFIX in rendered["ask"]


def test_the_gap_line_example_in_ask_parses_under_the_strict_contract(
    rendered: dict[str, str],
) -> None:
    """The template's own example is what agents copy; it must parse."""
    examples = [
        line
        for line in rendered["ask"].splitlines()
        if line.strip().startswith(GAP_LINE_PREFIX)
    ]
    assert len(examples) == 1, examples
    gap = parse_gap_line(examples[0])
    assert isinstance(gap, Gap)
    assert gap.in_scope is True
