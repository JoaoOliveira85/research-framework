"""Spec 083 T008: precondition 4 needs the state directory, not the budget log."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.pipeline import preconditions, state_layout
from research_framework.pipeline.preconditions import check


@pytest.fixture(autouse=True)
def _no_framework_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preconditions, "_cwd_looks_like_framework_repo", lambda: False)


def test_a_missing_budget_log_no_longer_blocks_a_run(tmp_vault_dir: Path) -> None:
    log = tmp_vault_dir / "_pipeline" / "budget-log.md"
    log.unlink()
    ok, unmet = check(tmp_vault_dir)
    assert not any("precondition 4" in m for m in unmet)
    assert log.read_text(encoding="utf-8").startswith("---\n_template_version: 1")
    assert "| Timestamp | Cycle |" in log.read_text(encoding="utf-8")


def test_a_missing_state_directory_still_blocks(tmp_vault_dir: Path) -> None:
    import shutil

    shutil.rmtree(state_layout.state_dir(tmp_vault_dir))
    _, unmet = check(tmp_vault_dir)
    assert any("precondition 4" in m and "state" in m for m in unmet)
