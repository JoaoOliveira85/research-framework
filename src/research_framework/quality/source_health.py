"""Sustained-error source health gate for the quality harness (spec 038 FR-005)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_DEFAULT_ERROR_RATE_THRESHOLD = 0.5
_MIN_WINDOW_SIZE = 3


@dataclass
class SourceHealthGateResult:
    passed: bool
    message: str
    module_breakdown: dict[str, float] = field(default_factory=dict)


def evaluate_sustained_error_gate(
    module_verdicts: dict[str, list[str]],
    *,
    error_rate_threshold: float = _DEFAULT_ERROR_RATE_THRESHOLD,
    min_window_size: int = _MIN_WINDOW_SIZE,
) -> SourceHealthGateResult:
    """FAIL when any module's rolling ``error`` rate exceeds *error_rate_threshold*."""
    breakdown: dict[str, float] = {}
    failing: list[str] = []

    for module, window in sorted(module_verdicts.items()):
        if len(window) < min_window_size:
            breakdown[module] = 0.0
            continue
        error_count = sum(1 for verdict in window if verdict == "error")
        rate = error_count / len(window)
        breakdown[module] = rate
        if rate > error_rate_threshold:
            failing.append(
                f"{module} ({rate:.0%} error over last {len(window)} cycles)"
            )

    if failing:
        return SourceHealthGateResult(
            passed=False,
            message="sustained source errors: " + "; ".join(failing),
            module_breakdown=breakdown,
        )
    return SourceHealthGateResult(
        passed=True,
        message="source health gate passed",
        module_breakdown=breakdown,
    )


def aggregate_module_cycle_verdicts(
    per_source_windows: list[list[str]],
) -> list[str]:
    """Collapse per-source rolling windows into one module-level cycle window.

    Each source keeps the last N cycle verdicts (oldest→newest). Sources with
    shorter histories are left-padded so index *i* always refers to the same
    cycle slot across sources. A module cycle is ``error`` when **any** source
    reported ``error`` in that slot (fail-closed for the sustained-error gate).
    """
    if not per_source_windows:
        return []
    max_len = max(len(window) for window in per_source_windows)
    if max_len == 0:
        return []
    aggregated: list[str] = []
    for slot in range(max_len):
        slot_verdicts = [
            window[slot - (max_len - len(window))]
            for window in per_source_windows
            if slot >= max_len - len(window)
        ]
        if any(verdict == "error" for verdict in slot_verdicts):
            aggregated.append("error")
        elif slot_verdicts and all(verdict == "empty" for verdict in slot_verdicts):
            aggregated.append("empty")
        else:
            aggregated.append("ok")
    if len(aggregated) > _MIN_WINDOW_SIZE:
        aggregated = aggregated[-_MIN_WINDOW_SIZE:]
    return aggregated


def load_module_verdict_windows(
    vault_dir: Any, modules: list[str] | None = None
) -> dict[str, list[str]]:
    """Build per-module rolling cycle windows from all source watermarks."""
    from pathlib import Path

    from research_framework.pipeline.source_bridge.cache import load_watermarks

    vault_path = Path(vault_dir)
    modules_root = vault_path / "modules"
    if modules is None:
        if not modules_root.is_dir():
            return {}
        module_names = sorted(
            p.name for p in modules_root.iterdir() if (p / "manifest.yaml").is_file()
        )
    else:
        module_names = list(modules)

    out: dict[str, list[str]] = {}
    for module in module_names:
        watermarks = load_watermarks(vault_path, module)
        per_source = [entry.recent_cycle_verdicts for entry in watermarks.values()]
        out[module] = aggregate_module_cycle_verdicts(per_source)
    return out
