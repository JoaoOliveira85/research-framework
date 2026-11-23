"""Update work in the plan and the batch loop (spec 087 FR-004, FR-005a; T007)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from research_framework.pipeline import backlog
from research_framework.pipeline._helpers import _scout_prompts, scout_correction
from research_framework.pipeline.batch import slice_topics_into_batches
from research_framework.pipeline.orchestrator import run_single_cycle
from research_framework.pipeline.research_plan import (
    PrioritizedTopic,
    ResearchPlan,
    UpdateTopic,
)
from research_framework.spec.schema import NoteTypeConfig, SpecConfig
from tests._helpers.vault_factory import build_minimal_vault


def _plan(**kwargs: Any) -> ResearchPlan:
    base: dict[str, Any] = {
        "cycle_number": 2,
        "generated_at": "2026-11-23T08:00:00Z",
        "framework_version": "x",
        "coverage_state": [],
        "priority_queue": [
            PrioritizedTopic(title="Alpha", category="concepts", priority_score=0.9),
            PrioritizedTopic(title="Beta", category="concepts", priority_score=0.8),
        ],
        "cycle_focus": ["concepts"],
        "cycle_quota": 10,
        "exclusions": ["already-covered: kafka-streams"],
    }
    return ResearchPlan(**{**base, **kwargs})


UPDATES = [
    UpdateTopic(
        stem="kafka-streams",
        path="data_vault/01 - Concepts/kafka-streams.md",
        reason="new_material",
        as_of="2025-01-01",
        prompted_by=("https://a.example/x", "https://b.example/y"),
    ),
    UpdateTopic(
        stem="outbox",
        path="",
        reason="review_due",
        as_of=None,
        prompted_by=(),
    ),
]


def test_plan_round_trips_its_update_queue_through_markdown() -> None:
    plan = _plan(update_queue=list(UPDATES), new_quota=7, update_quota=3)

    text = plan.to_markdown()
    back = ResearchPlan.from_markdown(text)

    assert back.update_queue == UPDATES
    assert (back.new_quota, back.update_quota) == (7, 3)
    assert back.exclusions == ["already-covered: kafka-streams"]
    # the priority queue still round-trips through its own parser, unchanged
    assert [
        t.title for t in scout_correction._parse_priority_queue_from_plan_md(text)
    ] == [
        "Alpha",
        "Beta",
    ]
    # and writing the parsed plan again is stable (the scout merge does this)
    import dataclasses

    again = dataclasses.replace(
        back,
        priority_queue=scout_correction._parse_priority_queue_from_plan_md(text),
    )
    assert again.to_markdown() == text
    assert "## Update queue" in text
    assert text.index("## Exclusions") < text.index("## Update queue")


def test_a_plan_without_update_work_is_written_as_before() -> None:
    plain = _plan().to_markdown()
    assert "Update queue" not in plain
    assert "update_quota" not in plain
    # an update queue with no share is not written either
    assert _plan(update_queue=list(UPDATES), update_quota=0).to_markdown() == plain
    back = ResearchPlan.from_markdown(plain)
    assert back.update_queue == [] and back.update_quota == 0


def test_slicing_cuts_update_batches_from_the_update_queue_oldest_first() -> None:
    updates = [
        UpdateTopic(
            stem=f"n{i}", path="", reason="review_due", as_of=f"2020-01-{i:02d}"
        )
        for i in range(1, 9)
    ]
    plan = _plan(update_queue=updates, new_quota=6, update_quota=4)

    batches = slice_topics_into_batches(plan, 3, new_count=2, update_count=4)

    new = [b for b in batches if b.kind == "new"]
    upd = [b for b in batches if b.kind == "update"]
    assert [t.title for b in new for t in b.topics] == ["Alpha", "Beta"]
    assert [u.stem for b in upd for u in b.updates] == ["n1", "n2", "n3", "n4"]
    assert [b.batch_number for b in batches] == list(range(1, len(batches) + 1))
    assert all(b.kind == "update" for b in batches[len(new) :])
    # without an update count the slicing is the old one
    old = slice_topics_into_batches(_plan(), 3)
    assert all(b.kind == "new" for b in old)
    assert slice_topics_into_batches(plan, 3) == slice_topics_into_batches(
        plan, 3, update_count=0
    )


# ---------------------------------------------------------------------------
# The update batch prompt
# ---------------------------------------------------------------------------


def test_the_update_prompt_exempts_its_notes_from_the_binding_exclusions(
    tmp_path: Path,
) -> None:
    dfs = tmp_path / "dfs.md"
    dfs.write_text("DFS {CYCLE_NUM}\n", encoding="utf-8")
    dest = tmp_path / "batch.md"
    exclusions = [
        "already-covered: kafka-streams",
        "already-covered: Other Note",
        "out-of-scope: crypto",
    ]

    _scout_prompts._render_batch_note_writer_prompt(
        dfs_prompt_src=dfs,
        dest=dest,
        cycle_num=3,
        scout_report=tmp_path / "scout.json",
        research_report=tmp_path / "research.json",
        batch_topics=[],
        correction_directive="",
        exclusions=exclusions,
        update_topics=UPDATES,
    )
    text = dest.read_text(encoding="utf-8")

    assert "## Update topics (JSON)" in text
    assert "## Batch topics (JSON)" not in text
    payload = json.loads(re.search(r"```json\n(.*?)\n```", text, re.DOTALL).group(1))
    assert payload[0] == {
        "note": "kafka-streams",
        "path": "data_vault/01 - Concepts/kafka-streams.md",
        "reason": "new_material",
        "as_of": "2025-01-01",
        "prompted_by": ["https://a.example/x", "https://b.example/y"],
    }
    block = text.split("## Exclusions (binding)")[1]
    assert "do NOT forbid editing them" in block
    assert "No other existing note may be edited" in block
    assert "no second note for the same topic may be created" in block
    # the assigned note is no longer excluded; everything else still is
    assert "- already-covered: kafka-streams" not in block
    assert "- already-covered: Other Note" in block
    assert "- out-of-scope: crypto" in block

    # a new-topic batch renders as it always did
    _scout_prompts._render_batch_note_writer_prompt(
        dfs_prompt_src=dfs,
        dest=dest,
        cycle_num=3,
        scout_report=tmp_path / "scout.json",
        research_report=tmp_path / "research.json",
        batch_topics=[PrioritizedTopic("T", "c", 0.5)],
        correction_directive="",
        exclusions=exclusions,
    )
    plain = dest.read_text(encoding="utf-8")
    assert "## Batch topics (JSON)" in plain
    assert "Update topics" not in plain
    assert "- already-covered: kafka-streams" in plain


# ---------------------------------------------------------------------------
# The batch loop, end to end with the fake agent
# ---------------------------------------------------------------------------


def _vault_with_due_notes(tmp_path: Path, *, mode: str = "expand") -> tuple[Path, Any]:
    vault = build_minimal_vault(
        tmp_path,
        num_categories=1,
        num_targets_per_category=20,
        max_cycles=1,
        spec_overrides={
            "research_mode": mode,
            "note_types": [
                NoteTypeConfig(
                    name="concept",
                    description="d",
                    folder="01 - Concepts",
                    min_word_count=30,
                    review_after_days=30,
                )
            ],
        },
    )
    spec = SpecConfig.from_dict(
        json.loads((vault / "_pipeline" / "spec-parse.json").read_text("utf-8"))
    )
    folder = vault / "data_vault" / "01 - Concepts"
    folder.mkdir(parents=True, exist_ok=True)
    # as_of descends with the index so "oldest first" is the REVERSE of the
    # file order: n10 is the oldest, n01 the newest
    for i in range(1, 11):
        (folder / f"due-note-{i:02d}.md").write_text(
            "---\n"
            "type: concept\n"
            f"summary: Due note {i}\n"
            "source_urls: [https://example.org/s]\n"
            "coverage_category: " + spec.coverage_targets.categories[0].name + "\n"
            f"as_of: 2020-01-{11 - i:02d}\n"
            "currency: current\n"
            "---\n\n" + ("body " * 50) + "\n",
            encoding="utf-8",
        )
    return vault, spec


def _rendered_prompts(vault: Path) -> list[str]:
    cycles = vault / "_pipeline" / "cycles"
    return [
        p.read_text(encoding="utf-8")
        for p in sorted(cycles.glob("cycle-001-batch-*-dfs.md"))
    ]


def test_ten_due_notes_and_a_share_of_three_dispatch_exactly_three_oldest_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    vault, spec = _vault_with_due_notes(tmp_path)

    run_single_cycle(vault, cycle_num=1, budget_cap=10.0, max_cycles=1, spec=spec)

    assert len(backlog.update_topics(vault)) == 10  # the sweep queued all ten
    update_prompts = [p for p in _rendered_prompts(vault) if "## Update topics" in p]
    assert len(update_prompts) == 1
    block = re.search(
        r"## Update topics \(JSON\)\s*```json\n(.*?)\n```",
        update_prompts[0],
        re.DOTALL,
    )
    assert block is not None
    stems = [row["note"] for row in json.loads(block.group(1))]
    assert stems == ["due-note-10", "due-note-09", "due-note-08"]
    new_prompts = [p for p in _rendered_prompts(vault) if "## Batch topics" in p]
    assert new_prompts, "new-topic batches still run"
    plan = (vault / "_pipeline" / "research-plan.md").read_text(encoding="utf-8")
    assert "update_quota: 3" in plan
    assert "new_quota: 7" in plan


def test_an_update_batch_that_writes_no_new_file_is_not_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    # refresh: new topics 0, so the only batches are update batches, and the
    # midpoint "no new file" failure would have hit batch 1
    vault, spec = _vault_with_due_notes(tmp_path, mode="refresh")

    run_single_cycle(vault, cycle_num=1, budget_cap=10.0, max_cycles=1, spec=spec)

    batch_files = sorted(
        (vault / "_pipeline" / "cycles").glob("cycle-001-batch-[0-9][0-9][0-9].json")
    )
    assert batch_files
    for path in batch_files:
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["kind"] == "update"
        assert doc["notes_written"] == []
        assert doc["accepted"] is True, doc["sg_gate_results"]
        assert all(
            g["gate_id"] != "SG-005" or g["status"] != "FAIL"
            for g in doc["sg_gate_results"]
        )
        assert doc["correction_directive_in"] == ""
    # no "do not edit existing notes" text reached any update prompt
    for prompt in _rendered_prompts(vault):
        assert "Do NOT edit existing notes" not in prompt
        assert "do not edit existing notes" not in prompt
