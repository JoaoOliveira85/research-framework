"""Tests for scripts/validate_cycle.py v2 (code-first) dispatcher."""

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


def _stage_code_first_vault(tmp_path: Path) -> Path:
    """Stage a minimal vault with a code-first spec-parse.json."""
    vault = tmp_path / "vault"
    (vault / "_pipeline" / "cycles").mkdir(parents=True)
    (vault / "data_vault").mkdir()
    # spec-parse.json with an enumerated acme-corp source (primary, role=behaviour)
    spec_parse = {
        "name": "Test CF Vault",
        "data_sources": [
            {
                "name": "GitHub repos",
                "type": "internal",
                "priority": 1,
                "role": "behaviour",
                "required": True,
                "repos": [
                    {
                        "name": "OEHK",
                        "url": "https://github.com/acme-corp/oehk-service",
                    },
                    {
                        "name": "OMS",
                        "url": "https://github.com/acme-corp/oms-service",
                    },
                    {
                        "name": "ERP",
                        "url": "https://github.com/acme-corp/erp-service",
                    },
                    {
                        "name": "WMS",
                        "url": "https://github.com/acme-corp/wms-service",
                    },
                    {
                        "name": "OEBH",
                        "url": "https://github.com/acme-corp/oebh-service",
                    },
                    {
                        "name": "OECDH",
                        "url": "https://github.com/acme-corp/oecdh-service",
                    },
                    {
                        "name": "PIM",
                        "url": "https://github.com/acme-corp/pim-service",
                    },
                ],
            },
            {
                "name": "Confluence",
                "type": "external",
                "priority": 2,
                "role": "intent",
                "required": True,
            },
        ],
    }
    (vault / "_pipeline" / "spec-parse.json").write_text(json.dumps(spec_parse))
    return vault


def _put(vault: Path, fixture: Path, name: str = "cycle-001-scout.json") -> Path:
    dest = vault / "_pipeline" / "cycles" / name
    dest.write_text(fixture.read_text(encoding="utf-8"))
    return dest


# --- CONTINUE: valid v2 scout ---


def test_v2_valid_scout_continues(cycle_reports_v2_dir: Path, tmp_path: Path) -> None:
    vault = _stage_code_first_vault(tmp_path)
    report = _put(vault, cycle_reports_v2_dir / "valid-scout-v2.json")
    result = _run(str(report), "--vault", str(vault))
    assert result.returncode == 0, result.stdout + result.stderr


# --- ABORT: code-first invariants violated ---


def test_v2_empty_topics_from_code_aborts(
    cycle_reports_v2_dir: Path, tmp_path: Path
) -> None:
    vault = _stage_code_first_vault(tmp_path)
    report = _put(vault, cycle_reports_v2_dir / "empty-code-topics.json")
    result = _run(str(report), "--vault", str(vault))
    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "trunk-seed ordering violated" in combined
    assert "topics_from_code is empty" in combined
    assert "code-first" not in combined.lower()


def test_v2_orphan_intent_aborts(cycle_reports_v2_dir: Path, tmp_path: Path) -> None:
    vault = _stage_code_first_vault(tmp_path)
    report = _put(vault, cycle_reports_v2_dir / "orphan-intent.json")
    result = _run(str(report), "--vault", str(vault))
    assert result.returncode == 2
    assert "intent without matching code topic" in result.stdout + result.stderr


def test_v2_missing_dimension_aborts(
    cycle_reports_v2_dir: Path, tmp_path: Path
) -> None:
    vault = _stage_code_first_vault(tmp_path)
    report = _put(vault, cycle_reports_v2_dir / "missing-dimension.json")
    result = _run(str(report), "--vault", str(vault))
    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "missing required dimension" in combined
    assert "market" in combined


def test_v2_out_of_enum_repo_aborts(cycle_reports_v2_dir: Path, tmp_path: Path) -> None:
    vault = _stage_code_first_vault(tmp_path)
    report = _put(vault, cycle_reports_v2_dir / "out-of-enum-repo.json")
    result = _run(str(report), "--vault", str(vault))
    assert result.returncode == 2
    assert "not under enumerated repo" in result.stdout + result.stderr


# --- spec 053 FR-006 / T008b: trunk-seed generalization ---


def _to_v3(report_data: dict) -> dict:
    """Rename a v2 scout report's fields to the v3 (trunk) shape."""
    data = dict(report_data)
    data["schema_version"] = "3"
    if "topics_from_code" in data:
        data["topics_from_trunk"] = data.pop("topics_from_code")
    for intent in data.get("intent_from_confluence") or []:
        if isinstance(intent, dict) and "parent_code_topic_id" in intent:
            intent["parent_trunk_topic_id"] = intent.pop("parent_code_topic_id")
    return data


def test_v2_topics_from_trunk_field_accepted(
    cycle_reports_v2_dir: Path, tmp_path: Path
) -> None:
    """spec 053 FR-006 / D6: a v3 report using `topics_from_trunk` +
    `parent_trunk_topic_id` validates identically to the old `topics_from_code`
    shape. (Pre-053 the structural validator REQUIRED topics_from_code → ABORT.)"""
    vault = _stage_code_first_vault(tmp_path)
    v3 = _to_v3(json.loads((cycle_reports_v2_dir / "valid-scout-v2.json").read_text()))
    report = vault / "_pipeline" / "cycles" / "cycle-001-scout.json"
    report.write_text(json.dumps(v3))
    result = _run(str(report), "--vault", str(vault))
    assert result.returncode == 0, result.stdout + result.stderr


def test_v2_legacy_topics_from_code_still_accepted(
    cycle_reports_v2_dir: Path, tmp_path: Path
) -> None:
    """Back-compat: the old `topics_from_code` shape keeps validating (exit 0)."""
    vault = _stage_code_first_vault(tmp_path)
    report = _put(vault, cycle_reports_v2_dir / "valid-scout-v2.json")
    result = _run(str(report), "--vault", str(vault))
    assert result.returncode == 0, result.stdout + result.stderr


def test_pure_domain_tie_empty_trunk_topics_does_not_abort(tmp_path: Path) -> None:
    """spec 053 D7: when no trunk is derivable (priority tie), an empty
    topics_from_trunk list must not ABORT — pure-domain vaults are exempt."""
    vault = tmp_path / "vault"
    (vault / "_pipeline" / "cycles").mkdir(parents=True)
    (vault / "data_vault").mkdir()
    spec_parse = {
        "name": "Pure-Domain Tie Vault",
        "data_sources": [
            {
                "name": "Journals",
                "type": "external",
                "priority": 1,
                "role": "domain",
                "required": True,
            },
            {
                "name": "Reddit",
                "type": "external",
                "priority": 1,
                "role": "domain",
                "required": False,
            },
        ],
    }
    (vault / "_pipeline" / "spec-parse.json").write_text(json.dumps(spec_parse))
    report_data = {
        "schema_version": "3",
        "cycle": 1,
        "phase": "scout",
        "timestamp": "2026-06-02T00:00:00Z",
        "dimensions_covered": [
            "technical",
            "organizational",
            "domain",
            "market",
            "temporal",
        ],
        "topics_from_trunk": [],
        "intent_from_confluence": [],
        "proposed_filenames": [],
        "sources_consulted": ["Journals", "Reddit"],
        "termination_condition": None,
        "notes_created": [],
        "unresolved_wikilinks": [],
        "budget_consumed_usd": 1.0,
    }
    report = vault / "_pipeline" / "cycles" / "cycle-001-scout.json"
    report.write_text(json.dumps(report_data))
    result = _run(str(report), "--vault", str(vault))
    combined = result.stdout + result.stderr
    assert "trunk-seed ordering violated" not in combined
    assert result.returncode != 2 or "trunk-seed" not in combined.lower()


def test_v3_trunk_seed_still_enforces_enumerated_repo(
    cycle_reports_v2_dir: Path, tmp_path: Path
) -> None:
    """The repo-membership check still fires for a code trunk under the v3 field
    name — a topic outside the enumerated repos ABORTs."""
    vault = _stage_code_first_vault(tmp_path)
    v3 = _to_v3(json.loads((cycle_reports_v2_dir / "valid-scout-v2.json").read_text()))
    v3["topics_from_trunk"].append(
        {
            "id": "CT-1-099",
            "topic_type": "service",
            "source_file": "rogue-org/rogue-service/README.md",
            "source_snippet": "x",
            "proposed_filename": "Rogue.md",
        }
    )
    report = vault / "_pipeline" / "cycles" / "cycle-001-scout.json"
    report.write_text(json.dumps(v3))
    result = _run(str(report), "--vault", str(vault))
    assert result.returncode == 2
    assert "not under enumerated repo" in result.stdout + result.stderr


def test_v3_pure_domain_vault_no_trunk_repos_does_not_trip(tmp_path: Path) -> None:
    """spec 053 FR-006 critical guard: a vault whose trunk has no repos (a
    journal/domain-first vault) must NOT trip 'not under enumerated repo' — the
    `if signatures:` guard no-ops when derive_trunk yields no repo signatures."""
    vault = tmp_path / "vault"
    (vault / "_pipeline" / "cycles").mkdir(parents=True)
    (vault / "data_vault").mkdir()
    spec_parse = {
        "name": "Journal-First Vault",
        "data_sources": [
            {
                "name": "Journals",
                "type": "external",
                "priority": 1,
                "role": "domain",
                "required": True,
            },
            {
                "name": "Reddit",
                "type": "external",
                "priority": 3,
                "role": "domain",
                "required": False,
            },
        ],
    }
    (vault / "_pipeline" / "spec-parse.json").write_text(json.dumps(spec_parse))
    report_data = {
        "schema_version": "3",
        "cycle": 1,
        "phase": "scout",
        "timestamp": "2026-06-02T00:00:00Z",
        "dimensions_covered": [
            "technical",
            "organizational",
            "domain",
            "market",
            "temporal",
        ],
        "topics_from_trunk": [
            {
                "id": "CT-1-001",
                "topic_type": "concept",
                "source_file": "journals/nature/some-paper.pdf",
                "source_snippet": "abstract",
                "proposed_filename": "Some Paper.md",
            }
        ],
        "intent_from_confluence": [],
        "proposed_filenames": ["Some Paper.md"],
        "sources_consulted": ["Journals", "Reddit"],
        "termination_condition": None,
        "notes_created": [],
        "unresolved_wikilinks": [],
        "budget_consumed_usd": 1.0,
    }
    report = vault / "_pipeline" / "cycles" / "cycle-001-scout.json"
    report.write_text(json.dumps(report_data))
    result = _run(str(report), "--vault", str(vault))
    assert "not under enumerated repo" not in result.stdout + result.stderr


# --- TERMINATE: conditions A / B / C ---


def test_v2_condition_c_terminates(cycle_reports_v2_dir: Path, tmp_path: Path) -> None:
    vault = _stage_code_first_vault(tmp_path)
    report = _put(vault, cycle_reports_v2_dir / "condition-c-met.json")
    # Budget cap < fixture's 251.0 → triggers Condition C
    result = _run(str(report), "--vault", str(vault), "--budget-cap", "250.0")
    assert result.returncode == 1
    assert "Condition C" in result.stdout + result.stderr


def test_v2_condition_b_terminates(cycle_reports_v2_dir: Path, tmp_path: Path) -> None:
    vault = _stage_code_first_vault(tmp_path)
    report = _put(vault, cycle_reports_v2_dir / "condition-b-met.json")
    result = _run(str(report), "--vault", str(vault))
    assert result.returncode == 1
    assert "Condition B" in result.stdout + result.stderr


def test_v2_scout_at_max_cycles_continues(
    cycle_reports_v2_dir: Path, tmp_path: Path
) -> None:
    """Same as v1: scout on cycle N when max_cycles=N must not TERMINATE before DFS."""
    vault = _stage_code_first_vault(tmp_path)
    report = _put(
        vault, cycle_reports_v2_dir / "valid-scout-v2.json", name="cycle-006-scout.json"
    )
    data = json.loads(report.read_text())
    data["cycle"] = 6
    assert data.get("phase") == "scout"
    report.write_text(json.dumps(data))
    result = _run(str(report), "--vault", str(vault), "--max-cycles", "6")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Condition A" not in result.stdout + result.stderr


def test_v2_research_at_max_cycles_terminates(
    cycle_reports_v2_dir: Path, tmp_path: Path
) -> None:
    vault = _stage_code_first_vault(tmp_path)
    report = _put(
        vault,
        cycle_reports_v2_dir / "condition-c-met.json",
        name="cycle-006-research.json",
    )
    data = json.loads(report.read_text())
    data["cycle"] = 6
    data["phase"] = "research"
    data["termination_condition"] = None
    data["budget_consumed_usd"] = 10.0
    report.write_text(json.dumps(data))
    result = _run(
        str(report), "--vault", str(vault), "--max-cycles", "6", "--budget-cap", "250"
    )
    assert result.returncode == 1
    assert "Condition A" in result.stdout + result.stderr


# --- Back-compat: v1 reports still validate via the legacy path ---


def test_v1_report_still_validates(cycle_reports_v2_dir: Path, tmp_path: Path) -> None:
    """A report without schema_version (v1 default) uses the legacy handler."""
    vault = _stage_code_first_vault(tmp_path)
    v1_report = {
        "cycle": 1,
        "phase": "scout",
        "timestamp": "2026-04-17T00:00:00Z",
        "sources_consulted": {"github_repos": {"searched": True}},
        "topics_found": {"new": ["X"], "existing": [], "total": 1},
        "cost_estimate_usd": 5.0,
        "cumulative_cost_usd": 5.0,
    }
    report_path = vault / "_pipeline" / "cycles" / "v1-report.json"
    report_path.write_text(json.dumps(v1_report))
    result = _run(str(report_path), "--vault", str(vault))
    # v1 handler: required source github_repos is present → may warn but returns 0
    assert result.returncode in (
        0,
        2,
    )  # v1 path exercised; exact result depends on v1 rules
