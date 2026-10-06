"""Empty arrays under ``set -u`` on bash 3.2 (the macOS ``/bin/bash``).

Before bash 4.4, expanding an empty array as ``"${ARR[@]}"`` while ``set -u``
is active is an "unbound variable" error. ``build.sh`` and the end-user
``install.sh`` both start with ``#!/usr/bin/env bash`` and
``set -euo pipefail``, and on a stock macOS that resolves to bash 3.2.

The scripts are run with ``/bin/bash`` explicitly rather than whatever ``bash``
is first on ``PATH`` (a Homebrew bash 5 hides the bug). Only a ``/bin/bash``
older than 4.4 can make these tests fail; on a newer one they still pin the
behaviour.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUILD_SH = _REPO_ROOT / "build.sh"
_INSTALL_SH = _REPO_ROOT / "dist-templates" / "install.sh"
_SYSTEM_BASH = Path("/bin/bash")

pytestmark = pytest.mark.skipif(
    not _SYSTEM_BASH.is_file(), reason="/bin/bash not available"
)


def _write_executable(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def test_build_quality_without_optional_flags_reaches_the_harness(
    tmp_path: Path,
) -> None:
    """``./build.sh --quality`` with neither ``--fixture`` nor ``--no-color``
    hands the harness an empty argument array. Under bash 3.2 that expansion
    aborted the build before the harness ran."""
    # Every `${PYTHON_BIN} -m …` gate (ruff, smoke pytest) passes instantly:
    # the subject here is the argument hand-off, not the gates.
    fake_python = _write_executable(tmp_path / "fake-python", "#!/bin/sh\nexit 0\n")
    harness = _write_executable(
        tmp_path / "harness", '#!/bin/sh\necho "HARNESS_STUB_RAN argc=$#"\n'
    )
    env = {
        **os.environ,
        "RESEARCH_FRAMEWORK_BUILD_TEST": "1",
        "PYTHON_BIN": str(fake_python),
        "QUALITY_RUNNER_CMD": str(harness),
    }
    proc = subprocess.run(
        [str(_SYSTEM_BASH), str(_BUILD_SH), "--quality"],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    combined = proc.stdout + proc.stderr
    assert "unbound variable" not in combined, combined
    assert proc.returncode == 0, combined
    assert "HARNESS_STUB_RAN argc=0" in combined
    assert "quality harness passed" in combined


def test_install_summary_with_no_warnings_writes_nothing_to_stderr(
    tmp_path: Path,
) -> None:
    """The install summary serialises two arrays that are empty on a clean
    run. Under bash 3.2 each expansion printed an "unbound variable" error
    from the installer's own line numbers into the operator's terminal."""
    summary_path = tmp_path / "install_summary.json"
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    # Fail the mandatory Python probe on any host: it is the first exit that
    # writes a summary, and it runs before any warning or degraded mode can
    # be recorded, so both arrays are empty by construction. Every other
    # invocation is delegated, because the summary writer itself runs Python.
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    stub_body = (
        "#!/bin/sh\n"
        'for a in "$@"; do\n'
        '  case "$a" in\n'
        "    *version_info*) echo 3.9; exit 0 ;;\n"
        "  esac\n"
        "done\n"
        f'exec "{sys.executable}" "$@"\n'
    )
    for name in ("python3.11", "python3"):
        _write_executable(fake_bin / name, stub_body)
    env = {
        **os.environ,
        "RV_INSTALL_LOG": "0",
        "RV_NONINTERACTIVE": "1",
        "INSTALL_SUMMARY_PATH": str(summary_path),
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
    }
    proc = subprocess.run(
        [str(_SYSTEM_BASH), str(_INSTALL_SH), str(tmp_path / "vault"), "--dry-run"],
        cwd=str(bundle),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "unbound variable" not in proc.stderr, proc.stderr
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    assert data["warnings"] == []
    assert data["degraded_modes"] == []
