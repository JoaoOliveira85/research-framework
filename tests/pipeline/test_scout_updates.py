"""Tier 3: the scout reports on existing notes instead of skipping them
(spec 087 FR-001, FR-002; T005)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from research_framework.pipeline import backlog, currency, state_layout
from research_framework.pipeline.research_plan import (
    ResearchPlan,
    merge_scout_topics,
    merge_scout_topics_detailed,
)
from research_framework.spec.schema import SpecConfig


def _spec() -> SpecConfig:
    return SpecConfig.from_dict(
        {"name": "scout", "owner": "tests", "note_types": [{"name": "concept"}]}
    )


def _note(vault: Path, stem: str, **frontmatter: Any) -> None:
    path = vault / "data_vault" / "01 - Concepts" / f"{stem}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["type: concept", *(f"{k}: {v}" for k, v in frontmatter.items())]
    path.write_text("---\n" + "\n".join(lines) + "\n---\n\nBody.\n", encoding="utf-8")


def _plan(exclusions: list[str]) -> ResearchPlan:
    return ResearchPlan(
        cycle_number=1,
        generated_at="2026-11-23T08:00:00Z",
        framework_version="x",
        coverage_state=[],
        priority_queue=[],
        cycle_focus=["concepts"],
        cycle_quota=5,
        exclusions=exclusions,
        narrative_header="",
    )


def _report(vault: Path, *, new: list[Any] | None = None, updates: Any = None) -> Path:
    found: dict[str, Any] = {"new": new or [], "existing": [], "total": len(new or [])}
    if updates is not None:
        found["updates"] = updates
    path = vault / "cycle-001-scout.json"
    path.write_text(
        json.dumps({"cycle": 1, "phase": "scout", "topics_found": found}),
        encoding="utf-8",
    )
    return path


def _entries(vault: Path) -> dict[str, dict[str, Any]]:
    path = state_layout.research_backlog_path(vault)
    data = json.loads(path.read_text(encoding="utf-8"))
    return {e["id"]: e for e in data["entries"] if e["origin"] == "update"}


def test_an_updates_row_becomes_a_new_material_entry_with_its_source(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _note(tmp_path, "Kafka Streams", as_of="2026-01-15", currency="current")
    report = _report(
        tmp_path,
        updates=[
            {
                "note": "Kafka Streams.md",
                "source_urls": ["https://example.org/ks-4", "https://example.org/ks-4"],
                "summary": "4.0 changes the default",
            },
            {"note": "Nonexistent Note", "source_urls": ["https://x"], "summary": "s"},
        ],
    )

    with caplog.at_level(logging.WARNING, logger=currency.__name__):
        queued = currency.record_scout_updates(tmp_path, _spec(), report, cycle=2)

    assert queued == 1
    entries = _entries(tmp_path)
    assert list(entries) == ["update:Kafka Streams"]
    entry = entries["update:Kafka Streams"]
    assert entry["reason"] == "new_material"
    assert entry["prompted_by"] == ["https://example.org/ks-4"]
    assert entry["as_of"] == "2026-01-15"
    assert entry["status_by"] == "scout"
    assert entry["first_seen_cycle"] == 2
    assert "Nonexistent Note" in caplog.text
    assert [r.stem for r in backlog.update_topics(tmp_path)] == ["Kafka Streams"]


def test_a_new_row_matching_an_existing_note_is_queued_as_an_update_not_dropped(
    tmp_path: Path,
) -> None:
    _note(tmp_path, "kafka_streams")
    plan = _plan(["already-covered: kafka_streams"])
    report = _report(
        tmp_path,
        new=[
            {
                "title": "Kafka Streams",
                "coverage_category": "concepts",
                "source_urls": ["https://example.org/news"],
            },
            {"title": "Brand New Topic", "coverage_category": "concepts"},
        ],
    )

    merged = merge_scout_topics_detailed(plan, report)

    assert [t.title for t in merged.plan.priority_queue] == ["Brand New Topic"]
    assert [r["title"] for r in merged.existing_note_rows] == ["Kafka Streams"]
    # the plain function keeps returning the plan alone
    assert [t.title for t in merge_scout_topics(plan, report).priority_queue] == [
        "Brand New Topic"
    ]

    queued = currency.record_scout_updates(
        tmp_path, _spec(), report, merged.existing_note_rows, cycle=1
    )

    assert queued == 1
    entry = _entries(tmp_path)["update:kafka_streams"]
    assert entry["reason"] == "new_material"
    assert entry["prompted_by"] == ["https://example.org/news"]


def test_a_persistently_rejected_title_is_still_dropped(tmp_path: Path) -> None:
    _note(tmp_path, "kafka_streams")
    plan = _plan(
        [
            "already-covered: kafka_streams",
            "persistent-rejects: thermodynamics",
            "out-of-scope: vendor-pricing",
        ]
    )
    report = _report(
        tmp_path,
        new=[
            {"title": "Thermodynamics", "source_urls": ["https://a"]},
            {"title": "Vendor Pricing", "source_urls": ["https://b"]},
        ],
    )

    merged = merge_scout_topics_detailed(plan, report)

    assert merged.plan.priority_queue == []
    assert merged.existing_note_rows == []
    assert currency.record_scout_updates(tmp_path, _spec(), report, [], cycle=1) == 0
    assert not state_layout.research_backlog_path(tmp_path).exists()


def test_a_second_sighting_adds_sources_to_the_one_entry(tmp_path: Path) -> None:
    _note(tmp_path, "kafka_streams")
    first = _report(tmp_path, updates=[{"note": "kafka_streams", "source_urls": ["a"]}])
    currency.record_scout_updates(tmp_path, _spec(), first, cycle=1)
    second = _report(
        tmp_path, updates=[{"note": "kafka-streams", "source_urls": ["b"]}]
    )
    currency.record_scout_updates(tmp_path, _spec(), second, cycle=2)

    entries = _entries(tmp_path)

    assert list(entries) == ["update:kafka_streams"]
    assert entries["update:kafka_streams"]["prompted_by"] == ["a", "b"]
