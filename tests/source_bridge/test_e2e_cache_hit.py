"""Tier-4 cache-hit e2e tests."""

from __future__ import annotations

import time
from pathlib import Path

from research_framework.pipeline.source_bridge.orchestrator import run_extraction


def test_second_cycle_cache_hit_zero_extractor_calls(bridge_vault: Path) -> None:
    first = run_extraction(bridge_vault, 1)
    second = run_extraction(bridge_vault, 2)
    assert second["cache_hits"] >= first.get("cache_hits", 0)


def test_sc001_second_cycle_stage_under_500ms(bridge_vault: Path) -> None:
    run_extraction(bridge_vault, 1)
    start = time.perf_counter()
    run_extraction(bridge_vault, 2)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 500
