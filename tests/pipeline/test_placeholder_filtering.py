"""Regression tests for placeholder-topic filtering at batch dispatch.

Background: ``research_plan._placeholder_titles`` synthesises stub titles like
``"flows: focus topic 3"`` when a coverage category has a gap but no enumerated
``expected_filenames``. The v0.2.19 cycle-6 trace showed that handing those
stubs to a note-writer agent causes a guaranteed zero-yield batch, which then
triggers a bogus SG-005 correction directive ("restore frontmatter
completeness") and the correction agent fabricates cosmetic edits to existing
notes ("bookkeeping fraud").

The fix has two layers, both exercised here:

1. ``research_plan`` tags placeholder topics with
   ``provenance="spec_gap_placeholder"``.
2. ``batch.slice_topics_into_batches`` drops placeholder topics before
   slicing, and drops any batch that falls below ``_MIN_BATCH=3`` after the
   filter.
"""

from __future__ import annotations

from research_framework.pipeline.batch import slice_topics_into_batches
from research_framework.pipeline.research_plan import (
    PLACEHOLDER_PROVENANCE,
    PLACEHOLDER_TITLE_RE,
    PrioritizedTopic,
    ResearchPlan,
    is_placeholder_topic,
)


def _topic(title: str, *, placeholder: bool = False) -> PrioritizedTopic:
    return PrioritizedTopic(
        title=title,
        category="flows",
        priority_score=0.5,
        source_hints=[],
        provenance=PLACEHOLDER_PROVENANCE if placeholder else "spec_gap",
        citation_count=0,
    )


def _plan(queue: list[PrioritizedTopic], quota: int = 12) -> ResearchPlan:
    return ResearchPlan(
        cycle_number=6,
        generated_at="2026-05-17T01:50:00Z",
        framework_version="0.0.0",
        coverage_state=[],
        priority_queue=queue,
        cycle_focus=["flows"],
        cycle_quota=quota,
        exclusions=[],
        narrative_header="",
    )


def test_placeholder_title_regex_matches_generated_stubs() -> None:
    assert PLACEHOLDER_TITLE_RE.search("flows: focus topic 3")
    assert PLACEHOLDER_TITLE_RE.search("Spring Features: focus topic 12")
    assert not PLACEHOLDER_TITLE_RE.search("Rate-Limited Eviction Handlers")


def test_is_placeholder_topic_via_provenance() -> None:
    assert is_placeholder_topic(_topic("anything", placeholder=True))


def test_is_placeholder_topic_via_title_fallback() -> None:
    # Even if the provenance tag is missing (e.g. round-tripped JSON dropped
    # it), the title regex still catches the stub.
    t = PrioritizedTopic(
        title="flows: focus topic 3",
        category="flows",
        priority_score=0.0,
        source_hints=[],
        provenance="spec_gap",
        citation_count=0,
    )
    assert is_placeholder_topic(t)


def test_all_placeholder_queue_yields_no_batches() -> None:
    plan = _plan(
        [_topic(f"flows: focus topic {i + 1}", placeholder=True) for i in range(4)]
    )
    assert slice_topics_into_batches(plan) == []


def test_mixed_queue_drops_placeholders_keeps_real_topics() -> None:
    real = [_topic(f"Real Topic {i}") for i in range(6)]
    fake = [_topic(f"flows: focus topic {i + 1}", placeholder=True) for i in range(3)]
    plan = _plan(real + fake, quota=9)
    batches = slice_topics_into_batches(plan)
    titles = [t.title for a in batches for t in a.topics]
    assert all("focus topic" not in t for t in titles)
    assert len(titles) == 6


def test_filtered_batch_below_minimum_is_dropped() -> None:
    # Real:fake interleaved so that the second batch would shrink below 3
    # after filtering. The dispatcher must drop that batch rather than emit
    # a malformed BatchResult.
    queue = [
        _topic("Real 1"),
        _topic("Real 2"),
        _topic("Real 3"),
        _topic("flows: focus topic 1", placeholder=True),
        _topic("flows: focus topic 2", placeholder=True),
        _topic("flows: focus topic 3", placeholder=True),
    ]
    plan = _plan(queue, quota=6)
    batches = slice_topics_into_batches(plan, batch_size=3)
    assert len(batches) == 1
    assert [t.title for t in batches[0].topics] == ["Real 1", "Real 2", "Real 3"]
