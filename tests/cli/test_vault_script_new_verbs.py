from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from research_framework.spec.schema import SpecConfig
from tests._helpers.vault_factory import build_minimal_vault

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests/fixtures/refresh_sources_vault"


def _spec(vault: Path) -> SpecConfig:
    return SpecConfig.from_dict(
        json.loads((vault / "_pipeline/spec-parse.json").read_text())
    )


def _venv(vault: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "venv", str(vault / ".venv")],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [str(vault / ".venv/bin/pip"), "install", "-q", "-e", str(REPO)],
        check=True,
        capture_output=True,
    )


def test_vault_shim_refresh_sources_json_exit_0(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    shutil.copytree(FIXTURE, vault)
    _venv(vault)
    from research_framework.generator.scaffold import render_vault_shim

    (vault / "vault").write_text(render_vault_shim(vault, _spec(vault)))
    os.chmod(vault / "vault", 0o755)
    proc = subprocess.run(
        ["./vault", "refresh-sources", "--json"],
        cwd=vault,
        capture_output=True,
        text=True,
        env={**os.environ, "CI": "1"},
        stdin=subprocess.DEVNULL,
    )
    assert proc.returncode == 0
    json.loads(proc.stdout)


def test_vault_shim_regenerate_shim_json_exit_codes(tmp_path: Path) -> None:
    vault = build_minimal_vault(tmp_path)
    _venv(vault)
    from research_framework.generator.scaffold import render_vault_shim

    (vault / "vault").write_text(render_vault_shim(vault, _spec(vault)))
    os.chmod(vault / "vault", 0o755)
    bad = subprocess.run(
        ["./vault", "regenerate-shim", "--json"],
        cwd=vault,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    assert bad.returncode == 2
    ok = subprocess.run(
        ["./vault", "regenerate-shim", "--json", "--force"],
        cwd=vault,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    assert ok.returncode == 0
