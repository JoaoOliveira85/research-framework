"""``--resume`` hands the paused stage to the cycle runner (issue #235).

The marker is deleted before ``run_cycles`` is ever called, so the stage it
named has to be read on the way past. These tests pin the CLI half of
budget-marker.contract.md §4.5: read before the clear, arm only when the
resume actually proceeded, and never arm on a cycle the marker did not name.
"""

from __future__ import annotations

import pytest

from research_framework.cli.budget_resume import peek_paused_stage
from research_framework.cli.research_resume import _resume
from research_framework.pipeline import cycle_runner
from research_framework.pipeline.budget_guard import (
    BudgetPausedMarker,
    atomic_write_json_marker,
)
from tests.cli.test_research_resume import (
    _minimal_vault,
    _patch_resume_deps,
    _resume_args,
)


@pytest.fixture(autouse=True)
def _clean_arming():
    cycle_runner._pending_stage_resume.clear()
    yield
    cycle_runner._pending_stage_resume.clear()


def _pause(vault_dir, stage: str, *, cycle: int = 1, cap: float = 5.0) -> None:
    marker = BudgetPausedMarker(
        pause_reason="dollar_cap_exceeded",
        cycle_number=cycle,
        paused_stage=stage,
        cumulative_spend_usd=4.9,
        cycle_budget_usd=cap,
        dispatch_estimate_usd=0.5,
    )
    atomic_write_json_marker(
        vault_dir / "_pipeline" / "BUDGET_PAUSED", marker.to_json_dict()
    )


def test_peek_reads_the_paused_stage_for_the_cycle(tmp_path) -> None:
    vault_dir, _ = _minimal_vault(tmp_path)
    _pause(vault_dir, "note_writer", cycle=2)
    assert peek_paused_stage(vault_dir, 2) == "note_writer"


def test_peek_ignores_a_marker_for_a_different_cycle(tmp_path) -> None:
    """Skipping phases of the wrong cycle would drop work, not just money."""
    vault_dir, _ = _minimal_vault(tmp_path)
    _pause(vault_dir, "note_writer", cycle=2)
    assert peek_paused_stage(vault_dir, 3) is None


def test_peek_is_none_without_a_marker(tmp_path) -> None:
    vault_dir, _ = _minimal_vault(tmp_path)
    assert peek_paused_stage(vault_dir, 1) is None


def test_peek_is_none_for_an_unreadable_marker(tmp_path) -> None:
    """An invalid marker is the budget handler's refusal to make, not ours."""
    vault_dir, _ = _minimal_vault(tmp_path)
    path = vault_dir / "_pipeline" / "BUDGET_PAUSED"
    path.write_text("{not json", encoding="utf-8")
    assert peek_paused_stage(vault_dir, 1) is None


def test_resume_arms_the_runner_with_the_paused_stage(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    vault_dir, spec_path = _minimal_vault(tmp_path)
    _patch_resume_deps(monkeypatch)
    _pause(vault_dir, "note_writer", cycle=1)

    armed: list[tuple[int, str]] = []
    monkeypatch.setattr(
        "research_framework.pipeline.cycle_runner.arm_stage_resume",
        lambda cycle, stage: armed.append((cycle, stage)),
        raising=True,
    )

    assert _resume(_resume_args(vault_dir, spec_path, cycle=1)) == 0
    assert armed == [(1, "note_writer")]


def test_a_refused_resume_arms_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Still over the cap ⇒ exit 1, marker retained, no skip promised."""
    vault_dir, spec_path = _minimal_vault(tmp_path)
    (vault_dir / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 1\n  budget_usd: 10.0\n"
        "limits:\n  cycle_budget_usd: 0.01\n",
        encoding="utf-8",
    )
    _patch_resume_deps(monkeypatch)
    _pause(vault_dir, "note_writer", cycle=1)
    sidecar = (
        vault_dir
        / "_pipeline"
        / "cycles"
        / "cycle-001"
        / "agent-calls"
        / "scout-1.json"
    )
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text('{"schema_version": "1.2", "cost_usd": 9.0}', encoding="utf-8")

    armed: list[tuple[int, str]] = []
    monkeypatch.setattr(
        "research_framework.pipeline.cycle_runner.arm_stage_resume",
        lambda cycle, stage: armed.append((cycle, stage)),
        raising=True,
    )

    args = _resume_args(vault_dir, spec_path, cycle=1)
    args.force_budget = False
    assert _resume(args) == 1
    assert armed == []


def test_a_resume_without_a_pause_arms_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    vault_dir, spec_path = _minimal_vault(tmp_path)
    _patch_resume_deps(monkeypatch)

    armed: list[tuple[int, str]] = []
    monkeypatch.setattr(
        "research_framework.pipeline.cycle_runner.arm_stage_resume",
        lambda cycle, stage: armed.append((cycle, stage)),
        raising=True,
    )

    assert _resume(_resume_args(vault_dir, spec_path, cycle=1)) == 0
    assert armed == []
