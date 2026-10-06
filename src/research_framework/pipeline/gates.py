"""Gate framework for the research_framework pipeline (feature 017, E-004).

Every step gate (SG-001..SG-005, between scout and note-writer) and every
cycle gate (CG-001..CG-007, between cycles) returns a `GateResult`. The
orchestrator inspects the status to decide whether to continue, retry
(incremental — accepted batches preserved per Q3), or abort.

Design notes per `data-model.md` E-004 and the constitution:

- Gates are pure functions. They MUST NOT call agents, MUST NOT mutate
  filesystem state, and MUST NOT swallow exceptions silently — bubbled
  exceptions become FAIL via :func:`run_gate`.
- ``status == "FAIL"`` MUST carry a non-empty ``correction_hint`` so the
  orchestrator can build a `CorrectionDirective` without re-reading the
  failure context.
- ``status == "NA"`` is the structurally-inapplicable signal (e.g. SG-003
  when ``forbidden_filename_prefixes`` is empty, R-007). Distinct from
  WARN so vault_audit.py can render "gate inactive by design" rather than
  "you did something wrong."
- The on-disk JSON shape lives in
  ``contracts/cycle-quality-report.schema.json#/$defs/gate_result``;
  :meth:`GateResult.to_dict` produces output that conforms to it.
"""

from __future__ import annotations

import re
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

GateStatus = Literal["PASS", "WARN", "FAIL", "NA"]
"""All four gate outcomes. ``NA`` distinguishes "gate inactive by design"
from WARN; see SG-003 / CG-003 abstraction-gate behaviour when the spec
declares no ``forbidden_filename_prefixes`` (R-007)."""

_GATE_ID_PATTERN = re.compile(r"^[CS]G-\d{3}$")
"""Match ``CG-001``..``CG-999`` and ``SG-001``..``SG-999``. Three-digit
zero-padded suffix matches ``contracts/cycle-quality-report.schema.json``."""


@dataclass
class GateResult:
    """Common return type for every step and cycle gate.

    Carries enough information for (a) the orchestrator to decide control
    flow, (b) the cycle quality report to render a row, and (c) the
    correction-directive builder to construct a remediation prompt without
    re-reading the failure context.

    Invariants enforced in :meth:`__post_init__`:

    - ``gate_id`` matches ``^[CS]G-\\d{3}$``.
    - ``status`` is one of PASS / WARN / FAIL / NA.
    - ``status == "FAIL"`` requires non-empty ``correction_hint``.

    The dataclass is conceptually immutable; callers create a new instance
    rather than mutating one in place.
    """

    gate_id: str
    status: GateStatus
    metric_name: str
    metric_value: float | int | str | bool
    threshold: float | int | str | None
    message: str
    correction_hint: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.gate_id, str) or not _GATE_ID_PATTERN.match(
            self.gate_id
        ):
            raise ValueError(
                f"GateResult.gate_id={self.gate_id!r} must match "
                f"{_GATE_ID_PATTERN.pattern!r} (e.g. 'CG-001', 'SG-005')"
            )
        if self.status not in ("PASS", "WARN", "FAIL", "NA"):
            raise ValueError(
                f"GateResult.status={self.status!r} must be one of "
                "PASS / WARN / FAIL / NA"
            )
        if self.status == "FAIL" and not self.correction_hint:
            raise ValueError(
                f"GateResult({self.gate_id}).correction_hint MUST be non-empty "
                "when status=FAIL — the orchestrator needs it to build a "
                "correction directive without re-reading failure context"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the on-disk JSON shape.

        Mirrors ``contracts/cycle-quality-report.schema.json#/$defs/gate_result``
        — required keys always present, optional keys (``threshold``,
        ``correction_hint``) included with their actual value (None for
        threshold; empty string for correction_hint when not FAIL).
        """
        return {
            "gate_id": self.gate_id,
            "status": self.status,
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "message": self.message,
            "correction_hint": self.correction_hint,
        }


def run_gate(
    gate_callable: Callable[..., GateResult], *args: Any, **kwargs: Any
) -> GateResult:
    """Execute ``gate_callable(*args, **kwargs)`` and return its `GateResult`.

    On exception, returns a synthetic FAIL with a diagnostic
    ``correction_hint`` of the form ``"<ExceptionClass>: <message>"`` plus
    the first traceback line so the orchestrator can decide whether to
    retry without losing the original signal. Exceptions are NEVER
    swallowed silently — letting a gate crash with no record would let
    drift compound exactly the way the trial run failed.

    The synthetic FAIL uses ``gate_id`` derived from the callable's name
    when it follows the ``[CS]G_NNN_*`` convention; otherwise falls back
    to ``CG-000`` (the orchestrator-side wrapper that can't recover the
    real ID at this layer).
    """
    try:
        return gate_callable(*args, **kwargs)
    except Exception as exc:
        gate_id = _infer_gate_id(gate_callable)
        # First non-empty traceback line gives the failure site without
        # blowing up the report file with a full stack.
        tb_lines = [
            line.strip() for line in traceback.format_exc().splitlines() if line.strip()
        ]
        site = tb_lines[-2] if len(tb_lines) >= 2 else ""
        hint = f"{type(exc).__name__}: {exc}"
        if site:
            hint = f"{hint} (at {site})"
        return GateResult(
            gate_id=gate_id,
            status="FAIL",
            metric_name="gate_runner_exception",
            metric_value=type(exc).__name__,
            threshold=None,
            message=f"gate {gate_callable.__name__} raised {type(exc).__name__}",
            correction_hint=hint,
        )


def _infer_gate_id(callable_obj: Callable[..., Any]) -> str:
    """Best-effort gate-id extraction from a callable's name.

    Convention: gates are named like ``CG001_min_cycle_yield`` or
    ``SG003_topic_abstraction_check``. We pull out the leading ``[CS]G``
    plus three digits and reformat to the ``CG-NNN`` shape required by
    the contract. Fallback ``CG-000`` is reserved for orchestrator-side
    failures where no real gate produced the result.
    """
    name = getattr(callable_obj, "__name__", "")
    m = re.match(r"^([CS]G)(\d{3})", name)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return "CG-000"
