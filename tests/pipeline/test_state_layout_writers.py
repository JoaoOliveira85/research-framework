"""Spec 083 T003-T006 — every state writer lands under ``_pipeline/state/``.

Each test drives a writer through its own public function and asserts the file
is at the :mod:`state_layout` path and not at the pre-083 path (FR-002, FR-004).
"""

from __future__ import annotations

from pathlib import Path

from research_framework.generator.scaffold import scaffold
from research_framework.pipeline import state_layout as L
from research_framework.pipeline.coverage import load_targets, save_targets
from research_framework.spec.parser import parse
from research_framework.spec.schema import CoverageCategory, CoverageTargets


def test_scaffold_seeds_coverage_targets_under_state(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    scaffold(parse(sample_spec_path), vault)
    assert L.coverage_targets_path(vault).is_file()
    assert not (vault / "_pipeline" / "coverage-targets.json").exists()


def test_save_and_load_targets_round_trip_at_the_state_path(tmp_path: Path) -> None:
    targets = CoverageTargets(
        categories=[CoverageCategory(name="c", note_type="x", target_count=3)]
    )
    save_targets(tmp_path, targets)
    assert L.coverage_targets_path(tmp_path).is_file()
    assert not (tmp_path / "_pipeline" / "coverage-targets.json").exists()
    assert load_targets(tmp_path).categories[0].name == "c"
