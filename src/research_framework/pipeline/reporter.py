"""Phase 3 report generator.

Assembles _pipeline/phase1-report.md from cycle JSON files, budget log, and coverage
targets.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_framework.cli._tty import is_interactive_tty

from . import atomic_write
from .budget_guard import (
    collect_tier_cost_warnings,
    list_sidecars_v11,
    read_approval_decisions,
)
from .coverage import load_targets
from .settings import LimitsSettings


def generate_report(vault_dir: Path) -> Path:
    """Write _pipeline/phase1-report.md and return its path."""
    pipeline = vault_dir / "_pipeline"
    pipeline.mkdir(exist_ok=True)
    out = pipeline / "phase1-report.md"

    cycles_dir = pipeline / "cycles"
    cycle_reports: list[tuple[int, str, dict]] = []
    if cycles_dir.exists():
        for path in sorted(cycles_dir.glob("cycle-*-*.json")):
            parts = path.stem.split("-")
            if len(parts) >= 3:
                try:
                    cycle_num = int(parts[1])
                except ValueError:
                    continue
                phase = parts[2]
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    # Unreadable, not UTF-8 (UnicodeDecodeError) or not JSON
                    # (JSONDecodeError): no report to summarise.
                    continue
                # The glob also matches non-report JSON, e.g. the list-shaped
                # ``cycle-NNN-step-gates.json``; only an object is a report.
                if isinstance(data, dict):
                    cycle_reports.append((cycle_num, phase, data))

    try:
        targets = load_targets(vault_dir)
        coverage_rows = [
            f"| {c.name} | {c.target_count} | {c.met_count} | "
            f"{'✓ MET' if c.is_met else f'gap: {c.gap}'} |"
            for c in targets.categories
        ]
    except (FileNotFoundError, RuntimeError):
        coverage_rows = ["| (no coverage-targets.json found) | — | — | — |"]

    budget_log_file = pipeline / "budget-log.md"
    budget_log = (
        budget_log_file.read_text(encoding="utf-8")
        if budget_log_file.exists()
        else "(no budget log)"
    )

    lines = [
        f"# Phase 1 Report — {vault_dir.name}",
        "",
        "## Cycles Summary",
        "",
        f"Total cycle files: {len(cycle_reports)}",
        "",
    ]
    if cycle_reports:
        lines.append("| Cycle | Phase | Notes Created | Dims Covered |")
        lines.append("|-------|-------|---------------|--------------|")
        for num, phase, data in cycle_reports:
            # An agent-written report can hold ``null`` or a number here; only
            # a list has entries to count.
            notes = data.get("notes_created")
            covered = data.get("dimensions_covered")
            created = len(notes) if isinstance(notes, list) else 0
            dims = len(covered) if isinstance(covered, list) else 0
            lines.append(f"| {num} | {phase} | {created} | {dims} |")
    lines.extend(
        [
            "",
            "## Coverage Status",
            "",
            "| Category | Target | Met | Status |",
            "|----------|--------|-----|--------|",
            *coverage_rows,
            "",
            "## Budget Log",
            "",
            budget_log,
        ]
    )
    if cycles_dir.exists():
        quality_reports = sorted(cycles_dir.glob("cycle-*-quality-report.json"))
        if quality_reports:
            lines.extend(["", "## Cycle quality reports", ""])
            for qpath in quality_reports:
                rel = qpath.relative_to(vault_dir).as_posix()
                lines.append(f"**Quality report**: [{rel}]({rel})")
    atomic_write.write_text(out, "\n".join(lines))
    return out


def append_cycle_cost_report(
    vault_dir: Path,
    cycle_num: int,
    *,
    tally: Any,
    limits: LimitsSettings,
) -> Path:
    """Write ``cycle-NNN-report.md`` cost sections (spec 033 FR-007/011/015).

    ``approval_gates_fired`` used to be a keyword argument, and the defect in
    issue #235 was that no production caller ever passed it: the field was
    always ``[]`` in a real report while the tests that "covered" it supplied
    their own rows. It is now read from the persisted decision record
    (``budget_guard.read_approval_decisions``), which the resume CLI writes —
    so there is no way to put a gate in this report that no operator decided.
    """
    cycles_dir = vault_dir / "_pipeline" / "cycles"
    cycles_dir.mkdir(parents=True, exist_ok=True)
    out = cycles_dir / f"cycle-{cycle_num:03d}-report.md"
    sidecars = list_sidecars_v11(vault_dir, cycle_num)
    tier_warnings = collect_tier_cost_warnings(sidecars, limits.tier_thresholds)
    per_stage: dict[str, float] = {}
    per_tier: dict[str, float] = {}
    for row in sidecars:
        stage = str(row.get("stage") or "unknown")
        per_stage[stage] = per_stage.get(stage, 0.0) + float(row.get("cost_usd") or 0.0)
        tier = str(row.get("tier") or "unknown")
        per_tier[tier] = per_tier.get(tier, 0.0) + float(row.get("cost_usd") or 0.0)
    cache_section = _cache_hit_section(vault_dir)
    payload = {
        "cumulative_spend_usd": tally.actual_usd,
        "per_stage_breakdown": per_stage,
        "per_tier_breakdown": per_tier,
        "tier_cost_warnings": tier_warnings,
        "estimation_methods_used": list(getattr(tally, "estimation_methods_used", [])),
        "approval_gates_fired": read_approval_decisions(vault_dir, cycle_num),
        "tty_mode": is_interactive_tty(),
        "cache_summary": cache_section,
    }
    lines = [
        f"# Cycle {cycle_num} cost report",
        "",
        "```json",
        json.dumps(payload, indent=2, ensure_ascii=False),
        "```",
        "",
    ]
    atomic_write.write_text(out, "\n".join(lines))
    return out


def _cache_hit_section(vault_dir: Path) -> dict[str, Any]:
    sources_root = vault_dir / "_pipeline" / "sources"
    if not sources_root.is_dir():
        return {"status": "na", "reason": "020_not_present"}
    hits = 0
    misses = 0
    for path in sources_root.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict):
            hits += int(data.get("cache_hits") or 0)
            misses += int(data.get("cache_misses") or 0)
    if hits + misses == 0:
        return {"status": "na", "reason": "020_not_present"}
    ratio = hits / (hits + misses) if (hits + misses) else 1.0
    return {"status": "ok", "cache_hits": hits, "cache_misses": misses, "ratio": ratio}
