"""`research-framework validate` must run its validators, or say why not.

After the CLI split, `_cmd_validate` looked for the validator scripts at
`Path(__file__).parents[2] / "scripts"` — `src/scripts` in a checkout,
`site-packages/scripts` in a wheel — which never exists. Every check was
skipped as "absent", nothing was printed, and the verb exited 0: a validation
gate that reported a pass having checked nothing.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_VAULT = REPO_ROOT / "tests" / "fixtures" / "vault"


def _run_validate(vault: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    return subprocess.run(
        [sys.executable, "-m", "research_framework", "validate", "--vault", str(vault)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


def test_validate_runs_the_vault_validator(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    shutil.copytree(FIXTURE_VAULT, vault)

    result = _run_validate(vault)

    assert "running validate_vault.py" in result.stdout, (
        f"rc={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )


def test_validate_missing_vault_exits_2_with_reason(tmp_path: Path) -> None:
    result = _run_validate(tmp_path / "no-such-vault")

    assert result.returncode == 2
    assert "no-such-vault" in result.stderr


# ---------------------------------------------------------------------------
# The three outcomes the fix promised beyond "it runs": each was untested.
# ---------------------------------------------------------------------------


def _fake_run(codes: list[int]):
    """A ``subprocess.run`` stand-in returning ``codes`` in order."""
    remaining = iter(codes)

    def run(_cmd, **_kwargs):
        return SimpleNamespace(returncode=next(remaining))

    return run


def test_a_signal_killed_validator_fails_the_verb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """A validator killed by a signal has a negative returncode, and
    ``max(worst, rc)`` drops it: an OOM-killed check read as a pass."""
    from research_framework.cli import audit

    monkeypatch.setattr(audit.subprocess, "run", _fake_run([0, -9, 0, 0, 0]))

    rc = audit._cmd_validate(argparse.Namespace(vault=tmp_path))

    assert rc == 2
    assert "template (exit -9)" in capsys.readouterr().err


def test_the_worst_validator_exit_code_is_returned_and_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from research_framework.cli import audit

    monkeypatch.setattr(audit.subprocess, "run", _fake_run([1, 0, 2, 0, 1]))

    rc = audit._cmd_validate(argparse.Namespace(vault=tmp_path))

    assert rc == 2
    err = capsys.readouterr().err
    for named in (
        "vault (exit 1)",
        "acronym (exit 2)",
        "code-source-coverage (exit 1)",
    ):
        assert named in err
    assert "template" not in err and "intent-drift" not in err


def test_no_validator_scripts_is_an_error_not_a_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Every check skipped as absent is the original bug's shape: exit 0
    having validated nothing."""
    from research_framework import _assets
    from research_framework.cli import audit

    empty = tmp_path / "scripts"
    empty.mkdir()
    monkeypatch.setattr(_assets, "asset_path", lambda _name: empty)

    rc = audit._cmd_validate(argparse.Namespace(vault=tmp_path))

    assert rc == 2
    assert "no validator scripts found" in capsys.readouterr().err
