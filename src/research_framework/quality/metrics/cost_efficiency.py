"""Cost-efficiency metric family (spec 033 US3/US4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from research_framework.pipeline.budget_guard import list_sidecars_v11
from research_framework.quality.baseline import REGRESSION_FAIL_PCT
from research_framework.quality.models import CycleOutput, Fixture


def _note_paths(out: CycleOutput) -> set[Path]:
    """Every note *out* wrote, resolved, each named once.

    ``CycleOutput.notes_written`` and ``research_result.notes_written`` are the
    SAME list on every output the harness builds — ``runner._invoke_cycles``
    derives the former from the latter. Summing both lengths counted each note
    twice and halved ``cost_per_substantive_note`` (issue #294). A union by
    resolved path is correct under both shapes: the runner's (both fields
    populated, aliased) and a hand-built one (only ``notes_written``).
    """
    paths = set(out.notes_written)
    if out.research_result is not None:
        paths.update(out.research_result.notes_written or [])
    return {p.resolve() for p in paths}


def _substantive_note_count(cycle_outputs: list[CycleOutput]) -> int:
    """Distinct notes written across *cycle_outputs* (floor 1, it is a divisor)."""
    seen: set[Path] = set()
    for out in cycle_outputs:
        seen |= _note_paths(out)
    return max(len(seen), 1)


def compute_cost_per_substantive_note(
    fixture: Fixture, cycle_outputs: list[CycleOutput]
) -> dict[str, Any]:
    """FR-009: sidecar v1.1 cost sum ÷ substantive notes added."""
    vault_dir = fixture.vault_dir
    cost_sum = 0.0
    for out in cycle_outputs:
        cost_sum += sum(
            float(r.get("cost_usd") or 0.0)
            for r in list_sidecars_v11(vault_dir, out.cycle_number)
        )
    notes = _substantive_note_count(cycle_outputs)
    value = round(cost_sum / notes, 4) if notes else 0.0
    return {
        "cost_per_substantive_note": value,
        "cost_sum_usd": cost_sum,
        "substantive_notes": notes,
    }


def cost_per_substantive_note_regression_verdict(
    baseline: float, current: float
) -> str:
    """Moderate gate: >15% increase vs baseline → fail."""
    if baseline <= 0:
        return "pass"
    delta_pct = ((current - baseline) / baseline) * 100.0
    if delta_pct > REGRESSION_FAIL_PCT:
        return "fail"
    return "pass"


def compute_source_cache_hit_ratio(
    fixture: Fixture, cycle_outputs: list[CycleOutput]
) -> dict[str, Any]:
    """FR-010: cache-hit ratio when spec 020 metadata exists."""
    _ = cycle_outputs
    sources_root = fixture.vault_dir / "_pipeline" / "sources"
    if not sources_root.is_dir():
        return {"status": "na", "reason": "020_not_present"}
    hits = 0
    misses = 0
    for path in sources_root.rglob("*.json"):
        try:
            import json

            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            hits += int(data.get("cache_hits") or 0)
            misses += int(data.get("cache_misses") or 0)
    if hits + misses == 0:
        return {"status": "na", "reason": "020_not_present"}
    ratio = hits / (hits + misses)
    rounded = round(ratio, 4)
    out: dict[str, Any] = {
        "status": "ok",
        "source_cache_hit_ratio": rounded,
        "cache_hit_ratio": rounded,
        "cache_hits": hits,
        "cache_misses": misses,
    }
    if ratio < 0.80:
        out["warning"] = "cache_hit_ratio_below_80_percent"
    return out
