"""Tier-5: a cycle revisits the notes the vault already has (spec 087 User
Stories 1 and 2, SC-001; T008)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from research_framework.pipeline import backlog
from research_framework.pipeline.orchestrator import run_single_cycle
from research_framework.spec.schema import NoteTypeConfig, SpecConfig
from research_framework.vault.frontmatter import parse_frontmatter_str
from tests._helpers import fake_agent
from tests._helpers.vault_factory import build_minimal_vault, commit_vault

pytestmark = pytest.mark.e2e

NOTE = (
    "---\n"
    "type: concept\n"
    "summary: How Kafka retries behave\n"
    "coverage_category: {category}\n"
    "source_urls: [https://example.org/original]\n"
    "as_of: 2020-01-01\n"
    "currency: current\n"
    "---\n\n"
    "# Kafka retries\n\nThe original body, unchanged since 2020.\n"
)
REL = "data_vault/01 - Concepts/kafka-retries.md"


def _vault(tmp_path: Path, *, mode: str = "expand") -> tuple[Path, SpecConfig, bytes]:
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
    note = vault / REL
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        NOTE.format(category=spec.coverage_targets.categories[0].name),
        encoding="utf-8",
    )
    commit_vault(vault)
    return vault, spec, note.read_bytes()


def _entry(vault: Path) -> dict[str, Any]:
    store = json.loads(
        (vault / "_pipeline" / "state" / "research-backlog.json").read_text("utf-8")
    )
    return next(e for e in store["entries"] if e["id"] == "update:kafka-retries")


def _report(vault: Path) -> dict[str, Any]:
    path = vault / "_pipeline" / "cycles" / "cycle-001-research.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_new_material_revises_the_note_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scout reports new material about a note the vault has; the cycle
    revises that note in place, cites the new source, and writes no second note
    (User Story 1, SC-001)."""
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    monkeypatch.setenv(fake_agent.UPDATE_SCENARIO_ENV, "revised")
    monkeypatch.setenv(
        fake_agent.SCOUT_UPDATES_ENV,
        json.dumps(
            [
                {
                    "note": "kafka-retries.md",
                    "source_urls": ["https://example.org/kafka-4"],
                    "summary": "4.0 changes the default",
                }
            ]
        ),
    )
    vault, spec, original = _vault(tmp_path)

    run_single_cycle(vault, cycle_num=1, budget_cap=10.0, max_cycles=1, spec=spec)

    entry = _entry(vault)
    assert entry["reason"] == "new_material"
    assert entry["prompted_by"] == ["https://example.org/kafka-4"]
    assert (entry["status"], entry["outcome"]) == ("resolved", "revised")
    # revised in place: same file, new body, the new source cited
    note = vault / REL
    assert note.read_bytes() != original
    fm, body = parse_frontmatter_str(note.read_text(encoding="utf-8"))
    assert "Revised by the fake agent" in body
    assert "https://example.org/original" in fm["source_urls"]
    assert any("new-source/kafka-retries" in u for u in fm["source_urls"])
    # no second note for the same topic
    stems = sorted(p.stem for p in (vault / "data_vault").rglob("*kafka-retries*.md"))
    assert stems == ["kafka-retries"]
    report = _report(vault)
    assert report["notes_updated"] == [REL]
    assert REL not in report["notes_created"]
    (result,) = report["update_outcome_results"]
    assert (result["note"], result["outcome"], result["status"]) == (
        "kafka-retries",
        "revised",
        "passed",
    )
    assert backlog.update_topics(vault) == []


@pytest.mark.parametrize(
    ("scenario", "closes", "outcome"),
    [
        ("confirmed", True, "confirmed"),
        ("revised", True, "revised"),
        ("superseded", True, "superseded"),
        ("retracted", True, "retracted"),
        ("no_outcome", False, None),
        ("retracted_lie", False, None),
    ],
)
def test_a_due_note_ends_in_exactly_one_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    closes: bool,
    outcome: str | None,
) -> None:
    """A note past its interval is queued by the sweep, worked, and ends in one
    outcome (User Story 2); one the writer cannot complete, or lies about, is
    restored and stays open."""
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    monkeypatch.setenv(fake_agent.UPDATE_SCENARIO_ENV, scenario)
    vault, spec, original = _vault(tmp_path)

    run_single_cycle(vault, cycle_num=1, budget_cap=10.0, max_cycles=1, spec=spec)

    entry = _entry(vault)
    assert entry["reason"] == "review_due"
    results = _report(vault)["update_outcome_results"]
    assert len(results) == 1
    if closes:
        assert (entry["status"], entry["outcome"]) == ("resolved", outcome)
        assert results[0]["status"] == "passed"
        assert backlog.update_topics(vault) == []
    else:
        assert entry["status"] == "open"
        assert "outcome" not in entry
        assert [r.stem for r in backlog.update_topics(vault)] == ["kafka-retries"]
        assert (vault / REL).read_bytes() == original  # restored from HEAD
        assert results[0]["status"] == "failed"
    # the cycle report says how the update batches ended
    summary = (vault / "_pipeline" / "cycles" / "cycle-001-summary.md").read_text(
        encoding="utf-8"
    )
    assert "Update outcomes" in summary
    # a confirmed outcome is content nowhere
    if scenario == "confirmed":
        assert _report(vault)["notes_updated"] == []


def test_the_research_report_lists_every_new_note_whatever_batch_wrote_last(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Update batches interleave with new ones and an agent rewrites the shared
    report on each batch; the cycle's notes_created must still be every new note
    (it fed the headline's "N notes drafted": 0 with six notes written)."""
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    monkeypatch.setenv(fake_agent.UPDATE_SCENARIO_ENV, "confirmed")
    monkeypatch.setenv(fake_agent.REPORT_REWRITE_ENV, "1")
    monkeypatch.setenv(
        fake_agent.SCOUT_UPDATES_ENV,
        json.dumps([{"note": "kafka-retries.md", "source_urls": ["https://e.org/x"]}]),
    )
    vault, spec, _ = _vault(tmp_path)

    run_single_cycle(vault, cycle_num=1, budget_cap=10.0, max_cycles=1, spec=spec)

    written: list[str] = []
    for batch in sorted((vault / "_pipeline/cycles").glob("cycle-001-batch-*.json")):
        written += json.loads(batch.read_text(encoding="utf-8")).get(
            "notes_written", []
        )
    assert written, "the cycle wrote new notes"
    assert sorted(_report(vault)["notes_created"]) == sorted(set(written))
