"""Spec 064 — budget-guard parity for the opencode runtime (US3).

opencode cost is per-call: local ($0, cost_source runtime) and metered (real or
estimated dollar). Its sidecars must (a) sum into the dollar tally — including
the modern schema 1.2 line (the rc3 `schema_version` footgun regression) — and
(b) be subject to the dollar cap (metered) and the wall-clock cap (the operative
guardrail for an unattended $0 local run, FR-012).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from research_framework.pipeline.budget_guard import (
    CycleSpendTally,
    check_pre_dispatch,
    refresh_actuals,
)
from research_framework.pipeline.settings import LimitsSettings


def _write_opencode_sidecar(
    vault: Path, cycle: int, stage: str, *, cost: float, tin: int, tout: int
) -> None:
    d = vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}" / "agent-calls"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stage}.json").write_text(
        json.dumps(
            {
                "schema_version": "1.2",  # modern line — must NOT be dropped
                "stage": stage,
                "agent": "opencode",
                "agent_kind": "real",
                "tier": "normal",
                "status": "ok",
                "exit_code": 0,
                "cost_usd": cost,
                "tokens_in": tin,
                "tokens_out": tout,
                "latency_ms": 0,
                "cost_source": "runtime",
                "started_at": "2026-01-01T00:00:00Z",
                "completed_at": "2026-01-01T00:00:01Z",
                "cycle": cycle,
            }
        ),
        encoding="utf-8",
    )


def test_opencode_sidecars_sum_into_budget_tally(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_opencode_sidecar(vault, 1, "scout", cost=0.04, tin=100, tout=20)
    _write_opencode_sidecar(vault, 1, "note_writer", cost=0.06, tin=200, tout=40)
    tally = CycleSpendTally(cycle_num=1)
    refresh_actuals(vault, 1, tally)
    # The schema-1.2 sidecars are counted (rc3 footgun regression).
    assert tally.actual_usd == 0.10


def test_budget_paused_fires_on_dollar_cap_metered(tmp_path: Path) -> None:
    tally = CycleSpendTally(actual_usd=0.95)
    limits = LimitsSettings(cycle_budget_usd=1.0)
    pause = check_pre_dispatch(
        tally=tally,
        limits=limits,
        estimate_cost_usd=0.10,  # 0.95 + 0.10 = 1.05 > 1.0
        estimate_codex_tokens=0,
        stage="note_writer",
        agent="opencode",
    )
    assert pause is not None
    assert pause.marker.pause_reason == "dollar_cap_exceeded"


def test_budget_paused_fires_on_wall_clock_cap_local(tmp_path: Path) -> None:
    """A local ($0) opencode run never hits the dollar cap, but the wall-clock
    cap still pauses an unattended run (FR-012)."""
    tally = CycleSpendTally(cycle_num=1, cycle_started_mono=time.monotonic() - 3600)
    limits = LimitsSettings(cycle_wallclock_budget_minutes=1)
    pause = check_pre_dispatch(
        tally=tally,
        limits=limits,
        estimate_cost_usd=0.0,  # local = $0; dollar cap can never fire
        estimate_codex_tokens=0,
        stage="scout",
        agent="opencode",
    )
    assert pause is not None
    assert pause.marker.pause_reason == "wallclock_exceeded"
