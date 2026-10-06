"""FR5 (spec 068) — quality-gated guard against the rc7 ``0% → 0%`` regression.

A multi-category vault (N notes × M categories, mixed slug / display_name
matching, scaffold ``NN - Title`` dirs) carrying a *stale* ``coverage-targets.json``
(the rc7 shape: ~107 notes on disk but a met_count summing to a handful) must,
after the 068 disk recompute, report **non-zero** coverage — both in the runtime
``coverage_snapshot`` the digest reads and in the harness coverage metric.

Wired into ``build.sh``'s SMOKE_TESTS so a regression that re-introduces the
stale incremental model (or breaks the recompute) hard-fails the release gate.
"""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.pipeline.coverage import recompute_from_disk, save_targets
from research_framework.pipeline.quality_report import _build_coverage_snapshot
from research_framework.quality.metrics.coverage import compute_coverage_metric
from research_framework.quality.models import CycleOutput, Fixture
from research_framework.spec.schema import CoverageCategory, CoverageTargets

# (dir, slug, display_name, note_type, n_notes, coverage_category style)
_CATEGORIES = [
    ("01 - Concepts", "concepts", "Concepts", "concept", 8, "slug"),
    ("02 - Algorithms", "algorithms", "Algorithms", "concept", 6, "display"),
    ("13 - Infrastructure", "infrastructure", "Infrastructure", "concept", 5, "slug"),
]


def _build_multi_category_vault(root: Path) -> Path:
    vault = root / "coverage-multi"
    (vault / "_pipeline").mkdir(parents=True)
    (vault / "research.spec.md").write_text(
        "---\nname: coverage-multi\ncoverage_targets:\n  categories:\n"
        + "".join(
            f"    - {{name: {slug}, note_type: {nt}, target_count: {n}}}\n"
            for _d, slug, _dn, nt, n, _style in _CATEGORIES
        )
        + "---\n",
        encoding="utf-8",
    )

    cats: list[CoverageCategory] = []
    for dirname, slug, display, note_type, n_notes, style in _CATEGORIES:
        cat_dir = vault / "data_vault" / dirname
        cat_dir.mkdir(parents=True)
        cov_value = slug if style == "slug" else display
        for i in range(n_notes):
            (cat_dir / f"{slug}-{i:02d}.md").write_text(
                f"---\ntype: {note_type}\ntitle: {display} {i}\n"
                f"coverage_category: {cov_value}\n---\n\nBody.\n",
                encoding="utf-8",
            )
        # Stale met_count (the rc7 shape): far below the on-disk reality. A
        # correct recompute heals it to n_notes (== target ⇒ category met); the
        # buggy stale value (1) would leave every category unmet ⇒ 0% coverage.
        cats.append(
            CoverageCategory(
                name=slug,
                display_name=display,
                note_type=note_type,
                target_count=n_notes,
                met_count=1,
            )
        )
    save_targets(vault, CoverageTargets(categories=cats))
    return vault


def test_recompute_heals_stale_counts_to_disk_reality(tmp_path: Path) -> None:
    vault = _build_multi_category_vault(tmp_path)
    targets = recompute_from_disk(vault)
    by = {c.name: c.met_count for c in targets.categories}
    expected = {slug: n for _d, slug, _dn, _nt, n, _s in _CATEGORIES}
    assert by == expected
    assert sum(by.values()) == sum(expected.values()) > 0


def test_digest_snapshot_is_non_zero_after_recompute(tmp_path: Path) -> None:
    """The coverage_snapshot the digest reads shows real %, never 0% → 0%."""
    vault = _build_multi_category_vault(tmp_path)
    targets = recompute_from_disk(vault)
    snap = _build_coverage_snapshot(targets, {})
    assert snap, "snapshot must not be empty"
    assert all(row["fill_pct"] > 0.0 for row in snap.values())


def test_harness_coverage_metric_non_zero(tmp_path: Path) -> None:
    """The spec-022 harness coverage metric reports non-zero coverage."""
    vault = _build_multi_category_vault(tmp_path)
    recompute_from_disk(vault)

    cyc = vault / "_pipeline" / "cycles"
    cyc.mkdir(parents=True, exist_ok=True)
    targets = recompute_from_disk(vault)
    report = cyc / "cycle-001-quality-report.json"
    report.write_text(
        json.dumps({"coverage_snapshot": _build_coverage_snapshot(targets, {})}),
        encoding="utf-8",
    )
    fixture = Fixture(
        name="coverage-multi",
        vault_dir=vault,
        spec_path=vault / "research.spec.md",
        settings_path=vault / "settings.yaml",
        coverage_targets_path=vault / "_pipeline" / "coverage-targets.json",
        fake_agent_responses_dir=vault / "fake_agent_responses",
        note_count_target=sum(n for *_r, n, _s in _CATEGORIES),
        failure_mode="stale-coverage-count",
    )
    cycle = CycleOutput(
        fixture_name="coverage-multi",
        cycle_number=1,
        exit_code=0,
        quality_report_path=report,
        research_report_path=vault / "cycle-001-research.json",
        notes_written=[],
        sg_trips=[],
    )
    metric = compute_coverage_metric(fixture, [cycle])
    assert metric["coverage_pct"] > 0.0
    assert sum(metric["notes_per_category"].values()) > 0
