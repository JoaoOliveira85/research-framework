"""Tests for sustained-error source health quality gate."""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.quality.source_health import (
    aggregate_module_cycle_verdicts,
    evaluate_sustained_error_gate,
    load_module_verdict_windows,
)


def test_sustained_error_over_fifty_percent_fails() -> None:
    module_verdicts = {"youtube": ["error", "error", "error"]}
    result = evaluate_sustained_error_gate(module_verdicts)
    assert result.passed is False
    assert "youtube" in result.message
    assert result.module_breakdown["youtube"] > 0.5


def test_empty_never_counts_toward_error_rate() -> None:
    module_verdicts = {
        "rss": ["empty", "ok", "error"],
        "reddit": ["empty", "empty", "ok"],
    }
    result = evaluate_sustained_error_gate(module_verdicts)
    assert result.passed is True
    assert result.module_breakdown["rss"] <= 0.5
    assert result.module_breakdown["reddit"] == 0.0


def test_fewer_than_three_cycles_does_not_fail() -> None:
    module_verdicts = {
        "youtube": ["error"],
        "rss": ["error", "ok"],
    }
    result = evaluate_sustained_error_gate(module_verdicts)
    assert result.passed is True


def test_source_health_gate_registered_in_quality_harness() -> None:
    from research_framework.quality.metrics import REGISTERED_METRIC_FAMILIES

    names = {family.name for family in REGISTERED_METRIC_FAMILIES}
    assert "source_health" in names
    family = next(f for f in REGISTERED_METRIC_FAMILIES if f.name == "source_health")
    assert family.compute_fn is not None
    assert "gate_passed" in family.metrics


def test_multi_source_window_aggregates_by_cycle_not_concatenation() -> None:
    """Concatenating per-source histories would miss sustained single-source errors."""
    per_source = [["error", "error", "error"], ["ok", "ok", "ok"]]
    window = aggregate_module_cycle_verdicts(per_source)
    assert window == ["error", "error", "error"]
    result = evaluate_sustained_error_gate({"rss": window})
    assert result.passed is False

    staggered = [["error", "ok", "ok"], ["ok", "error", "ok"]]
    staggered_window = aggregate_module_cycle_verdicts(staggered)
    assert staggered_window == ["error", "error", "ok"]
    staggered_result = evaluate_sustained_error_gate({"rss": staggered_window})
    assert staggered_result.passed is False


def test_load_module_verdict_windows_aligns_sources_by_cycle(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "modules" / "rss" / "manifest.yaml").parent.mkdir(parents=True)
    (vault / "modules" / "rss" / "manifest.yaml").write_text(
        "name: rss\n", encoding="utf-8"
    )
    wm_path = vault / "_pipeline" / "sources" / "rss" / "watermarks.json"
    wm_path.parent.mkdir(parents=True)
    wm_path.write_text(
        json.dumps(
            {
                "feed-a": {
                    "source_version": "v1",
                    "bridge_version": "0.8.0",
                    "extracted_at": "2026-06-01T00:00:00Z",
                    "verdict": "error",
                    "consecutive_empty_cycles": 0,
                    "recent_cycle_verdicts": ["error", "error", "error"],
                },
                "feed-b": {
                    "source_version": "v1",
                    "bridge_version": "0.8.0",
                    "extracted_at": "2026-06-01T00:00:00Z",
                    "verdict": "ok",
                    "consecutive_empty_cycles": 0,
                    "recent_cycle_verdicts": ["ok", "ok", "ok"],
                },
            }
        ),
        encoding="utf-8",
    )
    windows = load_module_verdict_windows(vault)
    assert windows["rss"] == ["error", "error", "error"]
