"""Tier 1: the ``discovery`` origin in the research backlog (spec 088 FR-007;
backlog schema 1.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline import backlog

REPO = Path(__file__).resolve().parents[2]
SCHEMA = (
    REPO
    / "specs"
    / "084-structured-research-backlog"
    / "contracts"
    / "research-backlog.schema.json"
)


def _observe(vault: Path, title: str, cycle: int = 1, **fields: object) -> None:
    assert backlog.observe_topic(
        vault,
        "scout",
        cycle=cycle,
        title=title,
        origin="discovery",
        scope_area="Streaming ingestion",
        source_urls=["https://a.example/x", "https://b.example/y"],
        **fields,  # type: ignore[arg-type]
    )


def test_only_the_scout_writes_discovery_topics(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot create origin"):
        backlog.observe_topic(
            tmp_path, "harvest", cycle=1, title="T", origin="discovery"
        )
    with pytest.raises(ValueError, match="cannot create origin"):
        backlog.observe_topic(tmp_path, "scout", cycle=1, title="T", origin="harvest")
    with pytest.raises(ValueError, match="does not own"):
        backlog.observe_topic(
            tmp_path, "scout", cycle=1, title="T", origin="discovery", citation_count=3
        )


def test_the_store_is_written_as_schema_1_2_and_listed_by_discovery_topics(
    tmp_path: Path,
) -> None:
    _observe(tmp_path, "Newer", cycle=2)
    _observe(tmp_path, "Older", cycle=1, detail="appeared in 2026")
    store = json.loads(backlog.store_path(tmp_path).read_text(encoding="utf-8"))
    assert store["schema_version"] == "1.2"
    assert [r.title for r in backlog.discovery_topics(tmp_path)] == ["Older", "Newer"]
    older = backlog.discovery_topics(tmp_path)[0]
    assert older.scope_area == "Streaming ingestion" and older.detail == (
        "appeared in 2026"
    )
    assert len(older.source_urls) == 2
    assert backlog.topic_state(tmp_path, "OLDER ") == ("discovery", "open")
    assert backlog.topic_state(tmp_path, "nothing") is None
    # they are titles (propose dedupes against them) but never planner topics
    assert "Older" in [t.title for t in backlog.all_titles(tmp_path)]
    assert backlog.planner_topics(tmp_path) == []


def test_the_view_has_a_found_by_discovery_section(tmp_path: Path) -> None:
    _observe(tmp_path, "Cell Based Routing")
    view = backlog.view_path(tmp_path).read_text(encoding="utf-8")
    assert "## Found by discovery" in view
    assert (
        "- **Cell Based Routing** — scope area: Streaming ingestion · 2 sources" in view
    )
    assert "Follow-on topics" not in view


def test_an_operator_status_is_never_overridden_and_the_schema_lists_the_origin(
    tmp_path: Path,
) -> None:
    _observe(tmp_path, "Cell Based Routing")
    store = backlog.store_path(tmp_path)
    doc = json.loads(store.read_text(encoding="utf-8"))
    doc["entries"][0]["status"] = "dropped"
    store.write_text(json.dumps(doc), encoding="utf-8")
    _observe(tmp_path, "Cell Based Routing", cycle=2)
    assert backlog.discovery_topics(tmp_path) == []
    assert backlog.topic_state(tmp_path, "cell based routing") == (
        "discovery",
        "dropped",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    props = schema["$defs"]["entry"]["properties"]
    assert "discovery" in props["origin"]["enum"]
    assert {"scope_area", "source_urls", "category", "proposed_filename"} <= set(props)
    assert backlog.ORIGINS == tuple(props["origin"]["enum"])


def test_a_malformed_discovery_field_makes_the_store_unreadable_not_silent(
    tmp_path: Path,
) -> None:
    _observe(tmp_path, "T")
    store = backlog.store_path(tmp_path)
    doc = json.loads(store.read_text(encoding="utf-8"))
    doc["entries"][0]["source_urls"] = "https://not-a-list"
    store.write_text(json.dumps(doc), encoding="utf-8")
    assert backlog.discovery_topics(tmp_path) == []  # an unusable store reads empty
    assert not backlog.observe_topic(
        tmp_path, "scout", cycle=2, title="U", origin="discovery"
    )
