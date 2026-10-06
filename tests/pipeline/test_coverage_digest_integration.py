"""FR3 (spec 068) — the digest reflects the recomputed coverage.

Proves the full chain recompute_from_disk → quality-report snapshot →
``build_coverage_delta`` / ``detect_gaps`` produces real, non-zero coverage and
does NOT mark a growing category "stagnant" (the rc7 ``0% → 0%`` regression).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from research_framework.pipeline.coverage import recompute_from_disk, save_targets
from research_framework.pipeline.digest.ranker import (
    detect_gaps,
    format_progress_delta,
    format_progress_pct,
)
from research_framework.pipeline.digest.scope import CycleScope
from research_framework.pipeline.digest.sections import build_coverage_delta
from research_framework.pipeline.quality_report import _build_coverage_snapshot
from research_framework.spec.schema import CoverageCategory, CoverageTargets


def _write_note(dir_: Path, filename: str, **fm: object) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    for key, value in fm.items():
        lines.append(f"{key}: {value}")
    lines += ["---", "", "Body.", ""]
    (dir_ / filename).write_text("\n".join(lines), encoding="utf-8")


def _emit_cycle_report(
    vault: Path, cycle: int, prev_snap: dict
) -> tuple[CycleScope, dict]:
    targets = recompute_from_disk(vault)
    snap = _build_coverage_snapshot(targets, prev_snap)
    cdir = vault / "_pipeline" / "cycles"
    cdir.mkdir(parents=True, exist_ok=True)
    qpath = cdir / f"cycle-{cycle:03d}-quality-report.json"
    qpath.write_text(json.dumps({"coverage_snapshot": snap}), encoding="utf-8")
    scope = CycleScope(
        number=cycle,
        cycle_dir=cdir,
        quality_report_path=qpath,
        finished_at=datetime.now(UTC),
        report_path=None,
    )
    return scope, snap


def test_digest_shows_real_coverage_not_zero(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    concepts = vault / "data_vault" / "01 - Concepts"
    (vault / "_pipeline").mkdir(parents=True)
    save_targets(
        vault,
        CoverageTargets(
            categories=[
                CoverageCategory(
                    name="concepts",
                    display_name="Concepts",
                    note_type="concept",
                    target_count=10,
                )
            ]
        ),
    )

    # Cycle 1 writes 3 notes; cycle 2 writes 3 more.
    for i in range(3):
        _write_note(concepts, f"C{i}.md", type="concept", coverage_category="concepts")
    scope1, snap1 = _emit_cycle_report(vault, 1, {})
    for i in range(3, 6):
        _write_note(concepts, f"C{i}.md", type="concept", coverage_category="concepts")
    scope2, _snap2 = _emit_cycle_report(vault, 2, snap1)

    categories = [{"name": "concepts", "target_count": 10}]
    delta = build_coverage_delta(categories, [scope1, scope2])
    assert delta  # not empty
    name, start, end, change = delta[0]
    assert name == "concepts"
    assert end > 0.0  # real coverage, not 0% → 0%
    assert change > 0.0  # coverage grew cycle-over-cycle

    gaps = detect_gaps(
        categories=categories,
        first_report={"coverage_snapshot": snap1},
        last_report={
            "coverage_snapshot": _build_coverage_snapshot(
                recompute_from_disk(vault), snap1
            )
        },
        last_cycle=2,
    )
    # A growing category must NOT be flagged stagnant.
    assert all(g.category != "concepts" or g.kind != "stagnant" for g in gaps)


_ONE_CATEGORY = [{"name": "concepts", "target_count": 4}]


def _report(met: int) -> dict:
    """A cycle quality report's coverage block, exactly as the pipeline writes it."""
    targets = CoverageTargets(
        categories=[
            CoverageCategory(
                name="concepts", note_type="concept", target_count=4, met_count=met
            )
        ]
    )
    return {"coverage_snapshot": _build_coverage_snapshot(targets, {})}


def test_a_met_category_is_not_reported_as_a_gap() -> None:
    """``fill_pct`` is a fraction (spec 017 schema: 0..1), not a percentage.

    The gap detector compared it with the category's target COUNT, so a fully
    met category (1.0) sat "below target" for any target above one note and
    every digest listed it as stagnant.
    """
    gaps = detect_gaps(
        categories=_ONE_CATEGORY,
        first_report=_report(4),
        last_report=_report(4),
        last_cycle=2,
    )

    assert gaps == []


def test_a_flat_unmet_category_is_stagnant_at_its_real_percentage() -> None:
    gaps = detect_gaps(
        categories=_ONE_CATEGORY,
        first_report=_report(2),
        last_report=_report(2),
        last_cycle=2,
    )

    assert [(g.category, g.kind) for g in gaps] == [("concepts", "stagnant")]
    assert format_progress_pct(gaps[0].progress_end) == "50%", (
        "half the target is 50%, not the stored fraction printed as 0.5%"
    )


def test_coverage_delta_renders_the_stored_fraction_as_a_percentage(
    tmp_path: Path,
) -> None:
    cdir = tmp_path / "_pipeline" / "cycles"
    cdir.mkdir(parents=True)
    scopes = []
    for cycle, met in ((1, 1), (2, 3)):
        qpath = cdir / f"cycle-{cycle:03d}-quality-report.json"
        qpath.write_text(json.dumps(_report(met)), encoding="utf-8")
        scopes.append(
            CycleScope(
                number=cycle,
                cycle_dir=cdir,
                quality_report_path=qpath,
                finished_at=datetime.now(UTC),
                report_path=None,
            )
        )

    [(_name, start, end, change)] = build_coverage_delta(_ONE_CATEGORY, scopes)

    assert (
        format_progress_pct(start),
        format_progress_pct(end),
        format_progress_delta(change),
    ) == ("25%", "75%", "+50%")
