"""D1: extended ``state.json`` read/write (spec 048 v1.1)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from research_framework.pipeline.cycle_state import read, write


def test_cycle_state_round_trip(tmp_path: Path) -> None:
    write(
        tmp_path,
        in_progress_cycle=3,
        cycles_budgeted=5,
        stage="research",
        cycle_started_at="2026-06-03T14:02:11Z",
        budget_snapshot={
            "wall_remaining_s": 4380,
            "dollar_remaining": 0.67,
            "dollar_budget": 1.50,
        },
    )
    state = read(tmp_path)
    assert state is not None
    assert state.in_progress_cycle == 3
    assert state.cycles_budgeted == 5
    assert state.stage == "research"
    assert state.cycle_started_at == "2026-06-03T14:02:11Z"
    assert state.budget_snapshot is not None
    assert state.budget_snapshot.wall_remaining_s == 4380
    assert state.budget_snapshot.dollar_remaining == 0.67
    assert state.budget_snapshot.dollar_budget == 1.50
    assert state.updated_at is not None


def test_cycle_state_absent_file_returns_none(tmp_path: Path) -> None:
    assert read(tmp_path) is None


def test_cycle_state_corrupt_json_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "_pipeline" / "state.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert read(tmp_path) is None


def test_cycle_state_nullable_budget_fields(tmp_path: Path) -> None:
    write(
        tmp_path,
        in_progress_cycle=1,
        budget_snapshot={
            "wall_remaining_s": None,
            "dollar_remaining": None,
            "dollar_budget": None,
        },
    )
    state = read(tmp_path)
    assert state is not None
    assert state.budget_snapshot is not None
    assert state.budget_snapshot.wall_remaining_s is None
    assert state.budget_snapshot.dollar_remaining is None
    assert state.budget_snapshot.dollar_budget is None


def test_cycle_runner_writes_stage_on_transitions(tmp_path: Path) -> None:
    """Integration: two stage writes produce monotonic ``updated_at``."""
    from research_framework.pipeline.cycle_state import read as read_state

    t0 = datetime(2026, 6, 3, 14, 0, 0, tzinfo=UTC)

    with patch(
        "research_framework.pipeline.cycle_state._utc_now_iso",
        side_effect=["2026-06-03T14:00:00Z", "2026-06-03T14:01:00Z"],
    ):
        write(
            tmp_path,
            in_progress_cycle=1,
            cycles_budgeted=3,
            stage="scout",
            cycle_started_at=t0.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        write(
            tmp_path,
            in_progress_cycle=1,
            cycles_budgeted=3,
            stage="research",
            cycle_started_at=t0.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    state = read_state(tmp_path)
    assert state is not None
    assert state.stage == "research"
    assert state.updated_at == "2026-06-03T14:01:00Z"
