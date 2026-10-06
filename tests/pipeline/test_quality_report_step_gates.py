"""Issue #269 — a cycle a step gate aborted must record that gate, not ``NA``.

SG-001..003 are evaluated by the scout step. Batch reports only ever carry
SG-004/SG-005 (``steps/research.py``), so ``_merge_sg_gates`` had no source for
the step gates at all and recorded every one of them as
``NA`` / ``step_gate_not_recorded``. On a cycle a step gate ABORTED there is no
batch report either — so the gate that stopped the cycle was the one reported
as "not recorded", which is the reading an operator most needs.
"""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.pipeline.gates import GateResult
from research_framework.pipeline.quality_report import _merge_sg_gates
from research_framework.pipeline.step_gate_log import record_step_gates


def _cycles_dir(vault: Path) -> Path:
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True, exist_ok=True)
    return cycles


def _sg002_fail() -> GateResult:
    return GateResult(
        gate_id="SG-002",
        status="FAIL",
        metric_name="distinct_coverage_categories",
        metric_value=1,
        threshold=5,
        message="only 1 distinct coverage_category value(s); need at least 5",
        correction_hint="propose topics across multiple coverage gaps",
    )


def test_the_gate_that_aborted_the_cycle_is_recorded_with_its_verdict(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    cycles = _cycles_dir(vault)
    record_step_gates(cycles, 1, [_sg002_fail()])

    gates, batches, *_rest = _merge_sg_gates(vault, 1)

    assert batches == [], "an aborted cycle wrote no batch report"
    assert gates["SG-002"].status == "FAIL"
    assert gates["SG-002"].metric_name == "distinct_coverage_categories"
    assert "need at least 5" in gates["SG-002"].message


def test_a_gate_the_abort_pre_empted_stays_na_with_an_honest_reason(
    tmp_path: Path,
) -> None:
    """SG-003 never ran — say that, do not invent a verdict."""
    vault = tmp_path / "vault"
    record_step_gates(_cycles_dir(vault), 1, [_sg002_fail()])

    gates, *_rest = _merge_sg_gates(vault, 1)

    assert gates["SG-003"].status == "NA"
    assert gates["SG-003"].metric_name == "step_gate_not_recorded"


def test_no_record_at_all_still_reports_na(tmp_path: Path) -> None:
    """A cycle that never reached the gates (crash at Step 0) is unchanged."""
    vault = tmp_path / "vault"
    _cycles_dir(vault)

    gates, *_rest = _merge_sg_gates(vault, 1)

    assert {gates[g].status for g in ("SG-001", "SG-002", "SG-003")} == {"NA"}


def test_a_batch_payload_still_wins_over_the_step_record(tmp_path: Path) -> None:
    """Precedence is unchanged: a batch that carries the gate is authoritative."""
    vault = tmp_path / "vault"
    cycles = _cycles_dir(vault)
    record_step_gates(cycles, 1, [_sg002_fail()])
    (cycles / "cycle-001-batch-001.json").write_text(
        json.dumps(
            {
                "batch_number": 1,
                "accepted": True,
                "notes_written": [],
                "topics": [],
                "sg_gate_results": [
                    {
                        "gate_id": "SG-002",
                        "status": "PASS",
                        "metric_name": "distinct_coverage_categories",
                        "metric_value": 5,
                        "threshold": 5,
                        "message": "re-evaluated after correction",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    gates, *_rest = _merge_sg_gates(vault, 1)

    assert gates["SG-002"].status == "PASS"
