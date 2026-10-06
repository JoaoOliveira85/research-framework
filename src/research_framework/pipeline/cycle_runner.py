"""The cycle driver. Began as a translation of a bash `run_cycle.sh`
wrapper (spec 004); that wrapper was deleted in #298 and this is the only
implementation of the step sequence.

Runs one research cycle:
    pre-metrics → scout (BFS) → validate → research (DFS)
    → validate vault → post-metrics → validate research → topic harvest

Exit codes:
    0 — CONTINUE (proceed to next cycle)
    1 — TERMINATE (Condition A, B, or C satisfied)
    2 — ABORT (structural error; do not proceed)
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess  # noqa: F401 — tests patch cycle_runner.subprocess.{run,Popen}
import sys
from datetime import UTC, datetime
from pathlib import Path

from research_framework.observability import BridgeLogWriter, publish_bridge_writer
from research_framework.observability.cycle_log import cycle_log_handler

from . import atomic_write as _atomic_write
from . import cycle_state as _live_state
from ._helpers import cosmetic_correction as _cosmetic_correction
from ._helpers import quality_report_guard as _quality_report_guard_mod
from ._helpers import scout_correction as _scout_correction
from ._helpers import script_runner as _script_runner
from ._helpers import source_signals as _source_signals
from ._helpers import state as _state
from ._helpers.cycle_state import CycleRuntimeState
from .budget_guard import (
    CycleBudgetSession,
    resolve_dispatch_agent,
    resolve_max_tokens,
)
from .settings import SettingsError, load_vault_settings
from .skill_check import validate_and_repair_skills
from .steps import (
    CycleContext,
    research_result_from_disk,
    run_postprocess,
    run_research,
    run_scout,
    scout_result_from_disk,
)
from .steps._types import PostprocessResult, ResearchResult, ScoutResult
from .timings import CycleTimings

_LOG = logging.getLogger(__name__)

# Per-cycle timing recorders (flushed from quality_report_guard._write_cycle_quality_report).
_active_timings: dict[int, CycleTimings] = {}


def peek_active_timing(cycle_num: int) -> CycleTimings | None:
    """Return the active timings recorder for ``cycle_num``, if any."""
    return _active_timings.get(cycle_num)


def pop_active_timing(cycle_num: int) -> CycleTimings | None:
    """Remove and return the active timings recorder for ``cycle_num``."""
    return _active_timings.pop(cycle_num, None)


# --- Stage-level resume after a budget pause (budget-marker.contract.md §4.5) ---
#
# ``BUDGET_PAUSED`` names the dispatch stage that would have run next. Resume
# restarts the cycle at the PHASE that stage belongs to, so the phases that
# already dispatched are not dispatched (and paid for) a second time — which
# is what "continue cycle from ``paused_stage``" has meant on paper, and by
# nobody's code, since spec 033 shipped (issue #235).

#: The cycle's phases, in the order ``run_cycle_steps`` executes them. Resume
#: skips every phase strictly before its target.
_CYCLE_PHASES: tuple[str, ...] = (
    "source_extraction",
    "scout",
    "research",
    "postprocess",
)

#: Dispatch stage → the phase it runs inside. Only stages the in-process
#: budget guard can actually see are listed: it wraps ``agent_call.py``
#: invocations made by this process, which today is ``scout`` (including its
#: correction retries), ``note_writer`` and ``verifier`` (research step 3b).
#: An unlisted stage resumes the whole cycle — see ``arm_stage_resume``.
_STAGE_PHASE: dict[str, str] = {
    "scout": "scout",
    "note_writer": "research",
    "verifier": "research",
}

#: Cycle number → target phase, armed by the resume CLI and consumed ONCE.
#: Deliberately in-process rather than a file: a stale resume plan on disk
#: would silently skip phases of an unrelated later run, which loses work,
#: while a plan lost to a crash only costs a full re-run, which loses money.
#: Losing money loudly beats losing work quietly.
_pending_stage_resume: dict[int, str] = {}


def arm_stage_resume(cycle_num: int, paused_stage: str) -> str | None:
    """Arm a single-shot stage-level resume; return the phase, or ``None``.

    ``None`` means "run the whole cycle": the stage is one this build does not
    map to a phase, so the only safe reading is that nothing may be skipped.
    Failing that way costs a re-dispatch; failing the other way would drop
    work the cycle still owes.
    """
    phase = _STAGE_PHASE.get(paused_stage)
    if phase is None:
        _LOG.warning(
            "BUDGET_PAUSED named stage %r, which maps to no cycle phase — "
            "resuming the whole cycle rather than skipping blind.",
            paused_stage,
        )
        return None
    _pending_stage_resume[cycle_num] = phase
    return phase


def _consume_stage_resume(cycle_num: int) -> str | None:
    """Pop this cycle's armed phase (single-shot).

    Popping is what keeps a CG-001 retry honest:
    ``_incremental_retry_after_cg_fail`` calls the runner up to three times for
    one cycle, and a retry exists precisely because the cycle under-produced —
    the second attempt must be free to scout again.
    """
    return _pending_stage_resume.pop(cycle_num, None)


def _phase_is_due(target_phase: str | None, phase: str) -> bool:
    """True when ``phase`` still has to run under this resume plan."""
    if target_phase is None:
        return True
    return _CYCLE_PHASES.index(phase) >= _CYCLE_PHASES.index(target_phase)


# Last typed step results per cycle (spec 022 v2 harness retarget; cleared each cycle).
_last_cycle_results: dict[
    int, dict[str, ScoutResult | ResearchResult | PostprocessResult | None]
] = {}


def get_last_cycle_results(
    cycle_num: int,
) -> dict[str, ScoutResult | ResearchResult | PostprocessResult | None]:
    """Return typed scout/research/postprocess results from the latest ``run_cycle_steps``."""
    return dict(_last_cycle_results.get(cycle_num, {}))


def _stash_cycle_results(
    cycle_num: int,
    *,
    scout: ScoutResult | None = None,
    research: ResearchResult | None = None,
    postprocess: PostprocessResult | None = None,
) -> None:
    bucket = _last_cycle_results.setdefault(cycle_num, {})
    if scout is not None:
        bucket["scout"] = scout
    if research is not None:
        bucket["research"] = research
    if postprocess is not None:
        bucket["postprocess"] = postprocess


# Re-export helpers for backward compatibility (tests patch cycle_runner.subprocess).
MAX_SCOUT_VALIDATION_RETRIES = _scout_correction.MAX_SCOUT_VALIDATION_RETRIES
QualityReportState = _state.QualityReportState
_StepError = _script_runner._StepError
_archive_applied_directive = _scout_correction._archive_applied_directive
_apply_exit_metadata = _state._apply_exit_metadata
_correction_prompt_text = _scout_correction._correction_prompt_text
_cycle_quota_for_gates = _source_signals._cycle_quota_for_gates
_detect_cosmetic_only_correction = _cosmetic_correction._detect_cosmetic_only_correction
_discover_new_markdown_files = _state._discover_new_markdown_files
_effective_note_writer_batch_size = _source_signals._effective_note_writer_batch_size
_empty_batch_result_for_pace = _state._empty_batch_result_for_pace
_heartbeat_interval_s = _script_runner._heartbeat_interval_s
_heartbeat_writer = _script_runner._heartbeat_writer
_hms = _script_runner._hms
_load_spec_for_scout_gates = _source_signals._load_spec_for_scout_gates
_load_yaml_settings = _source_signals._load_yaml_settings
_max_batches_per_cycle = _source_signals._max_batches_per_cycle
_merge_research_notes = _state._merge_research_notes
_parse_priority_queue_from_plan_md = (
    _scout_correction._parse_priority_queue_from_plan_md
)
_pipeline_int_setting = _source_signals._pipeline_int_setting
_probe_retrieval_enabled = _source_signals._probe_retrieval_enabled
_quality_report_guard = _quality_report_guard_mod._quality_report_guard
_read_correction_directive_block = _scout_correction._read_correction_directive_block
_read_skipped_topics_from_research = _state._read_skipped_topics_from_research
_render_batch_note_writer_prompt = _scout_correction._render_batch_note_writer_prompt
_render_prompt = _scout_correction._render_prompt
_retry_scout_with_validation_directive = (
    _scout_correction._retry_scout_with_validation_directive
)
_run_probe_retrieval_and_cache = _source_signals._run_probe_retrieval_and_cache
_resolve_script = _script_runner._resolve_script
_run_script = _script_runner._run_script
_snapshot_note_bodies = _cosmetic_correction._snapshot_note_bodies
_split_note_frontmatter = _cosmetic_correction._split_note_frontmatter
_state_write = _state._state_write
_synthetic_mid_batch_empty_sg005 = _cosmetic_correction._synthetic_mid_batch_empty_sg005
_unfilled_categories_for_gates = _source_signals._unfilled_categories_for_gates
_vault_notes_content_sha1 = _state._vault_notes_content_sha1
_write_cycle_quality_report = _quality_report_guard_mod._write_cycle_quality_report
notify_required_source_degraded = _source_signals.notify_required_source_degraded


def _publish_live_state(
    vault_dir: Path,
    *,
    cycle_num: int,
    max_cycles: int,
    stage: str | None,
    timer: CycleTimings,
    budget_session: CycleBudgetSession | None,
) -> None:
    """Write extended ``state.json`` at each stage transition (spec 048 v1.1 D1)."""
    try:
        _live_state.write(
            vault_dir,
            in_progress_cycle=cycle_num,
            cycles_budgeted=max_cycles,
            stage=stage,
            cycle_started_at=timer.cycle_started_at,
            budget_snapshot=_live_state.budget_snapshot_from_session(
                budget_session,
                cycle_started_at=timer.cycle_started_at,
            ),
        )
    except Exception as exc:
        _LOG.warning("live state write failed: %s", exc)


def _stage_from_agent_argv(args: tuple[object, ...]) -> str | None:
    argv = [str(a) for a in args]
    if "--stage" in argv:
        idx = argv.index("--stage")
        if idx + 1 < len(argv):
            return argv[idx + 1]
    return None


def _argv_value(argv: list[str], flag: str) -> str | None:
    if flag in argv:
        idx = argv.index(flag)
        if idx + 1 < len(argv):
            return argv[idx + 1]
    return None


def _prompt_text_from_argv(vault_dir: Path, args: tuple[object, ...]) -> str:
    path_str = _argv_value([str(a) for a in args], "--prompt-file")
    if not path_str:
        return ""
    path = Path(path_str)
    if not path.is_absolute():
        path = vault_dir / path
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _resolved_budget(
    vault_dir: Path, budget_cap: float | None, max_cycles: int | None
) -> tuple[float, int]:
    """Backfill omitted budget arguments from the spec-061 ladder (issue #233)."""
    from ..cli._budget_resolve import fill_missing_run_budget

    return fill_missing_run_budget(vault_dir, budget_cap, max_cycles)


def _resolve_dispatch_agent(session: CycleBudgetSession, stage: str) -> str:
    """Session-shaped view of :func:`budget_guard.resolve_dispatch_agent`.

    The precedence itself moved to ``budget_guard`` so the cost preflight
    (issue #238) can ask the same question with no live session; this wrapper
    keeps the dispatch hook's call site reading as it did.
    """
    return resolve_dispatch_agent(session.vault_settings, stage)


def _resolve_max_tokens(session: CycleBudgetSession, stage: str) -> int:
    return resolve_max_tokens(session.vault_settings, stage)


_BATCH_SIDECAR_STEM_RE = re.compile(r"^(?P<stage>.+)(?P<batch>-batch-\d+)$")


def _unwritten_sidecar_path(requested: Path) -> Path:
    """``requested``, or its first sibling that no dispatch has written yet.

    The cycle steps name the cost sidecar themselves (``scout.json``,
    ``note_writer-batch-N.json``) and ``agent_call.py`` replaces whatever is
    at the path it is given. So every re-dispatch in a cycle — the validator
    and SG-003 scout retries, each CG-001 attempt, a resumed cycle — named
    the file the dispatch before it had written, and only the last one's cost
    was left for the per-cycle and lifetime caps to count.

    Spec 028 FR-005 / FR-012: ``{stage}.json``, then ``{stage}-2.json``, … —
    the shape ``agent_call.py`` allocates when it picks the path itself. The
    number goes on the stage, so a batch sidecar still ends in
    ``-batch-N.json`` and its batch index is still read off the name.
    """
    if not requested.exists():
        return requested
    match = _BATCH_SIDECAR_STEM_RE.match(requested.stem)
    stage, batch = (match["stage"], match["batch"]) if match else (requested.stem, "")
    attempt = 2
    while True:
        candidate = requested.with_name(f"{stage}-{attempt}{batch}{requested.suffix}")
        if not candidate.exists():
            return candidate
        attempt += 1


def _with_unwritten_cost_sidecar(args: tuple[object, ...]) -> tuple[object, ...]:
    """``args`` with ``--cost-sidecar`` pointed at a path nothing has written."""
    argv = list(args)
    for i, arg in enumerate(argv[:-1]):
        if str(arg) == "--cost-sidecar":
            argv[i + 1] = _unwritten_sidecar_path(Path(str(argv[i + 1])))
            break
    return tuple(argv)


def _install_budget_run_script_guard(session: CycleBudgetSession | None) -> None:
    """Wrap ``script_runner._run_script`` for agent_call budget hooks (spec 033)."""
    if getattr(_script_runner, "_run_script_orig", None) is None:
        _script_runner._run_script_orig = _script_runner._run_script  # type: ignore[attr-defined]
    original = _script_runner._run_script_orig  # type: ignore[attr-defined]
    _script_runner._budget_session = session  # type: ignore[attr-defined]

    def guarded(
        python_bin: str, script_path: Path | str, *args: object, **kwargs: object
    ) -> int:
        name = Path(script_path).name
        active = getattr(_script_runner, "_budget_session", None)
        if name == "agent_call.py":
            args = _with_unwritten_cost_sidecar(args)
        if name == "agent_call.py" and active is not None:
            stage = _stage_from_agent_argv(args) or "unknown"
            active.before_agent_call(
                stage=stage,
                prompt_text=_prompt_text_from_argv(active.vault_dir, args),
                agent=_resolve_dispatch_agent(active, stage),
                tier=active.vault_settings.stage(stage).tier,
                max_tokens=_resolve_max_tokens(active, stage),
            )
        rc = original(python_bin, script_path, *args, **kwargs)
        if name == "agent_call.py" and active is not None:
            active.after_agent_call()
        return int(rc)

    _script_runner._run_script = guarded  # type: ignore[method-assign]


def _run_source_extraction_if_enabled(
    python_bin: str,
    vault_dir: Path,
    cycle_num: int,
    *,
    settings: dict,
    env: dict[str, str],
) -> int:
    """FR-001 Step 1.5: subprocess ``scripts/source_bridge.py`` before scout."""
    stages = settings.get("stages") if isinstance(settings.get("stages"), dict) else {}
    extraction = stages.get("source_extraction") if isinstance(stages, dict) else {}
    if not isinstance(extraction, dict) or not extraction.get("enabled"):
        return 0
    # Prefer the per-vault copy (always present after `generate` ships
    # scripts/source_bridge.py into <vault>/scripts/). Fall back to the
    # repo-root layout for development (`__file__` parents[3] = repo root).
    # Without the vault-dir-first lookup, installed mode resolves
    # parents[3] = ``.venv/lib/python3.12/`` and the script is "missing".
    bridge_script = vault_dir / "scripts" / "source_bridge.py"
    if not bridge_script.is_file():
        repo_root = Path(__file__).resolve().parents[3]
        bridge_script = repo_root / "scripts" / "source_bridge.py"
    if not bridge_script.is_file():
        _LOG.error(f"ERROR: source_bridge.py missing at {bridge_script}")
        return 2
    try:
        rc = _run_script(
            python_bin,
            bridge_script,
            "--vault",
            vault_dir,
            "--cycle",
            str(cycle_num),
            env=env,
        )
    except _StepError:
        return 2
    return int(rc)


def run_cycle_steps(
    vault_dir: Path,
    cycle_num: int,
    budget_cap: float | None = None,
    max_cycles: int | None = None,
    scripts_dir: Path | None = None,
) -> int:
    """Execute one full research cycle and return the exit code.

    Same step sequence, same exit-code semantics, no bash dependency.

    ``budget_cap`` / ``max_cycles`` used to default to ``10.0`` / ``5`` —
    numbers that appeared in no settings file, no spec and no flag, and that
    silently became the run's budget for any caller that omitted them (issue
    #233). ``None`` now means "ask the spec-061 ladder", which is the one
    answer every other entry point already gets.
    """
    budget_cap, max_cycles = _resolved_budget(vault_dir, budget_cap, max_cycles)
    runtime_state = CycleRuntimeState()
    _last_cycle_results.pop(cycle_num, None)
    # budget-marker.contract.md §4.5: a resume past a pause starts at the
    # paused stage's phase. Consumed here (once) so a CG-001 retry of the same
    # cycle runs it whole.
    resume_phase = _consume_stage_resume(cycle_num)

    # --- Setup ---
    if scripts_dir is None:
        scripts_dir = vault_dir / "scripts"

    pipeline_dir = vault_dir / "_pipeline"
    cycles_dir = pipeline_dir / "cycles"
    prompts_dir = pipeline_dir / "prompts"
    cycle_3 = f"{cycle_num:03d}"

    pre_metrics = cycles_dir / f"cycle-{cycle_3}-pre-metrics.json"

    cycles_dir.mkdir(parents=True, exist_ok=True)

    timer = CycleTimings(cycle_num=cycle_num, pipeline_dir=pipeline_dir)
    _active_timings[cycle_num] = timer
    _publish_live_state(
        vault_dir,
        cycle_num=cycle_num,
        max_cycles=max_cycles,
        stage=None,
        timer=timer,
        budget_session=None,
    )

    python_bin = sys.executable
    env: dict[str, str] = os.environ.copy()
    env["RV_PYTHON"] = python_bin

    _LOG.info("=" * 60)
    _LOG.info(f"RESEARCH CYCLE {cycle_num}/{max_cycles}")
    _LOG.info(f"Budget cap: ${budget_cap}")
    _LOG.info(f"Vault: {vault_dir}")
    _LOG.info(f"Started: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    _LOG.info("=" * 60)

    cycle_dir = cycles_dir / f"cycle-{cycle_3}"
    cycle_dir.mkdir(parents=True, exist_ok=True)

    # Spec 048 (Tier-6): open a per-cycle bridge.log alongside the existing
    # quality-report guard. The stacked context managers:
    #   1. quality-report guard (writes report-NNN.md on exit)
    #   2. BridgeLogWriter (opens the file, closes on exit)
    #   3. publish_bridge_writer (pushes writer onto the ContextVar AND
    #      resets the token on exit, so the next ``run_cycle_steps`` call
    #      in the same process does NOT see a stale closed writer)
    #   4. cycle_log_handler (v1.1 Tier-5 per-cycle logger file)
    with (
        _quality_report_guard(cycle_dir) as report_state,
        BridgeLogWriter(cycle_dir / "bridge.log") as bridge_writer,
        publish_bridge_writer(bridge_writer),
        cycle_log_handler(vault_dir, cycle_num),
    ):
        report_state.vault_dir = vault_dir
        report_state.cycle_num = cycle_num

        # --- Step -1: skill-file preflight ---
        # External agent CLIs (Cursor, Codex, Superpowers plugin) have rewritten
        # .agents/skills/*/SKILL.md frontmatter in earlier bundles, silently
        # disabling the corresponding skills mid-cycle. Restore from the wheel's
        # bundled copies when possible; refuse to start a cycle if any skill is
        # unrecoverable — running with a half-loaded skill registry is exactly
        # how v0.2.19 produced the "verifier never ran" failure mode.
        timer.lap("Preflight - validating .agents/skills/*/SKILL.md")
        _publish_live_state(
            vault_dir,
            cycle_num=cycle_num,
            max_cycles=max_cycles,
            stage="preflight",
            timer=timer,
            budget_session=None,
        )
        skill_result = validate_and_repair_skills(vault_dir)
        sidecar = pipeline_dir / f"cycle-{cycle_3}-skill-check.json"
        _atomic_write.write_text(
            sidecar,
            json.dumps(skill_result.to_dict(), indent=2, ensure_ascii=False) + "\n",
        )
        if skill_result.repaired:
            _LOG.info(
                f"  WARNING: auto-restored {len(skill_result.repaired)} SKILL.md "
                f"file(s) from the bundled copies — an external tool is likely "
                f"rewriting them. See {sidecar} for details."
            )
        if not skill_result.ok:
            _LOG.error("ERROR: one or more SKILL.md files are unrecoverable:")
            for issue in skill_result.unrecoverable:
                _LOG.info(f"  - {issue.path}: {issue.error}")
            _LOG.info(
                "Fix the listed files (or restore them from the source bundle) "
                "before retrying the cycle."
            )
            report_state.exit_status = "failure"
            report_state.exit_code = 2
            return 2
        _LOG.info(f"  OK ({skill_result.scanned} skill file(s) parsed cleanly)")

        # --- Step 0: pre-cycle metrics ---
        timer.lap("Step 0 - capturing pre-cycle vault metrics")
        try:
            rc0 = _run_script(
                python_bin,
                scripts_dir / "vault_metrics.py",
                vault_dir,
                "--output",
                pipeline_dir / "vault-metrics.json",
                env=env,
            )
        except _StepError:
            report_state.exit_status = "failure"
            report_state.exit_code = 2
            return 2
        if rc0 != 0:
            _LOG.error(
                "vault_metrics.py exited %s at Step 0 — cannot copy metrics.",
                rc0,
            )
            report_state.exit_status = "failure"
            report_state.exit_code = 2
            return 2
        from .atomic_write import write_json as _write_json

        _write_json(
            pre_metrics,
            json.loads(
                (pipeline_dir / "vault-metrics.json").read_text(encoding="utf-8")
            ),
        )
        settings_path = vault_dir / "settings.yaml"
        settings = _load_yaml_settings(settings_path) if settings_path.is_file() else {}

        budget_session: CycleBudgetSession | None = None
        try:
            vault_settings = load_vault_settings(vault_dir)
            budget_session = CycleBudgetSession(vault_dir, cycle_num, vault_settings)
        except SettingsError as exc:
            _script_runner._budget_session = None  # type: ignore[attr-defined]
            # Fail closed. With no budget session nothing enforces
            # ``limits`` (dollar, token and wall-clock caps) or
            # ``approval_gates``, so a file that carries either — or that
            # cannot be read as a mapping at all (``key`` is None: nobody can
            # say what it carries) — must stop the cycle, not uncap it on the
            # strength of a typo in an unrelated key. A file that configures
            # neither loses nothing and runs as it always has.
            unreadable = exc.key is None
            if settings_path.is_file() and (
                unreadable
                or not isinstance(settings, dict)
                or settings.get("limits")
                or settings.get("approval_gates")
            ):
                _LOG.error(
                    "ERROR: %s is not loadable (%s) — refusing to run cycle %d "
                    "without the budget caps and approval gates it configures. "
                    "Fix the file and re-run.",
                    settings_path,
                    exc,
                    cycle_num,
                )
                report_state.exit_status = "failure"
                report_state.exit_code = 2
                return 2
        _install_budget_run_script_guard(budget_session)

        ctx = CycleContext(
            vault_dir=vault_dir,
            cycle_num=cycle_num,
            cycle_dir=cycle_dir,
            settings=settings,
            scripts_dir=scripts_dir,
            pipeline_dir=pipeline_dir,
            cycles_dir=cycles_dir,
            prompts_dir=prompts_dir,
            python_bin=python_bin,
            env=env,
            max_cycles=max_cycles,
            budget_cap=budget_cap,
            runtime_state=runtime_state,
        )

        if resume_phase is not None:
            _LOG.info(
                "Resuming cycle %d at the %r phase — the phases before it "
                "already dispatched in this cycle and are not re-run.",
                cycle_num,
                resume_phase,
            )

        if _phase_is_due(resume_phase, "source_extraction"):
            extraction_rc = _run_source_extraction_if_enabled(
                python_bin,
                vault_dir,
                cycle_num,
                settings=settings,
                env=env,
            )
            if extraction_rc != 0:
                report_state.exit_status = "failure"
                report_state.exit_code = 2
                return 2

        # Issue #269: without this lap a cycle a step gate aborted flushes
        # timings that stop at "Step 0", which is indistinguishable from a
        # crash before the scout ever ran.
        timer.lap("Step 1/2 - scout (topic discovery + step gates)")
        _publish_live_state(
            vault_dir,
            cycle_num=cycle_num,
            max_cycles=max_cycles,
            stage="scout",
            timer=timer,
            budget_session=budget_session,
        )
        if _phase_is_due(resume_phase, "scout"):
            scout_result = run_scout(ctx)
        else:
            scout_result = scout_result_from_disk(ctx)
        _stash_cycle_results(cycle_num, scout=scout_result)
        if scout_result.exit_code == 2:
            report_state.exit_status = "failure"
            report_state.exit_code = 2
            return 2
        if scout_result.exit_code == 1:
            report_state.exit_code = 1
            return 1

        timer.lap("Step 3 - research (DFS)")
        _publish_live_state(
            vault_dir,
            cycle_num=cycle_num,
            max_cycles=max_cycles,
            stage="research",
            timer=timer,
            budget_session=budget_session,
        )
        if _phase_is_due(resume_phase, "research"):
            research_result = run_research(ctx, scout_result)
        else:
            research_result = research_result_from_disk(ctx)
        _stash_cycle_results(cycle_num, research=research_result)
        if research_result.exit_code == 2:
            # The research step aborted. Postprocess only asks whether
            # ``cycle-NNN-research.json`` exists, and an earlier attempt at
            # this cycle (a CG-001 retry, a resumed run) leaves one behind.
            report_state.exit_status = "failure"
            report_state.exit_code = 2
            return 2

        timer.lap("Step 4+ - postprocess (validation, metrics, harvest)")
        _publish_live_state(
            vault_dir,
            cycle_num=cycle_num,
            max_cycles=max_cycles,
            stage="postprocess",
            timer=timer,
            budget_session=budget_session,
        )
        post_result = run_postprocess(ctx, research_result)
        _stash_cycle_results(cycle_num, postprocess=post_result)
        research_exit = post_result.exit_code

        _LOG.info("\n" + "=" * 60)
        _LOG.info(f"CYCLE {cycle_num} COMPLETE")
        _LOG.info(f"Finished: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}")
        _LOG.info("=" * 60)

        if budget_session is not None:
            from .reporter import append_cycle_cost_report

            append_cycle_cost_report(
                vault_dir,
                cycle_num,
                tally=budget_session.tally,
                limits=budget_session.limits,
            )

        try:
            from .reports.deliver import deliver_cycle_reports

            deliver_cycle_reports(vault_dir, cycle_num)
        except Exception as exc:
            _LOG.warning("cycle report delivery failed: %s", exc)

        report_state.exit_code = research_exit
        return research_exit
