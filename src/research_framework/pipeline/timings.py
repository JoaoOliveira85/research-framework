"""Per-cycle stage timing capture.

Lightweight instrumentation for ``cycle_runner.run_cycle_steps``. Each stage
opens with a ``timer.lap("Step N - …")`` call that:

1. Prints the existing human-readable header (``"\\n[Step N] …"``).
2. Closes the previous lap, records its duration to the in-memory list.
3. Starts a new lap clock.

When the cycle finishes (success or abort), ``timer.flush(exit_code=...)``
writes ``_pipeline/cycles/cycle-NNN-timings.json`` with the per-stage
durations + the cycle's total wall time. The sidecar is the input to
:mod:`research_framework.pipeline.run_report`, which aggregates timings + cost
sidecars into the end-of-pipeline ``_pipeline/run-report.md``.

The class is intentionally **best-effort**: it never raises. A measurement
glitch must not crash a cycle — we'd rather lose a row than abort because
the stopwatch tripped.

Why this exists: the v0.2.19 pipeline printed step headers but offered no
way to answer "which step is eating my budget?" or "how long does cycle 5
actually take?" without grepping log timestamps by eye. The sidecar +
report close that loop without adding any runtime dependency.
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = ["CycleTimings"]

_LOG = logging.getLogger(__name__)


@dataclass
class _Lap:
    """One stage's timing record.

    ``duration_s`` is left at ``None`` while the lap is still running so the
    in-memory list always reflects what's been *measured*, not what's been
    *started*. ``CycleTimings._close_current`` is the only place that
    transitions ``None → float``.
    """

    stage: str
    started_at: str
    started_mono: float
    duration_s: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "started_at": self.started_at,
            "duration_s": self.duration_s,
        }


@dataclass
class CycleTimings:
    """Stopwatch for one research cycle.

    Construct at the top of ``run_cycle_steps``. Call :meth:`lap` at the
    start of each step (it closes the previous lap and starts a new one).
    Call :meth:`flush` exactly once at the end of the cycle to persist the
    sidecar. ``flush`` is idempotent — calling it twice rewrites the file
    with the latest ``exit_code``; this is how abort paths can flush at
    ``rc=2`` and the success path can then overwrite with the real return
    code without coordination.
    """

    cycle_num: int
    pipeline_dir: Path
    cycle_started_at: str = field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    _t0_mono: float = field(default_factory=time.monotonic)
    _laps: list[_Lap] = field(default_factory=list)
    _current: _Lap | None = None

    @property
    def cycle_3(self) -> str:
        return f"{self.cycle_num:03d}"

    @property
    def sidecar_path(self) -> Path:
        return self.pipeline_dir / "cycles" / f"cycle-{self.cycle_3}-timings.json"

    def _close_current(self) -> None:
        if self._current is None:
            return
        self._current.duration_s = round(
            time.monotonic() - self._current.started_mono, 3
        )
        self._laps.append(self._current)
        self._current = None

    def lap(self, stage: str, *, header: str | None = None) -> None:
        """Close the active stage (if any) and open ``stage``.

        ``header`` overrides the printed banner; pass ``None`` to print the
        default ``"\\n[<stage>]"`` form. Pass ``""`` to suppress the print
        entirely (useful for sub-steps that don't deserve their own header).
        """
        self._close_current()
        try:
            now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            self._current = _Lap(
                stage=stage, started_at=now_iso, started_mono=time.monotonic()
            )
            banner = f"\n[{stage}]" if header is None else header
            if banner:
                # Always flush — the cycle log is a tee'd terminal; users
                # rely on stage headers landing in order with subprocess
                # output that follows.
                print(banner, flush=True)  # noqa: T201 — keep raw print: final report stdout contract
                sys.stdout.flush()
        except Exception as exc:
            _LOG.warning("timings.lap(%r) failed: %s", stage, exc)

    def flush(self, *, exit_code: int) -> Path:
        """Persist the sidecar with the per-stage list + cycle total.

        Safe to call multiple times — each call rewrites the file. Best
        effort: any I/O error is logged and swallowed so the cycle's
        actual exit code is preserved.
        """
        try:
            self._close_current()
            total = round(time.monotonic() - self._t0_mono, 3)
            payload: dict[str, Any] = {
                "schema_version": "1",
                "cycle": self.cycle_num,
                "started_at": self.cycle_started_at,
                "total_duration_s": total,
                "exit_code": exit_code,
                "stages": [lap.to_dict() for lap in self._laps],
            }
            from .atomic_write import write_json as _write_json

            _write_json(self.sidecar_path, payload)
        except Exception as exc:
            _LOG.warning("timings.flush(cycle=%d) failed: %s", self.cycle_num, exc)
        return self.sidecar_path
