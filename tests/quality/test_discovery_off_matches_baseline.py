"""Tier 5: with the discovery share at zero the scout prompt, the plan and its
batches are what they were before the outside-in pass existed (spec 088 SC-003,
T004), on the three committed quality fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_framework.pipeline import backlog, discovery
from research_framework.pipeline.orchestrator import (
    _discovery_assignment,
    _render_cycle_scout_prompt,
)
from research_framework.quality.runner import REGISTERED_FIXTURES
from tests.quality.test_split_off_matches_baseline import (
    _batches,
    _plan_text,
    _set_split,
    _spec_and_vault,
)

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


def _prompt(vault: Path, spec) -> str:
    _render_cycle_scout_prompt(spec, vault, 1)
    return (vault / "_pipeline" / "prompts" / "scout-prompt.md").read_text("utf-8")


def _seed_discovery_topics(vault: Path) -> None:
    def seed(tx: backlog.Transaction) -> None:
        for i in range(4):
            tx.observe_topic(
                cycle=1,
                title=f"Found by discovery {i}",
                origin="discovery",
                scope_area="some area",
                source_urls=["https://example.org/x"],
            )

    assert backlog.update(vault, "scout", seed)


@pytest.mark.parametrize("name", sorted(REGISTERED_FIXTURES))
def test_share_zero_plans_the_same_work_as_before(name: str, tmp_path: Path) -> None:
    spec, vault = _spec_and_vault(name, tmp_path)
    baseline_plan = _plan_text(vault, spec)
    baseline_batches = _batches(vault, spec)
    assert baseline_batches, "the fixture plans some new-topic work"

    # discovery topics waiting in the backlog change neither the plan nor its
    # batches: the planner never offers them, only the discovery share does
    _seed_discovery_topics(vault)
    assert _plan_text(vault, spec) == baseline_plan
    assert _batches(vault, spec) == baseline_batches

    # with the share at 0 the cycle asks no areas and keeps no ledger
    _set_split(vault, new=70, updates=30, discovery=0)
    assert _discovery_assignment(vault, spec, 1) == ([], None)
    assert "Discovery pass" not in _prompt(vault, spec)
    assert not discovery.assignment_path(vault, 1).exists()
    assert not (vault / "_pipeline" / "state" / "discovery-ledger.json").exists()
    assert _plan_text(vault, spec) == baseline_plan
    assert _batches(vault, spec) == baseline_batches

    # a share above 0 is what turns the pass on (and only the prompt changes)
    _set_split(vault, new=60, updates=30, discovery=10)
    areas, start = _discovery_assignment(vault, spec, 1)
    if discovery.scope_areas(spec):
        assert areas and start
        assert "## Discovery pass" in _prompt(vault, spec)
    assert _plan_text(vault, spec) == baseline_plan
