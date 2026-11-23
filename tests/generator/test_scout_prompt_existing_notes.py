"""Tier 3: the scout prompt reports on existing notes instead of skipping them
(spec 087 FR-001, T005)."""

from __future__ import annotations

from pathlib import Path

from research_framework.generator.templates import render_scout_prompt
from research_framework.spec.parser import parse

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "specs"
    / "code-first-vault-spec.md"
)


def _prompt(tmp_path: Path, **lists: list[str]) -> str:
    vault = tmp_path / "vault"
    (vault / "_pipeline" / "prompts").mkdir(parents=True)
    path = render_scout_prompt(parse(FIXTURE), vault, **lists)
    return path.read_text(encoding="utf-8")


def test_existing_notes_are_reported_against_not_skipped(tmp_path: Path) -> None:
    prompt = _prompt(
        tmp_path,
        existing_notes=["Kafka Streams.md", "Outbox Pattern.md"],
        rejected_topics=["Thermodynamics"],
    )

    assert "Already covered — skip these" not in prompt
    assert "## Already have a note" in prompt
    assert "never a second note" in prompt
    assert "topics_found.updates" in prompt
    assert "- Kafka Streams.md" in prompt and "- Outbox Pattern.md" in prompt
    # the operator's rejects have their own, separate, skip list
    skip = prompt.split("## Rejected by the operator — skip these")[1].split("\n## ")[0]
    assert "- Thermodynamics" in skip
    assert "Kafka Streams.md" not in skip
    have = prompt.split("## Already have a note")[1].split("\n## ")[0]
    assert "Thermodynamics" not in have


def test_the_output_section_documents_the_updates_rows(tmp_path: Path) -> None:
    prompt = _prompt(tmp_path)

    assert '"updates"' in prompt
    assert '"note": "<existing note filename or stem>"' in prompt
    assert "## Already have a note" not in prompt
    assert "## Rejected by the operator" not in prompt


def test_the_two_lists_render_independently(tmp_path: Path) -> None:
    only_rejects = _prompt(tmp_path, rejected_topics=["Thermodynamics"])
    assert "## Rejected by the operator — skip these" in only_rejects
    assert "## Already have a note" not in only_rejects
