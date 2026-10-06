"""SC-005 sandbox retry budget halt test (spec 033)."""

from __future__ import annotations

import time

from research_framework.pipeline.budget_guard import (
    CycleSpendTally,
    check_pre_dispatch,
)
from research_framework.pipeline.settings import LimitsSettings


def test_sandbox_failure_retry_loop_halts_within_sixty_seconds() -> None:
    limits = LimitsSettings(cycle_budget_usd=1.00)
    tally = CycleSpendTally(actual_usd=0.0)
    started = time.monotonic()
    iterations = 0
    while iterations < 50:
        result = check_pre_dispatch(
            tally=tally,
            limits=limits,
            estimate_cost_usd=0.55,
            estimate_codex_tokens=0,
            stage="plan_narrator",
            agent="claude",
        )
        if result is not None:
            break
        tally.actual_usd += 0.55
        iterations += 1
    elapsed = time.monotonic() - started
    assert result is not None
    assert elapsed < 60.0
    assert iterations < 50
