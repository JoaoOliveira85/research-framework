"""Spec 084 T010 / acceptance 12: the scout prompt describes the backlog view."""

from __future__ import annotations

import re
from pathlib import Path

from research_framework.generator.scaffold import scaffold
from research_framework.generator.templates import render_all
from research_framework.pipeline import backlog
from research_framework.spec.simple import load as load_spec


def _view_with_every_section(vault: Path) -> str:
    def _fill(tx: backlog.Transaction) -> None:
        tx.observe_topic(
            cycle=1, title="Cited", origin="harvest", citation_count=2, cited_from=["a"]
        )
        tx.observe_topic(cycle=1, title="Flagged", origin="researcher")
        tx.observe_quarantine(stem="bad", kind="rewrite", detail="why")

    assert backlog.update(vault, "harvest", _fill)
    assert backlog.update(
        vault,
        "propose",
        lambda tx: tx.observe_topic(cycle=1, title="Tangent", origin="proposal"),
    )
    return backlog.view_path(vault).read_text(encoding="utf-8")


def test_prompt_names_the_views_sections_not_the_retired_blocks(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    spec = load_spec(sample_spec_path)
    vault = tmp_path / "vault"
    scaffold(spec, vault)
    render_all(spec, vault)
    prompt = (vault / "_pipeline" / "prompts" / "scout-prompt.md").read_text("utf-8")
    view = _view_with_every_section(vault)

    headings = re.findall(r"^## (.+)$", view, flags=re.MULTILINE)
    assert "Follow-on topics (harvest)" in headings
    assert "Quarantined notes" in headings
    for heading in headings:
        assert f"**{heading}**" in prompt, heading
    # The view's own sections appear in the order the prompt lists them.
    positions = [prompt.index(f"**{h}**") for h in headings]
    assert positions == sorted(positions)
    # The operator and migrated sections exist even when this store has none.
    assert "**Added by the operator**" in prompt
    assert "**Carried over from the old backlog**" in prompt
    # The retired comment-delimited blocks are gone.
    for retired in ("managed blocks", "Harvest — cycle", "topic-harvest", "cycle N"):
        assert retired not in prompt, retired
