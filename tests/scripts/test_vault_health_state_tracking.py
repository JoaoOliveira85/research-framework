"""Spec 083 FR-017: the control-file tracking check covers the state directory."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "vault_health.py"


def _load():
    spec = importlib.util.spec_from_file_location("vault_health_t083", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(vault: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(vault), *args], check=True, capture_output=True)


def _vault(tmp_path: Path, gitignore: str) -> Path:
    vault = tmp_path / "v"
    (vault / "_pipeline" / "state").mkdir(parents=True)
    (vault / "_pipeline" / "state" / "coverage-targets.json").write_text("{}\n")
    (vault / ".gitignore").write_text(gitignore)
    _git(tmp_path, "init", "-q", "-b", "main", str(vault))
    return vault


def test_untracked_state_directory_is_warned_about(tmp_path: Path) -> None:
    vh = _load()
    # Untracked: nothing added yet.
    vault = _vault(tmp_path / "a", "")
    warnings = vh.scan_control_file_git_tracking(vault)
    assert [(w.rel_path, w.reason) for w in warnings] == [
        ("_pipeline/state", "untracked")
    ]
    # Ignored: the legacy stanza hides state/.
    ignored = _vault(tmp_path / "b", "/*\n!_pipeline/\n_pipeline/*\n")
    assert [
        (w.rel_path, w.reason) for w in vh.scan_control_file_git_tracking(ignored)
    ] == [("_pipeline/state", "ignored")]
    # Tracked: no warning.
    _git(vault, "add", "-A")
    _git(vault, "-c", "user.email=t@e.com", "-c", "user.name=T", "commit", "-qm", "x")
    assert vh.scan_control_file_git_tracking(vault) == []
