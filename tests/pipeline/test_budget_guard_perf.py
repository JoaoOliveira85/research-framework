"""Performance guard for check_pre_dispatch (spec 033)."""

from __future__ import annotations

import time
from pathlib import Path

from research_framework.pipeline.budget_guard import CycleSpendTally, check_pre_dispatch
from research_framework.pipeline.settings import LimitsSettings

_FIXTURE_VAULT = (
    Path(__file__).resolve().parents[1] / "fixtures" / "cost_enforcement" / "vault"
)


def test_check_pre_dispatch_p95_under_fifty_ms() -> None:
    limits = LimitsSettings(cycle_budget_usd=100.0)
    tally = CycleSpendTally()
    samples: list[float] = []
    for _ in range(100):
        start = time.perf_counter()
        check_pre_dispatch(
            tally=tally,
            limits=limits,
            estimate_cost_usd=0.5,
            estimate_codex_tokens=100,
            stage="note_writer",
            agent="codex",
        )
        samples.append(time.perf_counter() - start)
    samples.sort()
    p95 = samples[94]
    assert p95 < 0.050
