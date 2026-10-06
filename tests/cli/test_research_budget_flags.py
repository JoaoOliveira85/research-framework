"""CLI budget flag tests (spec 033)."""

from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path

import pytest

from research_framework.cli.budget_resume import (
    handle_approval_marker_on_resume,
    handle_budget_marker_on_resume,
    validate_force_budget_flags,
)
from research_framework.pipeline.budget_guard import (
    ApprovalRequiredMarker,
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


def test_validate_force_budget_flags_is_noop() -> None:
    args = Namespace(force_budget=True)
    assert validate_force_budget_flags(args) == 0


def test_force_budget_tty_requires_confirmation_when_still_over_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "n")
    vault = tmp_path / "vault"
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
    args = Namespace(force_budget=True)
    assert handle_budget_marker_on_resume(args, vault, 1) == 1


def test_force_budget_headless_requires_rf_force_budget_ack_when_still_over_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import shutil

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    monkeypatch.delenv("RF_FORCE_BUDGET_ACK", raising=False)
    vault = tmp_path / "vault"
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
    args = Namespace(force_budget=True)
    rc = handle_budget_marker_on_resume(args, vault, 1)
    assert rc == 1
    captured = capsys.readouterr().err
    assert "RF_FORCE_BUDGET_ACK" in captured or "force_budget" in captured


def test_force_budget_skips_ack_when_cap_already_satisfied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

    def _fail_input(_: str) -> str:
        raise AssertionError("must not prompt when cap is satisfied")

    monkeypatch.setattr("builtins.input", _fail_input)
    vault = tmp_path / "vault"
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
    args = Namespace(force_budget=True)
    assert handle_budget_marker_on_resume(args, vault, 1) == 0
    assert not path.exists()


def test_approve_all_headless_requires_rf_approve_all_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    monkeypatch.delenv("RF_APPROVE_ALL_ACK", raising=False)
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 1\n  budget_usd: 1.0\n",
        encoding="utf-8",
    )
    marker = ApprovalRequiredMarker(
        stage_name="note_writer",
        cycle_number=1,
        prompt_preview="p",
        estimated_cost_usd=0.1,
        cumulative_spend_usd=0.0,
        tier="standard",
    )
    atomic_write_json_marker(
        vault / "_pipeline/APPROVAL_REQUIRED", marker.to_json_dict()
    )
    args = Namespace(approve=None, approve_all=True, reject=None)
    rc = handle_approval_marker_on_resume(args, vault)
    assert rc == 1
