"""Tier-1 unit tests for coverage-targets contract hash (T013)."""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.quality.baseline import coverage_targets_hash


def _write_targets(path: Path, categories: list[dict]) -> None:
    path.write_text(
        json.dumps({"categories": categories}, indent=2) + "\n",
        encoding="utf-8",
    )


def test_hash_stable_across_category_reordering(tmp_path: Path) -> None:
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    cats_a = [
        {"name": "flows", "note_type": "flow", "required_count": 3, "current": 1},
        {"name": "services", "note_type": "service", "required_count": 2, "current": 0},
    ]
    cats_b = list(reversed(cats_a))
    _write_targets(path_a, cats_a)
    _write_targets(path_b, cats_b)
    assert coverage_targets_hash(path_a) == coverage_targets_hash(path_b)


def test_mutating_current_does_not_change_hash(tmp_path: Path) -> None:
    path = tmp_path / "targets.json"
    base = [
        {
            "name": "concepts",
            "note_type": "concept",
            "required_count": 4,
            "current": 0,
        },
    ]
    _write_targets(path, base)
    before = coverage_targets_hash(path)
    mutated = [{**base[0], "current": 99}]
    _write_targets(path, mutated)
    assert coverage_targets_hash(path) == before


def test_mutating_required_count_changes_hash(tmp_path: Path) -> None:
    path = tmp_path / "targets.json"
    _write_targets(
        path,
        [
            {
                "name": "concepts",
                "note_type": "concept",
                "required_count": 4,
                "current": 2,
            },
        ],
    )
    before = coverage_targets_hash(path)
    _write_targets(
        path,
        [
            {
                "name": "concepts",
                "note_type": "concept",
                "required_count": 5,
                "current": 2,
            },
        ],
    )
    assert coverage_targets_hash(path) != before


def test_target_count_alias_maps_to_required_count(tmp_path: Path) -> None:
    """Production ``coverage-targets.json`` uses ``target_count`` / ``met_count``."""
    path = tmp_path / "targets.json"
    _write_targets(
        path,
        [
            {
                "name": "concepts",
                "note_type": "concept",
                "target_count": 4,
                "met_count": 2,
            },
        ],
    )
    alias_path = tmp_path / "alias.json"
    _write_targets(
        alias_path,
        [
            {
                "name": "concepts",
                "note_type": "concept",
                "required_count": 4,
                "current": 2,
            },
        ],
    )
    assert coverage_targets_hash(path) == coverage_targets_hash(alias_path)
