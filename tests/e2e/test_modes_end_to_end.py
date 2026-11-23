"""Tier-5: `research_mode` changes what a cycle dispatches (spec 087 User Story
4, FR-017; T013)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from research_framework.pipeline.orchestrator import run_single_cycle
from tests.e2e.test_update_cycle import _vault

pytestmark = pytest.mark.e2e


def _kinds(vault: Path) -> tuple[int, int]:
    """``(new-topic batches, update batches)`` the cycle's prompts show."""
    prompts = [
        p.read_text(encoding="utf-8")
        for p in sorted(
            (vault / "_pipeline" / "cycles").glob("cycle-001-batch-*-dfs.md")
        )
    ]
    new = sum(1 for p in prompts if "\n## Batch topics (JSON)\n" in p)
    update = sum(1 for p in prompts if "\n## Update topics (JSON)\n" in p)
    return new, update


def _run(tmp_path: Path, mode: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    vault, spec, _ = _vault(tmp_path / mode, mode=mode)
    run_single_cycle(vault, cycle_num=1, budget_cap=10.0, max_cycles=1, spec=spec)
    return vault


def test_refresh_runs_no_new_topic_batches_and_bootstrap_no_update_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    refresh = _run(tmp_path, "refresh", monkeypatch)
    new, update = _kinds(refresh)
    assert new == 0 and update >= 1  # the due note is worked, nothing new is written
    plan = (refresh / "_pipeline" / "research-plan.md").read_text(encoding="utf-8")
    assert re.search(r"^new_quota: 0$", plan, re.M)

    bootstrap = _run(tmp_path, "bootstrap", monkeypatch)
    new, update = _kinds(bootstrap)
    assert new >= 1 and update == 0  # the due note is queued, never worked
    plan = (bootstrap / "_pipeline" / "research-plan.md").read_text(encoding="utf-8")
    assert "Update queue" not in plan

    expand = _run(tmp_path, "expand", monkeypatch)
    new, update = _kinds(expand)
    assert new >= 1 and update >= 1  # the configured split: both
