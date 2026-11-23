"""Tier 5: one cycle with update work AND discovery topics dispatches new,
update and discovery work, each against its own share, interleaved per
``batch.interleave_kinds`` (spec 088 FR-007; spec 087 plan decision 8)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from research_framework.pipeline import backlog
from research_framework.pipeline.batch import interleave_kinds
from research_framework.pipeline.orchestrator import run_single_cycle
from tests._helpers import fake_agent
from tests.pipeline.test_update_batches import _vault_with_due_notes

pytestmark = pytest.mark.e2e

AREAS = ["Event-driven ingestion", "Operating retry storms"]
PROBES = ["Zanzibar Quokka Handshake", "Marmalade Tessellation Protocol"]


def _json_block(prompt: str, heading: str) -> list[dict]:
    match = re.search(
        rf"## {heading} \(JSON\)\s*```json\n(.*?)\n```", prompt, re.DOTALL
    )
    assert match is not None
    return json.loads(match.group(1))


def test_new_update_and_discovery_work_share_one_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    monkeypatch.setenv(fake_agent.DISCOVERY_ENV, json.dumps({"new": PROBES}))
    vault, spec = _vault_with_due_notes(tmp_path, notes=10, targets=20, batch_size=3)
    spec.scope.boundaries = AREAS

    run_single_cycle(vault, cycle_num=1, budget_cap=10.0, max_cycles=1, spec=spec)

    plan = (vault / "_pipeline" / "research-plan.md").read_text(encoding="utf-8")
    quota = int(re.search(r"^cycle_quota: (\d+)$", plan, re.MULTILINE).group(1))
    # 10% of the quota is the discovery credit: one whole slot at a quota of 10
    # (two topics were reported; the other waits in the backlog)
    assert quota == 10
    discovery_n = 1
    update_n = int(re.search(r"^update_quota: (\d+)$", plan, re.MULTILINE).group(1))
    assert update_n == 3  # 60:30 of the nine slots left
    assert [r.title for r in backlog.discovery_topics(vault)] == [PROBES[1]]

    cycles = vault / "_pipeline" / "cycles"
    prompts = [
        p.read_text(encoding="utf-8")
        for p in sorted(cycles.glob("cycle-001-batch-*-dfs.md"))
    ]
    kinds = ["update" if "\n## Update topics (JSON)\n" in p else "new" for p in prompts]
    assert kinds.count("update") >= 1 and kinds.count("new") >= 1
    # dispatched in the order the base's interleave gives for these counts
    assert kinds == interleave_kinds(kinds.count("new"), kinds.count("update"))

    # each kind against its own share: updates worked == update share, new
    # files written == the new-topic share plus the discovery topic
    update_stems = [
        row["note"]
        for p in prompts
        if "\n## Update topics (JSON)\n" in p
        for row in _json_block(p, "Update topics")
    ]
    assert len(update_stems) == update_n
    new_titles = [
        t["title"]
        for p in prompts
        if "\n## Batch topics (JSON)\n" in p
        for t in _json_block(p, "Batch topics")
    ]
    assert len(new_titles) == quota - update_n  # new share + discovery slot
    # the discovery topic leads the new topics
    assert new_titles[0] == PROBES[0]
    assert PROBES[1] not in new_titles
    report = json.loads((cycles / "cycle-001-research.json").read_text("utf-8"))
    assert report["update_work"]["worked"] == update_n
    created = [Path(n).stem.lower() for n in report["notes_created"]]
    assert any("zanzibar" in stem for stem in created)
    assert discovery_n == sum(1 for t in new_titles if t in PROBES)
