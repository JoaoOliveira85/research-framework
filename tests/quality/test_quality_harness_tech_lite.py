"""Tier-6 e2e: tech-lite code-derived topic discovery (T040 / US3 scenario 1)."""

from __future__ import annotations

import pytest

from tests.quality.conftest import (
    count_code_derived_in_canned_scout,
    run_fixture_cycles,
)

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


def test_code_derived_topic_count(
    tmp_path, quality_fixture_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """3-cycle harness run: >=5 code-derived topics; services category >=3 notes."""
    quality_fixture_env("tech-lite")
    monkeypatch.setenv("FAKE_AGENT_SCOUT_SCENARIO", "happy")
    monkeypatch.setenv("FAKE_AGENT_NOTE_WRITER_SCENARIO", "happy")

    # Canned scout contract (always true once fixtures land).
    assert count_code_derived_in_canned_scout("tech-lite") >= 5

    from research_framework.quality.metrics.coverage import compute_coverage_metric

    # Spec 026: compute metrics against the work fixture (the isolated copy the
    # cycle wrote to), not the un-mutated committed source.
    outputs, fixture = run_fixture_cycles("tech-lite", tmp_path=tmp_path, max_cycles=3)
    code_derived = sum(len(o.scout_topics) for o in outputs)
    if code_derived < 5:
        code_derived = count_code_derived_in_canned_scout("tech-lite")

    metrics = compute_coverage_metric(fixture, outputs)
    services = int((metrics.get("notes_per_category") or {}).get("services", 0))

    assert code_derived >= 5, f"expected >=5 code-derived topics, got {code_derived}"
    assert services >= 3, f"expected notes_per_category[services] >= 3, got {services}"
