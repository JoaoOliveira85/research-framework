"""Tests for scripts/vault_metrics.py — vault snapshot metrics."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "vault_metrics.py"


def run_script(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def test_snapshot_round_trip(vault_dir: Path) -> None:
    """vault_metrics.py outputs valid JSON with expected keys."""
    result = run_script(str(vault_dir))
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "note_count" in data
    assert "by_type" in data
    assert "word_count_buckets" in data
    assert "unresolved_wikilinks" in data


def test_note_count_matches_fixture_files(vault_dir: Path) -> None:
    """Reported note count matches actual fixture files under data_vault/."""
    result = run_script(str(vault_dir))
    data = json.loads(result.stdout)
    actual = len(list((vault_dir / "data_vault").rglob("*.md")))
    assert data["note_count"] == actual


def test_output_file_written(vault_dir: Path, tmp_path: Path) -> None:
    """--output path writes JSON to file."""
    out = tmp_path / "snapshot.json"
    result = run_script(str(vault_dir), "--output", str(out))
    assert result.returncode == 0
    assert out.exists()
    data = json.loads(out.read_text())
    assert "note_count" in data
