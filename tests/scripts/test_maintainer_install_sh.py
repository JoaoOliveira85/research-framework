"""The maintainer dev-setup script (root ``install.sh``) installs THIS repo.

It computed ``ROOT_DIR`` and created the venv there, but ran
``pip install -e ".[dev]"`` against the caller's working directory. Invoked as
``bash ~/src/research-framework/install.sh`` from anywhere else, it either
failed ("does not appear to be a Python project") or editable-installed
whatever project the caller happened to be standing in, into this repo's venv.

The harness pre-creates ``.venv/bin/activate`` so no venv is built and no
network is touched: the fake ``activate`` puts a ``python`` stub first on
PATH that records its working directory and arguments.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT_INSTALL_SH = Path(__file__).resolve().parents[2] / "install.sh"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_pip_install_targets_the_script_directory_not_the_cwd(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    elsewhere = tmp_path / "elsewhere"
    fakebin = tmp_path / "fakebin"
    log = tmp_path / "python-calls.log"
    for d in (repo / ".venv" / "bin", elsewhere, fakebin):
        d.mkdir(parents=True)
    shutil.copy2(ROOT_INSTALL_SH, repo / "install.sh")

    (repo / ".venv" / "bin" / "activate").write_text(
        f'export PATH="{fakebin}:$PATH"\n', encoding="utf-8"
    )
    stub = fakebin / "python"
    stub.write_text(
        f'#!/usr/bin/env bash\nprintf "%s|%s\\n" "$PWD" "$*" >> "{log}"\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)

    result = subprocess.run(
        ["bash", str(repo / "install.sh")],
        cwd=elsewhere,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    calls = log.read_text(encoding="utf-8").splitlines()
    editable = [c for c in calls if "install -e" in c]
    assert editable, f"no editable install recorded: {calls}"
    for call in editable:
        cwd, _, _args = call.partition("|")
        assert Path(cwd).resolve() == repo.resolve(), call
