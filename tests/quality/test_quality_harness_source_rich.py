"""Tier-6 e2e: source-rich no over-pruning (T042 / US3 scenario 3)."""

from __future__ import annotations

import pytest

from tests.quality.conftest import run_fixture_cycles

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


def test_no_overpruning(
    tmp_path, quality_fixture_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """coverage_pct >= 0.80 and verifier_reject_rate < 0.20 after 3 cycles."""
    quality_fixture_env("source-rich")
    monkeypatch.setenv("FAKE_AGENT_SCOUT_SCENARIO", "happy")
    monkeypatch.setenv("FAKE_AGENT_NOTE_WRITER_SCENARIO", "happy")
    monkeypatch.setenv("FAKE_AGENT_VERIFIER_SCENARIO", "accept")

    from research_framework.quality.metrics.coverage import compute_coverage_metric  # noqa: I001
    from research_framework.quality.metrics.cycle_health import (
        compute_cycle_health_metric,
    )

    # Spec 026: metrics read the work fixture (the copy the cycle wrote to).
    outputs, fixture = run_fixture_cycles(
        "source-rich", tmp_path=tmp_path, max_cycles=3
    )
    coverage = compute_coverage_metric(fixture, outputs)
    health = compute_cycle_health_metric(fixture, outputs)

    coverage_pct = float(coverage.get("coverage_pct", 0.0))
    reject_rate = float(health.get("verifier_reject_rate", 1.0))

    assert coverage_pct >= 0.80, f"coverage_pct {coverage_pct} below 0.80"
    assert reject_rate < 0.20, f"verifier_reject_rate {reject_rate} not < 0.20"
