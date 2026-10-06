"""FR4 (spec 061): run-report cycle-budget provenance.

``write_run_report`` records a ``cycle_budget {configured, source, actual,
exit_status}`` block in the additive ``_pipeline/run-report.json`` (and a
"Cycle budget" headline in ``run-report.md``). ``actual`` is the count of cycles
that left an artifact; ``exit_status`` maps the overall run exit code
(0 ⇒ complete / 1 ⇒ constrained / 2 ⇒ aborted). This is the provenance signal
spec 063's GA-004 acceptance gate consumes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_framework.pipeline.run_report import write_run_report


def _seed_cycles(vault: Path, n: int) -> None:
    """Drop ``n`` cycle timings artifacts so ``_discover_cycles`` counts them."""
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        (cycles / f"cycle-{i:03d}-timings.json").write_text(
            json.dumps({"exit_code": 0, "total_duration_s": 1.0, "stages": []}),
            encoding="utf-8",
        )


def _read_report_json(vault: Path) -> dict[str, Any]:
    return json.loads(
        (vault / "_pipeline" / "run-report.json").read_text(encoding="utf-8")
    )


def test_run_report_json_includes_cycle_budget_provenance(tmp_path: Path) -> None:
    _seed_cycles(tmp_path, 3)
    write_run_report(
        tmp_path,
        final_exit_code=0,
        final_exit_reason="vault complete",
        cycle_budget_configured=12,
        cycle_budget_source="settings",
    )
    cb = _read_report_json(tmp_path)["cycle_budget"]
    assert cb == {
        "configured": 12,
        "source": "settings",
        "actual": 3,
        "exit_status": "complete",
    }


def test_max_cycles_reached_reports_constrained_exit(tmp_path: Path) -> None:
    # configured == actual: the run consumed its whole cycle budget.
    _seed_cycles(tmp_path, 3)
    write_run_report(
        tmp_path,
        final_exit_code=1,
        final_exit_reason="max_cycles (3) reached",
        cycle_budget_configured=3,
        cycle_budget_source="settings",
    )
    cb = _read_report_json(tmp_path)["cycle_budget"]
    assert cb["exit_status"] == "constrained"
    assert cb["actual"] == cb["configured"] == 3


def test_clean_completion_reports_complete_with_actual_lte_configured(
    tmp_path: Path,
) -> None:
    _seed_cycles(tmp_path, 3)
    write_run_report(
        tmp_path,
        final_exit_code=0,
        cycle_budget_configured=12,
        cycle_budget_source="settings",
    )
    cb = _read_report_json(tmp_path)["cycle_budget"]
    assert cb["exit_status"] == "complete"
    assert cb["actual"] <= cb["configured"]


def test_run_report_markdown_includes_cycle_budget_headline(tmp_path: Path) -> None:
    _seed_cycles(tmp_path, 2)
    dest = write_run_report(
        tmp_path,
        final_exit_code=1,
        cycle_budget_configured=2,
        cycle_budget_source="flag",
    )
    md = dest.read_text(encoding="utf-8")
    assert "Cycle budget" in md
    assert "flag" in md  # source echoed
    assert "constrained" in md  # exit_status echoed
