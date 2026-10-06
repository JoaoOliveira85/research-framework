#!/usr/bin/env python3
"""Executor × model benchmark sweep (spec 056) — standalone, manually invoked.

Sweeps a ``{task × executor × model}`` matrix against the frozen vault fixture,
scoring each cell deterministically (Principle IV) and writing a dated,
never-clobbered report under ``<fixture>/_pipeline/benchmarks/<run-id>/``.

    # hermetic (no live LLM, CI-safe) — recorded fixture responses:
    python scripts/benchmark_executors.py --dry-run

    # live sweep (real API calls, costs money) — requires explicit ack:
    python scripts/benchmark_executors.py --yes --max-usd 2.00

This script is deliberately OUTSIDE the default pytest collection and every CI
gate (FR-001 / SC-007): it is an opt-in evaluation surface, not a test.
"""

from __future__ import annotations

import argparse
import functools
import json
import sys
from pathlib import Path

# Eval tool: run from the dev checkout where the package is importable. Mirror
# the sibling scripts' bootstrap so it works without an editable install too.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_REPO_SRC = _REPO_ROOT / "src"
if _REPO_SRC.exists() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

# ruff: noqa: E402  (imports follow the sys.path bootstrap above, by design)
from research_framework.benchmark import gating, matrix, reporter, runner

_DEFAULT_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "benchmark"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="benchmark_executors",
        description="Sweep a task × executor × model matrix; score quality/cost/latency.",
    )
    p.add_argument(
        "--fixture",
        type=Path,
        default=_DEFAULT_FIXTURE,
        help="Benchmark vault fixture (default: tests/fixtures/benchmark).",
    )
    p.add_argument(
        "--matrix",
        type=Path,
        default=None,
        help="Matrix YAML (default: <fixture>/benchmark-matrix.yaml).",
    )
    p.add_argument(
        "--task", action="append", default=None, help="Scope to task id (repeatable)."
    )
    p.add_argument(
        "--executor",
        action="append",
        default=None,
        help="Scope to runtime (repeatable).",
    )
    p.add_argument(
        "--model", action="append", default=None, help="Scope to model (repeatable)."
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Acknowledge live spend without an interactive prompt.",
    )
    p.add_argument(
        "--max-usd",
        type=float,
        default=None,
        help="Inclusive dollar cap; stop mid-sweep with a partial report.",
    )
    p.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="v1 supports only 1 (--repeat N is reserved for v1.1).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        dest="json_out",
        help="Print a machine summary JSON to stdout on completion.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Hermetic replay from fixture responses; no live LLM.",
    )
    p.add_argument(
        "--list-runs",
        action="store_true",
        help="List existing run-ids for the fixture and exit.",
    )
    return p


def _list_runs(fixture_dir: Path) -> int:
    root = reporter.benchmarks_root(fixture_dir)
    if not root.is_dir():
        print(f"(no runs yet under {root})")
        return 0
    for run in sorted(p.name for p in root.iterdir() if p.is_dir()):
        print(run)
    return 0


def main(argv: list[str] | None = None) -> int:
    import os

    args = _build_parser().parse_args(argv)
    fixture_dir: Path = args.fixture
    matrix_path: Path = args.matrix or (fixture_dir / "benchmark-matrix.yaml")

    if args.list_runs:
        return _list_runs(fixture_dir)
    if args.repeat != 1:
        print(
            "ERROR: --repeat is reserved for v1.1; v1 sample_count is fixed at 1.",
            file=sys.stderr,
        )
        return 2

    try:
        mtx = matrix.load_matrix(matrix_path)
    except matrix.MatrixError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    cells = matrix.apply_scope(
        matrix.expand_cells(mtx),
        tasks=args.task,
        executors=args.executor,
        models=args.model,
    )
    if not cells:
        print("ERROR: scope selected zero cells.", file=sys.stderr)
        return 2

    estimated = gating.estimate_matrix_cost(cells)
    mode = "hermetic dry-run (no spend)" if args.dry_run else "LIVE (real API spend)"
    print(
        f"Matrix: {len(cells)} cells × {reporter.SAMPLE_COUNT} sample — {mode}\n"
        f"Estimated upper-bound cost: ${estimated:.4f}",
        file=sys.stderr,
    )

    if args.dry_run:
        ack_mode = "dry-run"
    else:
        decision = gating.resolve_ack(
            yes=args.yes,
            env_ack=os.environ.get("RF_BENCHMARK_ACK"),
            stdin_isatty=sys.stdin.isatty(),
            stdout_isatty=sys.stdout.isatty(),
        )
        if not decision.proceed:
            hint = (
                "declined at prompt."
                if decision.mode == "tty"
                else "headless run needs --yes or RF_BENCHMARK_ACK=1."
            )
            print(f"Aborted before any dispatch — {hint}", file=sys.stderr)
            return 3
        ack_mode = decision.mode

    try:
        manifest = json.loads((fixture_dir / "manifest.json").read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        manifest = {}

    run_dir = reporter.create_run_dir(fixture_dir, reporter.run_id_now())
    if args.dry_run:
        dispatch_fn = runner.hermetic_dispatch
    else:
        # Bound each cell's vault budget to the whole-run cap (defence-in-depth).
        dispatch_fn = functools.partial(
            runner.live_dispatch, cell_budget_usd=args.max_usd
        )
    report = runner.run_matrix(
        cells,
        fixture_dir=fixture_dir,
        run_dir=run_dir,
        manifest=manifest,
        matrix_path=matrix_path,
        dispatch_fn=dispatch_fn,
        cost_cap=gating.CostCap(args.max_usd),
        ack_mode=ack_mode,
        estimated_usd=estimated,
        max_usd=args.max_usd,
    )

    cell_results = report["cells"]
    actual = sum(c["cost_usd"] for c in cell_results if c.get("cost_usd") is not None)
    summary = {
        "run_id": report["run_id"],
        "run_dir": str(run_dir),
        "cells_total": len(cells),
        "cells_reported": len(cell_results),
        "ok": sum(1 for c in cell_results if c["status"] == "ok"),
        "failed": sum(1 for c in cell_results if c["status"] == "failed"),
        "skipped": sum(1 for c in cell_results if c["status"] == "skipped"),
        "actual_usd": round(actual, 4),
        "report_json": str(run_dir / "report.json"),
    }
    if args.json_out:
        print(json.dumps(summary, indent=2))
    else:
        print(
            f"Done — {summary['ok']} ok / {summary['failed']} failed / "
            f"{summary['skipped']} skipped; ${summary['actual_usd']:.4f} spent.\n"
            f"Report: {summary['report_json']}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
