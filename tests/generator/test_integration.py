"""End-to-end integration test — `research_framework generate --dry-run` against sample spec."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_generate_dry_run_end_to_end(sample_spec_path: Path, tmp_path: Path) -> None:
    """Full generate flow produces a structurally complete vault."""
    vault = tmp_path / "generated-vault"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "research_framework.cli",
            "generate",
            "--spec",
            str(sample_spec_path),
            "--output",
            str(vault),
            "--dry-run",
            "--skip-gate",  # integration test doesn't re-run the test suite recursively
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    # Core layout
    assert (vault / "CLAUDE.md").exists()
    assert (vault / "AGENTS.md").exists()
    assert (vault / "README.md").exists()
    assert (vault / "update_vault.py").exists()
    assert (vault / "_index.md").exists()
    assert (vault / "_concepts.md").exists()
    assert (vault / "_graph.md").exists()
    assert (vault / "_templates" / "concept.md").exists()
    assert (vault / "_pipeline" / "coverage-targets.json").exists()
    assert (vault / "_pipeline" / "spec-parse.json").exists()
    assert (vault / "_pipeline" / "budget-log.md").exists()
    assert (vault / "_pipeline" / "prompts" / "scout-prompt.md").exists()
    assert (vault / "_pipeline" / "prompts" / "dfs-prompt.md").exists()
    assert (vault / "scripts" / "validate_vault.py").exists()
    assert (vault / "scripts" / "validate_cycle.py").exists()
    assert (vault / "scripts" / "topic_harvest.py").exists()
    assert (vault / "scripts" / "topic_propose.py").exists()
    # `run_cycle.sh` was the bash cycle driver `pipeline/cycle_runner.py`
    # replaced in spec 004. Nothing has invoked it since, yet `copy_scripts`
    # shipped it into every vault and chmod'd it executable — a second,
    # drifting copy of the step sequence that the doc-sync guard simultaneously
    # forbade anyone from documenting. It is no longer in the bundle (#298).
    assert not (vault / "scripts" / "run_cycle.sh").exists()

    # settings.yaml must carry the topic_propose block (off by default) so
    # the orchestrator has a tunable contract to flip without editing code.
    import yaml

    settings = yaml.safe_load((vault / "settings.yaml").read_text(encoding="utf-8"))
    tp = (settings.get("stages") or {}).get("topic_propose") or {}
    assert tp, "settings.yaml must declare stages.topic_propose"
    assert tp.get("enabled") is False, "Phase 2 must be opt-in (default off)"
    assert tp.get("max_proposals"), "max_proposals must be set"
    assert tp.get("max_degree"), "max_degree must be set"
    assert tp.get("on_missing_out_of_scope"), "on_missing_out_of_scope must be set"
    assert isinstance(tp.get("relation_types"), list) and tp["relation_types"], (
        "relation_types must be a non-empty closed enum"
    )

    # Data vault folder structure
    assert (vault / "data_vault" / "01 - Concepts").is_dir()

    # Spec name must appear in CLAUDE.md (not boilerplate)
    claude = (vault / "CLAUDE.md").read_text()
    assert "Test Vault" in claude

    # coverage-targets.json reflects the spec
    coverage = json.loads((vault / "_pipeline" / "coverage-targets.json").read_text())
    assert len(coverage["categories"]) == 2
    assert all(c["met_count"] == 0 for c in coverage["categories"])


def test_generate_invalid_spec_exits_2(tmp_path: Path) -> None:
    """Invalid spec → exit 2 with field-level error messages."""
    bad = tmp_path / "bad-spec.md"
    bad.write_text(
        "---\nname: \nowner: \nnote_types: []\ndata_sources: []\n"
        "search_dimensions: []\ncoverage_targets:\n  categories: []\n"
        "budget:\n  max_usd: 5\n  max_cycles: 1\n---\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "research_framework.cli",
            "generate",
            "--spec",
            str(bad),
            "--output",
            str(tmp_path / "never-created"),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    # Multiple field-level messages should appear
    assert "name" in result.stderr
    assert "owner" in result.stderr
