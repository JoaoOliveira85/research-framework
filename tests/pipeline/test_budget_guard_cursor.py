"""Spec 052 — budget-guard parity for the cursor-agent runtime.

cursor-agent is a *metered-token* runtime (real tokens, flat-rate dollar). It
must (a) have its tokens tallied like codex, (b) be subject to the metered-token
cap, and (c) have its estimated dollar counted toward the dollar cap. Codex's
existing behaviour must stay byte-identical.
"""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.pipeline.budget_guard import (
    CycleSpendTally,
    check_pre_dispatch,
    refresh_actuals,
)
from research_framework.pipeline.settings import LimitsSettings


def _write_sidecar(
    vault: Path,
    cycle: int,
    stage: str,
    agent: str,
    tin: int,
    tout: int,
    cost: float = 0.0,
) -> None:
    d = vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}" / "agent-calls"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stage}.json").write_text(
        json.dumps(
            {
                "schema_version": "1.1",
                "stage": stage,
                "agent": agent,
                "agent_kind": "real",
                "tier": "normal",
                "status": "ok",
                "exit_code": 0,
                "cost_usd": cost,
                "tokens_in": tin,
                "tokens_out": tout,
                "latency_ms": 0,
                "started_at": "2026-01-01T00:00:00Z",
                "completed_at": "2026-01-01T00:00:01Z",
                "cycle": cycle,
            }
        ),
        encoding="utf-8",
    )


def test_cursor_tokens_tallied(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_sidecar(vault, 1, "note_writer", "cursor-agent", tin=120, tout=80, cost=0.1)
    tally = CycleSpendTally(cycle_num=1)
    refresh_actuals(vault, 1, tally)
    assert tally.actual_codex_tokens == 200  # metered tokens now include cursor
    assert tally.actual_usd > 0.0


def test_cursor_token_cap_fires(tmp_path: Path) -> None:
    tally = CycleSpendTally(cycle_num=1, actual_codex_tokens=900)
    limits = LimitsSettings(codex_token_budget=1000)
    pause = check_pre_dispatch(
        tally=tally,
        limits=limits,
        estimate_cost_usd=0.0,
        estimate_codex_tokens=200,  # 900 + 200 = 1100 > 1000
        stage="note_writer",
        agent="cursor-agent",
    )
    assert pause is not None
    assert pause.marker.pause_reason == "codex_token_cap_exceeded"


def test_cursor_dollar_cap_fires_on_estimate(tmp_path: Path) -> None:
    tally = CycleSpendTally(actual_usd=0.95)
    limits = LimitsSettings(cycle_budget_usd=1.0)
    pause = check_pre_dispatch(
        tally=tally,
        limits=limits,
        estimate_cost_usd=0.10,  # 0.95 + 0.10 = 1.05 > 1.0
        estimate_codex_tokens=0,
        stage="note_writer",
        agent="cursor-agent",
    )
    assert pause is not None
    assert pause.marker.pause_reason == "dollar_cap_exceeded"


def test_codex_token_cap_unchanged(tmp_path: Path) -> None:
    """Regression guard: codex token-cap behaviour is byte-identical."""
    tally = CycleSpendTally(cycle_num=1, actual_codex_tokens=900)
    limits = LimitsSettings(codex_token_budget=1000)
    pause = check_pre_dispatch(
        tally=tally,
        limits=limits,
        estimate_cost_usd=0.0,
        estimate_codex_tokens=200,
        stage="note_writer",
        agent="codex",
    )
    assert pause is not None
    assert pause.marker.pause_reason == "codex_token_cap_exceeded"

    # claude is NOT a metered-token agent — no token cap.
    tally2 = CycleSpendTally(cycle_num=1, actual_codex_tokens=900)
    assert (
        check_pre_dispatch(
            tally=tally2,
            limits=limits,
            estimate_cost_usd=0.0,
            estimate_codex_tokens=200,
            stage="note_writer",
            agent="claude",
        )
        is None
    )
