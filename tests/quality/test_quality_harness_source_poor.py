"""Tier-6 e2e: source-poor SG-002 diversity gate (T041 / US3 scenario 2)."""

from __future__ import annotations

import json

import pytest

from research_framework.quality.runner import resolve_fixture
from tests.quality.conftest import run_fixture_cycles

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


def _canned_scout_low_diversity(fixture_name: str) -> bool:
    path = (
        resolve_fixture(fixture_name).fake_agent_responses_dir / "scout" / "happy.json"
    )
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows = (doc.get("topics_found") or {}).get("new") or []
    categories = {
        str(r.get("coverage_category") or "").strip()
        for r in rows
        if isinstance(r, dict)
    }
    return len(categories) < 2 and len(rows) >= 1


def test_sg002_diversity_gate_aborts_every_cycle(tmp_path, quality_fixture_env) -> None:
    """The gate must FIRE, and the cycle must stop — the runner's own signal.

    This assertion used to read ``sg002 >= 1 or sg_from_outputs >= 1`` against
    a ``sg_trips`` list the conftest would re-derive from the scout JSON when
    the gate produced nothing — the same single-category property
    ``_canned_scout_low_diversity`` asserts on the input two lines above. It
    therefore passed whether or not SG-002 ever fired (issue #265). Both the
    trip and the abort now come from the typed ``ScoutResult`` and the cycle's
    exit code, which is exactly what ``runner._cycle_output`` records for the
    release gate.
    """
    quality_fixture_env("source-poor")

    assert _canned_scout_low_diversity("source-poor"), (
        "canned scout must concentrate topics in one category for SG-002"
    )

    outputs, _fixture = run_fixture_cycles(
        "source-poor", tmp_path=tmp_path, max_cycles=3
    )

    assert len(outputs) == 3
    for output in outputs:
        assert "SG-002" in output.sg_trips, (
            f"cycle {output.cycle_number} did not trip SG-002; "
            f"scout_result={output.scout_result!r}"
        )
        assert output.exit_code == 2, (
            f"cycle {output.cycle_number} exited {output.exit_code}; SG-002 is "
            "an abort gate, so a low-diversity scout must stop the cycle"
        )
        assert not output.notes_written, (
            f"cycle {output.cycle_number} wrote notes; the cycle aborts at "
            "SG-002 before note_writer is dispatched"
        )


def test_sg002_trips_reach_the_cycle_health_metric(tmp_path, quality_fixture_env):
    """One trip per cycle must reach the metric the release gate compares."""
    from research_framework.quality.metrics.cycle_health import (
        compute_cycle_health_metric,
    )

    quality_fixture_env("source-poor")
    # Spec 026: metrics read the work fixture (the copy the cycle wrote to).
    outputs, fixture = run_fixture_cycles(
        "source-poor", tmp_path=tmp_path, max_cycles=3
    )
    metrics = compute_cycle_health_metric(fixture, outputs)

    assert int(metrics.get("sg002_trip_count", 0)) == 3
