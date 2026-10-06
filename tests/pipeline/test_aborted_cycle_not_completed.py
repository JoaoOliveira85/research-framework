"""Spec 070 F10 — an aborted cycle must not count as a completed one.

`_highest_completed_cycle` anchors `--resume` on the highest
`cycle-NNN-quality-report.json`, and documents the assumption that makes that
safe:

    A cycle that aborts mid-stream never writes the report, so we correctly
    fall back to the prior cycle as the resume anchor.

That assumption is false. Verified across all five of the operator's live
vaults: every aborted (exit 2) cycle had written its quality report. The
consequence is silent work loss — resume advances PAST the aborted cycle, so
its topics are never retried. feeds-vault's aborted cycle 9 had
`notes_written: 11, notes_rejected: 11` and would have been skipped.

The fix records an explicit abort marker and teaches the anchor to skip it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from research_framework.cli.research_resume import _highest_completed_cycle
from research_framework.pipeline.orchestrator import (
    clear_cycle_aborted,
    mark_cycle_aborted,
)


def _completed(vault: Path, n: int) -> None:
    d = vault / "_pipeline" / "cycles"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"cycle-{n:03d}-quality-report.json").write_text(json.dumps({}), "utf-8")


def test_aborted_cycle_is_not_the_resume_anchor(tmp_path: Path) -> None:
    """The regression: cycle 11 aborted, so resume must return to 11 — not 12."""
    for n in (9, 10, 11):
        _completed(tmp_path, n)
    mark_cycle_aborted(tmp_path, 11, reason="cycle 11 aborted (exit 2)")

    assert _highest_completed_cycle(tmp_path) == 10


def test_clean_cycles_are_unaffected(tmp_path: Path) -> None:
    for n in (1, 2, 3):
        _completed(tmp_path, n)
    assert _highest_completed_cycle(tmp_path) == 3


def test_marker_is_cleared_when_the_cycle_later_succeeds(tmp_path: Path) -> None:
    """Re-running the aborted cycle successfully must restore it as the anchor."""
    for n in (9, 10, 11):
        _completed(tmp_path, n)
    mark_cycle_aborted(tmp_path, 11, reason="boom")
    assert _highest_completed_cycle(tmp_path) == 10

    clear_cycle_aborted(tmp_path, 11)
    assert _highest_completed_cycle(tmp_path) == 11


def test_clearing_an_unmarked_cycle_is_a_noop(tmp_path: Path) -> None:
    _completed(tmp_path, 1)
    clear_cycle_aborted(tmp_path, 1)
    assert _highest_completed_cycle(tmp_path) == 1


def test_only_the_aborted_cycle_is_skipped(tmp_path: Path) -> None:
    """An abort in the middle must not discard the later clean cycles."""
    for n in (1, 2, 3, 4):
        _completed(tmp_path, n)
    mark_cycle_aborted(tmp_path, 2, reason="boom")
    assert _highest_completed_cycle(tmp_path) == 4


def test_marker_records_the_reason(tmp_path: Path) -> None:
    mark_cycle_aborted(tmp_path, 7, reason="scout report not written")
    marker = tmp_path / "_pipeline" / "cycles" / "cycle-007-aborted.json"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["cycle"] == 7
    assert "scout report not written" in payload["reason"]


def test_no_cycles_dir_returns_none(tmp_path: Path) -> None:
    assert _highest_completed_cycle(tmp_path) is None


# ---------------------------------------------------------------------------
# A cycle that leaves by exception — Ctrl-C, a budget pause, a crash — is not
# a completed one either. Only the rc=2 return used to write the marker.
# ---------------------------------------------------------------------------


def _run_cycles_with_a_cycle_that_raises(
    vault: Path, monkeypatch: pytest.MonkeyPatch, cycle: int, leave
) -> None:
    """Drive ``run_cycles`` into ``cycle``, which exits through the real guard.

    The stand-in for ``run_single_cycle`` does what the cycle runner does on
    its way out: it is inside ``_quality_report_guard``, which writes the
    quality report and clears ``in_progress_cycle`` on every exit path.
    """
    from research_framework.pipeline import cycle_runner, cycle_state
    from research_framework.pipeline import orchestrator as orch
    from tests.cli.test_fr6_exit_reason_visibility import _budget, _spec

    def _cycle(vault_dir, cycle_num, budget_cap, max_cycles, spec=None, resume=False):
        cycle_state.write(vault_dir, in_progress_cycle=cycle_num)
        cycle_dir = vault_dir / "_pipeline" / "cycles" / f"cycle-{cycle_num:03d}"
        with cycle_runner._quality_report_guard(cycle_dir) as state:
            state.vault_dir = vault_dir
            state.cycle_num = cycle_num
            leave(vault_dir, cycle_num)
        raise AssertionError("the cycle was meant to leave by exception")

    monkeypatch.setattr(orch, "run_single_cycle", _cycle)
    monkeypatch.setattr(orch, "merge_expected_filenames_from_scan", lambda _v: None)
    orch.run_cycles(
        _spec(vault), vault, start_cycle=cycle, resume=True, budget=_budget(5)
    )


def _resume_anchor(vault: Path) -> int:
    from research_framework.cli.research_resume import _resolve_resume_cycle

    return _resolve_resume_cycle(argparse.Namespace(output=vault, cycle=None))


@pytest.mark.regression
@pytest.mark.parametrize(
    "exc",
    [KeyboardInterrupt(), SystemExit(1), RuntimeError("crash mid-research")],
    ids=["ctrl-c", "pause", "crash"],
)
def test_a_cycle_that_leaves_by_exception_is_the_resume_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exc: BaseException
) -> None:
    """Cycle 2 was interrupted, so ``--resume`` must return to 2 — not 3."""
    vault = tmp_path / "vault"
    _completed(vault, 1)

    def _leave(_vault: Path, _cycle: int) -> None:
        raise exc

    with pytest.raises(type(exc)):
        _run_cycles_with_a_cycle_that_raises(vault, monkeypatch, 2, _leave)

    assert (vault / "_pipeline" / "cycles" / "cycle-002-quality-report.json").is_file()
    assert _resume_anchor(vault) == 2


@pytest.mark.regression
def test_a_budget_pause_is_re_checked_against_the_cycle_it_paused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pause must still be standing when the operator resumes.

    Anchored one cycle late, the resume re-checked the cap against a cycle
    that had spent nothing, found it "now satisfied", cleared ``BUDGET_PAUSED``
    without ``--force-budget`` and never went back to the paused cycle.
    """
    from research_framework.cli import budget_resume
    from research_framework.pipeline.budget_guard import (
        BudgetPausedMarker,
        budget_marker_path,
        pause_for_budget,
    )

    vault = tmp_path / "vault"
    _completed(vault, 1)
    (vault / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 5\n  budget_usd: 10.0\n"
        "limits:\n  cycle_budget_usd: 1.0\n",
        encoding="utf-8",
    )
    calls = vault / "_pipeline" / "cycles" / "cycle-002" / "agent-calls"
    calls.mkdir(parents=True)
    (calls / "scout.json").write_text(
        json.dumps({"schema_version": "1.2", "cost_usd": 3.0, "agent": "claude"}),
        encoding="utf-8",
    )

    def _pause(vault_dir: Path, cycle_num: int) -> None:
        pause_for_budget(
            vault_dir,
            BudgetPausedMarker(
                pause_reason="dollar_cap_exceeded",
                cycle_number=cycle_num,
                paused_stage="note_writer",
                cumulative_spend_usd=3.0,
                cycle_budget_usd=1.0,
                dispatch_estimate_usd=0.5,
            ),
        )

    with pytest.raises(SystemExit):
        _run_cycles_with_a_cycle_that_raises(vault, monkeypatch, 2, _pause)

    anchor = _resume_anchor(vault)
    assert anchor == 2
    assert budget_resume.peek_paused_stage(vault, anchor) == "note_writer"
    monkeypatch.setattr(budget_resume, "is_interactive_tty", lambda: False)
    args = argparse.Namespace(output=vault, cycle=None, force_budget=False)
    assert budget_resume.handle_budget_marker_on_resume(args, vault, anchor) != 0
    assert budget_marker_path(vault).is_file()


def test_the_marker_is_cleared_when_the_interrupted_cycle_later_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from research_framework.pipeline import orchestrator as orch
    from tests.cli.test_fr6_exit_reason_visibility import _budget, _spec

    vault = tmp_path / "vault"
    _completed(vault, 1)

    def _leave(_vault: Path, _cycle: int) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _run_cycles_with_a_cycle_that_raises(vault, monkeypatch, 2, _leave)
    assert _highest_completed_cycle(vault) == 1

    monkeypatch.setattr(orch, "run_single_cycle", lambda *_a, **_k: 0)
    monkeypatch.setattr(orch, "_run_health_gate", lambda _v: [])
    monkeypatch.setattr(orch, "scan_stubs", lambda _v, _s: [])
    orch.run_cycles(_spec(vault), vault, start_cycle=2, resume=True, budget=_budget(2))

    assert _highest_completed_cycle(vault) == 2


# ---------------------------------------------------------------------------
# The `cycle` verb calls run_single_cycle itself, so it owes the same marker.
# ---------------------------------------------------------------------------


def _cycle_verb(
    vault: Path, monkeypatch: pytest.MonkeyPatch, cycle: int, outcome: object
) -> int:
    """Run ``research-framework cycle`` on ``cycle``, which ends in ``outcome``.

    Like the real runner's guard, the stand-in writes the cycle's quality
    report on every exit before returning ``outcome`` or raising it.
    """
    from research_framework.cli.research_cycles import _cmd_cycle

    def _cycle(vault_dir: Path, **kwargs: object) -> object:
        _completed(vault_dir, kwargs["cycle_num"])  # type: ignore[arg-type]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(
        "research_framework.pipeline.orchestrator.run_single_cycle", _cycle
    )
    return _cmd_cycle(
        argparse.Namespace(
            vault=vault,
            cycle=cycle,
            budget_cap=None,
            target_topics=None,
            estimate_only=False,
        )
    )


@pytest.mark.regression
@pytest.mark.parametrize(
    "outcome",
    [2, KeyboardInterrupt(), SystemExit(1), RuntimeError("crash mid-research")],
    ids=["rc2", "ctrl-c", "pause", "crash"],
)
def test_the_cycle_verb_marks_a_cycle_that_did_not_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: object
) -> None:
    """Unmarked, cycle 2 read as completed and ``--resume`` went on to 3."""
    vault = tmp_path / "vault"
    _completed(vault, 1)

    if isinstance(outcome, BaseException):
        with pytest.raises(type(outcome)):
            _cycle_verb(vault, monkeypatch, 2, outcome)
    else:
        assert _cycle_verb(vault, monkeypatch, 2, outcome) == 2

    assert _highest_completed_cycle(vault) == 1


def test_the_cycle_verb_clears_the_marker_when_the_cycle_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    _completed(vault, 1)
    mark_cycle_aborted(vault, 2, reason="cycle 2 aborted (exit 2)")

    assert _cycle_verb(vault, monkeypatch, 2, 0) == 0

    assert _highest_completed_cycle(vault) == 2
