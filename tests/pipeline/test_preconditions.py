"""Tests for src/research_framework/pipeline/preconditions.py.

Performance note (2026-05-25, MONDAY §1.2 fix):
    Each test below calls ``check(tmp_vault_dir)`` on the initial-generate
    path (no ``for_resume=True``). Precondition 1's fallback would
    otherwise spawn ``pytest tests/scripts/`` once per test (because the
    test runner's CWD is the framework repo and the test vault doesn't
    ship its own ``scripts/tests/``). That cost ~16s × 5 ≈ 82s of
    fast-loop time for tests that don't actually exercise Precondition 1.

    The module-scoped autouse ``_skip_framework_tests_subprocess`` fixture
    monkeypatches ``_cwd_looks_like_framework_repo`` to return ``False``,
    which routes Precondition 1 into its "no scripts/tests/ in vault AND
    CWD is not the framework repo" no-op branch. The tests still validate
    preconditions 3, 4, 5 (structural files) which are the actual
    assertion targets. A future test that needs to exercise Precondition
    1's spawn path should override the fixture inside its own function
    scope (e.g. ``monkeypatch.setattr(preconditions, '_cwd_looks_like_framework_repo',
    lambda: True)``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.pipeline import preconditions
from research_framework.pipeline.preconditions import check


@pytest.fixture(autouse=True)
def _skip_framework_tests_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route Precondition 1 into its no-op fallback (see module docstring)."""
    monkeypatch.setattr(
        preconditions,
        "_cwd_looks_like_framework_repo",
        lambda: False,
    )


def test_missing_coverage_targets(tmp_vault_dir: Path) -> None:
    (tmp_vault_dir / "_pipeline" / "coverage-targets.json").unlink()
    ok, unmet = check(tmp_vault_dir)
    assert not ok
    assert any("coverage-targets" in m for m in unmet)


def test_missing_budget_log(tmp_vault_dir: Path) -> None:
    (tmp_vault_dir / "_pipeline" / "budget-log.md").unlink()
    ok, unmet = check(tmp_vault_dir)
    assert not ok
    assert any("budget-log" in m for m in unmet)


def test_missing_claude_md(tmp_vault_dir: Path) -> None:
    (tmp_vault_dir / "CLAUDE.md").unlink()
    ok, unmet = check(tmp_vault_dir)
    assert not ok
    assert any("CLAUDE.md" in m for m in unmet)


def test_claude_md_missing_naming_convention(tmp_vault_dir: Path) -> None:
    (tmp_vault_dir / "CLAUDE.md").write_text("# vault\nno convention declared\n")
    ok, unmet = check(tmp_vault_dir)
    assert not ok
    assert any("naming convention" in m for m in unmet)


def test_malformed_coverage_targets(tmp_vault_dir: Path) -> None:
    (tmp_vault_dir / "_pipeline" / "coverage-targets.json").write_text("not json")
    ok, unmet = check(tmp_vault_dir)
    assert not ok
    assert any("malformed" in m for m in unmet)
