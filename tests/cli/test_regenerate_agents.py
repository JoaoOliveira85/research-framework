"""Tests for `research-framework regenerate-agents` CLI sub-command."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
SAMPLE_SPEC = REPO_ROOT / "tests" / "fixtures" / "sample-spec.md"


def _make_minimal_vault(tmp_path: Path) -> Path:
    """Create a minimal vault with a spec-parse.json and research.spec.md."""
    vault = tmp_path / "testvault"
    vault.mkdir()
    (vault / "data_vault").mkdir()
    pipeline = vault / "_pipeline"
    pipeline.mkdir()

    # Minimal spec-parse.json (enough for the SimpleNamespace fallback path).
    spec_dict = {
        "name": "Test Vault",
        "owner": "Test Owner",
        "vault_corpus_dir": "data_vault",
        "note_types": [
            {
                "name": "concept",
                "description": "Concepts",
                "folder": "01 - Concepts",
                "required_sections": ["Overview"],
            }
        ],
        "data_sources": [
            {"name": "Web", "type": "external", "role": "general research"},
        ],
        "scope_include": ["AI"],
        "scope_exclude": ["Sports"],
    }
    (pipeline / "spec-parse.json").write_text(
        json.dumps(spec_dict, indent=2), encoding="utf-8"
    )

    # Copy real sample spec so load_spec can parse it if needed.
    shutil.copy2(SAMPLE_SPEC, vault / "research.spec.md")

    return vault


def _run_regenerate(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    import os as _os

    env = dict(_os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "research_framework", "regenerate-agents", *args],
        capture_output=True,
        text=True,
        env=env,
        **kwargs,
    )


def test_regenerate_all_with_force(tmp_path: Path) -> None:
    """--force rewrites all 8 agent files."""
    vault = _make_minimal_vault(tmp_path)
    result = _run_regenerate([str(vault), "--force"])
    assert result.returncode == 0, result.stderr
    assert "wrote 8 files" in result.stdout

    commands_dir = vault / ".claude" / "commands"
    from research_framework.agents import AGENT_NAMES

    for name in AGENT_NAMES:
        assert (commands_dir / f"{name}.md").exists(), f"missing {name}.md"


def test_regenerate_keeps_the_research_command_a_research_command(
    tmp_path: Path,
) -> None:
    """`/research` must survive a regenerate as the command `generate` wrote.

    It used to come back as the Topic-Radar agent definition instead — a
    different personality under the same filename (#252).
    """
    vault = _make_minimal_vault(tmp_path)
    result = _run_regenerate([str(vault), "--force"])
    assert result.returncode == 0, result.stderr

    research = (vault / ".claude" / "commands" / "research.md").read_text()
    assert "argument-hint:" in research, "not the generate-time slash command"
    assert "type: agent-definition" not in research
    assert "Depth-First Topic Researcher" not in research


def test_regenerate_specific_agents_with_force(tmp_path: Path) -> None:
    """--agent scout --agent verify --force rewrites exactly those two files."""
    vault = _make_minimal_vault(tmp_path)
    result = _run_regenerate(
        [str(vault), "--agent", "scout", "--agent", "verify", "--force"]
    )
    assert result.returncode == 0, result.stderr
    assert "wrote 2 files" in result.stdout

    commands_dir = vault / ".claude" / "commands"
    assert (commands_dir / "scout.md").exists()
    assert (commands_dir / "verify.md").exists()
    # Others should NOT exist (nothing pre-created).
    from research_framework.agents import AGENT_NAMES

    for name in AGENT_NAMES:
        if name not in ("scout", "verify"):
            assert not (commands_dir / f"{name}.md").exists()


def test_regenerate_without_force_declines_on_eof(tmp_path: Path) -> None:
    """Without --force and with no TTY input (EOF), the command declines."""
    vault = _make_minimal_vault(tmp_path)
    result = _run_regenerate(
        [str(vault)],
        input="",  # sends EOF immediately
    )
    # Should exit non-zero (aborted).
    assert result.returncode != 0


def test_regenerate_unknown_agent_exits_2(tmp_path: Path) -> None:
    """Passing an unknown agent name exits with code 2."""
    vault = _make_minimal_vault(tmp_path)
    result = _run_regenerate([str(vault), "--agent", "bogus", "--force"])
    assert result.returncode == 2
    assert "unknown agent" in result.stderr


def test_regenerate_missing_spec_parse_exits_2(tmp_path: Path) -> None:
    """Missing spec-parse.json causes exit 2."""
    vault = tmp_path / "empty_vault"
    vault.mkdir()
    (vault / "data_vault").mkdir()
    (vault / "_pipeline").mkdir()
    # No spec-parse.json.
    result = _run_regenerate([str(vault), "--force"])
    assert result.returncode == 2
    assert "spec-parse.json" in result.stderr
