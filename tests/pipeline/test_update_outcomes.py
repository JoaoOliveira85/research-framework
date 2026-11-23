"""UG-001: update outcomes are checked against HEAD (spec 087 FR-005, FR-011,
FR-012, FR-014; T008)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from research_framework.pipeline import backlog, update_outcomes
from research_framework.pipeline.research_plan import UpdateTopic
from research_framework.vault.frontmatter import parse_frontmatter_str
from tests._helpers import fake_agent
from tests._helpers.vault_factory import build_minimal_vault, commit_vault

NOTE = (
    "---\n"
    "type: concept\n"
    "summary: How Kafka retries behave\n"
    "coverage_category: cat_a\n"
    "source_urls: [https://example.org/original]\n"
    "as_of: 2020-01-01\n"
    "currency: current\n"
    "---\n\n"
    "# Kafka retries\n\nThe original body, unchanged since 2020.\n"
)


def _vault(tmp_path: Path, stems: tuple[str, ...] = ("kafka-retries",)):
    vault = build_minimal_vault(tmp_path, num_categories=1, max_cycles=1)
    folder = vault / "data_vault" / "01 - Concepts"
    folder.mkdir(parents=True, exist_ok=True)
    topics = []
    for stem in stems:
        (folder / f"{stem}.md").write_text(NOTE, encoding="utf-8")
        topics.append(
            UpdateTopic(
                stem=stem,
                path=f"data_vault/01 - Concepts/{stem}.md",
                reason="review_due",
                as_of="2020-01-01",
            )
        )
    commit_vault(vault)
    assert backlog.update(
        vault,
        "review",
        lambda tx: [
            tx.observe_update(t.stem, "review_due", as_of="2020-01-01") for t in topics
        ],
    )
    return vault, topics


def _run(
    vault: Path,
    topics: list[UpdateTopic],
    scenario: str,
    monkeypatch: pytest.MonkeyPatch,
) -> update_outcomes.BatchOutcomes:
    monkeypatch.setenv(fake_agent.UPDATE_SCENARIO_ENV, scenario)
    spec_parse = fake_agent._load_spec_parse(vault)
    fake_agent.process_update_batch(
        vault, [t.to_dict() for t in topics], 1, spec_parse=spec_parse
    )
    cycles = vault / "_pipeline" / "cycles"
    return update_outcomes.apply_batch(
        vault, cycles, cycles / "cycle-001-research.json", 1, topics
    )


def _report(vault: Path) -> dict[str, Any]:
    path = vault / "_pipeline" / "cycles" / "cycle-001-research.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _entry(vault: Path, stem: str) -> dict[str, Any]:
    store = json.loads(
        (vault / "_pipeline" / "state" / "research-backlog.json").read_text("utf-8")
    )
    return next(e for e in store["entries"] if e["id"] == f"update:{stem}")


@pytest.mark.parametrize(
    ("scenario", "holds", "why"),
    [
        ("confirmed", True, ""),
        ("confirmed_lie", False, "the body differs from HEAD"),
        ("revised", True, ""),
        ("revised_lie", False, "no source_urls entry was added"),
        ("superseded", True, ""),
        ("superseded_lie", False, "superseded_by is empty"),
        ("retracted", True, ""),
        ("retracted_lie", False, "no retraction_reason is recorded"),
        ("no_outcome", False, "no outcome was reported"),
    ],
)
def test_each_outcome_is_checked_against_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    holds: bool,
    why: str,
) -> None:
    vault, topics = _vault(tmp_path)

    judged = _run(vault, topics, scenario, monkeypatch)

    (verdict,) = judged.verdicts
    assert verdict.ok is holds, verdict.reason
    assert judged.gate.gate_id == "UG-001"
    assert judged.gate.status == ("PASS" if holds else "FAIL")
    if not holds:
        assert why in verdict.reason
        assert "kafka-retries" in judged.gate.correction_hint


def test_a_note_that_never_existed_at_head_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, topics = _vault(tmp_path)
    ghost = UpdateTopic(
        stem="ghost",
        path="data_vault/01 - Concepts/ghost.md",
        reason="review_due",
    )
    (vault / ghost.path).write_text(NOTE, encoding="utf-8")  # on disk, not at HEAD

    judged = _run(vault, [*topics, ghost], "confirmed", monkeypatch)

    by_stem = {v.stem: v for v in judged.verdicts}
    assert by_stem["kafka-retries"].ok
    assert not by_stem["ghost"].ok
    assert "did not exist at HEAD" in by_stem["ghost"].reason


def test_a_stale_as_of_fails_every_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, topics = _vault(tmp_path)
    monkeypatch.setenv(fake_agent.UPDATE_SCENARIO_ENV, "revised")
    fake_agent.process_update_batch(
        vault,
        [t.to_dict() for t in topics],
        1,
        spec_parse=fake_agent._load_spec_parse(vault),
    )
    note = vault / topics[0].path
    note.write_text(
        note.read_text(encoding="utf-8").replace(
            datetime.now(UTC).date().isoformat(), "2021-05-05"
        ),
        encoding="utf-8",
    )

    (verdict,) = update_outcomes.evaluate(
        vault, topics, _report(vault)["update_outcomes"]
    )

    assert not verdict.ok and "as_of is not today" in verdict.reason


def test_a_failed_outcome_restores_the_note_and_leaves_the_entry_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, topics = _vault(tmp_path, ("lies", "honest"))
    original = (vault / topics[0].path).read_bytes()

    # one liar, one honest note, in one batch
    monkeypatch.setenv(fake_agent.UPDATE_SCENARIO_ENV, "revised")
    spec_parse = fake_agent._load_spec_parse(vault)
    fake_agent.process_update_batch(
        vault, [t.to_dict() for t in topics], 1, spec_parse=spec_parse
    )
    # the first note's source never got added: a lying `revised`
    lying = vault / topics[0].path
    lying.write_text(
        lying.read_text(encoding="utf-8").replace(
            "https://synthetic.test/new-source/lies", "https://example.org/original"
        ),
        encoding="utf-8",
    )
    cycles = vault / "_pipeline" / "cycles"
    judged = update_outcomes.apply_batch(
        vault, cycles, cycles / "cycle-001-research.json", 1, topics
    )

    assert [v.ok for v in judged.verdicts] == [False, True]
    assert judged.gate.status == "FAIL"
    assert (vault / topics[0].path).read_bytes() == original  # restored from HEAD
    assert (vault / topics[1].path).read_bytes() != original  # the honest one stands
    assert _entry(vault, "lies")["status"] == "open"
    assert "outcome" not in _entry(vault, "lies")
    # the failed attempt is counted and its reason remembered (it will be set
    # aside after pipeline.update_max_attempts of them)
    assert _entry(vault, "lies")["attempts"] == 1
    assert (
        "no source_urls entry was added"
        in _entry(vault, "lies")["last_failure"]["reason"]
    )
    assert "attempts" not in _entry(vault, "honest")
    closed = _entry(vault, "honest")
    assert (closed["status"], closed["outcome"], closed["outcome_cycle"]) == (
        "resolved",
        "revised",
        1,
    )
    assert [r.stem for r in backlog.update_topics(vault)] == ["lies"]
    results = {r["note"]: r["status"] for r in _report(vault)["update_outcome_results"]}
    assert results == {"lies": "failed", "honest": "passed"}


def test_confirmed_moves_as_of_and_counts_as_no_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, topics = _vault(tmp_path)
    head_body = parse_frontmatter_str(NOTE)[1]

    judged = _run(vault, topics, "confirmed", monkeypatch)

    assert judged.gate.status == "PASS"
    fm, body = parse_frontmatter_str((vault / topics[0].path).read_text("utf-8"))
    assert body == head_body
    assert str(fm["as_of"]) == datetime.now(UTC).date().isoformat()
    report = _report(vault)
    # counted nowhere as content ...
    assert report["notes_created"] == []
    assert report["notes_updated"] == []
    batch_like = [v for v in judged.verdicts if v.outcome != "confirmed"]
    assert batch_like == []
    # ... but the sources it consulted are recorded, on the report and the entry
    (result,) = report["update_outcome_results"]
    assert result["status"] == "passed"
    assert result["sources_consulted"] == [
        "https://synthetic.test/update/kafka-retries"
    ]
    assert _entry(vault, "kafka-retries")["outcome"] == "confirmed"


def test_notes_updated_is_derived_from_the_passing_non_confirmed_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, topics = _vault(tmp_path)
    monkeypatch.setenv(fake_agent.UPDATE_SCENARIO_ENV, "revised")

    # the writer also claims a note it never touched, and files the assigned one
    # under notes_created: neither survives the derivation
    spec_parse = fake_agent._load_spec_parse(vault)
    fake_agent.process_update_batch(
        vault, [t.to_dict() for t in topics], 1, spec_parse=spec_parse
    )
    cycles = vault / "_pipeline" / "cycles"
    path = cycles / "cycle-001-research.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["notes_updated"] = ["data_vault/01 - Concepts/untouched.md", topics[0].path]
    doc["notes_created"] = [topics[0].path]
    path.write_text(json.dumps(doc), encoding="utf-8")

    update_outcomes.apply_batch(vault, cycles, path, 1, topics)

    final = _report(vault)
    assert final["notes_updated"] == [topics[0].path]
    assert final["notes_created"] == []
