"""Quickstart §8 smoke harness (T061, US3).

Runs the manual commands documented in
``specs/017-vault-quality-fix/quickstart.md`` §8 against disposable
vaults under ``tmp_path``. Uses the real ``scripts/check_abstraction.py`` and
``scripts/quality_report.py`` entry points (not non-existent ``python -m
research_framework.pipeline.*`` module CLIs).

Also covers the likely helper commands referenced in T061 (regenerate plan,
``scripts/quality_report.py``, ``scripts/check_abstraction.py``).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests._helpers import fake_cli_binary

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_SPEC = REPO_ROOT / "tests" / "fixtures" / "sample-spec.md"


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(cwd or REPO_ROOT),
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        check=False,
    )


def _prepare_smoke_vault(tmp_path: Path) -> Path:
    """Minimal vault: sample spec, coverage targets, backlog, empty corpus."""
    vault = tmp_path / "smokevault"
    vault.mkdir()
    (vault / "data_vault").mkdir()
    shutil.copy2(SAMPLE_SPEC, vault / "research.spec.md")
    from research_framework.pipeline.coverage import save_targets
    from research_framework.spec.simple import load as load_spec

    spec = load_spec(vault / "research.spec.md", location=vault)
    save_targets(vault, spec.coverage_targets)
    (vault / "_pipeline" / "research-backlog.md").write_text(
        "# backlog\n\n(no orphans)\n",
        encoding="utf-8",
    )
    (vault / "settings.yaml").write_text(
        "pipeline:\n  gates:\n    sg_003_abstraction_warn_pct: 20\n",
        encoding="utf-8",
    )
    return vault


def _prepare_quickstart_abstraction_vault(tmp_path: Path) -> Path:
    """Vault suitable for ``scripts/check_abstraction.py`` (SG-003, non-NA)."""
    vault = tmp_path / "abquick"
    vault.mkdir()
    spec_body = f"""---
name: quickstart-sg003-smoke
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
forbidden_filename_prefixes: ["svc_"]
---
"""
    (vault / "research.spec.md").write_text(spec_body, encoding="utf-8")
    (vault / "settings.yaml").write_text(
        yaml.safe_dump(
            {
                "pipeline": {
                    "gates": {
                        "sg_003_abstraction_warn_pct": 20,
                        "sg_003_abstraction_fail_pct": 60,
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True, exist_ok=True)
    scout = {
        "topics_found": {
            "new": [{"title": "Clean Architecture Patterns"}],
        },
        "proposed_filenames": [],
    }
    (cycles / "cycle-001-scout.json").write_text(
        json.dumps(scout, indent=2) + "\n",
        encoding="utf-8",
    )
    return vault


def _try_parse_gate_json(stdout: str) -> dict:
    lines = [ln for ln in stdout.strip().splitlines() if ln.strip()]
    if not lines:
        return {}
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        try:
            return json.loads(stdout.strip())
        except json.JSONDecodeError:
            return {}


class TestQuickstartSection8Smoke:
    """``quickstart.md`` §8 — ``scripts/check_abstraction.py`` + ``quality_report.py``."""

    def test_check_abstraction_script_prints_gate_result_json(
        self, tmp_path: Path
    ) -> None:
        vault = _prepare_quickstart_abstraction_vault(tmp_path)
        proc = _run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "check_abstraction.py"),
                str(vault / "research.spec.md"),
                str(vault),
            ],
            cwd=REPO_ROOT,
        )
        assert proc.returncode in (0, 1), (
            f"quickstart §8 check_abstraction: expected 0/1 (PASS/WARN/FAIL); "
            f"got {proc.returncode} stderr={proc.stderr!r}"
        )
        payload = _try_parse_gate_json(proc.stdout)
        assert payload.get("gate_id") == "SG-003", payload
        assert payload.get("status") in ("PASS", "WARN", "FAIL"), (
            f"expected concrete gate status on stdout; got {payload!r} "
            f"stderr={proc.stderr!r}"
        )

    def test_quality_report_cycle_missing_report_is_read_only(
        self, tmp_path: Path
    ) -> None:
        vault = _prepare_smoke_vault(tmp_path)
        cyc = vault / "_pipeline" / "cycles"
        cyc.mkdir(parents=True, exist_ok=True)
        missing = cyc / "cycle-001-quality-report.json"
        assert not missing.is_file()
        proc = _run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "quality_report.py"),
                "--vault",
                str(vault),
                "--cycle",
                "1",
            ],
            cwd=REPO_ROOT,
        )
        assert proc.returncode == 0, proc.stderr
        assert "missing" in proc.stderr.lower(), proc.stderr
        assert not missing.is_file(), "quality_report.py must not create the JSON file"

    def test_quality_report_cycle_summarizes_existing_report(
        self, tmp_path: Path
    ) -> None:
        vault = _prepare_smoke_vault(tmp_path)
        cyc = vault / "_pipeline" / "cycles"
        cyc.mkdir(parents=True, exist_ok=True)
        minimal = {
            "schema_version": "1",
            "cycle_number": 1,
            "framework_version": "0.2.18",
            "generated_at": "2026-05-15T12:00:00Z",
            "cycle_started_at": "2026-05-15T11:00:00Z",
            "cycle_finished_at": "2026-05-15T12:00:00Z",
            "gates": {
                "CG-001": {"status": "PASS", "metric_name": "n", "metric_value": 1}
            },
            "coverage_snapshot": {},
            "notes_written": 0,
            "notes_accepted": 0,
            "notes_rejected": 0,
            "batches": [],
            "queryability_score": 0,
            "queryability_trajectory": "stable",
            "degraded_sources": [],
            "retry_count": 0,
            "aborted": False,
        }
        report_path = cyc / "cycle-001-quality-report.json"
        before = json.dumps(minimal, sort_keys=True)
        report_path.write_text(json.dumps(minimal) + "\n", encoding="utf-8")
        proc = _run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "quality_report.py"),
                "--vault",
                str(vault),
                "--cycle",
                "1",
            ],
            cwd=REPO_ROOT,
        )
        assert proc.returncode == 0, proc.stderr
        assert "Cycle: 1" in proc.stdout, proc.stdout
        assert "CG-001" in proc.stdout, proc.stdout
        after = json.dumps(
            json.loads(report_path.read_text(encoding="utf-8")), sort_keys=True
        )
        assert after == before, "quality_report.py must not mutate the report file"

    def test_quality_report_all_lists_existing_reports(self, tmp_path: Path) -> None:
        vault = _prepare_smoke_vault(tmp_path)
        cyc = vault / "_pipeline" / "cycles"
        cyc.mkdir(parents=True, exist_ok=True)
        template = {
            "schema_version": "1",
            "framework_version": "0.2.18",
            "generated_at": "2026-05-15T12:00:00Z",
            "cycle_started_at": "2026-05-15T11:00:00Z",
            "cycle_finished_at": "2026-05-15T12:00:00Z",
            "gates": {},
            "coverage_snapshot": {},
            "notes_written": 0,
            "notes_accepted": 0,
            "notes_rejected": 0,
            "batches": [],
            "queryability_score": 42,
            "queryability_trajectory": "stable",
            "degraded_sources": [],
            "retry_count": 0,
            "aborted": False,
        }
        for n, q in ((1, 10), (2, 20)):
            body = {**template, "cycle_number": n, "queryability_score": q}
            (cyc / f"cycle-{n:03d}-quality-report.json").write_text(
                json.dumps(body) + "\n",
                encoding="utf-8",
            )
        proc = _run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "quality_report.py"),
                "--vault",
                str(vault),
                "--all",
            ],
            cwd=REPO_ROOT,
        )
        assert proc.returncode == 0, proc.stderr
        assert "cycle-001-quality-report.json" in proc.stdout
        assert "cycle-002-quality-report.json" in proc.stdout
        assert "\t10\t" in proc.stdout
        assert "\t20\t" in proc.stdout


class TestQuickstartCliAndScripts:
    """Regenerate-plan + helper scripts (stability harness)."""

    def test_cli_regenerate_plan_only_writes_valid_plan(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        vault = _prepare_smoke_vault(tmp_path)
        # The plan narrator dispatches through the real ``agent_call.py``, and
        # the CLI below inherits this environment: without a stand-in the real
        # ``claude`` on the developer's PATH was run.
        fake_cli_binary.activate(monkeypatch, tmp_path / "bin")
        proc = _run(
            [
                sys.executable,
                "-m",
                "research_framework.cli",
                "generate",
                str(vault),
                "--regenerate-plan-only",
            ],
            cwd=REPO_ROOT,
        )
        assert proc.returncode == 0, proc.stderr
        plan = vault / "_pipeline" / "research-plan.md"
        assert plan.is_file(), f"missing {plan}"
        text = plan.read_text(encoding="utf-8")
        assert text.lstrip().startswith("---"), "plan must start with YAML frontmatter"
        for heading in (
            "## Focus rationale",
            "## Coverage state",
            "## Cycle focus",
            "## Priority queue",
            "## Exclusions",
        ):
            assert heading in text, f"missing section {heading}"

    def test_script_quality_report_cycle_zero_never_exit_2(
        self, tmp_path: Path
    ) -> None:
        vault = _prepare_smoke_vault(tmp_path)
        cyc = vault / "_pipeline" / "cycles"
        cyc.mkdir(parents=True, exist_ok=True)
        minimal = {
            "schema_version": "1",
            "cycle_number": 1,
            "framework_version": "0.2.18",
            "generated_at": "2026-05-15T12:00:00Z",
            "cycle_started_at": "2026-05-15T11:00:00Z",
            "cycle_finished_at": "2026-05-15T12:00:00Z",
            "gates": {},
            "coverage_snapshot": {},
            "notes_written": 0,
            "notes_accepted": 0,
            "notes_rejected": 0,
            "batches": [],
            "queryability_score": 0,
            "queryability_trajectory": "stable",
            "degraded_sources": [],
            "retry_count": 0,
            "aborted": False,
        }
        (cyc / "cycle-001-quality-report.json").write_text(
            json.dumps(minimal) + "\n",
            encoding="utf-8",
        )
        proc = _run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "quality_report.py"),
                "--vault",
                str(vault),
                "--cycle",
                "1",
            ],
            cwd=REPO_ROOT,
        )
        assert proc.returncode != 2, (
            f"quality_report.py must not use exit 2 for a readable vault; "
            f"stderr={proc.stderr!r}"
        )
        assert proc.returncode == 0, proc.stderr

    def test_script_check_abstraction_gate_result_shape(self, tmp_path: Path) -> None:
        vault = tmp_path / "abvault"
        vault.mkdir()
        spec_body = f"""---
name: cli-abstraction-smoke
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
forbidden_filename_prefixes: ["svc_"]
---
"""
        (vault / "research.spec.md").write_text(spec_body, encoding="utf-8")
        (vault / "settings.yaml").write_text(
            yaml.safe_dump(
                {
                    "pipeline": {
                        "gates": {
                            "sg_003_abstraction_warn_pct": 20,
                            "sg_003_abstraction_fail_pct": 60,
                        }
                    }
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        cycles = vault / "_pipeline" / "cycles"
        cycles.mkdir(parents=True, exist_ok=True)
        scout = {
            "topics_found": {
                "new": [{"title": "Clean Architecture Patterns"}],
            },
            "proposed_filenames": [],
        }
        (cycles / "cycle-001-scout.json").write_text(
            json.dumps(scout, indent=2) + "\n",
            encoding="utf-8",
        )
        proc = _run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "check_abstraction.py"),
                str(vault / "research.spec.md"),
                str(vault),
            ],
            cwd=REPO_ROOT,
        )
        assert proc.returncode in (
            0,
            1,
        ), f"check_abstraction structural error (2) unexpected here: {proc.stderr}"
        assert proc.returncode != 2
        payload = _try_parse_gate_json(proc.stdout)
        assert payload.get("gate_id") == "SG-003", payload
        assert payload.get("status") in ("PASS", "WARN", "FAIL", "NA"), payload
