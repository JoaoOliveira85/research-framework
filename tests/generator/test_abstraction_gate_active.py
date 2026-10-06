"""The abstraction gates must be live on a stock generated vault (#296).

SG-003 and CG-003 keyed off ``spec.forbidden_filename_prefixes``, which defaults
to empty and which nothing under ``generator/`` writes. So every vault the
framework produces reported ``NA`` — "abstraction gate inactive" — on every
cycle, for ever, unless its author happened to discover the key. ``NA`` never
builds a correction directive, so in the cycle log it was indistinguishable
from a clean pass.

These tests run the real generator into ``tmp_path`` and evaluate the gates
through the same spec-loading path the orchestrator uses
(``_load_spec_for_scout_gates`` → ``_pipeline/spec-parse.json``), so they fail
if the gate is inactive anywhere along that route.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from research_framework.pipeline._helpers.source_signals import (
    _load_spec_for_scout_gates,
)
from research_framework.pipeline.gates_cycle import CG003_filename_abstraction_check
from research_framework.pipeline.gates_step import SG003_topic_abstraction_check


def _generate(spec_path: Path, vault: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "research_framework.cli",
            "generate",
            "--spec",
            str(spec_path),
            "--output",
            str(vault),
            "--dry-run",
            "--skip-gate",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"


def _scout_report(titles: list[str]) -> dict:
    return {"topics_found": {"new": [{"title": t} for t in titles]}}


def _set_gate_setting(vault: Path, key: str, value: object) -> None:
    path = vault / "settings.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.setdefault("pipeline", {}).setdefault("gates", {})[key] = value
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_sample_spec_declares_no_prefixes(sample_spec_path: Path) -> None:
    """Premise guard: the fixture spec is a stock one, exactly like a new vault's."""
    assert "forbidden_filename_prefixes" not in sample_spec_path.read_text(
        encoding="utf-8"
    )


def test_generated_vault_fails_sg003_on_internal_artifact_topics(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    """The documented FAIL condition: > 60% of ``topics_found.new`` match."""
    vault = tmp_path / "generated-vault"
    _generate(sample_spec_path, vault)
    spec = _load_spec_for_scout_gates(vault)
    assert spec is not None

    result = SG003_topic_abstraction_check(
        _scout_report(["svc_billing", "svc_ledger", "tbl_accounts", "idempotency"]),
        spec,
        vault,
    )
    assert result.status == "FAIL", result.message
    assert result.correction_hint


def test_generated_vault_passes_sg003_on_concept_topics(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    """Active does not mean noisy — real concept titles still pass."""
    vault = tmp_path / "generated-vault"
    _generate(sample_spec_path, vault)
    spec = _load_spec_for_scout_gates(vault)
    assert spec is not None

    result = SG003_topic_abstraction_check(
        _scout_report(["idempotency", "backpressure", "quorum reads"]), spec, vault
    )
    assert result.status == "PASS", result.message


def test_generated_vault_fails_cg003_on_internal_artifact_filenames(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "generated-vault"
    _generate(sample_spec_path, vault)
    spec = _load_spec_for_scout_gates(vault)
    assert spec is not None

    result = CG003_filename_abstraction_check(
        spec,
        ["svc_billing.md", "svc_ledger.md", "tbl_accounts.md", "idempotency.md"],
        vault,
    )
    assert result.status == "FAIL", result.message


def test_vault_can_switch_the_abstraction_gates_off(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    """Opting out stays possible, but it has to be written down."""
    vault = tmp_path / "generated-vault"
    _generate(sample_spec_path, vault)
    _set_gate_setting(vault, "abstraction_enabled", False)
    spec = _load_spec_for_scout_gates(vault)
    assert spec is not None

    scout = SG003_topic_abstraction_check(_scout_report(["svc_a"]), spec, vault)
    cycle = CG003_filename_abstraction_check(spec, ["svc_a.md"], vault)
    assert scout.status == "NA"
    assert cycle.status == "NA"
    assert "settings.yaml" in scout.message


def test_generated_scout_prompt_names_the_prefixes_the_gate_enforces(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    """The agent must be told the rule it is about to be graded on."""
    vault = tmp_path / "generated-vault"
    _generate(sample_spec_path, vault)
    prompt = (vault / "_pipeline" / "prompts" / "scout-prompt.md").read_text(
        encoding="utf-8"
    )
    assert "svc_" in prompt
