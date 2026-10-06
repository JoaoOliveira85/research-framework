"""Budget and approval marker handling for ``research --resume`` (spec 033)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research_framework.cli._tty import is_interactive_tty
from research_framework.pipeline.budget_guard import (
    ApprovalDecision,
    ApprovalRequiredMarker,
    BudgetPausedMarker,
    approval_marker_path,
    budget_marker_path,
    clear_approval_marker,
    clear_budget_marker,
    record_approval_decision,
    sum_sidecar_actuals_usd,
    sum_sidecar_metered_tokens,
    validate_budget_paused_marker,
)
from research_framework.pipeline.settings import LimitsSettings, load_vault_settings


def _env_ack(name: str) -> bool:
    return os.environ.get(name, "").strip() == "1"


def _refused(reason: str, marker_path: Path, remedy: str) -> int:
    """Report a DELIBERATE refusal on stderr and return 1 (issue #244).

    These branches used to return 1 having written nothing at all, which put
    them on the wrong side of spec 070 FR6: the backstop in ``cli.main`` fired
    and told the operator that their own ``--reject`` was "a framework bug".
    A refusal is not a bug, but it still owes FR6 the same three things as
    one — what was refused, where the state was left, and what would make the
    next run valid.

    The marker is named by its path on purpose: it is both the evidence that
    nothing was silently discarded and the thing to delete to abandon the
    pause.
    """
    print(f"{reason}; marker retained at {marker_path}. {remedy}", file=sys.stderr)
    return 1


def _approval_env_key(stage: str) -> str:
    """Per approval-marker.contract.md §5.2 (hyphens → underscores)."""
    normalized = stage.replace("-", "_").upper()
    return f"RF_APPROVE_{normalized}_ACK"


def _decide(marker: ApprovalRequiredMarker, vault_dir: Path, *, approved: bool) -> None:
    """Persist the operator's verdict (approval-marker.contract.md §6).

    Called from every branch where a person actually said yes or no — and from
    none of the branches that merely refuse to guess (a missing ``--approve``,
    a stage mismatch, a missing env ack). "You gave me no flag" is not a
    decision, and recording it as ``approved: false`` would put a verdict in
    the cycle report that nobody reached.
    """
    record_approval_decision(
        vault_dir,
        ApprovalDecision(
            stage_name=marker.stage_name,
            cycle_number=marker.cycle_number,
            approved=approved,
            decided_by_mode="tty" if is_interactive_tty() else "headless",
        ),
    )


def _render_approval_summary(marker: ApprovalRequiredMarker) -> str:
    """approval-marker.contract.md §5.1 step 1 — what step 2 is asking you to buy.

    The contract's TTY protocol is two steps and only the second one existed:
    "display stage, tier, ``estimated_cost_usd``, ``cumulative_spend_usd``,
    ``prompt_preview``", THEN "prompt". So the prompt asked an operator to
    consent to a paid dispatch while withholding every number that would make
    consent meaningful — all of which the marker had already persisted (issue
    #236).

    The projected total is computed here rather than added to the marker: it
    is a rendering of two fields the marker already carries, and putting a
    derived number in a versioned on-disk schema would give a later reader two
    sources for one fact.
    """
    lines = [
        f"APPROVAL_REQUIRED — stage {marker.stage_name!r}, cycle {marker.cycle_number}",
        f"  tier                   {marker.tier}",
    ]
    if marker.agent:
        lines.append(f"  agent                  {marker.agent}")
    projected = marker.cumulative_spend_usd + marker.estimated_cost_usd
    lines.extend(
        [
            f"  estimated cost         ${marker.estimated_cost_usd:.4f}",
            f"  spent this cycle       ${marker.cumulative_spend_usd:.4f}",
            f"  cycle total if you say yes  ${projected:.4f}",
            f"  paused at              {marker.paused_at}",
            "  prompt preview:",
        ]
    )
    preview = (marker.prompt_preview or "").strip()
    lines.extend(f"    {line}" for line in (preview.splitlines() or [""]))
    return "\n".join(lines)


def _show_approval_summary(marker: ApprovalRequiredMarker) -> None:
    """Print the §5.1 summary on stderr.

    stderr, not stdout: this is the reason a run stopped, and spec 070 FR6's
    stream rule exists because `> run.log` takes stdout away in the same
    breath as it drops the log level.
    """
    print(_render_approval_summary(marker), file=sys.stderr)


def _approval_remedy(stage: str) -> str:
    """The "what would make it valid" half of FR6 for an approval pause."""
    return (
        f"Re-run with `--approve {stage}` (headless also needs "
        f"`{_approval_env_key(stage)}=1`) to dispatch it, or delete the marker "
        "to abandon the paused stage."
    )


@dataclass(frozen=True)
class _CapRecheck:
    """One cap, re-evaluated at resume time (budget-marker.contract.md §4.3-4.5).

    ``pause_reason`` names the currency that stopped the run; this is the
    answer to "is that same currency still over its ceiling?", carrying the
    three renderings the resume flow owes an operator: a sentence for a TTY, a
    machine-readable body for a headless run, and the settings key that would
    make the next attempt legal.
    """

    pause_reason: str
    still_exceeded: bool
    tty_message: str
    payload: dict[str, Any]
    remedy: str


def _recheck_dollar_cap(
    limits: LimitsSettings, vault_dir: Path, cycle: int
) -> _CapRecheck:
    cap = limits.cycle_budget_usd
    actual = sum_sidecar_actuals_usd(vault_dir, cycle)
    return _CapRecheck(
        pause_reason="dollar_cap_exceeded",
        still_exceeded=cap is not None and actual > cap,
        tty_message=(
            f"Budget still exceeded: ${actual:.4f} > "
            f"${cap if cap is not None else 0.0:.4f}."
        ),
        payload={
            "error": "budget_paused",
            "pause_reason": "dollar_cap_exceeded",
            "actual_usd": actual,
            "cycle_budget_usd": cap,
        },
        remedy="Bump limits.cycle_budget_usd or pass --force-budget.",
    )


def _recheck_metered_token_cap(
    limits: LimitsSettings, vault_dir: Path, cycle: int
) -> _CapRecheck:
    cap = limits.codex_token_budget
    actual = sum_sidecar_metered_tokens(vault_dir, cycle)
    return _CapRecheck(
        pause_reason="codex_token_cap_exceeded",
        still_exceeded=cap is not None and actual > cap,
        tty_message=(
            f"Metered-token budget still exceeded: {actual} tokens > "
            f"codex_token_budget {cap}."
        ),
        payload={
            "error": "budget_paused",
            "pause_reason": "codex_token_cap_exceeded",
            "metered_tokens": actual,
            "codex_token_budget": cap,
        },
        remedy="Bump limits.codex_token_budget or pass --force-budget.",
    )


def _recheck_wallclock_cap(
    limits: LimitsSettings, marker: BudgetPausedMarker
) -> _CapRecheck:
    """Re-test the wall-clock ceiling against the elapsed the marker recorded.

    A wall-clock cap is the one limit resume cannot recompute.
    ``CycleSpendTally.cycle_started_mono`` is a ``time.monotonic()`` reading —
    meaningless outside the process that took it — and nothing else on disk
    records when the paused cycle began. Reading it as "elapsed resets on
    resume" is what made a wall-clock pause free to walk past: the clock
    restarted and the cap could never be over.

    So the marker's own ``wallclock_elapsed_seconds`` is the authority here,
    tested against the CURRENT configured ceiling. That gives a wall-clock
    pause the same shape as every other: the operator clears it by raising the
    ceiling above what the run already spent (or by forcing past it), and the
    new process then starts its own clock from zero — which is the honest
    reading, since a fresh process really is beginning a fresh cycle's work.
    """
    cap_minutes = limits.cycle_wallclock_budget_minutes
    cap_seconds = float(cap_minutes) * 60.0 if cap_minutes else None
    elapsed = float(marker.wallclock_elapsed_seconds or 0.0)
    return _CapRecheck(
        pause_reason="wallclock_exceeded",
        still_exceeded=cap_seconds is not None and elapsed > cap_seconds,
        tty_message=(
            f"Wall-clock budget still exceeded: {elapsed:.0f}s elapsed in the "
            f"paused cycle > {cap_seconds or 0.0:.0f}s cap."
        ),
        payload={
            "error": "budget_paused",
            "pause_reason": "wallclock_exceeded",
            "wallclock_elapsed_seconds": elapsed,
            "cycle_wallclock_budget_minutes": cap_minutes,
        },
        remedy=(
            "Bump limits.cycle_wallclock_budget_minutes above the elapsed "
            "time above, or pass --force-budget."
        ),
    )


def _recheck_paused_cap(
    marker: BudgetPausedMarker, limits: LimitsSettings, vault_dir: Path, cycle: int
) -> _CapRecheck:
    """Re-check the cap named by ``pause_reason`` — and only that one."""
    if marker.pause_reason == "wallclock_exceeded":
        return _recheck_wallclock_cap(limits, marker)
    if marker.pause_reason == "codex_token_cap_exceeded":
        return _recheck_metered_token_cap(limits, vault_dir, cycle)
    return _recheck_dollar_cap(limits, vault_dir, cycle)


def _load_valid_budget_marker(marker_path: Path) -> BudgetPausedMarker:
    """Parse + validate the marker, per budget-marker.contract.md §4.2.

    Raises ``ValueError`` for anything this build must not act on. The
    validator has existed since spec 033 shipped and had no production caller,
    so a marker with a bogus ``pause_reason`` or ``schema_version`` was parsed
    into whatever ``from_path`` could coerce and then deleted.
    """
    doc = json.loads(marker_path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("marker is not a JSON object")
    validate_budget_paused_marker(doc)
    return BudgetPausedMarker.from_path(marker_path)


def peek_paused_stage(vault_dir: Path, cycle: int) -> str | None:
    """The stage ``BUDGET_PAUSED`` names for ``cycle`` — read before the clear.

    ``handle_budget_marker_on_resume`` deletes the marker on its way past, and
    ``run_cycles`` is called after that, so the stage has to be read here or
    not at all (budget-marker.contract.md §4.5).

    Returns ``None`` for anything the caller must not act on: no marker, a
    marker this build cannot read (the budget handler owns that refusal, and
    will make it), or a marker belonging to a DIFFERENT cycle. That last case
    matters most — skipping phases of a cycle the pause never touched would
    drop work, not just re-spend money.
    """
    marker_path = budget_marker_path(vault_dir)
    if not marker_path.is_file():
        return None
    try:
        marker = _load_valid_budget_marker(marker_path)
    except (OSError, ValueError, TypeError, KeyError):
        return None
    if marker.cycle_number != cycle:
        return None
    return marker.paused_stage or None


def handle_budget_marker_on_resume(
    args: argparse.Namespace, vault_dir: Path, cycle: int
) -> int:
    """Budget marker precedence (budget-marker.contract.md §4)."""
    marker_path = budget_marker_path(vault_dir)
    if not marker_path.is_file():
        return 0
    try:
        marker = _load_valid_budget_marker(marker_path)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        # Deliberately NOT forceable: `--force-budget` is consent to overspend
        # a cap the operator can see, not consent to resume past a pause
        # nobody can read. Deleting it here would be the silent-clear bug in a
        # new costume.
        return _refused(
            f"BUDGET_PAUSED is not a valid marker per "
            f"budget-marker.contract.md §2 ({exc})",
            marker_path,
            "Inspect it, then delete it to abandon the pause. Resuming over "
            "an unreadable marker would drop whichever cap stopped the run.",
        )
    settings = load_vault_settings(vault_dir)
    recheck = _recheck_paused_cap(marker, settings.limits, vault_dir, cycle)
    force = _flag_is_true(args, "force_budget")
    if recheck.still_exceeded and not force:
        if is_interactive_tty():
            print(f"{recheck.tty_message} {recheck.remedy}", file=sys.stderr)
            return 1
        print(json.dumps(recheck.payload), file=sys.stderr)
        return 1
    if force and recheck.still_exceeded:
        if not is_interactive_tty() and not _env_ack("RF_FORCE_BUDGET_ACK"):
            print(
                json.dumps({"error": "force_budget_requires_RF_FORCE_BUDGET_ACK"}),
                file=sys.stderr,
            )
            return 1
        if is_interactive_tty():
            answer = input("Force resume despite budget cap? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                return _refused(
                    f"declined to force past the budget cap ({recheck.tty_message})",
                    marker_path,
                    f"{recheck.remedy} Or re-run `--force-budget` and answer `y`.",
                )
    clear_budget_marker(vault_dir)
    print(
        f"BUDGET_PAUSED cleared: {recheck.pause_reason} re-checked at "
        f"stage {marker.paused_stage!r}"
        + (" and forced past" if recheck.still_exceeded else " and now satisfied")
        + ".",
        file=sys.stderr,
    )
    return 0


def handle_approval_marker_on_resume(args: argparse.Namespace, vault_dir: Path) -> int:
    """Approval marker branch (approval-marker.contract.md §5)."""
    marker_path = approval_marker_path(vault_dir)
    if not marker_path.is_file():
        return 0
    marker = ApprovalRequiredMarker.from_path(marker_path)
    reject_stage = getattr(args, "reject", None)
    if reject_stage:
        if reject_stage == marker.stage_name or reject_stage == "all":
            _decide(marker, vault_dir, approved=False)
            return _refused(
                f"rejected approval for stage {marker.stage_name!r}",
                marker_path,
                _approval_remedy(marker.stage_name),
            )
    approve_stage = getattr(args, "approve", None)
    approve_all = _flag_is_true(args, "approve_all")
    if is_interactive_tty():
        if approve_all or (approve_stage and approve_stage == marker.stage_name):
            # Shown even though the flag has already decided: `--approve` on a
            # TTY is still a person watching a gate clear, and the cost of the
            # dispatch they just authorised is the one thing worth seeing.
            _show_approval_summary(marker)
            _decide(marker, vault_dir, approved=True)
            clear_approval_marker(vault_dir)
            return 0
        if approve_stage and approve_stage != marker.stage_name:
            print(
                json.dumps(
                    {
                        "error": "approve_stage_mismatch",
                        "expected": marker.stage_name,
                        "got": approve_stage,
                    }
                ),
                file=sys.stderr,
            )
            return 1
        # Contract §5.1: display, THEN prompt. In that order, always.
        _show_approval_summary(marker)
        answer = (
            input(f"Approve dispatch for stage {marker.stage_name!r}? [y/N] ")
            .strip()
            .lower()
        )
        if answer in ("y", "yes"):
            _decide(marker, vault_dir, approved=True)
            clear_approval_marker(vault_dir)
            return 0
        _decide(marker, vault_dir, approved=False)
        return _refused(
            f"declined approval for stage {marker.stage_name!r}",
            marker_path,
            _approval_remedy(marker.stage_name),
        )
    if not approve_stage and not approve_all:
        print(
            json.dumps({"error": "approval_required", "stage": marker.stage_name}),
            file=sys.stderr,
        )
        return 1
    if approve_stage and approve_stage != marker.stage_name and not approve_all:
        print(
            json.dumps(
                {
                    "error": "approve_stage_mismatch",
                    "expected": marker.stage_name,
                    "got": approve_stage,
                }
            ),
            file=sys.stderr,
        )
        return 1
    if approve_all:
        if not _env_ack("RF_APPROVE_ALL_ACK"):
            print(
                json.dumps({"error": "approve_all_requires_RF_APPROVE_ALL_ACK"}),
                file=sys.stderr,
            )
            return 1
    elif approve_stage:
        env_key = _approval_env_key(approve_stage)
        if not _env_ack(env_key):
            print(json.dumps({"error": f"{env_key}_required"}), file=sys.stderr)
            return 1
    _decide(marker, vault_dir, approved=True)
    clear_approval_marker(vault_dir)
    return 0


def _flag_is_true(args: argparse.Namespace, name: str) -> bool:
    """Return True only for an explicit boolean ``True`` (mocks are not flags)."""
    return getattr(args, name, None) is True


def validate_force_budget_flags(args: argparse.Namespace) -> int:
    """Pre-flight for ``--force-budget`` (ack lives in budget-marker handler)."""
    _ = args
    return 0
