"""Tier 3: with the update share at zero the plan and its batches are what they
were before updates existed (spec 087 SC-006, T007), on the three committed
quality fixtures."""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest
import yaml

from research_framework.pipeline import backlog, research_plan
from research_framework.pipeline._helpers import scout_correction
from research_framework.pipeline.batch import slice_topics_into_batches
from research_framework.quality.runner import (
    REGISTERED_FIXTURES,
    isolate_fixture,
    resolve_fixture,
)
from research_framework.spec.parsed import load_parsed_spec
from research_framework.spec.schema import SpecConfig

# Everything at the top of tests/quality/ is tier-6 marked (the marker-isolation
# guard); this one is cheap, but it lives beside the harness it reads.
pytestmark = [pytest.mark.e2e, pytest.mark.slow]

_STAMP = re.compile(r"^generated_at: .*$", re.MULTILINE)


def _spec_and_vault(name: str, tmp_path: Path) -> tuple[SpecConfig, Path]:
    fixture = isolate_fixture(resolve_fixture(name), tmp_path)
    vault = fixture.vault_dir
    # the committed fixtures carry no pipeline ceiling (the harness passes one);
    # a settings file the loader refuses would hide the split behind defaults
    _edit_settings(vault, max_cycles=3, budget_usd=10.0)
    return SpecConfig.from_dict(load_parsed_spec(vault)), vault


def _edit_settings(vault: Path, **pipeline: object) -> None:
    path = vault / "settings.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc.setdefault("pipeline", {}).update(pipeline)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def _set_split(vault: Path, new: int, updates: int, discovery: int) -> None:
    _edit_settings(
        vault, cycle_split={"new": new, "updates": updates, "discovery": discovery}
    )


def _queue_updates(vault: Path, count: int) -> None:
    def seed(tx: backlog.Transaction) -> None:
        for i in range(count):
            tx.observe_update(f"note-{i}", "review_due", as_of=f"2020-01-{i + 1:02d}")

    assert backlog.update(vault, "review", seed)


def _plan_text(vault: Path, spec: SpecConfig) -> str:
    plan = research_plan.generate_plan(vault, spec, 1)
    return _STAMP.sub("generated_at: X", plan.to_markdown())


def _batches(vault: Path, spec: SpecConfig):
    plan = research_plan.generate_plan(vault, spec, 1)
    # the scout merges its topics into the queue after the plan is written
    scouted = [
        research_plan.PrioritizedTopic(
            title=f"Scouted {i}", category="c", priority_score=1.0, provenance="scout"
        )
        for i in range(12)
    ]
    plan = dataclasses.replace(
        plan,
        priority_queue=[
            *scouted,
            *scout_correction._parse_priority_queue_from_plan_md(plan.to_markdown()),
        ],
    )
    return [
        (b.batch_number, b.kind, [t.title for t in b.topics], b.updates)
        for b in slice_topics_into_batches(plan, 4)
    ]


@pytest.mark.parametrize("name", sorted(REGISTERED_FIXTURES))
def test_update_share_zero_plans_the_same_work_as_before(
    name: str, tmp_path: Path
) -> None:
    spec, vault = _spec_and_vault(name, tmp_path)
    baseline_plan = _plan_text(vault, spec)
    baseline_batches = _batches(vault, spec)
    assert "Update queue" not in baseline_plan
    assert baseline_batches, "the fixture plans some new-topic work"

    # open update entries exist, but the update share is zero
    _queue_updates(vault, 6)
    _set_split(vault, new=90, updates=0, discovery=10)
    assert len(backlog.update_topics(vault)) == 6
    assert _plan_text(vault, spec) == baseline_plan
    assert _batches(vault, spec) == baseline_batches

    # ... or the mode gives updates 0
    _set_split(vault, new=60, updates=30, discovery=10)
    bootstrap = dataclasses.replace(spec, research_mode="bootstrap")
    assert _plan_text(vault, bootstrap) == baseline_plan
    assert _batches(vault, bootstrap) == baseline_batches

    # no open update entries at all: the default split changes nothing either
    other_spec, other_vault = _spec_and_vault(name, tmp_path / "again")
    assert _plan_text(other_vault, other_spec) == baseline_plan

    # and the split really does something once there is a share and work
    _set_split(vault, new=0, updates=100, discovery=0)
    with_updates = research_plan.generate_plan(vault, spec, 1)
    assert with_updates.update_quota > 0
    assert len(with_updates.update_queue) > 0
    assert json.dumps(with_updates.to_dict()["update_quota"])
