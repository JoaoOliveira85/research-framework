"""FR1 (spec 051) yield diagnostic + calibration sidecar — T013/T014.

Covers the two additive pieces wired into ``quality_report.py``:
- ``_append_yield_calibration`` → ``_pipeline/yield-calibration.json`` (T014),
  schema ``contracts/yield-calibration.schema.json``.
- ``CycleQualityReport.cg001_yield`` serialization in ``to_dict`` (T013).

The full ``write_report`` integration (which populates both) is exercised on
real fixtures by ``./build.sh --quality`` (T016).
"""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.pipeline.coverage import compute_yield_target
from research_framework.pipeline.quality_report import (
    CycleQualityReport,
    _append_yield_calibration,
)

_SCHEMA = json.loads(
    Path(
        "specs/051-post-revival-hardening/contracts/yield-calibration.schema.json"
    ).read_text(encoding="utf-8")
)
_REQUIRED = set(_SCHEMA["items"]["required"])
_ALLOWED = set(_SCHEMA["items"]["properties"])


def _seed_targets(vault: Path, target: int, met: int) -> None:
    (vault / "_pipeline").mkdir(parents=True, exist_ok=True)
    (vault / "_pipeline" / "coverage-targets.json").write_text(
        json.dumps(
            {
                "categories": [
                    {
                        "name": "c",
                        "note_type": "concept",
                        "target_count": target,
                        "met_count": met,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_sidecar_appends_schema_exact_records(tmp_path: Path) -> None:
    _seed_targets(tmp_path, target=100, met=0)
    yt = compute_yield_target(tmp_path, 1, 20)
    _append_yield_calibration(tmp_path, 1, yt, actual=12, exit_status="WARN")
    _append_yield_calibration(tmp_path, 2, yt, actual=50, exit_status="PASS")
    arr = json.loads(
        (tmp_path / "_pipeline" / "yield-calibration.json").read_text(encoding="utf-8")
    )
    assert isinstance(arr, list) and len(arr) == 2
    assert [e["cycle"] for e in arr] == [1, 2]  # sorted by cycle
    for e in arr:
        assert set(e) == _REQUIRED == _ALLOWED  # exact key set, no extras
        assert e["schema_version"] == "1.0"
        assert e["exit_status"] in {"PASS", "WARN", "FAIL"}


def test_sidecar_is_idempotent_per_cycle(tmp_path: Path) -> None:
    _seed_targets(tmp_path, target=100, met=0)
    yt = compute_yield_target(tmp_path, 1, 20)
    _append_yield_calibration(tmp_path, 1, yt, actual=12, exit_status="WARN")
    # Re-running write_report for the same cycle replaces, never duplicates.
    _append_yield_calibration(tmp_path, 1, yt, actual=99, exit_status="PASS")
    arr = json.loads(
        (tmp_path / "_pipeline" / "yield-calibration.json").read_text(encoding="utf-8")
    )
    assert len(arr) == 1
    assert arr[0]["actual"] == 99 and arr[0]["exit_status"] == "PASS"


def test_sidecar_tolerates_corrupt_existing_file(tmp_path: Path) -> None:
    (tmp_path / "_pipeline").mkdir(parents=True, exist_ok=True)
    (tmp_path / "_pipeline" / "yield-calibration.json").write_text(
        "{not json", encoding="utf-8"
    )
    _seed_targets(tmp_path, target=100, met=0)
    yt = compute_yield_target(tmp_path, 1, 20)
    _append_yield_calibration(tmp_path, 1, yt, actual=5, exit_status="WARN")
    arr = json.loads(
        (tmp_path / "_pipeline" / "yield-calibration.json").read_text(encoding="utf-8")
    )
    assert len(arr) == 1 and arr[0]["cycle"] == 1


def _minimal_report(**overrides: object) -> CycleQualityReport:
    base = dict(
        cycle_number=1,
        framework_version="0.7.1",
        generated_at="2026-06-02T12:00:00Z",
        cycle_started_at="2026-06-02T11:00:00Z",
        cycle_finished_at="2026-06-02T12:00:00Z",
        gates={},
        coverage_snapshot={},
        notes_written=0,
        notes_accepted=0,
        notes_rejected=0,
        batches=[],
        queryability_score=0,
        queryability_trajectory="stable",
        degraded_sources=[],
        retry_count=0,
        aborted=False,
        abort_reason="",
    )
    base.update(overrides)
    return CycleQualityReport(**base)  # type: ignore[arg-type]


def test_report_to_dict_includes_cg001_yield_when_present() -> None:
    diag = {
        "target": 50,
        "base": 5,
        "cadence_bucket": "monthly",
        "cadence_factor": 8.0,
        "coverage_bucket": "coverage_below_50pct",
        "coverage_factor": 1.5,
        "actual": 12,
        "exit_status": "WARN",
    }
    d = _minimal_report(cg001_yield=diag).to_dict()
    assert d["cg001_yield"] == diag


def test_report_to_dict_omits_cg001_yield_when_none() -> None:
    d = _minimal_report().to_dict()
    assert "cg001_yield" not in d
