"""Tests for ``research_plan.merge_scout_topics``.

Background: in v0.2.20 the deterministic research plan was generated
once pre-cycle from static state and never re-enriched with what the
scout discovered. On vaults whose coverage categories don't enumerate
``expected_filenames``, the queue was filled with synthetic
``"flows: focus topic N"`` placeholders that the batch filter
correctly dropped — leaving zero real topics for DFS to dispatch and a
4-line sentinel ``cycle-NNN-research.json`` that Step 6 then aborted
against (20 schema errors).

v0.2.21 removes placeholder generation entirely and replaces it with a
Step 2.5 in the cycle runner that calls
``merge_scout_topics(plan, scout_report)`` between scout (Step 1) and
DFS dispatch (Step 3). This test file covers the merge itself.
"""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.pipeline.research_plan import (
    SCOUT_PROVENANCE,
    PrioritizedTopic,
    ResearchPlan,
    merge_scout_topics,
)


def _empty_plan(queue: list[PrioritizedTopic] | None = None) -> ResearchPlan:
    return ResearchPlan(
        cycle_number=1,
        generated_at="2026-05-17T08:00:00Z",
        framework_version="0.2.21",
        coverage_state=[],
        priority_queue=list(queue or []),
        cycle_focus=["concepts"],
        cycle_quota=5,
        exclusions=[],
        narrative_header="",
    )


def _write_scout(tmp_path: Path, *, new_topics: list[dict]) -> Path:
    path = tmp_path / "cycle-001-scout.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "cycle": 1,
                "phase": "scout",
                "topics_found": {
                    "new": new_topics,
                    "existing": [],
                    "total": len(new_topics),
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_merge_prepends_scout_topics_with_score_one(tmp_path: Path) -> None:
    plan = _empty_plan(
        [
            PrioritizedTopic(
                title="existing spec-gap row",
                category="concepts",
                priority_score=0.42,
                provenance="spec_gap",
            )
        ]
    )
    scout_path = _write_scout(
        tmp_path,
        new_topics=[
            {
                "title": "Real Scout Topic A",
                "coverage_category": "api-protocols",
                "proposed_filename": "real-scout-topic-a.md",
                "source_code_topic_ids": ["CT-1-001", "CT-1-002"],
            },
            {
                "title": "Real Scout Topic B",
                "coverage_category": "concepts",
                "proposed_filename": "real-scout-topic-b.md",
            },
        ],
    )

    merged = merge_scout_topics(plan, scout_path)

    scout_rows = [t for t in merged.priority_queue if t.provenance == SCOUT_PROVENANCE]
    assert len(scout_rows) == 2
    assert all(t.priority_score == 1.0 for t in scout_rows)
    # Scout rows pin to top once re-sorted; spec_gap row drops below.
    assert merged.priority_queue[0].provenance == SCOUT_PROVENANCE
    assert merged.priority_queue[-1].title == "existing spec-gap row"
    # Source IDs propagate into source_hints so the dispatcher can show them.
    a = next(t for t in scout_rows if t.title == "Real Scout Topic A")
    assert a.source_hints == ["CT-1-001", "CT-1-002"]
    assert a.category == "api-protocols"


def test_merge_returns_plan_unchanged_when_scout_report_missing(tmp_path: Path) -> None:
    plan = _empty_plan()
    out = merge_scout_topics(plan, tmp_path / "does-not-exist.json")
    assert out is plan


def test_merge_returns_plan_unchanged_when_scout_json_malformed(tmp_path: Path) -> None:
    path = tmp_path / "cycle-001-scout.json"
    path.write_text("{not valid json", encoding="utf-8")
    plan = _empty_plan()
    out = merge_scout_topics(plan, path)
    # Same `priority_queue` contents (we don't assert identity in case of
    # defensive copy elsewhere) — but it must NOT raise.
    assert out.priority_queue == plan.priority_queue


def test_merge_skips_duplicate_titles_against_existing_queue(tmp_path: Path) -> None:
    plan = _empty_plan(
        [
            PrioritizedTopic(
                title="Already Queued",
                category="concepts",
                priority_score=0.5,
                provenance="spec_gap",
            )
        ]
    )
    scout_path = _write_scout(
        tmp_path,
        new_topics=[
            {"title": "already queued", "coverage_category": "concepts"},
            {"title": "Genuinely New", "coverage_category": "concepts"},
        ],
    )
    merged = merge_scout_topics(plan, scout_path)
    titles = [t.title for t in merged.priority_queue]
    # Case-insensitive dedup against existing queue keeps only one "Already Queued".
    assert titles.count("Already Queued") == 1
    assert "Genuinely New" in titles


def test_merge_skips_topics_in_exclusions(tmp_path: Path) -> None:
    plan = _empty_plan()
    plan = ResearchPlan(
        cycle_number=plan.cycle_number,
        generated_at=plan.generated_at,
        framework_version=plan.framework_version,
        coverage_state=plan.coverage_state,
        priority_queue=[],
        cycle_focus=plan.cycle_focus,
        cycle_quota=plan.cycle_quota,
        exclusions=["already-covered: covered-stem", "out-of-scope: customer-pii"],
        narrative_header="",
    )
    scout_path = _write_scout(
        tmp_path,
        new_topics=[
            {
                "title": "Covered Topic",
                "coverage_category": "concepts",
                "proposed_filename": "covered-stem.md",
            },
            {
                "title": "Customer PII",
                "coverage_category": "concepts",
                "proposed_filename": "customer-pii.md",
            },
            {
                "title": "Brand New Topic",
                "coverage_category": "concepts",
                "proposed_filename": "brand-new-topic.md",
            },
        ],
    )
    merged = merge_scout_topics(plan, scout_path)
    titles = [t.title for t in merged.priority_queue]
    assert titles == ["Brand New Topic"]


def test_merge_matches_exclusions_by_slug_not_verbatim(tmp_path: Path) -> None:
    """An exclusion is a file stem or a spec phrase; a scout row is checked by
    its filename or, with none, its title. Compared lowercased but otherwise
    verbatim, "Vendor Pricing" survived `out-of-scope: vendor-pricing` and
    `customer-pii.md` survived the phrase `out-of-scope: customer pii`."""
    plan = ResearchPlan(
        cycle_number=1,
        generated_at="2026-05-17T08:00:00Z",
        framework_version="0.2.21",
        coverage_state=[],
        priority_queue=[],
        cycle_focus=["concepts"],
        cycle_quota=5,
        exclusions=[
            "already-covered: kafka_streams",
            "out-of-scope: vendor-pricing",
            "out-of-scope: customer pii",
        ],
        narrative_header="",
    )
    scout_path = _write_scout_mixed(
        tmp_path,
        new_topics=[
            "Vendor Pricing",
            {"title": "Kafka Streams", "coverage_category": "concepts"},
            {
                "title": "Customer PII",
                "coverage_category": "concepts",
                "proposed_filename": "customer-pii.md",
            },
            {"title": "Brand New Topic", "coverage_category": "concepts"},
        ],
    )

    merged = merge_scout_topics(plan, scout_path)

    assert [t.title for t in merged.priority_queue] == ["Brand New Topic"]


def test_merge_skips_entries_without_title(tmp_path: Path) -> None:
    plan = _empty_plan()
    scout_path = _write_scout(
        tmp_path,
        new_topics=[
            {"coverage_category": "concepts"},  # no title
            {"title": "", "coverage_category": "concepts"},
            {"title": "   ", "coverage_category": "concepts"},
            {"title": "Real Topic", "coverage_category": "concepts"},
        ],
    )
    merged = merge_scout_topics(plan, scout_path)
    titles = [t.title for t in merged.priority_queue]
    assert titles == ["Real Topic"]


def test_merge_with_empty_topics_returns_plan_unchanged(tmp_path: Path) -> None:
    plan = _empty_plan()
    scout_path = _write_scout(tmp_path, new_topics=[])
    out = merge_scout_topics(plan, scout_path)
    assert out is plan


# ---------------------------------------------------------------------------
# Bare-string scout output (regression suite for the codex/gpt scout
# shape discovered during the feeds-vault revival, 2026-05-30 post-mortem).
# ---------------------------------------------------------------------------


def _write_scout_mixed(tmp_path: Path, *, new_topics: list[object]) -> Path:
    """Like _write_scout but accepts heterogeneous (str | dict) entries."""
    path = tmp_path / "cycle-001-scout.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "cycle": 1,
                "phase": "scout",
                "topics_found": {
                    "new": new_topics,
                    "existing": [],
                    "total": len(new_topics),
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_merge_accepts_bare_string_topics(tmp_path: Path) -> None:
    """Regression: codex/gpt scouts emit ``topics_found.new`` as a list of
    bare strings. ``merge_scout_topics`` used to silently drop every
    non-dict entry, leaving the priority queue empty and forcing the
    cycle to abort at CG-001 with "no notes created"."""
    plan = _empty_plan()
    scout_path = _write_scout_mixed(
        tmp_path,
        new_topics=[
            "AlphaEvolve",
            "Mira Murati",
            "Thinking Machines Lab",
        ],
    )
    merged = merge_scout_topics(plan, scout_path)
    titles = [t.title for t in merged.priority_queue]
    assert titles == ["AlphaEvolve", "Mira Murati", "Thinking Machines Lab"]
    # Bare strings get an orphan category derived from coverage_state
    # (deterministic per _pick_orphan_category). All three must have one.
    assert all(t.category for t in merged.priority_queue)
    # All carry the scout provenance + score, just like dict-shaped rows.
    assert all(t.provenance == SCOUT_PROVENANCE for t in merged.priority_queue)
    assert all(t.priority_score == 1.0 for t in merged.priority_queue)


def test_merge_handles_mixed_string_and_dict_rows(tmp_path: Path) -> None:
    plan = _empty_plan()
    scout_path = _write_scout_mixed(
        tmp_path,
        new_topics=[
            "Bare String Topic",
            {"title": "Dict Topic", "coverage_category": "concepts"},
            "",  # empty string is skipped
            42,  # non-string-non-dict is skipped
            {"coverage_category": "concepts"},  # no title is skipped
        ],
    )
    merged = merge_scout_topics(plan, scout_path)
    titles = [t.title for t in merged.priority_queue]
    assert titles == ["Bare String Topic", "Dict Topic"]


# ─── The merge as the cycle runs it: on the plan read back from disk ──────────
#
# ``steps/scout.py`` (Step 2.5) does not hold the generated ``ResearchPlan``.
# It reads ``_pipeline/research-plan.md`` back with ``from_markdown``, merges,
# and writes ``to_markdown()`` over the file the note-writer is then shown.


def _written_plan() -> ResearchPlan:
    from research_framework.pipeline.research_plan import CategoryFillState

    return ResearchPlan(
        cycle_number=2,
        generated_at="2026-05-17T08:00:00Z",
        framework_version="0.2.21",
        coverage_state=[
            CategoryFillState(
                name="patterns",
                target_count=10,
                met_count=2,
                fill_pct=0.2,
                priority=60,
                unmet_topics=["saga.md", "outbox.md"],
            ),
            CategoryFillState(
                name="concepts",
                target_count=4,
                met_count=4,
                fill_pct=1.0,
                priority=40,
            ),
        ],
        priority_queue=[
            PrioritizedTopic(
                title="Saga",
                category="patterns",
                priority_score=0.5,
                source_hints=["docs/saga.md"],
                provenance="spec_gap",
            )
        ],
        cycle_focus=["patterns"],
        cycle_quota=4,
        exclusions=["already-covered: kafka", "out-of-scope: vendor-pricing"],
        narrative_header="Patterns first.",
    )


def _merge_into_the_written_plan(plan: ResearchPlan, scout_path: Path) -> ResearchPlan:
    """What ``steps/scout.py`` does with the plan file between scout and DFS."""
    import dataclasses

    read_back = dataclasses.replace(
        ResearchPlan.from_markdown(plan.to_markdown()),
        priority_queue=list(plan.priority_queue),
    )
    return merge_scout_topics(read_back, scout_path)


def test_a_plan_read_back_from_markdown_renders_the_same_file() -> None:
    """``from_markdown`` returned ``coverage_state=[]`` and ``exclusions=[]``
    ("lossy by design"), which was true to its readers until the scout merge
    began writing the parsed plan back over the file."""
    import dataclasses

    plan = _written_plan()
    md = plan.to_markdown()

    read_back = dataclasses.replace(
        ResearchPlan.from_markdown(md), priority_queue=list(plan.priority_queue)
    )

    assert read_back.exclusions == plan.exclusions
    assert read_back.coverage_state == plan.coverage_state
    assert read_back.to_markdown() == md


def test_the_scout_merge_keeps_exclusions_and_coverage_state(tmp_path: Path) -> None:
    """The rewritten plan told the note-writer "MUST NOT propose: (none)" and
    showed an empty coverage table with every focus category at 0% filled."""
    scout_path = _write_scout(
        tmp_path,
        new_topics=[{"title": "Event Sourcing", "coverage_category": "patterns"}],
    )

    merged = _merge_into_the_written_plan(_written_plan(), scout_path)
    md = merged.to_markdown()

    assert [t.title for t in merged.priority_queue] == ["Event Sourcing", "Saga"]
    assert "| patterns | 10 | 2 | 20% | 60 | saga.md, outbox.md |" in md
    assert "| concepts | 4 | 4 | 100% | 40 | — |" in md
    assert "- patterns (20% filled)" in md
    assert "- already-covered: kafka" in md
    assert "- out-of-scope: vendor-pricing" in md
    assert "- (none)" not in md


def test_a_scout_topic_the_written_plan_excludes_is_not_merged(tmp_path: Path) -> None:
    """With the exclusions parsed away, the merge had nothing to check a scout
    topic against: an already-covered note went back to the top of the queue."""
    scout_path = _write_scout(
        tmp_path,
        new_topics=[
            {
                "title": "Kafka",
                "coverage_category": "patterns",
                "proposed_filename": "kafka.md",
            },
            {
                "title": "Vendor Pricing",
                "coverage_category": "patterns",
                "proposed_filename": "vendor-pricing.md",
            },
            {"title": "Event Sourcing", "coverage_category": "patterns"},
        ],
    )

    merged = _merge_into_the_written_plan(_written_plan(), scout_path)

    assert [t.title for t in merged.priority_queue] == ["Event Sourcing", "Saga"]


def test_from_markdown_reads_only_the_documented_sections() -> None:
    """The contract lets new sections follow ``## Exclusions`` and asks parsers
    to ignore them; its own example table carries a ``| ...`` filler row."""
    md = _written_plan().to_markdown()
    md = md.replace(
        "| concepts | 4 | 4 | 100% | 40 | — |",
        "| concepts | 4 | 4 | 100% | 40 | — |\n| ...",
    )
    md += "\n## Notes for the operator\n\n- not-an-exclusion: something else\n"

    plan = ResearchPlan.from_markdown(md)

    assert [c.name for c in plan.coverage_state] == ["patterns", "concepts"]
    assert plan.exclusions == [
        "already-covered: kafka",
        "out-of-scope: vendor-pricing",
    ]
