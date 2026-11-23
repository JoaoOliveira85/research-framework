"""Tier 1: ``note_types[].review_after_days`` (spec 087 FR-009)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from research_framework.spec.parsed import load_parsed_spec
from research_framework.spec.parser import parse
from research_framework.spec.schema import (
    NoteTypeConfig,
    SpecConfig,
    SpecValidationError,
)
from research_framework.spec.simple import expand, parse_simple
from research_framework.spec.validator import validate

_SIMPLE = """\
---
name: "Review Vault"
owner: "tester"
topic: "A small topic for review tests"
note_types:
  - name: concept
    folder: "01 - Concepts"
    review_after_days: 90
  - name: source
    folder: "02 - Sources"
---

Body.
"""

_FULL = """\
---
name: "Review Vault"
owner: "tester"
note_types:
  - name: concept
    folder: "01 - Concepts"
    review_after_days: 90
  - name: source
    folder: "02 - Sources"
---

Body.
"""


def _spec_with(value: Any, tmp_path: Path) -> SpecConfig:
    path = tmp_path / "research.spec.md"
    path.write_text(_SIMPLE, encoding="utf-8")
    spec = expand(parse_simple(path), location=tmp_path)
    spec.note_types[0].review_after_days = value
    return spec


def test_the_key_survives_both_spec_formats_and_the_parsed_cache(
    tmp_path: Path,
) -> None:
    simple_path = tmp_path / "simple" / "research.spec.md"
    simple_path.parent.mkdir()
    simple_path.write_text(_SIMPLE, encoding="utf-8")
    simple = expand(parse_simple(simple_path), location=simple_path.parent)

    full_path = tmp_path / "full.spec.md"
    full_path.write_text(_FULL, encoding="utf-8")
    full = parse(full_path)

    for spec in (simple, full):
        by_name = {nt.name: nt for nt in spec.note_types}
        assert by_name["concept"].review_after_days == 90
        assert by_name["source"].review_after_days is None
        # the dict round trip keeps it, and omits it when None
        round_trip = SpecConfig.from_dict(spec.to_dict())
        assert {nt.name: nt.review_after_days for nt in round_trip.note_types} == {
            "concept": 90,
            "source": None,
        }
        dicts = {d["name"]: d for d in spec.to_dict()["note_types"]}
        assert dicts["concept"]["review_after_days"] == 90
        assert "review_after_days" not in dicts["source"]

    # the parsed cache a vault actually reads
    vault = simple_path.parent
    (vault / "_pipeline").mkdir()
    (vault / "data_vault").mkdir()
    doc = load_parsed_spec(vault, write_cache=True)
    cached = {d["name"]: d for d in doc["note_types"]}
    assert cached["concept"]["review_after_days"] == 90
    assert "review_after_days" not in cached["source"]


@pytest.mark.parametrize(
    "value",
    [0, -1, -30, True, False, 1.5, 30.0, "30", "soon", [30]],
)
def test_zero_negative_and_non_integer_values_are_refused(
    value: Any, tmp_path: Path
) -> None:
    spec = _spec_with(value, tmp_path)

    with pytest.raises(SpecValidationError) as exc:
        validate(spec)

    messages = [m for m in exc.value.messages if "review_after_days" in m]
    assert messages, exc.value.messages
    assert "concept" in messages[0]
    assert "positive integer" in messages[0]


def test_a_non_integer_in_a_spec_file_is_refused_not_a_traceback(
    tmp_path: Path,
) -> None:
    path = tmp_path / "research.spec.md"
    path.write_text(_SIMPLE.replace("review_after_days: 90", "review_after_days: soon"))

    spec = expand(parse_simple(path), location=tmp_path)

    with pytest.raises(SpecValidationError) as exc:
        validate(spec)
    assert any("review_after_days" in m for m in exc.value.messages)


def test_a_positive_integer_is_accepted(tmp_path: Path) -> None:
    validate(_spec_with(1, tmp_path))
    validate(_spec_with(365, tmp_path))


def test_absent_means_none(tmp_path: Path) -> None:
    assert (
        NoteTypeConfig(name="n", description="", folder="f").review_after_days is None
    )
    assert NoteTypeConfig.from_dict({"name": "n"}).review_after_days is None
    assert NoteTypeConfig.from_dict({"name": "n", "review_after_days": None}) == (
        NoteTypeConfig.from_dict({"name": "n"})
    )
    assert (
        "review_after_days"
        not in NoteTypeConfig(name="n", description="", folder="f").to_dict()
    )
    validate(_spec_with(None, tmp_path))
