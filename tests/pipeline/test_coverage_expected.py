"""Tests for feature-002 coverage extensions: expected_filenames + resume aids."""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.pipeline.coverage import (
    existing_vault_filenames,
    merge_expected_filenames_from_scan,
    save_targets,
    unmet_expected_filenames,
)
from research_framework.spec.schema import CoverageCategory, CoverageTargets


def _stage(tmp_path: Path, categories: list[CoverageCategory], scan: dict) -> Path:
    vault = tmp_path / "vault"
    pipeline = vault / "_pipeline"
    pipeline.mkdir(parents=True)
    (vault / "data_vault").mkdir()
    save_targets(vault, CoverageTargets(categories=categories))
    (pipeline / "repo-scan.json").write_text(json.dumps(scan))
    return vault


def test_merge_expected_filenames_populates_and_bumps_target_count(
    tmp_path: Path,
) -> None:
    vault = _stage(
        tmp_path,
        categories=[
            CoverageCategory(name="services", note_type="service", target_count=2),
            CoverageCategory(name="concepts", note_type="concept", target_count=50),
        ],
        scan={
            "derived_targets": {
                "services": ["A.md", "B.md", "C.md", "D.md"],
                "concepts": ["ConceptX.md"],
                "flows": [],
                "decisions": [],
            }
        },
    )
    targets = merge_expected_filenames_from_scan(vault)
    services = next(c for c in targets.categories if c.name == "services")
    assert services.expected_filenames == ["A.md", "B.md", "C.md", "D.md"]
    # target_count bumped to match scanned count (4 > 2)
    assert services.target_count == 4

    concepts = next(c for c in targets.categories if c.name == "concepts")
    assert concepts.expected_filenames == ["ConceptX.md"]
    # target_count NOT dropped when scan has fewer than hand-typed (50 > 1)
    assert concepts.target_count == 50


def test_merge_handles_missing_scan(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    save_targets(
        vault,
        CoverageTargets(
            categories=[
                CoverageCategory(name="services", note_type="service", target_count=1)
            ]
        ),
    )
    # No repo-scan.json present → merge is a no-op
    targets = merge_expected_filenames_from_scan(vault)
    assert targets.categories[0].expected_filenames == []


def test_unmet_expected_filenames_skips_covered_and_met(tmp_path: Path) -> None:
    vault = _stage(
        tmp_path,
        categories=[
            CoverageCategory(
                name="services",
                note_type="service",
                target_count=3,
                expected_filenames=["A.md", "B.md", "C.md"],
            )
        ],
        scan={"derived_targets": {}},
    )
    # Write one of the expected notes
    (vault / "data_vault" / "A.md").write_text("---\ntitle: A\n---\n")
    missing = unmet_expected_filenames(vault)
    assert missing == {"services": ["B.md", "C.md"]}


def test_existing_vault_filenames_enumerates_notes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "data_vault" / "nested").mkdir(parents=True)
    (vault / "data_vault" / "One.md").write_text("---\n---\n")
    (vault / "data_vault" / "nested" / "Two.md").write_text("---\n---\n")
    names = existing_vault_filenames(vault)
    assert names == ["One.md", "Two.md"]
