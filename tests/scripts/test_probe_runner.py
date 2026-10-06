"""RED tests (T088): `scripts/probe_runner.py` CLI and probe-results JSON contract."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "probe_runner.py"
SCHEMA_PATH = (
    REPO_ROOT
    / "specs"
    / "017-vault-quality-fix"
    / "contracts"
    / "probe-result.schema.json"
)


def _run_cli(vault: Path, cycle: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--vault",
            str(vault),
            "--cycle",
            str(cycle),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def _assert_probe_result_doc(doc: dict[str, Any]) -> None:
    """Hand-rolled checks aligned with `probe-result.schema.json` (no jsonschema)."""
    assert doc.get("schema_version") == "1"
    assert isinstance(doc.get("cycle_number"), int) and doc["cycle_number"] >= 1
    gen_at = doc.get("generated_at", "")
    assert isinstance(gen_at, str) and gen_at
    datetime.fromisoformat(gen_at.replace("Z", "+00:00"))

    score = doc.get("score")
    assert isinstance(score, int) and 0 <= score <= 100

    results = doc.get("results")
    assert isinstance(results, list)
    kinds = {"coverage", "cross_reference", "findability"}
    for item in results:
        assert set(item.keys()) <= {
            "probe_id",
            "kind",
            "question",
            "keywords",
            "source_category",
            "candidates",
            "scored_candidates",
            "answered",
            "partial",
            "reason",
        }
        assert item.get("probe_id")
        assert item.get("kind") in kinds
        assert item.get("question")
        assert isinstance(item.get("candidates"), list)
        for c in item["candidates"]:
            assert set(c.keys()) == {"filename", "confidence"}
            assert c["confidence"] in ("high", "medium", "low")
        sc = item.get("scored_candidates")
        assert isinstance(sc, list)
        for pair in sc:
            assert isinstance(pair, (list, tuple)) and len(pair) == 2
            assert isinstance(pair[1], int) and 0 <= pair[1] <= 3
        assert isinstance(item.get("answered"), bool)
        assert isinstance(item.get("partial"), bool)


@pytest.fixture
def minimal_vault(tmp_path: Path) -> Path:
    """Tiny vault layout: spec-parse + `_pipeline/cycles` for outputs."""
    vault = tmp_path / "pvault"
    pipeline = vault / "_pipeline"
    cycles = pipeline / "cycles"
    cycles.mkdir(parents=True)
    spec_parse = {
        "name": "x",
        "location": ".",
        "owner": "o",
        "scope": {
            "domain": "d",
            "organization": "org",
            "boundaries": [],
            "out_of_scope": [],
            "contextual_questions": ["Q1?"],
            "source_of_truth_rules": [],
        },
        "note_types": [
            {
                "name": "concept",
                "description": "",
                "folder": "c/",
                "required_sections": ["Overview"],
                "contextual_questions": ["topic question?"],
                "min_word_count": 200,
                "source_policy": "",
                "template_version": "1.0.0",
            }
        ],
        "data_sources": [],
        "search_dimensions": [],
        "coverage_targets": {
            "categories": [
                {
                    "name": "cat",
                    "note_type": "concept",
                    "target_count": 1,
                    "met_count": 0,
                    "required": True,
                    "expected_filenames": [],
                    "display_name": "",
                }
            ],
            "last_updated": "",
            "cycle_number": 0,
        },
        "budget": {"max_usd": 1.0, "max_cycles": 3, "warn_at_pct": 0.8},
        "max_cycles": 3,
        "naming_convention": "full_name",
        "jira_project": None,
        "access_modes": [],
        "settings": {
            "default_executor": None,
            "stages": {},
            "commands": {"ask": "ask", "research": "research", "write": "write"},
        },
        "code_source_url_patterns": [],
        "research_mode": "bootstrap",
        "vault_corpus_dir": "data_vault",
        "processors": {},
    }
    (pipeline / "spec-parse.json").write_text(
        json.dumps(spec_parse, indent=2) + "\n", encoding="utf-8"
    )
    return vault


def test_probe_runner_writes_schema_shaped_json(
    minimal_vault: Path,
) -> None:
    cycle = 3
    cand_path = (
        minimal_vault
        / "_pipeline"
        / "cycles"
        / f"cycle-{cycle:03d}-probe-candidates.json"
    )
    cand_path.write_text(
        json.dumps(
            {
                "cycle_number": cycle,
                "probes": {
                    "dummy-probe-id": [
                        {"filename": "note_one.md", "confidence": "high"},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    result = _run_cli(minimal_vault, cycle)
    assert result.returncode == 0, (result.stdout, result.stderr)

    out = (
        minimal_vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}-probe-results.json"
    )
    assert out.is_file()
    doc = json.loads(out.read_text(encoding="utf-8"))
    _assert_probe_result_doc(doc)
    assert SCHEMA_PATH.is_file()


def test_probe_runner_missing_candidates_still_exits_zero_and_zero_answered(
    minimal_vault: Path,
) -> None:
    cycle = 2
    result = _run_cli(minimal_vault, cycle)
    assert result.returncode == 0, (result.stdout, result.stderr)

    out = (
        minimal_vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}-probe-results.json"
    )
    assert out.is_file()
    doc = json.loads(out.read_text(encoding="utf-8"))
    _assert_probe_result_doc(doc)
    assert doc["score"] == 0
    assert len(doc["results"]) > 0
    assert all(not r["answered"] for r in doc["results"])
