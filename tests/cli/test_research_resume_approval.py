"""Tier-3 approval resume tests (spec 033)."""

from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path

import pytest

from research_framework.cli.budget_resume import handle_approval_marker_on_resume
from research_framework.pipeline.budget_guard import (
    ApprovalRequiredMarker,
    atomic_write_json_marker,
)


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 1\n  budget_usd: 1.0\n",
        encoding="utf-8",
    )
    return vault


def test_headless_resume_without_approve_exits_json_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    vault = _vault(tmp_path)
    marker = ApprovalRequiredMarker(
        stage_name="research",
        cycle_number=1,
        prompt_preview="preview",
        estimated_cost_usd=0.2,
        cumulative_spend_usd=0.1,
        tier="standard",
    )
    atomic_write_json_marker(
        vault / "_pipeline/APPROVAL_REQUIRED", marker.to_json_dict()
    )
    args = Namespace(approve=None, approve_all=False, reject=None)
    rc = handle_approval_marker_on_resume(args, vault)
    assert rc == 1
    assert "approval_required" in capsys.readouterr().err


def test_headless_approve_note_writer_requires_env_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    monkeypatch.delenv("RF_APPROVE_NOTE_WRITER_ACK", raising=False)
    vault = _vault(tmp_path)
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
    args = Namespace(approve="note_writer", approve_all=False, reject=None)
    assert handle_approval_marker_on_resume(args, vault) == 1
    monkeypatch.setenv("RF_APPROVE_NOTE_WRITER_ACK", "1")
    assert handle_approval_marker_on_resume(args, vault) == 0


def test_tty_resume_approval_prompt_y_clears_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "y")
    vault = _vault(tmp_path)
    marker = ApprovalRequiredMarker(
        stage_name="research",
        cycle_number=1,
        prompt_preview="p",
        estimated_cost_usd=0.1,
        cumulative_spend_usd=0.0,
        tier="standard",
    )
    path = vault / "_pipeline/APPROVAL_REQUIRED"
    atomic_write_json_marker(path, marker.to_json_dict())
    args = Namespace(approve=None, approve_all=False, reject=None)
    assert handle_approval_marker_on_resume(args, vault) == 0
    assert not path.exists()


def test_headless_approve_wrong_stage_does_not_clear_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    monkeypatch.setenv("RF_APPROVE_SCOUT_ACK", "1")
    vault = _vault(tmp_path)
    marker = ApprovalRequiredMarker(
        stage_name="research",
        cycle_number=1,
        prompt_preview="p",
        estimated_cost_usd=0.1,
        cumulative_spend_usd=0.0,
        tier="standard",
    )
    path = vault / "_pipeline/APPROVAL_REQUIRED"
    atomic_write_json_marker(path, marker.to_json_dict())
    args = Namespace(approve="scout", approve_all=False, reject=None)
    assert handle_approval_marker_on_resume(args, vault) == 1
    assert path.is_file()
    assert "approve_stage_mismatch" in capsys.readouterr().err


def test_headless_approve_hyphenated_stage_env_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    monkeypatch.delenv("RF_APPROVE_MY_STAGE_ACK", raising=False)
    vault = _vault(tmp_path)
    marker = ApprovalRequiredMarker(
        stage_name="my-stage",
        cycle_number=1,
        prompt_preview="p",
        estimated_cost_usd=0.1,
        cumulative_spend_usd=0.0,
        tier="standard",
    )
    path = vault / "_pipeline/APPROVAL_REQUIRED"
    atomic_write_json_marker(path, marker.to_json_dict())
    args = Namespace(approve="my-stage", approve_all=False, reject=None)
    assert handle_approval_marker_on_resume(args, vault) == 1
    monkeypatch.setenv("RF_APPROVE_MY_STAGE_ACK", "1")
    assert handle_approval_marker_on_resume(args, vault) == 0
    assert not path.exists()


def test_approval_reject_retains_marker_and_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "n")
    vault = _vault(tmp_path)
    marker = ApprovalRequiredMarker(
        stage_name="research",
        cycle_number=1,
        prompt_preview="p",
        estimated_cost_usd=0.1,
        cumulative_spend_usd=0.0,
        tier="standard",
    )
    path = vault / "_pipeline/APPROVAL_REQUIRED"
    atomic_write_json_marker(path, marker.to_json_dict())
    args = Namespace(approve=None, approve_all=False, reject="research")
    assert handle_approval_marker_on_resume(args, vault) == 1
    assert path.is_file()


# ---------------------------------------------------------------------------
# Issue #244 — a deliberate refusal must not read as a framework bug
# ---------------------------------------------------------------------------


def _marked_vault(tmp_path: Path) -> tuple[Path, Path]:
    vault = _vault(tmp_path)
    marker = ApprovalRequiredMarker(
        stage_name="research",
        cycle_number=1,
        prompt_preview="p",
        estimated_cost_usd=0.1,
        cumulative_spend_usd=0.0,
        tier="standard",
    )
    path = vault / "_pipeline/APPROVAL_REQUIRED"
    atomic_write_json_marker(path, marker.to_json_dict())
    return vault, path


def test_reject_says_what_it_rejected_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--reject research` exited 1 with zero bytes, so the spec-070 FR6
    backstop told the operator their own refusal was "a framework bug"."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    vault, path = _marked_vault(tmp_path)

    args = Namespace(approve=None, approve_all=False, reject="research")
    assert handle_approval_marker_on_resume(args, vault) == 1

    err = capsys.readouterr().err
    assert "research" in err, "FR6: the refusal must name the stage it refused"
    assert "_pipeline/APPROVAL_REQUIRED" in err, (
        "FR6: it must name what it left behind, so resuming is obvious"
    )
    assert path.is_file()


def test_reject_all_names_the_stage_it_actually_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    vault, _path = _marked_vault(tmp_path)

    args = Namespace(approve=None, approve_all=False, reject="all")
    assert handle_approval_marker_on_resume(args, vault) == 1
    assert "research" in capsys.readouterr().err


def test_interactive_decline_says_what_it_left_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Answering `n` at the prompt is the same refusal by a different door."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "n")
    vault, path = _marked_vault(tmp_path)

    args = Namespace(approve=None, approve_all=False, reject=None)
    assert handle_approval_marker_on_resume(args, vault) == 1

    err = capsys.readouterr().err
    assert "research" in err
    assert "_pipeline/APPROVAL_REQUIRED" in err
    assert path.is_file()


def test_force_budget_decline_says_what_it_left_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same silent `return 1` on the budget marker's interactive branch."""
    from research_framework.cli.budget_resume import handle_budget_marker_on_resume
    from research_framework.pipeline.budget_guard import BudgetPausedMarker

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "n")
    monkeypatch.setattr(
        "research_framework.cli.budget_resume.sum_sidecar_actuals_usd",
        lambda _v, _c: 2.0,
    )
    vault = _vault(tmp_path)
    (vault / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 1\n  budget_usd: 1.0\nlimits:\n"
        "  cycle_budget_usd: 1.0\n",
        encoding="utf-8",
    )
    marker = BudgetPausedMarker(
        pause_reason="cycle_budget_exceeded",
        cycle_number=1,
        paused_stage="research",
        cumulative_spend_usd=2.0,
        cycle_budget_usd=1.0,
        dispatch_estimate_usd=0.5,
    )
    path = vault / "_pipeline/BUDGET_PAUSED"
    atomic_write_json_marker(path, marker.to_json_dict())

    args = Namespace(force_budget=True)
    assert handle_budget_marker_on_resume(args, vault, 1) == 1

    err = capsys.readouterr().err
    assert "_pipeline/BUDGET_PAUSED" in err
    assert path.is_file()
