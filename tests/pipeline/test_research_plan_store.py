"""Spec 084 T007: the planner reads its orphans from the backlog store."""

from __future__ import annotations

import json
import math
from pathlib import Path

from research_framework.pipeline import backlog
from research_framework.pipeline import state_layout as L
from research_framework.spec.schema import CoverageCategory

from .test_research_plan import _minimal_spec, _write_coverage


def _categories() -> list[CoverageCategory]:
    return [
        CoverageCategory(
            name="concept",
            note_type="concept",
            target_count=5,
            met_count=0,
            priority=10,
        )
    ]


def _orphans(plan) -> dict[str, object]:
    return {t.title: t for t in plan.priority_queue if t.provenance == "harvest_orphan"}


def test_an_operator_entry_is_queued_and_a_researcher_flag_is_not(
    tmp_path: Path,
) -> None:
    from research_framework.pipeline.research_plan import generate_plan

    cats = _categories()
    _write_coverage(tmp_path, categories=cats)

    def _harvest(tx: backlog.Transaction) -> None:
        tx.observe_topic(cycle=1, title="Flagged Only", origin="researcher")
        tx.observe_topic(
            cycle=1,
            title="Cited Orphan",
            origin="harvest",
            citation_count=2,
            cited_from=["data_vault/a.md"],
        )

    assert backlog.update(tmp_path, "harvest", _harvest)
    store = L.research_backlog_path(tmp_path)
    data = json.loads(store.read_text(encoding="utf-8"))
    data["entries"].append(
        {"title": "Hand Added", "origin": "operator", "status": "open"}
    )
    store.write_text(json.dumps(data), encoding="utf-8")

    plan = generate_plan(tmp_path, _minimal_spec(categories=cats), cycle_number=2)

    queued = _orphans(plan)
    assert set(queued) == {"Cited Orphan", "Hand Added"}
    assert math.isclose(queued["Hand Added"].priority_score, 0.3)  # type: ignore[attr-defined]
    assert math.isclose(queued["Cited Orphan"].priority_score, 0.5)  # type: ignore[attr-defined]


def test_score_uses_the_latest_citation_count(tmp_path: Path) -> None:
    from research_framework.pipeline.research_plan import generate_plan

    cats = _categories()
    _write_coverage(tmp_path, categories=cats)
    for cycle, count in ((1, 2), (3, 5)):
        assert backlog.observe_topic(
            tmp_path,
            "harvest",
            cycle=cycle,
            title="Carried Over",
            origin="harvest",
            citation_count=count,
            cited_from=["data_vault/a.md"],
        )

    plan = generate_plan(tmp_path, _minimal_spec(categories=cats), cycle_number=4)

    (topic,) = _orphans(plan).values()
    assert topic.citation_count == 5  # type: ignore[attr-defined]
    assert math.isclose(topic.priority_score, 0.8)  # type: ignore[attr-defined]
