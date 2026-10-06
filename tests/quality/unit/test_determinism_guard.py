"""Tier-1 unit tests for canonical JSON determinism helpers (T012)."""

from __future__ import annotations

import json

import pytest

from research_framework.quality import determinism
from research_framework.quality.determinism import (
    DeterminismError,
    assert_deterministic,
    canonical_json_dumps,
    canonical_json_write,
)


def test_nested_dict_keys_sorted_in_output() -> None:
    payload = {"z": 1, "a": {"y": 2, "b": 3}}
    text = canonical_json_dumps(payload)
    assert text.index('"a"') < text.index('"z"')
    assert text.index('"b"') < text.index('"y"')
    parsed = json.loads(text)
    assert list(parsed.keys()) == ["a", "z"]
    assert list(parsed["a"].keys()) == ["b", "y"]


def test_list_sorted_by_documented_name_key() -> None:
    payload = {
        "categories": [
            {"name": "flows", "note_type": "flow", "required_count": 3},
            {"name": "concepts", "note_type": "concept", "required_count": 4},
            {"name": "services", "note_type": "service", "required_count": 2},
        ]
    }
    first = canonical_json_dumps(payload)
    shuffled = {
        "categories": list(reversed(payload["categories"])),
    }
    second = canonical_json_dumps(shuffled)
    assert first == second


def test_float_truncated_to_four_decimal_places() -> None:
    payload = {"coverage_pct": 0.123456789, "nested": [1.99999]}
    text = canonical_json_dumps(payload)
    assert "0.1235" in text
    assert "2.0" in text
    round_trip = json.loads(text)
    assert round_trip["coverage_pct"] == 0.1235
    assert round_trip["nested"] == [2.0]


def test_canonical_json_write_round_trip(tmp_path) -> None:
    path = tmp_path / "out.json"
    payload = {"fixture": "tech-lite", "metrics": {"coverage": {"coverage_pct": 0.5}}}
    canonical_json_write(path, payload)
    assert path.read_text(encoding="utf-8") == canonical_json_dumps(payload)


def test_assert_deterministic_accepts_canonical_payload() -> None:
    payload = {
        "categories": [
            {"name": "b", "note_type": "concept", "required_count": 1},
            {"name": "a", "note_type": "service", "required_count": 2},
        ],
        "ratio": 0.3333333333,
    }
    assert_deterministic(payload, "coverage-contract")


def test_assert_deterministic_raises_on_divergence(monkeypatch) -> None:
    payload = {"a": 1}
    stable = canonical_json_dumps(payload)
    calls = {"n": 0}

    def flaky(p: object) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return stable
        return stable + " "

    monkeypatch.setattr(determinism, "canonical_json_dumps", flaky)
    with pytest.raises(DeterminismError, match="coverage-mismatch"):
        assert_deterministic(payload, "coverage-mismatch")
