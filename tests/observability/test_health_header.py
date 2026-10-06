"""FR-013: one-line cycle-health header (spec 048 v1.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline.cycle_summary import health_header, write_summary


def test_health_header_exact_format() -> None:
    line = health_header(
        2,
        exit_code=0,
        notes_drafted=41,
        verifier_passed=38,
        spent=1.21,
        budget=1.50,
        elapsed_s=3840,
        errors=0,
        warnings=1,
    )
    assert (
        line
        == "CYCLE 2: WARN | 41 notes drafted, 38 verifier-passed | $1.21 spent, $1.50 budget | 1h 04m elapsed | 0 errors, 1 warnings"
    )


@pytest.mark.parametrize(
    ("exit_code", "gate_fail", "errors", "warnings", "expected"),
    [
        (2, False, 0, 0, "FAIL"),
        (0, True, 0, 0, "FAIL"),
        (1, False, 1, 0, "FAIL"),
        (0, False, 0, 3, "WARN"),
        (1, False, 0, 2, "WARN"),
        (0, False, 0, 0, "PASS"),
        (1, False, 0, 0, "PASS"),
    ],
)
def test_health_header_status_derivation(
    exit_code: int,
    gate_fail: bool,
    errors: int,
    warnings: int,
    expected: str,
) -> None:
    line = health_header(
        1,
        exit_code=exit_code,
        notes_drafted=5,
        verifier_passed=5,
        spent=0.0,
        budget=1.0,
        elapsed_s=60,
        errors=errors,
        warnings=warnings,
        gate_fail=gate_fail,
    )
    assert line.startswith(f"CYCLE 1: {expected} |")


def test_health_header_budget_none_renders_na() -> None:
    line = health_header(
        1,
        exit_code=0,
        notes_drafted=1,
        verifier_passed=1,
        spent=0.5,
        budget=None,
        elapsed_s=90,
        errors=0,
        warnings=0,
    )
    assert "$0.50 spent, n/a budget" in line


def test_health_header_missing_fields_render_question_marks() -> None:
    line = health_header(
        1,
        exit_code=0,
        notes_drafted=None,
        verifier_passed=None,
        spent=None,
        budget=None,
        elapsed_s=None,
        errors=None,
        warnings=None,
    )
    assert "? notes drafted, ? verifier-passed" in line
    assert "? elapsed" in line
    assert "? errors, ? warnings" in line


def test_write_summary_prepends_health_header(tmp_path: Path) -> None:
    cycles = tmp_path / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)
    cycle = "001"
    (cycles / f"cycle-{cycle}-research.json").write_text(
        json.dumps(
            {
                "notes_created": ["a", "b"],
                "cumulative_cost_usd": 0.42,
            }
        ),
        encoding="utf-8",
    )
    (cycles / f"cycle-{cycle}-quality-report.json").write_text(
        json.dumps(
            {
                "gates": {
                    "verifier": {"status": "PASS", "gate_id": "verifier"},
                },
                "notes_accepted": 2,
            }
        ),
        encoding="utf-8",
    )
    (cycles / f"cycle-{cycle}-timings.json").write_text(
        json.dumps(
            {
                "started_at": "2026-06-01T10:00:00Z",
                "total_duration_s": 300,
            }
        ),
        encoding="utf-8",
    )

    dest = write_summary(tmp_path, 1, exit_code=0)
    text = dest.read_text(encoding="utf-8")
    first_line = text.splitlines()[0]
    assert first_line.startswith("CYCLE 1: PASS |")
    assert text.splitlines()[1].startswith("# Cycle 1 summary")


def test_write_summary_never_raises_on_partial_inputs(tmp_path: Path) -> None:
    dest = write_summary(tmp_path, 99, exit_code=2)
    assert dest.name == "cycle-099-summary.md"
    first_line = dest.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("CYCLE 99:")
