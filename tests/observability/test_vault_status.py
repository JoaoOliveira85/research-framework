"""FR-009/010/011: ``vault status`` verb (spec 048 v1.1)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from research_framework.cli.status import (
    build_status_json,
    render_active,
    render_inactive,
    run_status,
)


def _write_active_state(
    vault: Path,
    *,
    cycle: int = 3,
    budgeted: int = 5,
    stage: str = "research",
) -> Path:
    pipeline = vault / "_pipeline"
    pipeline.mkdir(parents=True, exist_ok=True)
    state_path = pipeline / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "in_progress_cycle": cycle,
                "cycles_budgeted": budgeted,
                "stage": stage,
                "cycle_started_at": "2026-06-03T14:02:11Z",
                "budget_snapshot": {
                    "wall_remaining_s": 4380,
                    "dollar_remaining": 0.67,
                    "dollar_budget": 1.50,
                },
                "updated_at": "2026-06-03T14:49:30Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cycle_dir = pipeline / "cycles" / f"cycle-{cycle:03d}"
    cycle_dir.mkdir(parents=True, exist_ok=True)
    log_path = cycle_dir / "cycle.log"
    log_path.write_text(
        "2026-06-03 14:49:30,123 [INFO] research_framework.pipeline.steps.research: drafting note 'AlphaEvolve'\n",
        encoding="utf-8",
    )
    header = (
        "CYCLE 3: PASS | 0 notes drafted, 0 verifier-passed | "
        "$0.00 spent, n/a budget | 0m 00s elapsed | 0 errors, 0 warnings"
    )
    (pipeline / "cycles" / f"cycle-{cycle:03d}-summary.md").write_text(
        header + "\n\n# Cycle 3 summary\n",
        encoding="utf-8",
    )
    return log_path


def test_active(tmp_path: Path) -> None:
    _write_active_state(tmp_path)
    from research_framework.pipeline.cycle_state import read

    state = read(tmp_path)
    assert state is not None
    last_log = (
        "2026-06-03 14:49:30,123 [INFO] research_framework.pipeline.steps.research: "
        "drafting note 'AlphaEvolve'"
    )
    text = render_active(state, last_log, elapsed_s=2839)
    assert "CYCLE 3 of 5 — stage: research" in text
    assert "elapsed:" in text
    assert "budget:" in text
    assert "last log:" in text
    assert "AlphaEvolve" in text


def test_active_starting_when_no_state(tmp_path: Path) -> None:
    text = render_active(None, None, elapsed_s=12, cycle_num=1, cycles_budgeted=5)
    assert "CYCLE 1 — (starting)" in text


def test_inactive(tmp_path: Path) -> None:
    cycles = tmp_path / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)
    header = (
        "CYCLE 2: PASS | 41 notes drafted, 38 verifier-passed | "
        "$1.21 spent, $1.50 budget | 1h 04m elapsed | 0 errors, 1 warnings"
    )
    summary = cycles / "cycle-002-summary.md"
    summary.write_text(
        header + "\n\n# Cycle 2 summary\n",
        encoding="utf-8",
    )
    (cycles / "cycle-002-research.json").write_text(
        json.dumps(
            {
                "capture_failures": [
                    {"url": "https://mistral.ai/x", "reason": "JS_SHELL"},
                ]
            }
        ),
        encoding="utf-8",
    )
    text = render_inactive(tmp_path)
    assert "(no active cycle)" in text
    assert header in text
    assert "last successful cycle:" in text
    assert "deferred warnings:" in text


def test_inactive_no_cycles_yet(tmp_path: Path) -> None:
    assert render_inactive(tmp_path) == "(no cycles yet)"


def _write_pipeline_state(vault: Path, phases: dict | None = None) -> None:
    """Write `_pipeline/pipeline-state.json` — the `pipeline` subcommand's
    own state file, distinct from this module's `_pipeline/state.json`."""
    from research_framework.pipeline.runner import _blank_state, _save_state

    state = _blank_state("2026-09-01-0600", "2026-09-01T06:00:00Z")
    if phases:
        for name, updates in phases.items():
            state["phases"][name].update(updates)
    _save_state(vault, state)


def test_inactive_surfaces_pipeline_state_when_no_cycles_exist(
    tmp_path: Path,
) -> None:
    """Issue #245: a vault driven only through `pipeline run` (never
    `cycle`/`resume`) must not be reported as "(no cycles yet)" — that file
    exists and has an answer."""
    _write_pipeline_state(
        tmp_path,
        phases={
            "verify": {
                "status": "failed",
                "errors": ["verify processor error: boom"],
            }
        },
    )
    text = render_inactive(tmp_path)
    assert "no cycles yet" not in text
    assert "pipeline run 2026-09-01-0600" in text
    assert "verify: failed" in text
    assert "boom" in text


def test_json_surfaces_pipeline_state(tmp_path: Path) -> None:
    _write_pipeline_state(
        tmp_path,
        phases={"collect": {"status": "done"}},
    )
    result = build_status_json(tmp_path)
    assert result["pipeline"] is not None
    assert result["pipeline"]["run_id"] == "2026-09-01-0600"
    assert result["pipeline"]["phases"]["collect"]["status"] == "done"


def test_json_pipeline_is_none_when_no_pipeline_run_happened(
    tmp_path: Path,
) -> None:
    result = build_status_json(tmp_path)
    assert result["pipeline"] is None


def test_active_cycle_state_still_reports_pipeline_state_alongside(
    tmp_path: Path,
) -> None:
    """The two files are independent — an active `cycle` run doesn't hide a
    `pipeline run`'s recorded state, or vice versa."""
    _write_active_state(tmp_path)
    _write_pipeline_state(tmp_path, phases={"scout": {"status": "done"}})
    result = build_status_json(tmp_path)
    assert result["active"] is True
    assert result["pipeline"]["phases"]["scout"]["status"] == "done"


def test_json_active_and_inactive(tmp_path: Path) -> None:
    _write_active_state(tmp_path)
    active = build_status_json(tmp_path)
    assert active["active"] is True
    assert active["cycle"] == 3
    assert active["stage"] == "research"
    assert active["last_cycle_header"] is None
    assert isinstance(active["deferred_warnings"], list)

    state_path = tmp_path / "_pipeline" / "state.json"
    state_path.unlink()
    inactive = build_status_json(tmp_path)
    assert inactive["active"] is False
    assert inactive["cycle"] is None
    assert inactive["stage"] is None
    assert inactive["elapsed_s"] is None
    assert inactive["last_log_line"] is None
    assert inactive["last_cycle_header"] is not None


def test_cli_wiring(capsys: pytest.CaptureFixture) -> None:
    from research_framework.cli._parser import build_parser

    parser = build_parser()
    commands = None
    for action in parser._actions:
        if getattr(action, "dest", None) == "command":
            commands = action.choices
            break
    assert commands is not None
    assert "status" in commands
    assert "pipeline" in commands

    with pytest.raises(SystemExit) as exc:
        from research_framework.cli import main

        main(["status"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "vault" in err.lower() or "--vault" in err


def test_edges_corrupt_state(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    pipeline = tmp_path / "_pipeline"
    pipeline.mkdir(parents=True)
    (pipeline / "state.json").write_text("{bad", encoding="utf-8")
    cycles = pipeline / "cycles"
    cycles.mkdir()
    header = "CYCLE 1: PASS | 1 notes drafted, 1 verifier-passed | $0.10 spent, n/a budget | 1m 00s elapsed | 0 errors, 0 warnings"
    (cycles / "cycle-001-summary.md").write_text(header + "\n", encoding="utf-8")

    rc = run_status(tmp_path, json_output=False)
    assert rc == 0
    out = capsys.readouterr().out
    assert "(no active cycle)" in out


def test_perf(tmp_path: Path) -> None:
    cycles = tmp_path / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)
    for n in range(1, 1001):
        (cycles / f"cycle-{n:03d}").mkdir()
    header = "CYCLE 1000: PASS | 0 notes drafted, 0 verifier-passed | $0.00 spent, n/a budget | 0m 00s elapsed | 0 errors, 0 warnings"
    (cycles / "cycle-1000-summary.md").write_text(header + "\n", encoding="utf-8")

    start = time.monotonic()
    build_status_json(tmp_path)
    elapsed = time.monotonic() - start
    assert elapsed < 1.0
