"""RED tests for batch scheduler + mid-cycle pace (T051, US4, feature 017).

Imports (T055): ``BatchAssignment``, ``BatchResult``, ``slice_topics_into_batches``,
``check_pace_at_midpoint`` from :mod:`research_framework.pipeline.batch`.
"""

from __future__ import annotations

import importlib
import math
import re

import pytest

from research_framework.pipeline.gates import GateResult
from research_framework.pipeline.research_plan import PrioritizedTopic, ResearchPlan


def _load_batch():
    try:
        return importlib.import_module("research_framework.pipeline.batch")
    except ModuleNotFoundError as exc:
        pytest.fail(f"Expected research_framework.pipeline.batch (T055): {exc}")


def _minimal_plan(*, quota: int, queue: list[PrioritizedTopic]) -> ResearchPlan:
    return ResearchPlan(
        cycle_number=1,
        generated_at="2026-05-15T12:00:00Z",
        framework_version="0.0.0",
        coverage_state=[],
        priority_queue=queue,
        cycle_focus=["concepts"],
        cycle_quota=quota,
        exclusions=[],
        narrative_header="",
    )


def _topic(title: str, score: float, category: str = "concepts") -> PrioritizedTopic:
    return PrioritizedTopic(
        title=title,
        category=category,
        priority_score=score,
        source_hints=[],
        provenance="spec_gap",
        citation_count=0,
    )


def _assignments(batch_mod, topics_per: list[int]) -> list:
    return [
        batch_mod.BatchAssignment(
            cycle_number=1,
            batch_number=i + 1,
            topics=[_topic(f"slot{i}-{j}", 0.5) for j in range(topics_per[i])],
        )
        for i in range(len(topics_per))
    ]


class TestBatchSizeClamping:
    """R-004: ``slice_topics_into_batches`` clamps batch size to [3, 10] with WARN."""

    @pytest.mark.parametrize("raw", [1, 2])
    def test_below_three_clamps_with_warn(
        self, raw: int, caplog: pytest.LogCaptureFixture
    ) -> None:
        batch = _load_batch()
        caplog.set_level("WARNING")
        plan = _minimal_plan(
            quota=12,
            queue=[_topic(f"t{i}", 1.0 - i * 0.01) for i in range(12)],
        )
        out = batch.slice_topics_into_batches(plan, raw)  # type: ignore[attr-defined]
        assert out
        assert all(len(a.topics) >= 3 for a in out)
        assert re.search(r"warn", caplog.text, re.I)

    @pytest.mark.parametrize("raw", [11, 99])
    def test_above_ten_clamps_with_warn(
        self, raw: int, caplog: pytest.LogCaptureFixture
    ) -> None:
        batch = _load_batch()
        caplog.set_level("WARNING")
        plan = _minimal_plan(
            quota=30,
            queue=[_topic(f"t{i}", 0.5) for i in range(30)],
        )
        out = batch.slice_topics_into_batches(plan, raw)  # type: ignore[attr-defined]
        assert all(len(a.topics) <= 10 for a in out)
        assert re.search(r"warn", caplog.text, re.I)

    def test_in_range_no_clamp_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        batch = _load_batch()
        caplog.set_level("WARNING")
        plan = _minimal_plan(quota=15, queue=[_topic(f"t{i}", 0.5) for i in range(15)])
        for bs in (3, 6, 10):
            batch.slice_topics_into_batches(plan, bs)  # type: ignore[attr-defined]
        assert caplog.text == ""


class TestSliceTopicsIntoBatches:
    """Quota arithmetic + priority-order slicing."""

    def test_batch_count_is_ceil_quota_over_effective_batch_size(self) -> None:
        batch = _load_batch()
        topics = [_topic(f"topic-{i}", 1.0 - i * 0.01) for i in range(30)]
        plan = _minimal_plan(quota=20, queue=topics)
        assignments = batch.slice_topics_into_batches(plan, 2)  # type: ignore[attr-defined]
        effective = len(assignments[0].topics)
        assert effective == 3
        assert len(assignments) == math.ceil(plan.cycle_quota / effective)

    def test_priority_order_first_batch_is_top_n(self) -> None:
        batch = _load_batch()
        queue = sorted(
            [_topic("low", 0.1), _topic("mid", 0.5), _topic("high", 0.9)],
            key=lambda t: (-t.priority_score, t.title),
        )
        plan = _minimal_plan(quota=10, queue=queue)
        assignments = batch.slice_topics_into_batches(plan, 2)  # type: ignore[attr-defined]
        assert [t.title for t in assignments[0].topics] == ["high", "mid"]
        assert assignments[1].topics[0].title == "low"


class TestBatchResultAccepted:
    """``accepted`` is True iff ``sg_gate_results`` has zero ``FAIL`` entries."""

    def test_accepted_true_when_no_fail(self) -> None:
        batch = _load_batch()
        r = batch.BatchResult(  # type: ignore[attr-defined]
            cycle_number=1,
            batch_number=1,
            started_at="2026-05-15T10:00:00Z",
            finished_at="2026-05-15T10:01:00Z",
            notes_written=["a.md"],
            skipped_topics=[],
            sg_gate_results=[
                GateResult(
                    gate_id="SG-004",
                    status="PASS",
                    metric_name="m",
                    metric_value=0,
                    threshold=None,
                    message="ok",
                ),
                GateResult(
                    gate_id="SG-005",
                    status="WARN",
                    metric_name="m",
                    metric_value=0,
                    threshold=None,
                    message="ok",
                ),
            ],
        )
        assert r.accepted is True

    def test_accepted_false_when_fail_present(self) -> None:
        batch = _load_batch()
        r = batch.BatchResult(  # type: ignore[attr-defined]
            cycle_number=1,
            batch_number=1,
            started_at="2026-05-15T10:00:00Z",
            finished_at="2026-05-15T10:01:00Z",
            notes_written=["a.md"],
            skipped_topics=[],
            sg_gate_results=[
                GateResult(
                    gate_id="SG-005",
                    status="FAIL",
                    metric_name="m",
                    metric_value=0,
                    threshold=None,
                    message="bad",
                    correction_hint="fix",
                ),
            ],
        )
        assert r.accepted is False


class TestMidCyclePaceCheck:
    """Story 9c / FR-006 — midpoint from ``topics_assigned_so_far``, not ``cycle_quota``."""

    def test_slow_completion_triggers_pace_directive(self) -> None:
        """5-batch pattern: after batch 3, completion ratio < 0.40 → ``CorrectionDirective``."""
        batch = _load_batch()
        plan = _minimal_plan(quota=25, queue=[_topic(f"t{i}", 0.5) for i in range(25)])
        topics_per_batch = 4
        assigns = _assignments(
            batch, [topics_per_batch, topics_per_batch, topics_per_batch]
        )
        # int(0.30 * 12) = 3 notes total → below 40% bar
        notes_batch1 = [f"a{i}.md" for i in range(1)]
        notes_batch2 = [f"b{i}.md" for i in range(1)]
        notes_batch3 = [f"c{i}.md" for i in range(1)]
        completed = [
            batch.BatchResult(
                cycle_number=1,
                batch_number=1,
                started_at="2026-05-15T10:00:00Z",
                finished_at="2026-05-15T10:05:00Z",
                notes_written=notes_batch1,
                skipped_topics=[],
                sg_gate_results=[],
            ),
            batch.BatchResult(
                cycle_number=1,
                batch_number=2,
                started_at="2026-05-15T10:00:00Z",
                finished_at="2026-05-15T10:05:00Z",
                notes_written=notes_batch2,
                skipped_topics=[],
                sg_gate_results=[],
            ),
            batch.BatchResult(
                cycle_number=1,
                batch_number=3,
                started_at="2026-05-15T10:00:00Z",
                finished_at="2026-05-15T10:05:00Z",
                notes_written=notes_batch3,
                skipped_topics=[],
                sg_gate_results=[],
            ),
        ]
        bundled = list(zip(assigns, completed, strict=True))
        directive = batch.check_pace_at_midpoint(plan, bundled, 3)  # type: ignore[attr-defined]
        assert directive is not None
        diag = directive.diagnosis.lower()
        assert "behind pace" in diag
        pct = int(round(100 * 3 / 12))
        assert f"{pct}%" in directive.diagnosis

    def test_sixty_percent_no_directive(self) -> None:
        batch = _load_batch()
        plan = _minimal_plan(quota=25, queue=[_topic(f"t{i}", 0.5) for i in range(25)])
        topics_per_batch = 4
        assigns = _assignments(
            batch, [topics_per_batch, topics_per_batch, topics_per_batch]
        )
        n_per = (3, 3, 2)  # 8 / 12
        completed = [
            batch.BatchResult(
                cycle_number=1,
                batch_number=bn,
                started_at="2026-05-15T10:00:00Z",
                finished_at="2026-05-15T10:05:00Z",
                notes_written=[f"x{bn}-{i}.md" for i in range(n_per[bn - 1])],
                skipped_topics=[],
                sg_gate_results=[],
            )
            for bn in (1, 2, 3)
        ]
        bundled = list(zip(assigns, completed, strict=True))
        assert batch.check_pace_at_midpoint(plan, bundled, 3) is None  # type: ignore[attr-defined]

    def test_midpoint_uses_assigned_topic_count_not_cycle_quota(self) -> None:
        """Quota 30 on plan, but only 20 topics across batches 1–3 → 50% target is 10 not 15."""
        batch = _load_batch()
        plan = _minimal_plan(quota=30, queue=[_topic(f"t{i}", 0.5) for i in range(30)])
        sizes = [6, 7, 7]
        assigns = _assignments(batch, sizes)
        completed = [
            batch.BatchResult(
                cycle_number=1,
                batch_number=i + 1,
                started_at="2026-05-15T10:00:00Z",
                finished_at="2026-05-15T10:05:00Z",
                notes_written=[f"n{i}-{j}.md" for j in range(2)],  # sparse vs assigned
                skipped_topics=[],
                sg_gate_results=[],
            )
            for i in range(3)
        ]
        bundled = list(zip(assigns, completed, strict=True))
        directive = batch.check_pace_at_midpoint(plan, bundled, 3)  # type: ignore[attr-defined]
        assert directive is not None
        d = directive.diagnosis
        assert "20" in d
        assert re.search(r"50%\s+of\s+30", d, re.I) is None
