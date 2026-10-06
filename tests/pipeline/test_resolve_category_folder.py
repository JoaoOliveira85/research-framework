"""Spec 066 D7 — ``resolve_category_folder`` destination resolution."""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.pipeline.coverage import resolve_category_folder


def _vault(tmp_path: Path, dirs: list[str], categories: list[dict]) -> Path:
    vault = tmp_path / "v"
    for d in dirs:
        (vault / "data_vault" / d).mkdir(parents=True, exist_ok=True)
    (vault / "_pipeline").mkdir(parents=True, exist_ok=True)
    (vault / "_pipeline" / "coverage-targets.json").write_text(
        json.dumps({"categories": categories}), encoding="utf-8"
    )
    return vault


def test_explicit_category_matches_numbered_dir(tmp_path: Path) -> None:
    vault = _vault(
        tmp_path,
        ["01 - Concepts", "06 - Frameworks"],
        [
            {
                "name": "frameworks",
                "note_type": "concept",
                "target_count": 1,
                "display_name": "Frameworks",
            }
        ],
    )
    folder = resolve_category_folder(vault, {"coverage_category": "Frameworks"})
    assert folder == vault / "data_vault" / "06 - Frameworks"


def test_category_slug_matches_via_display_name(tmp_path: Path) -> None:
    vault = _vault(
        tmp_path,
        ["06 - Frameworks"],
        [
            {
                "name": "frameworks",
                "note_type": "concept",
                "target_count": 1,
                "display_name": "Frameworks",
            }
        ],
    )
    folder = resolve_category_folder(vault, {"coverage_category": "frameworks"})
    assert folder == vault / "data_vault" / "06 - Frameworks"


def test_falls_back_to_data_vault_root(tmp_path: Path) -> None:
    vault = _vault(tmp_path, [], [])
    folder = resolve_category_folder(vault, {"coverage_category": "Nowhere"})
    assert folder == vault / "data_vault"
