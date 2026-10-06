"""Human-readable per-cycle summary.

Writes ``_pipeline/cycles/cycle-NNN-summary.md`` at the end of each cycle.
Drains the four artefacts the orchestrator already produces — the scout
report, the research report, the cycle quality report, and the per-cycle
skill-check sidecar — into a single Markdown page that fits on screen
without scrolling.

This exists because the v0.2.19 cycle output dumped raw JSON deltas
straight into the user's terminal, including eleven near-identical
``raw_capture.py exited 1 with network error`` lines per cycle. The
operator's actual question — "did this cycle achieve anything?" — was
buried under noise. The summary collapses repeats (e.g. capture failures
grouped by host) and surfaces the four signals that matter: notes
written/updated, gate verdicts, cost, and the exit reason.

The summary is best-effort: if any source JSON is missing or malformed
we still write the file with whatever sections we could fill, because a
partial summary is more useful than no summary when an early step has
already aborted the cycle.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

__all__ = ["health_header", "write_summary"]

_LOG = logging.getLogger(__name__)


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _LOG.warning("cycle_summary: failed to read %s: %s", path, exc)
        return None


def _host_of(url: str) -> str:
    """Return the host part of ``url``, or the raw string for non-URL inputs.

    The aggregator groups capture failures by host so e.g. ten failed
    github.com URLs collapse to one bullet instead of ten near-identical
    ones. ``file://`` URLs and bare paths still need a sensible key so they
    don't all map to "" — we use the URL's path basename in that case.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if parts.hostname:
        return parts.hostname
    if parts.path:
        return Path(parts.path).name or url
    return url


def _normalise_reason(raw: str) -> str:
    """Collapse pid- and timestamp-specific noise out of a failure reason."""
    out = re.sub(r"pid[=: ]\d+", "pid=<n>", raw)
    out = re.sub(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\S*", "<ts>", out)
    return out.strip()


@dataclass
class _CaptureGroup:
    host: str
    reason: str
    urls: list[str] = field(default_factory=list)

    def line(self) -> str:
        sample = self.urls[0]
        more = f" (+{len(self.urls) - 1} more)" if len(self.urls) > 1 else ""
        return (
            f"- **{self.host}** × {len(self.urls)} — {self.reason}\n  - {sample}{more}"
        )


def _aggregate_capture_failures(items: list[Any]) -> list[_CaptureGroup]:
    """Group capture failures by ``(host, reason)``.

    Both the agent CLIs and ``scripts/raw_capture.py`` have used a couple of
    shapes over time: ``{url, reason}`` and ``{url, error}``. We accept both
    and ignore unrecognised entries rather than crash the summary writer.
    """
    groups: dict[tuple[str, str], _CaptureGroup] = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        reason = str(item.get("reason") or item.get("error") or "unknown failure")
        host = _host_of(url) if url else "(no url)"
        norm = _normalise_reason(reason)
        key = (host, norm)
        if key not in groups:
            groups[key] = _CaptureGroup(host=host, reason=norm)
        groups[key].urls.append(url or "(no url)")
    return sorted(groups.values(), key=lambda g: (-len(g.urls), g.host))


def _gate_lines(quality: dict[str, Any] | None) -> tuple[Counter[str], list[str]]:
    """Return (status_counts, fail_lines) from the cycle quality report."""
    counts: Counter[str] = Counter()
    fail_lines: list[str] = []
    if not quality:
        return counts, fail_lines
    gates = quality.get("gates") or {}
    if isinstance(gates, dict):
        iterable = gates.items()
    elif isinstance(gates, list):
        iterable = ((str(i), g) for i, g in enumerate(gates))
    else:
        return counts, fail_lines
    for key, g in iterable:
        if not isinstance(g, dict):
            continue
        status = str(g.get("status") or "")
        counts[status] += 1
        if status == "FAIL":
            gid = g.get("gate_id") or key
            msg = (g.get("message") or "").strip()
            fail_lines.append(f"- **{gid}** — {msg}")
    return counts, fail_lines


def _coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value]


def _format_skill_check(skill_check: dict[str, Any] | None) -> str:
    if not skill_check:
        return "_no preflight sidecar found_"
    scanned = skill_check.get("scanned", 0)
    repaired = skill_check.get("repaired") or []
    unrecoverable = skill_check.get("unrecoverable") or []
    if not repaired and not unrecoverable:
        return f"PASS — {scanned} skill file(s) parsed cleanly"
    bits = [f"scanned {scanned}"]
    if repaired:
        bits.append(f"{len(repaired)} auto-restored")
    if unrecoverable:
        bits.append(f"**{len(unrecoverable)} unrecoverable**")
    return ", ".join(bits)


def _format_exit(exit_code: int, exit_reason: str | None) -> str:
    """Map the cycle_runner exit codes (0/1/2) onto human labels."""
    labels = {
        0: "CONTINUE — proceed to next cycle",
        1: "TERMINATE — termination condition met",
        2: "ABORT — structural error, do not proceed",
    }
    base = labels.get(exit_code, f"exit {exit_code}")
    if exit_reason:
        return f"{base}\n\n  Reason: {exit_reason.strip()}"
    return base


def _format_elapsed(elapsed_s: int | float | None) -> str:
    if elapsed_s is None:
        return "?"
    total = max(0, int(elapsed_s))
    if total >= 3600:
        hours = total // 3600
        minutes = (total % 3600) // 60
        return f"{hours}h {minutes:02d}m"
    minutes = total // 60
    seconds = total % 60
    return f"{minutes}m {seconds:02d}s"


def _derive_status(
    exit_code: int,
    *,
    gate_fail: bool,
    errors: int | None,
    warnings: int | None,
) -> str:
    err = 0 if errors is None else errors
    warn = 0 if warnings is None else warnings
    if exit_code == 2 or gate_fail or err > 0:
        return "FAIL"
    if warn > 0:
        return "WARN"
    return "PASS"


def health_header(
    cycle_n: int,
    *,
    exit_code: int,
    notes_drafted: int | None,
    verifier_passed: int | None,
    spent: float | None,
    budget: float | None,
    elapsed_s: int | float | None,
    errors: int | None,
    warnings: int | None,
    gate_fail: bool = False,
) -> str:
    """Pure FR-013 one-line header (also consumed by ``vault status`` + spec 035)."""
    status = _derive_status(
        exit_code, gate_fail=gate_fail, errors=errors, warnings=warnings
    )
    nd = "?" if notes_drafted is None else str(notes_drafted)
    vp = "?" if verifier_passed is None else str(verifier_passed)
    sp = "?" if spent is None else f"${float(spent):.2f}"
    bd = "n/a" if budget is None else f"${float(budget):.2f}"
    elapsed = _format_elapsed(elapsed_s)
    er = "?" if errors is None else str(errors)
    wr = "?" if warnings is None else str(warnings)
    return (
        f"CYCLE {cycle_n}: {status} | {nd} notes drafted, {vp} verifier-passed | "
        f"{sp} spent, {bd} budget | {elapsed} elapsed | {er} errors, {wr} warnings"
    )


def _collect_health_inputs(
    vault_dir: Path,
    cycle_num: int,
    *,
    exit_code: int,
    scout: dict[str, Any],
    research: dict[str, Any],
    quality: dict[str, Any] | None,
) -> dict[str, Any]:
    notes_created = _coerce_str_list(research.get("notes_created"))
    gate_counts, _fail_lines = _gate_lines(quality)
    gate_fail = gate_counts.get("FAIL", 0) > 0
    gate_warn = gate_counts.get("WARN", 0)

    verifier_passed: int | None = None
    notes_drafted = len(notes_created)
    spent: float | None = None
    if quality:
        if quality.get("notes_accepted") is not None:
            verifier_passed = int(quality["notes_accepted"])
        elif quality.get("notes_written") is not None:
            verifier_passed = int(quality["notes_written"])
    cost = research.get("cumulative_cost_usd") or research.get("cost_estimate_usd")
    if cost is not None:
        spent = float(cost)

    budget: float | None = None
    settings_path = vault_dir / "settings.yaml"
    if settings_path.is_file():
        try:
            import yaml

            raw = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                limits = raw.get("limits") or {}
                if isinstance(limits, dict):
                    cap = limits.get("cycle_budget_usd")
                    if cap is None:
                        cap = limits.get("budget_usd")
                    if cap is not None:
                        budget = float(cap)
        except Exception as exc:
            _LOG.warning("cycle_summary: could not read budget cap: %s", exc)

    elapsed_s: int | float | None = None
    cycle_3 = f"{cycle_num:03d}"
    timings = _safe_read_json(
        vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle_3}-timings.json"
    )
    if timings and timings.get("total_duration_s") is not None:
        elapsed_s = timings["total_duration_s"]
    elif quality:
        started = quality.get("cycle_started_at")
        finished = quality.get("cycle_finished_at")
        if started and finished:
            try:
                from datetime import datetime

                t0 = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(str(finished).replace("Z", "+00:00"))
                elapsed_s = int((t1 - t0).total_seconds())
            except (TypeError, ValueError, OverflowError):
                elapsed_s = None

    capture_groups = _aggregate_capture_failures(
        list(research.get("capture_failures") or [])
    )
    degraded_count = 0
    if quality and isinstance(quality.get("degraded_sources"), list):
        degraded_count = len(quality["degraded_sources"])

    incident_errors = 0
    incidents_path = vault_dir / "_pipeline" / "source-incidents.md"
    if incidents_path.is_file():
        try:
            text = incidents_path.read_text(encoding="utf-8")
            incident_errors = text.lower().count("required source")
        except OSError:
            incident_errors = 0

    errors = gate_counts.get("FAIL", 0) + incident_errors
    warnings = gate_warn + len(capture_groups) + degraded_count

    return {
        "exit_code": exit_code,
        "notes_drafted": notes_drafted,
        "verifier_passed": verifier_passed,
        "spent": spent,
        "budget": budget,
        "elapsed_s": elapsed_s,
        "errors": errors,
        "warnings": warnings,
        "gate_fail": gate_fail,
    }


def write_summary(
    vault_dir: Path,
    cycle_num: int,
    *,
    exit_code: int,
    exit_reason: str | None = None,
) -> Path:
    """Write ``_pipeline/cycles/cycle-NNN-summary.md`` and return its path.

    Never raises — the summary is observational and a failure here must not
    influence the cycle's exit code (caller already decided that). Any
    unexpected exception is logged and the function returns the destination
    path anyway so callers can still link to it.
    """
    cycle_3 = f"{cycle_num:03d}"
    cycles_dir = vault_dir / "_pipeline" / "cycles"
    pipeline_dir = vault_dir / "_pipeline"
    dest = cycles_dir / f"cycle-{cycle_3}-summary.md"

    try:
        scout = _safe_read_json(cycles_dir / f"cycle-{cycle_3}-scout.json") or {}
        research = _safe_read_json(cycles_dir / f"cycle-{cycle_3}-research.json") or {}
        quality = _safe_read_json(cycles_dir / f"cycle-{cycle_3}-quality-report.json")
        skill_check = _safe_read_json(
            pipeline_dir / f"cycle-{cycle_3}-skill-check.json"
        )

        notes_created = _coerce_str_list(research.get("notes_created"))
        notes_updated = _coerce_str_list(research.get("notes_updated"))
        topics_existing = _coerce_str_list(
            (research.get("topics_found") or {}).get("existing")
        )
        topics_new = _coerce_str_list((scout.get("topics_found") or {}).get("new"))

        cost = research.get("cumulative_cost_usd") or research.get("cost_estimate_usd")

        gate_counts, fail_lines = _gate_lines(quality)
        capture_groups = _aggregate_capture_failures(
            list(research.get("capture_failures") or [])
        )

        health_inputs = _collect_health_inputs(
            vault_dir,
            cycle_num,
            exit_code=exit_code,
            scout=scout,
            research=research,
            quality=quality,
        )
        header = health_header(cycle_num, **health_inputs)

        out: list[str] = []
        out.append(header)
        out.append(f"# Cycle {cycle_num} summary\n")
        out.append(f"**Exit**: {_format_exit(exit_code, exit_reason)}\n")

        out.append("## Work")
        if notes_created or notes_updated:
            if notes_created:
                out.append(f"- Notes created: **{len(notes_created)}**")
                for n in notes_created[:10]:
                    out.append(f"  - `{n}`")
                if len(notes_created) > 10:
                    out.append(f"  - … ({len(notes_created) - 10} more)")
            if notes_updated:
                out.append(f"- Notes updated: **{len(notes_updated)}**")
                for n in notes_updated[:10]:
                    out.append(f"  - `{n}`")
                if len(notes_updated) > 10:
                    out.append(f"  - … ({len(notes_updated) - 10} more)")
        else:
            out.append("- _no notes created or updated this cycle_")
        if topics_new:
            out.append(f"- New scout topics: **{len(topics_new)}**")
        if topics_existing:
            out.append(f"- Topics deepened: **{len(topics_existing)}**")
        if cost is not None:
            out.append(f"- Cumulative cost: ${float(cost):.2f}")
        out.append("")

        out.append("## Gates")
        if gate_counts:
            parts = [
                f"{count} {status}" for status, count in sorted(gate_counts.items())
            ]
            out.append(f"- Verdicts: {', '.join(parts)}")
            if fail_lines:
                out.append("- Failures:")
                out.extend(f"  {line}" for line in fail_lines)
        else:
            out.append("- _no gate verdicts recorded (cycle aborted early?)_")
        out.append("")

        out.append("## Preflight")
        out.append(f"- Skill check: {_format_skill_check(skill_check)}")
        out.append("")

        out.append("## Capture failures (aggregated)")
        if capture_groups:
            for grp in capture_groups[:8]:
                out.append(grp.line())
            if len(capture_groups) > 8:
                out.append(f"- _… {len(capture_groups) - 8} more host(s)_")
        else:
            out.append("- none")
        out.append("")

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("\n".join(out) + "\n", encoding="utf-8")
    except Exception as exc:
        _LOG.warning("cycle_summary.write_summary failed: %s", exc)
    return dest
