"""Tests for fake_module helper."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests._helpers.fake_module import write_fake_extractor


def test_fake_module_extractor_emits_json_stdout(tmp_path: Path) -> None:
    module_dir = tmp_path / "stub"
    write_fake_extractor(module_dir, stdout_payload={"hello": "world", "n": 1})
    (module_dir / "manifest.yaml").write_text("name: stub\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(module_dir / "extractor.py"), "extract"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(proc.stdout)["hello"] == "world"


def test_fake_module_inject_exception_on_attempt(tmp_path: Path) -> None:
    module_dir = tmp_path / "stub"
    write_fake_extractor(module_dir, fail_attempts={2})
    script = module_dir / "extractor.py"
    first = subprocess.run(
        [sys.executable, str(script), "extract"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0
    second = subprocess.run(
        [sys.executable, str(script), "extract"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode != 0
