"""Issue #269 — an operator must be able to tell a gate-abort from a crash.

When SG-002 aborted a cycle the whole record of it was one INFO log line: the
timings sidecar stopped at "Step 0", the scout stage was never opened, and the
quality report said the gate was "not recorded". This pins the three surfaces
that now carry the answer.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from research_framework.pipeline.cycle_runner import run_cycle_steps
from tests.pipeline.steps.test_scout import _minimal_spec
from tests.pipeline.test_cycle_runner import (
    _make_vault,
    _patch_cycle_runner_subprocess,
)

_SINGLE_CATEGORY_SCOUT = {
    "topics_found": {
        "new": [
            {"title": "Alpha", "coverage_category": "services"},
            {"title": "Beta", "coverage_category": "services"},
        ],
        "existing": [],
        "total": 2,
    }
}


def _run_cycle_aborted_by_sg002(tmp_path: Path, monkeypatch) -> Path:
    """Drive a real cycle whose scout topics all share one category."""
    from research_framework.pipeline._helpers import source_signals as ss

    monkeypatch.setattr(
        ss, "_load_spec_for_scout_gates", lambda _vault: _minimal_spec()
    )
    monkeypatch.setattr(ss, "_unfilled_categories_for_gates", lambda _vault: 5)
    monkeypatch.setattr(ss, "_cycle_quota_for_gates", lambda _pipeline: 1)

    vault = _make_vault(tmp_path)
    cycles = vault / "_pipeline" / "cycles"
    (vault / "_pipeline" / "vault-metrics.json").write_text("{}", encoding="utf-8")
    (cycles / "cycle-001-scout.json").write_text(
        json.dumps(_SINGLE_CATEGORY_SCOUT), encoding="utf-8"
    )

    def _fake_run(cmd, **kwargs):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = b""
        return mock

    with _patch_cycle_runner_subprocess(_fake_run):
        rc = run_cycle_steps(vault, 1)

    assert rc == 2, "SG-002 FAIL aborts the cycle"
    return vault


def test_timings_name_the_scout_stage_on_a_gate_abort(
    tmp_path: Path, monkeypatch
) -> None:
    vault = _run_cycle_aborted_by_sg002(tmp_path, monkeypatch)

    timings = json.loads(
        (vault / "_pipeline" / "cycles" / "cycle-001-timings.json").read_text(
            encoding="utf-8"
        )
    )
    stages = [s["stage"] for s in timings["stages"]]

    assert timings["exit_code"] == 2
    assert any("scout" in s for s in stages), (
        f"a cycle that reached the scout must record the stage; got {stages}"
    )


def test_the_quality_report_names_the_gate_that_aborted_the_cycle(
    tmp_path: Path, monkeypatch
) -> None:
    vault = _run_cycle_aborted_by_sg002(tmp_path, monkeypatch)

    report = json.loads(
        (vault / "_pipeline" / "cycles" / "cycle-001-quality-report.json").read_text(
            encoding="utf-8"
        )
    )

    assert report["gates"]["SG-002"]["status"] == "FAIL"
    assert report["gates"]["SG-001"]["status"] == "PASS"
