"""Tier 3: discovery rows become topics, update entries, re-observations or
drops; a topic needs a slot; discovery never counts toward focus or diversity
(spec 088 FR-005, FR-006, FR-007)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_framework.pipeline import backlog, discovery, state_layout
from research_framework.pipeline.batch import slice_topics_into_batches
from research_framework.pipeline.gates_step import (
    SG001_topics_new_nonempty,
    SG002_topic_category_diversity,
)
from research_framework.pipeline.research_plan import (
    CategoryFillState,
    PrioritizedTopic,
    ResearchPlan,
    _exclusion_slug,
)
from research_framework.spec.schema import SpecConfig

AREA = "Streaming ingestion"


def _spec(mode: str = "expand") -> SpecConfig:
    return SpecConfig.from_dict(
        {
            "name": "routing",
            "owner": "tests",
            "research_mode": mode,
            "naming_convention": "slug",
            "scope": {"boundaries": [AREA, "Other area"]},
        }
    )


def _vault(tmp_path: Path) -> Path:
    folder = tmp_path / "data_vault" / "01 - Concepts"
    folder.mkdir(parents=True)
    (folder / "kafka-retries.md").write_text(
        "---\ntype: concept\nas_of: 2025-01-01\n---\n\nBody.\n", encoding="utf-8"
    )
    return tmp_path


def _row(title: str, **over: Any) -> dict[str, Any]:
    row = {
        "title": title,
        "area": AREA,
        "why_new": "new this year",
        "source_urls": ["https://example.org/" + title.replace(" ", "-")],
        "published": "2026-09-01",
        "coverage_category": "patterns",
        "proposed_filename": title.lower().replace(" ", "-") + ".md",
    }
    row.update(over)
    return row


def _entries(vault: Path) -> dict[str, dict[str, Any]]:
    store = json.loads(
        state_layout.research_backlog_path(vault).read_text(encoding="utf-8")
    )
    return {e["id"]: e for e in store["entries"]}


def test_rows_route_to_topic_update_observation_or_drop(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    # an open harvest topic, and one the operator dropped
    backlog.observe_topic(
        vault,
        "harvest",
        cycle=1,
        title="Harvested Topic",
        origin="harvest",
        citation_count=2,
        cited_from=["a.md"],
    )
    backlog.observe_topic(
        vault, "propose", cycle=1, title="Operator Dropped", origin="proposal"
    )
    store = backlog.store_path(vault)
    doc = json.loads(store.read_text(encoding="utf-8"))
    for entry in doc["entries"]:
        if entry["title"] == "Operator Dropped":
            entry["status"] = "dropped"
    store.write_text(json.dumps(doc), encoding="utf-8")

    rows = [
        _row("Cell Based Routing"),  # brand new -> a discovery topic
        _row("Kafka Retries", proposed_filename="kafka-retries.md"),  # a note
        _row("Retries Reworded", proposed_filename="kafka-retries.md"),  # same note
        _row("Rejected Idea"),  # a persistent reject
        _row("Fenced Out"),  # out of scope
        _row("Harvested Topic"),  # an open backlog topic
        _row("Operator Dropped"),
        _row("Already Planned"),
        _row("Cell Based Routing"),  # a duplicate in the report
    ]
    routing = discovery.route_rows(
        vault,
        _spec(),
        rows,
        cycle=3,
        exclusions=[
            "already-covered: kafka-retries",
            "persistent-rejects: rejected-idea",
            "out-of-scope: fenced out",
        ],
        planned_titles=["Already Planned"],
    )

    assert routing.topics == [{"title": "Cell Based Routing", "area": AREA}]
    assert routing.observed == ["Harvested Topic"]
    assert routing.rerouted == 2
    assert routing.kept == 2
    dropped = {d["title"]: d["reason"] for d in routing.dropped}
    assert dropped == {
        "Rejected Idea": "persistent reject",
        "Fenced Out": "out of scope",
        "Operator Dropped": "dropped from the backlog by the operator",
        "Already Planned": "already in this cycle's plan",
        "Cell Based Routing": "duplicate of another row in this report",
    }

    entries = _entries(vault)
    topic = entries["topic:cell based routing"]
    assert topic["origin"] == "discovery" and topic["status"] == "open"
    assert topic["scope_area"] == AREA
    assert topic["source_urls"] == ["https://example.org/Cell-Based-Routing"]
    assert topic["category"] == "patterns"
    assert topic["status_by"] == "scout" and topic["first_seen_cycle"] == 3
    # an existing note -> one new_material update entry carrying both sources
    update = entries["update:kafka-retries"]
    assert update["reason"] == "new_material" and update["status_by"] == "scout"
    assert update["prompted_by"] == [
        "https://example.org/Kafka-Retries",
        "https://example.org/Retries-Reworded",
    ]
    assert not any("kafka" in k for k in entries if k.startswith("topic:"))
    # an open harvest topic was observed again, not duplicated or re-labelled
    harvested = entries["topic:harvested topic"]
    assert harvested["origin"] == "harvest" and harvested["seen_cycles"] == 2
    assert harvested["last_seen_cycle"] == 3
    assert sum(1 for e in entries.values() if e["title"] == "Harvested Topic") == 1
    # neither a dropped nor a rejected row was recorded
    assert "topic:rejected idea" not in entries
    assert entries["topic:operator dropped"]["status"] == "dropped"
    # the planner does not offer discovery topics; the discovery queue does
    assert [t.title for t in backlog.planner_topics(vault)] == ["Harvested Topic"]
    assert [r.title for r in backlog.discovery_topics(vault)] == ["Cell Based Routing"]


def test_a_refresh_cycle_only_updates_notes(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    routing = discovery.route_rows(
        vault,
        _spec("refresh"),
        [
            _row("Brand New"),
            _row("Kafka Retries", proposed_filename="kafka-retries.md"),
        ],
        cycle=1,
        mode="refresh",
    )
    assert routing.topics == [] and routing.rerouted == 1
    assert [d["title"] for d in routing.dropped] == ["Brand New"]
    assert "refresh" in routing.dropped[0]["reason"]
    assert "topic:brand new" not in _entries(vault)


def test_a_discovery_topic_seen_again_stays_one_entry(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    for cycle in (1, 2):
        routing = discovery.route_rows(
            vault, _spec(), [_row("Cell Based Routing")], cycle=cycle
        )
        assert routing.topics == [{"title": "Cell Based Routing", "area": AREA}]
    entries = [e for e in _entries(vault).values() if e["origin"] == "discovery"]
    assert len(entries) == 1
    assert (entries[0]["first_seen_cycle"], entries[0]["last_seen_cycle"]) == (1, 2)


def _plan(quota: int, **over: Any) -> ResearchPlan:
    base: dict[str, Any] = {
        "cycle_number": 4,
        "generated_at": "2026-11-23T08:00:00Z",
        "framework_version": "x",
        "coverage_state": [
            CategoryFillState(
                name="patterns",
                target_count=5,
                met_count=0,
                fill_pct=0.0,
                priority=90,
                unmet_topics=[],
            )
        ],
        "priority_queue": [
            PrioritizedTopic(
                title=f"Scouted {i}",
                category="patterns",
                priority_score=1.0,
                provenance="scout",
            )
            for i in range(quota)
        ],
        "cycle_focus": ["patterns"],
        "cycle_quota": quota,
        "exclusions": [],
    }
    base.update(over)
    return ResearchPlan(**base)


def _seed_discovery(vault: Path, titles: list[str], cycle: int = 1) -> None:
    for offset, title in enumerate(titles):
        discovery.route_rows(vault, _spec(), [_row(title)], cycle=cycle + offset)


def test_the_share_holds_some_topics_and_the_rest_wait_oldest_first(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    (vault / "settings.yaml").write_text(
        "pipeline:\n  max_cycles: 5\n  budget_usd: 10.0\n"
        "  cycle_split: {new: 50, updates: 0, discovery: 50}\n",
        encoding="utf-8",
    )
    _seed_discovery(vault, ["Oldest", "Middle", "Newest"])
    plan, merged = discovery.plan_discovery_topics(vault, _spec(), _plan(4), cycle=4)
    # 50% of a quota of 4 is two slots; the two oldest topics take them
    assert merged == 2
    assert [t.title for t in plan.priority_queue[:3]] == [
        "Oldest",
        "Middle",
        "Scouted 0",
    ]
    assert [t.provenance for t in plan.priority_queue[:2]] == ["discovery"] * 2
    assert plan.priority_queue[0].category == "patterns"
    assert plan.priority_queue[0].source_hints == ["https://example.org/Oldest"]
    # the one that did not fit stays open and goes first next cycle
    assert [r.title for r in backlog.discovery_topics(vault)] == [
        "Oldest",
        "Middle",
        "Newest",
    ]
    # re-running the same cycle's planning merges nothing more and spends nothing
    again, extra = discovery.plan_discovery_topics(vault, _spec(), plan, cycle=4)
    assert extra == 0 and again.priority_queue == plan.priority_queue
    ledger = discovery.load_ledger(vault)
    assert ledger["credit"]["cycle"] == 4 and ledger["credit"]["spent"] == 2


def test_discovery_topics_head_the_queue_whatever_the_order_given(
    tmp_path: Path,
) -> None:
    queue = [
        PrioritizedTopic(
            title="A", category="c", priority_score=1.0, provenance="scout"
        ),
        PrioritizedTopic(
            title="Found", category="c", priority_score=1.0, provenance="discovery"
        ),
    ]
    plan = _plan(2, priority_queue=queue)
    (first,) = slice_topics_into_batches(plan, 6)
    assert [t.title for t in first.topics] == ["Found", "A"]


def test_discovery_rows_do_not_count_toward_focus_or_diversity() -> None:
    discovery_rows = [
        _row(f"Found {i}", coverage_category=f"cat-{i}") for i in range(6)
    ]
    report: dict[str, Any] = {
        "topics_found": {
            "new": [{"title": "N", "coverage_category": "patterns"}],
            "discovery": discovery_rows,
        }
    }
    spec = _spec()
    # six distinct categories among the discovery rows do not satisfy diversity
    diversity = SG002_topic_category_diversity(report, spec, unfilled_categories=5)
    assert diversity.status == "FAIL" and diversity.metric_value == 1
    # and a report with only discovery rows has no new topics at all
    only = {"topics_found": {"new": [], "discovery": discovery_rows}}
    assert SG001_topics_new_nonempty(only, spec, 3).status == "FAIL"
    assert SG002_topic_category_diversity(only, spec, 5).metric_value == 0


def test_resolve_covered_closes_a_discovery_topic_once_its_note_exists(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    _seed_discovery(vault, ["Cell Based Routing"])
    assert backlog.resolve_covered(vault, ["cell-based-routing"])
    entry = _entries(vault)["topic:cell based routing"]
    assert entry["status"] == "resolved" and entry["status_by"] == "harvest"
    assert backlog.discovery_topics(vault) == []
    assert _exclusion_slug("Cell Based Routing") == "cell-based-routing"


def test_a_row_naming_a_propose_reject_is_dropped_via_the_public_helper(
    tmp_path: Path,
) -> None:
    from research_framework.pipeline import rejects

    vault = _vault(tmp_path)
    path = state_layout.propose_rejects_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "- **Operator Rejected** — cycle 001 (2026-11-01): not wanted\nnotes\n",
        encoding="utf-8",
    )
    assert rejects.persistent_reject_titles(vault) == ["Operator Rejected"]
    routing = discovery.route_rows(
        vault, _spec(), [_row("Operator Rejected"), _row("Fine Topic")], cycle=1
    )
    assert [d["title"] for d in routing.dropped] == ["Operator Rejected"]
    assert routing.topics == [{"title": "Fine Topic", "area": AREA}]


def test_record_new_material_takes_rows_directly(tmp_path: Path) -> None:
    from research_framework.pipeline import currency

    vault = _vault(tmp_path)
    queued = currency.record_new_material(
        vault,
        _spec(),
        [
            {"key": "kafka-retries", "source_urls": ["https://a", "https://b"]},
            {"key": "kafka-retries", "source_urls": ["https://b", "https://c"]},
            {"key": "not-a-note", "source_urls": ["https://x"]},
        ],
        cycle=2,
    )
    assert queued == 1
    entry = _entries(vault)["update:kafka-retries"]
    assert entry["prompted_by"] == ["https://a", "https://b", "https://c"]
    assert currency.record_new_material(vault, _spec(), []) == 0
