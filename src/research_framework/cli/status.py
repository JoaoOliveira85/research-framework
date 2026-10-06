"""``vault status`` read-only CLI verb (spec 048 v1.1 FR-009/010/011)."""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from ..pipeline.cycle_state import CycleState
from ..pipeline.cycle_state import read as read_cycle_state

_LOG = logging.getLogger(__name__)

_SUMMARY_RE = re.compile(r"^cycle-(\d+)-summary\.md$")


def _format_duration_short(seconds: int | None) -> str:
    if seconds is None:
        return "n/a"
    total = max(0, int(seconds))
    if total >= 3600:
        hours = total // 3600
        minutes = (total % 3600) // 60
        return f"{hours}h {minutes:02d}m"
    minutes = total // 60
    secs = total % 60
    return f"{minutes}m {secs:02d}s"


def _tail_last_line(path: Path, *, max_bytes: int = 8192) -> str | None:
    if not path.is_file():
        return None
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            chunk = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    lines = [line for line in chunk.splitlines() if line.strip()]
    return lines[-1] if lines else None


def _elapsed_since(iso_ts: str | None) -> int | None:
    if not iso_ts:
        return None
    try:
        start = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return max(0, int((datetime.now(UTC) - start).total_seconds()))
    except (TypeError, ValueError, OverflowError):
        return None


def _find_last_summary(cycles_dir: Path) -> tuple[int, Path] | None:
    if not cycles_dir.is_dir():
        return None
    best: tuple[int, Path] | None = None
    for entry in cycles_dir.iterdir():
        if not entry.is_file():
            continue
        match = _SUMMARY_RE.match(entry.name)
        if not match:
            continue
        num = int(match.group(1))
        if best is None or num > best[0]:
            best = (num, entry)
    return best


def _read_first_line(path: Path) -> str | None:
    try:
        with path.open(encoding="utf-8") as handle:
            return handle.readline().rstrip("\n")
    except OSError:
        return None


def _deferred_warnings(vault_dir: Path, cycle_num: int) -> list[str]:
    research_path = (
        vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle_num:03d}-research.json"
    )
    warnings: list[str] = []
    if research_path.is_file():
        try:
            data = json.loads(research_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        for item in data.get("capture_failures") or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            reason = str(item.get("reason") or item.get("error") or "unknown")
            host = url.split("/")[2] if "://" in url else url or "(no url)"
            warnings.append(f"{host} capture: {reason}")
    warnings.extend(_stagnant_warnings(vault_dir, cycle_num))
    return warnings


def _stagnant_warnings(vault_dir: Path, cycle_num: int) -> list[str]:
    """Spec 069 FR3: surface the stagnant-source WARNs the cycle quality report
    recorded, so ``./vault status`` agrees with the quality report (contract C3-a).
    """
    from ..pipeline.stagnant_sources import STAGNANT_PREFIX

    report_path = (
        vault_dir
        / "_pipeline"
        / "cycles"
        / f"cycle-{cycle_num:03d}-quality-report.json"
    )
    if not report_path.is_file():
        return []
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [
        str(entry)
        for entry in (data.get("degraded_sources") or [])
        if isinstance(entry, str) and entry.startswith(STAGNANT_PREFIX)
    ]


def render_active(
    state: CycleState | None,
    last_log_line: str | None,
    *,
    elapsed_s: int | None = None,
    cycle_num: int | None = None,
    cycles_budgeted: int | None = None,
) -> str:
    """Plain-text ACTIVE block (contract §3 — five data points)."""
    if state is None:
        cyc = cycle_num or 1
        elapsed = _format_duration_short(elapsed_s)
        lines = [f"CYCLE {cyc} — (starting)", f"  elapsed:  {elapsed}"]
        if last_log_line:
            lines.append(f"  last log: {last_log_line}")
        return "\n".join(lines)

    cycle = state.in_progress_cycle or 0
    budgeted = state.cycles_budgeted
    stage = state.stage or "?"
    if elapsed_s is None:
        elapsed_s = _elapsed_since(state.cycle_started_at)
    elapsed = _format_duration_short(elapsed_s)

    if budgeted is not None:
        headline = f"CYCLE {cycle} of {budgeted} — stage: {stage}"
    else:
        headline = f"CYCLE {cycle} — stage: {stage}"

    snap = state.budget_snapshot
    if snap and (
        snap.wall_remaining_s is not None
        or snap.dollar_remaining is not None
        or snap.dollar_budget is not None
    ):
        wall = _format_duration_short(snap.wall_remaining_s)
        dollar_rem = (
            f"${snap.dollar_remaining:.2f}"
            if snap.dollar_remaining is not None
            else "n/a"
        )
        dollar_bud = (
            f"${snap.dollar_budget:.2f}" if snap.dollar_budget is not None else "n/a"
        )
        budget_line = f"  budget:   {wall} wall remaining · {dollar_rem} of {dollar_bud} remaining"
    else:
        budget_line = "  budget:   n/a"

    lines = [
        headline,
        f"  elapsed:  {elapsed}",
        budget_line,
    ]
    if last_log_line:
        lines.append(f"  last log: {last_log_line}")
    return "\n".join(lines)


def _pipeline_status(vault_dir: Path) -> dict[str, object] | None:
    """Read `_pipeline/pipeline-state.json` (the `pipeline` subcommand's
    state, distinct from this verb's own `_pipeline/state.json` cycle
    state), if it exists.

    Issue #245: the top-level `status` verb is wired to the single-cycle
    world (`cycle` / `resume`) and previously had no idea a `pipeline run`
    (collect→extract→scout→triage→research→verify→report) had ever
    happened in this vault — so a vault driven entirely through `pipeline`
    reported "(no cycles yet)" no matter how many runs it had, or how they
    failed. Delegates to `pipeline.runner.status`, the one place that
    already knows this file's shape, rather than re-parsing it here.
    """
    if not (vault_dir / "_pipeline" / "pipeline-state.json").is_file():
        return None
    from ..pipeline.runner import status as _pipeline_runner_status

    return _pipeline_runner_status(vault_dir)


def _render_pipeline_status_block(pipeline_status: dict[str, object]) -> str:
    run_id = pipeline_status.get("run_id") or "none"
    started = pipeline_status.get("started_at") or "—"
    lines = [f"(no active cycle — pipeline run {run_id}, started {started})"]
    phases = pipeline_status.get("phases")
    if isinstance(phases, dict):
        for phase, rec in phases.items():
            if not isinstance(rec, dict):
                continue
            lines.append(f"  {phase}: {rec.get('status', 'pending')}")
            for err in rec.get("errors") or []:
                lines.append(f"    ! {err}")
    return "\n".join(lines)


def render_inactive(vault_dir: Path) -> str:
    """Plain-text NO-active-cycle block (contract §3 FR-011)."""
    pipeline = vault_dir / "_pipeline"
    if not pipeline.is_dir():
        return "(no cycles yet)"

    cycles_dir = pipeline / "cycles"
    last = _find_last_summary(cycles_dir)
    if last is None:
        # Issue #245: before falling back to the cycle-blind "(no cycles
        # yet)", check whether a `pipeline run` recorded anything here.
        pipeline_status = _pipeline_status(vault_dir)
        if pipeline_status is not None:
            return _render_pipeline_status_block(pipeline_status)
        return "(no cycles yet)"

    cycle_num, summary_path = last
    header = _read_first_line(summary_path) or ""
    lines = ["(no active cycle)", header]

    if ": PASS" in header:
        try:
            mtime = datetime.fromtimestamp(summary_path.stat().st_mtime, tz=UTC)
            days = max(0, (datetime.now(UTC) - mtime).days)
            lines.append(f"  last successful cycle: {days} days ago")
        except OSError:
            pass

    deferred = _deferred_warnings(vault_dir, cycle_num)
    if deferred:
        preview = deferred[0]
        lines.append(f"  deferred warnings: {len(deferred)} ({preview})")
    return "\n".join(lines)


def _coverage_summary(vault_dir: Path) -> dict[str, object] | None:
    """Recomputed coverage for the status JSON (spec 068 FR4).

    Read-only: derives ``met_count`` from disk via the same
    :func:`recompute_from_disk` the cycle-end + digest paths use (one source of
    truth, contract C3) but does NOT persist (status is a read-only verb).
    Returns ``None`` when the vault has no ``coverage-targets.json`` yet.
    """
    from ..pipeline.coverage import recompute_from_disk

    try:
        targets = recompute_from_disk(vault_dir, persist=False)
    except (FileNotFoundError, RuntimeError, OSError):
        return None
    categories: list[dict[str, object]] = []
    total_target = 0
    total_met_capped = 0
    for cat in targets.categories:
        target = max(0, int(cat.target_count))
        met = max(0, int(cat.met_count))
        fill = float(met) / float(target) if target else 0.0
        categories.append(
            {
                "name": cat.name,
                "met": met,
                "target": target,
                "fill_pct": min(1.0, max(0.0, fill)),
            }
        )
        total_target += target
        total_met_capped += min(met, target)
    overall = float(total_met_capped) / float(total_target) if total_target else 0.0
    return {
        "overall_fill_pct": min(1.0, max(0.0, overall)),
        "categories": categories,
    }


def build_status_json(vault_dir: Path) -> dict[str, object]:
    """Stable ``--json`` object for automation (contract §3)."""
    state = read_cycle_state(vault_dir)
    active = state is not None and state.active
    coverage = _coverage_summary(vault_dir)
    # Issue #245: always attach the `pipeline run` state (`None` when this
    # vault has never had one) — independent of the cycle-state `active`
    # branch below, since a `pipeline` run and a `cycle`/`resume` run are
    # tracked in two different files and either can exist without the other.
    pipeline_status = _pipeline_status(vault_dir)

    if active and state is not None:
        cycle = state.in_progress_cycle
        log_path = (
            vault_dir / "_pipeline" / "cycles" / f"cycle-{int(cycle):03d}" / "cycle.log"
        )
        last_log = _tail_last_line(log_path)
        elapsed_s = _elapsed_since(state.cycle_started_at)
        snap = state.budget_snapshot
        budget_obj: dict[str, float | int | None] | None = None
        if snap is not None:
            budget_obj = {
                "wall_remaining_s": snap.wall_remaining_s,
                "dollar_remaining": snap.dollar_remaining,
                "dollar_budget": snap.dollar_budget,
            }
        return {
            "active": True,
            "cycle": cycle,
            "cycles_budgeted": state.cycles_budgeted,
            "stage": state.stage,
            "elapsed_s": elapsed_s,
            "budget": budget_obj,
            "last_log_line": last_log,
            "last_cycle_header": None,
            "days_since_last_success": None,
            "deferred_warnings": [],
            "coverage": coverage,
            "pipeline": pipeline_status,
        }

    cycles_dir = vault_dir / "_pipeline" / "cycles"
    last = _find_last_summary(cycles_dir)
    header: str | None = None
    days_since: int | None = None
    deferred: list[str] = []
    if last is not None:
        cycle_num, summary_path = last
        header = _read_first_line(summary_path)
        deferred = _deferred_warnings(vault_dir, cycle_num)
        if header and ": PASS" in header:
            try:
                mtime = datetime.fromtimestamp(summary_path.stat().st_mtime, tz=UTC)
                days_since = max(0, (datetime.now(UTC) - mtime).days)
            except OSError:
                days_since = None

    return {
        "active": False,
        "cycle": None,
        "cycles_budgeted": None,
        "stage": None,
        "elapsed_s": None,
        "budget": None,
        "last_log_line": None,
        "last_cycle_header": header,
        "days_since_last_success": days_since,
        "deferred_warnings": deferred,
        "coverage": coverage,
        "pipeline": pipeline_status,
    }


def run_status(vault_dir: Path, *, json_output: bool = False) -> int:
    """Core status read — never raises (SC-001 fail-open)."""
    try:
        state = read_cycle_state(vault_dir)
        if state is not None and state.active:
            if json_output:
                print(json.dumps(build_status_json(vault_dir), indent=2))
                return 0
            cycle = state.in_progress_cycle or 1
            log_path = (
                vault_dir
                / "_pipeline"
                / "cycles"
                / f"cycle-{int(cycle):03d}"
                / "cycle.log"
            )
            last_log = _tail_last_line(log_path)
            elapsed_s = _elapsed_since(state.cycle_started_at)
            print(
                render_active(state, last_log, elapsed_s=elapsed_s),
            )
            return 0

        if json_output:
            print(json.dumps(build_status_json(vault_dir), indent=2))
            return 0
        print(render_inactive(vault_dir))
        return 0
    except Exception as exc:
        _LOG.warning("vault status failed: %s", exc)
        if json_output:
            print(json.dumps(build_status_json(vault_dir), indent=2))
        else:
            print(render_inactive(vault_dir))
        return 0


def cmd_status(args: argparse.Namespace) -> int:
    vault = getattr(args, "vault", None)
    if vault is None:
        print("error: --vault is required", file=sys.stderr)
        return 2
    vault_dir = Path(vault).expanduser().resolve()
    if not vault_dir.is_dir():
        print(f"error: vault not found: {vault_dir}", file=sys.stderr)
        return 2
    json_output = bool(getattr(args, "json", False))
    state_path = vault_dir / "_pipeline" / "state.json"
    if state_path.is_file():
        try:
            json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            _LOG.warning("vault status: corrupt state.json — treating as inactive")
    return run_status(vault_dir, json_output=json_output)


__all__ = [
    "build_status_json",
    "cmd_status",
    "render_active",
    "render_inactive",
    "run_status",
]
