"""Benchmark report assembly + dated run directories (spec 056, contract §1–5).

Writes a machine ``report.json`` and a human ``report.md`` under a never-clobbered
``<fixture>/_pipeline/benchmarks/<run-id>/`` dir (run-id = UTC
``YYYYMMDDTHHMMSSZ``). The directory is gitignored; prior runs are preserved so
deltas are derivable (US4 / SC-006).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPORT_SCHEMA_VERSION = "1.0"
SAMPLE_COUNT = 1  # v1: exactly one live invocation per cell (Q5).
RUN_ID_RE = re.compile(r"^\d{8}T\d{6}Z$")


def run_id_now() -> str:
    """UTC ``YYYYMMDDTHHMMSSZ`` run id (sortable, second-resolution)."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def iso_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def benchmarks_root(fixture_dir: Path) -> Path:
    return fixture_dir / "_pipeline" / "benchmarks"


def create_run_dir(fixture_dir: Path, run_id: str) -> Path:
    """Create + return the run dir; refuse to clobber an existing one (FR-009)."""
    if not RUN_ID_RE.match(run_id):
        raise ValueError(f"run_id must be YYYYMMDDTHHMMSSZ, got {run_id!r}")
    run_dir = benchmarks_root(fixture_dir) / run_id
    if run_dir.exists():
        raise FileExistsError(f"benchmark run dir already exists: {run_dir}")
    (run_dir / "cells").mkdir(parents=True)
    return run_dir


def build_report(
    *,
    run_id: str,
    matrix_path: Path,
    fixture_dir: Path,
    cells: list[dict[str, Any]],
    started_at: str,
    completed_at: str,
    estimated_usd: float | None,
    ack_mode: str,
    max_usd: float | None,
) -> dict[str, Any]:
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "matrix_path": str(matrix_path),
        "fixture_path": str(fixture_dir),
        "sample_count": SAMPLE_COUNT,
        "cost_gate": {
            "estimated_usd": estimated_usd,
            "ack_mode": ack_mode,
            "max_usd": max_usd,
        },
        "cells": cells,
    }


def write_report(run_dir: Path, report: dict[str, Any]) -> tuple[Path, Path]:
    json_path = run_dir / "report.json"
    md_path = run_dir / "report.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    """Human report: run header, per-task tables, failures/skips, cost summary (§5)."""
    cells: list[dict[str, Any]] = report.get("cells", [])
    gate = report.get("cost_gate", {})
    lines: list[str] = []
    lines.append(f"# Benchmark report — {report.get('run_id')}")
    lines.append("")
    lines.append(f"- **Matrix**: `{report.get('matrix_path')}`")
    lines.append(f"- **Fixture**: `{report.get('fixture_path')}`")
    lines.append(f"- **Ack mode**: {gate.get('ack_mode')}")
    lines.append(f"- **Sample count**: {report.get('sample_count')}")
    lines.append(
        f"- **Window**: {report.get('started_at')} → {report.get('completed_at')}"
    )
    lines.append("")

    # 2. Per-task tables (quality desc; no cross-task aggregate — FR-015).
    tasks: list[str] = []
    for cell in cells:
        if cell["task"] not in tasks:
            tasks.append(cell["task"])
    for task in tasks:
        lines.append(f"## Task: `{task}`")
        lines.append("")
        lines.append("| executor | model | quality | cost_usd | latency_ms | status |")
        lines.append("|---|---|---|---|---|---|")
        task_cells = [c for c in cells if c["task"] == task]
        task_cells.sort(
            key=lambda c: (c.get("quality") is None, -(c.get("quality") or 0.0))
        )
        for c in task_cells:
            lines.append(
                f"| {c['executor']} | {c['model']} | {_fmt(c.get('quality'))} "
                f"| {_fmt(c.get('cost_usd'))} | {_fmt(c.get('latency_ms'))} "
                f"| {c['status']} |"
            )
        lines.append("")

    # 3. Failures & skips appendix.
    non_ok = [c for c in cells if c["status"] != "ok"]
    if non_ok:
        lines.append("## Failures & skips")
        lines.append("")
        for c in non_ok:
            lines.append(
                f"- `{c['task']}/{c['executor']}/{c['model']}` — "
                f"**{c['status']}**: {c.get('reason') or 'no reason recorded'}"
            )
        lines.append("")

    # 4. Cost summary — keep measured and estimated dollars distinct (a cell with
    #    cost_source "estimated" is a spec-033 fallback, not a billed measurement).
    measured = sum(
        c["cost_usd"]
        for c in cells
        if c.get("cost_usd") is not None and c.get("cost_source") == "sidecar"
    )
    estimated_actual = sum(
        c["cost_usd"]
        for c in cells
        if c.get("cost_usd") is not None and c.get("cost_source") == "estimated"
    )
    lines.append("## Cost summary")
    lines.append("")
    est = gate.get("estimated_usd")
    lines.append(
        f"- **Pre-run estimate**: {('$' + format(est, '.4f')) if est is not None else 'n/a'}"
    )
    lines.append(f"- **Measured (cost_source=sidecar)**: ${measured:.4f}")
    lines.append(
        f"- **Estimated fallback (cost_source=estimated)**: ${estimated_actual:.4f}"
    )
    lines.append(
        f"- **Reported total (measured + estimated)**: ${measured + estimated_actual:.4f}"
    )
    lines.append("")
    return "\n".join(lines)
