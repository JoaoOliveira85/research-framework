"""``approval_gates_fired``, end to end from the production caller (issue #235).

The old coverage handed ``append_cycle_cost_report`` a literal
``approval_gates_fired=[...]`` that no production caller ever passed, so the
suite was green on plumbing nothing exercised. These tests start where a real
run starts — the operator's verdict inside
``handle_approval_marker_on_resume`` — and end where the operator reads it, in
``cycle-NNN-report.md``. Nothing in between is hand-fed.
"""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from research_framework.cli.budget_resume import handle_approval_marker_on_resume
from research_framework.pipeline.budget_guard import (
    ApprovalRequiredMarker,
    CycleSpendTally,
    atomic_write_json_marker,
)
from research_framework.pipeline.reporter import append_cycle_cost_report
from research_framework.pipeline.settings import LimitsSettings


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 1\n  budget_usd: 1.0\n",
        encoding="utf-8",
    )
    return vault


def _pause_at(vault: Path, stage: str, *, cycle: int = 1) -> None:
    marker = ApprovalRequiredMarker(
        stage_name=stage,
        cycle_number=cycle,
        prompt_preview="preview",
        estimated_cost_usd=0.2,
        cumulative_spend_usd=0.1,
        tier="standard",
    )
    atomic_write_json_marker(
        vault / "_pipeline/APPROVAL_REQUIRED", marker.to_json_dict()
    )


def _gates_fired(vault: Path, cycle: int = 1) -> list[dict]:
    """The ``approval_gates_fired`` rows a real cycle report would carry."""
    append_cycle_cost_report(
        vault,
        cycle,
        tally=CycleSpendTally(cycle_num=cycle),
        limits=LimitsSettings(),
    )
    text = (vault / "_pipeline/cycles" / f"cycle-{cycle:03d}-report.md").read_text(
        encoding="utf-8"
    )
    start = text.index("```json") + len("```json")
    end = text.index("```", start)
    return json.loads(text[start:end].strip())["approval_gates_fired"]


def _headless(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)


def _tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)


def test_headless_approval_reaches_the_cycle_cost_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _headless(monkeypatch)
    monkeypatch.setenv("RF_APPROVE_NOTE_WRITER_ACK", "1")
    vault = _vault(tmp_path)
    _pause_at(vault, "note_writer")

    args = Namespace(approve="note_writer", approve_all=False, reject=None)
    assert handle_approval_marker_on_resume(args, vault) == 0

    rows = _gates_fired(vault)
    assert rows == [
        {
            "stage": "note_writer",
            "approved": True,
            "decided_at": rows[0]["decided_at"],
            "decided_by_mode": "headless",
        }
    ]


def test_tty_approval_is_recorded_as_tty_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _tty(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: "y")
    vault = _vault(tmp_path)
    _pause_at(vault, "scout")

    args = Namespace(approve=None, approve_all=False, reject=None)
    assert handle_approval_marker_on_resume(args, vault) == 0

    rows = _gates_fired(vault)
    assert [(r["stage"], r["approved"], r["decided_by_mode"]) for r in rows] == [
        ("scout", True, "tty")
    ]


def test_tty_refusal_is_recorded_as_approved_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """approval-marker.contract.md §5.4: "cycle report logs ``approved: false``"."""
    _tty(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _: "n")
    vault = _vault(tmp_path)
    _pause_at(vault, "note_writer")

    args = Namespace(approve=None, approve_all=False, reject=None)
    assert handle_approval_marker_on_resume(args, vault) == 1

    rows = _gates_fired(vault)
    assert [(r["stage"], r["approved"]) for r in rows] == [("note_writer", False)]


def test_explicit_reject_flag_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _headless(monkeypatch)
    vault = _vault(tmp_path)
    _pause_at(vault, "note_writer")

    args = Namespace(approve=None, approve_all=False, reject="note_writer")
    assert handle_approval_marker_on_resume(args, vault) == 1

    rows = _gates_fired(vault)
    assert [(r["stage"], r["approved"], r["decided_by_mode"]) for r in rows] == [
        ("note_writer", False, "headless")
    ]


def test_approve_all_records_the_gated_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _headless(monkeypatch)
    monkeypatch.setenv("RF_APPROVE_ALL_ACK", "1")
    vault = _vault(tmp_path)
    _pause_at(vault, "verifier")

    args = Namespace(approve=None, approve_all=True, reject=None)
    assert handle_approval_marker_on_resume(args, vault) == 0

    assert [r["stage"] for r in _gates_fired(vault)] == ["verifier"]


def test_a_refusal_to_decide_records_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refusal to guess is not a verdict.

    The headless no-flags branch and the stage-mismatch branch both exit 1
    without the operator having said yes or no; recording either as
    ``approved: false`` would put a decision in the report that nobody made.
    """
    _headless(monkeypatch)
    vault = _vault(tmp_path)
    _pause_at(vault, "note_writer")

    no_flags = Namespace(approve=None, approve_all=False, reject=None)
    assert handle_approval_marker_on_resume(no_flags, vault) == 1

    monkeypatch.setenv("RF_APPROVE_SCOUT_ACK", "1")
    mismatch = Namespace(approve="scout", approve_all=False, reject=None)
    assert handle_approval_marker_on_resume(mismatch, vault) == 1

    assert _gates_fired(vault) == []


def test_a_decision_lands_on_its_own_cycles_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The verdict belongs to the cycle whose dispatch was gated, not to all."""
    _headless(monkeypatch)
    monkeypatch.setenv("RF_APPROVE_NOTE_WRITER_ACK", "1")
    vault = _vault(tmp_path)
    _pause_at(vault, "note_writer", cycle=3)

    args = Namespace(approve="note_writer", approve_all=False, reject=None)
    assert handle_approval_marker_on_resume(args, vault) == 0

    assert _gates_fired(vault, cycle=3)
    assert _gates_fired(vault, cycle=2) == []


def test_no_gate_no_rows(tmp_path: Path) -> None:
    """A cycle nobody gated reports an empty list, not a missing key."""
    vault = _vault(tmp_path)
    assert _gates_fired(vault) == []
