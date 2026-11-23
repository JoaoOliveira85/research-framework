"""Tier 1: a spec that declares no ``research_mode`` is ``expand`` (spec 087
FR-016)."""

from __future__ import annotations

from pathlib import Path

from research_framework.spec.parser import parse
from research_framework.spec.schema import SpecConfig
from research_framework.spec.simple import expand, parse_simple

_SIMPLE = '---\nname: "M"\nowner: "t"\ntopic: "A topic"\n{extra}---\n\nBody.\n'
_FULL = '---\nname: "M"\nowner: "t"\n{extra}---\n\nBody.\n'


def test_a_spec_that_declares_no_mode_is_expand(tmp_path: Path) -> None:
    simple_path = tmp_path / "simple.spec.md"
    simple_path.write_text(_SIMPLE.format(extra=""), encoding="utf-8")
    assert parse_simple(simple_path).research_mode == "expand"
    assert (
        expand(parse_simple(simple_path), location=tmp_path).research_mode == "expand"
    )

    full_path = tmp_path / "full.spec.md"
    full_path.write_text(_FULL.format(extra=""), encoding="utf-8")
    assert parse(full_path).research_mode == "expand"
    assert SpecConfig.from_dict({"name": "M", "owner": "t"}).research_mode == "expand"


def test_a_declared_mode_is_kept(tmp_path: Path) -> None:
    for mode in ("bootstrap", "refresh", "expand"):
        path = tmp_path / f"{mode}.spec.md"
        path.write_text(
            _SIMPLE.format(extra=f"research_mode: {mode}\n"), encoding="utf-8"
        )
        assert parse_simple(path).research_mode == mode
