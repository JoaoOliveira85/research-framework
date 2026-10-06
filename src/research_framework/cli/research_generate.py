from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .._assets import (
    default_settings_path,
    load_output_dir_from_settings,
    settings_profile_path,
)
from ..generator.scaffold import scaffold
from ..generator.scripts import copy_scripts
from ..generator.templates import render_all
from ..spec.schema import SpecValidationError
from ..spec.simple import load as load_spec
from ..spec.validator import validate
from ._budget_resolve import BudgetError, resolve_cycle_budget_from_path
from ._common import _run_phase1_gate
from .research_cycles import _regenerate_plan_only
from .research_phase3 import _prepopulate_pipeline, _run_phase3
from .research_resume import _resume


def _estimate_only_for_generate(args: argparse.Namespace) -> int:
    """`generate --estimate-only`: price the next cycle, dispatch nothing (#238).

    The cycle it prices is the one this invocation would run next — the same
    number ``--resume`` would resolve — so the estimate belongs to the run the
    operator is actually about to start, not to cycle 1 of a hypothetical one.
    """
    from ..pipeline.orchestrator import is_archived
    from .research_cycles import _estimate_only
    from .research_resume import _resolve_resume_cycle, _resume_vault_dir

    vault_dir = _resume_vault_dir(args)
    if not vault_dir.is_dir():
        print(f"error: vault not found: {vault_dir}", file=sys.stderr)
        return 2
    # Spec 071, same single rule called earlier: an archived vault will never
    # run another cycle, so pricing one and reporting it "safe to leave
    # unattended" would answer a question the operator cannot act on.
    if is_archived(vault_dir):
        print(
            f"error: {vault_dir} is archived — no research cycle may run "
            "against it, so there is no next cycle to price.\n"
            f"Set `archived: false` in {vault_dir / 'settings.yaml'} to resume "
            "research.",
            file=sys.stderr,
        )
        return 2
    cycle = args.cycle if getattr(args, "cycle", None) else _resolve_resume_cycle(args)
    return _estimate_only(vault_dir, cycle)


def _cmd_generate(args: argparse.Namespace) -> int:
    if args.regenerate_plan_only:
        return _regenerate_plan_only(args)

    # Issue #286: --approve/--approve-all/--reject/--force-budget only mean
    # anything on a resume (spec 033's approval gates and budget pauses are
    # markers written mid-run; a fresh generate has no run yet to approve,
    # reject or force past). They used to be silently accepted no-ops outside
    # --resume. Refuse loudly instead, same as every other refusal in this
    # file (spec 070 FR6).
    if not getattr(args, "resume", False):
        _resume_only_flags = [
            flag
            for flag, value in (
                ("--approve", getattr(args, "approve", None)),
                ("--approve-all", getattr(args, "approve_all", False)),
                ("--reject", getattr(args, "reject", None)),
                ("--force-budget", getattr(args, "force_budget", False)),
            )
            if value
        ]
        if _resume_only_flags:
            print(
                "error: "
                + ", ".join(_resume_only_flags)
                + " only take effect with --resume (spec 033 approval gates "
                "and budget pauses exist only mid-run); pass --resume or "
                "drop the flag.",
                file=sys.stderr,
            )
            return 2

    # Issue #238: the preflight answers a question about an EXISTING vault
    # (what will its next cycle cost, and is anything configured to stop it),
    # so it runs before the flags that only a real generate needs — notably
    # `--spec`, which a preflight has no use for.
    if getattr(args, "estimate_only", False):
        return _estimate_only_for_generate(args)

    if getattr(args, "legacy_cycle_runner", False):
        print(
            "DEPRECATION WARNING: --legacy-cycle-runner restores pre-017 "
            "single-invocation note-writer behaviour; this path will be removed "
            "in 0.3.0",
            file=sys.stderr,
        )

    if args.spec is None:
        print(
            "error: --spec is required (omit only with --regenerate-plan-only)",
            file=sys.stderr,
        )
        return 2

    if args.dry_run and args.resume:
        print("error: --dry-run and --resume are mutually exclusive", file=sys.stderr)
        return 2

    # The reverse of issue #286: these three shape Phase 1 (the settings baked
    # into the vault, the files copied into its `_pipeline/`, the pytest gate),
    # which --resume skips. They used to be silently ignored there.
    if args.resume:
        _fresh_only_flags = [
            flag
            for flag, value in (
                ("--settings", args.settings),
                ("--prepopulate", args.prepopulate),
                ("--skip-gate", args.skip_gate),
            )
            if value
        ]
        if _fresh_only_flags:
            print(
                "error: "
                + ", ".join(_fresh_only_flags)
                + " only take effect on a fresh generate (they shape Phase 1, "
                "which --resume skips); drop the flag or drop --resume.",
                file=sys.stderr,
            )
            return 2

    # Spec 071: refuse an archived vault here as well as in the orchestrator.
    # The orchestrator guard is the invariant (it covers every caller); this one
    # exists so the operator always reads "archived" rather than whichever
    # unrelated config error happens to be hit first — an archived vault is
    # precisely the one whose spec and settings nobody has kept current.
    # Same single rule, called earlier.
    from ..pipeline.orchestrator import is_archived

    _target = args.output or getattr(args, "vault_dir", None)
    if _target is not None and is_archived(Path(_target)):
        print(
            f"error: {_target} is archived — no research cycle may write to it.\n"
            "It stays fully queryable (`./vault ask`, `status`, `digest`, "
            "`re-grade`) and still takes framework upgrades (`./vault update`).\n"
            f"To resume research, set `archived: false` in {_target}/settings.yaml.",
            file=sys.stderr,
        )
        return 2

    # --resume skips Phase 0/1; handled below by invoking pipeline modules.
    if args.resume:
        return _resume(args)

    # Resolve which `settings.yaml` we're going to bake into the vault
    # BEFORE loading the spec, because a settings file is now allowed to
    # carry an `output_dir` that backstops `--output` when the user
    # didn't pass one.
    settings_src: Path | None = None
    if args.settings:
        try:
            settings_src = settings_profile_path(args.settings)
        except FileNotFoundError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(f"[phase 1] settings profile: {settings_src}")
    else:
        # No `--settings` flag: fall through to the bundled default so we
        # can still honour `output_dir` in the stock profile and so the
        # vault carries a current settings.yaml.
        try:
            settings_src = default_settings_path()
        except FileNotFoundError:
            settings_src = None

    # Resolution order for the vault destination:
    #   1. `--output <dir>` on the CLI (explicit user intent)
    #   2. `output_dir:` inside the settings file we're baking in
    #      (zero-arg generate.sh lives off this)
    #   3. the spec file's own `location` (detailed specs) or the
    #      auto-derived `<spec-parent>/<spec.name>` (simple specs).
    output_from_settings: Path | None = None
    if settings_src is not None and args.output is None:
        output_from_settings = load_output_dir_from_settings(settings_src)

    # Phase 0: load + validate spec. `load_spec` auto-detects whether the
    # file is a simple `research.spec.md` (expanded via simple.expand) or a
    # detailed `vault-spec.md`, so users can pick whichever surface fits.
    effective_location = args.output or output_from_settings
    try:
        spec = load_spec(args.spec, location=effective_location)
    except SpecValidationError as e:
        for msg in e.messages:
            print(msg, file=sys.stderr)
        return 2

    # Now that the spec is loaded we can pin the final vault dir. `args.output`
    # is still the last-word override; `output_from_settings` beats the spec
    # default; spec location is the floor.
    vault_dir = args.output or output_from_settings or spec.location

    # Validate with the vault context so spec 069 FR1 declared-source backing
    # runs (every source must trigger-match a module or be a strategy_hint).
    try:
        validate(spec, vault_dir=vault_dir)
    except SpecValidationError as e:
        for msg in e.messages:
            print(msg, file=sys.stderr)
        return 2
    if output_from_settings is not None and args.output is None:
        print(f"[phase 0] output_dir from settings: {vault_dir}")

    print(f"[phase 0] spec validated: {spec.name}")
    print(f"[phase 1] generating vault at {vault_dir}")

    # Phase 1: scaffold + templates + scripts. `spec_source` is threaded in
    # so the vault copies its own `research.spec.md` for later --resume runs.
    # `--settings` lets the user pick a runtime profile (any settings.yaml);
    # when omitted we already resolved the bundled default above.
    scaffold(spec, vault_dir, spec_source=args.spec, settings_source=settings_src)
    render_all(spec, vault_dir)
    copy_scripts(vault_dir)

    # Feature 002 — carry-forward files from an archived vault's _pipeline/.
    # FR-023: copy post-mortem / lessons-learned / budget-log verbatim so
    # institutional memory survives a clean rebuild.
    if args.prepopulate:
        _prepopulate_pipeline(vault_dir, args.prepopulate)

    print("[phase 1] infrastructure written")

    # Phase 1 gate: pytest must pass (dev-only; auto-skips when running
    # from an installed wheel — see `_run_phase1_gate` for why).
    if not args.skip_gate:
        gate = _run_phase1_gate(vault_dir)
        if gate is None:
            pass  # gate self-reported as skipped; don't double-log "passed"
        elif gate != 0:
            print(
                "[phase 1 gate] FAILED — pytest did not pass. Fix scripts before "
                "Phase 2.",
                file=sys.stderr,
            )
            return 2
        else:
            print("[phase 1 gate] passed")

    if args.dry_run:
        print("[dry-run] stopping after Phase 1")
        return 0

    if getattr(args, "legacy_cycle_runner", False):
        raise NotImplementedError(
            "--legacy-cycle-runner not available; pre-017 path was removed."
        )

    # Phase 2/3 — delegated to pipeline modules (implemented in Phase 6)
    try:
        from ..pipeline.orchestrator import run_cycles
    except ImportError:
        print("Phase 2/3 modules not available in this build.")
        return 0

    # Spec 061: resolve the per-cycle budget ONCE, from the baked vault
    # settings.yaml + the (last-word) CLI flags. Replaces the old silent
    # `cycles.initial_max` spec mutation; the resolver emits a loud WARNING
    # for any deprecated/overridden key (FR4) and never truncates silently.
    try:
        budget = resolve_cycle_budget_from_path(
            vault_dir / "settings.yaml",
            flag_max_cycles=getattr(args, "max_cycles", None),
            flag_max_usd=getattr(args, "max_usd", None),
            flag_more_cycles=getattr(args, "more_cycles", None),
            flag_max_usd_this_run=getattr(args, "max_usd_this_run", None),
            start_cycle=1,
        )
    except BudgetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    rc = run_cycles(spec, vault_dir, budget=budget)
    if rc != 0:
        return rc

    return _run_phase3(spec, vault_dir)
