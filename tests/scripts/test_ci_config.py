"""spec 009 / US2 + US3 + US5 — the PR CI workflow contract.

Before 009 the repo had **no PR CI** (`quality.yml` runs only on version tags).
This test pins `.github/workflows/ci.yml` so the cross-platform gate can't
silently lose a leg or a step:

  - triggers on **both** `pull_request` and `push` to the default branch (FR-004)
  - matrix `os == [macos-latest, ubuntu-latest]`, `fail-fast: false`
  - the macOS leg is **required** (no job-level `continue-on-error: true`) (FR-004)
  - each leg runs the full guard set: `pytest -m "not e2e"`, `ruff check`,
    `ruff format --check`, `shellcheck`, and the 039 installer `--dry-run` smoke

PyYAML footgun: YAML 1.1 parses the bare key ``on`` as the boolean ``True``;
GitHub keeps it as ``on``. We look up both so the test is robust either way.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load() -> dict:
    return yaml.safe_load(CI_YML.read_text(encoding="utf-8"))


def _triggers(config: dict) -> dict:
    # `on:` → True under YAML 1.1; fall back to the string key just in case.
    trig = config.get(True)
    if trig is None:
        trig = config.get("on")
    assert isinstance(trig, dict), f"`on:` must be a mapping, got {trig!r}"
    return trig


def _ci_job(config: dict) -> dict:
    jobs = config["jobs"]
    assert len(jobs) >= 1
    # The cross-platform matrix job (first job that declares a matrix).
    for job in jobs.values():
        if "strategy" in job and "matrix" in job["strategy"]:
            return job
    raise AssertionError("no matrix job found in ci.yml")


def _all_run_steps(job: dict) -> str:
    return "\n".join(
        str(step["run"])
        for step in job["steps"]
        if isinstance(step, dict) and "run" in step
    )


def test_ci_yml_exists() -> None:
    assert CI_YML.is_file(), "spec 009 US2: .github/workflows/ci.yml must exist"


def test_triggers_on_version_tags_and_by_hand_only() -> None:
    """PRs #323/#324 moved CI off `pull_request`/`push: main`.

    Spec 009 FR-004 asked for a per-PR cross-platform gate, and got one. It
    was withdrawn in September 2026 for a reason the spec could not have
    anticipated: a month's Actions allowance went in under a day on per-PR
    runs with a macOS matrix, which bills at 10x. The merge gate is now the
    LOCAL suite every PR reports (CONTRIBUTING § 1), and CI runs on version
    tags and by hand.

    This test used to assert the opposite and had been red on `main` since
    #324 — the workflow changed and its contract test did not, which is the
    same drift in the same direction as the docs #217 catalogues. Asserting
    the *current* triggers keeps it a contract test rather than deleting it:
    a `pull_request` trigger re-added by accident is a real billing incident,
    so it is worth failing on.
    """
    trig = _triggers(_load())
    assert "workflow_dispatch" in trig, "CI must remain runnable by hand"
    assert "push" in trig, "CI must run on a release tag push"
    push = trig["push"]
    assert isinstance(push, dict) and push.get("tags"), (
        "the push trigger must be scoped to tags, not branches"
    )
    assert "branches" not in push, (
        "a branch push trigger is what #323 removed — CI must not run per push"
    )
    assert "pull_request" not in trig, (
        "CI must not run per PR (#324): the merge gate is the local suite. "
        "Re-adding this trigger burns the Actions allowance in a day."
    )
    assert "schedule" not in trig, "no cron trigger — #324 removed it"


def test_matrix_is_linux_with_macos_opt_in() -> None:
    """macOS bills at 10x, so it is opt-in on a manual run (#323), not a
    standing leg. The Linux leg is unconditional."""
    job = _ci_job(_load())
    os_expr = job["strategy"]["matrix"]["os"]
    assert isinstance(os_expr, str) and "inputs.macos" in os_expr, (
        "the OS matrix must be the macos opt-in expression from #323"
    )
    assert "ubuntu-latest" in os_expr, "Linux must always be in the matrix"
    assert "macos-latest" in os_expr, (
        "macOS must still be reachable — opt-in, not removed"
    )
    assert job["strategy"].get("fail-fast") is False, (
        "fail-fast must be false so one OS failing still reports the other"
    )


def test_the_macos_opt_in_is_a_declared_workflow_input() -> None:
    """The matrix expression reads `inputs.macos`; if the input were dropped
    the expression would silently evaluate to the Linux-only branch forever."""
    inputs = _triggers(_load())["workflow_dispatch"]["inputs"]
    assert "macos" in inputs, "workflow_dispatch must declare the `macos` input"
    assert inputs["macos"]["type"] == "boolean"
    assert inputs["macos"]["default"] is False, (
        "macOS must default off — that default is the cost control"
    )


def test_macos_leg_is_required() -> None:
    job = _ci_job(_load())
    assert job.get("continue-on-error") is not True, (
        "FR-004: macOS is the primary target — the job must NOT be continue-on-error"
    )


def test_each_leg_runs_the_full_guard_set() -> None:
    runs = _all_run_steps(_ci_job(_load()))
    assert 'pytest -m "not e2e"' in runs, "FR-005: fast-loop pytest"
    assert "ruff check" in runs, "FR-005: ruff lint"
    assert "ruff format --check" in runs, (
        "FR-005: ruff format gate (separate from check)"
    )
    assert "shellcheck" in runs, "FR-006: shellcheck over shipped .sh"


def test_installs_dev_extra() -> None:
    runs = _all_run_steps(_ci_job(_load()))
    assert "pip install -e .[dev]" in runs, "FR-005: install the dev extra"


def test_runs_installer_dry_run_smoke() -> None:
    """US5/FR-005: each leg runs `install.sh … --dry-run` (consumes 039).
    039 has merged, so this step is required (no continue-on-error tolerance)."""
    runs = _all_run_steps(_ci_job(_load()))
    assert "install.sh" in runs and "--dry-run" in runs, (
        "US5: CI must exercise the installer in --dry-run on both OSes"
    )


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck absent")
def test_shellcheck_step_passes_on_this_tree() -> None:
    """Run CI's own shellcheck step locally.

    CI runs only on version tags (#323), so a shellcheck finding in a shipped
    script is first seen when a release is being cut. Root ``install.sh`` sat
    in that state: its unannotated ``source .venv/bin/activate`` is SC1091,
    which shellcheck reports at info level and still exits 1 on.
    """
    steps = [
        s
        for s in _ci_job(_load())["steps"]
        if isinstance(s, dict) and s.get("name") == "Shellcheck shipped scripts"
    ]
    assert len(steps) == 1, "expected exactly one 'Shellcheck shipped scripts' step"
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", steps[0]["run"]],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
