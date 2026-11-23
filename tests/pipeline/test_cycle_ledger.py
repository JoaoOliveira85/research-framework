"""Spec 083 T007: the cycle ledger and the readers that prefer it."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from research_framework.cli.research_resume import (
    _highest_completed_cycle,
    _resolve_resume_cycle,
)
from research_framework.pipeline import cycle_ledger, state_layout
from research_framework.pipeline.coverage import _hours_since_last_cycle
from research_framework.pipeline.orchestrator import _cumulative_sidecar_cost


def _cycles(vault: Path) -> Path:
    path = vault / "_pipeline" / "cycles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _scan_cycle(vault: Path, n: int, cost: float, *, stamp: str | None = None) -> None:
    cycles = _cycles(vault)
    (cycles / f"cycle-{n:03d}-quality-report.json").write_text("{}", encoding="utf-8")
    calls = cycles / f"cycle-{n:03d}" / "agent-calls"
    calls.mkdir(parents=True, exist_ok=True)
    (calls / "a.json").write_text(json.dumps({"cost_usd": cost}), encoding="utf-8")
    if stamp:
        (cycles / f"cycle-{n:03d}-research.json").write_text(
            json.dumps({"timestamp": stamp}), encoding="utf-8"
        )


def _args(vault: Path):
    import argparse

    return argparse.Namespace(output=vault, vault_dir=vault, cycle=None)


def _row(vault: Path, n: int, cost: float, when: datetime | None = None) -> None:
    cycle_ledger.append_cycle(
        vault, cycle=n, cost_usd=cost, sidecars_missing=False, finished_at=when
    )


def test_a_closed_cycle_appends_exactly_one_row(tmp_path: Path) -> None:
    _scan_cycle(tmp_path, 1, 0.5)
    cycle_ledger.close_cycle(tmp_path, 1)
    cycle_ledger.close_cycle(tmp_path, 1)  # same cycle again: replaces
    doc = json.loads(state_layout.cycle_ledger_path(tmp_path).read_text())
    assert doc["schema_version"] == 1
    assert len(doc["cycles"]) == 1
    row = doc["cycles"][0]
    assert row["cycle"] == 1 and row["cost_usd"] == pytest.approx(0.5)
    assert row["sidecars_missing"] is False
    assert row["finished_at"].endswith("Z")
    cycle_ledger.close_cycle(tmp_path, 2)  # no sidecars at all
    rows = cycle_ledger.load(tmp_path)
    assert [r.cycle for r in rows] == [1, 2]
    assert rows[1].sidecars_missing is True and rows[1].cost_usd == 0.0


def test_readers_survive_an_empty_cycles_directory(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    for n, cost in ((1, 1.0), (2, 2.0), (3, 0.5)):
        _row(tmp_path, n, cost, now - timedelta(hours=10 - n))
    assert not (tmp_path / "_pipeline" / "cycles").exists()
    assert _resolve_resume_cycle(_args(tmp_path)) == 4
    assert _cumulative_sidecar_cost(tmp_path, up_to=3) == pytest.approx(3.5)
    hours = _hours_since_last_cycle(tmp_path, current_cycle=4, now=now)
    assert hours == pytest.approx(7.0, abs=0.01)


def test_scan_supplies_only_cycles_the_ledger_lacks(tmp_path: Path) -> None:
    _row(tmp_path, 1, 1.0)
    _row(tmp_path, 2, 2.0)
    _scan_cycle(tmp_path, 1, 9.0)
    _scan_cycle(tmp_path, 2, 9.0)  # disagrees with the ledger
    _scan_cycle(tmp_path, 3, 0.25)
    assert _cumulative_sidecar_cost(tmp_path, up_to=3) == pytest.approx(3.25)
    assert _resolve_resume_cycle(_args(tmp_path)) == 4


def test_a_corrupt_ledger_is_reported_not_guessed(tmp_path: Path) -> None:
    _scan_cycle(tmp_path, 1, 1.0, stamp="2026-01-01T00:00:00Z")
    path = state_layout.cycle_ledger_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    for call in (
        lambda: _resolve_resume_cycle(_args(tmp_path)),
        lambda: _cumulative_sidecar_cost(tmp_path, up_to=1),
        lambda: _hours_since_last_cycle(tmp_path, current_cycle=2),
    ):
        with pytest.raises(cycle_ledger.CycleLedgerError, match="cycle-ledger.json"):
            call()


def test_backfill_adds_only_the_cycles_the_ledger_lacks(tmp_path: Path) -> None:
    _row(tmp_path, 1, 1.0)
    _scan_cycle(tmp_path, 1, 9.0)
    _scan_cycle(tmp_path, 2, 0.75, stamp="2026-01-02T03:04:05Z")
    _cycles(tmp_path).joinpath("cycle-003-quality-report.json").write_text("{}")
    _cycles(tmp_path).joinpath("cycle-004-quality-report.json").write_text("{}")
    _cycles(tmp_path).joinpath("cycle-004-aborted.json").write_text("{}")
    assert cycle_ledger.backfill_from_cycles(tmp_path) == 2
    assert cycle_ledger.backfill_from_cycles(tmp_path) == 0
    by = {r.cycle: r for r in cycle_ledger.load(tmp_path)}
    assert sorted(by) == [1, 2, 3]  # aborted cycle 4 gets no row
    assert by[1].cost_usd == 1.0
    assert by[2].finished_at == "2026-01-02T03:04:05Z"
    assert by[2].cost_usd == pytest.approx(0.75) and not by[2].sidecars_missing
    assert by[3].sidecars_missing and by[3].cost_usd == 0.0


def test_highest_completed_cycle_is_max_of_ledger_and_scan(tmp_path: Path) -> None:
    assert _highest_completed_cycle(tmp_path) is None
    _row(tmp_path, 5, 0.0)
    _scan_cycle(tmp_path, 3, 0.0)
    assert _highest_completed_cycle(tmp_path) == 5
