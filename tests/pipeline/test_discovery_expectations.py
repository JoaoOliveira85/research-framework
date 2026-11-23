"""Tier 1: SG-001's expectations count discovery topics as work other than new
topics (spec 088 with spec 087 FR-017)."""

from __future__ import annotations

from pathlib import Path

from research_framework.pipeline.currency import cycle_expectations
from research_framework.pipeline.gates_step import SG001_topics_new_nonempty
from research_framework.spec.schema import SpecConfig


def _spec() -> SpecConfig:
    return SpecConfig.from_dict(
        {"name": "x", "owner": "t", "naming_convention": "slug"}
    )


def test_discovery_slots_come_off_new_wanted_and_count_as_other_work(
    tmp_path: Path,
) -> None:
    spec = _spec()
    # no discovery topic waiting: exactly the spec-087 expectation
    without = cycle_expectations(tmp_path, spec, 20)
    assert without[1] == 0
    # 10% of 20 is two slots; with topics waiting they leave `new wanted`
    with_topics = cycle_expectations(tmp_path, spec, 20, discovery_available=5)
    assert with_topics == (without[0] - 2, 2)
    # fewer waiting than the share: only what can be dispatched counts
    one = cycle_expectations(tmp_path, spec, 20, discovery_available=1)
    assert one == (without[0] - 1, 1)


def test_an_empty_new_list_with_discovery_work_warns_instead_of_failing(
    tmp_path: Path,
) -> None:
    spec = _spec()
    wanted, planned = cycle_expectations(tmp_path, spec, 20, discovery_available=3)
    report = {"topics_found": {"new": [], "discovery": [{"title": "x"}]}}
    result = SG001_topics_new_nonempty(
        report, spec, 20, new_wanted=wanted, updates_planned=planned
    )
    assert result.status == "WARN"
    # discovery rows are not new rows: they never satisfy the count either
    assert result.metric_value == 0
    nothing = SG001_topics_new_nonempty(
        report, spec, 20, new_wanted=wanted, updates_planned=0
    )
    assert nothing.status == "FAIL"
