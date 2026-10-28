"""``ask --escalate``: the framework, not the agent, starts research (issue #15).

The vault's ``/ask`` command used to tell the agent to run
``research-framework cycle ... --budget-cap 2.0`` itself whenever the vault
could not answer an in-scope question. The agent therefore chose to start a
paid run and picked its cap, and the operator had never opted in for that
question.

The split now follows Principle IV — agents report, scripts decide:

* The agent runs no framework command. When the vault cannot answer, it says
  so and reports the gap on ONE line of a fixed shape (:data:`GAP_LINE_PREFIX`
  followed by a JSON object, see :func:`parse_gap_line`).
* :func:`run_ask` reads that line after the session. Without ``escalate`` it
  never starts a run — it says how to ask for one. With ``escalate`` an
  in-scope gap is researched once, through the caller's ``research`` callable
  (the ``cycle --target-topics`` path, under the normal spec-061 budget
  ladder), and the question is asked again.

The discovered topic is recorded only where spec 073 records it — the
append-only managed region of ``research.spec.md``, written by the cycle verb
this flow reuses. Nothing here writes it anywhere else.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "GAP_LINE_PREFIX",
    "AskAnswer",
    "Gap",
    "GapLineError",
    "dispatch_ask",
    "parse_gap_line",
    "render_ask_prompt",
    "run_ask",
]

#: The one line the ``/ask`` agent writes when the vault cannot answer. The
#: template (``templates/commands/ask.md.j2``) spells this literal out; a test
#: renders it and parses its example, so the two cannot drift apart.
GAP_LINE_PREFIX = "VAULT-GAP:"

#: Exactly these keys, no more: a gap line is a report, not a request. A field
#: such as a budget would be the agent picking its own cap again.
_GAP_KEYS = frozenset({"topic", "in_scope"})

#: The stage name the dispatch is recorded under; ``stages.ask`` in
#: settings.yaml picks its executor, ``default_executor`` otherwise.
ASK_STAGE = "ask"


class GapLineError(ValueError):
    """The answer carried a gap line that does not meet the contract.

    Raised rather than guessed around: a run decided on a misread line would
    spend money on a topic nobody reported.
    """


@dataclass(frozen=True)
class Gap:
    """What the agent reported the vault does not cover."""

    topic: str
    in_scope: bool


@dataclass(frozen=True)
class AskAnswer:
    """One ``/ask`` dispatch: its exit code and the agent's answer text."""

    returncode: int
    text: str


def parse_gap_line(answer: str) -> Gap | None:
    """Return the gap the answer reports, ``None`` when it reports none.

    A gap line is a line whose stripped text starts with
    :data:`GAP_LINE_PREFIX`, followed by a JSON object with exactly a non-empty
    string ``topic`` and a boolean ``in_scope``. The prefix mentioned inside a
    sentence is not a gap line. More than one gap line, or one that breaks the
    shape, raises :class:`GapLineError`.
    """
    lines = [
        line.strip()
        for line in answer.splitlines()
        if line.strip().startswith(GAP_LINE_PREFIX)
    ]
    if not lines:
        return None
    if len(lines) > 1:
        raise GapLineError(
            f"the answer carries {len(lines)} {GAP_LINE_PREFIX} lines; the "
            "contract is at most one"
        )
    payload = lines[0][len(GAP_LINE_PREFIX) :].strip()
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise GapLineError(f"{GAP_LINE_PREFIX} payload is not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise GapLineError(f"{GAP_LINE_PREFIX} payload must be a JSON object")
    if set(data) != _GAP_KEYS:
        raise GapLineError(
            f"{GAP_LINE_PREFIX} payload must have exactly the keys "
            f"{sorted(_GAP_KEYS)}; got {sorted(data)}"
        )
    topic, in_scope = data["topic"], data["in_scope"]
    if not isinstance(topic, str) or not topic.strip():
        raise GapLineError(f"{GAP_LINE_PREFIX} `topic` must be a non-empty string")
    if not isinstance(in_scope, bool):
        raise GapLineError(f"{GAP_LINE_PREFIX} `in_scope` must be true or false")
    return Gap(topic=topic.strip(), in_scope=in_scope)


def render_ask_prompt(command_text: str, question: str) -> str:
    """The vault's ``/ask`` command as a one-shot prompt for ``question``.

    Drops the command's YAML frontmatter (Claude Code metadata, not
    instructions) and substitutes ``$ARGUMENTS`` the way the slash command
    itself would.
    """
    body = command_text
    if body.startswith("---\n"):
        end = body.find("\n---\n", 4)
        if end != -1:
            body = body[end + len("\n---\n") :]
    return body.lstrip("\n").replace("$ARGUMENTS", question)


def dispatch_ask(vault: Path, prompt: str, run_dir: Path) -> AskAnswer:
    """Send ``prompt`` to the ``ask`` stage through ``scripts/agent_call.py``.

    The one LLM dispatch surface (Principle IV's static guard), with the same
    bound, process-group isolation and log the weekly runner gets. The answer
    streams to the operator as it arrives; the text this returns is what
    ``agent_call.py`` wrote to ``--output-file`` — the agent's final answer,
    whatever runtime produced it. Prompt, answer, log and cost sidecar land
    under ``run_dir``.
    """
    from . import run_receipt
    from .runner import _call_agent

    prompt_file = run_receipt.stage_path(run_dir, "prompts", ASK_STAGE, ".md")
    answer_file = run_receipt.stage_path(run_dir, "answers", ASK_STAGE, ".md")
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(prompt, encoding="utf-8")
    outcome = _call_agent(
        vault,
        stage=ASK_STAGE,
        quiet=False,
        prompt_file=prompt_file,
        run_dir=run_dir,
        output_file=answer_file,
    )
    if outcome.returncode != 0:
        return AskAnswer(outcome.returncode, "")
    if not answer_file.is_file():
        print(
            f"[ask] ERROR: the ask agent exited 0 but wrote no answer to {answer_file}",
            file=sys.stderr,
        )
        return AskAnswer(1, "")
    return AskAnswer(0, answer_file.read_text(encoding="utf-8"))


def _stderr(message: str) -> None:
    print(f"[ask] {message}", file=sys.stderr)


def run_ask(
    question: str,
    *,
    escalate: bool,
    ask: Callable[[str], AskAnswer],
    research: Callable[[str], int],
    report: Callable[[str], None] = _stderr,
) -> int:
    """Answer ``question``; research a reported in-scope gap only if ``escalate``.

    ``research(topic)`` runs the research and returns its exit code; it owns
    the budget ladder and every refusal the cycle verb makes. It is called at
    most once: a gap that survives the research is reported, not researched
    again, so one ask can never turn into a loop of paid runs.
    """
    answer = ask(question)
    if answer.returncode != 0:
        report(
            f"ERROR: the ask agent exited {answer.returncode}; nothing was researched."
        )
        return answer.returncode
    try:
        gap = parse_gap_line(answer.text)
    except GapLineError as exc:
        report(f"ERROR: {exc}. Nothing was researched.")
        return 1

    if gap is None:
        return 0
    if not gap.in_scope:
        report(
            f"gap outside the vault's declared scope: {gap.topic!r}. "
            "Not researched — widen the spec's scope first if it belongs here."
        )
        return 0
    if not escalate:
        report(
            f"the vault does not cover {gap.topic!r}. Re-run with --escalate to "
            "research it under the vault's configured budget, then re-ask."
        )
        return 0

    report(f"escalating: researching {gap.topic!r} under the configured budget ladder.")
    rc = research(gap.topic)
    if rc != 0:
        report(
            f"ERROR: the research run for {gap.topic!r} exited {rc}; the question "
            "was not re-asked."
        )
        return rc

    report("research finished; asking again.")
    again = ask(question)
    if again.returncode != 0:
        report(f"ERROR: the re-ask exited {again.returncode}.")
        return again.returncode
    try:
        still = parse_gap_line(again.text)
    except GapLineError as exc:
        report(f"ERROR: {exc}.")
        return 1
    if still is not None:
        report(
            f"the vault still does not cover {still.topic!r} after one research "
            "run. Not escalating again."
        )
    return 0
