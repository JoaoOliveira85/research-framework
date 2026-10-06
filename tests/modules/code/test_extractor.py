"""Code module extractor tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests._helpers.fake_repo import FakeRepo


def _run_extractor(command: str, payload: dict, module_dir: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(module_dir / "extractor.py"), command],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(module_dir),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_code_extractor_get_source_version_from_fake_repo(tmp_path: Path) -> None:
    repo = FakeRepo(tmp_path / "repo-version")
    module_dir = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "research_framework"
        / "modules"
        / "code"
    )
    out = _run_extractor(
        "get_source_version", {"source": {"path": str(repo.root)}}, module_dir
    )
    assert out["source_version"] == repo.head_sha()


def test_code_extractor_extract_emits_signal_shape(tmp_path: Path) -> None:
    repo = FakeRepo(tmp_path / "repo-extract")
    module_dir = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "research_framework"
        / "modules"
        / "code"
    )
    out = _run_extractor(
        "extract",
        {"source": {"path": str(repo.root)}, "source_id": str(repo.root)},
        module_dir,
    )
    assert out["module"] == "code"
    assert "verdict" in out
    assert "facts" in out


def test_code_extractor_against_fake_repo_fixture(tmp_path: Path) -> None:
    test_code_extractor_get_source_version_from_fake_repo(tmp_path)
    test_code_extractor_extract_emits_signal_shape(tmp_path)
