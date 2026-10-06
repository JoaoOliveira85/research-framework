"""Guard: no directory under ``tests/`` is silently dropped from collection.

pytest's *default* ``norecursedirs`` is
``*.egg .* _darcs build CVS dist node_modules venv {arch}``. One of those
entries is ``build`` — and this repo has a ``tests/build/`` tier. For as long
as ``pyproject.toml`` left ``norecursedirs`` unset, every module in it
(``test_smoke_gate.py``, ``test_smoke_gate_enforced.py``,
``test_settings_profiles_packaged.py`` — the D11 guard that proves
``settings.ollama.yaml`` ships in the wheel AND the install bundle — and the
rest) was skipped by ``pytest -m "not e2e"`` without a word: not a skip, not a
deselect, just absent. A gate that cannot see a test is the same thing as not
having written it.

These tests are deliberately OUTSIDE ``tests/build/``: a guard that lives in
the directory it guards disappears with it.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = REPO_ROOT / "tests"

#: One node id per directory this guard insists the default run can reach.
#: `tests/build/` is the one the default swallowed; the others are here so a
#: careless `norecursedirs` rewrite cannot trade one hidden tier for another.
REQUIRED_COLLECTED_DIRS: tuple[str, ...] = (
    "tests/build",
    "tests/contracts",
    "tests/docs",
    "tests/spec",
)


def _pytest_ini_options() -> dict:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["tool"]["pytest"]["ini_options"]


def test_norecursedirs_is_set_explicitly_and_does_not_hide_build() -> None:
    """The config must not fall back to pytest's default, which excludes `build`."""
    options = _pytest_ini_options()
    assert "norecursedirs" in options, (
        "pyproject.toml's [tool.pytest.ini_options] has no `norecursedirs`, so "
        "pytest's default applies — and that default excludes any directory "
        "named `build`, which silently drops all of tests/build/."
    )
    patterns = options["norecursedirs"]
    assert "build" not in patterns, (
        "`build` is back in norecursedirs; tests/build/ is a real test tier "
        f"({len(list((TESTS_ROOT / 'build').glob('test_*.py')))} modules) and "
        "would stop being collected."
    )


def test_tests_build_directory_is_not_empty() -> None:
    """Fail closed: an empty tests/build/ would make the collection test vacuous."""
    modules = sorted(p.name for p in (TESTS_ROOT / "build").glob("test_*.py"))
    assert len(modules) >= 5, f"expected tests/build/ to hold modules; found {modules}"
    assert "test_settings_profiles_packaged.py" in modules, (
        "the D11 packaging guard has moved; point this guard at its new home "
        "rather than deleting the assertion."
    )


@pytest.mark.slow
def test_default_collection_reaches_every_test_directory() -> None:
    """A real `pytest --collect-only` from the repo root must see each directory."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            # `addopts` carries `-v`, which cancels `-q` and suppresses the
            # per-test node ids this guard reads. Clear it for the probe.
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "PYTHONWARNINGS": "ignore"},
    )
    out = result.stdout
    assert re.search(r"\d+ tests? collected", out), (
        f"collection did not report a summary; tail:\n{out[-800:]}"
    )
    missing = [d for d in REQUIRED_COLLECTED_DIRS if f"{d}/" not in out]
    assert not missing, (
        "the default `pytest --collect-only -q` collected nothing under "
        f"{', '.join(missing)} — check `norecursedirs` in pyproject.toml."
    )


@pytest.mark.slow
def test_settings_profiles_packaging_guard_runs_in_the_fast_loop() -> None:
    """The D11 guard must be selected by the gate command, not merely exist."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
            "-m",
            "not e2e",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "PYTHONWARNINGS": "ignore"},
    )
    assert "tests/build/test_settings_profiles_packaged.py::" in result.stdout, (
        'the D11 packaging guard is not part of `pytest -m "not e2e"`; tail:\n'
        f"{result.stdout[-800:]}"
    )
