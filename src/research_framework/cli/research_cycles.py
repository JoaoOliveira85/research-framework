from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..spec.schema import SpecValidationError
from ..spec.simple import load as load_spec
from ..spec.validator import validate
from ._budget_resolve import BudgetError, resolve_cycle_budget_from_path

#: The two pause markers, in the precedence the resume path resolves them
#: (budget-marker.contract.md §4: budget first, approval second).
_PAUSE_MARKERS: tuple[tuple[str, str], ...] = (
    ("BUDGET_PAUSED", "_pipeline/BUDGET_PAUSED"),
    ("APPROVAL_REQUIRED", "_pipeline/APPROVAL_REQUIRED"),
)


def _standing_pause(vault: Path) -> tuple[str, Path] | None:
    """The first pause marker standing in ``vault``, or ``None``.

    Deliberately cycle-agnostic. ``cycle`` carries no ``--force-budget`` /
    ``--approve`` surface, so it is in no position to decide a pause for a
    particular cycle; the only honest reading it can take of "a marker exists"
    is "something is waiting on a person".
    """
    for name, rel in _PAUSE_MARKERS:
        path = vault / rel
        if path.is_file():
            return name, path
    return None


def _refuse_over_pause(name: str, path: Path) -> int:
    """Spec 070 FR6: what was refused, where the state is, what makes it valid.

    Issue #233's table: only ``generate --resume`` honoured pause markers, so
    running ``cycle`` after a pause dispatched the paused stage again and paid
    for it a second time — the same double-spend §4.5 was amended to stop,
    reached through a different verb.
    """
    print(
        f"error: {name} is standing at {path} — this vault is waiting on an "
        "operator decision, and `cycle` has no flag that can make one.\n"
        "Inspect it with `research-framework pause show --vault <vault>`, then "
        "either resume properly (`research-framework generate --resume ...` "
        "with --force-budget / --approve <stage>) or abandon it with "
        "`research-framework pause clear --vault <vault>`.",
        file=sys.stderr,
    )
    return 2


def _cmd_cycle(args: argparse.Namespace) -> int:
    try:
        from ..pipeline.orchestrator import (
            clear_cycle_aborted,
            mark_cycle_aborted,
            run_single_cycle,
        )
    except ImportError:
        print("pipeline not available in this build", file=sys.stderr)
        return 2

    # A standing pause outranks every other complaint this verb could make:
    # it is the one fact that explains why the vault is where it is, and a
    # config nit reported ahead of it would bury it.
    pause = _standing_pause(args.vault)
    if pause is not None:
        return _refuse_over_pause(*pause)

    # Spec 061: ONE ladder for every run verb. `--budget-cap` is this verb's
    # `--max-usd` rung; omitted, `pipeline.budget_usd` decides; absent, the
    # run is uncapped. The $10.00 that used to sit in the parser was a budget
    # from no rung at all (issue #233).
    try:
        budget = resolve_cycle_budget_from_path(
            args.vault / "settings.yaml",
            flag_max_usd=getattr(args, "budget_cap", None),
            start_cycle=args.cycle,
            # This verb's spelling of the flag. A resolver that names a flag
            # the operator did not type sends them looking for the wrong knob.
            usd_flag_name="--budget-cap",
        )
    except BudgetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    budget_cap = budget.max_usd if budget.max_usd is not None else 0.0

    if getattr(args, "estimate_only", False):
        return _estimate_only(args.vault, args.cycle)

    # Spec 074: the spec MUST reach the orchestrator or `--target-topics` is
    # silently discarded. `run_single_cycle` guards the scout-prompt re-render
    # on `spec is not None`, so calling it without one meant the flag was
    # accepted, documented in --help, threaded through two layers, and inert.
    spec = None
    spec_path = args.vault / "research.spec.md"
    load_error = ""
    if spec_path.is_file():
        try:
            spec = load_spec(spec_path, location=args.vault)
        except Exception as exc:  # noqa: BLE001 - reported below, never swallowed
            load_error = f"{type(exc).__name__}: {exc}"

    # Deliberately LOADED, not validated. The scout renderer needs a SpecConfig,
    # not a conforming one, and hard-validating here would refuse vaults that
    # have been running for cycles — the same over-strictness trap spec 070 FR2
    # hit. A spec problem severe enough to matter surfaces at its own gate.
    if spec is None and args.target_topics:
        # Refuse rather than run a cycle that quietly ignores what was asked
        # for — a discarded flag must never look like success.
        detail = f" ({load_error})" if load_error else ""
        print(
            f"error: --target-topics needs {spec_path} to render the scout "
            f"prompt, and it could not be loaded{detail}. Re-run without the "
            "flag to research the existing backlog instead.",
            file=sys.stderr,
        )
        return 2

    # Spec 070 F10, as `run_cycles` does it: the cycle runner writes the
    # quality report on every exit, so a cycle that aborted (rc=2) or left by
    # exception (Ctrl-C, a budget or approval pause, a crash) reads as
    # completed unless it is marked, and `--resume` then skips past it.
    try:
        rc = run_single_cycle(
            args.vault,
            cycle_num=args.cycle,
            budget_cap=budget_cap,
            max_cycles=budget.max_cycles,
            spec=spec,
            resume=bool(args.target_topics),
            target_topics=args.target_topics,
        )
    except BaseException as exc:
        mark_cycle_aborted(
            args.vault,
            args.cycle,
            reason=f"cycle {args.cycle} interrupted ({type(exc).__name__})",
        )
        raise
    if rc == 2:
        mark_cycle_aborted(
            args.vault, args.cycle, reason=f"cycle {args.cycle} aborted (exit 2)"
        )
    else:
        clear_cycle_aborted(args.vault, args.cycle)

    # Spec 073: a query that found ground the spec did not declare records it,
    # so the next person does not have to reconstruct it from a chat
    # transcript. `ask.md` escalates through this very command, which is why
    # the hook lives here rather than in the interactive session.
    #
    # Best-effort by design: the research has already succeeded, and a
    # bookkeeping failure must not change this cycle's exit code.
    if spec is not None:
        try:
            from ..pipeline.spec_append import record_query_discoveries

            if record_query_discoveries(
                args.vault, spec, args.cycle, args.target_topics
            ):
                print(
                    "[spec-append] recorded discovered ground in "
                    f"{args.vault / 'research.spec.md'}",
                    file=sys.stderr,
                )
        except Exception as exc:  # noqa: BLE001 - reported, never fatal
            print(f"[spec-append] skipped: {exc}", file=sys.stderr)
    return rc


def _estimate_only(vault: Path, cycle_num: int) -> int:
    """Print the projected spend for ``cycle_num`` and dispatch nothing (#238).

    Exit 2 when no ``limits.cycle_budget_usd`` resolves. The preflight's whole
    question is "is this safe to leave running unattended", and a run with no
    ceiling is not — nothing would stop it, whatever it cost. The estimate is
    still printed first: a refusal that withholds the number it refused over
    would be useless.
    """
    from ..pipeline.budget_preflight import estimate_cycle, render_estimate_text

    estimate = estimate_cycle(vault, cycle_num=cycle_num)
    print(render_estimate_text(estimate))
    if estimate.cycle_budget_usd is None:
        print(
            "error: no `limits.cycle_budget_usd` is configured for this vault, "
            "so nothing would pause an unattended run. Set one in "
            f"{vault / 'settings.yaml'} before leaving this running.",
            file=sys.stderr,
        )
        return 2
    return 0


_PIPELINE_STATUS_ICONS = {
    "done": "✓",
    "pending": "–",
    "in_progress": "→",
    "waiting": "⏸",
    "failed": "✗",
    "skipped": "⊘",
}


def _format_phase_duration(seconds: float | None) -> str | None:
    """Render a phase's ``duration_s`` as ``1h02m03s`` / ``2m03s`` / ``3s``."""
    if seconds is None:
        return None
    total = int(round(max(0.0, seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def _format_phase_cost(rec: dict) -> str:
    """``$0.2500`` for a phase that dispatched, ``cost unknown`` when the
    sidecar it asked for did not arrive, and nothing at all for a phase that
    never dispatched (spec 080 FR-012)."""
    if not isinstance(rec.get("summary"), dict):
        return ""
    if rec["summary"].get("cost_sidecar") is None:
        return ""
    cost = rec.get("cost_usd")
    return f"${cost:.4f}" if isinstance(cost, int | float) else "cost unknown"


def _render_pipeline_status_text(summary: dict) -> str:
    """Human-readable ``pipeline status`` rendering (issue #245).

    Unlike the old TTY-only path, this always shows the persisted
    ``errors[]`` and each phase's duration — the read side of the
    failure-reporting story is worthless if the one place an operator
    looks omits the reason a phase failed.
    """
    run_id = summary.get("run_id") or "none"
    started = summary.get("started_at") or "—"
    lines = [f"Pipeline status (run {run_id}, started {started}):"]
    for phase, rec in summary.get("phases", {}).items():
        st = rec.get("status", "pending")
        icon = _PIPELINE_STATUS_ICONS.get(st, "?")
        duration = _format_phase_duration(rec.get("duration_s"))
        bits = [b for b in (duration, _format_phase_cost(rec)) if b]
        tail = f"  ({', '.join(bits)})" if bits else ""
        lines.append(f"  {phase:<10} {icon} {st}{tail}")
        summ = rec.get("summary")
        if summ and isinstance(summ, dict):
            for k, v in summ.items():
                lines.append(f"      {k}: {v}")
        for err in rec.get("errors") or []:
            lines.append(f"      ! {err}")

    # Spec 080 FR-018: where the run's own record is, and what it cost. Both
    # are `None` on a vault whose runs predate the receipt, and the renderer
    # says nothing rather than inventing a path (FR-019).
    if summary.get("run_dir"):
        lines.append(f"  Run directory: {summary['run_dir']}")
    if summary.get("receipt"):
        lines.append(f"  Receipt:       {summary['receipt']}")
    total = summary.get("cost_total_usd")
    # FR-013: a total computed with a sidecar missing is a floor, and every
    # rendering of it has to say so. When NO sidecar could be read there is no
    # total at all — "unknown" is the honest word, and "$0.0000" would be a
    # number an operator adds up across eight vaults.
    if total is not None:
        bound = (
            " — a lower bound: at least one cost sidecar could not be read"
            if summary.get("cost_is_lower_bound")
            else ""
        )
        lines.append(f"  Cost:          ${total:.4f}{bound}")
    elif summary.get("cost_is_lower_bound"):
        lines.append(
            "  Cost:          unknown — every cost sidecar this run asked for "
            "is missing, so it has no spend record at all"
        )
    return "\n".join(lines)


def _prune_runs(vault: Path, args: argparse.Namespace) -> int:
    """``pipeline <vault> prune-runs`` — spec 080 FR-020 / T008.

    Run directories are never pruned automatically: the record of a bad night
    is the thing an operator goes looking for weeks later, and a framework
    that deletes it on a schedule is a framework that deletes the evidence.
    This verb is the explicit ask, with the same cap-N-AND-age shape #307 gave
    research branches — a directory survives if it is among the newest N *or*
    younger than the age. The run named by the current state file survives
    whatever the bounds say.
    """
    import shutil

    from ..pipeline import run_receipt
    from ..pipeline.runner import STATE_FILE

    current: str | None = None
    state_path = vault / STATE_FILE
    if state_path.is_file():
        try:
            raw = json.loads(state_path.read_text(encoding="utf-8"))
            current = raw.get("run_id") if isinstance(raw, dict) else None
        except (OSError, json.JSONDecodeError):
            current = None

    keep = int(getattr(args, "keep", 5))
    older_than_days = int(getattr(args, "older_than_days", 90))
    if keep < 0 or older_than_days < 0:
        print(
            "error: --keep and --older-than must be zero or greater; "
            f"got --keep {keep} --older-than {older_than_days}.",
            file=sys.stderr,
        )
        return 2

    doomed = run_receipt.prunable_runs(
        vault, keep=keep, older_than_days=older_than_days, current_run_id=current
    )
    if not doomed:
        print(
            f"Nothing to prune: every run directory under "
            f"{run_receipt.runs_root(vault)} is among the newest {keep} or "
            f"younger than {older_than_days} days."
        )
        return 0

    dry = bool(getattr(args, "dry_run", False))
    verb = "Would remove" if dry else "Removed"
    for path in doomed:
        if not dry:
            shutil.rmtree(path, ignore_errors=True)
        print(f"{verb} {path}")
    print(
        f"{verb.lower()} {len(doomed)} run director"
        f"{'y' if len(doomed) == 1 else 'ies'} "
        f"(keeping the newest {keep} and anything younger than "
        f"{older_than_days} days)."
    )
    return 0


def _cmd_pipeline(args: argparse.Namespace) -> int:
    """Dispatch pipeline subcommands to runner functions."""
    from ..pipeline.runner import (
        run_collect,
        run_extract,
        run_finish,
        run_full,
        run_resume,
        run_scout,
        status,
    )

    vault: Path = args.vault.resolve()
    if not vault.exists() or not vault.is_dir():
        print(f"error: vault not found: {vault}", file=sys.stderr)
        return 2

    sub = args.pipeline_cmd
    quiet: bool = getattr(args, "quiet", False)

    # Issue #232: `--budget-cap` was accepted here, threaded into `run_full`,
    # documented as "passed to agent invocations" — and read by nothing in
    # `runner.py`. Spec 074 set the precedent: refuse loudly rather than let a
    # cap the operator believes in enforce nothing.
    #
    # Spec 080 made pipeline spend RECORDED (every dispatch writes a sidecar
    # under the run directory) and the decision at 080 T009 is that the flag
    # still stays refused. A cap has to be checked BEFORE a dispatch; the
    # sidecar exists only after one. Enforcing against a running total would
    # stop the run at the first phase that overshot, having already paid for
    # it — a cap that reports a breach rather than preventing one.
    # `limits.cycle_budget_usd` is enforced at `agent_call.py`, the surface
    # that knows a call is about to happen, which is where spec 033 put it.
    if getattr(args, "budget_cap", None) is not None:
        print(
            "error: --budget-cap is not implemented for `pipeline` runs and is "
            "refused rather than silently ignored. A cap must be checked before "
            "a dispatch; this verb learns what a phase cost only after it ran "
            "(see `_pipeline/runs/<run_id>/run.json`). Cap spend with "
            "`limits.cycle_budget_usd` in the vault's settings.yaml (enforced "
            "before every dispatch), or run a research cycle with "
            "`cycle --budget-cap`.",
            file=sys.stderr,
        )
        return 2

    # `--dry-run` belongs to `prune-runs`. Accepted on a run verb it was read
    # by nothing, so `full --dry-run` ran the real, paid pipeline.
    if getattr(args, "dry_run", False) and sub != "prune-runs":
        print(
            f"error: --dry-run applies only to `pipeline <vault> prune-runs`; "
            f"`{sub}` has no dry-run mode and was not started.",
            file=sys.stderr,
        )
        return 2

    if sub == "full":
        return run_full(vault, quiet=quiet)
    elif sub == "collect":
        return run_collect(vault, quiet=quiet)
    elif sub == "extract":
        return run_extract(vault, quiet=quiet)
    elif sub == "scout":
        return run_scout(vault, quiet=quiet)
    elif sub == "resume":
        return run_resume(vault, quiet=quiet)
    elif sub == "finish":
        return run_finish(vault, quiet=quiet)
    elif sub == "prune-runs":
        return _prune_runs(vault, args)
    elif sub == "status":
        import json as _json

        summary = status(vault)
        # Issue #245: format is now an explicit choice, not an accident of
        # whether stdout happens to be a TTY — a redirected/piped run (every
        # cron/launchd invocation) used to silently get JSON with no way to
        # ask for the human-readable form, and vice versa.
        if bool(getattr(args, "json", False)):
            print(_json.dumps(summary, indent=2))
        else:
            print(_render_pipeline_status_text(summary))
        return 0
    else:
        print(f"error: unknown pipeline subcommand: {sub}", file=sys.stderr)
        return 2


def _regenerate_plan_only(args: argparse.Namespace) -> int:
    """Rewrite research plan + narrator header for the inferred next cycle only."""
    vault_dir: Path | None = args.vault_dir
    if vault_dir is None:
        vault_dir = args.output
    if vault_dir is None:
        print(
            "error: --regenerate-plan-only requires a vault directory "
            "(positional path or --output)",
            file=sys.stderr,
        )
        return 2
    vault_dir = vault_dir.expanduser().resolve()
    spec_path = vault_dir / "research.spec.md"
    if not spec_path.is_file():
        print(f"error: spec not found: {spec_path}", file=sys.stderr)
        return 2
    try:
        spec = load_spec(spec_path, location=vault_dir)
        validate(spec)
    except SpecValidationError as e:
        for msg in e.messages:
            print(msg, file=sys.stderr)
        return 2

    ct_path = vault_dir / "_pipeline" / "coverage-targets.json"
    cycle_number = 1
    if ct_path.is_file():
        try:
            data = json.loads(ct_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("root must be an object")
            last = data.get("cycle_number", 0)
            cycle_number = int(last) + 1
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as e:
            print(f"error: could not read cycle from {ct_path}: {e}", file=sys.stderr)
            return 2
    if cycle_number < 1:
        cycle_number = 1

    try:
        from ..pipeline.plan_narrator import prepend_narrative
        from ..pipeline.research_plan import generate_plan
    except ImportError:
        print("error: pipeline modules not available in this build", file=sys.stderr)
        return 2

    try:
        body = generate_plan(vault_dir, spec, cycle_number).to_markdown()
    except (
        FileNotFoundError,
        RuntimeError,
        OSError,
        SpecValidationError,
        ValueError,
    ) as e:
        print(str(e), file=sys.stderr)
        return 2

    out_live = vault_dir / "_pipeline" / "research-plan.md"
    out_archive = (
        vault_dir
        / "_pipeline"
        / "cycles"
        / f"cycle-{cycle_number:03d}-research-plan.md"
    )
    try:
        out_live.parent.mkdir(parents=True, exist_ok=True)
        out_archive.parent.mkdir(parents=True, exist_ok=True)
        out_live.write_text(body, encoding="utf-8")
        out_archive.write_text(body, encoding="utf-8")
    except OSError as e:
        print(str(e), file=sys.stderr)
        return 2

    try:
        prepend_narrative(vault_dir, cycle_number)
    except (OSError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 2
    return 0
