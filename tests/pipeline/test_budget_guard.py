"""Tier-2/3 budget_guard tests (spec 033)."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import pytest

from research_framework.pipeline.budget_guard import (
    CycleSpendTally,
    check_approval_gate,
    check_pre_dispatch,
    collect_tier_cost_warnings,
    list_sidecars_v11,
    maybe_emit_budget_warn,
    redact_preview,
    refresh_actuals,
)
from research_framework.pipeline.settings import LimitsSettings, VaultSettings

_FIXTURE_VAULT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "cost_enforcement" / "vault"
)


def test_cycle_spend_tally_initial_state() -> None:
    tally = CycleSpendTally()
    assert tally.actual_usd == 0.0
    assert tally.actual_codex_tokens == 0
    assert tally.warn_emitted is False


def test_list_sidecars_v11_reads_agent_calls_only() -> None:
    rows = list_sidecars_v11(_FIXTURE_VAULT, 1)
    assert len(rows) == 8
    assert all(r.get("schema_version") == "1.1" for r in rows)


def test_list_sidecars_v11_ignores_non_1_1_schema() -> None:
    rows = list_sidecars_v11(_FIXTURE_VAULT, 1)
    assert not any(r.get("stage") == "stale" for r in rows)


def test_refresh_actuals_sums_multi_batch_and_retry_sidecars() -> None:
    tally = CycleSpendTally(cycle_num=1)
    refresh_actuals(_FIXTURE_VAULT, 1, tally)
    expected = 0.20 + 0.15 + 0.05 + 0.03 + 0.12 + 0.08 + 0.11 + 0.07
    assert abs(tally.actual_usd - expected) < 0.001


def test_refresh_actuals_includes_failed_sidecar_cost_usd() -> None:
    tally = CycleSpendTally(cycle_num=1)
    refresh_actuals(_FIXTURE_VAULT, 1, tally)
    assert tally.actual_usd >= 0.07


def test_refresh_actuals_sums_codex_tokens_only_for_codex_agent() -> None:
    tally = CycleSpendTally(cycle_num=1)
    refresh_actuals(_FIXTURE_VAULT, 1, tally)
    assert tally.actual_codex_tokens == 300


def _limits(**kwargs: object) -> LimitsSettings:
    return LimitsSettings(**kwargs)  # type: ignore[arg-type]


def test_pre_dispatch_allows_dispatch_when_actual_plus_estimate_equals_cap() -> None:
    tally = CycleSpendTally(actual_usd=0.90)
    limits = _limits(cycle_budget_usd=1.0)
    assert (
        check_pre_dispatch(
            tally=tally,
            limits=limits,
            estimate_cost_usd=0.10,
            estimate_codex_tokens=0,
            stage="scout",
            agent="claude",
        )
        is None
    )


def test_pre_dispatch_pauses_dollar_cap_on_strict_exceed() -> None:
    tally = CycleSpendTally(actual_usd=0.95)
    limits = _limits(cycle_budget_usd=1.0)
    result = check_pre_dispatch(
        tally=tally,
        limits=limits,
        estimate_cost_usd=0.10,
        estimate_codex_tokens=0,
        stage="scout",
        agent="claude",
    )
    assert result is not None
    assert result.marker.pause_reason == "dollar_cap_exceeded"


def test_pre_dispatch_wallclock_exceeded_marker_conditional_fields() -> None:
    tally = CycleSpendTally(cycle_started_mono=time.monotonic() - 120.0)
    limits = _limits(cycle_wallclock_budget_minutes=1)
    result = check_pre_dispatch(
        tally=tally,
        limits=limits,
        estimate_cost_usd=0.0,
        estimate_codex_tokens=0,
        stage="scout",
        agent="claude",
    )
    assert result is not None
    assert result.marker.pause_reason == "wallclock_exceeded"
    assert result.marker.wallclock_elapsed_seconds is not None
    assert result.marker.wallclock_cap_seconds == 60.0


def test_pre_dispatch_codex_token_cap_exceeded_marker_conditional_fields() -> None:
    tally = CycleSpendTally(actual_codex_tokens=7900)
    limits = _limits(codex_token_budget=8000)
    result = check_pre_dispatch(
        tally=tally,
        limits=limits,
        estimate_cost_usd=0.1,
        estimate_codex_tokens=200,
        stage="research",
        agent="codex",
    )
    assert result is not None
    assert result.marker.pause_reason == "codex_token_cap_exceeded"
    assert result.marker.codex_tokens_cumulative == 8100
    assert result.marker.codex_token_budget == 8000


def test_pre_dispatch_excludes_local_zero_cost_from_dollar_increment() -> None:
    tally = CycleSpendTally(actual_usd=0.99)
    limits = _limits(cycle_budget_usd=1.0)
    assert (
        check_pre_dispatch(
            tally=tally,
            limits=limits,
            estimate_cost_usd=0.50,
            estimate_codex_tokens=0,
            stage="local",
            agent="local",
        )
        is None
    )


def test_soft_warn_emitted_once_at_cycle_budget_warn_threshold(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tally = CycleSpendTally(actual_usd=0.85)
    limits = _limits(cycle_budget_usd=1.0, cycle_budget_warn_at=0.80)
    with caplog.at_level(logging.WARNING):
        maybe_emit_budget_warn(tally, limits)
        maybe_emit_budget_warn(tally, limits)
    assert tally.warn_emitted is True
    assert sum(1 for r in caplog.records if r.levelno == logging.WARNING) == 1


def test_collect_tier_cost_warnings_one_row_per_offending_sidecar() -> None:
    sidecars = list_sidecars_v11(_FIXTURE_VAULT, 1)
    warnings = collect_tier_cost_warnings(sidecars, {"basic": 0.05, "standard": 0.05})
    assert len(warnings) >= 2
    assert all("delta" in w for w in warnings)


def test_check_approval_gate_runs_after_budget_pre_check_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = VaultSettings(
        max_cycles=1,
        budget_usd=1.0,
        approval_gates=["note_writer"],
        limits=_limits(cycle_budget_usd=100.0),
    )
    tally = CycleSpendTally()
    marker = check_approval_gate(
        vault_dir=_FIXTURE_VAULT,
        vault_settings=settings,
        tally=tally,
        stage="note_writer",
        prompt_text="x",
        tier="basic",
        agent="claude",
        limits=settings.limits,
    )
    assert marker is not None
    assert marker.stage_name == "note_writer"


def test_prompt_preview_redacts_api_key_patterns() -> None:
    raw = "key=sk-abcdefghijklmnopqrstuvwxyz1234567890"
    out = redact_preview(raw, max_len=500)
    assert "sk-" not in out
    assert "[REDACTED]" in out


def test_cycle_runner_invokes_pre_dispatch_and_refresh_hooks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    from research_framework.pipeline._helpers import script_runner as h
    from research_framework.pipeline.budget_guard import CycleBudgetSession
    from research_framework.pipeline.cycle_runner import (
        _install_budget_run_script_guard,
    )
    from research_framework.pipeline.settings import load_vault_settings

    calls: list[str] = []

    def spy_before(self, **kwargs: object) -> None:
        calls.append("before")

    def spy_after(self) -> None:
        calls.append("after")

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 1\n  budget_usd: 10.0\n"
        "limits:\n  cycle_budget_usd: 100.0\n",
        encoding="utf-8",
    )
    (vault / "scripts").mkdir()
    script = vault / "scripts" / "agent_call.py"
    script.write_text('print("ok")\n', encoding="utf-8")
    settings = load_vault_settings(vault)
    session = CycleBudgetSession(vault, 1, settings)
    monkeypatch.setattr(CycleBudgetSession, "before_agent_call", spy_before)
    monkeypatch.setattr(CycleBudgetSession, "after_agent_call", spy_after)
    _install_budget_run_script_guard(session)
    h._run_script(sys.executable, script, "--stage", "scout", env={})
    assert calls == ["before", "after"]


def test_scout_correction_retry_honors_budget_run_script_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scout validation retry must call through script_runner._run_script binding."""
    import json
    import sys

    from research_framework.pipeline._helpers import scout_correction
    from research_framework.pipeline.budget_guard import CycleBudgetSession
    from research_framework.pipeline.cycle_runner import (
        _install_budget_run_script_guard,
    )
    from research_framework.pipeline.settings import load_vault_settings

    calls: list[str] = []

    def spy_before(self, **kwargs: object) -> None:
        calls.append("before")

    def spy_after(self) -> None:
        calls.append("after")

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 1\n  budget_usd: 10.0\n"
        "limits:\n  cycle_budget_usd: 100.0\n",
        encoding="utf-8",
    )
    scripts_dir = vault / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "agent_call.py").write_text('print("ok")\n', encoding="utf-8")
    (scripts_dir / "validate_cycle.py").write_text('print("ok")\n', encoding="utf-8")

    cycles_dir = vault / "_pipeline" / "cycles"
    cycles_dir.mkdir(parents=True)
    cycle_num = 1
    cycle_3 = "001"
    scout_report = cycles_dir / f"cycle-{cycle_3}-scout.json"
    scout_report.write_text('{"schema_version":"2.0"}', encoding="utf-8")
    sidecar = scout_report.with_suffix(scout_report.suffix + ".validation.json")
    sidecar.write_text(
        json.dumps({"errors": ["required source 'open_web' not in sources_consulted"]}),
        encoding="utf-8",
    )

    scout_prompt_src = vault / "scout_prompt.j2"
    scout_prompt_src.write_text("{CYCLE_NUM}", encoding="utf-8")
    scout_prompt_rendered = cycles_dir / f"cycle-{cycle_3}-scout-prompt.md"

    settings = load_vault_settings(vault)
    session = CycleBudgetSession(vault, 1, settings)
    monkeypatch.setattr(CycleBudgetSession, "before_agent_call", spy_before)
    monkeypatch.setattr(CycleBudgetSession, "after_agent_call", spy_after)
    _install_budget_run_script_guard(session)

    exit_code = scout_correction._retry_scout_with_validation_directive(
        python_bin=sys.executable,
        scripts_dir=scripts_dir,
        vault_dir=vault,
        cycles_dir=cycles_dir,
        cycle_num=cycle_num,
        cycle_3=cycle_3,
        scout_report=scout_report,
        scout_prompt_src=scout_prompt_src,
        scout_prompt_rendered=scout_prompt_rendered,
        max_cycles=1,
        budget_cap=10.0,
        env={},
    )

    assert exit_code == 0
    assert calls == ["before", "after"], (
        "scout retry agent_call must observe script_runner._run_script guard"
    )


def test_cycle_runner_invokes_approval_gate_before_gated_dispatch(
    tmp_path: Path,
) -> None:
    from research_framework.pipeline.budget_guard import CycleBudgetSession
    from research_framework.pipeline.settings import LimitsSettings, VaultSettings

    vault = tmp_path / "vault"
    vault.mkdir()
    settings = VaultSettings(
        max_cycles=1,
        budget_usd=1.0,
        approval_gates=["scout"],
        limits=LimitsSettings(cycle_budget_usd=100.0),
    )
    session = CycleBudgetSession(vault, 1, settings)
    with pytest.raises(SystemExit):
        session.before_agent_call(stage="scout", prompt_text="gate me")
    assert (vault / "_pipeline/APPROVAL_REQUIRED").is_file()
