"""spec-019 / 0.2.29 — validate_cycle.py must emit a structured sidecar.

Background:

Pre-0.2.29, the cycle runner only got the validator's exit code (0/1/2)
plus the human-friendly stdout block. When the validator exited 2 on a
scout report with recoverable structural errors (e.g. a missing required
source name in ``sources_consulted``), the runner had no way to feed the
specific errors back to the scout agent as a correction directive — so
the whole cycle aborted on first failure.

0.2.29 (US2 / H2 escalation) drives a correction loop in
``cycle_runner._retry_scout_with_validation_directive``. That loop reads
the validator's errors from a sidecar JSON next to the report. This test
locks in the sidecar contract so the loop can rely on it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent.parent
SCRIPT = REPO / "scripts" / "validate_cycle.py"


def _write_minimal_scout_report(
    tmp_path: Path,
    *,
    sources_consulted: list | dict | None,
    extra_overrides: dict | None = None,
) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    pipeline = vault / "_pipeline"
    cycles = pipeline / "cycles"
    cycles.mkdir(parents=True)

    # Minimal valid v2 *research* report skeleton. Phase deliberately
    # "research" so check_termination_v2 hits both the field check and
    # the sources_consulted check.
    report = {
        "schema_version": "2.0",
        "cycle": 1,
        "phase": "research",
        "timestamp": "2026-05-18T10:00:00Z",
        "topics_from_code": [],
        "intent_from_confluence": [],
        "topics_proposed": [],
        "topics_existing": [],
        "topics_new": [],
        "coverage_status": {},
        "dimensions_covered": [],
        "termination_condition": "C",
        "decision_rationale": "test",
        "budget_consumed_usd": 60.0,
    }
    if sources_consulted is not None:
        report["sources_consulted"] = sources_consulted
    if extra_overrides:
        report.update(extra_overrides)
    report_path = cycles / "cycle-001-research.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    # spec-parse.json drives required-sources enforcement.
    (pipeline / "spec-parse.json").write_text(
        json.dumps(
            {
                "name": "T",
                "data_sources": [
                    {"name": "GitHub repos", "required": True},
                    {"name": "Confluence", "required": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    return vault, report_path


def _run_validator(report_path: Path, vault: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(report_path),
            "--vault",
            str(vault),
            "--max-cycles",
            "5",
            "--budget-cap",
            "50.0",
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _sidecar_for(report_path: Path) -> Path:
    return report_path.with_suffix(report_path.suffix + ".validation.json")


def test_sidecar_is_written_on_abort(tmp_path: Path) -> None:
    """When validate_cycle.py exits 2, it MUST write a sidecar listing every
    structural error.

    Without this, ``cycle_runner._retry_scout_with_validation_directive``
    can't synthesize a correction directive and is forced back into the
    pre-0.2.29 hard-abort path.
    """
    vault, report_path = _write_minimal_scout_report(
        tmp_path,
        sources_consulted=["GitHub repos"],
    )
    result = _run_validator(report_path, vault)
    assert result.returncode == 2, (
        f"expected ABORT (exit 2) on missing required source 'Confluence', "
        f"got {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    sidecar = _sidecar_for(report_path)
    assert sidecar.exists(), (
        f"validator must write {sidecar.name} on exit 2 so the runner can "
        f"feed errors back to the scout"
    )
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["status"] == "ABORT"
    assert isinstance(data.get("errors"), list)
    error_blob = " | ".join(data["errors"]).lower()
    assert "confluence" in error_blob, (
        f"sidecar errors must name the missing source so the directive is "
        f"actionable. got: {data['errors']}"
    )


def test_sidecar_is_written_on_terminate(tmp_path: Path) -> None:
    """The sidecar contract is exit-code-agnostic.

    The runner doesn't currently *use* the sidecar for TERMINATE/CONTINUE
    paths, but the writer should treat the sidecar as a side-channel
    that mirrors the printed result. Locking this in now means we don't
    have to invent a second contract for future consumers (e.g. the
    spec-019 vault blueprint stage).
    """
    vault, report_path = _write_minimal_scout_report(
        tmp_path,
        sources_consulted=["GitHub repos", "Confluence"],
    )
    result = _run_validator(report_path, vault)
    assert result.returncode in (0, 1), (
        f"expected CONTINUE/TERMINATE on a complete report, got "
        f"{result.returncode}\nstdout:\n{result.stdout}"
    )
    sidecar = _sidecar_for(report_path)
    assert sidecar.exists()
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["status"] in ("CONTINUE", "TERMINATE")


def test_sidecar_contains_canonical_fields(tmp_path: Path) -> None:
    """Lock in the sidecar shape the runner relies on."""
    vault, report_path = _write_minimal_scout_report(
        tmp_path,
        sources_consulted=["GitHub repos"],  # triggers ABORT
    )
    _run_validator(report_path, vault)
    data = json.loads(_sidecar_for(report_path).read_text(encoding="utf-8"))
    expected = {"status", "reason", "errors", "warnings", "metrics_delta"}
    missing = expected - set(data.keys())
    assert not missing, (
        f"sidecar missing canonical fields: {missing}. Adding fields is "
        f"safe; removing/renaming breaks the cycle_runner contract."
    )


def test_sidecar_errors_non_empty_iff_abort(tmp_path: Path) -> None:
    """Errors list non-empty ⇔ ABORT.

    The runner gates the correction loop on ``len(errors) > 0``. Empty
    errors on ABORT means we'd loop on no signal; populated errors on a
    non-ABORT exit code means we'd loop spuriously. Verified using the
    canonical passing scout fixture (no errors → status != ABORT) and
    the minimal one we construct here that's missing a required source.
    """
    vault, report_path = _write_minimal_scout_report(
        tmp_path,
        sources_consulted=["GitHub repos"],  # missing Confluence
    )
    _run_validator(report_path, vault)
    data = json.loads(_sidecar_for(report_path).read_text(encoding="utf-8"))
    assert data["status"] == "ABORT"
    assert data["errors"], "ABORT result must have at least one error"

    # Positive case: copy the canonical valid-scout-v2 fixture and point
    # the validator at it. We don't try to construct a passing report
    # from scratch — the v2 schema has enough surface area that the
    # fixture is the documented contract.
    fixture = (
        REPO / "tests" / "fixtures" / "cycle-reports" / "v2" / "valid-scout-v2.json"
    )
    pos_vault = tmp_path / "pos-vault"
    pos_cycles = pos_vault / "_pipeline" / "cycles"
    pos_cycles.mkdir(parents=True)
    pos_report = pos_cycles / "cycle-001-scout.json"
    pos_report.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    (pos_vault / "_pipeline" / "spec-parse.json").write_text(
        json.dumps(
            {
                "name": "T",
                "data_sources": [
                    {"name": "GitHub repos", "required": True},
                    {"name": "Confluence", "required": True},
                ],
            }
        ),
        encoding="utf-8",
    )
    pos_result = _run_validator(pos_report, pos_vault)
    pos_data = json.loads(_sidecar_for(pos_report).read_text(encoding="utf-8"))
    assert pos_data["status"] != "ABORT", (
        f"valid-scout-v2 fixture should not ABORT; sidecar=\n"
        f"{json.dumps(pos_data, indent=2)}\nstderr:\n{pos_result.stderr}"
    )
    assert pos_data["errors"] == []
