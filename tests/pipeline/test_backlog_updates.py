"""Spec 087 T003: update entries in the research backlog (schema 1.1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from research_framework.pipeline import backlog, state_layout


def _store(vault: Path) -> dict[str, Any]:
    return json.loads(
        state_layout.research_backlog_path(vault).read_text(encoding="utf-8")
    )


def _entry(vault: Path, stem: str) -> dict[str, Any]:
    return next(e for e in _store(vault)["entries"] if e["id"] == f"update:{stem}")


def _seed(vault: Path, store: dict[str, Any]) -> Path:
    path = state_layout.research_backlog_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
    return path


def test_one_open_entry_per_note_and_a_second_sighting_updates_it(
    tmp_path: Path,
) -> None:
    assert backlog.observe_update(
        tmp_path,
        "scout",
        stem="kafka-retries",
        reason="new_material",
        prompted_by=["https://a.example", "https://b.example"],
        cycle=2,
        as_of="2026-01-01",
    )
    assert backlog.observe_update(
        tmp_path,
        "scout",
        stem="kafka-retries",
        reason="new_material",
        prompted_by=["https://b.example", "https://c.example"],
        cycle=3,
    )

    entries = [e for e in _store(tmp_path)["entries"] if e["origin"] == "update"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["id"] == "update:kafka-retries"
    assert entry["status"] == "open"
    assert entry["prompted_by"] == [
        "https://a.example",
        "https://b.example",
        "https://c.example",
    ]
    assert (entry["first_seen_cycle"], entry["last_seen_cycle"]) == (2, 3)
    assert entry["seen_cycles"] == 2
    assert entry["as_of"] == "2026-01-01"  # a sighting without as_of keeps it
    # the scheme: topics never see update entries
    assert backlog.planner_topics(tmp_path) == []
    assert backlog.all_titles(tmp_path) == []


def test_new_material_outranks_review_due_then_oldest_as_of(tmp_path: Path) -> None:
    def seed(tx: backlog.Transaction) -> None:
        tx.observe_update("due-old", "review_due", as_of="2024-01-01")
        tx.observe_update("due-new", "review_due", as_of="2025-06-01")
        tx.observe_update("due-none", "review_due")
        tx.observe_update("mat-new", "new_material", as_of="2026-01-01")
        tx.observe_update("mat-old", "new_material", as_of="2025-01-01")
        # a review_due note that later gets new material is promoted ...
        tx.observe_update("due-promoted", "review_due", as_of="2026-03-01")
        tx.observe_update("due-promoted", "new_material", prompted_by=["https://x"])
        # ... and a new_material one is never demoted
        tx.observe_update("mat-stays", "new_material", as_of="2026-06-01")
        tx.observe_update("mat-stays", "review_due")

    assert backlog.update(tmp_path, "scout", seed)

    refs = backlog.update_topics(tmp_path)

    order = [(r.stem, r.reason) for r in refs]
    # new_material first
    reasons = [reason for _, reason in order]
    assert reasons == sorted(reasons, key=lambda r: r != "new_material")
    material = [r.stem for r in refs if r.reason == "new_material"]
    assert material == ["mat-old", "mat-new", "due-promoted", "mat-stays"]
    review = [r.stem for r in refs if r.reason == "review_due"]
    assert review == ["due-old", "due-new", "due-none"]
    assert refs[0].as_of == "2025-01-01"
    with pytest.raises(AttributeError):
        refs[0].reason = "x"  # type: ignore[misc]


def test_close_records_the_outcome_and_a_later_sighting_reopens(
    tmp_path: Path,
) -> None:
    backlog.observe_update(tmp_path, "review", stem="n", reason="review_due", cycle=1)

    assert backlog.close_update(tmp_path, "n", "revised", cycle=4) is True

    closed = _entry(tmp_path, "n")
    assert closed["status"] == "resolved"
    assert (closed["outcome"], closed["outcome_cycle"]) == ("revised", 4)
    assert backlog.update_topics(tmp_path) == []
    assert backlog.close_update(tmp_path, "missing", "confirmed") is False
    with pytest.raises(ValueError):
        backlog.close_update(tmp_path, "n", "shrugged")

    backlog.observe_update(
        tmp_path, "scout", stem="n", reason="new_material", prompted_by=["https://u"]
    )

    reopened = _entry(tmp_path, "n")
    assert reopened["status"] == "open"
    assert "outcome" not in reopened and "outcome_cycle" not in reopened
    assert reopened["outcome_history"] == [{"outcome": "revised", "cycle": 4}]
    assert reopened["reason"] == "new_material"

    backlog.close_update(tmp_path, "n", "confirmed", cycle=6)
    backlog.observe_update(tmp_path, "review", stem="n", reason="review_due")
    assert _entry(tmp_path, "n")["outcome_history"] == [
        {"outcome": "revised", "cycle": 4},
        {"outcome": "confirmed", "cycle": 6},
    ]


def test_an_operators_status_is_never_changed_by_a_writer(tmp_path: Path) -> None:
    backlog.observe_update(tmp_path, "scout", stem="n", reason="new_material")
    path = state_layout.research_backlog_path(tmp_path)
    store = _store(tmp_path)
    store["entries"][0]["status"] = "dropped"
    path.write_text(json.dumps(store), encoding="utf-8")

    assert backlog.close_update(tmp_path, "n", "confirmed") is False
    backlog.observe_update(tmp_path, "scout", stem="n", reason="new_material")

    assert _entry(tmp_path, "n")["status"] == "dropped"
    assert backlog.update_topics(tmp_path) == []


def test_a_1_0_store_is_read_and_written_as_1_1_without_loss(tmp_path: Path) -> None:
    store = {
        "schema_version": "1.0",
        "x_top": {"keep": [1, 2]},
        "entries": [
            {
                "id": "topic:alpha",
                "title": "Alpha",
                "origin": "operator",
                "status": "open",
                "status_by": "operator",
                "status_written": "open",
                "my_field": {"b": 1, "a": 2},
            }
        ],
    }
    _seed(tmp_path, store)

    assert backlog.observe_update(
        tmp_path, "scout", stem="n", reason="new_material", cycle=1
    )

    after = _store(tmp_path)
    assert after["schema_version"] == "1.1"
    assert after["x_top"] == {"keep": [1, 2]}
    assert after["entries"][0] == store["entries"][0]
    assert list(after["entries"][0]["my_field"]) == ["b", "a"]
    assert after["entries"][1]["id"] == "update:n"


def test_a_newer_minor_is_not_downgraded(tmp_path: Path) -> None:
    _seed(tmp_path, {"schema_version": "1.4", "entries": []})
    backlog.observe_update(tmp_path, "scout", stem="n", reason="new_material")
    assert _store(tmp_path)["schema_version"] == "1.4"


def test_bad_arguments_and_writers_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        backlog.observe_update(tmp_path, "scout", stem="n", reason="because")
    with pytest.raises(ValueError):
        backlog.observe_update(tmp_path, "harvest", stem="n", reason="new_material")
    with pytest.raises(ValueError):
        backlog.observe_update(tmp_path, "scout", stem="", reason="new_material")
    with pytest.raises(ValueError):
        backlog.update(tmp_path, "scout", lambda tx: tx.close_update("n", "revised"))
