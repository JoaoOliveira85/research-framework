"""v0.2.26 regression tests for ``preconditions.check(..., for_resume=True)``.

Background: the user's cycle-5 vault had 56 ``validate_vault.py`` violations
(legacy frontmatter), a 17-source preflight that reported every source as
"unreachable: unknown access_method", and was running from a bundled install
(no ``tests/scripts/`` co-located). v0.2.25 ``--resume`` blocked with:

    Preconditions unmet:
      - precondition 1: pytest tests/scripts/ failed in research-framework repo
      - precondition 2: validate_vault.py reports violations
      - precondition 6: source preflight failed — see _pipeline/preflight.json

All three are legitimate on initial generate but inappropriate for resume:
1. The framework is already installed and the previous cycle ran — no
   reason to re-validate the framework here.
2. The vault is **expected** to have unresolved quality issues; that's why
   we're running more cycles.
3. The preflight checker's recognized-access-method set is narrower than
   the spec validator's, so specs that worked for cycles 1–N report
   unreachable here. Downgrade to WARN.

v0.2.26 adds ``for_resume=True`` to the check signature; ``cli.py::_resume``
sets it. The tests below lock the new behaviour for both modes.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest

from research_framework.pipeline.preconditions import check

_real_subprocess_run = subprocess.run


# ---------------------------------------------------------------------------
# Vault fixtures
# ---------------------------------------------------------------------------


def _write_structural_files(vault: Path) -> None:
    """Pre 3/4/5 files (always required, even on resume)."""
    pl = vault / "_pipeline"
    pl.mkdir(parents=True, exist_ok=True)
    pl.joinpath("coverage-targets.json").write_text("{}", encoding="utf-8")
    pl.joinpath("budget-log.md").write_text("# budget\n", encoding="utf-8")
    vault.joinpath("CLAUDE.md").write_text(
        "# vault\nnaming convention: snake_case\n", encoding="utf-8"
    )


def _write_validate_vault_that_fails(vault: Path) -> None:
    """Stub ``scripts/validate_vault.py`` that always exits 1 (mimicking the
    user's vault with 56 frontmatter violations).
    """
    scripts = vault / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    scripts.joinpath("validate_vault.py").write_text(
        "import sys\nprint('FAIL: violations galore')\nsys.exit(1)\n",
        encoding="utf-8",
    )


def _write_spec_with_unreachable_required(vault: Path) -> None:
    """A spec whose required source is a non-existent path. Preflight will
    return ``overall_status == "fail"`` against this.
    """
    bad = vault / "this-path-does-not-exist-for-resume-test"
    assert not bad.exists()
    vault.joinpath("research.spec.md").write_text(
        "\n".join(
            [
                "---",
                'name: "ResumeRegression"',
                "location: ./",
                "owner: t",
                "settings: {}",
                "---",
                "## Scope",
                "domain: d",
                "organization: o",
                "## Note Types",
                "- name: concept",
                "  description: d",
                '  folder: "01 - Concepts"',
                "## Data Sources",
                "- name: main-repo",
                "  type: internal",
                "  role: behaviour",
                "  required: true",
                "  access_method: local",
                "  repos:",
                f'    - name: r\n      url: ""\n      local_path: "{bad.as_posix()}"',
                "## Search Dimensions",
                "dimensions: []",
                "## Coverage Targets",
                "categories: []",
                "## Budget",
                "max_usd: 1",
                "max_cycles: 1",
                "",
            ]
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Resume path: preconditions 1, 2, 6 must NOT block
# ---------------------------------------------------------------------------


def test_resume_skips_precondition_1_framework_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On --resume the framework-tests check is skipped entirely. We prove
    it by patching ``subprocess.run`` to track any pytest invocation and
    asserting none happen for the framework-tests path."""
    vault = tmp_path / "v-pre1-resume"
    _write_structural_files(vault)
    _write_spec_with_unreachable_required(vault)

    calls: list[list[str]] = []

    def tracking_run(cmd, **kwargs):
        calls.append([str(c) for c in cmd])
        if "pytest" in cmd:
            return subprocess.CompletedProcess(cmd, 0, b"", b"")
        return _real_subprocess_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", tracking_run)

    ok, unmet = check(vault, for_resume=True)

    pytest_invocations = [c for c in calls if any("pytest" in part for part in c)]
    assert pytest_invocations == [], (
        "for_resume=True must NOT invoke pytest; "
        f"saw {len(pytest_invocations)} call(s): {pytest_invocations}"
    )
    assert not any("precondition 1" in m for m in unmet)


def test_resume_skips_precondition_2_validate_vault_failures(
    tmp_path: Path,
) -> None:
    """v0.2.25's blocker: validate_vault.py exits 1 because the vault has
    legacy frontmatter violations. On --resume that exit code must not
    appear in the unmet list."""
    vault = tmp_path / "v-pre2-resume"
    _write_structural_files(vault)
    _write_validate_vault_that_fails(vault)
    _write_spec_with_unreachable_required(vault)

    ok, unmet = check(vault, for_resume=True)

    assert not any("precondition 2" in m for m in unmet), (
        "validate_vault.py exit 1 must not block --resume; unmet was:\n"
        + "\n".join(unmet)
    )


def test_resume_downgrades_precondition_6_preflight_fail_to_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """v0.2.25's blocker: preflight reports every source unreachable
    because the access_method strings aren't in its recognized set. On
    --resume that fail becomes a logger.warning, not an unmet entry."""
    vault = tmp_path / "v-pre6-resume"
    _write_structural_files(vault)
    _write_spec_with_unreachable_required(vault)

    caplog.set_level(
        logging.WARNING, logger="research_framework.pipeline.preconditions"
    )
    ok, unmet = check(vault, for_resume=True)

    assert not any("precondition 6" in m for m in unmet), (
        "preflight fail must downgrade to warning on --resume; unmet was:\n"
        + "\n".join(unmet)
    )
    warning_text = " ".join(rec.getMessage() for rec in caplog.records)
    assert "preflight" in warning_text.lower(), (
        "expected a logger.warning mentioning preflight; got:\n" + warning_text
    )
    assert "downgrad" in warning_text.lower() or "warn" in warning_text.lower()


def test_resume_with_realistic_v0_2_25_user_vault_succeeds(
    tmp_path: Path,
) -> None:
    """End-to-end regression: a vault that triggered all three v0.2.25
    blockers (validate_vault fails + preflight fails + bundled install with
    no framework tests) MUST validate cleanly under for_resume=True. This
    is the literal shape of the user's reference-vault-v4 cycle-6 attempt.
    """
    vault = tmp_path / "v-user-regression"
    _write_structural_files(vault)
    _write_validate_vault_that_fails(vault)
    _write_spec_with_unreachable_required(vault)

    ok, unmet = check(vault, for_resume=True)

    assert ok, (
        "v0.2.25 regression: resume on the user's reference-vault-v4 shape "
        "still blocks. unmet:\n" + "\n".join(unmet)
    )


# ---------------------------------------------------------------------------
# Resume path: structural preconditions 3/4/5 STILL block (sanity)
# ---------------------------------------------------------------------------


def test_resume_still_demands_coverage_targets(tmp_path: Path) -> None:
    """``--resume`` does NOT make us accept a vault that's missing the
    coverage-targets file. The orchestrator can't function without it."""
    vault = tmp_path / "v-no-targets"
    pl = vault / "_pipeline"
    pl.mkdir(parents=True)
    pl.joinpath("budget-log.md").write_text("# budget\n", encoding="utf-8")
    vault.joinpath("CLAUDE.md").write_text(
        "# vault\nnaming convention: snake_case\n", encoding="utf-8"
    )
    vault.joinpath("research.spec.md").write_text("", encoding="utf-8")

    ok, unmet = check(vault, for_resume=True)
    assert not ok
    assert any("coverage-targets" in m for m in unmet)


def test_resume_still_demands_budget_log(tmp_path: Path) -> None:
    vault = tmp_path / "v-no-budget"
    pl = vault / "_pipeline"
    pl.mkdir(parents=True)
    pl.joinpath("coverage-targets.json").write_text("{}", encoding="utf-8")
    vault.joinpath("CLAUDE.md").write_text(
        "# vault\nnaming convention: snake_case\n", encoding="utf-8"
    )
    vault.joinpath("research.spec.md").write_text("", encoding="utf-8")

    ok, unmet = check(vault, for_resume=True)
    assert not ok
    assert any("budget-log" in m for m in unmet)


def test_resume_still_demands_claude_md_with_naming_convention(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "v-no-claude"
    pl = vault / "_pipeline"
    pl.mkdir(parents=True)
    pl.joinpath("coverage-targets.json").write_text("{}", encoding="utf-8")
    pl.joinpath("budget-log.md").write_text("# budget\n", encoding="utf-8")
    vault.joinpath("research.spec.md").write_text("", encoding="utf-8")

    ok, unmet = check(vault, for_resume=True)
    assert not ok
    assert any("CLAUDE.md" in m for m in unmet)


# ---------------------------------------------------------------------------
# Initial generate path: pre-1 fallback must NOT invent failures when
# the CWD isn't the framework repo (v0.2.25 bug)
# ---------------------------------------------------------------------------


def test_initial_generate_skips_pytest_fallback_when_not_in_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v0.2.25 ran ``pytest tests/scripts/`` against the caller's CWD when
    the vault had no embedded ``scripts/tests/``. On bundled installs that
    CWD is the vault folder (no ``tests/`` dir), so pytest failed and the
    precondition reported a phantom problem. v0.2.26 skips this fallback
    unless the CWD is plausibly the framework repo.
    """
    vault = tmp_path / "v-init-not-in-repo"
    _write_structural_files(vault)
    # No scripts/tests/ in vault → triggers the fallback path.
    # No tests/scripts/ in CWD either: chdir to a clean tmp dir.
    clean_cwd = tmp_path / "clean-cwd"
    clean_cwd.mkdir()
    monkeypatch.chdir(clean_cwd)
    # Also need a passing validate_vault.py so we isolate the Pre-1 signal.
    (vault / "scripts").mkdir(parents=True, exist_ok=True)
    (vault / "scripts" / "validate_vault.py").write_text(
        "import sys\nsys.exit(0)\n", encoding="utf-8"
    )
    # Spec with a reachable source so Pre-6 doesn't muddy the picture.
    repo = vault / "ok-repo"
    repo.mkdir()
    vault.joinpath("research.spec.md").write_text(
        "\n".join(
            [
                "---",
                'name: "InitNotInRepo"',
                "location: ./",
                "owner: t",
                "settings: {}",
                "---",
                "## Scope",
                "domain: d",
                "organization: o",
                "## Note Types",
                "- name: concept",
                "  description: d",
                '  folder: "01 - Concepts"',
                "## Data Sources",
                "- name: code",
                "  type: internal",
                "  role: behaviour",
                "  required: true",
                "  access_method: local",
                "  repos:",
                f'    - name: r\n      url: ""\n      local_path: "{repo.as_posix()}"',
                "## Search Dimensions",
                "dimensions: []",
                "## Coverage Targets",
                "categories: []",
                "## Budget",
                "max_usd: 1",
                "max_cycles: 1",
                "",
            ]
        ),
        encoding="utf-8",
    )

    calls: list[list[str]] = []

    def tracking_run(cmd, **kwargs):
        calls.append([str(c) for c in cmd])
        if "pytest" in cmd:
            return subprocess.CompletedProcess(cmd, 1, b"", b"not found")
        return _real_subprocess_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", tracking_run)

    ok, unmet = check(vault, for_resume=False)

    framework_pytest_calls = [
        c for c in calls if "pytest" in c and any("tests/scripts" in part for part in c)
    ]
    assert framework_pytest_calls == [], (
        "v0.2.25 ran tests/scripts/ from an arbitrary CWD; v0.2.26 must "
        f"skip that path. Saw: {framework_pytest_calls}"
    )
    assert not any("precondition 1" in m for m in unmet), (
        "Pre-1 must not appear in unmet on bundled installs; got:\n" + "\n".join(unmet)
    )


# ---------------------------------------------------------------------------
# Initial generate path: ALL six checks still run (backwards compat)
# ---------------------------------------------------------------------------


def test_initial_generate_still_runs_validate_vault_check(
    tmp_path: Path,
) -> None:
    """Initial generate (for_resume=False default) must still enforce
    precondition 2 — a fresh vault that fails validate_vault is a real
    problem worth blocking. Backwards-compat guard so the v0.2.26 changes
    don't accidentally over-relax the initial path too.
    """
    vault = tmp_path / "v-init-bad-vault"
    _write_structural_files(vault)
    _write_validate_vault_that_fails(vault)
    vault.joinpath("research.spec.md").write_text("", encoding="utf-8")

    ok, unmet = check(vault, for_resume=False)
    assert any("precondition 2" in m for m in unmet), (
        "Initial generate must still block on validate_vault violations; "
        "unmet was:\n" + "\n".join(unmet)
    )


def test_initial_generate_still_runs_preflight_check(tmp_path: Path) -> None:
    """Initial generate must still block on a preflight fail — that's the
    purpose of the check on the initial path. v0.2.26 only relaxes resume.
    """
    vault = tmp_path / "v-init-bad-preflight"
    _write_structural_files(vault)
    # Passing validate_vault.py so it doesn't shadow the preflight signal.
    (vault / "scripts").mkdir(parents=True, exist_ok=True)
    (vault / "scripts" / "validate_vault.py").write_text(
        "import sys\nsys.exit(0)\n", encoding="utf-8"
    )
    _write_spec_with_unreachable_required(vault)

    ok, unmet = check(vault, for_resume=False)
    assert any("preflight" in m.lower() for m in unmet), (
        "Initial generate must still block on preflight fail; unmet was:\n"
        + "\n".join(unmet)
    )
