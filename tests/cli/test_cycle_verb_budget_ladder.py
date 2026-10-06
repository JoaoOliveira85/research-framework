"""`cycle` resolves its budget through the spec-061 ladder (issue #233).

Before this, the three run verbs told three different budget stories and
``--help`` could not tell you which. ``generate`` (and ``--resume``) resolved
the spec-061 ladder; ``cycle`` carried a hardcoded ``--budget-cap`` default of
$10.00 that never consulted settings at all — the fourth budget knob the spec
was written to eliminate; ``pipeline`` refused its own flag (issue #232).

These tests pin the ladder for ``cycle``: no hardcoded default anywhere on the
path, settings honoured, flag last word, and a standing pause marker refused
rather than walked past.
"""

from __future__ import annotations

import inspect
import json
from argparse import Namespace
from pathlib import Path
from typing import Any

import pytest

from research_framework.cli import build_parser
from research_framework.cli.research_cycles import _cmd_cycle
from research_framework.pipeline.budget_guard import (
    ApprovalRequiredMarker,
    BudgetPausedMarker,
    atomic_write_json_marker,
)


def _vault(tmp_path: Path, settings: str | None) -> Path:
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    if settings is not None:
        (vault / "settings.yaml").write_text(settings, encoding="utf-8")
    return vault


def _capture_run_single_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def _fake(vault_dir: Path, *args: Any, **kwargs: Any) -> int:
        calls.append({"vault_dir": vault_dir, "positional": args, **kwargs})
        return 0

    monkeypatch.setattr(
        "research_framework.pipeline.orchestrator.run_single_cycle", _fake
    )
    return calls


def _args(vault: Path, **over: Any) -> Namespace:
    base: dict[str, Any] = {
        "vault": vault,
        "cycle": 1,
        "budget_cap": None,
        "target_topics": None,
        "estimate_only": False,
    }
    base.update(over)
    return Namespace(**base)


def test_budget_cap_flag_has_no_hardcoded_default() -> None:
    """The $10.00 in ``_parser.py`` was the bug — absence must mean "ask the ladder"."""
    args = build_parser().parse_args(["cycle", "--vault", "/tmp/v", "--cycle", "1"])
    assert args.budget_cap is None, (
        "`cycle --budget-cap` still carries a hardcoded default; it must be "
        "None so the spec-061 ladder decides."
    )


def test_run_single_cycle_carries_no_hardcoded_dollar_or_cycle_default() -> None:
    from research_framework.pipeline.orchestrator import run_single_cycle

    sig = inspect.signature(run_single_cycle)
    assert sig.parameters["budget_cap"].default is None
    assert sig.parameters["max_cycles"].default is None


def test_run_cycle_steps_carries_no_hardcoded_dollar_or_cycle_default() -> None:
    from research_framework.pipeline.cycle_runner import run_cycle_steps

    sig = inspect.signature(run_cycle_steps)
    assert sig.parameters["budget_cap"].default is None
    assert sig.parameters["max_cycles"].default is None


def test_cycle_reads_the_dollar_cap_and_ceiling_from_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path, "pipeline:\n  max_cycles: 7\n  budget_usd: 3.5\n")
    calls = _capture_run_single_cycle(monkeypatch)

    assert _cmd_cycle(_args(vault)) == 0

    assert calls[0]["budget_cap"] == pytest.approx(3.5)
    assert calls[0]["max_cycles"] == 7


def test_cycle_flag_beats_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path, "pipeline:\n  max_cycles: 7\n  budget_usd: 3.5\n")
    calls = _capture_run_single_cycle(monkeypatch)

    assert _cmd_cycle(_args(vault, budget_cap=1.25)) == 0

    assert calls[0]["budget_cap"] == pytest.approx(1.25)


def test_cycle_zero_budget_is_unlimited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR3-Z2: one ladder, one meaning of zero — on every verb."""
    vault = _vault(tmp_path, "pipeline:\n  max_cycles: 2\n  budget_usd: 0\n")
    calls = _capture_run_single_cycle(monkeypatch)

    assert _cmd_cycle(_args(vault)) == 0

    assert calls[0]["budget_cap"] == 0.0, "0 must reach the guard as 'uncapped'"


def test_cycle_with_no_settings_falls_through_to_the_built_in_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from research_framework.pipeline.settings import DEFAULT_MAX_CYCLES

    vault = _vault(tmp_path, None)
    calls = _capture_run_single_cycle(monkeypatch)

    assert _cmd_cycle(_args(vault)) == 0

    assert calls[0]["max_cycles"] == DEFAULT_MAX_CYCLES
    assert calls[0]["budget_cap"] == 0.0


def test_cycle_rejects_a_negative_budget_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path, "pipeline:\n  max_cycles: 2\n")
    calls = _capture_run_single_cycle(monkeypatch)

    assert _cmd_cycle(_args(vault, budget_cap=-1.0)) == 2
    assert not calls
    assert "--budget-cap" in capsys.readouterr().err


def _write_budget_marker(vault: Path, *, cycle: int = 1) -> Path:
    marker = BudgetPausedMarker(
        pause_reason="dollar_cap_exceeded",
        cycle_number=cycle,
        paused_stage="note_writer",
        cumulative_spend_usd=4.0,
        cycle_budget_usd=2.0,
        dispatch_estimate_usd=0.5,
    )
    path = vault / "_pipeline" / "BUDGET_PAUSED"
    atomic_write_json_marker(path, marker.to_json_dict())
    return path


def _write_approval_marker(vault: Path, *, cycle: int = 1) -> Path:
    marker = ApprovalRequiredMarker(
        stage_name="note_writer",
        cycle_number=cycle,
        prompt_preview="write the notes",
        estimated_cost_usd=0.75,
        cumulative_spend_usd=1.5,
        tier="standard",
        agent="claude",
    )
    path = vault / "_pipeline" / "APPROVAL_REQUIRED"
    atomic_write_json_marker(path, marker.to_json_dict())
    return path


def test_cycle_refuses_to_run_over_a_standing_budget_pause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Only ``generate --resume`` honoured pause markers; ``cycle`` re-spent.

    ``cycle`` has no ``--force-budget`` / ``--approve`` surface, so it does not
    get to decide a pause — it refuses, names the marker, and points at the
    verb that can (``pause``) and the verb that resumes properly.
    """
    vault = _vault(tmp_path, "pipeline:\n  max_cycles: 2\n  budget_usd: 1.0\n")
    marker = _write_budget_marker(vault)
    calls = _capture_run_single_cycle(monkeypatch)

    rc = _cmd_cycle(_args(vault))

    assert rc == 2
    assert not calls, "a paused vault must not dispatch another cycle"
    err = capsys.readouterr().err
    assert str(marker) in err
    assert "pause" in err
    assert marker.is_file(), "refusing must not delete the operator's marker"


def test_cycle_refuses_to_run_over_a_standing_approval_pause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path, "pipeline:\n  max_cycles: 2\n")
    marker = _write_approval_marker(vault)
    calls = _capture_run_single_cycle(monkeypatch)

    rc = _cmd_cycle(_args(vault))

    assert rc == 2
    assert not calls
    assert str(marker) in capsys.readouterr().err
    assert marker.is_file()


def test_cycle_runs_normally_with_no_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path, "pipeline:\n  max_cycles: 2\n  budget_usd: 4.0\n")
    calls = _capture_run_single_cycle(monkeypatch)

    assert _cmd_cycle(_args(vault)) == 0
    assert len(calls) == 1


def test_cycle_refusal_survives_an_unreadable_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A marker this build cannot parse is still a pause — refuse, don't guess."""
    vault = _vault(tmp_path, "pipeline:\n  max_cycles: 2\n")
    (vault / "_pipeline" / "BUDGET_PAUSED").write_text("{not json", encoding="utf-8")
    calls = _capture_run_single_cycle(monkeypatch)

    assert _cmd_cycle(_args(vault)) == 2
    assert not calls
    assert "BUDGET_PAUSED" in capsys.readouterr().err


def test_pipeline_refusal_names_the_same_ladder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The third verb's story must be readable from its own refusal (#233)."""
    from research_framework.cli.research_cycles import _cmd_pipeline

    vault = _vault(tmp_path, "pipeline:\n  max_cycles: 2\n")
    args = Namespace(
        vault=vault,
        pipeline_cmd="full",
        budget_cap=1.0,
        quiet=True,
        json=False,
    )
    assert _cmd_pipeline(args) == 2
    err = capsys.readouterr().err
    assert "limits.cycle_budget_usd" in err


def test_marker_refusal_does_not_fire_for_another_cycles_budget_pause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A marker is vault-level; the refusal is deliberately cycle-agnostic.

    ``budget-marker.contract.md`` §1 keeps ONE marker per vault, and §4 makes
    resume re-check it whatever cycle it names. ``cycle`` cannot clear a pause,
    so the honest reading of "a pause is standing" is "any pause".
    """
    vault = _vault(tmp_path, "pipeline:\n  max_cycles: 5\n")
    _write_budget_marker(vault, cycle=1)
    calls = _capture_run_single_cycle(monkeypatch)

    assert _cmd_cycle(_args(vault, cycle=4)) == 2
    assert not calls


def test_settings_read_is_the_shared_resolver_not_a_second_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One ladder means one function — assert `cycle` calls it."""
    import research_framework.cli.research_cycles as rc_mod

    vault = _vault(tmp_path, "pipeline:\n  max_cycles: 3\n  budget_usd: 2.0\n")
    _capture_run_single_cycle(monkeypatch)
    seen: list[Path] = []
    real = rc_mod.resolve_cycle_budget_from_path

    def _spy(path: Path, **kwargs: Any):
        seen.append(path)
        return real(path, **kwargs)

    monkeypatch.setattr(rc_mod, "resolve_cycle_budget_from_path", _spy)
    assert _cmd_cycle(_args(vault)) == 0
    assert seen == [vault / "settings.yaml"]


def test_deprecated_cycles_block_warns_on_the_cycle_verb_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """FR4: the loud override must be loud on every verb, not just generate."""
    import logging

    vault = _vault(tmp_path, "cycles:\n  initial_max: 6\n")
    calls = _capture_run_single_cycle(monkeypatch)

    with caplog.at_level(logging.WARNING):
        assert _cmd_cycle(_args(vault)) == 0

    assert calls[0]["max_cycles"] == 6
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "pipeline.max_cycles" in joined


def test_cycle_still_threads_the_spec_and_target_topics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression guard for spec 074 — the ladder change must not drop these."""
    vault = _vault(tmp_path, "pipeline:\n  max_cycles: 2\n")
    (vault / "research.spec.md").write_text("bad spec", encoding="utf-8")
    calls = _capture_run_single_cycle(monkeypatch)

    rc = _cmd_cycle(_args(vault, target_topics=["a"]))

    assert rc == 2, "an unloadable spec + --target-topics is still a refusal"
    assert not calls


def test_marker_refusal_is_reported_before_any_settings_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The pause is the actionable fact; a config nit must not mask it."""
    vault = _vault(tmp_path, "pipeline:\n  max_cycles: 2\n")
    _write_budget_marker(vault)
    _capture_run_single_cycle(monkeypatch)

    assert _cmd_cycle(_args(vault, budget_cap=-5.0)) == 2
    assert "BUDGET_PAUSED" in capsys.readouterr().err


def test_marker_json_is_left_byte_identical_by_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path, "pipeline:\n  max_cycles: 2\n")
    marker = _write_budget_marker(vault)
    before = marker.read_bytes()
    _capture_run_single_cycle(monkeypatch)

    assert _cmd_cycle(_args(vault)) == 2
    assert marker.read_bytes() == before
    assert json.loads(before)["paused_stage"] == "note_writer"
