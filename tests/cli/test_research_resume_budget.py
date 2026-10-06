"""Tier-3 resume + budget marker tests (spec 033)."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from research_framework.cli.budget_resume import handle_budget_marker_on_resume
from research_framework.pipeline.budget_guard import (
    BudgetPausedMarker,
    atomic_write_json_marker,
)

_FIXTURE_VAULT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "cost_enforcement" / "vault"
)


def _write_settings(vault: Path, cap: float) -> None:
    (vault / "settings.yaml").write_text(
        f"""
pipeline:
  max_cycles: 2
  budget_usd: 1.0
limits:
  cycle_budget_usd: {cap}
""",
        encoding="utf-8",
    )


def test_resume_refuses_when_sidecar_sum_still_over_cap(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    import shutil

    shutil.copytree(_FIXTURE_VAULT, vault)
    _write_settings(vault, 0.10)
    marker = BudgetPausedMarker(
        pause_reason="dollar_cap_exceeded",
        cycle_number=1,
        paused_stage="scout",
        cumulative_spend_usd=1.0,
        cycle_budget_usd=0.10,
        dispatch_estimate_usd=0.5,
    )
    atomic_write_json_marker(vault / "_pipeline/BUDGET_PAUSED", marker.to_json_dict())
    args = Namespace(force_budget=False)
    rc = handle_budget_marker_on_resume(args, vault, 1)
    assert rc == 1


def test_resume_clears_budget_marker_when_cap_satisfied(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    import shutil

    shutil.copytree(_FIXTURE_VAULT, vault)
    _write_settings(vault, 100.0)
    marker = BudgetPausedMarker(
        pause_reason="dollar_cap_exceeded",
        cycle_number=1,
        paused_stage="scout",
        cumulative_spend_usd=1.0,
        cycle_budget_usd=0.10,
        dispatch_estimate_usd=0.5,
    )
    path = vault / "_pipeline/BUDGET_PAUSED"
    atomic_write_json_marker(path, marker.to_json_dict())
    args = Namespace(force_budget=False)
    rc = handle_budget_marker_on_resume(args, vault, 1)
    assert rc == 0
    assert not path.exists()
