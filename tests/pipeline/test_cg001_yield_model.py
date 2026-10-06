"""CG-001 configurable cycle-yield model (spec 051 FR1).

Replaces the old ``test_remaining_yield_scaling.py`` (capped + staleness-
staircase model, removed in FR1 per research D1). Covers the multiplicative
``base × cadence_factor × coverage_factor`` model, the bucket boundaries
(research U2: exact 50%/80% coverage + 24h/7d/14d cadence land deterministically),
clamping, the dormant-vault headline scenario, and the migrated
``_hours_since_last_cycle`` coverage.

The *tech-lite quality baseline* (FR1's "defaults must not move the harness")
is enforced end-to-end by ``./build.sh --quality`` (task T016), not here — a
unit test cannot replicate the harness's metric pipeline.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from research_framework.pipeline.coverage import (
    YieldTarget,
    _cadence_bucket,
    _coverage_bucket,
    _hours_since_last_cycle,
    compute_yield_target,
    remaining_yield,
    save_targets,
)
from research_framework.pipeline.settings import CycleYieldSettings
from research_framework.spec.schema import CoverageCategory, CoverageTargets


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _set_coverage(vault: Path, target: int, met: int) -> None:
    cat = CoverageCategory(
        name="concepts", note_type="concept", target_count=target, met_count=met
    )
    save_targets(vault, CoverageTargets(categories=[cat]))


def _write_prior_cycle(vault: Path, cycle_num: int, hours_ago: float) -> None:
    cycles_dir = vault / "_pipeline" / "cycles"
    cycles_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC) - timedelta(hours=hours_ago)
    (cycles_dir / f"cycle-{cycle_num:03d}-research.json").write_text(
        json.dumps({"cycle": cycle_num, "timestamp": ts.isoformat()}),
        encoding="utf-8",
    )


def _targets(target: int, met: int) -> CoverageTargets:
    return CoverageTargets(
        categories=[
            CoverageCategory(
                name="c", note_type="concept", target_count=target, met_count=met
            )
        ]
    )


# --------------------------------------------------------------------------- #
# cadence buckets (boundaries pinned — research U2)
# --------------------------------------------------------------------------- #
def test_cadence_cold_start_is_monthly() -> None:
    # No prior cycle → most generous bucket (fresh/dormant vault writes a batch).
    assert _cadence_bucket(None) == "monthly"


def test_cadence_boundaries() -> None:
    assert _cadence_bucket(0.0) == "daily"
    assert _cadence_bucket(23.9) == "daily"
    assert _cadence_bucket(24.0) == "weekly"  # 24h → weekly
    assert _cadence_bucket(167.9) == "weekly"
    assert _cadence_bucket(168.0) == "biweekly"  # 7d → biweekly
    assert _cadence_bucket(335.9) == "biweekly"
    assert _cadence_bucket(336.0) == "monthly"  # 14d → monthly
    assert _cadence_bucket(10_000.0) == "monthly"


# --------------------------------------------------------------------------- #
# coverage buckets (exact 50% / 80% land in the middle — research U2)
# --------------------------------------------------------------------------- #
def test_coverage_no_targets_is_above_80() -> None:
    assert _coverage_bucket(CoverageTargets(categories=[])) == "coverage_above_80pct"


def test_coverage_boundaries() -> None:
    assert _coverage_bucket(_targets(100, 49)) == "coverage_below_50pct"  # 0.49
    assert _coverage_bucket(_targets(10, 5)) == "coverage_50_to_80pct"  # exact 0.50
    assert _coverage_bucket(_targets(100, 80)) == "coverage_50_to_80pct"  # exact 0.80
    assert _coverage_bucket(_targets(100, 81)) == "coverage_above_80pct"  # 0.81
    assert _coverage_bucket(_targets(10, 0)) == "coverage_below_50pct"  # 0.0
    assert _coverage_bucket(_targets(10, 10)) == "coverage_above_80pct"  # 1.0


# --------------------------------------------------------------------------- #
# compute_yield_target — the matrix + clamping
# --------------------------------------------------------------------------- #
def test_dormant_vault_headline_scenario(tmp_path: Path) -> None:
    # The FR1 headline: a long-dormant (cold), <50%-covered vault should aim
    # high. ceil(5 * 8.0 * 1.5) = 60, clamped to ceiling 50 — NOT 5-8.
    _set_coverage(tmp_path, target=100, met=0)
    yt = compute_yield_target(tmp_path, cycle_number=1, max_cycles=20)
    assert isinstance(yt, YieldTarget)
    assert (yt.cadence_bucket, yt.coverage_bucket) == (
        "monthly",
        "coverage_below_50pct",
    )
    assert yt.target == 50  # clamped at max_ceiling


def test_daily_rerun_low_target(tmp_path: Path) -> None:
    # 12h since last cycle, 0% coverage: ceil(5 * 1.0 * 1.5) = 8.
    _set_coverage(tmp_path, target=100, met=0)
    _write_prior_cycle(tmp_path, cycle_num=1, hours_ago=12.0)
    yt = compute_yield_target(tmp_path, cycle_number=2, max_cycles=20)
    assert yt.cadence_bucket == "daily"
    assert yt.target == 8


def test_weekly_midcoverage(tmp_path: Path) -> None:
    # 48h (weekly), 50% coverage (middle): ceil(5 * 3.0 * 1.0) = 15.
    _set_coverage(tmp_path, target=10, met=5)
    _write_prior_cycle(tmp_path, cycle_num=1, hours_ago=48.0)
    yt = compute_yield_target(tmp_path, cycle_number=2, max_cycles=20)
    assert (yt.cadence_bucket, yt.coverage_bucket) == ("weekly", "coverage_50_to_80pct")
    assert yt.target == 15


def test_biweekly_high_coverage(tmp_path: Path) -> None:
    # 200h (biweekly), >80% coverage: ceil(5 * 5.0 * 0.5) = 13.
    _set_coverage(tmp_path, target=10, met=9)
    _write_prior_cycle(tmp_path, cycle_num=1, hours_ago=200.0)
    yt = compute_yield_target(tmp_path, cycle_number=2, max_cycles=20)
    assert (yt.cadence_bucket, yt.coverage_bucket) == (
        "biweekly",
        "coverage_above_80pct",
    )
    assert yt.target == 13


def test_clamp_to_floor(tmp_path: Path) -> None:
    # Custom settings whose raw target falls below min_floor → clamped up.
    # Keep unmet > 0 (85% covered) so the no-work short-circuit doesn't fire.
    _set_coverage(tmp_path, target=100, met=85)  # 0.85 → above_80 (0.5), unmet=15
    cy = CycleYieldSettings(base_notes_per_cycle=1, min_floor=10, max_ceiling=50)
    yt = compute_yield_target(tmp_path, cycle_number=1, max_cycles=20, cy=cy)
    assert yt.coverage_bucket == "coverage_above_80pct"
    assert yt.target == 10  # ceil(1 * 8.0 * 0.5)=4 → floored to 10


def test_fully_covered_vault_has_zero_yield(tmp_path: Path) -> None:
    # All targets met (unmet == 0) → no mandatory yield (old-model invariant).
    _set_coverage(tmp_path, target=10, met=10)
    yt = compute_yield_target(tmp_path, cycle_number=1, max_cycles=20)
    assert yt.target == 0


def test_clamp_to_ceiling(tmp_path: Path) -> None:
    _set_coverage(tmp_path, target=100, met=0)  # below_50 → 1.5
    cy = CycleYieldSettings(base_notes_per_cycle=5, min_floor=1, max_ceiling=3)
    yt = compute_yield_target(tmp_path, cycle_number=1, max_cycles=20, cy=cy)
    assert yt.target == 3  # 60 → capped to 3


def test_unknown_bucket_factor_falls_back_to_one(tmp_path: Path) -> None:
    # If a factor map is missing a bucket key, the multiplier defaults to 1.0.
    _set_coverage(tmp_path, target=100, met=0)  # below_50
    cy = CycleYieldSettings(
        base_notes_per_cycle=5,
        cadence_factor={"daily": 1.0},  # 'monthly' missing → 1.0
        coverage_factor={"coverage_below_50pct": 2.0},
        min_floor=1,
        max_ceiling=50,
    )
    yt = compute_yield_target(tmp_path, cycle_number=1, max_cycles=20, cy=cy)
    assert yt.cadence_factor == 1.0  # missing 'monthly' → default 1.0
    assert yt.target == 10  # ceil(5 * 1.0 * 2.0)


def test_remaining_yield_shim_returns_target_int(tmp_path: Path) -> None:
    _set_coverage(tmp_path, target=100, met=0)
    assert remaining_yield(tmp_path, 1, 20) == 50
    assert isinstance(remaining_yield(tmp_path, 1, 20), int)


def test_bare_vault_no_targets_zero_yield(tmp_path: Path) -> None:
    # No coverage-targets.json, no settings.yaml → no crash; with no targets
    # there is no coverage work, so the mandatory yield is 0 (always-PASS gate).
    yt = compute_yield_target(tmp_path, cycle_number=1, max_cycles=20)
    assert yt.coverage_bucket == "coverage_above_80pct"  # no targets
    assert yt.target == 0


# --------------------------------------------------------------------------- #
# _hours_since_last_cycle (migrated from the retired scaling test file)
# --------------------------------------------------------------------------- #
def test_hours_since_last_cycle_none_with_no_prior(tmp_path: Path) -> None:
    assert _hours_since_last_cycle(tmp_path, current_cycle=1) is None
    assert _hours_since_last_cycle(tmp_path, current_cycle=5) is None


def test_hours_since_last_cycle_reads_highest_prior(tmp_path: Path) -> None:
    _write_prior_cycle(tmp_path, cycle_num=1, hours_ago=48.0)
    _write_prior_cycle(tmp_path, cycle_num=2, hours_ago=12.0)
    hours = _hours_since_last_cycle(tmp_path, current_cycle=3)
    assert hours is not None
    assert 11.5 < hours < 12.5


def test_hours_since_last_cycle_unparseable_timestamp(tmp_path: Path) -> None:
    cycles_dir = tmp_path / "_pipeline" / "cycles"
    cycles_dir.mkdir(parents=True, exist_ok=True)
    (cycles_dir / "cycle-001-research.json").write_text(
        json.dumps({"cycle": 1, "timestamp": "not-a-date"}), encoding="utf-8"
    )
    assert _hours_since_last_cycle(tmp_path, current_cycle=2) is None
