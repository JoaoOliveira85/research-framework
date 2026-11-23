"""Update work in the plan and the batch loop (spec 087 FR-004, FR-005a; T007)."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
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
from tests._helpers.vault_factory import build_minimal_vault, commit_vault


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
    # the kinds interleave (test_update_batches_are_interleaved_in_proportion);
    # within each kind the order is the queue's own
    assert [b.kind for b in batches] != ["new"] * len(new) + ["update"] * len(upd)
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


def _vault_with_due_notes(
    tmp_path: Path,
    *,
    mode: str = "expand",
    notes: int = 10,
    targets: int = 20,
    batch_size: int | None = None,
) -> tuple[Path, Any]:
    vault = build_minimal_vault(
        tmp_path,
        num_categories=1,
        num_targets_per_category=targets,
        max_cycles=1,
        note_writer_batch_size=batch_size,
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
    for i in range(1, notes + 1):
        (folder / f"due-note-{i:02d}.md").write_text(
            "---\n"
            "type: concept\n"
            f"summary: Due note {i}\n"
            "source_urls: [https://example.org/s]\n"
            "coverage_category: " + spec.coverage_targets.categories[0].name + "\n"
            f"as_of: {date(2020, 1, 11) - timedelta(days=i)}\n"
            "currency: current\n"
            "---\n\n" + ("body " * 50) + "\n",
            encoding="utf-8",
        )
    # UG-001 judges an update batch against HEAD
    commit_vault(vault)
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

    # the sweep queued all ten; the three worked ones (confirmed) are closed
    assert len(backlog.update_topics(vault)) == 7
    update_prompts = [
        p
        for p in _rendered_prompts(vault)
        if "\n## Update topics (JSON)\n" in p  # the block, not the DFS prose
    ]
    assert len(update_prompts) == 1
    block = re.search(
        r"## Update topics \(JSON\)\s*```json\n(.*?)\n```",
        update_prompts[0],
        re.DOTALL,
    )
    assert block is not None
    stems = [row["note"] for row in json.loads(block.group(1))]
    assert stems == ["due-note-10", "due-note-09", "due-note-08"]
    new_prompts = [
        p for p in _rendered_prompts(vault) if "\n## Batch topics (JSON)\n" in p
    ]
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


# ---------------------------------------------------------------------------
# Dispatch order follows the split (a cycle cut short has still worked updates)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("n_new", "n_update"),
    [
        (6, 3),
        (1, 3),
        (3, 1),
        (9, 1),
        (10, 2),
        (5, 5),
        (2, 7),
        (7, 2),
        (0, 4),
        (4, 0),
        (1, 1),
    ],
)
def test_update_batches_are_interleaved_in_proportion(
    n_new: int, n_update: int
) -> None:
    from math import ceil

    from research_framework.pipeline.batch import interleave_kinds

    order = interleave_kinds(n_new, n_update)
    total = n_new + n_update

    assert sorted(order) == sorted(["new"] * n_new + ["update"] * n_update)
    done = 0
    for i, kind in enumerate(order, start=1):
        done += kind == "update"
        # after ANY prefix each kind's share is within one batch of its overall share
        assert abs(done - i * n_update / total) < 1, (i, order)
    if n_update:
        first_update = order.index("update") + 1
        if n_update * 3 >= total:
            assert first_update == 1  # updates are a third or more: they lead
        else:
            assert first_update <= ceil(total / n_update)
    if not n_update:
        assert order == ["new"] * n_new  # exactly what it was before
    assert interleave_kinds(n_new, n_update) == order  # deterministic

    # through the slicer: numbers sequential in dispatch order, order kept within kinds
    updates = [
        UpdateTopic(stem=f"u{i:02d}", path="", reason="review_due", as_of="2020-01-01")
        for i in range(n_update * 3)
    ]
    queue = [
        PrioritizedTopic(title=f"T{i:02d}", category="c", priority_score=0.9 - i / 1000)
        for i in range(n_new * 3)
    ]
    plan = _plan(
        priority_queue=queue,
        update_queue=updates,
        cycle_quota=max(1, n_new * 3),
        new_quota=n_new * 3,
        update_quota=n_update * 3,
    )
    batches = slice_topics_into_batches(
        plan, 3, new_count=n_new * 3, update_count=n_update * 3
    )
    assert [b.batch_number for b in batches] == list(range(1, len(batches) + 1))
    assert [b.kind for b in batches] == order
    assert [t.title for b in batches if b.kind == "new" for t in b.topics] == [
        f"T{i:02d}" for i in range(n_new * 3)
    ]
    assert [u.stem for b in batches if b.kind == "update" for u in b.updates] == [
        f"u{i:02d}" for i in range(n_update * 3)
    ]


def _batch_prompts(vault: Path) -> list[str]:
    return _rendered_prompts(vault)


def test_a_cycle_cut_after_three_batches_has_worked_an_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    vault, spec = _vault_with_due_notes(tmp_path, notes=12, targets=60, batch_size=3)
    settings = vault / "settings.yaml"  # the cycle is stopped after three batches
    settings.write_text(
        settings.read_text().replace(
            "max_batches_per_cycle: 10", "max_batches_per_cycle: 3"
        )
    )

    run_single_cycle(vault, cycle_num=1, budget_cap=10.0, max_cycles=1, spec=spec)

    prompts = _batch_prompts(vault)
    assert len(prompts) == 3
    updated = [p for p in prompts if "\n## Update topics (JSON)\n" in p]
    assert updated, "a cut cycle must have worked an update batch"
    assert [p for p in prompts if "\n## Batch topics (JSON)\n" in p]
    first = (vault / "_pipeline/cycles/cycle-001-batch-001.json").read_text("utf-8")
    assert json.loads(first)["kind"] == "update"  # updates are over a third: they lead
    # and the update was settled, not left half done
    assert len(backlog.update_topics(vault)) < 12


def test_a_correction_for_a_new_batch_skips_over_an_update_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from research_framework.pipeline import batch as batch_mod

    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    # every new-topic batch is written without source_urls, so SG-005 fails it
    monkeypatch.setenv("FAKE_AGENT_NOTE_WRITER_SCENARIO", "fail_frontmatter")
    vault, spec = _vault_with_due_notes(tmp_path, notes=4, targets=40, batch_size=3)
    real = batch_mod.slice_topics_into_batches

    def new_update_new(*args: Any, **kwargs: Any) -> list[Any]:
        """Force the order N U N ... so a correction must hop over the update."""
        import dataclasses

        out = real(*args, **kwargs)
        news = [b for b in out if b.kind == "new"]
        ups = [b for b in out if b.kind == "update"]
        assert len(news) >= 2 and ups
        order = [news[0], ups[0], *news[1:], *ups[1:]]
        return [dataclasses.replace(b, batch_number=n) for n, b in enumerate(order, 1)]

    monkeypatch.setattr(batch_mod, "slice_topics_into_batches", new_update_new)

    run_single_cycle(vault, cycle_num=1, budget_cap=10.0, max_cycles=1, spec=spec)

    cycles = vault / "_pipeline" / "cycles"
    first_new, update, second_new = (
        json.loads((cycles / f"cycle-001-batch-{n:03d}.json").read_text("utf-8"))
        for n in (1, 2, 3)
    )
    assert (first_new.get("kind"), update["kind"], second_new.get("kind")) == (
        None,
        "update",
        None,
    )
    assert first_new["accepted"] is False  # SG-005: no source_urls
    assert first_new["correction_directive_in"] == ""
    # the update batch never sees a new batch's correction ...
    assert update["correction_directive_in"] == ""
    assert "## Correction directive" not in (
        cycles / "cycle-001-batch-002-dfs.md"
    ).read_text("utf-8")
    # ... and the next NEW batch still does, though an update sat between them
    assert second_new["correction_directive_in"].strip()
    assert "## Correction directive" in (
        cycles / "cycle-001-batch-003-dfs.md"
    ).read_text("utf-8")
