"""Research-phase v2 reports must not be held to scout-only required fields.

Background: v0.2.19 cycle 6 aborted because ``scripts/validate_cycle.py``
demanded ``topics_from_code`` / ``intent_from_confluence`` /
``dimensions_covered`` from the DFS research report. Those fields are
*produced* by the scout and *consumed* by the research stage — the writer
agent (correctly) omits them, which then crashed the cycle.

After the fix, ``REQUIRED_REPORT_FIELDS_V2_RESEARCH`` is the strict subset
applied to research-phase reports.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "validate_cycle.py"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True
    )


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "_pipeline" / "cycles").mkdir(parents=True)
    (vault / "data_vault").mkdir()
    (vault / "_pipeline" / "spec-parse.json").write_text(
        json.dumps({"name": "v", "data_sources": []})
    )
    return vault


def _write(report: dict, vault: Path, name: str) -> Path:
    path = vault / "_pipeline" / "cycles" / name
    path.write_text(json.dumps(report))
    return path


def test_research_report_without_scout_only_fields_is_accepted(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    report = {
        "schema_version": "2.0",
        "cycle": 6,
        "phase": "research",
        "timestamp": "2026-05-17T01:56:20Z",
        "sources_consulted": {
            "local_team_service_repositories": {"searched": True, "results_count": 8}
        },
        "budget_consumed_usd": 0.0,
        "topics_found": {"new": [], "existing": ["X"], "total": 1},
        "notes_created": [],
        "notes_updated": [],
        "cost_estimate_usd": 0.0,
        "cumulative_cost_usd": 0.0,
        "next_action": "continue",
    }
    path = _write(report, vault, "cycle-006-research.json")
    result = _run(str(path), "--vault", str(vault), "--max-cycles", "10")
    assert result.returncode == 0, result.stdout + result.stderr


def test_scout_report_still_requires_scout_only_fields(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    report = {
        "schema_version": "2.0",
        "cycle": 1,
        "phase": "scout",
        "timestamp": "2026-05-17T01:00:00Z",
        "sources_consulted": {},
        "budget_consumed_usd": 0.0,
        # intentionally missing: dimensions_covered, topics_from_code,
        # intent_from_confluence
    }
    path = _write(report, vault, "cycle-001-scout.json")
    result = _run(str(path), "--vault", str(vault))
    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "topics_from_code" in combined
    assert "dimensions_covered" in combined


# ---------------------------------------------------------------------------
# v0.2.25 regression: research-phase budget aliases
# ---------------------------------------------------------------------------


def _research_report_minus_budget(cycle: int = 6) -> dict:
    return {
        "schema_version": "2.0",
        "cycle": cycle,
        "phase": "research",
        "timestamp": "2026-05-17T17:05:00Z",
        "sources_consulted": {
            "local_team_service_repositories": {"searched": True, "results_count": 5}
        },
        "topics_found": {"new": [], "existing": ["JSON"], "total": 1},
        "notes_created": ["data_vault/01 - Concepts/json.md"],
        "notes_updated": [],
        "next_action": "continue",
    }


def test_research_report_with_only_cumulative_cost_usd_is_accepted(
    tmp_path: Path,
) -> None:
    """v0.2.21–v0.2.24 aborted every real research cycle here because the
    DFS prompt template told the agent to emit ``cumulative_cost_usd``
    while the validator demanded ``budget_consumed_usd``. v0.2.25 accepts
    either alias.
    """
    vault = _vault(tmp_path)
    report = _research_report_minus_budget()
    report["cumulative_cost_usd"] = 0.0  # legacy DFS-prompt field name
    path = _write(report, vault, "cycle-006-research.json")
    result = _run(str(path), "--vault", str(vault), "--max-cycles", "10")
    assert result.returncode == 0, result.stdout + result.stderr


def test_research_report_with_only_cost_estimate_usd_is_accepted(
    tmp_path: Path,
) -> None:
    """Same as the cumulative case but using the second legacy alias the
    DFS prompt still emits. v0.2.25 must accept all three names."""
    vault = _vault(tmp_path)
    report = _research_report_minus_budget()
    report["cost_estimate_usd"] = 0.0
    path = _write(report, vault, "cycle-006-research.json")
    result = _run(str(path), "--vault", str(vault), "--max-cycles", "10")
    assert result.returncode == 0, result.stdout + result.stderr


def test_research_report_with_no_budget_field_is_rejected(
    tmp_path: Path,
) -> None:
    """Guard against over-relaxation: a research report that reports NO
    budget at all must still fail validation. Budget reporting is a
    contract requirement, just not tied to a single field name."""
    vault = _vault(tmp_path)
    report = _research_report_minus_budget()
    path = _write(report, vault, "cycle-006-research.json")
    result = _run(str(path), "--vault", str(vault), "--max-cycles", "10")
    assert result.returncode == 2, "no-budget report should fail validation"
    combined = result.stdout + result.stderr
    assert "budget" in combined.lower(), (
        "rejection message should mention budget; got:\n" + combined
    )


def test_research_report_with_all_three_budget_aliases_is_accepted(
    tmp_path: Path,
) -> None:
    """The v0.2.25 prompt template emits all three fields for forward-
    compat. This must remain valid."""
    vault = _vault(tmp_path)
    report = _research_report_minus_budget()
    report["budget_consumed_usd"] = 0.0
    report["cumulative_cost_usd"] = 0.0
    report["cost_estimate_usd"] = 0.0
    path = _write(report, vault, "cycle-006-research.json")
    result = _run(str(path), "--vault", str(vault), "--max-cycles", "10")
    assert result.returncode == 0, result.stdout + result.stderr
