"""Cycle quality-report guard and one-shot write on every exit path."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path

from .state import (
    QualityReportState,
    _apply_exit_metadata,
    _cycle_num_from_state,
    _vault_dir_from_state,
)

_LOG = logging.getLogger(__name__)


@contextmanager
def _quality_report_guard(cycle_dir: Path):
    """Write cycle quality report exactly once on every exit path (spec 025 A6)."""
    state = QualityReportState(cycle_dir=cycle_dir)
    try:
        yield state
        if state.exit_status is None:
            state.exit_status = "success"
    except KeyboardInterrupt:
        state.exit_status = "interrupted"
        raise
    except Exception as exc:
        if state.exit_status is None:
            state.exit_status = "failure"
        if state.exception is None:
            state.exception = repr(exc)
        raise
    finally:
        try:
            # Route through cycle_runner so tests can patch a single symbol (A6).
            from research_framework.pipeline import cycle_runner as _cr

            _cr._write_cycle_quality_report(state)
        except Exception as exc:
            _LOG.warning("_quality_report_guard: quality report write failed: %s", exc)


def _write_cycle_quality_report(state: QualityReportState) -> None:
    """Best-effort cycle quality JSON; must not affect exit codes (T049).

    Also flushes the per-cycle timings sidecar if one is active for this
    cycle. Invoked exactly once from ``_quality_report_guard`` on every exit.

    Clears ``state.json::in_progress_cycle`` on every cycle exit (spec 025 A4).
    """
    vault_dir = _vault_dir_from_state(state)
    cycle_num = _cycle_num_from_state(state)
    from research_framework.pipeline import cycle_state as _live_state

    _live_state.write(vault_dir, in_progress_cycle=None)

    report_path: Path | None = None
    try:
        from research_framework.pipeline import quality_report

        report_path = quality_report.write_report(vault_dir, cycle_num)
    except Exception as exc:  # noqa: BLE001 — never mask cycle exit on quality-report failure
        _LOG.warning("quality_report.write_report failed: %s", exc)

    if report_path is not None and report_path.is_file():
        _apply_exit_metadata(report_path, state)

    from research_framework.pipeline import cycle_runner as _cr

    timings = _cr.peek_active_timing(cycle_num)
    if timings is not None:
        flush_code = state.exit_code if state.exit_code is not None else 2
        try:
            timings.flush(exit_code=flush_code)
        except Exception as exc:
            _LOG.warning("_write_cycle_quality_report: timings.flush failed: %s", exc)
        _cr.pop_active_timing(cycle_num)
