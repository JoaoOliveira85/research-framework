"""Source health metric family for the quality harness (spec 038 FR-005)."""

from __future__ import annotations

from typing import Any

from research_framework.quality.source_health import (
    evaluate_sustained_error_gate,
    load_module_verdict_windows,
)

from ..models import CycleOutput, Fixture


def compute_source_health_metric(
    fixture: Fixture, cycle_outputs: list[CycleOutput]
) -> dict[str, Any]:
    """Evaluate sustained-error gate from per-module watermark verdict windows."""
    del cycle_outputs  # gate reads durable watermark state, not per-cycle outputs
    windows = load_module_verdict_windows(fixture.vault_dir)
    result = evaluate_sustained_error_gate(windows)
    return {
        "gate_passed": result.passed,
        "message": result.message,
        "module_error_rates": result.module_breakdown,
    }
