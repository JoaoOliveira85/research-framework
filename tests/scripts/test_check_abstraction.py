"""Tests for ``scripts/check_abstraction.py`` (T028, feature 017).

Thin CLI wrapper around ``SG003_topic_abstraction_check`` — Script Exit Code
Model: 0 for PASS / WARN / NA, 1 for FAIL, 2 for structural errors (missing
spec, unreadable paths). Stdout must be JSON conforming to
``contracts/cycle-quality-report.schema.json#/$defs/gate_result``.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
import yaml


def _gate_result_schema() -> dict:
    contracts = (
        Path(__file__).resolve().parents[2]
        / "specs"
        / "017-vault-quality-fix"
        / "contracts"
        / "cycle-quality-report.schema.json"
    )
    schema = json.loads(contracts.read_text(encoding="utf-8"))
    return schema["$defs"]["gate_result"]


def _matches_schema(payload: dict, schema: dict) -> tuple[bool, str]:
    for k in schema.get("required", []):
        if k not in payload:
            return False, f"missing required key: {k}"
    if schema.get("additionalProperties") is False:
        allowed = set(schema.get("properties", {}).keys())
        extras = set(payload.keys()) - allowed
        if extras:
            return False, f"unexpected keys: {sorted(extras)}"
    props = schema.get("properties", {})
    if "status" in payload and "enum" in props.get("status", {}):
        if payload["status"] not in props["status"]["enum"]:
            return False, f"invalid status: {payload['status']!r}"
    if "gate_id" in payload and "pattern" in props.get("gate_id", {}):
        if not re.match(props["gate_id"]["pattern"], payload["gate_id"]):
            return False, f"gate_id {payload['gate_id']!r} fails pattern"
    if payload.get("status") == "FAIL" and not payload.get("correction_hint"):
        return False, "status=FAIL requires non-empty correction_hint"
    return True, ""


@pytest.fixture
def check_abstraction_module():
    """Load ``check_abstraction.py`` as a module without ``shell``."""
    script = Path(__file__).resolve().parents[2] / "scripts" / "check_abstraction.py"
    spec = importlib.util.spec_from_file_location("check_abstraction_script", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_abstraction_script"] = module
    spec.loader.exec_module(module)
    return module


def _write_minimal_vault(
    vault: Path,
    *,
    forbidden: list[str],
    scout_titles: list[str],
    abstraction_enabled: bool | None = None,
) -> tuple[Path, Path]:
    """Return ``(spec_path, scout_path)``.

    Writes a decoy ``cycle-001-research.json`` alongside the scout report. The
    two documents come from different stages — only the scout report carries
    ``topics_found.new`` — so a CLI that picks the wrong one scores zero rows
    and reports PASS where the gate reports FAIL (#296).
    """
    vault.mkdir(parents=True, exist_ok=True)
    spec_body = f"""---
name: cli-abstraction
location: {vault}
owner: t
topic: test
goal: test
problem: test
growth_mode: incremental
size: small
scope:
  domain: d
  organization: o
  boundaries: []
  out_of_scope: []
note_types:
  - name: concept
    description: "x"
    folder: "01 - Concepts"
    min_word_count: 100
data_sources:
  - name: S
    type: external
    description: "x"
    required: true
    access_method: "web"
    role: domain
search_dimensions: [technical]
coverage_targets:
  categories:
    - name: concepts
      note_type: concept
      target_count: 3
      met_count: 0
      required: true
budget:
  max_usd: 1.0
  max_cycles: 2
forbidden_filename_prefixes: {json.dumps(forbidden)}
---
"""
    spec_path = vault / "research.spec.md"
    spec_path.write_text(spec_body, encoding="utf-8")
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True, exist_ok=True)
    scout_path = cycles / "cycle-001-scout.json"
    scout_path.write_text(
        json.dumps(
            {
                "topics_found": {
                    "new": [{"title": t} for t in scout_titles],
                },
                "proposed_filenames": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (cycles / "cycle-001-research.json").write_text(
        json.dumps({"cycle": 1, "phase": "research", "notes_written": []}, indent=2),
        encoding="utf-8",
    )
    gates: dict = {
        "sg_003_abstraction_warn_pct": 20,
        "sg_003_abstraction_fail_pct": 60,
    }
    if abstraction_enabled is not None:
        gates["abstraction_enabled"] = abstraction_enabled
    settings = {"pipeline": {"gates": gates}}
    (vault / "settings.yaml").write_text(
        yaml.safe_dump(settings, sort_keys=False),
        encoding="utf-8",
    )
    return spec_path, scout_path


class TestCheckAbstractionExitCodes:
    """Exit-code mapping for orchestrators and CI."""

    def test_exit_zero_on_pass(
        self, tmp_path: Path, check_abstraction_module, capsys
    ) -> None:
        _write_minimal_vault(
            tmp_path,
            forbidden=["zzz_"],
            scout_titles=["alpha", "beta", "gamma", "delta", "epsilon"],
        )
        rc = check_abstraction_module.main(
            [str(tmp_path / "research.spec.md"), str(tmp_path)]
        )
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "PASS"

    def test_exit_zero_on_warn(
        self, tmp_path: Path, check_abstraction_module, capsys
    ) -> None:
        _write_minimal_vault(
            tmp_path,
            forbidden=["oms_"],
            scout_titles=["oms_a", "oms_b", "x1", "x2", "x3"],
        )
        rc = check_abstraction_module.main(
            [str(tmp_path / "research.spec.md"), str(tmp_path)]
        )
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "WARN"

    def test_exit_zero_on_na_when_vault_disables_the_gate(
        self, tmp_path: Path, check_abstraction_module, capsys
    ) -> None:
        """NA is now a recorded vault decision, not an unpopulated spec key."""
        _write_minimal_vault(
            tmp_path,
            forbidden=[],
            scout_titles=["svc_x"],
            abstraction_enabled=False,
        )
        rc = check_abstraction_module.main(
            [str(tmp_path / "research.spec.md"), str(tmp_path)]
        )
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "NA"

    def test_empty_spec_list_falls_back_to_framework_prefixes(
        self, tmp_path: Path, check_abstraction_module, capsys
    ) -> None:
        """A spec that declares nothing gets the starter set, not an inactive gate."""
        _write_minimal_vault(
            tmp_path,
            forbidden=[],
            scout_titles=["svc_a", "svc_b", "tbl_c", "cache invalidation"],
        )
        rc = check_abstraction_module.main(
            [str(tmp_path / "research.spec.md"), str(tmp_path)]
        )
        assert rc == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "FAIL"

    def test_exit_one_on_fail(
        self, tmp_path: Path, check_abstraction_module, capsys
    ) -> None:
        _write_minimal_vault(
            tmp_path,
            forbidden=["oms_"],
            scout_titles=["oms_a", "oms_b", "oms_c", "oms_d", "ok"],
        )
        rc = check_abstraction_module.main(
            [str(tmp_path / "research.spec.md"), str(tmp_path)]
        )
        assert rc == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["status"] == "FAIL"

    def test_exit_two_when_spec_missing(
        self, tmp_path: Path, check_abstraction_module, capsys
    ) -> None:
        missing = tmp_path / "missing-spec.md"
        rc = check_abstraction_module.main([str(missing), str(tmp_path)])
        assert rc == 2
        captured = capsys.readouterr()
        blob = (captured.err + captured.out).lower()
        assert (
            "not found" in blob
            or "missing" in blob
            or "structural" in blob
            or "error" in blob
        )


class TestCheckAbstractionReportSource:
    """The CLI and the in-process gate must read the same cycle report (#296).

    ``scripts/check_abstraction.py`` used to glob ``cycle-*-research.json`` —
    the DFS output — while ``pipeline/steps/scout.py`` evaluates
    ``cycle-NNN-scout.json``. Run over the same cycle directory the two
    disagreed, or the CLI scored zero rows against a report that never had
    ``topics_found.new`` in it.
    """

    def test_cli_payload_matches_in_process_gate(
        self, tmp_path: Path, check_abstraction_module, capsys
    ) -> None:
        from research_framework.pipeline.gates_step import (
            SG003_topic_abstraction_check,
        )
        from research_framework.spec.parser import parse as parse_spec_file

        spec_path, scout_path = _write_minimal_vault(
            tmp_path,
            forbidden=["oms_"],
            scout_titles=["oms_a", "oms_b", "oms_c", "oms_d", "ok"],
        )
        check_abstraction_module.main([str(spec_path), str(tmp_path)])
        cli_payload = json.loads(capsys.readouterr().out)

        in_process = SG003_topic_abstraction_check(
            json.loads(scout_path.read_text(encoding="utf-8")),
            parse_spec_file(spec_path),
            tmp_path,
        )
        assert cli_payload == in_process.to_dict()
        assert cli_payload["status"] == "FAIL"

    def test_research_json_is_not_the_report_the_cli_reads(
        self, tmp_path: Path, check_abstraction_module, capsys
    ) -> None:
        """The decoy research report would score PASS; the scout report FAILs."""
        _write_minimal_vault(
            tmp_path,
            forbidden=["oms_"],
            scout_titles=["oms_a", "oms_b", "oms_c", "oms_d", "ok"],
        )
        rc = check_abstraction_module.main(
            [str(tmp_path / "research.spec.md"), str(tmp_path)]
        )
        assert rc == 1
        assert json.loads(capsys.readouterr().out)["status"] == "FAIL"

    def test_exit_two_when_no_scout_report(
        self, tmp_path: Path, check_abstraction_module, capsys
    ) -> None:
        spec_path, scout_path = _write_minimal_vault(
            tmp_path, forbidden=["oms_"], scout_titles=["ok"]
        )
        scout_path.unlink()
        rc = check_abstraction_module.main([str(spec_path), str(tmp_path)])
        assert rc == 2
        assert "scout" in capsys.readouterr().err.lower()

    def test_explicit_report_argument_overrides_the_derived_one(
        self, tmp_path: Path, check_abstraction_module, capsys
    ) -> None:
        """`--report` lets a caller name the report instead of deriving it."""
        spec_path, _ = _write_minimal_vault(
            tmp_path, forbidden=["oms_"], scout_titles=["ok"]
        )
        other = tmp_path / "_pipeline" / "cycles" / "cycle-007-scout.json"
        other.write_text(
            json.dumps({"topics_found": {"new": [{"title": "oms_x"}]}}),
            encoding="utf-8",
        )
        rc = check_abstraction_module.main(
            [str(spec_path), str(tmp_path), "--report", str(other)]
        )
        assert rc == 1
        assert json.loads(capsys.readouterr().out)["status"] == "FAIL"


class TestCheckAbstractionJsonContract:
    """Printed ``gate_result`` matches the cycle-quality-report fragment."""

    def test_stdout_conforms_to_gate_result_schema(
        self, tmp_path: Path, check_abstraction_module, capsys
    ) -> None:
        _write_minimal_vault(
            tmp_path,
            forbidden=["x_"],
            scout_titles=["one", "two"],
        )
        check_abstraction_module.main(
            [str(tmp_path / "research.spec.md"), str(tmp_path)]
        )
        payload = json.loads(capsys.readouterr().out)
        ok, why = _matches_schema(payload, _gate_result_schema())
        assert ok, why
