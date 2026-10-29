"""Issue #14: an over-cap refusal names the one setting that clears it."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from research_framework.cli.budget_resume import handle_budget_marker_on_resume
from research_framework.pipeline.budget_guard import (
    BudgetPausedMarker,
    atomic_write_json_marker,
    pause_for_budget,
)

_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "cost_enforcement" / "vault"
)
_ALL = (
    "limits.cycle_budget_usd",
    "limits.codex_token_budget",
    "limits.cycle_wallclock_budget_minutes",
)
_CASES = [
    ("dollar_cap_exceeded", "  cycle_budget_usd: 0.01\n", "limits.cycle_budget_usd"),
    (
        "codex_token_cap_exceeded",
        "  codex_token_budget: 100\n",
        "limits.codex_token_budget",
    ),
    (
        "wallclock_exceeded",
        "  cycle_wallclock_budget_minutes: 1\n",
        "limits.cycle_wallclock_budget_minutes",
    ),
]


def _marker(reason: str) -> BudgetPausedMarker:
    return BudgetPausedMarker(
        pause_reason=reason,
        cycle_number=1,
        paused_stage="research",
        cumulative_spend_usd=1.0,
        cycle_budget_usd=0.01,
        dispatch_estimate_usd=0.0,
        codex_tokens_cumulative=900_000,
        codex_token_budget=100,
        wallclock_elapsed_seconds=99999.0,
        wallclock_cap_seconds=60.0,
    )


@pytest.mark.parametrize("reason,limits,setting", _CASES)
def test_headless_refusal_payload_names_the_setting(
    reason: str,
    limits: str,
    setting: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    vault = tmp_path / "vault"
    shutil.copytree(_FIXTURE, vault)
    (vault / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 2\n  budget_usd: 1.0\nlimits:\n" + limits,
        encoding="utf-8",
    )
    atomic_write_json_marker(
        vault / "_pipeline/BUDGET_PAUSED", _marker(reason).to_json_dict()
    )

    assert handle_budget_marker_on_resume(vault, 1) == 1

    payload = json.loads(capsys.readouterr().err)
    assert payload["error"] == "budget_paused"
    assert setting in payload["remedy"]
    assert not any(o in payload["remedy"] for o in _ALL if o != setting)


@pytest.mark.parametrize("reason,limits,setting", _CASES)
def test_pause_message_names_only_the_matching_setting(
    reason: str,
    limits: str,
    setting: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "_pipeline").mkdir()
    with pytest.raises(SystemExit):
        pause_for_budget(tmp_path, _marker(reason))
    err = capsys.readouterr().err
    assert setting in err
    assert not any(o in err for o in _ALL if o != setting)
