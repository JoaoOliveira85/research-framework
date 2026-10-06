"""Postprocess step (spec 025 US6 B3)."""

from __future__ import annotations

import json
import logging
import time

from .._helpers import script_runner as sr
from .._helpers import source_signals as ss
from ..atomic_write import write_json as _atomic_write_json
from ._types import (
    CoverageDelta,
    CycleContext,
    PostprocessResult,
    ResearchResult,
    WikilinkFix,
)

_LOG = logging.getLogger(__name__)


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
    cycles_dir / f"cycle-{cycle_3}-scout.json"
    research_report = cycles_dir / f"cycle-{cycle_3}-research.json"
    cycles_dir / f"cycle-{cycle_3}-pre-metrics.json"
    post_metrics = cycles_dir / f"cycle-{cycle_3}-post-metrics.json"
    assert scripts_dir is not None and cycles_dir is not None
    assert prompts_dir is not None and python_bin

    # --- Step 4: post-DFS validation suite (report-only; does not halt the cycle) ---
    try:
        vv_rc = sr._run_script(
            python_bin, scripts_dir / "validate_vault.py", vault_dir, env=env
        )
    except sr._StepError:
        vv_rc = 2
    try:
        tc_rc = sr._run_script(
            python_bin, scripts_dir / "check_template_compliance.py", vault_dir, env=env
        )
    except sr._StepError:
        tc_rc = 2
    try:
        ac_rc = sr._run_script(
            python_bin, scripts_dir / "check_acronym_links.py", vault_dir, env=env
        )
    except sr._StepError:
        ac_rc = 2

    # Feature 002 — code-first validators (skip if not present)
    id_rc = 0
    if (scripts_dir / "check_intent_drift.py").exists():
        try:
            id_rc = sr._run_script(
                python_bin, scripts_dir / "check_intent_drift.py", vault_dir, env=env
            )
        except sr._StepError:
            id_rc = 2
    cs_rc = 0
    if (scripts_dir / "check_code_source_coverage.py").exists():
        try:
            cs_rc = sr._run_script(
                python_bin,
                scripts_dir / "check_code_source_coverage.py",
                vault_dir,
                env=env,
            )
        except sr._StepError:
            cs_rc = 2

    if any(rc != 0 for rc in (vv_rc, tc_rc, ac_rc, id_rc, cs_rc)):
        _LOG.info(
            f"[Step 4] Quality violations reported "
            f"(vault={vv_rc} template={tc_rc} acronym={ac_rc} "
            f"drift={id_rc} code_source={cs_rc}) — cycle continues."
        )

    # --- Step 5: post-metrics + check research report ---
    try:
        rc5 = sr._run_script(
            python_bin,
            scripts_dir / "vault_metrics.py",
            vault_dir,
            "--output",
            pipeline_dir / "vault-metrics.json",
            env=env,
        )
    except sr._StepError:
        return 2
    if rc5 != 0:
        _LOG.error(
            "vault_metrics.py exited %s at Step 5 — cannot copy metrics.",
            rc5,
        )
        return 2
    from ..atomic_write import write_json as _write_json

    _write_json(
        post_metrics,
        json.loads((pipeline_dir / "vault-metrics.json").read_text(encoding="utf-8")),
    )

    if not research_report.exists():
        _LOG.error(f"ERROR: research report not written at {research_report}")
        return 2
    # --- Step 6: validate research ---
    try:
        research_exit = sr._run_script(
            python_bin,
            scripts_dir / "validate_cycle.py",
            research_report,
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
    # --- Step 6b: source manager — record cycle quality metrics (best-effort) ---
    if research_exit != 2:
        try:
            import json as _json

            from ..source_manager import record_cycle as _record_cycle

            if research_report.exists():
                _report_data = _json.loads(research_report.read_text(encoding="utf-8"))
                _record_cycle(
                    vault_dir,
                    cycle_num,
                    _report_data,
                    notes_dir=vault_dir / "data_vault",
                )
        except Exception as e:
            _LOG.warning("source_manager.record_cycle failed: %s — continuing", e)

    # --- Step 7: topic harvest (best-effort) ---
    if research_exit != 2:
        try:
            rc = sr._run_script(
                python_bin,
                scripts_dir / "topic_harvest.py",
                vault_dir,
                cycle_num,
                env=env,
            )
            if rc != 0:
                _LOG.warning("topic_harvest.py exited %s — continuing", rc)
        except Exception as e:
            _LOG.warning("topic_harvest.py failed: %s — continuing", e)

    # --- Step 7b: topic propose (Phase 2, best-effort, opt-in) ---
    if research_exit != 2:
        if (scripts_dir / "topic_propose.py").exists():
            try:
                rc = sr._run_script(
                    python_bin,
                    scripts_dir / "topic_propose.py",
                    vault_dir,
                    cycle_num,
                    env=env,
                )
                if rc != 0:
                    _LOG.warning("topic_propose.py exited %s — continuing", rc)
            except Exception as e:
                _LOG.warning("topic_propose.py failed: %s — continuing", e)

    if research_exit != 2:
        try:
            spec_probe = ss._load_spec_for_scout_gates(vault_dir)
            if spec_probe is not None:
                ss._run_probe_retrieval_and_cache(vault_dir, spec_probe, cycle_num)
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning(
                "[cycle_runner] probe-retrieval step failed: %s", exc
            )
    return research_exit


def run_postprocess(
    ctx: CycleContext, research_result: ResearchResult
) -> PostprocessResult:
    _ = research_result
    t0 = time.monotonic()
    code = _phase(ctx)
    cycle_3 = f"{ctx.cycle_num:03d}"
    post_json = ctx.cycles_dir / f"cycle-{cycle_3}-postprocess.json"
    fixes: list[WikilinkFix] = []
    post_json.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(
        post_json,
        {"cycle": ctx.cycle_num, "phase": "postprocess", "exit_code": code},
    )
    return PostprocessResult(
        wikilink_fixes=fixes,
        coverage_delta=CoverageDelta(),
        duration_ms=int((time.monotonic() - t0) * 1000),
        raw_json_path=post_json,
        exit_code=code,
    )
