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
    GapLineError,
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
    # Any vault-local script run as `./<name>`.
    re.compile(r"\./[\w-]+(\.py)?\b"),
)

#: Lines a rendered command may carry although a pattern above matches them.
#: `/research` tells the agent to run the vault's validators after writing a
#: note. `update_vault.py validate` runs the vault-local check scripts
#: (template compliance, code-source coverage, drift, validate_vault) offline:
#: it starts no research cycle, dispatches no agent and spends nothing, so it
#: is not the "framework run" issue #15 forbids.
_ALLOWED_LINES = frozenset({"./update_vault.py validate"})


@pytest.fixture(scope="module")
def rendered() -> dict[str, str]:
    spec = parse(_SPEC)
    return {name: render_agent(name, spec) for name in ("ask", "research")}


@pytest.mark.parametrize("command", ["ask", "research"])
def test_the_rendered_command_names_no_framework_command(
    rendered: dict[str, str], command: str
) -> None:
    text = "\n".join(
        line
        for line in rendered[command].splitlines()
        if line.strip() not in _ALLOWED_LINES
    )
    hits = [rx.pattern for rx in _FRAMEWORK_COMMANDS if rx.search(text)]
    assert not hits, f"/{command} names a framework command: {hits}"


def test_ask_tells_the_agent_to_report_a_gap_on_the_contract_line(
    rendered: dict[str, str],
) -> None:
    assert GAP_LINE_PREFIX in rendered["ask"]


def test_the_gap_line_example_in_ask_is_refused_if_copied_verbatim(
    rendered: dict[str, str],
) -> None:
    """An agent that copies the template's example must not buy a paid cycle.

    The example's topic is a `<placeholder>`; the parser refuses it, so a
    verbatim copy is an error, never an in-scope gap.
    """
    examples = [
        line
        for line in rendered["ask"].splitlines()
        if line.strip().startswith(GAP_LINE_PREFIX)
    ]
    assert len(examples) == 1, examples
    with pytest.raises(GapLineError, match="placeholder"):
        parse_gap_line(examples[0])
