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
    ResearchOutcome,
    dispatch_ask,
    render_ask_prompt,
    run_ask,
)
from ._budget_resolve import BudgetError, resolve_cycle_budget_from_path
from .research_cycles import _cmd_cycle, _standing_pause
from .research_resume import _cycle_aborted, _highest_completed_cycle


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


def _has_ask_stage(vault: Path) -> bool:
    """True when settings.yaml declares a ``stages.ask`` mapping."""
    import yaml

    try:
        data = yaml.safe_load((vault / "settings.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return False
    stages = data.get("stages") if isinstance(data, dict) else None
    return isinstance(stages, dict) and isinstance(stages.get("ask"), dict)


def _next_cycle(vault: Path) -> int:
    """The cycle an escalation runs: the one after the last completed cycle."""
    highest = _highest_completed_cycle(vault)
    return (highest or 0) + 1


def _research(vault: Path, topic: str) -> ResearchOutcome:
    """Run ONE cycle at ``topic`` through the ``cycle`` verb, under the ladder.

    No dollar figure is chosen here: ``budget_cap=None`` makes ``_cmd_cycle``
    resolve ``pipeline.budget_usd`` from settings.yaml exactly as it does for
    an operator who omits ``--budget-cap``, and the per-cycle
    ``limits.cycle_budget_usd`` stays enforced before every dispatch.

    Two lifetime ceilings are checked before the cycle starts, because an
    escalation picks its own cycle number and nobody typed it:
    ``pipeline.max_cycles`` (the highest cycle number this vault may run) and
    ``pipeline.budget_usd`` against the spend already recorded in the cycle
    cost sidecars — the same sum the multi-cycle loop compares it with.
    """
    from ..pipeline.orchestrator import _cumulative_sidecar_cost

    cycle = _next_cycle(vault)
    try:
        budget = resolve_cycle_budget_from_path(
            vault / "settings.yaml", start_cycle=cycle
        )
    except BudgetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return ResearchOutcome("failed", 2, "budget settings are invalid")
    if cycle > budget.max_cycles:
        print(
            f"error: escalating would run cycle {cycle}, past this vault's "
            f"lifetime ceiling of {budget.max_cycles} (pipeline.max_cycles, "
            f"from {budget.max_cycles_source}). Raise it in "
            f"{vault / 'settings.yaml'} to research this gap.",
            file=sys.stderr,
        )
        return ResearchOutcome("failed", 2, "pipeline.max_cycles reached")
    if budget.max_usd is not None and budget.max_usd > 0:
        spent = _cumulative_sidecar_cost(vault, up_to=cycle)
        if spent >= budget.max_usd:
            print(
                f"error: this vault has recorded ${spent:.4f} of spend, at or "
                f"past its lifetime ceiling of ${budget.max_usd:.2f} "
                f"(pipeline.budget_usd, from {budget.max_usd_source}). No cycle "
                f"was started. Raise it in {vault / 'settings.yaml'} to research "
                "this gap.",
                file=sys.stderr,
            )
            return ResearchOutcome("failed", 2, "pipeline.budget_usd reached")

    paused_before = _standing_pause(vault)
    cycle_args = argparse.Namespace(
        vault=vault,
        cycle=cycle,
        budget_cap=None,
        estimate_only=False,
        target_topics=[topic],
    )
    try:
        rc = _cmd_cycle(cycle_args)
    except SystemExit as exc:
        # A budget or approval pause exits the process from inside the cycle
        # (`budget_guard.pause_for_budget`), having written its marker and its
        # reason. It is told apart below by the marker, not by this code.
        rc = exc.code if isinstance(exc.code, int) and exc.code else 1

    # A marker that was standing BEFORE the run made `_cmd_cycle` refuse; one
    # that appeared during it is this run pausing at a ceiling.
    paused_after = _standing_pause(vault)
    if paused_before is None and paused_after is not None:
        name, path = paused_after
        return ResearchOutcome("paused", rc or 1, f"{name} at {path}")
    if _cycle_aborted(vault / "_pipeline" / "cycles", cycle):
        return ResearchOutcome("failed", rc or 2, f"cycle {cycle} aborted")
    # 0 is CONTINUE and 1 is TERMINATE (a validate_cycle condition met): both
    # are a cycle that ran to its end.
    if rc in (0, 1):
        return ResearchOutcome("completed", rc)
    return ResearchOutcome("failed", rc)


def _cmd_ask(args: argparse.Namespace) -> int:
    vault = Path(args.vault).resolve()
    if not vault.is_dir():
        print(f"error: vault not found: {vault}", file=sys.stderr)
        return 2
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

    if not _has_ask_stage(vault):
        # Without the block the dispatch inherits default_executor — on the
        # shipped claude profile, bypassPermissions — so a vault that
        # refreshed ask.md but not settings.yaml would ask with full
        # permissions, and could run the research it was told not to.
        print(
            f"error: {vault / 'settings.yaml'} has no `stages.ask` block, so the "
            "ask agent would run with default_executor's permissions. Copy the "
            "`stages.ask` block from the matching shipped settings profile "
            "(CHANGELOG, issue #15 migration notes) and re-run.",
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
