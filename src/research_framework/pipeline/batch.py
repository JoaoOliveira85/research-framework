"""Note-writer batch scheduling and mid-cycle pace checks (feature 017, E-003)."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, replace
from typing import Any

from research_framework._assets import default_settings_path
from research_framework.pipeline.correction import CorrectionDirective
from research_framework.pipeline.gates import GateResult
from research_framework.pipeline.research_plan import (
    PrioritizedTopic,
    ResearchPlan,
    UpdateTopic,
    is_placeholder_topic,
)
from research_framework.pipeline.settings import SettingsError, load_vault_settings

__all__ = [
    "BatchAssignment",
    "BatchResult",
    "check_pace_at_midpoint",
    "interleave_batches",
    "interleave_kinds",
    "slice_topics_into_batches",
]

_LOG = logging.getLogger(__name__)

_MIN_BATCH = 3
_MAX_BATCH = 10


def _clamp_batch_size(raw: int) -> int:
    if raw < _MIN_BATCH or raw > _MAX_BATCH:
        _LOG.warning(
            "batch size %s is outside [%s, %s]; clamping to valid range",
            raw,
            _MIN_BATCH,
            _MAX_BATCH,
        )
        return max(_MIN_BATCH, min(_MAX_BATCH, int(raw)))
    return int(raw)


def _default_batch_size_from_settings() -> int:
    try:
        path = default_settings_path()
        pipe = load_vault_settings(path.parent).extras.get("pipeline") or {}
        return int(pipe.get("note_writer_batch_size", 6))
    except (SettingsError, FileNotFoundError, OSError, TypeError, ValueError):
        return 6


@dataclass
class BatchAssignment:
    """Planned note-writer invocation for one batch (E-003)."""

    cycle_number: int
    batch_number: int
    topics: list[PrioritizedTopic]
    correction_directive: str = ""
    # Spec 087 FR-005a: ``"new"`` writes new notes; ``"update"`` revisits the
    # notes in ``updates`` (``topics`` then holds one stand-in row per note, so
    # everything that counts or serialises a batch's topics keeps working).
    kind: str = "new"
    updates: list[UpdateTopic] = field(default_factory=list)


@dataclass
class BatchResult:
    """Outcome of one note-writer batch / gate pass (E-003)."""

    cycle_number: int
    batch_number: int
    started_at: str
    finished_at: str
    notes_written: list[str]
    skipped_topics: list[dict[str, str]]
    sg_gate_results: list[GateResult]
    topics: list[PrioritizedTopic] | None = None
    correction_directive_in: str = ""
    kind: str = "new"

    def __post_init__(self) -> None:
        if any(
            isinstance(row, dict) and row.get("reason") == "agent_chose_alternative"
            for row in self.skipped_topics
        ):
            extra = GateResult(
                gate_id="SG-005",
                status="FAIL",
                metric_name="batch_topic_adherence",
                metric_value=1,
                threshold=0,
                message="Assigned topic skipped with reason agent_chose_alternative.",
                correction_hint=(
                    "Write notes only for assigned batch topics; do not substitute "
                    "alternate topics without following the skip protocol."
                ),
            )
            self.sg_gate_results = [*self.sg_gate_results, extra]

    @property
    def accepted(self) -> bool:
        return not any(g.status == "FAIL" for g in self.sg_gate_results)

    def to_dict(self) -> dict[str, Any]:
        # Earlier versions enforced ``3 <= len(self.topics) <= 10`` here,
        # mirroring the slicer's preferred batch size. That conflated two
        # concerns: the slicer *prefers* full batches (3..10) for prompt
        # economy, but the realistic last batch of a small queue is often
        # 1 or 2 topics (e.g. queue of 8 with batch_size=3 → 3 + 3 + 2)
        # and that last batch must still serialize cleanly. v0.2.22 narrows
        # the contract to "non-empty, not absurdly large": at least one
        # topic was assigned (otherwise we wouldn't be writing a batch
        # report at all) and not so many that the batch report explodes
        # past anything a single agent invocation could reasonably handle.
        if self.topics is None or not (1 <= len(self.topics) <= _MAX_BATCH):
            raise ValueError(
                "BatchResult.topics must hold "
                f"1..{_MAX_BATCH} PrioritizedTopic rows for batch-report "
                f"schema serialization (got "
                f"{0 if self.topics is None else len(self.topics)})"
            )
        topics_out: list[dict[str, Any]] = []
        for t in self.topics:
            d = t.to_dict()
            row: dict[str, Any] = {
                "title": d["title"],
                "category": d["category"],
                "priority_score": d["priority_score"],
                "provenance": d["provenance"],
            }
            if d.get("source_hints"):
                row["source_hints"] = list(d["source_hints"])
            if d.get("citation_count", 0) != 0:
                row["citation_count"] = int(d["citation_count"])
            topics_out.append(row)

        skipped: list[dict[str, str]] = []
        for row in self.skipped_topics:
            entry: dict[str, str] = {
                "topic": str(row.get("topic", "")),
                "reason": str(row.get("reason", "")),
            }
            if row.get("detail") is not None:
                entry["detail"] = str(row["detail"])
            skipped.append(entry)

        sg = [g.to_dict() for g in self.sg_gate_results]

        out = {
            "schema_version": "1",
            "cycle_number": self.cycle_number,
            "batch_number": self.batch_number,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "topics": topics_out,
            "notes_written": list(self.notes_written),
            "skipped_topics": skipped,
            "sg_gate_results": sg,
            "accepted": self.accepted,
            "correction_directive_in": self.correction_directive_in,
        }
        if self.kind != "new":
            out["kind"] = self.kind
        return out


def _batch_count_denominator(raw_bs: int, clamped: int) -> int:
    """Divisor for ``ceil(topic_cap / denom)`` when capping batch *count*.

    - Values above ``_MAX_BATCH`` fold to ``clamped`` (same as quota-side cap).
    - ``raw_bs == 2`` keeps divisor 2 so ``topic_cap=3`` yields two batches
      (``[2,1]``) while per-batch sizes still respect ``clamped == 3``.
    - Other sub-minimum values (e.g. ``1``) use ``clamped`` so ``topic_cap=12``
      yields four full batches of three topics.
    """
    if raw_bs > _MAX_BATCH:
        return clamped
    if raw_bs < _MIN_BATCH:
        return 2 if raw_bs == 2 else clamped
    return raw_bs


def _drop_placeholder_topics(
    queue: list[PrioritizedTopic],
    cycle_number: int,
) -> list[PrioritizedTopic]:
    """Filter ``queue`` to non-placeholder topics, logging the drop count.

    Placeholders (``provenance == "spec_gap_placeholder"`` or titles matching
    ``"<X>: focus topic N"``) come from over-promised specs whose scout could
    not enrich them with concrete titles. Dispatching them to a note-writer
    triggers SG-005 (no notes written → fail → correction directive), which in
    v0.2.19 cascaded into the agent fabricating cosmetic fixes. Dropping them
    pre-dispatch is silent-success: the cycle simply researches fewer topics
    rather than crashing on garbage input.
    """
    kept: list[PrioritizedTopic] = []
    dropped: list[str] = []
    for t in queue:
        if is_placeholder_topic(t):
            dropped.append(t.title)
        else:
            kept.append(t)
    if dropped:
        _LOG.warning(
            "cycle %d: dropping %d placeholder topic(s) before dispatch: %s",
            cycle_number,
            len(dropped),
            ", ".join(dropped[:5]) + ("…" if len(dropped) > 5 else ""),
        )
    return kept


def slice_topics_into_batches(
    plan: ResearchPlan,
    batch_size: int | None = None,
    *,
    new_count: int | None = None,
    update_count: int | None = None,
) -> list[BatchAssignment]:
    """Split the plan's work into sequential batches (priority order).

    New-topic batches come from ``plan.priority_queue`` capped at the new-topic
    count; update batches (spec 087 FR-005a) follow, cut from
    ``plan.update_queue`` in the order the queue gives (oldest first) and capped
    at ``update_count``. With no ``update_count`` (or 0) the result is exactly
    what it was before updates existed: the new-topic cap is the cycle quota.
    ``new_count`` defaults to the quota minus the update count.

    Placeholders are dropped from the queue before slicing — see
    :func:`_drop_placeholder_topics` for the rationale. The cycle quota is
    re-applied against the filtered count so we never sleep through a cycle
    on a queue that turned out to be 100% placeholders.
    """
    raw_bs = (
        batch_size if batch_size is not None else _default_batch_size_from_settings()
    )
    clamped = _clamp_batch_size(raw_bs)
    queue = _drop_placeholder_topics(list(plan.priority_queue), plan.cycle_number)
    # Spec 088: discovery topics are dispatched ahead of every other new topic
    # (a stable partition: each group keeps its order), whatever a re-sort of
    # the queue did to them.
    queue = [t for t in queue if t.provenance == "discovery"] + [
        t for t in queue if t.provenance != "discovery"
    ]
    update_n = min(max(int(update_count or 0), 0), len(plan.update_queue))
    if update_n <= 0:
        return _slice_new_batches(
            plan, queue, int(plan.cycle_quota), raw_bs=raw_bs, clamped=clamped
        )
    new_quota = (
        int(new_count)
        if new_count is not None
        else max(0, int(plan.cycle_quota) - update_n)
    )
    new = _slice_new_batches(plan, queue, new_quota, raw_bs=raw_bs, clamped=clamped)
    updates = _slice_update_batches(
        plan, plan.update_queue[:update_n], clamped, first_number=1
    )
    return interleave_batches(new, updates)


def interleave_kinds(n_new: int, n_update: int) -> list[str]:
    """The dispatch order of ``n_new`` new-topic and ``n_update`` update batches.

    Deterministic, Bresenham-style: after every prefix of ``i`` batches the
    number of update batches is ``target(i)``, so each kind's share of any prefix
    is within one batch of its overall share. A cycle cut short by its budget or
    clock therefore has worked updates in proportion, instead of reaching them
    last (spec 087).

    * Updates at least a third of the batches: ``target(i) = ceil(i * u / t)``,
      so the FIRST batch is an update batch (3 of 9: ``U N N U N N U N N``).
    * Fewer: ``target(i) = floor(i * u / t)``, so the first update batch sits at
      position ``ceil(t / u)`` exactly (1 of 4: ``N N N U``), never later.
    * No update batches: all new, as before. No new batches: all updates.
    """
    total = n_new + n_update
    if n_update <= 0 or total == 0:
        return ["new"] * n_new
    ceiling = n_update * 3 >= total
    order: list[str] = []
    placed = 0
    for i in range(1, total + 1):
        scaled = i * n_update
        target = -(-scaled // total) if ceiling else scaled // total
        if target > placed:
            order.append("update")
            placed += 1
        else:
            order.append("new")
    return order


def interleave_batches(
    new: list[BatchAssignment], updates: list[BatchAssignment]
) -> list[BatchAssignment]:
    """Merge the two kinds in :func:`interleave_kinds` order, keeping each
    kind's own order, and number the result in dispatch order (1..n)."""
    new_iter, update_iter = iter(new), iter(updates)
    merged = [
        next(update_iter if kind == "update" else new_iter)
        for kind in interleave_kinds(len(new), len(updates))
    ]
    return [replace(b, batch_number=n) for n, b in enumerate(merged, start=1)]


def _slice_update_batches(
    plan: ResearchPlan,
    updates: list[UpdateTopic],
    clamped: int,
    *,
    first_number: int,
) -> list[BatchAssignment]:
    out: list[BatchAssignment] = []
    num_batches = math.ceil(len(updates) / clamped)
    pos = 0
    for bn in range(num_batches):
        remaining = len(updates) - pos
        chunk = min(clamped, math.ceil(remaining / (num_batches - bn)))
        rows = updates[pos : pos + chunk]
        pos += chunk
        out.append(
            BatchAssignment(
                cycle_number=plan.cycle_number,
                batch_number=first_number + bn,
                topics=[
                    PrioritizedTopic(
                        title=u.stem,
                        category=u.reason,
                        priority_score=1.0,
                        source_hints=list(u.prompted_by),
                        provenance="update",
                    )
                    for u in rows
                ],
                kind="update",
                updates=list(rows),
            )
        )
    return out


def _slice_new_batches(
    plan: ResearchPlan,
    queue: list[PrioritizedTopic],
    quota: int,
    *,
    raw_bs: int,
    clamped: int,
) -> list[BatchAssignment]:
    n = len(queue)
    if n == 0:
        return []

    topic_cap = min(quota, n)
    if topic_cap <= 0:
        return []

    denom = _batch_count_denominator(raw_bs, clamped)
    num_batches_cap = math.ceil(quota / clamped)
    num_batches_queue = math.ceil(topic_cap / denom)
    num_batches = min(num_batches_cap, num_batches_queue)

    topics = queue[:topic_cap]
    out: list[BatchAssignment] = []
    remaining = len(topics)
    pos = 0
    for bn in range(1, num_batches + 1):
        if remaining <= 0:
            break
        batches_left = num_batches - bn + 1
        chunk = min(
            clamped,
            remaining,
            math.ceil(remaining / batches_left),
        )
        slice_ = topics[pos : pos + chunk]
        if not slice_:
            break
        # Second line of defence: even if a placeholder slipped through the
        # initial drop (e.g. queue re-serialized without the provenance tag),
        # filter again per-batch. We only skip a batch when this *secondary*
        # filter is what shrank it — small batches that were already small
        # because the queue ran out (the existing pre-fix behaviour the
        # ``TestSliceTopicsIntoBatches`` cases rely on) still ship.
        slice_real = [t for t in slice_ if not is_placeholder_topic(t)]
        placeholders_filtered = len(slice_) - len(slice_real)
        if placeholders_filtered and len(slice_real) < _MIN_BATCH:
            if not slice_real:
                _LOG.warning(
                    "cycle %d batch %d: 100%% placeholder slice — skipping batch",
                    plan.cycle_number,
                    len(out) + 1,
                )
            else:
                _LOG.warning(
                    "cycle %d batch %d: dropped to %d topics after placeholder "
                    "filtering (below MIN_BATCH=%d) — skipping batch",
                    plan.cycle_number,
                    len(out) + 1,
                    len(slice_real),
                    _MIN_BATCH,
                )
            pos += chunk
            remaining -= chunk
            continue
        out.append(
            BatchAssignment(
                cycle_number=plan.cycle_number,
                batch_number=len(out) + 1,
                topics=list(slice_real),
            )
        )
        pos += chunk
        remaining -= chunk
    return out


def check_pace_at_midpoint(
    plan: ResearchPlan,
    completed_batches: list[tuple[BatchAssignment, BatchResult]],
    next_batch_number: int,
) -> CorrectionDirective | None:
    """Return a pace ``CorrectionDirective`` when completion is <40% at midpoint.

    ``next_batch_number`` is the batch about to start. The assignment sized
    for that batch (present in ``completed_batches``) completes
    ``topics_assigned_so_far``; finished batches before it define the midpoint
    crossing. ``notes_written_so_far`` sums every ``BatchResult`` in
    ``completed_batches`` (tests expect cumulative notes across all bundled
    results at this checkpoint).
    """
    before = [
        (a, r) for a, r in completed_batches if a.batch_number < next_batch_number
    ]
    current_assignment: BatchAssignment | None = None
    for a, _ in completed_batches:
        if a.batch_number == next_batch_number:
            current_assignment = a
            break
    if not before or current_assignment is None:
        return None

    topics_assigned_so_far = sum(len(a.topics) for a, _ in before) + len(
        current_assignment.topics
    )
    if topics_assigned_so_far <= 0:
        return None

    midpoint_target = topics_assigned_so_far / 2.0
    cumulative = 0
    midpoint_batch_index = 0
    for i, (a, _) in enumerate(before):
        cumulative += len(a.topics)
        if cumulative >= midpoint_target:
            midpoint_batch_index = i
            break
    else:
        midpoint_batch_index = len(before) - 1

    # Midpoint crossing is the batch boundary after ``midpoint_batch_index``;
    # the pace check runs when we are about to start the following batch.
    if next_batch_number != midpoint_batch_index + 2:
        return None

    # Tests (and FR-006) measure completion rate across all finished batches in
    # ``completed_batches`` at the midpoint boundary, not only those strictly
    # before ``next_batch_number``.
    notes_written_so_far = sum(len(r.notes_written) for _, r in completed_batches)
    completion_ratio = notes_written_so_far / topics_assigned_so_far
    if completion_ratio >= 0.40:
        return None

    cycle = int(plan.cycle_number) if plan.cycle_number >= 1 else 1
    diagnosis = (
        f"You're behind pace at midpoint ({completion_ratio:.0%} complete vs "
        f"≥40% expected) across {topics_assigned_so_far} assigned topics — "
        "prioritize breadth over depth for remaining topics."
    )

    return CorrectionDirective(
        cycle_number=cycle,
        batch_number=next_batch_number,
        failing_gate_ids=[f"pace-cycle-{cycle:03d}-mid"],
        diagnosis=diagnosis,
        required_actions=[
            "Increase note completion rate for remaining assigned batch topics "
            "this cycle (breadth over depth).",
        ],
        forbidden_actions=[],
        expires_after_cycle=cycle + 1,
    )
