"""``./build.sh --fixture`` without a fixture name is a usage error.

The option parser read the value as ``${2:-}`` and then ran ``shift 2``:

* ``./build.sh --quality --fixture`` — nothing left to shift, so ``shift 2``
  failed and ``set -e`` ended the script with exit 1 and no output at all;
* ``./build.sh --fixture --quality`` — ``--quality`` was taken as the fixture
  name, so the quality harness the operator asked for never ran and the build
  exited 0.

Every gate is stubbed (``PYTHON_BIN``, ``QUALITY_RUNNER_CMD``) and
``RESEARCH_FRAMEWORK_BUILD_TEST=1`` stops before the wheel build, so a parser
that lets either command line through cannot start a real build from a test.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUILD_SH = _REPO_ROOT / "build.sh"
_SYSTEM_BASH = Path("/bin/bash")

pytestmark = pytest.mark.skipif(
    not _SYSTEM_BASH.is_file(), reason="/bin/bash not available"
)


def _write_executable(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.mark.parametrize(
    "argv",
    [["--quality", "--fixture"], ["--fixture", "--quality"]],
    ids=["last-argument", "followed-by-an-option"],
)
def test_fixture_without_a_name_is_a_usage_error(
    tmp_path: Path, argv: list[str]
) -> None:
    fake_python = _write_executable(tmp_path / "fake-python", "#!/bin/sh\nexit 0\n")
    harness = _write_executable(
        tmp_path / "harness", '#!/bin/sh\necho "HARNESS_STUB_RAN"\n'
    )
    proc = subprocess.run(
        [str(_SYSTEM_BASH), str(_BUILD_SH), *argv],
        cwd=_REPO_ROOT,
        env={
            **os.environ,
            "RESEARCH_FRAMEWORK_BUILD_TEST": "1",
            "PYTHON_BIN": str(fake_python),
            "QUALITY_RUNNER_CMD": str(harness),
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    combined = proc.stdout + proc.stderr

    assert proc.returncode == 2, combined
    assert "--fixture needs a fixture name" in proc.stderr
    assert "--help" in proc.stderr
    assert "smoke gate" not in combined, "the build started anyway"
    assert "HARNESS_STUB_RAN" not in combined
