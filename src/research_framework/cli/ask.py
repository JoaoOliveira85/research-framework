"""``research-framework ask`` — a one-shot vault question (issue #15).

``./vault ask --escalate`` forwards here. The flow itself lives in
:mod:`research_framework.pipeline.ask_escalation`; this module wires it to the
vault: the vault's own ``/ask`` command as the prompt, ``agent_call.py`` as the
dispatch, and the ``cycle`` verb as the research run — so an escalation meets
every gate a hand-typed ``cycle --target-topics`` meets (standing pause
markers, the spec-061 budget ladder, the spec-074 spec check) and its topic is
recorded by the spec-073 append, the only writer of discovered ground.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from ..pipeline.ask_escalation import (
    GAP_LINE_PREFIX,
    dispatch_ask,
    render_ask_prompt,
    run_ask,
)
from ._budget_resolve import BudgetError, resolve_cycle_budget_from_path
from .research_cycles import _cmd_cycle
from .research_resume import _highest_completed_cycle


def _ask_command_path(vault: Path) -> Path:
    """``.claude/commands/<stem>.md`` — the stem a spec may have renamed."""
    from ..agents._render import command_stems
    from ..spec.simple import load as load_spec

    stem = "ask"
    spec_path = vault / "research.spec.md"
    if spec_path.is_file():
        try:
            stem = command_stems(load_spec(spec_path, location=vault))["ask"]
        except Exception:  # noqa: BLE001 - the default name is the honest fallback
            stem = "ask"
    return vault / ".claude" / "commands" / f"{stem}.md"


def _next_cycle(vault: Path) -> int:
    """The cycle an escalation runs: the one after the last completed cycle."""
    highest = _highest_completed_cycle(vault)
    return (highest or 0) + 1


def _research(vault: Path, topic: str) -> int:
    """Run ONE cycle at ``topic`` through the ``cycle`` verb, under the ladder.

    No dollar figure is chosen here: ``budget_cap=None`` makes ``_cmd_cycle``
    resolve ``pipeline.budget_usd`` from settings.yaml exactly as it does for
    an operator who omits ``--budget-cap``, and the per-cycle
    ``limits.cycle_budget_usd`` stays enforced before every dispatch. The one
    check added is the lifetime cycle ceiling, which ``cycle`` leaves to the
    operator who typed a cycle number — an escalation picks the number itself,
    so it must not pick one past ``pipeline.max_cycles``.
    """
    cycle = _next_cycle(vault)
    try:
        budget = resolve_cycle_budget_from_path(
            vault / "settings.yaml", start_cycle=cycle
        )
    except BudgetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if cycle > budget.max_cycles:
        print(
            f"error: escalating would run cycle {cycle}, past this vault's "
            f"lifetime ceiling of {budget.max_cycles} (pipeline.max_cycles, "
            f"from {budget.max_cycles_source}). Raise it in "
            f"{vault / 'settings.yaml'} to research this gap.",
            file=sys.stderr,
        )
        return 2
    cycle_args = argparse.Namespace(
        vault=vault,
        cycle=cycle,
        budget_cap=None,
        estimate_only=False,
        target_topics=[topic],
    )
    try:
        return _cmd_cycle(cycle_args)
    except SystemExit as exc:
        # A budget or approval pause exits the process from inside the cycle
        # (`budget_guard.pause_for_budget`), having written its marker and its
        # reason. That is the ceiling holding; the ask reports it, not re-asks.
        return exc.code if isinstance(exc.code, int) and exc.code else 1


def _cmd_ask(args: argparse.Namespace) -> int:
    vault = Path(args.vault).resolve()
    question = " ".join(args.question).strip()
    if not question:
        print("error: ask needs a question.", file=sys.stderr)
        return 2

    command_path = _ask_command_path(vault)
    if not command_path.is_file():
        print(f"error: no /ask command at {command_path}.", file=sys.stderr)
        return 2
    command_text = command_path.read_text(encoding="utf-8")
    if GAP_LINE_PREFIX not in command_text:
        # A command written before issue #15 tells the agent to start a paid
        # cycle itself and never writes the line this verb reads: dispatching
        # it would let the agent spend, and report "no gap" when there was one.
        print(
            f"error: {command_path} predates the {GAP_LINE_PREFIX} gap contract "
            "(it may still tell the agent to start research itself). Refresh "
            f"it with `research-framework regenerate-agents {vault} --agent ask`.",
            file=sys.stderr,
        )
        return 2

    stamp = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H%M%SZ")
    run_dir = vault / "_pipeline" / "ask" / stamp
    return run_ask(
        question,
        escalate=bool(args.escalate),
        ask=lambda q: dispatch_ask(vault, render_ask_prompt(command_text, q), run_dir),
        research=lambda topic: _research(vault, topic),
    )
