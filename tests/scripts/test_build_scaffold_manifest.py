"""Tests for scripts/build_scaffold_manifest.py — scaffold manifest generator."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "build_scaffold_manifest.py"
TEMPLATES_DIR = REPO_ROOT / "templates"
SCHEMA_PATH = (
    REPO_ROOT
    / "specs"
    / "013-vault-migrator"
    / "contracts"
    / "scaffold-manifest.schema.json"
)


@pytest.fixture
def manifest_output(tmp_path: Path) -> dict:
    out = tmp_path / "scaffold-manifest.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(out)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    return json.loads(out.read_text())


def test_walks_templates_dir_and_emits_entries(manifest_output: dict) -> None:
    """(a) output contains entries derived from templates/."""
    assert len(manifest_output["entries"]) > 0
    paths = [e["path"] for e in manifest_output["entries"]]
    # At least one entry should come from a known template
    assert any("CLAUDE.md" in p or "vault" in p for p in paths)


def test_rendered_sha256_is_hex_string(manifest_output: dict) -> None:
    """(b) rendered_sha256 is a 64-char hex string (SHA-256 over normalised output)."""
    for entry in manifest_output["entries"]:
        sha = entry["rendered_sha256"]
        assert len(sha) == 64
        assert all(c in "0123456789abcdef" for c in sha)


def test_output_matches_schema(manifest_output: dict) -> None:
    """(c) emits JSON matching scaffold-manifest.schema.json."""
    schema = json.loads(SCHEMA_PATH.read_text())
    required = schema.get("required", [])
    for field in required:
        assert field in manifest_output, f"missing required field: {field}"
    assert isinstance(manifest_output["framework_version"], int)
    assert isinstance(manifest_output["entries"], list)
    for entry in manifest_output["entries"]:
        for req in schema["properties"]["entries"]["items"].get("required", []):
            assert req in entry, f"entry missing field: {req}"


def test_byte_stable_on_two_runs(tmp_path: Path) -> None:
    """(d) running the script twice with no input changes produces identical JSON."""
    out1 = tmp_path / "run1.json"
    out2 = tmp_path / "run2.json"
    for out in (out1, out2):
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--output", str(out)],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        assert r.returncode == 0, r.stderr
    # Compare canonically (ignore generated_at timestamp)
    m1 = json.loads(out1.read_text())
    m2 = json.loads(out2.read_text())
    m1.pop("generated_at", None)
    m2.pop("generated_at", None)
    assert m1 == m2


def test_generator_commit_is_git_sha(manifest_output: dict) -> None:
    """(e) generator_commit is the current git SHA."""
    commit = manifest_output["generator_commit"]
    assert len(commit) >= 7
    assert all(c in "0123456789abcdef" for c in commit)
    # Verify it actually matches the repo's HEAD
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    head_short = result.stdout.strip()
    assert commit.startswith(head_short) or head_short.startswith(commit[:7])
