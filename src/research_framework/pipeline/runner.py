"""Pipeline orchestrator runner — 015g.

Sequences the seven research-pipeline phases:
  collect → extract → scout → triage → research → verify → report

Public API
----------
    run_full(vault, *, quiet) -> int
    run_collect(vault, *, quiet) -> int
    run_extract(vault, *, quiet) -> int
    run_scout(vault, *, quiet) -> int
    run_resume(vault, *, quiet) -> int
    run_finish(vault, *, quiet) -> int
    status(vault) -> dict
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..vault.corpus import existing_corpus_dir
from . import run_receipt
from .process_tree import popen_session, terminate_process_tree

_LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PHASES = ["collect", "extract", "scout", "triage", "research", "verify", "report"]
FRAMEWORK_VERSION = 1
STATE_FILE = "_pipeline/pipeline-state.json"

# Phase statuses
PENDING = "pending"
IN_PROGRESS = "in_progress"
WAITING = "waiting"
DONE = "done"
SKIPPED = "skipped"
FAILED = "failed"


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


def _now_utc() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_run_id() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%d-%H%M")


def _framework_version() -> str:
    """The package version, for the receipt's ``framework_version`` field.

    Distinct from the state file's ``FRAMEWORK_VERSION``, which is an integer
    schema version. Falls back to ``"unknown"`` rather than raising: a version
    lookup must never be what fails a run.
    """
    try:
        from importlib.metadata import version

        return version("research-framework")
    except Exception:  # pragma: no cover — packaging edge
        return "unknown"


def _run_dir(
    vault: Path, state: dict[str, Any], *, verb: str | None = None
) -> Path | None:
    """This run's directory, derived from the state file's ``run_id``.

    Creates it when absent, which is what makes ``resume`` and ``finish`` work
    on a state file written before spec 080 shipped (FR-004): the run is
    reconstructed and recorded as such, not refused. The reconstruction flag
    is a marker FILE, not a key on the state dict — the state file's schema is
    ``additionalProperties: false`` and FR-001 keeps it that way, so anything
    the receipt needs and the state file does not carry lives on disk beside
    the artifacts.
    """
    run_id = state.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        return None
    # "Reconstructed" means phases ran BEFORE the directory existed — a state
    # file written before spec 080 shipped. A state file already on disk plus
    # no directory for its run_id is exactly that shape. A bare
    # `pipeline <vault> scout` on a fresh vault mints a new run_id and creates
    # its first directory, which is a new run, not a recovered one.
    resuming_an_existing_run = (vault / STATE_FILE).exists()
    path, created = run_receipt.ensure_run_dir(vault, run_id)
    if path is None:
        return None
    if created and resuming_an_existing_run and verb != "full":
        run_receipt.mark_reconstructed(path)
    if verb is not None:
        run_receipt.record_verb(path, verb)
    return path


def _write_receipt(vault: Path, state: dict[str, Any]) -> None:
    """Rewrite ``run.json`` + ``run-report.md`` from state and disk."""
    run_receipt.write_receipt(
        vault,
        state,
        phases=tuple(PHASES),
        framework_version=_framework_version(),
    )


def _blank_state(run_id: str, started_at: str) -> dict[str, Any]:
    phases: dict[str, Any] = {}
    for phase in PHASES:
        phases[phase] = {"status": PENDING, "errors": []}
    return {
        "run_id": run_id,
        "started_at": started_at,
        "framework_version": FRAMEWORK_VERSION,
        "phases": phases,
    }


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    from .atomic_write import write_json

    write_json(path, data)


def _load_state(vault: Path) -> dict[str, Any]:
    """Load pipeline-state.json; return blank state if absent."""
    state_path = vault / STATE_FILE
    if not state_path.exists():
        now = _now_utc()
        return _blank_state(_make_run_id(), now)
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read pipeline-state.json: {exc}") from exc


def _save_state(vault: Path, state: dict[str, Any]) -> None:
    _atomic_write_json(vault / STATE_FILE, state)


def _set_phase(
    state: dict[str, Any],
    phase: str,
    *,
    phase_status: str,
    started_at: str | None = None,
    finished_at: str | None = None,
    summary: dict[str, Any] | None = None,
    errors: list[str] | None = None,
) -> None:
    rec = state["phases"][phase]
    rec["status"] = phase_status
    if started_at is not None:
        rec["started_at"] = started_at
    if finished_at is not None:
        rec["finished_at"] = finished_at
    if summary is not None:
        rec["summary"] = summary
    if errors is not None:
        rec["errors"] = errors


def _resolve_phase_cost(
    phase: str, summary: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Copy the dispatch's cost out of its sidecar and into the phase summary.

    FR-012. The sidecar the phase ASKED for is the expectation; whether it
    arrived is the finding. A sidecar that is missing or unparseable yields
    ``cost_usd: None`` and a ``WARNING`` naming the path it should have been
    at — spec 078 FR-015's "no zero is silent" rule binds the reader as much
    as the writer, and a run that reports ``$0.00`` for a phase that
    dispatched an agent is worse than one that says it does not know.
    """
    if not summary:
        return summary
    expected = summary.get("cost_sidecar")
    if not isinstance(expected, str):
        return summary
    cost, source = run_receipt.read_sidecar_cost(Path(expected))
    if cost is None:
        _LOG.warning(
            "  WARN: the %s phase dispatched an agent but its cost sidecar at "
            "%s is missing or unreadable; this run's cost is a lower bound.",
            phase,
            expected,
        )
    summary["cost_usd"] = cost
    summary["cost_source"] = source
    return summary


def _close_phase(
    vault: Path,
    state: dict[str, Any],
    phase: str,
    *,
    phase_status: str,
    summary: dict[str, Any] | None = None,
    errors: list[str] | None = None,
) -> int:
    """Persist a phase's terminal record, REPORT it, and return its exit code.

    Every ``_drive_*`` driver used to end the same way: build ``errors``, hand
    them to :func:`_set_phase`, save, and return ``0``/``1``. None of them said
    anything above ``INFO``. ``cli/_log_level`` drops to ``WARNING`` off a TTY,
    which is every cron / launchd / systemd run, so a failing weekly run wrote
    its entire diagnosis into ``pipeline-state.json`` and emitted zero bytes.
    Spec 070 FR6 — "every non-zero exit MUST write a diagnosable message to
    stderr" — has been marked DONE since v1.0.0; the FR6 backstop was the only
    thing in a failed run that spoke, and it named ``run-report.md``, which the
    pipeline runner does not write (issue #219).

    The reviewers asked for one helper rather than six bespoke patches, so this
    is the single place a phase ends. Severity carries meaning, the same way
    PR #305 made it carry meaning in the CLI:

    * ``FAILED`` → ``ERROR``. This is the exit reason, and ``ERROR`` is what
      ``cli.__init__._ReasonCounter`` counts as one.
    * ``SKIPPED`` → ``WARNING``. The phase did not fail, but it did not do the
      work either, and a downstream phase is about to be starved (issue #223).
    * anything else → nothing extra. The drivers narrate their own success at
      ``INFO`` and a successful run must stay quiet under a redirect.

    The message names the absolute path of ``pipeline-state.json`` because the
    log line is bounded and the state file is not: the truncated reason points
    at the whole record. ``quiet`` is deliberately not consulted — it suppresses
    narration, not the reason a run exited non-zero.
    """
    recorded = list(errors or [])
    summary = _resolve_phase_cost(phase, summary)
    _set_phase(
        state,
        phase,
        phase_status=phase_status,
        finished_at=_now_utc(),
        summary=summary,
        errors=recorded,
    )
    _save_state(vault, state)
    _write_receipt(vault, state)

    if phase_status == FAILED:
        detail = "\n".join(f"  - {e}" for e in recorded) or (
            "  - (no reason recorded — that is itself a bug)"
        )
        run_dir = run_receipt.run_dir_for(vault, state.get("run_id") or "")
        _LOG.error(
            "phase '%s' FAILED (%d error(s)):\n%s\nFull record: %s\nThis run: %s",
            phase,
            len(recorded),
            detail,
            vault / STATE_FILE,
            run_dir,
        )
        return 1

    if phase_status == SKIPPED:
        reason = (summary or {}).get("skipped_reason") or "no reason recorded"
        _LOG.warning(
            "phase '%s' SKIPPED: %s. Full record: %s",
            phase,
            reason,
            vault / STATE_FILE,
        )
        return 0

    return 0


# ---------------------------------------------------------------------------
# Phase drivers
# ---------------------------------------------------------------------------


def _is_rss_access(access_method: str) -> bool:
    lowered = access_method.lower()
    return "rss" in lowered or "feed" in lowered or "atom" in lowered


def _partition_declared_sources(
    vault: Path,
) -> tuple[list[str], list[dict[str, str]], list[str]]:
    """Split the spec's external sources into (rss names, unsupported, errors).

    "Unsupported" means exactly one thing: this framework version has no
    collector that can read it. That is currently everything except RSS — web
    fetch, GitHub, arXiv, Reddit, HN — because ``collect`` never routes through
    the ``source_bridge`` modules spec 020 shipped.
    """
    spec_parse = vault / "_pipeline" / "spec-parse.json"
    if not spec_parse.exists():
        return [], [], []

    try:
        spec_data = json.loads(spec_parse.read_text(encoding="utf-8"))
    except Exception as exc:
        return [], [], [f"spec-parse.json read error: {exc}"]

    rss_names: list[str] = []
    unsupported: list[dict[str, str]] = []
    for ds in spec_data.get("data_sources", []) or []:
        if not isinstance(ds, dict) or ds.get("type") != "external":
            continue
        access = str(ds.get("access_method", ""))
        if _is_rss_access(access):
            rss_names.append(str(ds.get("name", "")))
        else:
            unsupported.append(
                {"name": str(ds.get("name", "")), "access_method": access}
            )
    return rss_names, unsupported, []


def _drive_collect(vault: Path, state: dict[str, Any], *, quiet: bool) -> int:
    """Collect phase: enumerate spec data_sources; dispatch to collectors."""
    phase = "collect"
    started = _now_utc()
    _set_phase(state, phase, phase_status=IN_PROGRESS, started_at=started, errors=[])
    _save_state(vault, state)

    summary: dict[str, Any] = {"items_new": 0, "by_source": {}}
    errors: list[str] = []

    rss_source_names, unsupported, parse_errors = _partition_declared_sources(vault)
    errors.extend(parse_errors)
    summary["declared_sources"] = len(rss_source_names) + len(unsupported)
    summary["unsupported_sources"] = unsupported

    # Run the RSS collector (014's first slice).
    try:
        from ..collectors.rss import collect as rss_collect

        result = rss_collect(vault, sources=rss_source_names or None)
        summary["items_new"] += result.fetched
        summary["by_source"]["rss"] = result.fetched
        errors.extend(result.errors)
        if not quiet:
            _LOG.info(
                f"  collect_rss: {result.fetched} new items "
                f"({result.skipped_existing} skipped)"
            )
    except Exception as exc:
        errors.append(f"rss collector error: {exc}")

    # A declared source this framework cannot read is the operator's problem to
    # know about, at a level a redirected run can see. It used to be logged at
    # INFO — invisible under the non-TTY WARNING default — and only for the
    # four kinds ``_infer_kind`` happened to recognise, so a vault declaring
    # web fetch, GitHub and official docs said nothing at all (issue #223).
    if unsupported:
        _LOG.warning(
            "  WARN: %d declared data source(s) have no collector in this "
            "framework version and were NOT collected: %s. Extract and the "
            "context tree will be empty for them.",
            len(unsupported),
            ", ".join(f"{s['name']} ({s['access_method']})" for s in unsupported),
        )

    if not quiet:
        _LOG.info(f"  Total: {summary['items_new']} new items in _pipeline/raw/")

    if errors:
        final_status = FAILED
    elif unsupported and summary["items_new"] == 0:
        # Nothing was collected AND the reason is that the runner cannot read
        # what the spec declares. That is not success. SKIPPED-with-reason is
        # what lets `pipeline status` distinguish it from an honest zero —
        # an empty RSS feed, or a vault that declares no external sources at
        # all, both of which stay DONE.
        final_status = SKIPPED
        summary["skipped_reason"] = (
            f"collected nothing: all {len(unsupported)} declared data source(s) "
            f"({', '.join(s['name'] for s in unsupported)}) need a collector "
            f"this framework version does not have. Nothing downstream will "
            f"have input — extract will report 0 files and the report will say "
            f"there is no context tree."
        )
    else:
        final_status = DONE

    return _close_phase(
        vault,
        state,
        phase,
        phase_status=final_status,
        summary=summary,
        errors=errors,
    )


def _drive_extract(vault: Path, state: dict[str, Any], *, quiet: bool) -> int:
    """Extract phase: run the extract processor."""
    phase = "extract"
    started = _now_utc()
    _set_phase(state, phase, phase_status=IN_PROGRESS, started_at=started, errors=[])
    _save_state(vault, state)

    errors: list[str] = []
    context_tree_path: Path | None = None
    files_processed = 0

    try:
        from ..processors.extract import extract

        result = extract(vault)
        files_processed = result.files_processed
        context_tree_path = result.context_tree_path
        errors.extend(result.errors)
        if not quiet:
            if context_tree_path:
                _LOG.info(
                    "  %s items processed; context tree at %s",
                    files_processed,
                    context_tree_path.relative_to(vault),
                )
            else:
                _LOG.info("  %s items processed", files_processed)
    except Exception as exc:
        errors.append(f"extract processor error: {exc}")

    summary: dict[str, Any] = {"files_processed": files_processed}
    if context_tree_path:
        summary["context_tree_path"] = str(context_tree_path)

    final_status = DONE if not errors else FAILED
    return _close_phase(
        vault,
        state,
        phase,
        phase_status=final_status,
        summary=summary,
        errors=errors,
    )


# Vault-relative source of each agent stage's prompt. Two kinds of source
# exist and they are NOT interchangeable:
#
# * ``_pipeline/prompts/*.md`` — pipeline prompt templates written by
#   ``research-framework generate``. They carry the ``{CYCLE_NUM}`` /
#   ``{SCOUT_REPORT}`` / ``{RESEARCH_REPORT}`` placeholders that name the
#   run's artifacts, so substituting those is the whole rendering job.
# * ``.claude/commands/*.md`` — the vault's rendered agent definition. It is
#   the authoritative behaviour for its stage but carries no placeholders,
#   so the runner has to state this run's artifact paths itself (see
#   ``_run_context_block``).
_STAGE_PROMPT_SOURCES: dict[str, str] = {
    "scout": "_pipeline/prompts/scout-prompt.md",
    # The pipeline's research phase IS the DFS note-writer, and
    # ``dfs-prompt.md`` is the only shipped template that consumes
    # ``scout-report.json``'s ``topics_found.new`` — the queue THIS runner
    # actually produces (``_drive_scout`` renders the scout prompt against
    # that exact path). The ``.claude/commands/research.md`` agent
    # definition drives off a "Topic Radar" note instead, which is a
    # cycle-orchestrator artifact a ``pipeline`` run never writes; pointing
    # this phase at it would stop every run on "Research queue is clear".
    # It also carries a user-configurable filename
    # (``spec.settings.commands.research``), so it is not reliably locatable.
    "research": "_pipeline/prompts/dfs-prompt.md",
    # No report prompt template ships. The report agent definition IS the
    # phase's behaviour, and every generated vault carries it under this
    # fixed name (``generator.templates.render_all`` →
    # ``write_agents(only=[..., "report", ...])``).
    "report": ".claude/commands/report.md",
}


def _stage_artifacts(vault: Path) -> dict[str, Path]:
    """Absolute paths of the artifacts a single-shot pipeline run works with.

    Single source of these paths: ``_render_stage_prompt`` substitutes them
    into the prompt templates and ``_run_context_block`` names them for the
    agent definitions, so a rename cannot leave the two disagreeing.
    """
    pipeline_dir = vault / "_pipeline"
    return {
        "scout_report": pipeline_dir / "scout-report.json",
        "research_report": pipeline_dir / "research-report.json",
        "context_tree": pipeline_dir / "extracted" / "context-tree.md",
        "pipeline_state": vault / STATE_FILE,
    }


def _run_facts(vault: Path, run_dir: Path | None) -> list[str]:
    """What THIS run did, read from its own receipt (spec 080 FR-015, #224).

    On 2026-09-01 one vault's weekly report claimed 45 notes added for a run
    whose research phase created zero. The agent was never told what the run
    did, so it reconstructed a narrative from the only thing it could see —
    the repository's git history — and the narrative was about a different
    week. Handing it the run's own counts is the fix: a report that claims
    additions then contradicts the facts printed above it.

    Read from ``run.json`` rather than re-derived from the flat artifacts,
    so the report and ``status`` cannot disagree about the same run.
    """
    if run_dir is None:
        return []
    try:
        receipt = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(receipt, dict):
        return []

    phases = receipt.get("phases") or {}

    def _summary(phase: str) -> dict[str, Any]:
        rec = phases.get(phase) or {}
        summary = rec.get("summary")
        return summary if isinstance(summary, dict) else {}

    lines = [
        "## What this run did",
        "",
        f"Run `{receipt.get('run_id')}`, recorded at `{run_dir}`.",
        "",
        "Phase outcomes: "
        + ", ".join(
            f"{name} {(rec or {}).get('status', 'pending')}"
            for name, rec in phases.items()
        )
        + ".",
        "",
    ]

    unsupported = _summary("collect").get("unsupported_sources")
    if isinstance(unsupported, list) and unsupported:
        lines.append(
            "- Sources this run could NOT collect from: "
            + ", ".join(str(s) for s in unsupported)
            + "."
        )

    queue = _summary("scout").get("topics_found_new")
    if queue is None:
        queue = _triage_queue_size(vault)
    if queue is not None:
        lines.append(f"- The scout queue held {queue} topic(s).")

    created = _summary("research").get("notes_created")
    updated = _summary("research").get("notes_updated")
    created_n = created if isinstance(created, int) else None
    updated_n = updated if isinstance(updated, int) else None
    if created_n is not None or updated_n is not None:
        lines.append(
            f"- The research phase created {created_n if created_n is not None else '?'}"
            f" note(s) and updated {updated_n if updated_n is not None else '?'}."
        )
    # FR-016: said in a sentence, before any instruction to summarise
    # additions, so a report that lists new notes contradicts its own input.
    if created_n == 0:
        lines.append("")
        lines.append(
            "**This run created no notes.** Do not describe additions: there "
            "were none. Say so, and report why the run produced nothing if the "
            "phase outcomes above show a reason."
        )
        lines.append("")

    verify = _summary("verify")
    if verify.get("verdict"):
        lines.append(
            f"- Verify verdict: **{verify.get('verdict')}** over "
            f"{verify.get('notes_checked', '?')} note(s) — "
            f"{verify.get('content_flags', '?')} content flag(s), "
            f"{verify.get('tooling_flags', '?')} tooling flag(s)."
        )
        by_check = verify.get("flags_by_check")
        if isinstance(by_check, dict) and by_check:
            top = sorted(
                ((k, v) for k, v in by_check.items() if isinstance(v, int)),
                key=lambda kv: kv[1],
                reverse=True,
            )[:3]
            if top:
                lines.append(
                    "- Most frequent flag families: "
                    + ", ".join(f"{name} ({count})" for name, count in top)
                    + "."
                )

    cost = receipt.get("cost") or {}
    total = cost.get("total_usd")
    if isinstance(total, int | float):
        bound = (
            " (a lower bound — a cost sidecar could not be read)"
            if cost.get("sidecars_missing")
            else ""
        )
        lines.append(f"- This run cost ${total:.4f}{bound}.")

    verify_report = (receipt.get("artifacts") or {}).get("verify_report")
    if verify_report:
        # FR-017: the file the runner actually wrote, not `verify-*.md`, which
        # nothing has ever written.
        lines.append(f"- Full verify detail: `{verify_report}`.")

    lines += ["", "---", ""]
    return lines


def _run_context_block(vault: Path, stage: str, run_dir: Path | None = None) -> str:
    """Preamble naming this run's artifacts, by absolute path.

    Prepended only to a prompt sourced from an agent definition. Those are
    written for interactive slash-command use and describe the artifacts of
    a *cycle* run; a ``research-framework pipeline`` run is single-shot and
    writes a different, flat set. Naming them explicitly is what keeps the
    agent off a Topic Radar note or a ``_pipeline/cycles/`` directory this
    runner never creates.

    Since spec 080 FR-015 it also carries what the run itself did, from the
    receipt — see :func:`_run_facts`.
    """
    artifacts = _stage_artifacts(vault)
    return (
        "\n".join(
            [
                "## Pipeline run context",
                "",
                f"You are the `{stage}` phase of a single-shot "
                f"`research-framework pipeline` run over the vault at "
                f"`{vault}`.",
                "",
                "This run's artifacts, by absolute path:",
                "",
                f"- Triaged research queue: `{artifacts['scout_report']}` — "
                "the approved topics are its `topics_found.new` entries.",
                f"- Research output: `{artifacts['research_report']}`.",
                f"- Extracted context tree: `{artifacts['context_tree']}`.",
                "- Per-phase status and the verify verdict: "
                f"`{artifacts['pipeline_state']}`.",
                "",
                "A pipeline run has no cycle directory and no Topic Radar "
                "note. Read the queue from the file above, and treat any "
                "artifact that does not exist as unavailable rather than "
                "waiting for it.",
                "",
                "---",
                "",
            ]
            + _run_facts(vault, run_dir)
        )
        + "\n"
    )


def _render_stage_prompt(
    vault: Path, stage: str, run_dir: Path | None = None
) -> Path | None:
    """Render ``stage``'s prompt under the run directory (spec 080 FR-003).

    Was ``_pipeline/<stage>-prompt.rendered.md``, which the next run
    overwrote — so the prompt that produced a bad answer was gone by the time
    anyone looked. It is now ``<run_dir>/prompts/<stage>.rendered.md``, and a
    re-driven stage suffixes rather than overwrites (FR-005). The flat path
    remains the fallback when there is no run directory.

    The prompt templates carry ``{CYCLE_NUM}`` / ``{SCOUT_REPORT}`` /
    ``{RESEARCH_REPORT}`` placeholders inherited from the cycle-based
    orchestrator (``pipeline/steps/scout.py``, ``pipeline/steps/research.py``).
    This runner has no cycle concept, so it renders a fixed "cycle 1" against
    stage-level (not cycle-numbered) artifact paths and skips the cycle-based
    correction-directive injection (``_render_prompt``'s ``vault_dir`` /
    ``cycle_num`` kwargs) — that directive belongs to a
    ``_pipeline/cycles/`` history this runner does not write, and injecting it
    here would misattribute a stale directive to this run.

    Returns ``None`` when the stage has no registered source, when that
    source is absent from the vault (nothing to render), or when rendering
    fails. ``_call_agent`` then reports the gap and skips the phase rather
    than forwarding an empty prompt to a live agent.
    """
    relative_source = _STAGE_PROMPT_SOURCES.get(stage)
    if relative_source is None:
        return None
    source = vault / relative_source
    if not source.is_file():
        return None

    from ._helpers._scout_prompts import _render_prompt

    artifacts = _stage_artifacts(vault)
    dest = (
        run_receipt.stage_path(run_dir, "prompts", stage, ".rendered.md")
        if run_dir is not None
        else vault / "_pipeline" / f"{stage}-prompt.rendered.md"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        _render_prompt(
            source,
            dest,
            {
                "{CYCLE_NUM}": "1",
                "{SCOUT_REPORT}": str(artifacts["scout_report"]),
                "{RESEARCH_REPORT}": str(artifacts["research_report"]),
            },
        )
        if relative_source.startswith(".claude/commands/"):
            body = dest.read_text(encoding="utf-8")
            dest.write_text(
                _run_context_block(vault, stage, run_dir) + body, encoding="utf-8"
            )
    except OSError as exc:
        _LOG.warning(
            "  WARN: could not render the %s prompt from %s: %s",
            stage,
            source,
            exc,
        )
        return None
    return dest


# ---------------------------------------------------------------------------
# Phase completion is defined by artifact, not by exit code (issue #222)
#
# The scout, research and report phases were recorded ``done`` purely on the
# agent exiting 0. Nothing checked that ``scout-report.json`` or
# ``research-report.json`` existed, that they parsed, or that a single note had
# been written — so reference-vault's research phase ran for 34 seconds on
# 2026-09-01, wrote nothing, and is recorded ``done``.
#
# The cycle path has refused to do this since spec 019, through
# ``scripts/validate_cycle.py``. That script is NOT reachable from here: it
# lives in ``scripts/``, which ships as packaged DATA under
# ``research_framework/_data/scripts/`` and is reached only as a subprocess,
# and its checks are cycle-scoped (cycle numbers, coverage targets, a
# ``_pipeline/cycles/`` history this single-shot runner never writes). What the
# runner can and must assert is that the artifact IT names in the prompt came
# back, parsed, and carried the field the NEXT phase reads. That is the check
# below; a full validator reuse belongs with the runner's owning spec (#50).
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """``(document, error)`` — never raises, and never returns both."""
    if not path.is_file():
        return None, f"{path} was not written"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{path} could not be read: {exc}"
    if not isinstance(doc, dict):
        return None, f"{path} is not a JSON object"
    return doc, None


def _queue_from_scout_report(vault: Path) -> list[Any] | None:
    """``topics_found.new`` from the scout report, or ``None`` if unreadable."""
    doc, error = _read_json(_stage_artifacts(vault)["scout_report"])
    if error is not None or doc is None:
        return None
    found = doc.get("topics_found")
    new = found.get("new") if isinstance(found, dict) else None
    return new if isinstance(new, list) else None


def _consulted_names(sources_consulted: Any) -> set[str]:
    """Source names a report claims to have actually searched.

    v2 reports spell ``sources_consulted`` either as a list of names or as a
    map carrying a ``searched`` flag (``validate_cycle.validate_sources_v2``
    accepts both). A source listed with ``searched: false`` is not a source
    consulted — that is the exact shape reference-vault produced for web, GitHub
    and official docs.
    """
    if isinstance(sources_consulted, list):
        return {str(name) for name in sources_consulted}
    if isinstance(sources_consulted, dict):
        consulted = set()
        for name, detail in sources_consulted.items():
            if isinstance(detail, dict) and detail.get("searched") is False:
                continue
            consulted.add(str(name))
        return consulted
    return set()


def _declared_sources(vault: Path) -> list[str]:
    """External ``data_sources`` names the vault's spec declares."""
    doc, error = _read_json(vault / "_pipeline" / "spec-parse.json")
    if error is not None or doc is None:
        return []
    names = []
    for ds in doc.get("data_sources") or []:
        if isinstance(ds, dict) and ds.get("name"):
            names.append(str(ds["name"]))
    return names


def _unconsulted_sources(vault: Path, report: dict[str, Any]) -> list[str]:
    consulted = _consulted_names(report.get("sources_consulted"))
    return [name for name in _declared_sources(vault) if name not in consulted]


def _check_scout_artifact(vault: Path) -> tuple[list[str], dict[str, Any]]:
    """Scout is done ⇔ it wrote a readable queue. Returns (errors, summary)."""
    path = _stage_artifacts(vault)["scout_report"]
    doc, error = _read_json(path)
    if error is not None or doc is None:
        return ([f"the scout agent exited 0 but {error}"], {})

    found = doc.get("topics_found")
    new = found.get("new") if isinstance(found, dict) else None
    if not isinstance(new, list):
        return (
            [
                f"the scout agent exited 0 but {path} carries no "
                f"`topics_found.new` list — that is the queue `resume` "
                f"researches, so the next phase has nothing to read"
            ],
            {},
        )

    unconsulted = _unconsulted_sources(vault, doc)
    if unconsulted:
        # A warning, not a failure: a source may be legitimately empty this
        # week. What is not acceptable is the operator not being told, which
        # is how 7/7 vaults reported `rss: 0` in silence.
        _LOG.warning(
            "  WARN: the scout did not consult %d declared data source(s): %s. "
            "Extract and the context tree will be correspondingly thin.",
            len(unconsulted),
            ", ".join(unconsulted),
        )
    existing = found.get("existing") if isinstance(found, dict) else None
    return (
        [],
        {
            "topics_found_new": len(new),
            "topics_found_existing": len(existing) if isinstance(existing, list) else 0,
            "sources_not_consulted": unconsulted,
        },
    )


def _check_research_artifact(vault: Path) -> tuple[list[str], dict[str, Any]]:
    """Research is done ⇔ it wrote notes, or the queue was empty and it says so."""
    path = _stage_artifacts(vault)["research_report"]
    doc, error = _read_json(path)
    if error is not None or doc is None:
        return ([f"the research agent exited 0 but {error}"], {})

    created = doc.get("notes_created")
    created = created if isinstance(created, list) else []
    updated = doc.get("notes_updated")
    updated = updated if isinstance(updated, list) else []
    queue = _queue_from_scout_report(vault)
    queue_size = len(queue) if queue is not None else 0

    summary: dict[str, Any] = {
        "notes_created": len(created),
        "notes_updated": len(updated),
        "queue_size": queue_size,
    }

    if created or updated:
        return ([], summary)

    if queue_size == 0:
        # An honest no-op. Record WHY, so "nothing to research" is
        # distinguishable in `pipeline status` from "researched nothing".
        summary["empty_queue_reason"] = (
            "no topics were queued: `topics_found.new` in "
            f"{_stage_artifacts(vault)['scout_report']} is empty or absent"
        )
        return ([], summary)

    return (
        [
            f"the research agent exited 0 having written no notes, with "
            f"{queue_size} topic(s) queued in "
            f"{_stage_artifacts(vault)['scout_report']}"
        ],
        summary,
    )


def _check_report_artifact(vault: Path) -> tuple[list[str], dict[str, Any]]:
    """Report is done ⇔ an export file exists."""
    exports_dir = vault / "_pipeline" / "exports"
    exports = sorted(p for p in exports_dir.glob("*.md") if p.is_file())
    if not exports:
        return (
            [f"the report agent exited 0 but wrote no export under {exports_dir}"],
            {"exports": 0},
        )
    return ([], {"exports": len(exports), "latest_export": str(exports[-1])})


def _drive_scout(vault: Path, state: dict[str, Any], *, quiet: bool) -> int:
    """Scout phase: invoke the scout agent via agent_call.py."""
    phase = "scout"
    started = _now_utc()
    _set_phase(state, phase, phase_status=IN_PROGRESS, started_at=started, errors=[])
    _save_state(vault, state)

    run_dir = _run_dir(vault, state)
    errors: list[str] = []
    summary: dict[str, Any] = {}
    try:
        prompt_file = _render_stage_prompt(vault, "scout", run_dir)
        outcome = _call_agent(
            vault,
            stage="scout",
            quiet=quiet,
            prompt_file=prompt_file,
            run_dir=run_dir,
        )
        errors.extend(_agent_phase_errors("scout", outcome))
        if outcome.log_path is not None:
            summary["agent_log"] = str(outcome.log_path)
        if outcome.cost_sidecar is not None:
            summary["cost_sidecar"] = str(outcome.cost_sidecar)
        if prompt_file is not None:
            summary["prompt"] = str(prompt_file)
        if not errors:
            # Exit 0 is a claim, not evidence. The phase is done only if the
            # artifact the NEXT phase reads is actually there (issue #222).
            artifact_errors, artifact_summary = _check_scout_artifact(vault)
            errors.extend(artifact_errors)
            summary.update(artifact_summary)
    except Exception as exc:
        errors.append(f"scout agent error: {exc}")

    final_status = DONE if not errors else FAILED
    return _close_phase(
        vault,
        state,
        phase,
        phase_status=final_status,
        summary=summary,
        errors=errors,
    )


def _drive_research(vault: Path, state: dict[str, Any], *, quiet: bool) -> int:
    """Research phase: invoke the research agent via agent_call.py."""
    phase = "research"
    started = _now_utc()
    _set_phase(state, phase, phase_status=IN_PROGRESS, started_at=started, errors=[])
    _save_state(vault, state)

    run_dir = _run_dir(vault, state)
    errors: list[str] = []
    summary: dict[str, Any] = {}
    try:
        prompt_file = _render_stage_prompt(vault, "research", run_dir)
        outcome = _call_agent(
            vault,
            stage="research",
            quiet=quiet,
            prompt_file=prompt_file,
            run_dir=run_dir,
        )
        errors.extend(_agent_phase_errors("research", outcome))
        if outcome.log_path is not None:
            summary["agent_log"] = str(outcome.log_path)
        if outcome.cost_sidecar is not None:
            summary["cost_sidecar"] = str(outcome.cost_sidecar)
        if prompt_file is not None:
            summary["prompt"] = str(prompt_file)
        if not errors:
            # Exit 0 is a claim, not evidence. The phase is done only if the
            # artifact the NEXT phase reads is actually there (issue #222).
            artifact_errors, artifact_summary = _check_research_artifact(vault)
            errors.extend(artifact_errors)
            summary.update(artifact_summary)
    except Exception as exc:
        errors.append(f"research agent error: {exc}")

    final_status = DONE if not errors else FAILED
    return _close_phase(
        vault,
        state,
        phase,
        phase_status=final_status,
        summary=summary,
        errors=errors,
    )


def _corpus_dir(vault: Path) -> Path:
    """Resolve the vault's corpus directory, falling back to the vault root.

    The name comes from the shared seam
    (:func:`research_framework.vault.corpus.existing_corpus_dir`). Only the
    last-resort fallback is local to grading: with no corpus on disk at all we
    grade the vault ROOT, which walks ``.claude/commands/``, ``CLAUDE.md``,
    ``README.md``, ``*.spec.md`` and ``.venv/`` as if they were notes — that is
    what pushed the flag/notes ratio past ``fail_threshold`` on every real
    vault on 2026-09-01.
    """
    return existing_corpus_dir(vault) or vault


def _write_verify_report(
    vault: Path, report: dict[str, Any], run_dir: Path | None = None
) -> Path | None:
    """Persist ``VerifyResult.report`` as ``<run_dir>/verify-report.json``.

    ``report['results']`` is the ONLY carrier of per-note flag detail, and
    ``_drive_verify`` used to drop it on the floor: a FAIL was persisted as
    ``{"verdict": "FAIL", "notes_checked": N}``, which cannot tell one
    malformed note apart from 9066 flags over 840 notes (issue #218).

    Spec 015f § Path conventions promised ``_pipeline/logs/verify-<date>``;
    nothing wrote it and ``_common.logs_dir()`` had no callers at all. Spec
    080 supersedes that promise for the runner: the report belongs with the
    rest of the run's record, at ``<run_dir>/verify-report.json``, in JSON
    because it is machine-read (by the phase summary, and by the report agent)
    rather than skimmed. The timestamped flat path stays as the fallback for a
    dispatch with no run directory.

    A re-driven verify suffixes rather than overwrites (FR-005): a weekly run
    re-driven after a fix must not erase the evidence of the failure it
    fixed.

    Returns the path written, or ``None`` — an unwritable log directory
    downgrades the diagnosis, it does not fail the phase.
    """
    from ..processors._common import logs_dir
    from .atomic_write import write_json

    if run_dir is not None:
        dest = run_receipt.stage_path(run_dir, ".", "verify-report", ".json")
    else:
        dest = logs_dir(vault) / f"verify-{datetime.now(tz=UTC):%Y-%m-%dT%H%M%SZ}.json"
    try:
        write_json(dest, report)
    except OSError as exc:
        _LOG.warning("  WARN: could not write the verify report to %s: %s", dest, exc)
        return None
    return dest


def _vault_declarations(vault: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """``(processors, note_types)`` as the vault's own spec declares them.

    ``verify.py``'s docstring has promised since the processors moved into the
    framework that ``processors.verify.fail_threshold`` is "passed down from
    spec's ``processors.verify``" — and the pipeline path, the one caller that
    could pass it, never did (issue #228). The section is already parsed into
    ``_pipeline/spec-parse.json``, which ``_corpus_dir`` reads two lines later.

    An unreadable or absent spec-parse is not a verify failure: the processor's
    own defaults grade the vault, exactly as they did before. Returns empty
    containers rather than raising.
    """
    doc, error = _read_json(vault / "_pipeline" / "spec-parse.json")
    if error is not None or doc is None:
        return {}, []
    processors = doc.get("processors")
    note_types = doc.get("note_types")
    return (
        processors if isinstance(processors, dict) else {},
        [nt for nt in (note_types or []) if isinstance(nt, dict)],
    )


def _drive_verify(vault: Path, state: dict[str, Any], *, quiet: bool) -> int:
    """Verify phase: run the verify processor."""
    phase = "verify"
    started = _now_utc()
    _set_phase(state, phase, phase_status=IN_PROGRESS, started_at=started, errors=[])
    _save_state(vault, state)

    run_dir = _run_dir(vault, state)
    errors: list[str] = []
    verdict = ""
    notes_checked = 0
    summary: dict[str, Any] = {"verdict": "", "notes_checked": 0}

    try:
        from ..processors.verify import verify

        spec_processors, spec_note_types = _vault_declarations(vault)
        # A phase named "verify" REPORTS; it does not mutate the corpus.
        # Auto-fix stays available through the processor CLI, where the
        # operator opts in explicitly — and stays an EXPLICIT argument here so
        # that the no-mutation guarantee wins the processor's
        # explicit > spec-config > default ladder against a spec that asks for
        # auto_fix.
        result = verify(
            _corpus_dir(vault),
            auto_fix=False,
            spec_processors=spec_processors,
            spec_note_types=spec_note_types,
            note_templates_dir=vault / "_templates",
        )
        verdict = result.verdict
        notes_checked = result.notes_checked
        errors.extend(result.errors)
        report_path = _write_verify_report(vault, result.report, run_dir)
        # Everything that produced the verdict, so a FAIL is diagnosable from
        # `pipeline status` without re-running the processor (issue #218).
        summary = {
            "verdict": verdict,
            "notes_checked": notes_checked,
            "structural_flags": result.structural_flags,
            "content_flags": result.content_flags,
            "tooling_flags": result.tooling_flags,
            "malformed_count": result.malformed_count,
            "auto_fixes_applied": result.auto_fixes_applied,
            "fail_threshold": result.fail_threshold,
            "flags_by_check": result.report.get("flags_by_check", {}),
            "report_path": str(report_path) if report_path else None,
        }
        if not quiet:
            _LOG.info(
                f"  {notes_checked} notes spot-checked; "
                f"verdict: {verdict}; "
                f"{result.structural_flags} flag(s) "
                f"({result.content_flags} content, {result.tooling_flags} tooling)"
            )
    except Exception as exc:
        errors.append(f"verify processor error: {exc}")
        verdict = "ERROR"
        summary = {"verdict": verdict, "notes_checked": notes_checked}

    final_status = DONE if verdict in ("PASS", "WARN") else FAILED
    return _close_phase(
        vault,
        state,
        phase,
        phase_status=final_status,
        summary=summary,
        errors=errors,
    )


def _drive_report(vault: Path, state: dict[str, Any], *, quiet: bool) -> int:
    """Report phase: invoke the report agent via agent_call.py."""
    phase = "report"
    started = _now_utc()
    _set_phase(state, phase, phase_status=IN_PROGRESS, started_at=started, errors=[])
    _save_state(vault, state)

    run_dir = _run_dir(vault, state)
    errors: list[str] = []
    summary: dict[str, Any] = {}
    try:
        prompt_file = _render_stage_prompt(vault, "report", run_dir)
        outcome = _call_agent(
            vault,
            stage="report",
            quiet=quiet,
            prompt_file=prompt_file,
            run_dir=run_dir,
        )
        errors.extend(_agent_phase_errors("report", outcome))
        if outcome.log_path is not None:
            summary["agent_log"] = str(outcome.log_path)
        if outcome.cost_sidecar is not None:
            summary["cost_sidecar"] = str(outcome.cost_sidecar)
        if prompt_file is not None:
            summary["prompt"] = str(prompt_file)
        if not errors:
            # Exit 0 is a claim, not evidence. The phase is done only if the
            # artifact the NEXT phase reads is actually there (issue #222).
            artifact_errors, artifact_summary = _check_report_artifact(vault)
            errors.extend(artifact_errors)
            summary.update(artifact_summary)
    except Exception as exc:
        errors.append(f"report agent error: {exc}")

    final_status = DONE if not errors else FAILED
    return _close_phase(
        vault,
        state,
        phase,
        phase_status=final_status,
        summary=summary,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Agent call helper
# ---------------------------------------------------------------------------


def _agent_call_script(vault: Path) -> Path | None:
    """Locate scripts/agent_call.py relative to the vault or framework."""
    # 1. Prefer <vault>/scripts/agent_call.py (generated vaults).
    candidate = vault / "scripts" / "agent_call.py"
    if candidate.exists():
        return candidate
    # 2. Fall back to the framework's own scripts/ directory.
    framework_scripts = (
        Path(__file__).resolve().parents[3] / "scripts" / "agent_call.py"
    )
    if framework_scripts.exists():
        return framework_scripts
    return None


@dataclass(frozen=True)
class AgentCallOutcome:
    """What a dispatch to ``agent_call.py`` actually produced.

    ``_call_agent`` used to return a bare ``int``. Under ``quiet`` — the mode
    every unattended run uses — it ran ``capture_output=True`` and then threw
    ``result.stdout`` and ``result.stderr`` away, so the agent's own account of
    why it exited 3 was unrecoverable (issue #220). A phase that fails owes the
    operator that account; an ``int`` cannot carry it.
    """

    returncode: int
    output_tail: str = ""
    log_path: Path | None = None
    timed_out: bool = False
    timeout_s: float | None = None
    #: The sidecar this dispatch ASKED ``agent_call.py`` to write (FR-010).
    #: Carrying the expectation, not the finding, is what lets a phase
    #: distinguish "no sidecar was requested" from "one was requested and
    #: never arrived" — the second is a WARNING and a counted miss.
    cost_sidecar: Path | None = None


# Outer bound on one agent dispatch. This is NOT a second opinion about how
# long an LLM stage should take — ``agent_call.py`` already enforces the
# operator's ``timeout_s`` on the call itself. It is the backstop for that
# inner timeout failing to take effect, which is exactly what the 2026-05-31
# postmortem records: the 60-minute note_writer timeout fired correctly and
# ``agent_call.py`` stayed alive for another 3h 17m because codex's
# grandchildren never released the stdout pipe. So the runner's bound is the
# inner one plus a grace margin, and it kills the whole process GROUP.
_DEFAULT_AGENT_TIMEOUT_S = 3600.0
_AGENT_TIMEOUT_GRACE_S = 300.0
_AGENT_TIMEOUT_ENV = "RF_PIPELINE_AGENT_TIMEOUT_S"
# ``timeout(1)``'s exit code for "the command did not finish in time".
_AGENT_TIMEOUT_RC = 124
_AGENT_TAIL_LINES = 20
_AGENT_TAIL_CHARS = 2000
_AGENT_DRAIN_TIMEOUT_S = 5.0


def _settings_stage_timeout_s(vault: Path, stage: str) -> float | None:
    """``stages.<stage>.timeout_s``, else ``default_executor.timeout_s``.

    Read straight from the YAML rather than through
    :func:`pipeline.settings.load_vault_settings`, deliberately. That loader
    validates the whole file and raises when ``pipeline.max_cycles`` is absent
    or malformed — none of which has anything to do with how long this runner
    should wait for a subprocess. A settings file this runner cannot fully
    understand must still yield a bound, and the two keys read here are the
    same ones ``agent_call._resolve_executor`` resolves, with the same
    stage-beats-default precedence.
    """
    settings_path = vault / "settings.yaml"
    if not settings_path.is_file():
        return None
    try:
        import yaml

        raw = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None

    for section, key in (("stages", stage), ("default_executor", None)):
        block = raw.get(section)
        if not isinstance(block, dict):
            continue
        if key is not None:
            block = block.get(key)
            if not isinstance(block, dict):
                continue
        value = block.get("timeout_s")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if value > 0:
            return float(value)
    return None


def _agent_timeout_s(vault: Path, stage: str) -> float | None:
    """Wall-clock bound for one dispatch, or ``None`` for "no bound".

    Precedence: ``RF_PIPELINE_AGENT_TIMEOUT_S`` → the vault's own resolved
    stage timeout plus :data:`_AGENT_TIMEOUT_GRACE_S` → the default. The env
    var accepts ``0`` (or any non-positive value) as a deliberate opt-out, for
    an operator babysitting a long interactive run; an *undeclared* absence of
    a bound is what this issue is about, a declared one is their call.
    """
    raw = os.environ.get(_AGENT_TIMEOUT_ENV)
    if raw is not None and raw.strip():
        try:
            override = float(raw)
        except ValueError:
            _LOG.warning(
                "  WARN: %s=%r is not a number; falling back to the vault's "
                "own stage timeout.",
                _AGENT_TIMEOUT_ENV,
                raw,
            )
        else:
            return None if override <= 0 else override

    inner = _settings_stage_timeout_s(vault, stage) or _DEFAULT_AGENT_TIMEOUT_S
    return inner + _AGENT_TIMEOUT_GRACE_S


def _agent_log_path(vault: Path, stage: str, run_dir: Path | None) -> Path:
    """Where this dispatch's merged output goes.

    Under the run directory since spec 080 (FR-003): an operator opening one
    place after an unattended night should not also have to know that the
    logs are timestamped siblings under ``_pipeline/logs/``. A stage
    re-driven inside one run suffixes rather than overwrites (FR-005).

    Falls back to the old flat, timestamped path when there is no run
    directory — a bare ``pipeline <vault> scout`` against a vault with no
    state file still has to put its output somewhere.
    """
    if run_dir is not None:
        return run_receipt.stage_path(run_dir, "logs", stage, ".log")
    from ..processors._common import logs_dir

    stamp = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H%M%SZ")
    return logs_dir(vault) / f"{stage}-{stamp}.log"


def _render_tail(lines: list[str]) -> str:
    """The last few lines of the agent's output, capped for a state file."""
    text = "\n".join(lines).strip()
    if len(text) > _AGENT_TAIL_CHARS:
        text = "..." + text[-_AGENT_TAIL_CHARS:]
    return text


def _dispatch_agent(
    cmd: list[str],
    *,
    vault: Path,
    stage: str,
    quiet: bool,
    run_dir: Path | None = None,
) -> AgentCallOutcome:
    """Run ``cmd`` bounded, process-group-isolated, and tee'd to a log.

    Three properties the old ``subprocess.run(cmd)`` did not have:

    * **Bounded.** ``proc.wait(timeout=...)`` in the main thread, with the
      output drained by a reader thread. Draining in the main thread and
      consulting the clock afterwards is the trap ``agent_call.py`` documents
      at its own read loop: a subprocess that emits one line an hour keeps the
      loop alive and the timeout is never reached.
    * **Isolated.** ``popen_session`` makes the child its own process-group
      leader, so ``terminate_process_tree`` on expiry reaches the sandbox and
      MCP grandchildren that would otherwise hold the pipe open — the
      2026-05-31 zombie-pipe scenario.
    * **Recorded.** stderr is merged into stdout and both are written to
      ``_pipeline/logs/<stage>-<ts>.log``; the tail comes back on the outcome
      for the phase's ``errors``. Merging is deliberate: two unread pipes
      deadlock, one stream cannot, and the agent's failure is at the END of
      what it said, which is precisely what the tail keeps. The full stream is
      in the log either way.
    """
    timeout_s = _agent_timeout_s(vault, stage)
    log_path: Path | None = _agent_log_path(vault, stage, run_dir)
    handle = None
    try:
        assert log_path is not None
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = log_path.open("w", encoding="utf-8", buffering=1)
    except OSError as exc:
        _LOG.warning("  WARN: could not open the %s agent log: %s", stage, exc)
        log_path = None

    tail: deque[str] = deque(maxlen=_AGENT_TAIL_LINES)

    proc = popen_session(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    def _drain() -> None:
        if proc.stdout is None:  # pragma: no cover — Popen guarantees it
            return
        for line in proc.stdout:
            tail.append(line.rstrip("\n"))
            if handle is not None:
                try:
                    handle.write(line)
                except (OSError, ValueError):
                    pass
            if not quiet:
                try:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                except (OSError, ValueError):
                    pass

    reader = threading.Thread(target=_drain, daemon=True, name=f"agent-{stage}")
    reader.start()

    timed_out = False
    try:
        returncode = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        terminate_process_tree(proc)
        returncode = _AGENT_TIMEOUT_RC
    except BaseException:
        # Ctrl+C, or anything else that unwinds past us: never leave the
        # agent (or its grandchildren) running on the operator's machine.
        terminate_process_tree(proc)
        raise
    else:
        # A clean exit says nothing about what the agent forked. Whatever is
        # still in its process group would run on, holding the pipe the
        # reader below is waiting on. An empty group makes this a no-op.
        terminate_process_tree(proc)
    finally:
        reader.join(timeout=_AGENT_DRAIN_TIMEOUT_S)
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass

    return AgentCallOutcome(
        returncode=returncode,
        output_tail=_render_tail(list(tail)),
        log_path=log_path,
        timed_out=timed_out,
        timeout_s=timeout_s,
    )


def _call_agent(
    vault: Path,
    *,
    stage: str,
    quiet: bool,
    prompt_file: Path | None,
    run_dir: Path | None = None,
) -> AgentCallOutcome:
    """Invoke agent_call.py for a given stage.

    ``prompt_file`` must point at an already-rendered prompt on disk.
    agent_call.py falls back to reading stdin when no ``--prompt-file`` is
    given; ``subprocess.run(cmd)`` here doesn't pipe anything in, so the
    inner (non-interactive) ``claude --print`` call would receive an empty
    prompt and fail with a message that gives no clue this is a pipeline
    wiring gap ("Input must be provided either through stdin or as a
    prompt argument when using --print"). Failing fast here instead, with
    an explicit reason, is strictly better than forwarding that empty call.
    """
    script = _agent_call_script(vault)
    if script is None:
        # No agent ran, so this is not an exit 0: reporting one let the
        # artifact check pass on a previous run's file still on disk.
        _LOG.error(
            "  ERROR: agent_call.py not found (looked in %s and the framework's "
            "scripts/); the %s agent was not dispatched.",
            vault / "scripts",
            stage,
        )
        return AgentCallOutcome(returncode=2)

    if prompt_file is None:
        relative_source = _STAGE_PROMPT_SOURCES.get(stage)
        if relative_source is None:
            _LOG.error(
                "  ERROR: no rendered prompt available for stage '%s'; it has "
                "no entry in _STAGE_PROMPT_SOURCES, so there is nothing to "
                "send the agent. Skipping.",
                stage,
            )
        else:
            _LOG.error(
                "  ERROR: no rendered prompt available for stage '%s'. Either "
                "`%s` is missing from this vault (run `research-framework "
                "generate` for it first) or it failed to render. Skipping.",
                stage,
                relative_source,
            )
        return AgentCallOutcome(returncode=2)

    cmd = [
        sys.executable,
        str(script),
        "--stage",
        stage,
        "--vault",
        str(vault),
        "--prompt-file",
        str(prompt_file),
    ]
    # FR-010: nothing the runner dispatches may spend money without a record.
    # ``--output-file`` is deliberately NOT requested (FR-011): the merged log
    # already holds the agent's stdout, and ``--output-file`` is written only
    # on exit 0 — it would be absent in exactly the runs an operator needs to
    # read.
    sidecar: Path | None = None
    if run_dir is not None:
        sidecar = run_receipt.stage_path(run_dir, "agent-calls", stage, ".json")
        cmd += ["--cost-sidecar", str(sidecar)]
    outcome = _dispatch_agent(
        cmd, vault=vault, stage=stage, quiet=quiet, run_dir=run_dir
    )
    return dataclasses.replace(outcome, cost_sidecar=sidecar)


def _agent_phase_errors(stage: str, outcome: AgentCallOutcome) -> list[str]:
    """The phase-level reasons an agent dispatch failed.

    Empty on success — a phase that reports nothing is a phase that worked.
    """
    if outcome.returncode == 0:
        return []
    if outcome.timed_out:
        errors = [
            f"{stage} agent timed out after {outcome.timeout_s:.0f}s; its "
            f"process group was terminated"
        ]
    else:
        errors = [f"{stage} agent exited with code {outcome.returncode}"]
    if outcome.output_tail:
        errors.append(f"last output from the {stage} agent:\n{outcome.output_tail}")
    return errors


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_collect(vault: Path, *, quiet: bool = False) -> int:
    """Run the collect phase only."""
    state = _load_state(vault)
    _run_dir(vault, state, verb="collect")
    if not quiet:
        _LOG.info("[collect] collecting raw items...")
    return _drive_collect(vault, state, quiet=quiet)


def run_extract(vault: Path, *, quiet: bool = False) -> int:
    """Run the extract phase only."""
    state = _load_state(vault)
    _run_dir(vault, state, verb="extract")
    if not quiet:
        _LOG.info("[extract] extracting and synthesising context tree...")
    return _drive_extract(vault, state, quiet=quiet)


def run_scout(vault: Path, *, quiet: bool = False) -> int:
    """Run the scout phase only."""
    state = _load_state(vault)
    _run_dir(vault, state, verb="scout")
    if not quiet:
        _LOG.info("[scout] running scout agent...")
    return _drive_scout(vault, state, quiet=quiet)


def run_full(
    vault: Path,
    *,
    quiet: bool = False,
) -> int:
    """Run collect → extract → scout, then STOP at triage.

    Returns exit code (0 = all phases OK, non-zero = at least one failed).

    Took a ``budget_cap`` until issue #232. Nothing in this module ever read
    it, and no phase below writes a cost sidecar (#220/#221), so there is no
    spend record a cap could be checked against — the keyword only made the
    CLI's claim that it was "passed to agent invocations" look plausible. The
    CLI now refuses the flag outright; when the phases start emitting
    sidecars, wire it here rather than re-adding a parameter nothing reads.
    """
    now = _now_utc()
    # FR-002: ``_make_run_id`` is minute-granular. Two ``full`` runs inside one
    # minute used to share an id, and the second silently overwrote the first's
    # state because there was nothing else to collide with (D1). The run
    # directory is now that something.
    run_id = run_receipt.allocate_run_id(vault, _make_run_id())
    state = _blank_state(run_id, now)
    state["phases"]["triage"]["status"] = PENDING
    _save_state(vault, state)

    # FR-001: allocated before the first phase runs, so every phase below has
    # somewhere to put its log, its prompt and its sidecar.
    run_dir = _run_dir(vault, state, verb="full")
    _write_receipt(vault, state)

    if not quiet:
        _LOG.info(f"Pipeline run {run_id} started")
        if run_dir is not None:
            _LOG.info(f"  This run's record: {run_dir}")

    rc_total = 0

    # [1/3] Collect
    if not quiet:
        _LOG.info("[1/3] collect ...")
    rc = _drive_collect(vault, state, quiet=quiet)
    rc_total = max(rc_total, rc)

    # [2/3] Extract
    if not quiet:
        _LOG.info("[2/3] extract ...")
    rc = _drive_extract(vault, state, quiet=quiet)
    rc_total = max(rc_total, rc)

    # [3/3] Scout
    if not quiet:
        _LOG.info("[3/3] scout ...")
    rc = _drive_scout(vault, state, quiet=quiet)
    rc_total = max(rc_total, rc)

    # Mark triage as waiting (human must triage).
    _set_phase(state, "triage", phase_status=WAITING, started_at=_now_utc())
    _save_state(vault, state)
    _write_receipt(vault, state)

    if not quiet:
        _announce_triage_pause(vault)

    return rc_total


def _triage_queue_size(vault: Path) -> int | None:
    """How many topics ``resume`` would research, or ``None`` if unreadable."""
    try:
        data = json.loads(
            (vault / "_pipeline" / "scout-report.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None
    found = data.get("topics_found") if isinstance(data, dict) else None
    new = found.get("new") if isinstance(found, dict) else None
    return len(new) if isinstance(new, list) else None


def _announce_triage_pause(vault: Path) -> None:
    """Name the artifact triage actually happens in (issue #240).

    This used to read "Open the radar, approve/defer queue items". A
    ``pipeline`` run never writes a Topic Radar — that is a cycle-orchestrator
    artifact, and ``_STAGE_PROMPT_SOURCES``' comment above deliberately steers
    the research stage away from it — so the pipeline's one human checkpoint
    sent the operator looking for a file that does not exist, with no
    documented protocol anywhere in the repo.

    What it can honestly say today is where the queue is, how big it is, and
    that ``resume`` takes all of it. A real approve/defer gate (a generated
    triage artifact, a ``triage`` verb, ``resume`` refusing an empty approval
    set) changes the contract across three stages and wants its own spec; the
    count is here because "107 topics in one single-shot pass" is the thing an
    operator needs to see before it happens, not after.
    """
    report = vault / "_pipeline" / "scout-report.json"
    size = _triage_queue_size(vault)
    _LOG.info("")
    _LOG.info("HUMAN TRIAGE REQUIRED")
    if size is None:
        _LOG.info(
            "  The research queue is `topics_found.new` in %s — which this run "
            "left missing or unreadable. Check the scout phase above before "
            "resuming; there is nothing to research yet.",
            report,
        )
    else:
        _LOG.info(
            "  The research queue is `topics_found.new` in %s — %d topic(s).",
            report,
            size,
        )
    _LOG.info(
        "  `resume` researches every entry in that list, in one pass, with no "
        "further prompt: there is no approve/defer gate yet (issue #240). To "
        "defer a topic, delete its entry from `topics_found.new` before "
        "resuming — git keeps the original if you want it back."
    )
    _LOG.info("  Then:")
    _LOG.info("    research-framework pipeline %s resume", vault)


def run_resume(vault: Path, *, quiet: bool = False) -> int:
    """Resume from after triage: run research.

    Marks triage as done, then runs the research phase.
    """
    state = _load_state(vault)
    _run_dir(vault, state, verb="resume")

    triage_status = state["phases"]["triage"]["status"]
    if triage_status not in (WAITING, DONE, PENDING):
        if not quiet:
            _LOG.warning(f"WARN: triage status is '{triage_status}'; proceeding anyway")

    # Flip triage to done.
    _set_phase(
        state,
        "triage",
        phase_status=DONE,
        finished_at=_now_utc(),
    )
    _save_state(vault, state)

    if not quiet:
        _LOG.info("[4/6] research ...")
    rc = _drive_research(vault, state, quiet=quiet)

    # Issue #285: `resume` runs research ONLY (issue #245 split it from verify
    # + report on purpose — see `run_finish`), but until now it ended here
    # with no printed guidance. The only "then:" instruction anywhere in this
    # module is `_announce_triage_pause`'s, and it names `resume` — so an
    # operator following the printed trail from `full` never learns that a
    # second verb, `finish`, exists at all.
    if not quiet and rc == 0:
        _LOG.info("")
        _LOG.info("Research complete. Then:")
        _LOG.info("    research-framework pipeline %s finish", vault)

    return rc


def run_finish(vault: Path, *, quiet: bool = False) -> int:
    """Run verify + report. Never runs research (issue #245: it does not
    "skip research if the queue is empty" — it does not run research at
    all, empty queue or not)."""
    state = _load_state(vault)
    _run_dir(vault, state, verb="finish")

    rc_total = 0

    if not quiet:
        _LOG.info("[5/6] verify ...")
    rc = _drive_verify(vault, state, quiet=quiet)
    rc_total = max(rc_total, rc)

    if not quiet:
        _LOG.info("[6/6] report ...")
    rc = _drive_report(vault, state, quiet=quiet)
    rc_total = max(rc_total, rc)

    if not quiet and rc_total == 0:
        _LOG.info("")
        _LOG.info("Run complete.")

    return rc_total


def _parse_state_ts(value: Any) -> datetime | None:
    """Parse a ``_now_utc()``-formatted timestamp; ``None`` on anything else."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _phase_duration_s(started_at: Any, finished_at: Any) -> float | None:
    """Seconds between a phase's ``started_at`` and ``finished_at``.

    ``None`` when either timestamp is missing or unparseable — issue #245:
    a phase that never finished (still ``in_progress``, or a process that
    was killed before writing ``finished_at``) has no duration to report,
    and that must be visible as "unknown", not a wrong number.
    """
    start = _parse_state_ts(started_at)
    end = _parse_state_ts(finished_at)
    if start is None or end is None:
        return None
    return max(0.0, (end - start).total_seconds())


def status(vault: Path) -> dict[str, Any]:
    """Read pipeline-state.json and return a structured summary dict.

    Issue #245: the one command an operator uses to ask "why did this run
    fail" must surface everything ``pipeline-state.json`` recorded about
    it — the persisted ``errors[]`` (already read here, but historically
    dropped by the TTY renderer downstream) and each phase's wall-clock
    duration, derived from ``started_at``/``finished_at`` rather than
    stored twice. ``summary`` is forwarded unchanged, which already
    carries whatever a given phase records there (e.g. #318 added
    ``agent_log`` / ``report_path`` to several phases) without this
    function needing to know each field by name.
    """
    state_path = vault / STATE_FILE
    if not state_path.exists():
        # FR-019: `status` never fails for want of a receipt. Without a state
        # file there is no run to have one, so the spec-080 keys are present
        # and null rather than absent — a consumer (#247's fleet view next)
        # reads one shape, not two.
        return {
            "run_id": None,
            "started_at": None,
            "framework_version": FRAMEWORK_VERSION,
            "run_dir": None,
            "receipt": None,
            "cost_total_usd": None,
            "cost_is_lower_bound": False,
            "phases": {
                phase: {
                    "status": PENDING,
                    "started_at": None,
                    "finished_at": None,
                    "duration_s": None,
                    "cost_usd": None,
                    "cost_source": None,
                    "summary": None,
                    "errors": [],
                }
                for phase in PHASES
            },
        }

    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}
    if not isinstance(raw, dict):
        return {"error": f"{state_path} is not a JSON object"}

    # Build a concise summary.
    run_id = raw.get("run_id")
    run_dir = (
        run_receipt.run_dir_for(vault, run_id) if isinstance(run_id, str) else None
    )
    receipt = run_dir / "run.json" if run_dir is not None else None

    out: dict[str, Any] = {
        "run_id": run_id,
        "started_at": raw.get("started_at"),
        "framework_version": raw.get("framework_version", FRAMEWORK_VERSION),
        "run_dir": str(run_dir) if run_dir is not None and run_dir.exists() else None,
        "receipt": str(receipt) if receipt is not None and receipt.exists() else None,
        "cost_total_usd": None,
        "cost_is_lower_bound": False,
        "phases": {},
    }
    total: float | None = None
    missing = 0
    for phase in PHASES:
        rec = raw.get("phases", {}).get(phase, {})
        started_at = rec.get("started_at")
        finished_at = rec.get("finished_at")
        summary = rec.get("summary")
        summary = summary if isinstance(summary, dict) else None
        cost = (summary or {}).get("cost_usd")
        cost = float(cost) if isinstance(cost, int | float) else None
        if (summary or {}).get("cost_sidecar") is not None:
            if cost is None:
                missing += 1
            else:
                total = cost if total is None else total + cost
        out["phases"][phase] = {
            "status": rec.get("status", PENDING),
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_s": _phase_duration_s(started_at, finished_at),
            "cost_usd": cost,
            "cost_source": (summary or {}).get("cost_source"),
            "summary": summary,
            "errors": rec.get("errors", []),
        }
    out["cost_total_usd"] = round(total, 4) if total is not None else None
    # FR-013: a total computed with any sidecar missing is a floor, and every
    # rendering of it has to say so rather than show a number that looks exact.
    out["cost_is_lower_bound"] = missing > 0
    return out
