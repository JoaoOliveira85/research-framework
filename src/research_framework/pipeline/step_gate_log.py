"""Per-cycle record of the scout step's gate verdicts (SG-001..SG-003).

The scout step evaluates SG-001..SG-003 and, on FAIL, aborts the cycle before
any note-writer batch exists. Batch reports only ever carry SG-004/SG-005
(``steps/research.py``), so ``quality_report`` had no source for the step gates
at all: it recorded every one of them as ``NA`` / ``step_gate_not_recorded`` —
including the gate that had just stopped the cycle, which is the one reading an
operator most needs (issue #269). Their only trace was an INFO log line.

This module is that missing account. The scout writes each verdict here as it
is evaluated, so the record survives the abort that follows; the quality report
reads it back. The on-disk shape is a JSON list of
:meth:`~research_framework.pipeline.gates.GateResult.to_dict` payloads — the
same shape as ``sg_gate_results`` inside a batch report, so one reader parses
both.

Every function here is best-effort: a cycle must never fail because its
telemetry could not be written.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path

from .atomic_write import write_json
from .gates import GateResult

_LOG = logging.getLogger(__name__)

__all__ = ["read_step_gates", "record_step_gates", "step_gate_log_path"]


def step_gate_log_path(cycles_dir: Path, cycle_num: int) -> Path:
    """Path of the step-gate record for *cycle_num*."""
    return cycles_dir / f"cycle-{cycle_num:03d}-step-gates.json"


def record_step_gates(
    cycles_dir: Path, cycle_num: int, results: Iterable[GateResult]
) -> None:
    """Merge *results* into the cycle's step-gate record.

    A gate can be evaluated twice in one cycle (the scout re-runs SG-001..003
    after an SG-003 correction retry). The later verdict is the cycle's answer,
    so it replaces the earlier one for that ``gate_id``.
    """
    merged = {gate.gate_id: gate for gate in read_step_gates(cycles_dir, cycle_num)}
    for gate in results:
        merged[gate.gate_id] = gate
    payload = [merged[gid].to_dict() for gid in sorted(merged)]
    try:
        write_json(step_gate_log_path(cycles_dir, cycle_num), payload)
    except OSError as exc:  # pragma: no cover - telemetry must not fail a cycle
        _LOG.warning("step-gate record write failed: %s", exc)


def read_step_gates(cycles_dir: Path, cycle_num: int) -> list[GateResult]:
    """Return the recorded step gates for *cycle_num*, ordered by gate id."""
    path = step_gate_log_path(cycles_dir, cycle_num)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    gates: list[GateResult] = []
    for item in raw:
        gate = _gate_from_dict(item)
        if gate is not None:
            gates.append(gate)
    return sorted(gates, key=lambda g: g.gate_id)


def _gate_from_dict(item: object) -> GateResult | None:
    if not isinstance(item, dict) or not item.get("gate_id"):
        return None
    try:
        return GateResult(
            gate_id=str(item["gate_id"]),
            status=item["status"],
            metric_name=str(item.get("metric_name") or ""),
            metric_value=item.get("metric_value", 0),
            threshold=item.get("threshold"),
            message=str(item.get("message") or ""),
            correction_hint=str(item.get("correction_hint") or ""),
        )
    except (KeyError, TypeError, ValueError):
        return None
