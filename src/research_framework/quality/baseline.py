"""Baseline helpers for the quality harness (spec 022)."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from research_framework import __version__

from .determinism import canonical_json_dumps
from .exceptions import BaselineMissingError, BaselineStaleError
from .models import (
    BaselineJSON,
    CurrentJSON,
    FixtureRegression,
    MetricDiff,
    RegressionReport,
)

__all__ = (
    "BaselineMissingError",
    "BaselineStaleError",
    "REGRESSION_FAIL_PCT",
    "REGRESSION_WARN_PCT",
    "coverage_targets_hash",
    "diff_against_baseline",
    "load_baseline_json",
    "merge_regression_reports",
)

REGRESSION_FAIL_PCT = 15.0
REGRESSION_WARN_PCT = 5.0

# v1 roll-up gated metrics (OI-D3); used when US2 registry is empty.
_V1_REGRESSION_METRICS: dict[str, str] = {
    "coverage.coverage_pct": "higher_is_better",
    "coverage.spec_drift": "lower_is_better",
    "cycle_health.cycles_pass": "higher_is_better",
    "cycle_health.cycles_fail": "lower_is_better",
    "cycle_health.sg002_trip_count": "lower_is_better",
    "note_quality.template_compliance_pct": "higher_is_better",
    "note_quality.acronym_link_pct": "higher_is_better",
}

_VERDICT_RANK = {"pass": 0, "warn": 1, "fail": 2}


def coverage_targets_hash(coverage_targets_path: Path) -> str:
    """Return ``sha256:<hex>`` of the coverage-targets *contract* fields only.

    Hashes ``categories[].{name, required_count, note_type}`` triples. Mutable
    fields such as ``current`` / ``met_count`` are excluded (research.md § D3).
    Production vault JSON may use ``target_count`` instead of ``required_count``;
    both map to the canonical ``required_count`` key in the hash payload.
    """
    raw = json.loads(coverage_targets_path.read_text(encoding="utf-8"))
    categories = raw.get("categories", [])
    triples: list[dict[str, Any]] = []
    for cat in categories:
        required = cat.get("required_count")
        if required is None:
            required = cat.get("target_count", 0)
        triples.append(
            {
                "name": cat["name"],
                "note_type": cat["note_type"],
                "required_count": int(required),
            }
        )
    payload = {"categories": triples}
    canonical = canonical_json_dumps(payload)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def load_baseline_json(path: Path) -> BaselineJSON:
    """Parse a committed ``*.baseline.json`` file."""
    if not path.is_file():
        raise BaselineMissingError()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return BaselineJSON(
        schema_version=raw["schema_version"],
        fixture=raw["fixture"],
        baseline_commit=raw["baseline_commit"],
        last_updated=raw["last_updated"],
        last_updated_by=raw["last_updated_by"],
        last_updated_reason=raw["last_updated_reason"],
        coverage_targets_hash=raw["coverage_targets_hash"],
        metrics=raw["metrics"],
    )


def diff_against_baseline(
    current: CurrentJSON,
    baseline: BaselineJSON,
) -> RegressionReport:
    """Diff *current* metrics against *baseline* using the moderate gate (OI-2)."""
    gated = _gated_metric_directions()
    metric_diffs: dict[str, MetricDiff] = {}
    unmeasured: dict[str, str] = {}
    for key, direction in sorted(gated.items()):
        family, _, metric_name = key.partition(".")
        base_val = _scalar_metric(baseline.metrics, family, metric_name)
        cur_val = _scalar_metric(current.metrics, family, metric_name)
        if cur_val is None:
            reason = _unmeasured_reason(current.metrics, family, metric_name)
            if reason:
                unmeasured[key] = reason
        if base_val is None or cur_val is None:
            continue
        delta_pct = _delta_pct(base_val, cur_val)
        verdict = _metric_verdict(base_val, cur_val, delta_pct, direction)
        metric_diffs[key] = MetricDiff(
            baseline=base_val,
            current=cur_val,
            delta_pct=delta_pct,
            direction=direction,
            verdict=verdict,
        )

    fixture_verdict = _rollup_verdict(d.verdict for d in metric_diffs.values())
    fails = sum(1 for d in metric_diffs.values() if d.verdict == "fail")
    warns = sum(1 for d in metric_diffs.values() if d.verdict == "warn")
    summary = f"{fails} regressions, {warns} warnings"
    if unmeasured:
        summary += f", {len(unmeasured)} unmeasured"
    fixture_reg = FixtureRegression(
        verdict=fixture_verdict,
        metric_diffs=metric_diffs,
        summary=summary,
        unmeasured=unmeasured,
    )
    return RegressionReport(
        schema_version="1.0",
        run_timestamp=current.run_timestamp,
        harness_version=__version__,
        verdict=fixture_reg.verdict,
        fixtures={current.fixture: fixture_reg},
    )


def merge_regression_reports(reports: list[RegressionReport]) -> RegressionReport:
    """Combine per-fixture reports into one top-level report."""
    if not reports:
        return RegressionReport(
            schema_version="1.0",
            run_timestamp="",
            harness_version=__version__,
            verdict="pass",
            fixtures={},
        )
    fixtures: dict[str, FixtureRegression] = {}
    for report in reports:
        fixtures.update(report.fixtures)
    top = _rollup_verdict(fr.verdict for fr in fixtures.values())
    return RegressionReport(
        schema_version="1.0",
        run_timestamp=reports[0].run_timestamp,
        harness_version=reports[0].harness_version,
        verdict=top,
        fixtures=fixtures,
    )


def _gated_metric_directions() -> dict[str, str]:
    from .metrics import REGISTERED_METRIC_FAMILIES

    if REGISTERED_METRIC_FAMILIES:
        result: dict[str, str] = {}
        for family in REGISTERED_METRIC_FAMILIES:
            for name, direction in family.baseline_subset.items():
                result[f"{family.name}.{name}"] = direction
        return result
    return dict(_V1_REGRESSION_METRICS)


def _scalar_metric(
    metrics: dict[str, dict[str, Any]],
    family: str,
    key: str,
) -> float | None:
    block = metrics.get(family, {})
    value = block.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _unmeasured_reason(
    metrics: dict[str, dict[str, Any]],
    family: str,
    key: str,
) -> str:
    """Why *family.key* could not be measured this run, per the metric family."""
    reasons = metrics.get(family, {}).get("unmeasured")
    if not isinstance(reasons, dict):
        return ""
    return str(reasons.get(key) or "")


def _delta_pct(baseline: float, current: float) -> float | str:
    if baseline == 0:
        return "n/a"
    return round((current - baseline) / baseline * 100.0, 1)


def _metric_verdict(
    base_val: float, cur_val: float, delta_pct: float | str, direction: str
) -> str:
    if math.isnan(base_val) or math.isnan(cur_val):
        # NaN compares false against every bound below and would fall through
        # to "pass": a reading that is not a number is a failed one.
        return "fail"
    if base_val == 0 and direction == "lower_is_better":
        # A `lower_is_better` counter (``cycles_fail``, ``sg002_trip_count``,
        # ``verifier_reject_rate``) baselined at 0 means nothing had gone
        # wrong yet, so any real increase off that floor IS the regression
        # in full — there's no 5%/15% band to place it in, and `_delta_pct`
        # returning `"n/a"` must not read as `pass` (issue #267). A
        # `higher_is_better` metric baselined at 0 needs no matching special
        # case: these metrics are non-negative, so 0 is already the worst
        # possible reading and nothing can regress below it.
        return "fail" if cur_val > 0 else "pass"
    if delta_pct == "n/a" or not isinstance(delta_pct, (int, float)):
        return "pass"
    if direction == "higher_is_better":
        if delta_pct < -REGRESSION_FAIL_PCT:
            return "fail"
        if delta_pct <= -REGRESSION_WARN_PCT:
            return "warn"
        return "pass"
    if direction == "lower_is_better":
        if delta_pct > REGRESSION_FAIL_PCT:
            return "fail"
        if delta_pct >= REGRESSION_WARN_PCT:
            return "warn"
        return "pass"
    return "pass"


def _rollup_verdict(verdicts: Any) -> str:
    ordered = list(verdicts)
    if not ordered:
        return "pass"
    return max(ordered, key=lambda v: _VERDICT_RANK.get(v, 0))
