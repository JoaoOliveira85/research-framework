"""The TTY approval prompt must show what it is asking you to buy (#236).

``approval-marker.contract.md`` §5.1 step 1 is unambiguous — "load marker;
display stage, tier, ``estimated_cost_usd``, ``cumulative_spend_usd``,
``prompt_preview``" — and then step 2 prompts. The implementation went
straight to step 2, so an operator approved a paid dispatch with no idea what
it cost, what the run had already spent, or which tier it would run on. The
marker carried all of it; nothing rendered it.

Every field asserted here is one the marker already persisted.
"""

from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path

import pytest

from research_framework.cli.budget_resume import handle_approval_marker_on_resume
from research_framework.pipeline.budget_guard import (
    ApprovalRequiredMarker,
    approval_marker_path,
    atomic_write_json_marker,
)

_PREVIEW = "Write notes for: distributed tracing, retry budgets, and shed load"


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    return vault


def _write_marker(vault: Path, **over: object) -> ApprovalRequiredMarker:
    fields: dict[str, object] = {
        "stage_name": "note_writer",
        "cycle_number": 4,
        "prompt_preview": _PREVIEW,
        "estimated_cost_usd": 1.2345,
        "cumulative_spend_usd": 6.5,
        "tier": "flagship",
        "agent": "claude",
    }
    fields.update(over)
    marker = ApprovalRequiredMarker(**fields)  # type: ignore[arg-type]
    atomic_write_json_marker(approval_marker_path(vault), marker.to_json_dict())
    return marker


def _tty(monkeypatch: pytest.MonkeyPatch, *, answer: str = "n") -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: answer)


def _args(**over: object) -> Namespace:
    base: dict[str, object] = {"approve": None, "approve_all": False, "reject": None}
    base.update(over)
    return Namespace(**base)


def _output(capsys: pytest.CaptureFixture[str]) -> str:
    captured = capsys.readouterr()
    return captured.out + captured.err


def test_prompt_is_preceded_by_the_marker_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path)
    _write_marker(vault)
    _tty(monkeypatch, answer="n")

    assert handle_approval_marker_on_resume(_args(), vault) == 1

    text = _output(capsys)
    assert "note_writer" in text
    assert "flagship" in text, "tier (contract §5.1 step 1)"
    assert "claude" in text, "resolved agent"
    assert "1.2345" in text, "estimated_cost_usd"
    assert "6.5000" in text, "cumulative_spend_usd"
    assert "distributed tracing" in text, "prompt_preview"


def test_summary_names_the_projected_total_not_just_the_two_halves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """ "$1.23 now, $6.50 already" is two facts; the decision needs the sum."""
    vault = _vault(tmp_path)
    _write_marker(vault)
    _tty(monkeypatch, answer="n")

    handle_approval_marker_on_resume(_args(), vault)

    assert "7.7345" in _output(capsys)


def test_summary_is_shown_before_a_flag_driven_tty_approval_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--approve`` on a TTY still clears a gate; the operator still sees it."""
    vault = _vault(tmp_path)
    _write_marker(vault)
    _tty(monkeypatch)

    assert handle_approval_marker_on_resume(_args(approve="note_writer"), vault) == 0

    text = _output(capsys)
    assert "1.2345" in text and "flagship" in text


def test_summary_survives_a_marker_with_no_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``agent`` is optional per contract §3.2 — the render must not blow up."""
    vault = _vault(tmp_path)
    _write_marker(vault, agent=None)
    _tty(monkeypatch, answer="n")

    assert handle_approval_marker_on_resume(_args(), vault) == 1

    text = _output(capsys)
    assert "note_writer" in text and "1.2345" in text


def test_summary_goes_to_stderr_so_a_redirected_stdout_still_shows_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec 070 FR6's stream rule: the thing that stops a run goes to stderr."""
    vault = _vault(tmp_path)
    _write_marker(vault)
    _tty(monkeypatch, answer="n")

    handle_approval_marker_on_resume(_args(), vault)

    assert "1.2345" in capsys.readouterr().err


def test_headless_refusal_body_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Contract §5.2 step 4 pins that JSON body; this change must not widen it."""
    import json

    vault = _vault(tmp_path)
    _write_marker(vault)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

    assert handle_approval_marker_on_resume(_args(), vault) == 1

    err = capsys.readouterr().err.strip().splitlines()
    body = json.loads(err[-1])
    assert body == {"error": "approval_required", "stage": "note_writer"}


def test_rejecting_by_flag_does_not_print_a_prompt_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--reject`` is a decision already taken — there is nothing to weigh."""
    vault = _vault(tmp_path)
    _write_marker(vault)
    _tty(monkeypatch)

    assert handle_approval_marker_on_resume(_args(reject="note_writer"), vault) == 1

    assert "1.2345" not in _output(capsys)
