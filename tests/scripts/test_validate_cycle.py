"""Tests for scripts/validate_cycle.py — cycle report validation."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "validate_cycle.py"


def run_script(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def _stage_vault(vault_dir: Path, cycle_reports_dir: Path, tmp_path: Path) -> Path:
    """Build a writable vault with _pipeline/spec-parse.json and a cycle report dir."""
    staged = tmp_path / "vault"
    shutil.copytree(vault_dir, staged)
    (staged / "_pipeline" / "cycles").mkdir(parents=True, exist_ok=True)
    return staged


def _put_report(
    staged_vault: Path, source_report: Path, name: str = "cycle-001-scout.json"
) -> Path:
    dest = staged_vault / "_pipeline" / "cycles" / name
    dest.write_text(source_report.read_text(), encoding="utf-8")
    return dest


def test_valid_scout_continues(
    vault_dir: Path, cycle_reports_dir: Path, tmp_path: Path
) -> None:
    staged = _stage_vault(vault_dir, cycle_reports_dir, tmp_path)
    report = _put_report(staged, cycle_reports_dir / "valid-scout.json")
    result = run_script(str(report), "--vault", str(staged))
    assert result.returncode == 0, result.stdout


def test_missing_required_source_aborts(
    vault_dir: Path, cycle_reports_dir: Path, tmp_path: Path
) -> None:
    staged = _stage_vault(vault_dir, cycle_reports_dir, tmp_path)
    report = _put_report(
        staged, cycle_reports_dir / "invalid-scout-missing-dimension.json"
    )
    result = run_script(str(report), "--vault", str(staged))
    assert result.returncode == 2
    assert "external_web" in result.stdout.lower()


def test_condition_b_terminates_with_no_unresolved(
    vault_dir: Path, cycle_reports_dir: Path, tmp_path: Path
) -> None:
    """Research phase with empty new_topics AND no unresolved refs → TERMINATE."""
    staged = _stage_vault(vault_dir, cycle_reports_dir, tmp_path)
    # Override metrics to have zero unresolved references for this test
    (staged / "_pipeline" / "vault-metrics.json").write_text(
        json.dumps(
            {
                "active_notes": 3,
                "unresolved_references": [],
                "unresolved_wikilinks": 0,
            }
        )
    )
    report = _put_report(
        staged,
        cycle_reports_dir / "research-condition-b-terminate.json",
        name="cycle-003-research.json",
    )
    result = run_script(str(report), "--vault", str(staged), "--max-cycles", "5")
    assert result.returncode == 1
    assert "Condition B" in result.stdout


def test_condition_b_override_when_unresolved_exist(
    vault_dir: Path, cycle_reports_dir: Path, tmp_path: Path
) -> None:
    """Research phase with empty new_topics BUT unresolved refs → CONTINUE (override)."""
    staged = _stage_vault(vault_dir, cycle_reports_dir, tmp_path)
    # fixture vault-metrics.json already has one unresolved_reference
    report = _put_report(
        staged,
        cycle_reports_dir / "research-condition-b-terminate.json",
        name="cycle-003-research.json",
    )
    result = run_script(str(report), "--vault", str(staged), "--max-cycles", "5")
    assert result.returncode == 0
    assert "unresolved" in result.stdout.lower()


def test_condition_a_scout_at_max_cycles_still_continues_to_dfs(
    vault_dir: Path, cycle_reports_dir: Path, tmp_path: Path
) -> None:
    """Scout runs before DFS; Condition A must not fire after scout on the last cycle."""
    staged = _stage_vault(vault_dir, cycle_reports_dir, tmp_path)
    report = _put_report(
        staged, cycle_reports_dir / "valid-scout.json", name="cycle-005-scout.json"
    )
    data = json.loads(report.read_text())
    data["cycle"] = 5
    assert data.get("phase") == "scout"
    report.write_text(json.dumps(data))
    result = run_script(str(report), "--vault", str(staged), "--max-cycles", "5")
    assert result.returncode == 0, result.stdout
    assert "Condition A" not in result.stdout


def test_condition_a_research_at_max_cycles_terminates(
    vault_dir: Path, cycle_reports_dir: Path, tmp_path: Path
) -> None:
    staged = _stage_vault(vault_dir, cycle_reports_dir, tmp_path)
    report = _put_report(
        staged,
        cycle_reports_dir / "valid-research.json",
        name="cycle-005-research.json",
    )
    data = json.loads(report.read_text())
    data["cycle"] = 5
    data["phase"] = "research"
    report.write_text(json.dumps(data))
    result = run_script(str(report), "--vault", str(staged), "--max-cycles", "5")
    assert result.returncode == 1
    assert "Condition A" in result.stdout


def test_condition_c_budget_terminates(
    vault_dir: Path, cycle_reports_dir: Path, tmp_path: Path
) -> None:
    staged = _stage_vault(vault_dir, cycle_reports_dir, tmp_path)
    report = _put_report(
        staged,
        cycle_reports_dir / "scout-budget-exceeded.json",
        name="cycle-002-scout.json",
    )
    result = run_script(str(report), "--vault", str(staged), "--budget-cap", "250.0")
    assert result.returncode == 1
    assert "Condition C" in result.stdout


def test_valid_research_continues(
    vault_dir: Path, cycle_reports_dir: Path, tmp_path: Path
) -> None:
    staged = _stage_vault(vault_dir, cycle_reports_dir, tmp_path)
    report = _put_report(
        staged,
        cycle_reports_dir / "valid-research.json",
        name="cycle-001-research.json",
    )
    result = run_script(str(report), "--vault", str(staged), "--max-cycles", "5")
    assert result.returncode == 0


def test_malformed_json_aborts(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not valid json {{{")
    result = run_script(str(bad))
    assert result.returncode == 2


def test_file_not_found_aborts() -> None:
    result = run_script("/tmp/research_framework-nonexistent-cycle.json")
    assert result.returncode == 2


def test_filename_collision_aborts(
    vault_dir: Path, cycle_reports_dir: Path, tmp_path: Path
) -> None:
    staged = _stage_vault(vault_dir, cycle_reports_dir, tmp_path)
    data = json.loads((cycle_reports_dir / "valid-scout.json").read_text())
    # Collide with an existing fixture note
    data["proposed_filenames"] = ["Valid Concept.md"]
    report = staged / "_pipeline" / "cycles" / "cycle-001-scout.json"
    report.write_text(json.dumps(data))
    result = run_script(str(report), "--vault", str(staged))
    assert result.returncode == 2
    assert "collision" in result.stdout.lower()
