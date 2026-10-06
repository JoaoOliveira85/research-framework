"""Scout step (spec 025 US6 B3)."""

from __future__ import annotations

import dataclasses
import json
import logging
import time
from pathlib import Path

from .. import atomic_write
from .._helpers import scout_correction as sc
from .._helpers import script_runner as sr
from .._helpers import source_signals as ss
from ..gates import GateResult, run_gate
from ..gates_step import (
    SG001_topics_new_nonempty,
    SG002_topic_category_diversity,
    SG003_topic_abstraction_check,
)
from ..step_gate_log import read_step_gates, record_step_gates
from ._types import CycleContext, SafetyGateTrip, ScoutedTopic, ScoutResult

_LOG = logging.getLogger(__name__)

_TRIPPED_STATUSES = frozenset({"FAIL", "WARN"})


def _evaluate_step_gate(
    cycles_dir: Path,
    cycle_num: int,
    gate_fn,
    *args,
    label: str = "",
    **kwargs,
) -> GateResult:
    """Run one scout step gate, log its verdict, and persist it (issue #269).

    Persisting at evaluation time is what makes the record survive the abort a
    FAIL triggers: the caller returns straight out of the cycle, and the
    quality report needs to say which gate stopped it.
    """
    result = run_gate(gate_fn, *args, **kwargs)
    _LOG.info(f"[gates] {result.gate_id}{label}: {result.status} — {result.message}")
    record_step_gates(cycles_dir, cycle_num, [result])
    return result


def _step_gate_trips(cycles_dir: Path, cycle_num: int) -> list[SafetyGateTrip]:
    """Recorded SG-001..003 verdicts that tripped (FAIL or WARN), in gate order."""
    return [
        SafetyGateTrip(gate_id=gate.gate_id, status=gate.status, message=gate.message)
        for gate in read_step_gates(cycles_dir, cycle_num)
        if str(gate.status or "").upper() in _TRIPPED_STATUSES
    ]


def _source_extraction_enabled(settings: dict | None) -> bool:
    if not settings:
        return False
    stages = settings.get("stages")
    if not isinstance(stages, dict):
        return False
    extraction = stages.get("source_extraction")
    if not isinstance(extraction, dict):
        return False
    return bool(extraction.get("enabled"))


def _inject_source_signals_into_prompt(
    vault_dir: Path,
    cycle_num: int,
    prompt_path: Path,
    settings: dict | None,
) -> None:
    """FR-008: inject cached signal payloads; scout must not re-walk sources."""
    if not _source_extraction_enabled(settings):
        return
    cycle_3 = f"{cycle_num:03d}"
    sidecar = (
        vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle_3}" / "source-signals.json"
    )
    if not sidecar.is_file():
        return
    try:
        blob = json.loads(sidecar.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    text = prompt_path.read_text(encoding="utf-8")
    text += (
        "\n\n## Cached source signals (source-extraction stage)\n\n"
        f"```json\n{json.dumps(blob, indent=2)}\n```\n"
    )
    prompt_path.write_text(text, encoding="utf-8")


def _tag_topics_by_signal_module(
    scout_body: dict, vault_dir: Path, cycle_num: int
) -> None:
    """FR-009: annotate proposed topics with signal ``module`` field."""
    cycle_3 = f"{cycle_num:03d}"
    sidecar = (
        vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle_3}" / "source-signals.json"
    )
    if not sidecar.is_file():
        return
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    signals = data.get("signals") if isinstance(data, dict) else None
    if not isinstance(signals, list) or not signals:
        return
    default_module = str(signals[0].get("module", "generic"))
    topics = scout_body.get("topics_found")
    if not isinstance(topics, dict):
        return
    new_topics = topics.get("new")
    if not isinstance(new_topics, list):
        return
    for item in new_topics:
        if isinstance(item, dict) and "module" not in item:
            item["module"] = default_module


def _phase(ctx: CycleContext) -> int:
    __exit = 0
    vault_dir = ctx.vault_dir
    cycle_num = ctx.cycle_num
    cycle_3 = f"{cycle_num:03d}"
    scripts_dir = ctx.scripts_dir
    cycles_dir = ctx.cycles_dir
    prompts_dir = ctx.prompts_dir
    pipeline_dir = ctx.pipeline_dir or (vault_dir / "_pipeline")
    python_bin = ctx.python_bin
    env = dict(ctx.env)
    max_cycles = ctx.max_cycles
    budget_cap = ctx.budget_cap
    scout_report = cycles_dir / f"cycle-{cycle_3}-scout.json"
    cycles_dir / f"cycle-{cycle_3}-research.json"
    cycles_dir / f"cycle-{cycle_3}-pre-metrics.json"
    post_metrics = cycles_dir / f"cycle-{cycle_3}-post-metrics.json"
    assert scripts_dir is not None and cycles_dir is not None
    assert prompts_dir is not None and python_bin

    # --- Step 1: scout (BFS) ---

    scout_prompt_src = prompts_dir / "scout-prompt.md"
    if not scout_prompt_src.exists():
        _LOG.error(f"ERROR: scout prompt missing at {scout_prompt_src}")
        _LOG.info(
            "Re-run 'research-framework generate' to re-render prompts from the spec."
        )
        return 2
    # Render scout prompt (replace placeholders)
    scout_prompt_rendered = cycles_dir / f"cycle-{cycle_3}-scout-prompt.rendered.md"
    sc._render_prompt(
        scout_prompt_src,
        scout_prompt_rendered,
        {"{CYCLE_NUM}": str(cycle_num), "{SCOUT_REPORT}": str(scout_report)},
        vault_dir=vault_dir,
        cycle_num=cycle_num,
    )
    _inject_source_signals_into_prompt(
        vault_dir, cycle_num, scout_prompt_rendered, ctx.settings
    )

    try:
        sr._run_script(
            python_bin,
            scripts_dir / "agent_call.py",
            "--vault",
            vault_dir,
            "--stage",
            "scout",
            "--prompt-file",
            scout_prompt_rendered,
            "--cost-sidecar",
            cycles_dir / f"cycle-{cycle_3}" / "agent-calls" / "scout.json",
            env=env,
            log_file=cycles_dir / f"cycle-{cycle_3}-scout.log",
        )
    except sr._StepError:
        return 2
    # --- Step 2: validate scout ---

    if not scout_report.exists():
        _LOG.error(f"ERROR: scout report not written at {scout_report}")
        _LOG.info("The agent may have ignored the output-path instruction.")
        return 2
    try:
        scout_exit = sr._run_script(
            python_bin,
            scripts_dir / "validate_cycle.py",
            scout_report,
            "--vault",
            vault_dir,
            "--max-cycles",
            max_cycles,
            "--budget-cap",
            budget_cap,
            env=env,
        )
    except sr._StepError:
        return 2
    if scout_exit == 2:
        # spec-019 / 0.2.29: scout structural errors used to abort the cycle
        # outright. Most of them (missing required source name in
        # ``sources_consulted``, off-repo ``source_file`` path, wrong
        # ``dimensions_covered`` set, orphan intent rows) are *recoverable* —
        # the scout already did the expensive code-walking work, it just
        # missed a piece of the summary contract. Instead of nuking the
        # cycle, drive the same correction loop SG-003 uses below: feed
        # the validator's errors back to the scout as a directive,
        # re-render the prompt, re-run, re-validate. Cap at
        # ``h.MAX_SCOUT_VALIDATION_RETRIES`` attempts (1 retry by default —
        # 1 initial + 1 follow-up). Only then abort.
        scout_exit = sc._retry_scout_with_validation_directive(
            python_bin=python_bin,
            scripts_dir=scripts_dir,
            vault_dir=vault_dir,
            cycles_dir=cycles_dir,
            cycle_num=cycle_num,
            cycle_3=cycle_3,
            scout_report=scout_report,
            scout_prompt_src=scout_prompt_src,
            scout_prompt_rendered=scout_prompt_rendered,
            max_cycles=max_cycles,
            budget_cap=budget_cap,
            env=env,
        )
        if scout_exit == 2:
            _LOG.info(
                "ABORT: scout report still has structural errors after the "
                "validator-directive correction loop. See "
                f"{scout_report.name}.validation.json for the residual errors."
            )
            return 2
    if scout_exit == 1:
        _LOG.info("TERMINATE after scout — no DFS this cycle.")
        # Still capture post-metrics so the cycle directory is complete (best-effort)
        try:
            sr._run_script(
                python_bin,
                scripts_dir / "vault_metrics.py",
                vault_dir,
                "--output",
                post_metrics,
                env=env,
            )
        except sr._StepError:
            pass
        return 1
    # --- Step 2b: FR-009 module tags from cached source signals ---
    if scout_exit == 0:
        try:
            scout_body = json.loads(scout_report.read_text(encoding="utf-8"))
        except Exception as exc:
            _LOG.warning(
                f"[scout] WARN: could not load scout JSON for module tags: {exc}"
            )
        else:
            _tag_topics_by_signal_module(scout_body, vault_dir, cycle_num)
            # Atomic (temp file + os.replace): this rewrite races the
            # concurrent-reader e2e test and any other consumer polling
            # cycle-NNN-scout.json — a plain write_text() truncates the file
            # in place and is briefly visible as empty (issue #312).
            atomic_write.write_text(
                scout_report,
                json.dumps(scout_body, indent=2, ensure_ascii=False) + "\n",
            )
    # --- Step 2c: scout quality gates (SG-001..SG-003, T034) ---
    # Evaluate ``cycle-NNN-scout.json`` (scout output on disk — not research.json).
    spec_for_gates = ss._load_spec_for_scout_gates(vault_dir)
    if scout_exit == 0 and spec_for_gates is not None:
        try:
            scout_body = json.loads(scout_report.read_text(encoding="utf-8"))
        except Exception as exc:
            _LOG.info(
                f"[gates] WARN: could not load scout JSON for gates: {exc} — continuing"
            )
        else:
            try:
                quota = ss._cycle_quota_for_gates(pipeline_dir)
                unfilled = ss._unfilled_categories_for_gates(vault_dir)
                r1 = _evaluate_step_gate(
                    cycles_dir,
                    cycle_num,
                    SG001_topics_new_nonempty,
                    scout_body,
                    spec_for_gates,
                    quota,
                )
                if r1.status == "FAIL":
                    return 2
                r2 = _evaluate_step_gate(
                    cycles_dir,
                    cycle_num,
                    SG002_topic_category_diversity,
                    scout_body,
                    spec_for_gates,
                    unfilled,
                )
                if r2.status == "FAIL":
                    return 2
                r3 = _evaluate_step_gate(
                    cycles_dir,
                    cycle_num,
                    SG003_topic_abstraction_check,
                    scout_body,
                    spec_for_gates,
                    vault_dir,
                )
                if r3.status == "FAIL":
                    from research_framework.pipeline.correction import (
                        build_directive,
                    )

                    build_directive(
                        vault_dir,
                        failing_gates=[r3],
                        cycle=cycle_num,
                        batch=None,
                    )
                    # Re-render scout prompt so a follow-up scout sees the directive
                    # (prompt templates may inject ``_pipeline/corrections/`` — US4
                    # T056 will add explicit in-cycle re-prompt + batching).
                    sc._render_prompt(
                        scout_prompt_src,
                        scout_prompt_rendered,
                        {
                            "{CYCLE_NUM}": str(cycle_num),
                            "{SCOUT_REPORT}": str(scout_report),
                        },
                        vault_dir=vault_dir,
                        cycle_num=cycle_num,
                    )
                    try:
                        sr._run_script(
                            python_bin,
                            scripts_dir / "agent_call.py",
                            "--vault",
                            vault_dir,
                            "--stage",
                            "scout",
                            "--prompt-file",
                            scout_prompt_rendered,
                            "--cost-sidecar",
                            cycles_dir
                            / f"cycle-{cycle_3}"
                            / "agent-calls"
                            / "scout.json",
                            env=env,
                            log_file=cycles_dir / f"cycle-{cycle_3}-scout.log",
                        )
                    except sr._StepError:
                        return 2
                    if not scout_report.exists():
                        _LOG.error(f"ERROR: scout report not written at {scout_report}")
                        _LOG.info(
                            "The agent may have ignored the output-path instruction "
                            "after SG-003 correction."
                        )
                        return 2
                    try:
                        scout_exit_retry = sr._run_script(
                            python_bin,
                            scripts_dir / "validate_cycle.py",
                            scout_report,
                            "--vault",
                            vault_dir,
                            "--max-cycles",
                            max_cycles,
                            "--budget-cap",
                            budget_cap,
                            env=env,
                        )
                    except sr._StepError:
                        return 2
                    if scout_exit_retry == 2:
                        _LOG.info(
                            "ABORT: scout report has structural errors after "
                            "SG-003 retry. Fix and retry."
                        )
                        return 2
                    # Spec-019 / 0.2.30: SG-003 retry succeeded — archive the
                    # directive so later renders this cycle (DFS) and the
                    # first attempt of the next cycle aren't poisoned.
                    sc._archive_applied_directive(vault_dir, cycle_num)
                    if scout_exit_retry == 1:
                        _LOG.info("TERMINATE after scout retry — no DFS this cycle.")
                        try:
                            sr._run_script(
                                python_bin,
                                scripts_dir / "vault_metrics.py",
                                vault_dir,
                                "--output",
                                post_metrics,
                                env=env,
                            )
                        except sr._StepError:
                            pass
                        return 1
                    try:
                        scout_body = json.loads(
                            scout_report.read_text(encoding="utf-8")
                        )
                    except Exception as exc:
                        _LOG.info(
                            f"[gates] WARN: could not re-load scout JSON after "
                            f"SG-003 retry: {exc} — continuing with prior topics"
                        )
                    else:
                        r1b = _evaluate_step_gate(
                            cycles_dir,
                            cycle_num,
                            SG001_topics_new_nonempty,
                            scout_body,
                            spec_for_gates,
                            quota,
                            label=" (post retry)",
                        )
                        if r1b.status == "FAIL":
                            return 2
                        r2b = _evaluate_step_gate(
                            cycles_dir,
                            cycle_num,
                            SG002_topic_category_diversity,
                            scout_body,
                            spec_for_gates,
                            unfilled,
                            label=" (post retry)",
                        )
                        if r2b.status == "FAIL":
                            return 2
                        r3b = _evaluate_step_gate(
                            cycles_dir,
                            cycle_num,
                            SG003_topic_abstraction_check,
                            scout_body,
                            spec_for_gates,
                            vault_dir,
                            label=" (post retry)",
                        )
                        if r3b.status == "FAIL":
                            _LOG.info(
                                "[gates] SG-003 still FAIL after scout re-prompt — "
                                "continuing cycle; CG-003 enforces at cycle end"
                            )
            except Exception as exc:
                _LOG.warning(
                    f"[gates] WARN: scout step gates failed: {exc} — continuing"
                )

    # --- Step 2.5: merge scout-discovered topics into research-plan.md ---
    # The deterministic research plan is generated PRE-cycle from static
    # state (coverage-targets.json, backlog, exclusions). On a vault whose
    # coverage categories don't enumerate `expected_filenames`, that
    # produces an empty priority queue — there's nothing for the
    # dispatcher to slice in Step 3 and the cycle silently writes a
    # 4-line sentinel `cycle-NNN-research.json` that Step 6 then aborts
    # against. The fix: post-scout, fold `topics_found.new` into the
    # plan's queue (provenance="scout", score=1.0 so they pin to the
    # top) and rewrite `_pipeline/research-plan.md` on disk before the
    # DFS dispatcher loads it. Best-effort: an unreadable scout JSON
    # leaves the plan untouched (and is logged), it does not abort the
    # cycle.
    try:
        plan_md_path = pipeline_dir / "research-plan.md"
        if plan_md_path.is_file() and scout_report.is_file():
            from ..research_plan import (
                SCOUT_PROVENANCE as _SCOUT_PROV,
            )
            from ..research_plan import (
                ResearchPlan as _RP,
            )
            from ..research_plan import (
                merge_scout_topics as _merge_scout_topics,
            )

            existing_text = plan_md_path.read_text(encoding="utf-8")
            existing_plan = _RP.from_markdown(existing_text)
            existing_plan = dataclasses.replace(
                existing_plan,
                priority_queue=sc._parse_priority_queue_from_plan_md(existing_text),
            )
            merged_plan = _merge_scout_topics(existing_plan, scout_report)
            added = sum(
                1 for t in merged_plan.priority_queue if t.provenance == _SCOUT_PROV
            )
            if added:
                from ..atomic_write import write_text as _aw_text

                _aw_text(plan_md_path, merged_plan.to_markdown())
                cycle_archive = cycles_dir / f"cycle-{cycle_3}-research-plan.md"
                _aw_text(cycle_archive, merged_plan.to_markdown())
                _LOG.info(
                    f"[plan] merged {added} scout topic(s) into priority queue "
                    f"(total queue now {len(merged_plan.priority_queue)})"
                )
            else:
                _LOG.info(
                    "[plan] no scout topics merged "
                    "(topics_found.new empty or all duplicates of existing queue)"
                )
    except Exception as exc:
        _LOG.warning(
            f"[plan] WARN: merge_scout_topics failed: {exc} — using original plan"
        )
    return __exit


def run_scout(ctx: CycleContext) -> ScoutResult:
    t0 = time.monotonic()
    code = _phase(ctx)
    return _collect_result(ctx, exit_code=code, started_mono=t0)


def scout_result_from_disk(ctx: CycleContext) -> ScoutResult:
    """This cycle's scout result WITHOUT dispatching (budget-marker §4.5).

    A resume that starts at a later phase must still hand the rest of the
    cycle a scout result, or a cycle that was paused after scouting would
    report as one that scouted nothing. Rebuilding it costs nothing new:
    :func:`run_scout` already derives every field from
    ``cycle-NNN-scout.json`` and the persisted step-gate verdicts, so the only
    thing skipped here is the dispatch that already happened and was already
    paid for. The exit code is 0 because a scout the cycle moved on from is a
    scout that succeeded.
    """
    return _collect_result(ctx, exit_code=0, started_mono=time.monotonic())


def _collect_result(
    ctx: CycleContext, *, exit_code: int, started_mono: float
) -> ScoutResult:
    t0 = started_mono
    code = exit_code
    cycle_3 = f"{ctx.cycle_num:03d}"
    scout_report = ctx.cycles_dir / f"cycle-{cycle_3}-scout.json"
    topics: list[ScoutedTopic] = []
    cost = 0.0
    # Issue #269: the step gates were evaluated inside ``_phase`` and their
    # verdicts died there — ``sg_trips`` was hard-coded empty, so a cycle the
    # gate had just aborted reported no trip at all.
    trips = _step_gate_trips(ctx.cycles_dir, ctx.cycle_num)
    if scout_report.is_file():
        try:
            doc = json.loads(scout_report.read_text(encoding="utf-8"))
            for row in (doc.get("topics_found") or {}).get("new") or []:
                if isinstance(row, str):
                    topics.append(ScoutedTopic(title=row))
                elif isinstance(row, dict):
                    topics.append(
                        ScoutedTopic(
                            title=str(row.get("title") or ""),
                            coverage_category=row.get("coverage_category"),
                            note_type=row.get("note_type"),
                        )
                    )
            cost = float(
                doc.get("cost_estimate_usd") or doc.get("cumulative_cost_usd") or 0
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    return ScoutResult(
        topics_found=topics,
        sg_trips=trips,
        duration_ms=int((time.monotonic() - t0) * 1000),
        cost_usd=cost,
        raw_json_path=scout_report,
        exit_code=code,
    )
