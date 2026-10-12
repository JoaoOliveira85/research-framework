"""Guards must judge the checkout under test, not another installed copy (#2).

``python scripts/guards/<guard>.py`` puts ``scripts/guards/`` on ``sys.path[0]``,
not ``src/``, so a guard that imports ``research_framework`` resolves it via
site-packages / an editable finder: a stale install or another worktree wins
and the guard reports findings about *that* tree's templates. The shared
helper ``scripts/guards/_checkout_package.py`` makes that a loud, explicit
failure instead.

The wrong-location case is simulated with a throwaway package on
``PYTHONPATH`` (which sits ahead of site-packages exactly like a stale
editable install would) — no real venvs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:  # ``scripts/`` is not an installed package
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.guards import _checkout_package as helper  # noqa: E402

_GUARDS = _REPO_ROOT / "scripts" / "guards"
_EXPECTED_FRAGMENT = "expected"


# ---------------------------------------------------------------------------
# The helper
# ---------------------------------------------------------------------------


def test_origin_inside_checkout_src_is_accepted(tmp_path: Path) -> None:
    origin = tmp_path / "src" / "research_framework" / "__init__.py"
    assert helper.package_location_problem(tmp_path, origin=origin) is None


def test_origin_in_another_tree_is_reported(tmp_path: Path) -> None:
    repo = tmp_path / "a"
    other = tmp_path / "b" / "src" / "research_framework" / "__init__.py"
    problem = helper.package_location_problem(repo, origin=other)
    assert problem is not None
    assert str(other.parent) in problem
    assert f"expected {repo / 'src'}" in problem
    assert "pip install -e ." in problem


def test_sibling_dir_sharing_a_prefix_is_not_inside_src(tmp_path: Path) -> None:
    # ``<repo>/src-old`` starts with ``<repo>/src`` as a string; it is not under it.
    origin = tmp_path / "src-old" / "research_framework" / "__init__.py"
    assert helper.package_location_problem(tmp_path, origin=origin) is not None


def test_unimportable_package_is_reported(tmp_path: Path) -> None:
    problem = helper.package_location_problem(tmp_path, package="rf_no_such_pkg_xyz")
    assert problem is not None
    assert "rf_no_such_pkg_xyz" in problem


def test_real_checkout_resolves_inside_this_repo() -> None:
    # pytest's ``pythonpath = ["src", "."]`` makes this the checkout under test.
    assert helper.package_location_problem(_REPO_ROOT) is None


def test_require_exits_2_with_message_on_wrong_location(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    origin = tmp_path / "elsewhere" / "research_framework" / "__init__.py"
    with pytest.raises(SystemExit) as excinfo:
        helper.require_checkout_package(tmp_path / "repo", origin=origin)
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "imported research_framework from" in err
    assert _EXPECTED_FRAGMENT in err


# ---------------------------------------------------------------------------
# The guards, run as scripts against a stand-in package in the wrong place
# ---------------------------------------------------------------------------


@pytest.fixture
def wrong_tree(tmp_path: Path) -> Path:
    """A directory holding a stub ``research_framework`` that is not ours."""
    pkg = tmp_path / "wrong" / "research_framework"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    return tmp_path / "wrong"


def _run(script: str, pythonpath: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(pythonpath)}
    return subprocess.run(
        [sys.executable, str(_GUARDS / script)],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_agent_asset_guard_fails_loudly_on_wrong_package(wrong_tree: Path) -> None:
    result = _run("check_agent_asset_references.py", wrong_tree)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "imported research_framework from" in result.stderr
    assert str(wrong_tree) in result.stderr
    assert "pip install -e ." in result.stderr


def test_run_all_refuses_to_run_battery_on_wrong_package(wrong_tree: Path) -> None:
    result = _run("run_all.py", wrong_tree)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "imported research_framework from" in result.stderr
    # Fail before any guard runs: no guard may report a verdict on the wrong tree.
    assert "[guards] running" not in result.stdout


def test_run_all_list_does_not_need_the_package(wrong_tree: Path) -> None:
    # ``--list`` only prints the battery; it must keep working regardless.
    env = {**os.environ, "PYTHONPATH": str(wrong_tree)}
    result = subprocess.run(
        [sys.executable, str(_GUARDS / "run_all.py"), "--list"],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
