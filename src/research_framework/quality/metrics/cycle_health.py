"""Cycle health metric family for the quality harness (spec 022 US2)."""

from __future__ import annotations

from typing import Any

from research_framework.pipeline.steps._types import SafetyGateTrip

from ..models import CycleOutput, Fixture
from ._helpers import UNMEASURED_KEY, load_json, record_ratio, truncate_float


def compute_cycle_health_metric(
    fixture: Fixture, cycle_outputs: list[CycleOutput]
) -> dict[str, Any]:
    """Return cycle pass/fail counts, SG-002 trips, retry and verifier rates."""
    del fixture  # reserved for future fixture-specific health signals
    if not cycle_outputs:
        return {
            "cycles_pass": 0,
            "cycles_fail": 0,
            "sg002_trip_count": 0,
            "retry_once_rate": 0.0,
            "verifier_reject_rate": None,
            UNMEASURED_KEY: {"verifier_reject_rate": "no_cycles_run"},
        }

    cycles_pass = sum(1 for c in cycle_outputs if c.exit_code == 0)
    cycles_fail = len(cycle_outputs) - cycles_pass
    sg002_trip_count = sum(_sg002_trips_for_cycle(c) for c in cycle_outputs)

    total_retries = 0
    total_verifier_invocations = 0
    total_verifier_rejects = 0

    for cycle in cycle_outputs:
        report = load_json(cycle.quality_report_path)
        total_retries += int(report.get("retry_count") or 0)

        typed_research = cycle.research_result
        if typed_research is not None and (
            typed_research.notes_written or typed_research.notes_rejected
        ):
            total_verifier_invocations += len(typed_research.notes_written) + len(
                typed_research.notes_rejected
            )
            total_verifier_rejects += len(typed_research.notes_rejected)
            continue

        verifier_path = cycle.quality_report_path.with_name(
            f"cycle-{cycle.cycle_number:03d}-verifier.json"
        )
        manifest = load_json(verifier_path)
        verdicts = manifest.get("verdicts")
        if isinstance(verdicts, list) and verdicts:
            total_verifier_invocations += len(verdicts)
            total_verifier_rejects += sum(
                1
                for v in verdicts
                if isinstance(v, dict) and v.get("status") == "rejected"
            )
        else:
            written = int(report.get("notes_written") or 0)
            rejected = int(report.get("notes_rejected") or 0)
            if written > 0:
                total_verifier_invocations += written
                total_verifier_rejects += rejected

    n_cycles = len(cycle_outputs)
    out: dict[str, Any] = {
        "cycles_pass": cycles_pass,
        "cycles_fail": cycles_fail,
        "sg002_trip_count": sg002_trip_count,
        "retry_once_rate": truncate_float(total_retries / n_cycles)
        if n_cycles
        else 0.0,
    }
    # A verifier that was never invoked did not reject 0% — it did not run
    # (issue #268). Every cycle of the source-poor fixture aborts at SG-002
    # before the note-writer, so this metric has never measured there.
    record_ratio(
        out,
        "verifier_reject_rate",
        total_verifier_rejects,
        total_verifier_invocations,
        reason="verifier_never_invoked",
    )
    return out


def _sg002_trips_for_cycle(cycle: CycleOutput) -> int:
    if cycle.scout_result is not None and cycle.scout_result.sg_trips:
        return _count_sg002(cycle.scout_result.sg_trips)
    if cycle.sg_trips:
        return sum(1 for trip in cycle.sg_trips if trip == "SG-002")
    return 0


def _count_sg002(trips: list[SafetyGateTrip]) -> int:
    return sum(
        1
        for trip in trips
        if trip.gate_id == "SG-002"
        and str(trip.status or "").upper() in {"FAIL", "WARN"}
    )
