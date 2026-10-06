"""Metric family calculators for the quality harness (US2)."""

from __future__ import annotations

from typing import Any

from ..models import CycleOutput, Fixture, MetricFamily
from .cost_efficiency import (
    compute_cost_per_substantive_note,
    compute_source_cache_hit_ratio,
)
from .coverage import compute_coverage_metric
from .cycle_health import compute_cycle_health_metric
from .note_quality import compute_note_quality_metric
from .source_health import compute_source_health_metric
from .source_quality import compute_source_quality_metric


def _compute_cost_efficiency_family(
    fixture: Fixture, cycle_outputs: list[CycleOutput]
) -> dict[str, Any]:
    note_metric = compute_cost_per_substantive_note(fixture, cycle_outputs)
    cache_metric = compute_source_cache_hit_ratio(fixture, cycle_outputs)
    return {**note_metric, **cache_metric}


REGISTERED_METRIC_FAMILIES: list[MetricFamily] = [
    MetricFamily(
        name="coverage",
        compute_fn=compute_coverage_metric,
        metrics=["coverage_pct", "notes_per_category", "spec_drift"],
        baseline_subset={
            "coverage_pct": "higher_is_better",
            "spec_drift": "lower_is_better",
        },
    ),
    MetricFamily(
        name="cycle_health",
        compute_fn=compute_cycle_health_metric,
        metrics=[
            "cycles_pass",
            "cycles_fail",
            "sg002_trip_count",
            "retry_once_rate",
            "verifier_reject_rate",
        ],
        baseline_subset={
            "cycles_pass": "higher_is_better",
            "cycles_fail": "lower_is_better",
            "sg002_trip_count": "lower_is_better",
            "verifier_reject_rate": "lower_is_better",
        },
    ),
    MetricFamily(
        name="note_quality",
        compute_fn=compute_note_quality_metric,
        metrics=[
            "template_compliance_pct",
            "per_template_section_fill",
            "acronym_link_pct",
        ],
        baseline_subset={
            "template_compliance_pct": "higher_is_better",
            "acronym_link_pct": "higher_is_better",
        },
    ),
    MetricFamily(
        name="cost_efficiency",
        compute_fn=_compute_cost_efficiency_family,
        metrics=["cost_per_substantive_note", "source_cache_hit_ratio"],
        baseline_subset={
            "cost_per_substantive_note": "lower_is_better",
        },
    ),
    MetricFamily(
        name="source_health",
        compute_fn=compute_source_health_metric,
        metrics=["gate_passed", "message", "module_error_rates"],
        baseline_subset={},
    ),
    MetricFamily(
        name="source_quality",
        compute_fn=compute_source_quality_metric,
        metrics=[
            "source_diversity_shannon",
            "broken_source_rate",
            "spec_source_utilization",
            "tier2_source_ratio",
        ],
        baseline_subset={
            "tier2_source_ratio": "lower_is_better",
        },
    ),
]

__all__ = (
    "REGISTERED_METRIC_FAMILIES",
    "compute_all_metrics",
    "compute_cost_per_substantive_note",
    "compute_coverage_metric",
    "compute_cycle_health_metric",
    "compute_note_quality_metric",
    "compute_source_cache_hit_ratio",
    "compute_source_health_metric",
    "compute_source_quality_metric",
)


def compute_all_metrics(
    fixture: Fixture, cycle_outputs: list[CycleOutput]
) -> dict[str, Any]:
    """Run every registered metric family and return the ``metrics`` subtree."""
    metrics: dict[str, Any] = {}
    for family in REGISTERED_METRIC_FAMILIES:
        metrics[family.name] = family.compute_fn(fixture, cycle_outputs)
    return metrics
