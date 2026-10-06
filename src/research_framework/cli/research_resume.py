from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

from ..spec.schema import SpecValidationError
from ._budget_resolve import BudgetError, resolve_cycle_budget_from_path
from .budget_resume import (
    handle_approval_marker_on_resume,
    handle_budget_marker_on_resume,
    peek_paused_stage,
    validate_force_budget_flags,
)


def _resume_vault_dir(args: argparse.Namespace) -> Path:
    return args.output or getattr(args, "vault_dir", None) or Path.cwd()


_LOG = logging.getLogger(__name__)

_QUALITY_REPORT_RX = re.compile(r"^cycle-(\d+)-quality-report\.json$")


def _highest_completed_cycle(vault_dir: Path) -> int | None:
    """Scan ``_pipeline/cycles/`` for the highest CLEANLY-COMPLETED cycle.

    A cycle is "cleanly completed" iff ``cycle-NNN-quality-report.json``
    exists at the top of ``_pipeline/cycles/``. The quality report is the
    canonical end-of-cycle artifact written by
    ``pipeline.quality_report.write_report``; nothing else creates it.

    Earlier (0.6.1) we accepted ANY ``cycle-NNN/`` directory OR any
    ``cycle-NNN-*.json`` file as evidence of a completed cycle. That
    over-counted partial state — in particular, ``source_bridge`` writes
    ``cycle-999/source-signals.json`` during early sanity testing, and on
    a vault carrying that artifact ``_highest_completed_cycle`` returned
    999. Resume then tried to start cycle 1000, the orchestrator hit
    ``start_cycle > max_cycles`` immediately, and the run exited with
    "constrained exit — max_cycles reached" without doing any work.

    Tightening to the quality-report-only check is safe because:

    - Quality reports are atomic-written at cycle exit (spec 023).
    - A cycle that aborts mid-stream DOES still write the report (spec 070
      F10 — an earlier version of this docstring claimed otherwise, and was
      wrong on all five live vaults checked). ``_cycle_aborted`` reads the
      explicit marker the orchestrator writes so the anchor falls back.
    - Stray ``cycle-NNN/`` directories from manual experimentation
      (e.g. sentinel writes from ``source_bridge`` smoke runs) are
      ignored.

    Discovered during the feeds-vault revival follow-up (post-mortem
    2026-05-30, "Follow-up" section).
    """
    cycles_dir = vault_dir / "_pipeline" / "cycles"
    if not cycles_dir.is_dir():
        return None
    highest = 0
    for child in cycles_dir.iterdir():
        if not (child.is_file() and child.suffix == ".json"):
            continue
        m = _QUALITY_REPORT_RX.match(child.name)
        if m is None:
            continue
        try:
            n = int(m.group(1))
        except ValueError:
            continue
        if n > highest and not _cycle_aborted(cycles_dir, n):
            highest = n
    return highest if highest > 0 else None


def _cycle_aborted(cycles_dir: Path, cycle: int) -> bool:
    """True when ``cycle`` carries a spec-070 F10 abort marker.

    An aborted cycle still writes its quality report, so the report alone
    cannot distinguish "completed" from "died on the way out".
    """
    return (cycles_dir / f"cycle-{cycle:03d}-aborted.json").is_file()


def _resolve_resume_cycle(args: argparse.Namespace) -> int:
    """Auto-detect resume target.

    Resolution order (spec 025 A4, extended 0.6.1):

    1. ``_pipeline/state.json::in_progress_cycle`` — the cycle currently
       in flight (set when a cycle starts, cleared when it finishes).
    2. ``max(cycle-NNN on disk) + 1`` — if state.json says null but
       completed cycles are visible, treat ``--resume`` as "start the
       next cycle". This makes ``./vault research`` idempotent across
       re-runs: cycle 1 done → next run starts cycle 2, etc.
    3. Error — no state file, no cycles on disk.
    """
    vault_dir = _resume_vault_dir(args)
    state_path = vault_dir / "_pipeline" / "state.json"
    state: dict | None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        state = None
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"_pipeline/state.json is corrupted: {exc}; "
            "use --cycle <N> to specify manually"
        ) from exc

    cycle = None
    if isinstance(state, dict):
        cycle = state.get("in_progress_cycle")
        if isinstance(cycle, list):
            if len(cycle) > 1:
                raise SystemExit(
                    f"multiple in-progress cycles found: {cycle}; "
                    "specify with `--cycle <N>`"
                )
            cycle = cycle[0] if cycle else None
        if cycle is not None and not isinstance(cycle, int):
            raise SystemExit(
                f"invalid in_progress_cycle in state.json: {cycle!r}; "
                "use `--cycle <N>` to specify"
            )

    if cycle is not None:
        return cycle

    # Fallback: scan the cycles dir for the highest completed cycle and
    # advance to the next one (0.6.1 — see docstring).
    highest = _highest_completed_cycle(vault_dir)
    if highest is not None:
        return highest + 1

    # Issue #150: nothing in flight and nothing completed means this is a fresh
    # scaffold (or a vault whose only cycle aborted — spec 070 F10 makes that
    # look the same, correctly, because it must be retried). `--resume` is the
    # documented "safe to re-run if interrupted" verb; hard-erroring here made
    # it hostile on the very first invocation, and the rc7 validation script
    # grew a workaround that injected `--cycle 1` — doing by hand exactly what
    # this function is for.
    _LOG.info(
        "no in-progress or completed cycle on disk; starting at cycle 1 "
        "(fresh vault, or its only cycle aborted and is being retried)"
    )
    return 1


def _resume(args: argparse.Namespace) -> int:
    if getattr(args, "legacy_cycle_runner", False):
        raise NotImplementedError(
            "--legacy-cycle-runner not available; pre-017 path was removed."
        )

    try:
        from ..pipeline.orchestrator import run_cycles
        from ..pipeline.preconditions import check
    except ImportError:
        print("--resume requires pipeline module (available in v0.3+)", file=sys.stderr)
        return 2

    vault_dir = _resume_vault_dir(args)
    # Import via the public cli package so tests can monkeypatch cli.load_spec.
    from research_framework.cli import load_spec as _load_spec
    from research_framework.cli import validate as _validate

    try:
        spec = _load_spec(args.spec, location=vault_dir)
        _validate(spec)
    except SpecValidationError as e:
        for msg in e.messages:
            print(msg, file=sys.stderr)
        return 2

    ok, unmet = check(vault_dir, for_resume=True)
    if not ok:
        # Issue #242: this is an rc=1 rejection, so spec 070 FR6 puts it on
        # stderr. On stdout it was lost to every `> run.log` redirection —
        # and a redirection is also what drops the log level to WARNING, so
        # the operator got a bare exit 1.
        print("Preconditions unmet:", file=sys.stderr)
        for condition in unmet:
            print(f"  - {condition}", file=sys.stderr)
        return 1

    # The resume anchor is resolved FIRST because `--more-cycles N` means "N
    # more from here" and cannot be resolved without knowing where "here" is
    # (issue #239). Nothing in `_resolve_resume_cycle` depends on the budget,
    # so the two only ever had this order by accident.
    if args.cycle is None:
        args.cycle = _resolve_resume_cycle(args)

    # Spec 061: resolve the per-cycle budget from the baked settings.yaml +
    # the (last-word) CLI flags — the SAME ladder as generate, so resume can
    # never silently disagree with the initial run. The resolver emits a loud
    # WARNING for any deprecated/overridden key (FR4).
    try:
        budget = resolve_cycle_budget_from_path(
            vault_dir / "settings.yaml",
            flag_max_cycles=getattr(args, "max_cycles", None),
            flag_max_usd=getattr(args, "max_usd", None),
            flag_more_cycles=getattr(args, "more_cycles", None),
            flag_max_usd_this_run=getattr(args, "max_usd_this_run", None),
            start_cycle=args.cycle,
        )
    except BudgetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    rc_force = validate_force_budget_flags(args)
    if rc_force != 0:
        return rc_force

    # budget-marker.contract.md §4.5. The stage has to be read BEFORE the
    # handler clears the marker, but it is only acted on if that handler let
    # the resume through: a refusal (still over cap, unreadable marker,
    # declined force) leaves the pause standing and promises no skip.
    paused_stage = peek_paused_stage(vault_dir, args.cycle)

    rc_budget = handle_budget_marker_on_resume(args, vault_dir, args.cycle)
    if rc_budget != 0:
        return rc_budget

    rc_approval = handle_approval_marker_on_resume(args, vault_dir)
    if rc_approval != 0:
        return rc_approval

    if paused_stage:
        from ..pipeline.cycle_runner import arm_stage_resume

        arm_stage_resume(args.cycle, paused_stage)

    start = args.cycle
    rc = run_cycles(spec, vault_dir, start_cycle=start, resume=True, budget=budget)
    if rc != 0:
        # H4 (spec-019 / 0.2.28): only finalize a clean run. If
        # run_cycles aborted mid-cycle, we leave the vault as-is so
        # the user can inspect and re-resume.
        return rc
    from research_framework.cli import _run_phase3 as _finalize

    return _finalize(spec, vault_dir)
