"""Tier-6 integration: build.sh --quality flag wiring (T068 / US5)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUILD_SH = _REPO_ROOT / "build.sh"

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


def test_build_without_quality_skips_harness() -> None:
    """US5 scenario 3: default build.sh does not invoke the quality harness."""
    text = _BUILD_SH.read_text(encoding="utf-8")
    assert "RUN_QUALITY" in text
    assert "running quality harness" in text

    env = {
        **os.environ,
        "RESEARCH_FRAMEWORK_BUILD_TEST": "1",
        "PYTHON_BIN": sys.executable,
    }
    proc = subprocess.run(
        ["bash", str(_BUILD_SH)],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "smoke gate passed" in combined
    assert "running quality harness" not in combined
    assert "HARNESS_STUB_RAN" not in combined


def test_build_quality_runs_smoke_then_harness(tmp_path: Path) -> None:
    """US5 scenario 4: --quality runs smoke gate before the harness."""
    stub = tmp_path / "harness_stub.sh"
    stub.write_text(
        "#!/usr/bin/env bash\necho 'HARNESS_STUB_RAN'\nexit 0\n", encoding="utf-8"
    )
    stub.chmod(0o755)
    env = {
        **os.environ,
        "RESEARCH_FRAMEWORK_BUILD_TEST": "1",
        "PYTHON_BIN": sys.executable,
        "QUALITY_RUNNER_CMD": str(stub),
    }
    proc = subprocess.run(
        ["bash", str(_BUILD_SH), "--quality", "--no-color"],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    smoke_idx = combined.index("smoke gate passed")
    harness_idx = combined.index("running quality harness")
    stub_idx = combined.index("HARNESS_STUB_RAN")
    assert smoke_idx < harness_idx < stub_idx
