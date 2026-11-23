"""Spec 084 T002: observations, resolutions and queries."""

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


def _by_id(vault: Path) -> dict[str, dict[str, Any]]:
    return {e["id"]: e for e in _store(vault)["entries"]}


def _seed(vault: Path, entries: list[dict[str, Any]]) -> None:
    path = state_layout.research_backlog_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": "1.0", "entries": entries}, indent=2) + "\n",
        encoding="utf-8",
    )


def _open(entry_id: str, title: str, origin: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": entry_id,
        "title": title,
        "origin": origin,
        "status": "open",
        "status_by": "harvest" if origin != "operator" else "operator",
        "status_written": "open",
        **extra,
    }


def test_carry_over_is_one_entry_with_the_latest_citations(tmp_path: Path) -> None:
    for cycle, count, paths in (
        (1, 2, ["a.md", "b.md"]),
        (3, 5, ["a.md", "b.md", "c.md", "d.md", "e.md"]),
    ):
        assert backlog.observe_topic(
            tmp_path,
            "harvest",
            cycle=cycle,
            title="Orphan Topic",
            origin="harvest",
            citation_count=count,
            cited_from=paths,
        )
    entries = _store(tmp_path)["entries"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["id"] == "topic:orphan topic"
    assert entry["first_seen_cycle"] == 1
    assert entry["last_seen_cycle"] == 3
    assert entry["seen_cycles"] == 2
    assert entry["citation_count"] == 5
    assert entry["cited_from"] == ["a.md", "b.md", "c.md", "d.md", "e.md"]
    [topic] = backlog.planner_topics(tmp_path)
    assert topic.citation_count == 5


def test_seeing_a_topic_twice_in_one_cycle_counts_one_cycle(tmp_path: Path) -> None:
    for _ in range(2):
        backlog.observe_topic(
            tmp_path, "harvest", cycle=4, title="T", origin="harvest", citation_count=1
        )
    assert _by_id(tmp_path)["topic:t"]["seen_cycles"] == 1


def test_a_writer_touches_only_observation_fields(tmp_path: Path) -> None:
    original = _open(
        "topic:keep me",
        "Keep Me",
        "operator",
        added="2026-01-02",
        first_seen_cycle=None,
        my_unknown_field={"nested": [1, 2]},
        detail="the operator's own words",
    )
    quarantined = _open(
        "quarantine:deseq",
        "deseq",
        "quarantine",
        stem="deseq",
        kind="rewrite",
        added="2026-01-03",
        first_seen_cycle=2,
        seen_cycles=1,
        last_seen_cycle=2,
        note="mine",
    )
    _seed(tmp_path, [original, quarantined])
    backlog.observe_topic(
        tmp_path,
        "harvest",
        cycle=5,
        title="  keep   me ",
        origin="harvest",
        citation_count=3,
        cited_from=["x.md"],
        detail="harvest says",
    )
    backlog.observe_quarantine(
        tmp_path, stem="deseq", kind="retry", detail="again", cycle=6
    )
    backlog.resolve_covered(tmp_path, ["Keep Me"])
    backlog.resolve_quarantine(tmp_path, ["deseq"])
    by_id = _by_id(tmp_path)
    topic = by_id["topic:keep me"]
    for name in ("title", "origin", "added", "first_seen_cycle", "my_unknown_field"):
        assert topic[name] == original[name]
    assert topic["detail"] == "the operator's own words"
    assert topic["citation_count"] == 3
    assert topic["status"] == "open"  # operator origin: never auto-resolved
    quar = by_id["quarantine:deseq"]
    for name in ("title", "origin", "added", "first_seen_cycle", "note"):
        assert quar[name] == quarantined[name]
    assert quar["kind"] == "retry"
    assert quar["last_seen_cycle"] == 6


def test_a_writer_cannot_set_a_field_it_does_not_own(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        backlog.observe_topic(
            tmp_path,
            "harvest",
            cycle=1,
            title="T",
            origin="harvest",
            relation="adjacent",
        )
    with pytest.raises(ValueError):
        backlog.observe_topic(
            tmp_path, "propose", cycle=1, title="T", origin="harvest", detail="x"
        )
    assert not state_layout.research_backlog_path(tmp_path).exists()


def test_a_dropped_or_operator_reopened_entry_is_never_moved_by_a_writer(
    tmp_path: Path,
) -> None:
    dropped = _open("topic:dropped", "Dropped", "harvest")
    dropped.update(status="dropped", status_written="dropped", status_by="operator")
    # The operator reopened what the module had resolved.
    reopened = _open("topic:reopened", "Reopened", "harvest")
    reopened.update(status="open", status_written="resolved")
    quar = _open("quarantine:gone", "gone", "quarantine", stem="gone", kind="retry")
    quar.update(status="dropped", status_written="open")
    _seed(tmp_path, [dropped, reopened, quar])
    backlog.observe_topic(
        tmp_path,
        "harvest",
        cycle=9,
        title="Dropped",
        origin="harvest",
        citation_count=2,
    )
    backlog.resolve_covered(tmp_path, ["dropped", "reopened"])
    backlog.resolve_quarantine(tmp_path, [])
    by_id = _by_id(tmp_path)
    assert by_id["topic:dropped"]["status"] == "dropped"
    assert by_id["topic:dropped"]["citation_count"] == 2  # observation still recorded
    assert by_id["topic:reopened"]["status"] == "open"
    assert by_id["topic:reopened"]["status_by"] == "operator"
    assert by_id["quarantine:gone"]["status"] == "dropped"


def test_an_entry_a_writer_resolved_reopens_when_it_is_observed_again(
    tmp_path: Path,
) -> None:
    # A topic whose note was written, then removed and cited again.
    backlog.observe_topic(
        tmp_path, "harvest", cycle=1, title="Fresh", origin="harvest", citation_count=1
    )
    backlog.resolve_covered(tmp_path, ["fresh"])
    assert _by_id(tmp_path)["topic:fresh"]["status"] == "resolved"
    backlog.observe_topic(
        tmp_path, "harvest", cycle=2, title="Fresh", origin="harvest", citation_count=3
    )
    fresh = _by_id(tmp_path)["topic:fresh"]
    assert (fresh["status"], fresh["status_by"], fresh["status_written"]) == (
        "open",
        "harvest",
        "open",
    )
    assert fresh["citation_count"] == 3
    # A harvest that still finds the note resolves it again in the same pass.
    backlog.resolve_covered(tmp_path, ["fresh"])
    assert _by_id(tmp_path)["topic:fresh"]["status"] == "resolved"

    # A note quarantined, reinstated, then quarantined a second time.
    backlog.observe_quarantine(tmp_path, stem="deseq", kind="rewrite", detail="first")
    backlog.resolve_quarantine_stem(tmp_path, "deseq")
    assert _by_id(tmp_path)["quarantine:deseq"]["status"] == "resolved"
    backlog.observe_quarantine(tmp_path, stem="deseq", kind="retry", detail="second")
    again = _by_id(tmp_path)["quarantine:deseq"]
    assert (again["status"], again["kind"], again["detail"]) == (
        "open",
        "retry",
        "second",
    )
    assert len(_store(tmp_path)["entries"]) == 2  # reopened, never duplicated


def test_an_entry_an_operator_resolved_is_not_reopened_by_a_sighting(
    tmp_path: Path,
) -> None:
    by_hand = _open("topic:settled", "Settled", "harvest")
    # The operator resolved it in the file; the module last wrote "open".
    by_hand.update(status="resolved", status_written="open")
    quar = _open("quarantine:kept", "kept", "quarantine", stem="kept", kind="rewrite")
    quar.update(status="resolved", status_written="resolved", status_by="operator")
    _seed(tmp_path, [by_hand, quar])
    backlog.observe_topic(
        tmp_path,
        "harvest",
        cycle=4,
        title="Settled",
        origin="harvest",
        citation_count=2,
    )
    backlog.observe_quarantine(tmp_path, stem="kept", kind="retry")
    by_id = _by_id(tmp_path)
    assert by_id["topic:settled"]["status"] == "resolved"
    assert by_id["topic:settled"]["status_by"] == "operator"
    assert by_id["quarantine:kept"]["status"] == "resolved"
    assert by_id["quarantine:kept"]["kind"] == "retry"  # the observation is recorded


def test_resolve_covered_resolves_harvest_and_researcher_not_others(
    tmp_path: Path,
) -> None:
    _seed(
        tmp_path,
        [
            _open("topic:a", "A", "harvest"),
            _open("topic:b", "B", "researcher"),
            _open("topic:c", "C", "proposal"),
            _open("topic:d", "D", "operator"),
            _open("topic:e", "E", "harvest"),
        ],
    )
    backlog.resolve_covered(tmp_path, ["a", "B", "c", "D"])
    status = {k: v["status"] for k, v in _by_id(tmp_path).items()}
    assert status == {
        "topic:a": "resolved",
        "topic:b": "resolved",
        "topic:c": "open",
        "topic:d": "open",
        "topic:e": "open",
    }
    assert _by_id(tmp_path)["topic:a"]["status_by"] == "harvest"
    assert len(_store(tmp_path)["entries"]) == 5  # nothing is ever deleted


@pytest.mark.parametrize("kind", ["rewrite", "retry"])
def test_resolve_quarantine_stem_is_exact(tmp_path: Path, kind: str) -> None:
    backlog.observe_quarantine(tmp_path, stem="deseq", kind=kind)
    backlog.observe_quarantine(tmp_path, stem="deseq2", kind=kind)
    backlog.observe_quarantine(tmp_path, stem="my-deseq", kind=kind)
    backlog.resolve_quarantine_stem(tmp_path, "deseq")
    status = {k: v["status"] for k, v in _by_id(tmp_path).items()}
    assert status == {
        "quarantine:deseq": "resolved",
        "quarantine:deseq2": "open",
        "quarantine:my-deseq": "open",
    }
    assert _by_id(tmp_path)["quarantine:deseq"]["status_by"] == "regrade"


def test_resolve_quarantine_resolves_stems_no_longer_live(tmp_path: Path) -> None:
    backlog.observe_quarantine(tmp_path, stem="a", kind="rewrite")
    backlog.observe_quarantine(tmp_path, stem="b", kind="retry")
    backlog.resolve_quarantine(tmp_path, ["b"])
    status = {k: v["status"] for k, v in _by_id(tmp_path).items()}
    assert status == {"quarantine:a": "resolved", "quarantine:b": "open"}


def test_planner_topics_queue_on_evidence(tmp_path: Path) -> None:
    _seed(
        tmp_path,
        [
            _open(
                "topic:late cited",
                "Late cited",
                "harvest",
                citation_count=2,
                first_seen_cycle=4,
            ),
            _open("topic:operator", "Operator", "operator", first_seen_cycle=None),
            _open(
                "topic:early cited",
                "Early cited",
                "harvest",
                citation_count=1,
                first_seen_cycle=2,
            ),
            _open(
                "topic:flag only",
                "Flag only",
                "researcher",
                citation_count=0,
                first_seen_cycle=1,
            ),
            _open("topic:proposal", "Proposal", "proposal", first_seen_cycle=1),
            _open(
                "topic:merged",
                "Merged",
                "researcher",
                citation_count=3,
                first_seen_cycle=3,
            ),
            _open("quarantine:q", "q", "quarantine", stem="q", kind="retry"),
            _open("migrated:0001", "old line", "migrated"),
            {
                **_open("topic:resolved", "Resolved", "harvest", citation_count=9),
                "status": "resolved",
                "status_written": "resolved",
            },
            _open("topic:reopened", "Reopened", "harvest", status_by="operator"),
        ],
    )
    titles = [t.title for t in backlog.planner_topics(tmp_path)]
    assert titles == [
        "Early cited",
        "Merged",
        "Late cited",
        "Operator",
        "Reopened",
    ]


def test_planner_topics_return_immutable_values(tmp_path: Path) -> None:
    backlog.observe_topic(
        tmp_path,
        "harvest",
        cycle=1,
        title="T",
        origin="harvest",
        citation_count=1,
        cited_from=["a.md"],
    )
    [topic] = backlog.planner_topics(tmp_path)
    with pytest.raises(AttributeError):
        topic.title = "changed"  # type: ignore[misc]
    assert topic.cited_from == ("a.md",)


def test_all_titles_ignores_status(tmp_path: Path) -> None:
    resolved = _open("topic:old one", "Old  One", "harvest")
    resolved.update(status="resolved", status_written="resolved")
    dropped = _open("topic:gone", "Gone", "operator")
    dropped.update(status="dropped", status_written="dropped")
    _seed(
        tmp_path,
        [
            _open("topic:open", "Open", "harvest"),
            resolved,
            dropped,
            _open("quarantine:q", "q", "quarantine", stem="q", kind="retry"),
        ],
    )
    assert backlog.all_titles(tmp_path) == [
        ("open", "Open"),
        ("old one", "Old  One"),
        ("gone", "Gone"),
        ("q", "q"),
    ]


def test_a_wrapped_title_and_its_case_variant_are_one_entry(tmp_path: Path) -> None:
    for title in (
        "Danish Kaffemote Coffee\nMeeting Networking Norm",
        "danish kaffemote coffee meeting networking norm",
    ):
        backlog.observe_topic(
            tmp_path,
            "harvest",
            cycle=1,
            title=title,
            origin="harvest",
            citation_count=1,
        )
    assert len(_store(tmp_path)["entries"]) == 1
    [ref] = backlog.all_titles(tmp_path)
    assert ref.key == "danish kaffemote coffee meeting networking norm"


def test_a_store_written_by_observations_satisfies_the_schema_checks(
    tmp_path: Path,
) -> None:
    from tests.pipeline.test_backlog_store import SCHEMA_PATH, _check

    backlog.observe_topic(
        tmp_path,
        "harvest",
        cycle=2,
        title="Cited",
        origin="harvest",
        citation_count=3,
        cited_from=["a.md"],
    )
    backlog.observe_topic(
        tmp_path, "harvest", cycle=2, title="Flag", origin="researcher", detail="why"
    )
    backlog.observe_topic(
        tmp_path,
        "propose",
        cycle=2,
        title="Tangent",
        origin="proposal",
        relation="adjacent",
        parent_note="P",
        scope_warn=True,
        detail="because",
    )
    backlog.observe_quarantine(tmp_path, stem="deseq", kind="rewrite", detail="bad")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    _check(_store(tmp_path), schema, schema["$defs"], "$")
    assert len(_store(tmp_path)["entries"]) == 4


def test_create_empty_seeds_a_store_once(tmp_path: Path) -> None:
    assert backlog.create_empty(tmp_path) is True
    assert _store(tmp_path) == {"schema_version": "1.1", "entries": []}
    assert backlog.create_empty(tmp_path) is False
