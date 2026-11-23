"""Tier-5: a superseded note links its successor, stops counting, and `ask` is
told to follow it (spec 087 User Story 3, SC-004; T013)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline import backlog
from research_framework.pipeline.ask_escalation import render_ask_prompt
from research_framework.pipeline.coverage import currency_counts, recompute_from_disk
from research_framework.pipeline.orchestrator import run_single_cycle
from research_framework.vault.frontmatter import parse_frontmatter_str
from tests._helpers import fake_agent
from tests.e2e.test_update_cycle import REL, _vault

pytestmark = pytest.mark.e2e


def _met(vault: Path) -> int:
    (cat,) = recompute_from_disk(vault, persist=False).categories
    return cat.met_count


def test_a_superseded_note_links_its_successor_and_ask_follows_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    monkeypatch.setenv("FAKE_AGENT_VERIFIER_SCENARIO", "accept")
    monkeypatch.setenv(fake_agent.UPDATE_SCENARIO_ENV, "superseded")
    # a refresh cycle: only update work, so the one change to the note count is
    # the supersession itself
    vault, spec, _original = _vault(tmp_path, mode="refresh")
    settings = vault / "settings.yaml"  # the verifier judges the outcome
    settings.write_text(settings.read_text().replace("enabled: false", "enabled: true"))
    before = _met(vault)
    assert before == 1

    run_single_cycle(vault, cycle_num=1, budget_cap=10.0, max_cycles=1, spec=spec)

    old, _ = parse_frontmatter_str((vault / REL).read_text(encoding="utf-8"))
    assert old["currency"] == "superseded"
    (successor_ref,) = old["superseded_by"]
    successor_path = next((vault / "data_vault").rglob(f"{successor_ref}.md"))
    new, _ = parse_frontmatter_str(successor_path.read_text(encoding="utf-8"))
    assert new["supersedes"] == ["kafka-retries"]  # the link is symmetric
    assert new["currency"] == "current"
    # the verifier let it stand: the evidence is among the sources, corroborated
    assert old["verifier_status"] == "verified"
    assert any(
        isinstance(s, dict) and s["credibility"] == "corroborated"
        for s in old["source_urls"]
    )
    entry = next(
        e
        for e in json.loads(
            (vault / "_pipeline/state/research-backlog.json").read_text("utf-8")
        )["entries"]
        if e["id"] == "update:kafka-retries"
    )
    assert (entry["status"], entry["outcome"]) == ("resolved", "superseded")
    assert backlog.update_topics(vault) == []

    # SC-004: the superseded note no longer counts. The successor took its
    # place, so the count did not grow; with the old note counted it would be
    # one higher.
    assert _met(vault) == before
    (category,) = currency_counts(vault).values()
    assert category.uncountable == 1
    assert category.uncountable_notes == (REL,)
    (vault / REL).write_text(
        (vault / REL).read_text().replace("currency: superseded", "currency: current")
    )
    assert _met(vault) == before + 1

    # what `ask` is handed: the vault's own command, with the currency rule,
    # and notes whose frontmatter names the way to the successor
    command = (vault / ".claude" / "commands" / "ask.md").read_text(encoding="utf-8")
    prompt = render_ask_prompt(command, "How do Kafka retries behave?")
    assert "How do Kafka retries behave?" in prompt
    assert "Never present a superseded or retracted note as current" in prompt
    assert "follow its `superseded_by` to the successor" in prompt
    assert "answer from that note" in prompt
    assert "past its review interval" in prompt
    assert "`concept`: 30 days" in prompt
