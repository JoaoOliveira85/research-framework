"""Cycle gates judge NEW-topic work, scaled to the plan's new-topic share
(spec 087, defect 5): a cycle that did its update work is not labelled FAIL for
the thin spread of the few new notes it also wrote."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from research_framework.pipeline.cycle_summary import (
    _collect_health_inputs,
    health_header,
)
from research_framework.pipeline.gates import GateResult
from research_framework.pipeline.gates_cycle import (
    SMALL_NEW_SHARE,
    CG002_category_diversity,
    CG004_avg_word_count,
    CG005_cumulative_coverage_trajectory,
    new_topic_share,
    scale_to_new_share,
)
from research_framework.pipeline.quality_report import write_report
from research_framework.pipeline.research_plan import (
    PrioritizedTopic,
    ResearchPlan,
    UpdateTopic,
)
from tests._helpers.vault_factory import build_minimal_vault

# the three shapes: no new topics planned, a small new share, the default split
UPDATE_ONLY = 0.0
SMALL = 0.32  # the real cycle 30: 39 new of 123
DEFAULT = 60 / 90  # the default 60/30 split of new to update work


def _one_category_notes(n: int = 6) -> list[dict[str, str]]:
    return [{"file": f"n{i}.md", "category": "mid-level-topics"} for i in range(n)]


def _cg002(share: float | None) -> GateResult:
    return scale_to_new_share(
        CG002_category_diversity(_one_category_notes(), unfilled_categories=40), share
    )


def _cg004(share: float | None) -> GateResult:
    before = {"a": {"met": 0}, "b": {"met": 3}}
    after = {"a": {"met": 0}, "b": {"met": 4}}  # "a" is still at zero
    return scale_to_new_share(
        CG004_avg_word_count(before, after, 50, ["a", "b"], new_share=share), share
    )


def _cg005(share: float | None) -> GateResult:
    snap = {"a": {"fill_pct": 0.1}, "b": {"fill_pct": 0.1}}
    return scale_to_new_share(
        CG005_cumulative_coverage_trajectory(snap, max_cycles=30, current_cycle=30),
        share,
    )


@pytest.mark.parametrize("gate", [_cg002, _cg004])
def test_an_update_only_cycle_is_not_judged_on_new_topic_coverage(gate: Any) -> None:
    result = gate(UPDATE_ONLY)
    assert result.status == "PASS"
    assert "no new topics" in result.message


@pytest.mark.parametrize("gate", [_cg002, _cg004])
def test_a_small_new_share_warns_instead_of_failing(gate: Any) -> None:
    raw = gate(None)
    assert raw.status == "FAIL"  # the unscaled verdict, as before

    result = gate(SMALL)

    assert result.status == "WARN"
    assert raw.message in result.message
    assert "32%" in result.message and f"{SMALL_NEW_SHARE:.0%}" in result.message
    assert result.correction_hint == raw.correction_hint


@pytest.mark.parametrize("gate", [_cg002, _cg004])
def test_the_default_split_with_real_new_work_still_fails_as_today(gate: Any) -> None:
    for share in (None, DEFAULT, SMALL_NEW_SHARE, 1.0):
        assert gate(share).status == "FAIL"


def test_the_projection_gate_passes_an_update_only_cycle_and_otherwise_warns() -> None:
    assert _cg005(UPDATE_ONLY).status == "PASS"
    assert _cg005(SMALL).status == "WARN"  # advisory already: unchanged
    assert _cg005(DEFAULT).status == "WARN"
    assert _cg005(None).status == "WARN"


def test_velocity_is_expected_only_of_the_new_share() -> None:
    before = {"a": {"met": 1}}
    after = {"a": {"met": 3}}
    # 2 new notes of an expected 50 per category is 0.04 of it; of a new share
    # of 10% (5 expected) it is 0.4, so the WARN message reports the better figure
    full = CG004_avg_word_count(before, after, 50, ["a"])
    scaled = CG004_avg_word_count(before, after, 50, ["a"], new_share=0.1)
    assert full.metric_value == pytest.approx(0.04)
    assert scaled.metric_value == pytest.approx(0.4)
    assert (
        CG004_avg_word_count(before, after, 50, ["a"], new_share=1.0).metric_value
        == full.metric_value
    )


def _plan(vault: Path, *, new: int, update: int, updates_queued: int = 2) -> None:
    plan = ResearchPlan(
        cycle_number=1,
        generated_at="2026-11-23T08:00:00Z",
        framework_version="x",
        coverage_state=[],
        priority_queue=[PrioritizedTopic("Alpha", "cat_a", 0.9)],
        cycle_focus=["cat_a"],
        cycle_quota=new + update,
        exclusions=[],
        update_queue=[
            UpdateTopic(stem=f"n{i}", path="", reason="review_due", as_of=None)
            for i in range(updates_queued)
        ],
        new_quota=new,
        update_quota=update,
    )
    path = vault / "_pipeline" / "research-plan.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan.to_markdown(), encoding="utf-8")


def test_the_new_share_is_read_from_the_plan(tmp_path: Path) -> None:
    assert new_topic_share(tmp_path) is None  # no plan: judged in full
    _plan(tmp_path, new=39, update=84)
    assert new_topic_share(tmp_path) == pytest.approx(39 / 123)
    _plan(tmp_path, new=0, update=10)
    assert new_topic_share(tmp_path) == 0.0
    _plan(tmp_path, new=7, update=0)  # no update work planned: the old plan shape
    assert new_topic_share(tmp_path) is None


def _cycle_with(tmp_path: Path, *, new: int, update: int) -> dict[str, str]:
    """A cycle of one new batch whose six notes share one category, then the
    quality report's cycle gates."""
    vault = build_minimal_vault(
        tmp_path, num_categories=3, num_targets_per_category=20, max_cycles=3
    )
    if update:
        _plan(vault, new=new, update=update)
    notes = []
    for i in range(6):
        rel = f"data_vault/01 - Concepts/new-{i}.md"
        (vault / rel).parent.mkdir(parents=True, exist_ok=True)
        (vault / rel).write_text(
            "---\ntype: concept\n---\n\n" + "word " * 120, encoding="utf-8"
        )
        notes.append(rel)
    batch = {
        "schema_version": "1",
        "cycle_number": 1,
        "batch_number": 1,
        "started_at": "2026-11-23T08:00:00Z",
        "finished_at": "2026-11-23T08:10:00Z",
        "topics": [
            {"title": f"T{i}", "category": "one-category", "priority_score": 1.0}
            for i in range(6)
        ],
        "notes_written": notes,
        "skipped_topics": [],
        "sg_gate_results": [],
        "accepted": True,
    }
    (vault / "_pipeline" / "cycles").mkdir(parents=True, exist_ok=True)
    (vault / "_pipeline/cycles/cycle-001-batch-001.json").write_text(json.dumps(batch))
    report = json.loads(write_report(vault, 1).read_text(encoding="utf-8"))
    return {g: v["status"] for g, v in report["gates"].items() if g.startswith("CG")}


def test_the_quality_report_judges_by_the_plans_new_share(tmp_path: Path) -> None:
    default = _cycle_with(tmp_path / "default", new=60, update=30)
    small = _cycle_with(tmp_path / "small", new=39, update=84)
    none = _cycle_with(tmp_path / "none", new=0, update=10)
    legacy = _cycle_with(tmp_path / "legacy", new=0, update=0)  # no update work

    assert default["CG-002"] == "FAIL" and legacy["CG-002"] == "FAIL"
    assert small["CG-002"] == "WARN"
    assert none["CG-002"] == "PASS" and none["CG-004"] == "PASS"
    # the gates this change leaves alone judge the notes written, as before
    for shape in (default, small, none, legacy):
        assert shape["CG-006"] == "PASS" and shape["CG-007"] == "PASS"


def _health(**over: Any) -> str:
    args: dict[str, Any] = {
        "exit_code": 0,
        "notes_drafted": 6,
        "verifier_passed": 6,
        "spent": 13.0,
        "budget": 20.0,
        "elapsed_s": 60,
        "errors": 0,
        "warnings": 2,
    }
    return health_header(30, **{**args, **over})


def test_the_headline_counts_update_work_and_does_not_fail_on_these_gates() -> None:
    line = _health(updated=11, confirmed=3)
    assert "6 notes drafted, 6 verifier-passed, 11 updated, 3 confirmed" in line
    assert line.startswith("CYCLE 30: WARN")  # not FAIL: no gate failed
    # a cycle with no update work keeps its old headline exactly
    assert "updated" not in _health() and "confirmed" not in _health()


def test_the_headline_inputs_count_passed_update_outcomes() -> None:
    research = {
        "notes_created": ["a.md", "b.md"],
        "update_outcome_results": [
            {"outcome": "revised", "status": "passed"},
            {"outcome": "superseded", "status": "passed"},
            {"outcome": "confirmed", "status": "passed"},
            {"outcome": "revised", "status": "failed"},
        ],
    }
    inputs = _collect_health_inputs(
        Path("/nonexistent"),
        30,
        exit_code=0,
        scout={},
        research=research,
        quality=None,
    )
    assert (inputs["updated"], inputs["confirmed"]) == (2, 1)
    assert inputs["notes_drafted"] == 2
    plain = _collect_health_inputs(
        Path("/nonexistent"), 30, exit_code=0, scout={}, research={}, quality=None
    )
    assert plain["updated"] is None and plain["confirmed"] is None
