"""Issue #15 — the framework, not the ``/ask`` agent, decides to start research.

The ``/ask`` template used to tell the agent to run
``research-framework cycle ... --budget-cap 2.0`` itself, so the agent chose
to start a paid run and picked its cap. Now the agent only *reports* a gap,
on one strict line, and :func:`run_ask` decides what happens next:

* without ``escalate`` nothing is ever researched;
* with it, an in-scope gap is researched once and the question re-asked.

The flow is driven here with stand-in callables, so every branch is pinned
without an agent or a cycle. ``tests/cli/test_ask_verb.py`` drives the real
dispatch and the real cycle verb.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline.ask_escalation import (
    GAP_LINE_PREFIX,
    AskAnswer,
    Gap,
    GapLineError,
    ResearchOutcome,
    gap_line_near_miss,
    parse_gap_line,
    render_ask_prompt,
    run_ask,
)


def _gap(topic: str = "Regional consultancies", *, in_scope: bool = True) -> str:
    return f"{GAP_LINE_PREFIX} " + json.dumps({"topic": topic, "in_scope": in_scope})


# ---------------------------------------------------------------------------
# parse_gap_line — the strict contract
# ---------------------------------------------------------------------------


def test_an_answer_without_a_gap_line_reports_no_gap() -> None:
    assert parse_gap_line("The vault covers this.\n\nVault Sources:\n[1] x") is None


def test_a_well_formed_gap_line_is_parsed() -> None:
    answer = f"The vault does not cover this.\n\n{_gap('Contract channels')}\n"
    assert parse_gap_line(answer) == Gap(topic="Contract channels", in_scope=True)


def test_an_out_of_scope_gap_is_parsed_as_out_of_scope() -> None:
    gap = parse_gap_line(_gap("Crypto custody", in_scope=False))
    assert gap == Gap(topic="Crypto custody", in_scope=False)


def test_the_prefix_mentioned_mid_line_is_not_a_gap_line() -> None:
    answer = f"I would normally write a {GAP_LINE_PREFIX} line here, but no."
    assert parse_gap_line(answer) is None


def test_surrounding_whitespace_and_the_topic_are_trimmed() -> None:
    line = f"   {GAP_LINE_PREFIX} " + json.dumps(
        {"topic": "  Padded topic  ", "in_scope": True}
    )
    assert parse_gap_line(line + "   ") == Gap(topic="Padded topic", in_scope=True)


@pytest.mark.parametrize(
    "line",
    [
        pytest.param(f"{GAP_LINE_PREFIX} not json", id="not-json"),
        pytest.param(f"{GAP_LINE_PREFIX} []", id="not-an-object"),
        pytest.param(f'{GAP_LINE_PREFIX} {{"topic": "x"}}', id="missing-in-scope"),
        pytest.param(f'{GAP_LINE_PREFIX} {{"in_scope": true}}', id="missing-topic"),
        pytest.param(
            f'{GAP_LINE_PREFIX} {{"topic": "", "in_scope": true}}', id="empty-topic"
        ),
        pytest.param(
            f'{GAP_LINE_PREFIX} {{"topic": 3, "in_scope": true}}', id="topic-not-str"
        ),
        pytest.param(
            f'{GAP_LINE_PREFIX} {{"topic": "x", "in_scope": "yes"}}',
            id="in-scope-not-bool",
        ),
        pytest.param(
            f'{GAP_LINE_PREFIX} {{"topic": "x", "in_scope": true, "cap": 2.0}}',
            id="unknown-key",
        ),
    ],
)
def test_a_malformed_gap_line_is_refused_not_guessed(line: str) -> None:
    with pytest.raises(GapLineError):
        parse_gap_line(f"Some answer.\n{line}\n")


@pytest.mark.parametrize(
    "topic",
    [
        pytest.param(
            "<the uncovered topic, one short line>", id="template-placeholder"
        ),
        pytest.param("<topic>", id="angle-bracket-placeholder"),
    ],
)
def test_a_copied_placeholder_topic_is_refused(topic: str) -> None:
    """Copying the template's example must not buy a paid cycle."""
    with pytest.raises(GapLineError, match="placeholder"):
        parse_gap_line(_gap(topic))


@pytest.mark.parametrize(
    "topic",
    [
        pytest.param("first line\nsecond line", id="newline"),
        pytest.param("tab\there", id="tab"),
        pytest.param("bell\u0007", id="bell"),
        pytest.param("del\u007f", id="delete"),
    ],
)
def test_a_topic_with_control_characters_is_refused(topic: str) -> None:
    with pytest.raises(GapLineError, match="control character"):
        parse_gap_line(_gap(topic))


def test_a_topic_longer_than_the_cap_is_refused() -> None:
    with pytest.raises(GapLineError, match="200"):
        parse_gap_line(_gap("x" * 201))
    assert parse_gap_line(_gap("x" * 200)) == Gap("x" * 200, True)


@pytest.mark.parametrize(
    "line",
    [
        pytest.param(f"**{GAP_LINE_PREFIX}** {{}}", id="bold"),
        pytest.param(f"`{GAP_LINE_PREFIX} {{}}`", id="backticks"),
        pytest.param(f"- {GAP_LINE_PREFIX} {{}}", id="bullet"),
        pytest.param("vault-gap: {}", id="lowercase"),
    ],
)
def test_a_near_miss_gap_line_is_detected(line: str) -> None:
    assert parse_gap_line(f"Answer.\n{line}\n") is None
    assert gap_line_near_miss(f"Answer.\n{line}\n")


def test_an_answer_without_any_gap_mention_is_not_a_near_miss() -> None:
    assert not gap_line_near_miss("Covered.\n\nVault Sources:\n[1] x")
    assert not gap_line_near_miss(_gap("T"))


@pytest.mark.parametrize(
    "prose",
    [
        "The vault covers this, so no VAULT-GAP line is needed.",
        "I considered writing vault-gap: but the notes answer it.",
        "> quoted: VAULT-GAP: {}",
    ],
)
def test_the_marker_inside_prose_is_not_a_near_miss(prose: str) -> None:
    """Only a line that STARTS with the (decorated) marker is a near miss."""
    assert not gap_line_near_miss(f"Answer.\n{prose}\n")


_CWD_STUB = """\
import argparse
import os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--vault")
parser.add_argument("--stage")
parser.add_argument("--prompt-file")
parser.add_argument("--cost-sidecar")
parser.add_argument("--output-file")
args, _ = parser.parse_known_args()
out = Path(args.output_file)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(os.getcwd(), encoding="utf-8")
"""


def test_the_ask_agent_runs_in_the_vault_whatever_the_callers_cwd(
    tmp_path, monkeypatch
) -> None:
    """Read-only tools may only read inside the cwd, and the prompt's paths
    (`AGENTS.md`, `data_vault/_index.md`) are relative: an agent started in
    the operator's cwd cannot read the vault and reports a spurious gap."""
    from research_framework.pipeline.ask_escalation import dispatch_ask

    vault = tmp_path / "vault"
    (vault / "scripts").mkdir(parents=True)
    (vault / "scripts" / "agent_call.py").write_text(_CWD_STUB, encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    answer = dispatch_ask(vault, "prompt", vault / "_pipeline" / "ask" / "t")

    assert answer.returncode == 0
    assert Path(answer.text).resolve() == vault.resolve()


def test_a_near_miss_is_warned_about_not_passed_silently() -> None:
    rec = _Recorder([AskAnswer(0, f"Answer.\n**{GAP_LINE_PREFIX}** {{}}")])

    assert rec.run(escalate=True) == 0

    assert rec.researched == []
    assert any("WARN" in m and GAP_LINE_PREFIX in m for m in rec.messages)


def test_two_gap_lines_are_refused() -> None:
    with pytest.raises(GapLineError):
        parse_gap_line(f"{_gap('A')}\n{_gap('B')}\n")


# ---------------------------------------------------------------------------
# render_ask_prompt — the vault's own /ask command, one-shot
# ---------------------------------------------------------------------------


def test_the_prompt_is_the_command_body_with_the_question_substituted() -> None:
    command = "---\ndescription: x\n---\n\n# /ask\n\n## Question\n\n$ARGUMENTS\n"
    prompt = render_ask_prompt(command, "What is X?")
    assert prompt.startswith("# /ask")
    assert "What is X?" in prompt
    assert "$ARGUMENTS" not in prompt
    assert "description:" not in prompt


# ---------------------------------------------------------------------------
# run_ask — who starts a run, and when
# ---------------------------------------------------------------------------


class _Recorder:
    """Stand-ins for the dispatch and the research run, recording each call."""

    def __init__(
        self,
        answers: list[AskAnswer],
        research: ResearchOutcome = ResearchOutcome("completed", 0),
    ) -> None:
        self._answers = list(answers)
        self.asked: list[str] = []
        self.researched: list[str] = []
        self._research = research
        self.messages: list[str] = []

    def ask(self, question: str) -> AskAnswer:
        self.asked.append(question)
        return self._answers.pop(0)

    def research(self, topic: str) -> ResearchOutcome:
        self.researched.append(topic)
        return self._research

    def report(self, message: str) -> None:
        self.messages.append(message)

    def run(self, *, escalate: bool, question: str = "Q?") -> int:
        return run_ask(
            question,
            escalate=escalate,
            ask=self.ask,
            research=self.research,
            report=self.report,
        )


def test_without_escalate_an_in_scope_gap_starts_no_run() -> None:
    rec = _Recorder([AskAnswer(0, f"Not covered.\n{_gap('T')}")])

    assert rec.run(escalate=False) == 0

    assert rec.researched == []
    assert rec.asked == ["Q?"]
    assert any("--escalate" in m for m in rec.messages)


def test_with_escalate_an_in_scope_gap_is_researched_then_re_asked() -> None:
    rec = _Recorder(
        [
            AskAnswer(0, f"Not covered.\n{_gap('Contract channels')}"),
            AskAnswer(0, "Covered now.\n\nVault Sources:\n[1] data_vault/x.md"),
        ]
    )

    assert rec.run(escalate=True, question="Which channels?") == 0

    assert rec.researched == ["Contract channels"]
    assert rec.asked == ["Which channels?", "Which channels?"]


def test_with_escalate_no_gap_means_no_run() -> None:
    rec = _Recorder([AskAnswer(0, "Covered.\n\nVault Sources:\n[1] data_vault/x.md")])

    assert rec.run(escalate=True) == 0

    assert rec.researched == []
    assert len(rec.asked) == 1


def test_with_escalate_an_out_of_scope_gap_means_no_run() -> None:
    rec = _Recorder([AskAnswer(0, f"Out of scope.\n{_gap('Crypto', in_scope=False)}")])

    assert rec.run(escalate=True) == 0

    assert rec.researched == []
    assert len(rec.asked) == 1


@pytest.mark.parametrize("escalate", [False, True])
def test_a_malformed_gap_line_fails_the_ask_and_starts_no_run(escalate: bool) -> None:
    rec = _Recorder([AskAnswer(0, f"{GAP_LINE_PREFIX} {{broken")])

    assert rec.run(escalate=escalate) == 1

    assert rec.researched == []


def test_a_failed_dispatch_is_reported_and_starts_no_run() -> None:
    rec = _Recorder([AskAnswer(3, "")])

    assert rec.run(escalate=True) == 3

    assert rec.researched == []


def test_a_cycle_that_terminates_with_1_completed_and_is_re_asked() -> None:
    """The cycle runner's 1 is TERMINATE (Conditions A/B/C), not a failure.

    A targeted cycle often finds no new topics (B), and the last allowed cycle
    always meets A — so treating 1 as failure would never re-ask.
    """
    rec = _Recorder(
        [AskAnswer(0, _gap("T")), AskAnswer(0, "Covered now.")],
        research=ResearchOutcome("completed", 1),
    )

    assert rec.run(escalate=True) == 0

    assert rec.researched == ["T"]
    assert len(rec.asked) == 2


def test_a_failed_research_run_is_not_followed_by_a_re_ask() -> None:
    rec = _Recorder([AskAnswer(0, _gap("T"))], research=ResearchOutcome("failed", 2))

    assert rec.run(escalate=True) == 2

    assert rec.researched == ["T"]
    assert len(rec.asked) == 1


def test_a_paused_research_run_is_reported_as_a_pause_and_not_re_asked() -> None:
    """A run stopped at the budget ceiling has not closed the gap."""
    rec = _Recorder(
        [AskAnswer(0, _gap("T"))],
        research=ResearchOutcome("paused", 1, "BUDGET_PAUSED at _pipeline/x"),
    )

    assert rec.run(escalate=True) == 1

    assert len(rec.asked) == 1
    assert any("paused" in m and "BUDGET_PAUSED" in m for m in rec.messages)


def test_a_gap_that_survives_the_research_is_not_escalated_twice() -> None:
    """One escalation per ask: a second gap is reported, never auto-researched."""
    rec = _Recorder([AskAnswer(0, _gap("T")), AskAnswer(0, _gap("T"))])

    assert rec.run(escalate=True) == 0

    assert rec.researched == ["T"]
    assert len(rec.asked) == 2
    assert any("still" in m for m in rec.messages)
