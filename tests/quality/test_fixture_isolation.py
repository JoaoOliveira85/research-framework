"""Spec 026 — fixture-isolation regression locks.

These tests guard three invariants:

* **US1 / SC-001 / SC-005** — neither the pytest ``run_fixture_cycles`` path
  nor the ``python -m research_framework.quality.runner`` path (the one
  ``build.sh --quality`` invokes) may mutate the *tracked* source-of-truth
  fixture tree under ``tests/fixtures/quality/``. The harness must run against
  an isolated copy.
* **US2 / SC-002** — committed fake-agent shims stay machine-agnostic (no baked
  ``/Users``-style absolute paths), while out-of-repo (``tmp_path``) installs
  DO bake the repo root so Strategy-3 import resolution keeps interception
  intact.
* **US3 / SC-006** — the fixture bootstrap refuses to mutate tracked files
  without an explicit ``--force``.

The git-status checks compare the set of dirty paths *before* and *after* the
run, so they are robust to a developer's pre-existing working-tree changes
(they assert only that the run introduced **no new** dirty paths).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES_REL = "tests/fixtures/quality"


def _dirty_paths(pathspec: str) -> set[str]:
    """Return the set of paths git reports as dirty under *pathspec*."""
    out = subprocess.run(
        ["git", "status", "--porcelain", "--", pathspec],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    # porcelain v1: "XY <path>" (rename uses " -> "); the path starts at col 3.
    return {line[3:] for line in out.splitlines() if line.strip()}


def _subprocess_env() -> dict[str, str]:
    env = {**os.environ}
    src = str(_REPO_ROOT / "src")
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src + os.pathsep + existing if existing else src
    return env


def test_quality_cycle_leaves_tracked_tree_pristine(tmp_path, quality_fixture_env):
    """US1 / SC-005: a ``run_fixture_cycles`` cycle must not dirty the tracked tree."""
    from tests.quality.conftest import run_fixture_cycles

    quality_fixture_env("tech-lite")
    before = _dirty_paths(_FIXTURES_REL)
    run_fixture_cycles("tech-lite", tmp_path=tmp_path, max_cycles=1)
    introduced = _dirty_paths(_FIXTURES_REL) - before
    assert not introduced, (
        f"run_fixture_cycles dirtied the tracked fixture tree: {sorted(introduced)}"
    )


@pytest.mark.e2e
@pytest.mark.slow
def test_quality_runner_leaves_tracked_tree_pristine():
    """SC-001: ``python -m research_framework.quality.runner`` keeps the tree clean.

    This is the path ``build.sh --quality`` runs; it must isolate cycle writes
    to a gitignored workspace, never the committed fixtures.
    """
    before = _dirty_paths(_FIXTURES_REL)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "research_framework.quality.runner",
            "--fixture",
            "tech-lite",
            "--no-color",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        env=_subprocess_env(),
    )
    introduced = _dirty_paths(_FIXTURES_REL) - before
    assert proc.returncode == 0, f"quality runner failed:\n{proc.stderr[-2000:]}"
    assert not introduced, (
        f"quality runner dirtied the tracked fixture tree: {sorted(introduced)}"
    )


def test_committed_shims_machine_agnostic():
    """US2 / SC-002: committed fixture shims carry no machine-specific paths."""
    machine_path = re.compile(r"/(Users|home|private/var/folders)/")
    shims = sorted(
        (_REPO_ROOT / "tests" / "fixtures" / "quality").glob("*/scripts/agent_call.py")
    )
    assert shims, "expected committed fake-agent shims under tests/fixtures/quality/"
    offenders = {
        str(shim.relative_to(_REPO_ROOT)): [
            line
            for line in shim.read_text(encoding="utf-8").splitlines()
            if machine_path.search(line)
        ]
        for shim in shims
    }
    offenders = {path: lines for path, lines in offenders.items() if lines}
    assert not offenders, f"committed shims contain machine-specific paths: {offenders}"


def test_tmp_path_shim_bakes_root_and_interception_holds(tmp_path):
    """US2 scenario 2 / T010: out-of-repo install bakes the repo root (Strategy 3);
    in-repo install bakes ``None`` (the byte-stable committed-shim path)."""
    from tests._helpers import fake_agent

    repo_root = fake_agent._repo_root()

    out_of_repo = fake_agent.install_shim(tmp_path / "scripts").read_text(
        encoding="utf-8"
    )
    assert f"_BAKED_REPO_ROOT = {str(repo_root)!r}" in out_of_repo, (
        "a tmp_path (out-of-repo) shim MUST bake the abs repo root so the "
        "shim's Strategy-3 import can find tests/_helpers/fake_agent "
        "(keeps the Principle-IV interception guard working)"
    )
    assert "_BAKED_REPO_ROOT = None" not in out_of_repo

    probe_dir = repo_root / "_pipeline" / "quality" / "_shim_probe_026"
    try:
        in_repo = fake_agent.install_shim(probe_dir).read_text(encoding="utf-8")
        assert "_BAKED_REPO_ROOT = None" in in_repo, (
            "an in-repo shim MUST bake None so committed fixture shims stay "
            "byte-stable across worktrees (machine-agnostic)"
        )
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)


def test_bootstrap_refuses_without_force():
    """US3 / SC-006: the fixture bootstrap is a dry-run no-op without ``--force``."""
    script = (
        _REPO_ROOT / "tests" / "fixtures" / "quality" / "_bootstrap_us3_fixtures.py"
    )
    before = _dirty_paths(_FIXTURES_REL)
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        env=_subprocess_env(),
    )
    introduced = _dirty_paths(_FIXTURES_REL) - before
    assert not introduced, (
        f"the bootstrap mutated tracked files without --force: {sorted(introduced)}"
    )
    assert proc.returncode == 0, (
        f"dry-run bootstrap should exit 0:\n{proc.stderr[-1000:]}"
    )
    combined = (proc.stdout + proc.stderr).lower()
    assert "force" in combined, "dry-run output should mention the --force escape hatch"
