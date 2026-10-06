"""`pause show` / `pause clear` — inspect or abandon a pause (#237).

``budget-marker.contract.md`` §5 has anticipated an explicit cleanup command
since spec 033 shipped ("tasks may add ``./vault research --clear-pause``")
and nothing implemented it. An operator abandoning a paused cycle had to
delete ``_pipeline/BUDGET_PAUSED`` by hand, and no verb would tell them what
the marker said first — which stage, what it was about to cost, how much the
cycle had already spent.

``show`` is read-only and renders exactly the fields the resume path is about
to re-check; ``clear`` removes a marker only under an explicit acknowledgement.
"""

from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from research_framework.cli import build_parser
from research_framework.cli.pause import _cmd_pause
from research_framework.pipeline.budget_guard import (
    ApprovalRequiredMarker,
    BudgetPausedMarker,
    approval_decisions_path,
    approval_marker_path,
    atomic_write_json_marker,
    budget_marker_path,
)


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    return vault


def _budget_marker(vault: Path, **over: object) -> Path:
    fields: dict[str, object] = {
        "pause_reason": "dollar_cap_exceeded",
        "cycle_number": 3,
        "paused_stage": "note_writer",
        "cumulative_spend_usd": 4.25,
        "cycle_budget_usd": 5.0,
        "dispatch_estimate_usd": 1.5,
        "blocked_dispatch_preview": "write notes about retry budgets",
    }
    fields.update(over)
    marker = BudgetPausedMarker(**fields)  # type: ignore[arg-type]
    path = budget_marker_path(vault)
    atomic_write_json_marker(path, marker.to_json_dict())
    return path


def _approval_marker(vault: Path) -> Path:
    marker = ApprovalRequiredMarker(
        stage_name="verifier",
        cycle_number=3,
        prompt_preview="verify the notes",
        estimated_cost_usd=0.25,
        cumulative_spend_usd=4.25,
        tier="basic",
        agent="claude",
    )
    path = approval_marker_path(vault)
    atomic_write_json_marker(path, marker.to_json_dict())
    return path


def _args(vault: Path, cmd: str, **over: object) -> Namespace:
    base: dict[str, object] = {
        "vault": vault,
        "pause_cmd": cmd,
        "json": False,
        "yes": False,
        "marker": "all",
    }
    base.update(over)
    return Namespace(**base)


# --- registration ----------------------------------------------------------


def test_pause_is_a_registered_verb_with_a_handler() -> None:
    args = build_parser().parse_args(["pause", "show", "--vault", "/tmp/v"])
    assert callable(getattr(args, "func", None))
    assert args.pause_cmd == "show"


def test_pause_rejects_an_unknown_subcommand() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["pause", "detonate", "--vault", "/tmp/v"])


# --- show ------------------------------------------------------------------


def test_show_renders_every_field_the_resume_path_rechecks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path)
    _budget_marker(vault)

    assert _cmd_pause(_args(vault, "show")) == 0

    out = capsys.readouterr().out
    assert "dollar_cap_exceeded" in out
    assert "note_writer" in out
    assert "4.2500" in out, "cumulative spend"
    assert "5.0000" in out, "the cap it tripped"
    assert "1.5000" in out, "the blocked dispatch's estimate"
    assert "retry budgets" in out, "blocked_dispatch_preview"
    assert "cycle 3" in out.lower()


def test_show_is_read_only(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    path = _budget_marker(vault)
    before = path.read_bytes()

    _cmd_pause(_args(vault, "show"))

    assert path.read_bytes() == before


def test_show_reports_an_unpaused_vault_without_failing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path)

    assert _cmd_pause(_args(vault, "show")) == 0

    assert "no pause" in capsys.readouterr().out.lower()


def test_show_renders_both_markers_when_both_stand(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path)
    _budget_marker(vault)
    _approval_marker(vault)

    assert _cmd_pause(_args(vault, "show")) == 0

    out = capsys.readouterr().out
    assert "BUDGET_PAUSED" in out and "APPROVAL_REQUIRED" in out
    assert "verifier" in out and "note_writer" in out


def test_show_json_is_machine_readable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path)
    _budget_marker(vault)
    _approval_marker(vault)

    assert _cmd_pause(_args(vault, "show", json=True)) == 0

    doc = json.loads(capsys.readouterr().out)
    assert doc["paused"] is True
    assert doc["budget"]["pause_reason"] == "dollar_cap_exceeded"
    assert doc["budget"]["paused_stage"] == "note_writer"
    assert doc["approval"]["stage_name"] == "verifier"
    assert doc["approval"]["estimated_cost_usd"] == pytest.approx(0.25)


def test_show_json_on_an_unpaused_vault_is_still_valid_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path)

    assert _cmd_pause(_args(vault, "show", json=True)) == 0

    doc = json.loads(capsys.readouterr().out)
    assert doc == {"paused": False, "budget": None, "approval": None}


def test_show_does_not_fail_on_a_marker_it_cannot_parse(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A read-only inspector must be at its most useful on a broken marker."""
    vault = _vault(tmp_path)
    budget_marker_path(vault).write_text("{ not json", encoding="utf-8")

    assert _cmd_pause(_args(vault, "show")) == 0

    out = capsys.readouterr().out
    assert "BUDGET_PAUSED" in out
    assert "unreadable" in out.lower()


def test_show_flags_a_schema_version_this_build_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path)
    doc = json.loads(_budget_marker(vault).read_text(encoding="utf-8"))
    doc["schema_version"] = "9.9"
    budget_marker_path(vault).write_text(json.dumps(doc), encoding="utf-8")

    assert _cmd_pause(_args(vault, "show")) == 0

    assert "9.9" in capsys.readouterr().out


def test_show_refuses_a_missing_vault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _cmd_pause(_args(tmp_path / "nope", "show")) == 2
    assert "not found" in capsys.readouterr().err


# --- clear -----------------------------------------------------------------


def test_clear_needs_an_acknowledgement_headless(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path)
    path = _budget_marker(vault)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    assert _cmd_pause(_args(vault, "clear")) == 1

    assert path.is_file(), "an unacknowledged clear must not delete anything"
    assert "--yes" in capsys.readouterr().err


def test_clear_with_yes_removes_the_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path)
    path = _budget_marker(vault)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    assert _cmd_pause(_args(vault, "clear", yes=True)) == 0

    assert not path.exists()
    assert "cleared" in capsys.readouterr().out.lower()


def test_clear_on_a_tty_asks_and_honours_a_no(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path)
    path = _budget_marker(vault)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _p: "n")

    assert _cmd_pause(_args(vault, "clear")) == 1

    assert path.is_file()


def test_clear_on_a_tty_shows_what_is_about_to_be_abandoned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path)
    _budget_marker(vault)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _p: "y")

    assert _cmd_pause(_args(vault, "clear")) == 0

    out = capsys.readouterr().out
    assert "note_writer" in out and "4.2500" in out


def test_clear_marker_selector_clears_only_what_was_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path)
    budget = _budget_marker(vault)
    approval = _approval_marker(vault)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    assert _cmd_pause(_args(vault, "clear", yes=True, marker="approval")) == 0

    assert budget.is_file(), "budget pause untouched"
    assert not approval.exists()


def test_clear_all_clears_both(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _vault(tmp_path)
    budget = _budget_marker(vault)
    approval = _approval_marker(vault)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    assert _cmd_pause(_args(vault, "clear", yes=True)) == 0

    assert not budget.exists() and not approval.exists()


def test_clear_on_an_unpaused_vault_is_a_no_op_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path)

    assert _cmd_pause(_args(vault, "clear", yes=True)) == 0

    assert "no pause" in capsys.readouterr().out.lower()


def test_clearing_an_approval_pause_records_no_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Abandoning is not a verdict (approval-marker.contract.md §6.1).

    ``approval-decisions.json`` is the record of what an operator DECIDED.
    Writing ``approved: false`` for someone who walked away would put a
    decision in the cycle report that nobody made — the exact rule §6.1 spells
    out for the branches that refuse to guess.
    """
    vault = _vault(tmp_path)
    _approval_marker(vault)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    assert _cmd_pause(_args(vault, "clear", yes=True)) == 0

    assert not approval_decisions_path(vault).exists()


def test_clear_removes_a_marker_this_build_cannot_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one thing resume deliberately refuses to do, `clear` exists to do."""
    vault = _vault(tmp_path)
    budget_marker_path(vault).write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    assert _cmd_pause(_args(vault, "clear", yes=True)) == 0

    assert not budget_marker_path(vault).exists()
