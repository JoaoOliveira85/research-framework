"""Tests for `research_framework inventory` CLI sub-command."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
FIXTURE_VAULT = Path(__file__).parent.parent / "fixtures" / "vault"
MANIFEST_PATH = REPO_ROOT / "dist-templates" / "scaffold-manifest.json"


def _run_inventory(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    import os as _os

    env = dict(_os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "research_framework", "inventory", *args],
        capture_output=True,
        text=True,
        env=env,
        **kwargs,
    )


def _make_minimal_vault(tmp_path: Path) -> Path:
    """Clone the fixture vault into tmp_path so we have an isolated copy."""
    dst = tmp_path / "vault"
    shutil.copytree(FIXTURE_VAULT, dst)
    return dst


# ---------------------------------------------------------------------------
# JSON output validates against schema (basic field presence)
# ---------------------------------------------------------------------------


def test_json_output_has_required_fields(tmp_path: Path) -> None:
    vault = _make_minimal_vault(tmp_path)
    result = _run_inventory([str(vault), "--format=json"])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    inv = json.loads(result.stdout)
    for key in (
        "vault_root",
        "framework_version",
        "vault_spec",
        "manifest_status",
        "corpus",
        "scripts",
        "slash_commands",
        "pipeline_state",
        "warnings",
        "generated_at",
    ):
        assert key in inv, f"Missing key: {key}"


def test_manifest_status_structure(tmp_path: Path) -> None:
    vault = _make_minimal_vault(tmp_path)
    result = _run_inventory([str(vault), "--format=json"])
    assert result.returncode == 0
    ms = json.loads(result.stdout)["manifest_status"]
    for key in ("entries_total", "matching", "pending_overwrite", "pending_create"):
        assert key in ms, f"manifest_status missing: {key}"
    assert ms["entries_total"] > 0


# ---------------------------------------------------------------------------
# Text output is non-empty and readable
# ---------------------------------------------------------------------------


def test_text_output_nonempty(tmp_path: Path) -> None:
    vault = _make_minimal_vault(tmp_path)
    result = _run_inventory([str(vault), "--format=text"])
    assert result.returncode == 0
    assert len(result.stdout.strip()) > 50


def test_text_output_contains_vault_name(tmp_path: Path) -> None:
    vault = _make_minimal_vault(tmp_path)
    result = _run_inventory([str(vault), "--format=text"])
    assert result.returncode == 0
    # spec-parse.json has name "Test Vault"
    assert "Test Vault" in result.stdout


# ---------------------------------------------------------------------------
# User-added script appears in scripts.user_added
# ---------------------------------------------------------------------------


def test_user_added_script_detected(tmp_path: Path) -> None:
    vault = _make_minimal_vault(tmp_path)
    scripts_dir = vault / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    (scripts_dir / "foo.py").write_text("# custom script\n")

    result = _run_inventory([str(vault), "--format=json"])
    assert result.returncode == 0
    inv = json.loads(result.stdout)
    user_added_names = [e["name"] for e in inv["scripts"]["user_added"]]
    assert "foo.py" in user_added_names


# ---------------------------------------------------------------------------
# User-added slash command appears in slash_commands.user_added
# ---------------------------------------------------------------------------


def test_user_added_slash_command_detected(tmp_path: Path) -> None:
    vault = _make_minimal_vault(tmp_path)
    cmd_dir = vault / ".claude" / "commands"
    cmd_dir.mkdir(parents=True, exist_ok=True)
    (cmd_dir / "custom.md").write_text("# custom command\n")

    result = _run_inventory([str(vault), "--format=json"])
    assert result.returncode == 0
    inv = json.loads(result.stdout)
    user_added_names = [e["name"] for e in inv["slash_commands"]["user_added"]]
    assert "custom" in user_added_names


def test_user_added_slash_command_agent_definition(tmp_path: Path) -> None:
    vault = _make_minimal_vault(tmp_path)
    cmd_dir = vault / ".claude" / "commands"
    cmd_dir.mkdir(parents=True, exist_ok=True)
    (cmd_dir / "myagent.md").write_text("---\ntype: agent-definition\n---\n# agent\n")

    result = _run_inventory([str(vault), "--format=json"])
    assert result.returncode == 0
    inv = json.loads(result.stdout)
    user_added = {e["name"]: e for e in inv["slash_commands"]["user_added"]}
    assert "myagent" in user_added
    assert user_added["myagent"]["agent_definition"] is True


# ---------------------------------------------------------------------------
# Read-only: git status clean after inventory
# ---------------------------------------------------------------------------


def test_inventory_is_readonly(tmp_path: Path) -> None:
    """Inventory must not write any file to the vault."""
    import shutil as _shutil

    if not _shutil.which("git"):
        pytest.skip("git not available")

    vault = _make_minimal_vault(tmp_path)
    # Init a git repo in the vault so we can check status
    subprocess.run(["git", "init", str(vault)], capture_output=True)
    subprocess.run(["git", "-C", str(vault), "add", "."], capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(vault),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=T",
            "commit",
            "-m",
            "init",
        ],
        capture_output=True,
    )

    result = _run_inventory([str(vault), "--format=json"])
    assert result.returncode == 0

    status = subprocess.run(
        ["git", "-C", str(vault), "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    assert status.stdout.strip() == "", f"Vault was modified:\n{status.stdout}"


# ---------------------------------------------------------------------------
# Non-vault exit code 2
# ---------------------------------------------------------------------------


def test_not_a_vault_exits_2(tmp_path: Path) -> None:
    result = _run_inventory([str(tmp_path), "--format=json"])
    assert result.returncode == 2


# ---------------------------------------------------------------------------
# --out writes to file
# ---------------------------------------------------------------------------


def test_out_flag_writes_file(tmp_path: Path) -> None:
    vault = _make_minimal_vault(tmp_path)
    out_file = tmp_path / "inv.json"
    result = _run_inventory([str(vault), "--format=json", "--out", str(out_file)])
    assert result.returncode == 0
    assert out_file.exists()
    inv = json.loads(out_file.read_text())
    assert "vault_root" in inv
