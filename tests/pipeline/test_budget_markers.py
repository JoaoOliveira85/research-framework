"""Tier-2/3 budget and approval marker tests (spec 033)."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.pipeline.budget_guard import (
    ApprovalRequiredMarker,
    BudgetPausedMarker,
    atomic_write_json_marker,
    pause_for_approval,
    pause_for_budget,
    validate_approval_required_marker,
    validate_budget_paused_marker,
)


def test_budget_paused_marker_roundtrip_json_dict(tmp_path: Path) -> None:
    for reason in (
        "dollar_cap_exceeded",
        "wallclock_exceeded",
        "codex_token_cap_exceeded",
    ):
        marker = BudgetPausedMarker(
            pause_reason=reason,
            cycle_number=1,
            paused_stage="scout",
            cumulative_spend_usd=1.0,
            cycle_budget_usd=2.0,
            dispatch_estimate_usd=0.5,
            codex_tokens_cumulative=100 if "codex" in reason else None,
            codex_token_budget=200 if "codex" in reason else None,
            wallclock_elapsed_seconds=61.0 if reason == "wallclock_exceeded" else None,
            wallclock_cap_seconds=60.0 if reason == "wallclock_exceeded" else None,
        )
        path = tmp_path / f"budget-{reason}.json"
        atomic_write_json_marker(path, marker.to_json_dict())
        loaded = BudgetPausedMarker.from_path(path)
        assert loaded.pause_reason == reason
        assert loaded.pause_reason != "approval_required"


def test_approval_required_marker_roundtrip_json_dict(tmp_path: Path) -> None:
    marker = ApprovalRequiredMarker(
        stage_name="note_writer",
        cycle_number=2,
        prompt_preview="preview text",
        estimated_cost_usd=0.42,
        cumulative_spend_usd=1.1,
        tier="standard",
        agent="claude",
    )
    path = tmp_path / "approval.json"
    atomic_write_json_marker(path, marker.to_json_dict())
    loaded = ApprovalRequiredMarker.from_path(path)
    assert loaded.stage_name == "note_writer"
    assert loaded.estimated_cost_usd == 0.42


def test_atomic_write_json_marker_uses_os_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The marker writer must go through ``os.replace`` to be torn-write safe.

    As of the 0.6.x quality pass, ``atomic_write_json_marker`` delegates to
    ``research_framework.pipeline.atomic_write.write_text`` (the canonical
    spec-023 implementation), so we spy on ``os.replace`` at that module's
    boundary rather than at ``budget_guard``'s.
    """
    calls: list[tuple[str, str]] = []

    import os as real_os

    original_replace = real_os.replace

    def spy_replace(src: str, dst: str) -> None:
        calls.append((src, dst))
        original_replace(src, dst)

    monkeypatch.setattr(
        "research_framework.pipeline.atomic_write.os.replace", spy_replace
    )
    final = tmp_path / "marker.json"
    atomic_write_json_marker(final, {"schema_version": "1.0", "ok": True})
    assert final.is_file()
    assert len(calls) == 1, (
        f"expected exactly one os.replace call (tmp -> final), got {len(calls)}"
    )
    assert calls[0][1] == final


def test_budget_marker_schema_dollar_cap_exceeded_positive_cycle_budget() -> None:
    doc = BudgetPausedMarker(
        pause_reason="dollar_cap_exceeded",
        cycle_number=1,
        paused_stage="scout",
        cumulative_spend_usd=1.0,
        cycle_budget_usd=0.01,
        dispatch_estimate_usd=0.02,
    ).to_json_dict()
    validate_budget_paused_marker(doc)
    bad = dict(doc)
    bad["cycle_budget_usd"] = 0.0
    with pytest.raises(ValueError):
        validate_budget_paused_marker(bad)


def test_budget_marker_schema_wallclock_exceeded_requires_elapsed_and_cap() -> None:
    good = BudgetPausedMarker(
        pause_reason="wallclock_exceeded",
        cycle_number=1,
        paused_stage="scout",
        cumulative_spend_usd=0.0,
        cycle_budget_usd=1.0,
        dispatch_estimate_usd=0.0,
        wallclock_elapsed_seconds=120.0,
        wallclock_cap_seconds=60.0,
    ).to_json_dict()
    validate_budget_paused_marker(good)
    bad = dict(good)
    del bad["wallclock_elapsed_seconds"]
    with pytest.raises(ValueError):
        validate_budget_paused_marker(bad)


def test_budget_marker_schema_codex_token_cap_exceeded_requires_token_fields() -> None:
    good = BudgetPausedMarker(
        pause_reason="codex_token_cap_exceeded",
        cycle_number=1,
        paused_stage="research",
        cumulative_spend_usd=0.0,
        cycle_budget_usd=1.0,
        dispatch_estimate_usd=0.0,
        codex_tokens_cumulative=9000,
        codex_token_budget=8000,
    ).to_json_dict()
    validate_budget_paused_marker(good)
    bad = dict(good)
    del bad["codex_token_budget"]
    with pytest.raises(ValueError):
        validate_budget_paused_marker(bad)


def test_budget_marker_schema_rejects_an_unknown_schema_version() -> None:
    """§2.4 pins ``schema_version`` to ``const: "1.0"`` (issue #231).

    Presence was checked; the value was not, so a marker claiming any version
    at all sailed through the validator — which mattered the moment resume
    started calling it.
    """
    doc = BudgetPausedMarker(
        pause_reason="dollar_cap_exceeded",
        cycle_number=1,
        paused_stage="scout",
        cumulative_spend_usd=0.0,
        cycle_budget_usd=1.0,
        dispatch_estimate_usd=0.0,
    ).to_json_dict()
    validate_budget_paused_marker(doc)
    bad = dict(doc)
    bad["schema_version"] = "9.9"
    with pytest.raises(ValueError, match="schema_version"):
        validate_budget_paused_marker(bad)


def test_budget_marker_schema_rejects_approval_required_pause_reason() -> None:
    doc = BudgetPausedMarker(
        pause_reason="dollar_cap_exceeded",
        cycle_number=1,
        paused_stage="scout",
        cumulative_spend_usd=0.0,
        cycle_budget_usd=1.0,
        dispatch_estimate_usd=0.0,
    ).to_json_dict()
    doc["pause_reason"] = "approval_required"
    with pytest.raises(ValueError):
        validate_budget_paused_marker(doc)


def test_approval_marker_schema_accepts_prompt_preview_500_chars() -> None:
    preview = "x" * 500
    doc = ApprovalRequiredMarker(
        stage_name="research",
        cycle_number=1,
        prompt_preview=preview,
        estimated_cost_usd=0.1,
        cumulative_spend_usd=0.0,
        tier="basic",
    ).to_json_dict()
    validate_approval_required_marker(doc)


def test_approval_marker_schema_rejects_prompt_preview_over_500_chars() -> None:
    doc = {
        "schema_version": "1.0",
        "stage_name": "research",
        "cycle_number": 1,
        "paused_at": "2026-01-01T00:00:00Z",
        "prompt_preview": "y" * 501,
        "estimated_cost_usd": 0.1,
        "cumulative_spend_usd": 0.0,
        "tier": "basic",
    }
    with pytest.raises(ValueError):
        validate_approval_required_marker(doc)


def test_pause_for_budget_writes_marker_before_exit(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    marker = BudgetPausedMarker(
        pause_reason="dollar_cap_exceeded",
        cycle_number=1,
        paused_stage="scout",
        cumulative_spend_usd=1.0,
        cycle_budget_usd=1.0,
        dispatch_estimate_usd=0.5,
    )
    with pytest.raises(SystemExit) as exc:
        pause_for_budget(vault, marker)
    assert exc.value.code == 1
    assert (vault / "_pipeline/BUDGET_PAUSED").is_file()


def test_pause_for_approval_writes_marker_before_exit(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    marker = ApprovalRequiredMarker(
        stage_name="note_writer",
        cycle_number=1,
        prompt_preview="hello",
        estimated_cost_usd=0.2,
        cumulative_spend_usd=0.1,
        tier="standard",
    )
    with pytest.raises(SystemExit) as exc:
        pause_for_approval(vault, marker)
    assert exc.value.code == 1
    assert (vault / "_pipeline/APPROVAL_REQUIRED").is_file()


def test_approval_gate_writes_approval_required_not_budget_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from research_framework.pipeline import budget_guard as bg
    from research_framework.pipeline.settings import LimitsSettings, VaultSettings

    vault = tmp_path / "vault"
    vault.mkdir()
    settings = VaultSettings(
        max_cycles=1,
        budget_usd=1.0,
        approval_gates=["research"],
        limits=LimitsSettings(cycle_budget_usd=100.0),
    )
    tally = bg.CycleSpendTally(cycle_num=1)
    monkeypatch.setattr(
        bg,
        "check_pre_dispatch",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "research_framework.pipeline.cost_estimator.estimate_dispatch",
        lambda **kwargs: type(
            "E",
            (),
            {
                "cost_usd": 0.1,
                "codex_tokens": 0,
                "estimation_method": "default_ceiling",
                "vendor": "claude",
            },
        )(),
    )
    marker = bg.check_approval_gate(
        vault_dir=vault,
        vault_settings=settings,
        tally=tally,
        stage="research",
        prompt_text="prompt",
        tier="standard",
        agent="claude",
        limits=settings.limits,
    )
    assert marker is not None
    with pytest.raises(SystemExit):
        bg.pause_for_approval(vault, marker)
    assert (vault / "_pipeline/APPROVAL_REQUIRED").is_file()
    assert not (vault / "_pipeline/BUDGET_PAUSED").exists()
