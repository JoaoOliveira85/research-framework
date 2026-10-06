"""Per-cycle step-gate record (issue #269).

Scout evaluates SG-001..003 and aborts the cycle on FAIL, before any batch
report exists. This record is the only account of what the gate decided, so it
has to survive that abort and round-trip losslessly.
"""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.pipeline.gates import GateResult
from research_framework.pipeline.step_gate_log import (
    read_step_gates,
    record_step_gates,
    step_gate_log_path,
)


def _gate(gate_id: str, status: str, *, message: str = "m") -> GateResult:
    return GateResult(
        gate_id=gate_id,
        status=status,  # type: ignore[arg-type]
        metric_name="distinct_coverage_categories",
        metric_value=1,
        threshold=5,
        message=message,
        correction_hint="fix it" if status == "FAIL" else "",
    )


def test_read_returns_empty_when_nothing_recorded(tmp_path: Path) -> None:
    assert read_step_gates(tmp_path, 1) == []


def test_round_trips_a_recorded_verdict(tmp_path: Path) -> None:
    record_step_gates(tmp_path, 1, [_gate("SG-002", "FAIL", message="only 1 category")])

    gates = read_step_gates(tmp_path, 1)

    assert [g.gate_id for g in gates] == ["SG-002"]
    assert gates[0].status == "FAIL"
    assert gates[0].message == "only 1 category"
    assert gates[0].correction_hint == "fix it"


def test_records_accumulate_and_are_ordered_by_gate_id(tmp_path: Path) -> None:
    record_step_gates(tmp_path, 1, [_gate("SG-002", "FAIL")])
    record_step_gates(tmp_path, 1, [_gate("SG-001", "PASS")])

    assert [g.gate_id for g in read_step_gates(tmp_path, 1)] == ["SG-001", "SG-002"]


def test_a_later_verdict_replaces_the_earlier_one_for_the_same_gate(
    tmp_path: Path,
) -> None:
    """The scout re-runs the gates after an SG-003 correction retry."""
    record_step_gates(tmp_path, 1, [_gate("SG-003", "FAIL")])
    record_step_gates(tmp_path, 1, [_gate("SG-003", "PASS")])

    gates = read_step_gates(tmp_path, 1)

    assert [(g.gate_id, g.status) for g in gates] == [("SG-003", "PASS")]


def test_records_are_per_cycle(tmp_path: Path) -> None:
    record_step_gates(tmp_path, 1, [_gate("SG-002", "FAIL")])

    assert read_step_gates(tmp_path, 2) == []
    assert step_gate_log_path(tmp_path, 2).name == "cycle-002-step-gates.json"


def test_unreadable_record_is_not_fatal(tmp_path: Path) -> None:
    step_gate_log_path(tmp_path, 1).write_text("{not json", encoding="utf-8")

    assert read_step_gates(tmp_path, 1) == []


def test_malformed_rows_are_skipped_not_raised(tmp_path: Path) -> None:
    step_gate_log_path(tmp_path, 1).write_text(
        json.dumps(
            [
                {"gate_id": "not-a-gate-id", "status": "FAIL"},
                {"no_gate_id": True},
                _gate("SG-001", "PASS").to_dict(),
            ]
        ),
        encoding="utf-8",
    )

    assert [g.gate_id for g in read_step_gates(tmp_path, 1)] == ["SG-001"]
