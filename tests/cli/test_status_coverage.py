"""FR4 (spec 068) — ``./vault status`` surfaces the recomputed coverage.

Contract C3-a: status coverage uses the SAME source as the digest (the
per-category met/target fill the quality-report snapshot reports). A divergence
between status and digest would mean two sources of truth — exactly what 068
forbids.
"""

from __future__ import annotations

from pathlib import Path

from research_framework.cli.status import build_status_json
from research_framework.pipeline.coverage import recompute_from_disk, save_targets
from research_framework.pipeline.quality_report import _build_coverage_snapshot
from research_framework.spec.schema import CoverageCategory, CoverageTargets


def _write_note(dir_: Path, filename: str, **fm: object) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    for key, value in fm.items():
        lines.append(f"{key}: {value}")
    lines += ["---", "", "Body.", ""]
    (dir_ / filename).write_text("\n".join(lines), encoding="utf-8")


def _seed(vault: Path, *cats: CoverageCategory) -> None:
    (vault / "_pipeline").mkdir(parents=True, exist_ok=True)
    save_targets(vault, CoverageTargets(categories=list(cats)))


def test_status_coverage_matches_digest_snapshot_source(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    concepts = vault / "data_vault" / "01 - Concepts"
    _seed(
        vault,
        CoverageCategory(
            name="concepts",
            display_name="Concepts",
            note_type="concept",
            target_count=10,
        ),
    )
    for i in range(6):
        _write_note(concepts, f"C{i}.md", type="concept", coverage_category="concepts")

    targets = recompute_from_disk(vault)
    digest_snapshot = _build_coverage_snapshot(targets, {})

    status = build_status_json(vault)
    coverage = status["coverage"]
    assert isinstance(coverage, dict)
    cats = {c["name"]: c for c in coverage["categories"]}
    assert cats["concepts"]["met"] == 6
    assert cats["concepts"]["target"] == 10
    # One source of truth: status fill_pct == digest snapshot fill_pct.
    assert cats["concepts"]["fill_pct"] == digest_snapshot["concepts"]["fill_pct"]


def test_status_coverage_absent_when_no_targets(tmp_path: Path) -> None:
    """A bare vault (no coverage-targets.json) yields coverage: None, no crash."""
    vault = tmp_path / "vault"
    (vault / "_pipeline").mkdir(parents=True)
    status = build_status_json(vault)
    assert status["coverage"] is None
