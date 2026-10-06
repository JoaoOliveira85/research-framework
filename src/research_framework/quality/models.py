"""Shared types for the spec-022 quality harness."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from research_framework.pipeline.steps._types import (
    PostprocessResult,
    ResearchResult,
    ScoutResult,
)

# Metric compute functions receive a fixture and all cycle outputs for that run.
MetricComputeFn = Callable[["Fixture", list["CycleOutput"]], dict[str, Any]]


@dataclass(frozen=True)
class Fixture:
    """A named harness target under ``tests/fixtures/quality/<name>/``."""

    name: str
    vault_dir: Path
    spec_path: Path
    settings_path: Path
    coverage_targets_path: Path
    fake_agent_responses_dir: Path
    note_count_target: int
    failure_mode: str


@dataclass
class MetricFamily:
    """Named bundle of related quality metrics (v1: coverage, cycle_health, note_quality)."""

    name: str
    compute_fn: MetricComputeFn
    metrics: list[str]
    baseline_subset: dict[str, str]


@dataclass
class CycleOutput:
    """Read-only handle for one ``run_cycle_steps`` invocation."""

    fixture_name: str
    cycle_number: int
    exit_code: int
    quality_report_path: Path
    research_report_path: Path
    notes_written: list[Path] = field(default_factory=list)
    scout_topics: list[dict[str, Any]] = field(default_factory=list)
    sg_trips: list[str] = field(default_factory=list)
    scout_result: ScoutResult | None = None
    research_result: ResearchResult | None = None
    postprocess_result: PostprocessResult | None = None


@dataclass
class BaselineJSON:
    """Committed gold-standard per fixture (``*.baseline.json``)."""

    schema_version: str
    fixture: str
    baseline_commit: str
    last_updated: str
    last_updated_by: str
    last_updated_reason: str
    coverage_targets_hash: str
    metrics: dict[str, dict[str, Any]]


@dataclass
class CurrentJSON:
    """Runtime harness output per fixture (``*.current.json``)."""

    schema_version: str
    fixture: str
    run_timestamp: str
    coverage_targets_hash: str
    metrics: dict[str, dict[str, Any]]


@dataclass
class MetricDiff:
    """Per-metric regression diff entry."""

    baseline: float
    current: float
    delta_pct: float | str
    direction: str
    verdict: str


@dataclass
class FixtureRegression:
    """Per-fixture slice of a regression report."""

    verdict: str
    metric_diffs: dict[str, MetricDiff]
    summary: str
    unmeasured: dict[str, str] = field(default_factory=dict)
    """Gated metrics this run could not measure, mapped to why (issue #268).

    A metric with an empty denominator is not diffable, so it carries no
    verdict. Naming it here keeps a non-measurement from reading as a pass.
    """


@dataclass
class RegressionReport:
    """Aggregated diff across all fixtures in one harness run."""

    schema_version: str
    run_timestamp: str
    harness_version: str
    verdict: str
    fixtures: dict[str, FixtureRegression]
