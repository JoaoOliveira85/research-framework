"""Regression tests for :meth:`BatchResult.to_dict` size constraints.

Background: v0.2.21 shipped with a hard ``3 <= len(topics) <= 10``
invariant on ``BatchResult.to_dict``. The slicer happily produced
2-topic *last* batches whenever the priority queue wasn't a clean
multiple of the configured batch size (e.g. queue of 8 with
``batch_size=3`` → 3 + 3 + 2). The first two batches succeeded; the
third raised ``ValueError`` during serialization and aborted cycle 1
of the v0.2.21 ``reference-vault-v4`` run.

Unit tests at the time passed because they constructed ``BatchResult``
objects with exactly ``len(topics) == _MIN_BATCH`` or larger — the
asymmetric-tail case (the realistic one) was untested. These tests
lock the relaxed v0.2.22 contract in.
"""

from __future__ import annotations

import pytest

from research_framework.pipeline.batch import (
    _MAX_BATCH,
    BatchAssignment,
    BatchResult,
    slice_topics_into_batches,
)
from research_framework.pipeline.gates import GateResult
from research_framework.pipeline.research_plan import PrioritizedTopic, ResearchPlan


def _topic(title: str) -> PrioritizedTopic:
    return PrioritizedTopic(
        title=title,
        category="concepts",
        priority_score=1.0,
        source_hints=[],
        provenance="scout",
        citation_count=0,
    )


def _plan(queue: list[PrioritizedTopic], quota: int) -> ResearchPlan:
    return ResearchPlan(
        cycle_number=1,
        generated_at="2026-05-17T12:00:00Z",
        framework_version="0.2.22",
        coverage_state=[],
        priority_queue=queue,
        cycle_focus=["concepts"],
        cycle_quota=quota,
        exclusions=[],
        narrative_header="",
    )


def _make_result(topics: list[PrioritizedTopic]) -> BatchResult:
    return BatchResult(
        cycle_number=1,
        batch_number=3,
        started_at="2026-05-17T12:00:00Z",
        finished_at="2026-05-17T12:01:00Z",
        notes_written=[f"{t.title.lower().replace(' ', '-')}.md" for t in topics],
        skipped_topics=[],
        sg_gate_results=[
            GateResult(
                gate_id="SG-005",
                status="PASS",
                metric_name="frontmatter_completeness",
                metric_value=1.0,
                threshold=1.0,
                message="ok",
            )
        ],
        topics=topics,
    )


@pytest.mark.parametrize("size", [1, 2, 3, 5, _MAX_BATCH])
def test_to_dict_accepts_realistic_batch_sizes(size: int) -> None:
    """Batches from 1..MAX_BATCH must serialize without raising.

    Sizes 1 and 2 specifically lock the v0.2.22 behavior: an
    asymmetric trailing batch from a small queue (e.g. queue of 8,
    batch_size=3 → tail of 2) must reach disk as a normal batch
    report.
    """
    topics = [_topic(f"Topic {i}") for i in range(size)]
    out = _make_result(topics).to_dict()
    assert len(out["topics"]) == size
    assert out["accepted"] is True


def test_to_dict_rejects_empty_topics_list() -> None:
    """``len(topics) == 0`` is still a programming error.

    If the dispatcher ever calls ``to_dict`` with no assigned topics it
    means the slicer or our loop logic dropped a batch silently — we
    want a loud failure there, not a silent empty report.
    """
    with pytest.raises(ValueError, match=r"1\.\.10"):
        _make_result([]).to_dict()


def test_to_dict_rejects_none_topics() -> None:
    """``topics=None`` (default for the legacy code path) still raises."""
    with pytest.raises(ValueError, match=r"1\.\.10"):
        BatchResult(
            cycle_number=1,
            batch_number=1,
            started_at="2026-05-17T12:00:00Z",
            finished_at="2026-05-17T12:00:00Z",
            notes_written=[],
            skipped_topics=[],
            sg_gate_results=[],
            topics=None,
        ).to_dict()


def test_to_dict_rejects_oversized_batch() -> None:
    """Anything beyond ``_MAX_BATCH`` still raises (sanity guard)."""
    topics = [_topic(f"Topic {i}") for i in range(_MAX_BATCH + 1)]
    with pytest.raises(ValueError, match=r"1\.\.10"):
        _make_result(topics).to_dict()


def test_asymmetric_queue_produces_serializable_tail_batch() -> None:
    """End-to-end through the slicer: queue of 8 with batch_size=3
    → batches of 3 + 3 + 2; the trailing 2-topic batch must serialize.

    This is the exact configuration that crashed cycle 1 of the
    v0.2.21 ``reference-vault-v4`` run. The first two batches succeeded,
    the third aborted with ``ValueError: BatchResult.topics must hold
    3..10 …``.
    """
    queue = [_topic(f"Real {i + 1}") for i in range(8)]
    plan = _plan(queue, quota=8)
    batches: list[BatchAssignment] = slice_topics_into_batches(plan, batch_size=3)

    sizes = [len(b.topics) for b in batches]
    assert sizes == [3, 3, 2], (
        f"slicer regression: expected 3+3+2 for queue=8 / batch_size=3, got {sizes}"
    )

    # Every batch — including the asymmetric tail — must serialize.
    for assignment in batches:
        _make_result(assignment.topics).to_dict()


@pytest.mark.parametrize(
    "queue_size,batch_size",
    [
        # Realistic slicer outputs that historically hit the seam:
        (1, 3),  # single-topic queue
        (2, 3),  # tail-only sub-min queue
        (4, 3),  # 3 + 1 tail
        (5, 3),  # 3 + 2 tail
        (7, 3),  # 3 + 2 + 2
        (8, 3),  # 3 + 3 + 2 (the prod crash)
        (10, 3),  # 4 + 3 + 3
        (15, 6),  # 5 + 5 + 5 (clean multiple — sanity)
        (16, 6),  # asymmetric tail at batch_size=6
        (11, 10),  # 6 + 5
    ],
)
def test_every_slicer_output_serializes_for_arbitrary_queue_sizes(
    queue_size: int, batch_size: int
) -> None:
    """Contract test across the slicer ↔ BatchResult seam.

    For each (queue_size, batch_size) combo, slice the queue then
    serialize every produced batch's ``BatchResult``. The slicer is
    free to produce asymmetric batches; the serializer must accept
    them all without raising. Any new invariant added to
    ``BatchResult.to_dict`` will trip this test before reaching
    a tagged release.
    """
    queue = [_topic(f"Topic {i + 1}") for i in range(queue_size)]
    plan = _plan(queue, quota=queue_size)
    batches = slice_topics_into_batches(plan, batch_size=batch_size)
    assert batches, f"slicer produced no batches for queue={queue_size}"
    total_assigned = sum(len(b.topics) for b in batches)
    assert total_assigned >= 1
    assert total_assigned <= queue_size
    for assignment in batches:
        result = _make_result(assignment.topics)
        out = result.to_dict()
        assert out["batch_number"] == result.batch_number
        assert out["accepted"] is True
        assert len(out["topics"]) == len(assignment.topics)
