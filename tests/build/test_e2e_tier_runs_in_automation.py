"""Tier-7: every e2e-marked test must run somewhere automated (issue #266).

A marker is a promise that something runs the test. Until this file, 17 of the
27 ``e2e``-marked tests — across 10 files — ran in **no** automation at all:

- PR CI (``.github/workflows/ci.yml``) ran ``pytest -m "not e2e"``, which
  deselects the whole tier by construction;
- the smoke gate (``build.sh``'s ``SMOKE_TESTS``) selects by file path and
  listed only four of the thirteen e2e files;
- the quality/release job runs ``build.sh --quality``, which drives
  ``research_framework.quality.runner`` — not pytest.

So FR-003 / FR-004 / US3 / SC-002 proofs and the smoke-gate enforcement test
were green only on someone's laptop. This file pins the two routes an
e2e-marked file may take — the smoke gate, or the workflow's own e2e job —
and fails if any file takes neither.

It also pins the inverse convention: ``test_runner_agent_dispatch.py``'s
PR-gating power depends on it staying **unmarked** (its docstring says so),
and until now nothing enforced that. A future ``pytestmark = e2e`` there would
silently move the #209 regression gate out of the fast loop.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUILD_SH = _REPO_ROOT / "build.sh"
_CI_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

# The marker expression the CI e2e job runs. ``live_llm`` is excluded because
# those tests spend real money and are opt-in by design.
E2E_SELECTION = 'pytest -m "e2e and not live_llm"'

# Deliberately unmarked, and load-bearing that it stays so: it is the #209
# regression gate, and only PR CI's ``-m "not e2e"`` run reaches it.
_MUST_STAY_UNMARKED = ("tests/pipeline/test_runner_agent_dispatch.py",)


def _collect_e2e_files() -> set[str]:
    """Ask pytest itself which files carry the marker.

    Authoritative on purpose. A regex over ``pytest.mark.e2e`` would be
    cheaper and would drift from pytest's real selection — which is the exact
    class of bug this file exists to stop. ``--collect-only -qq`` prints bare
    ``path::name`` node ids and nothing else.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-m",
            "e2e and not live_llm",
            "--collect-only",
            "-qq",
            "-p",
            "no:cacheprovider",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"collection failed:\n{result.stdout[-3000:]}\n{result.stderr[-2000:]}"
    )
    files = {
        line.split("::", 1)[0].strip()
        for line in result.stdout.splitlines()
        if "::" in line and line.split("::", 1)[0].strip().endswith(".py")
    }
    assert files, (
        "no e2e-marked tests collected — the marker expression or the node-id "
        "parsing has drifted from what pytest prints"
    )
    return files


def _smoke_test_entries() -> set[str]:
    text = _BUILD_SH.read_text(encoding="utf-8")
    match = re.search(r"SMOKE_TESTS=\(\n(.*?)\n\)", text, re.DOTALL)
    assert match, "could not locate SMOKE_TESTS=(...) in build.sh"
    entries: set[str] = set()
    for raw in match.group(1).splitlines():
        line = raw.strip()
        if line.startswith("#"):
            continue
        quoted = re.match(r'"([^"]+)"', line)
        if quoted:
            entries.add(quoted.group(1))
    return entries


def _covered_by_smoke_gate(path: str, entries: set[str]) -> bool:
    """A gate entry covers *path* if it is the file or a parent directory."""
    return path in entries or any(
        entry.endswith("/") and path.startswith(entry) for entry in entries
    )


def _ci_runs_the_e2e_tier() -> bool:
    return E2E_SELECTION in _CI_WORKFLOW.read_text(encoding="utf-8")


def test_every_e2e_file_runs_in_some_automation() -> None:
    """Either the marker job runs the tier, or the gate names every file."""
    orphans = sorted(
        path
        for path in _collect_e2e_files()
        if not _covered_by_smoke_gate(path, _smoke_test_entries())
    )
    if not orphans:
        return
    assert _ci_runs_the_e2e_tier(), (
        f"{len(orphans)} e2e-marked file(s) run in no automation: {orphans}. "
        f"Either restore the `{E2E_SELECTION}` job in {_CI_WORKFLOW.name} or "
        "add each file to build.sh::SMOKE_TESTS."
    )


@pytest.mark.parametrize("path", _MUST_STAY_UNMARKED)
def test_pr_gating_files_carry_no_e2e_marker(path: str) -> None:
    """``-m "not e2e"`` is what reaches these; a marker would remove them."""
    assert Path(_REPO_ROOT / path).is_file(), f"{path} no longer exists"
    assert path not in _collect_e2e_files(), (
        f"{path} now carries an e2e marker. Its whole point is running in PR "
        "CI's fast loop — see its module docstring. Drop the marker, or move "
        "the regression gate it protects somewhere `-m 'not e2e'` reaches."
    )
