"""Scout validation retry loop, prompt rendering, and correction directives."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from ..gates import GateResult
from . import script_runner
from ._scout_prompts import (  # noqa: F401
    _correction_prompt_text,
    _parse_priority_queue_from_plan_md,
    _read_correction_directive_block,
    _render_batch_note_writer_prompt,
    _render_prompt,
)
from .script_runner import _StepError

_LOG = logging.getLogger(__name__)

#: Maximum number of *additional* scout retries after a structural validation
#: failure, before the cycle aborts. ``1`` = "scout once, on structural error
#: feed the validator's complaints back to the agent, scout once more, then
#: give up." Spec-019 / 0.2.29 — see ``_retry_scout_with_validation_directive``.
#: Kept low on purpose: the directive is unambiguous (the validator names
#: every missing field by name), so the second attempt should converge or
#: the source of failure is something the agent can't fix without a human
#: intervention.
MAX_SCOUT_VALIDATION_RETRIES = 1


def _archive_applied_directive(vault_dir: Path, cycle_num: int) -> None:
    """Move a satisfied correction directive out of the active path.

    Called after a retry succeeds so the directive doesn't leak into
    the next render call (e.g. an unrelated DFS prompt later in the
    same cycle, or the first attempt of the next cycle). The directive
    is *moved*, not deleted, so a forensic reader can reconstruct what
    correction fired and when.
    """
    cycle_3 = f"{cycle_num:03d}"
    src = vault_dir / "_pipeline" / "corrections" / f"cycle-{cycle_3}.json"
    if not src.exists():
        return
    applied_dir = vault_dir / "_pipeline" / "corrections" / "applied"
    applied_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    dst = applied_dir / f"cycle-{cycle_3}-applied-{ts}.json"
    try:
        src.rename(dst)
    except OSError as exc:
        _LOG.warning(
            "_archive_applied_directive: could not move %s -> %s: %s",
            src,
            dst,
            exc,
        )


def _retry_scout_with_validation_directive(
    *,
    python_bin: Path,
    scripts_dir: Path,
    vault_dir: Path,
    cycles_dir: Path,
    cycle_num: int,
    cycle_3: str,
    scout_report: Path,
    scout_prompt_src: Path,
    scout_prompt_rendered: Path,
    max_cycles: int | str,
    budget_cap: float | str,
    env: dict[str, str],
) -> int:
    """Drive the scout-validation correction loop. Returns the final exit code.

    On entry, the most recent scout attempt has produced ``scout_report`` and
    ``validate_cycle.py`` has returned exit code 2 (structural error). The
    validator wrote a ``<report>.validation.json`` sidecar — we read the
    error list out of it, wrap it as a synthetic ``GateResult`` with a
    fresh gate id (``SV-002``: "Scout Validator, exit code 2"), build a
    correction directive via the same machinery SG-003 uses, re-render the
    scout prompt (which will inject the directive), and re-run the scout +
    validator. We do this at most ``MAX_SCOUT_VALIDATION_RETRIES`` times.
    Returns the *final* validate_cycle.py exit code (0/1/2).

    This is the spec-019 / 0.2.29 fix for H2 escalation — see the call site
    above for the rationale.
    """
    from research_framework.pipeline.correction import build_directive

    sidecar_path = scout_report.with_suffix(scout_report.suffix + ".validation.json")
    attempts_made = 0
    while attempts_made < MAX_SCOUT_VALIDATION_RETRIES:
        attempts_made += 1
        # Pull the validator's structured errors out of the sidecar. We
        # *don't* scrape stdout — the sidecar is the contract.
        try:
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            error_lines = list(sidecar.get("errors") or [])
        except (OSError, json.JSONDecodeError):
            error_lines = []
        if not error_lines:
            # Validator returned exit 2 but wrote no errors. Either the
            # sidecar is stale or this is an unrecoverable shape error
            # (JSON parse failure, missing schema_version). No directive
            # we can build will be useful — bail to abort.
            return 2
        msg = "Scout report has the following structural errors:\n" + "\n".join(
            f"- {e}" for e in error_lines
        )
        # Spec-019 / 0.2.30: the directive text the agent sees on retry
        # has to be unambiguous about HOW to comply. The 0.2.28 H2
        # enforcement caught missing sources but the 0.2.29 directive
        # told the agent to "fix this" without saying how. With the
        # 0.2.30 phase-scoping in validate_cycle.py, the only sources
        # that can land here are ones the scout SHOULD have consulted
        # (role: behaviour / intent), so the compliance pattern is
        # concrete: either list the source as actually consulted, or
        # acknowledge skipping it with a one-line reason — both are
        # accepted by validate_sources_v2.
        hint = (
            "Re-emit the scout report fixing every error above. For each "
            "missing source named in the diagnosis, add an entry to your "
            "``sources_consulted`` list using ONE of these two shapes:\n\n"
            "  1. Plain string when you actually consulted it this cycle:\n"
            '       "sources_consulted": ["Local Team Service Repositories", "GitHub Pull Requests and Review Conversations", ...]\n\n'
            "  2. Object form when you genuinely skipped it (the validator "
            "accepts this — it becomes a WARN, not an ABORT):\n"
            '       "sources_consulted": [\n'
            '         {"name": "GitHub Pull Requests and Review Conversations", "searched": false, "reason": "<one-line reason>"},\n'
            "         ...\n"
            "       ]\n\n"
            "You MAY mix the two shapes in the same list. Preserve every "
            "existing topic and intent row in your prior report — only "
            "modify the named structural fields. Source names must match "
            "those declared in research.spec.md exactly (case-insensitive)."
        )
        synthetic = GateResult(
            gate_id="SG-006",
            status="FAIL",
            metric_name="scout_validation_structural_errors",
            metric_value=float(len(error_lines)),
            threshold=0.0,
            message=msg,
            correction_hint=hint,
        )
        build_directive(
            vault_dir,
            failing_gates=[synthetic],
            cycle=cycle_num,
            batch=None,
        )
        _LOG.info(
            "[scout] structural validation failed on attempt "
            "%s — re-prompting scout with validator "
            "directive (%s error(s)).",
            attempts_made,
            len(error_lines),
        )
        _render_prompt(
            scout_prompt_src,
            scout_prompt_rendered,
            {"{CYCLE_NUM}": str(cycle_num), "{SCOUT_REPORT}": str(scout_report)},
            vault_dir=vault_dir,
            cycle_num=cycle_num,
        )
        try:
            script_runner._run_script(
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
        except _StepError:
            return 2
        if not scout_report.exists():
            _LOG.error(
                "scout report not written at %s after validator-directive retry.",
                scout_report,
            )
            return 2
        try:
            retry_exit = script_runner._run_script(
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
        except _StepError:
            return 2
        if retry_exit != 2:
            # Spec-019 / 0.2.30: archive the directive so it doesn't
            # leak into later renders (DFS prompt, next cycle's first
            # attempt). Best-effort; failure to archive is logged but
            # doesn't change the cycle outcome.
            _archive_applied_directive(vault_dir, cycle_num)
            return retry_exit
    return 2
