"""Issue #267 — a zero baseline must not be a free pass for the release gate.

`_delta_pct(0, x)` returns ``"n/a"`` and the old `_metric_verdict` mapped
``"n/a"`` to ``"pass"`` unconditionally. Seven to eight of the ten gated
metrics are ``0.0`` in all three committed baselines, so a `lower_is_better`
counter (``cycles_fail``, ``sg002_trip_count``, ``verifier_reject_rate``) could
explode from 0 to any value and the gate would still print PASS.

This is distinct from issue #268's "unmeasured" (a metric with nothing to
divide this run, `current is None`): that stays informational by design. A
zero *baseline* with a real, measured current value is a different case —
there IS a comparison to make, it just has no percentage scale to place on
the 5%/15% band, and the two must be told apart.

Only `lower_is_better` needs the special case: those metrics are
non-negative counts/rates, so a baseline of 0 is already the best possible
reading and any real increase off it is unambiguously a regression.
`higher_is_better` metrics baselined at 0 have the opposite property — 0 is
already the worst possible reading, so nothing can regress below it, and the
ordinary `n/a`-reads-as-`pass` path is already safe for them.
"""

from __future__ import annotations

import math

import pytest

from research_framework.quality.baseline import _metric_verdict, diff_against_baseline
from research_framework.quality.models import BaselineJSON, CurrentJSON


def _report_for(baseline_metrics: dict, current_metrics: dict) -> tuple:
    current = CurrentJSON(
        schema_version="1.0",
        fixture="x",
        run_timestamp="2026-01-01T00:00:00Z",
        coverage_targets_hash="sha256:deadbeef",
        metrics=current_metrics,
    )
    baseline = BaselineJSON(
        schema_version="1.0",
        fixture="x",
        baseline_commit="abc",
        last_updated="2026-01-01T00:00:00Z",
        last_updated_by="test",
        last_updated_reason="test",
        coverage_targets_hash="sha256:deadbeef",
        metrics=baseline_metrics,
    )
    report = diff_against_baseline(current, baseline)
    return report, report.fixtures["x"]


# --- _metric_verdict edge cases -------------------------------------------


def test_zero_baseline_lower_is_better_real_increase_fails() -> None:
    assert _metric_verdict(0, 2, "n/a", "lower_is_better") == "fail"


def test_zero_baseline_lower_is_better_still_zero_passes() -> None:
    assert _metric_verdict(0, 0, "n/a", "lower_is_better") == "pass"


def test_zero_baseline_higher_is_better_stays_pass() -> None:
    """These metrics are non-negative, so 0 is already the floor: nothing can
    regress below it, so a higher_is_better metric baselined at 0 has no
    hidden-regression risk and keeps the ordinary n/a-reads-as-pass path."""
    assert _metric_verdict(0, 0.5, "n/a", "higher_is_better") == "pass"
    assert _metric_verdict(0, 0, "n/a", "higher_is_better") == "pass"


def test_nonzero_baseline_verdicts_are_unchanged() -> None:
    """The fix must not touch the ordinary percentage-band path."""
    assert _metric_verdict(10, 10, 0.0, "higher_is_better") == "pass"
    assert _metric_verdict(10, 8, -20.0, "higher_is_better") == "fail"
    assert _metric_verdict(10, 12, 20.0, "lower_is_better") == "fail"


# --- diff_against_baseline: the gate itself --------------------------------


def test_cycles_fail_exploding_from_a_zero_baseline_fails_the_gate() -> None:
    """The exact scenario in issue #267: cycles_fail 0 -> 3, baseline 0."""
    _report, fx = _report_for(
        baseline_metrics={"cycle_health": {"cycles_fail": 0}},
        current_metrics={"cycle_health": {"cycles_fail": 3}},
    )

    assert fx.metric_diffs["cycle_health.cycles_fail"].verdict == "fail"
    assert fx.verdict == "fail"


def test_sg002_trip_count_exploding_from_a_zero_baseline_fails_the_gate() -> None:
    _report, fx = _report_for(
        baseline_metrics={"cycle_health": {"sg002_trip_count": 0}},
        current_metrics={"cycle_health": {"sg002_trip_count": 1}},
    )

    assert fx.metric_diffs["cycle_health.sg002_trip_count"].verdict == "fail"
    assert fx.verdict == "fail"


def test_a_lower_is_better_metric_still_zero_stays_a_pass() -> None:
    _report, fx = _report_for(
        baseline_metrics={"cycle_health": {"cycles_fail": 0}},
        current_metrics={"cycle_health": {"cycles_fail": 0}},
    )

    assert fx.metric_diffs["cycle_health.cycles_fail"].verdict == "pass"
    assert fx.verdict == "pass"


def test_a_higher_is_better_metric_climbing_off_a_zero_baseline_passes() -> None:
    """coverage_pct 0.0 -> 0.5 is an improvement, not a regression to catch."""
    _report, fx = _report_for(
        baseline_metrics={"coverage": {"coverage_pct": 0.0}},
        current_metrics={"coverage": {"coverage_pct": 0.5}},
    )

    assert fx.metric_diffs["coverage.coverage_pct"].verdict == "pass"
    assert fx.verdict == "pass"


@pytest.mark.parametrize(
    ("family", "metric", "baseline", "current"),
    [
        ("cycle_health", "cycles_fail", 0, math.nan),
        ("coverage", "coverage_pct", 0.5, math.nan),
        ("coverage", "coverage_pct", math.nan, 0.5),
    ],
    ids=["zero-baseline-current-nan", "band-current-nan", "baseline-nan"],
)
def test_a_nan_reading_fails_the_gate(
    family: str, metric: str, baseline: float, current: float
) -> None:
    """NaN compares false against every bound, so a metric that came out as
    NaN fell through each band (and the zero-baseline check) to "pass", and
    the gate passed on a reading that is not a number."""
    _report, fx = _report_for(
        baseline_metrics={family: {metric: baseline}},
        current_metrics={family: {metric: current}},
    )

    assert fx.metric_diffs[f"{family}.{metric}"].verdict == "fail"
    assert fx.verdict == "fail"


def test_a_real_zero_baseline_regression_and_a_true_unmeasured_metric_are_told_apart() -> (
    None
):
    """The two 'nothing to compare' shapes must not collapse into each other."""
    _report, fx = _report_for(
        baseline_metrics={
            "cycle_health": {"sg002_trip_count": 0},
            "note_quality": {"acronym_link_pct": 0.0},
        },
        current_metrics={
            "cycle_health": {"sg002_trip_count": 2},
            "note_quality": {
                "acronym_link_pct": None,
                "unmeasured": {"acronym_link_pct": "no_acronym_occurrences_in_notes"},
            },
        },
    )

    # The real regression from a zero baseline fails outright.
    assert fx.metric_diffs["cycle_health.sg002_trip_count"].verdict == "fail"
    # The genuinely-unmeasured metric (issue #268) stays purely informational.
    assert "note_quality.acronym_link_pct" not in fx.metric_diffs
    assert fx.unmeasured["note_quality.acronym_link_pct"] == (
        "no_acronym_occurrences_in_notes"
    )
    # One real regression is enough to fail the fixture, unmeasured or not.
    assert fx.verdict == "fail"
