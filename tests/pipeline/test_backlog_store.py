"""Spec 084 T001: the backlog store (load, validate, atomic save, update)."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import pytest

from research_framework.pipeline import backlog, state_layout

SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "specs"
    / "084-structured-research-backlog"
    / "contracts"
    / "research-backlog.schema.json"
)


def _write_store(vault: Path, data: Any) -> Path:
    path = state_layout.research_backlog_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        data if isinstance(data, str) else json.dumps(data, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _entry(title: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": backlog.topic_id(title),
        "title": title,
        "origin": "operator",
        "status": "open",
        "status_by": "operator",
        "status_written": "open",
        **extra,
    }


def _noop(vault: Path, writer: str = "harvest") -> bool:
    return backlog.update(vault, writer, lambda tx: None)


def _entries(vault: Path) -> list[dict[str, Any]]:
    path = state_layout.research_backlog_path(vault)
    return json.loads(path.read_text(encoding="utf-8"))["entries"]


def test_round_trip_preserves_unknown_fields_and_order(tmp_path: Path) -> None:
    store = {
        "schema_version": "1.3",
        "x_top_level": {"keep": [3, 1, 2]},
        "entries": [
            {
                "zeta": "z",
                "id": "topic:alpha",
                "title": "Alpha",
                "note": {"b": 1, "a": 2},
                "origin": "operator",
                "status": "open",
                "status_by": "operator",
                "status_written": "open",
                "alpha_field": [1, "two", None],
            },
            _entry("Beta", priority=7),
        ],
    }
    path = _write_store(tmp_path, store)
    assert _noop(tmp_path) is True
    assert json.loads(path.read_text(encoding="utf-8")) == store
    # key order inside the file is preserved too
    again = json.loads(path.read_text(encoding="utf-8"))
    assert list(again) == list(store)
    assert list(again["entries"][0]) == list(store["entries"][0])
    assert list(again["entries"][0]["note"]) == ["b", "a"]
    assert again["schema_version"] == "1.3"


def test_topic_ids_fold_case_and_whitespace() -> None:
    wrapped = "Danish Kaffemote Coffee\nMeeting  Norm"
    single = "danish kaffemote coffee meeting norm"
    assert backlog.topic_id(wrapped) == backlog.topic_id(single)
    assert backlog.topic_id(single) == "topic:danish kaffemote coffee meeting norm"
    assert backlog.quarantine_id("deseq") == "quarantine:deseq"
    assert backlog.migrated_id(7) == "migrated:0007"


def test_a_status_change_made_outside_the_module_is_recorded_as_the_operators(
    tmp_path: Path,
) -> None:
    reopened = {
        "id": "topic:reopened",
        "title": "Reopened",
        "origin": "harvest",
        "status": "open",
        "status_by": "harvest",
        "status_written": "resolved",  # module wrote resolved; operator reopened
    }
    dropped = {**reopened, "id": "topic:dropped", "title": "Dropped"}
    dropped["status"] = "dropped"
    untouched = {**reopened, "id": "topic:untouched", "title": "Untouched"}
    untouched["status_written"] = "open"
    by_hand = {
        "id": "topic:by hand",
        "title": "By hand",
        "origin": "operator",
        "status": "open",
    }
    _write_store(
        tmp_path,
        {
            "schema_version": "1.0",
            "entries": [reopened, dropped, untouched, by_hand],
        },
    )
    assert _noop(tmp_path) is True
    by_id = {e["id"]: e for e in _entries(tmp_path)}
    assert (
        by_id["topic:reopened"]["status_by"],
        by_id["topic:reopened"]["status_written"],
    ) == (
        "operator",
        "open",
    )
    assert (
        by_id["topic:dropped"]["status_by"],
        by_id["topic:dropped"]["status_written"],
    ) == (
        "operator",
        "dropped",
    )
    assert by_id["topic:untouched"]["status_by"] == "harvest"
    assert by_id["topic:by hand"]["status_by"] == "operator"
    assert by_id["topic:by hand"]["status_written"] == "open"


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        json.dumps(
            {
                "schema_version": "1.0",
                "entries": [_entry("Same"), _entry("same")],
            }
        ),
        json.dumps(
            {
                "schema_version": "1.0",
                "entries": [{"id": "topic:x", "title": "X", "origin": "operator"}],
            }
        ),
    ],
    ids=["invalid-json", "duplicate-id", "missing-required-field"],
)
def test_malformed_store_is_left_byte_identical_and_logged(
    tmp_path: Path, content: str, caplog: pytest.LogCaptureFixture
) -> None:
    path = _write_store(tmp_path, content)
    before = path.read_bytes()
    with caplog.at_level(logging.DEBUG, logger="research_framework.pipeline.backlog"):
        assert _noop(tmp_path) is False
    assert path.read_bytes() == before
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors and str(path) in errors[0].getMessage()
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="research_framework.pipeline.backlog"):
        assert backlog.all_titles(tmp_path) == []
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings and str(path) in warnings[0].getMessage()
    assert path.read_bytes() == before


def test_newer_major_version_is_read_only(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = {"schema_version": "2.0", "entries": [_entry("Future")]}
    path = _write_store(tmp_path, store)
    before = path.read_bytes()
    with caplog.at_level(logging.DEBUG, logger="research_framework.pipeline.backlog"):
        assert _noop(tmp_path) is False
    assert path.read_bytes() == before
    assert any(
        r.levelno == logging.ERROR and str(path) in r.getMessage()
        for r in caplog.records
    )
    assert [t.title for t in backlog.all_titles(tmp_path)] == ["Future"]


def test_an_entry_without_an_id_gets_one_on_the_next_write(tmp_path: Path) -> None:
    store = {
        "schema_version": "1.0",
        "entries": [
            {
                "title": "Wrapped  Title\nHere",
                "origin": "operator",
                "status": "open",
                "my_field": "kept",
            },
            {
                "title": "stem-a",
                "origin": "quarantine",
                "status": "open",
                "stem": "stem-a",
                "kind": "retry",
            },
        ],
    }
    _write_store(tmp_path, store)
    assert _noop(tmp_path) is True
    first, second = _entries(tmp_path)
    assert first["id"] == "topic:wrapped title here"
    assert first["my_field"] == "kept"
    assert second["id"] == "quarantine:stem-a"


def test_a_missing_store_is_created_empty_on_the_first_write(tmp_path: Path) -> None:
    assert _noop(tmp_path) is True
    assert json.loads(
        state_layout.research_backlog_path(tmp_path).read_text(encoding="utf-8")
    ) == {"schema_version": "1.0", "entries": []}


def test_an_unconverted_legacy_markdown_backlog_is_not_written(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    legacy = tmp_path / "_pipeline" / "research-backlog.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# Research Backlog\n\n- **Old** — cited by 2 notes\n")
    assert backlog.is_unconverted(tmp_path) is True
    with caplog.at_level(logging.ERROR, logger="research_framework.pipeline.backlog"):
        assert _noop(tmp_path) is False
    assert not state_layout.research_backlog_path(tmp_path).exists()
    assert legacy.read_text().startswith("# Research Backlog")


def test_an_unknown_writer_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        backlog.update(tmp_path, "someone", lambda tx: None)


def test_a_failing_transaction_writes_nothing(tmp_path: Path) -> None:
    path = _write_store(tmp_path, {"schema_version": "1.0", "entries": []})
    before = path.read_bytes()

    def boom(tx: backlog.Transaction) -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        backlog.update(tmp_path, "harvest", boom)
    assert path.read_bytes() == before


def _check(
    value: Any, schema: dict[str, Any], defs: dict[str, Any], where: str
) -> None:
    """A small walker for the subset of JSON Schema the committed file uses."""
    if "$ref" in schema:
        schema = defs[schema["$ref"].rsplit("/", 1)[1]]
    if "const" in schema:
        assert value == schema["const"], where
    if "enum" in schema:
        assert value in schema["enum"], where
    types = schema.get("type")
    if types is not None:
        names = types if isinstance(types, list) else [types]
        py = {
            "string": str,
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict,
            "null": type(None),
        }
        assert any(
            isinstance(value, py[n])
            and not (n == "integer" and isinstance(value, bool))
            for n in names
        ), f"{where}: {value!r} is not {names}"
    if isinstance(value, str):
        if "pattern" in schema:
            assert re.search(schema["pattern"], value), where
        if "minLength" in schema:
            assert len(value) >= schema["minLength"], where
    if isinstance(value, int) and not isinstance(value, bool) and "minimum" in schema:
        assert value >= schema["minimum"], where
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            _check(item, schema["items"], defs, f"{where}[{i}]")
    if isinstance(value, dict):
        for name in schema.get("required", []):
            assert name in value, f"{where}: missing {name}"
        for name, sub in schema.get("properties", {}).items():
            if name in value:
                _check(value[name], sub, defs, f"{where}.{name}")
        for rule in schema.get("allOf", []):
            cond = rule["if"]["properties"]
            if all(
                key in value and _matches(value[key], sub) for key, sub in cond.items()
            ):
                _check(value, rule["then"], defs, where)


def _matches(value: Any, sub: dict[str, Any]) -> bool:
    return "const" not in sub or value == sub["const"]


def test_store_validates_against_the_committed_schema(tmp_path: Path) -> None:
    seed = {
        "schema_version": "1.0",
        "entries": [
            {"title": "Hand added", "origin": "operator", "status": "open"},
            {
                "title": "deseq",
                "origin": "quarantine",
                "status": "dropped",
                "stem": "deseq",
                "kind": "rewrite",
                "detail": "bad",
            },
            {
                "id": "topic:cited",
                "title": "Cited",
                "origin": "harvest",
                "status": "resolved",
                "status_by": "harvest",
                "status_written": "resolved",
                "added": "2026-11-01",
                "updated": "2026-11-02",
                "first_seen_cycle": 1,
                "last_seen_cycle": 3,
                "seen_cycles": 2,
                "citation_count": 4,
                "cited_from": ["a.md"],
            },
        ],
    }
    _write_store(tmp_path, seed)
    assert _noop(tmp_path) is True
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    data = json.loads(
        state_layout.research_backlog_path(tmp_path).read_text(encoding="utf-8")
    )
    _check(data, schema, schema["$defs"], "$")
    assert len(data["entries"]) == 3
