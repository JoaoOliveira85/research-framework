"""Whichever kind of batch comes last, every note the cycle changed or wrote is
verified (spec 087, defect 6): an agent rewrites the shared research report on
each batch, so the pipeline keeps its own record of what each batch produced."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.pipeline.orchestrator import run_single_cycle
from tests._helpers import fake_agent
from tests.e2e.test_update_cycle import REL, _vault

pytestmark = pytest.mark.e2e


def _verified(vault: Path) -> dict[str, str]:
    doc = json.loads(
        (vault / "_pipeline/cycles/cycle-001-verifier.json").read_text("utf-8")
    )
    return {v["note_path"]: v["status"] for v in doc["verdicts"]}


def _written(vault: Path) -> list[str]:
    out: list[str] = []
    for b in sorted((vault / "_pipeline/cycles").glob("cycle-001-batch-*.json")):
        out += json.loads(b.read_text("utf-8")).get("notes_written", [])
    return out


def _order(vault: Path) -> list[str]:
    return [
        json.loads(b.read_text("utf-8")).get("kind", "new")
        for b in sorted((vault / "_pipeline/cycles").glob("cycle-001-batch-*.json"))
    ]


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, new_topics: str) -> Path:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    monkeypatch.setenv("FAKE_AGENT_VERIFIER_SCENARIO", "accept")
    monkeypatch.setenv(fake_agent.UPDATE_SCENARIO_ENV, "revised")
    monkeypatch.setenv(fake_agent.REPORT_REWRITE_ENV, "1")
    monkeypatch.setenv(fake_agent.SCOUT_NEW_ENV, new_topics)
    monkeypatch.setenv(
        fake_agent.SCOUT_UPDATES_ENV,
        json.dumps([{"note": "kafka-retries.md", "source_urls": ["https://e.org/x"]}]),
    )
    vault, spec, _ = _vault(tmp_path)
    settings = vault / "settings.yaml"
    settings.write_text(settings.read_text().replace("enabled: false", "enabled: true"))
    run_single_cycle(vault, cycle_num=1, budget_cap=10.0, max_cycles=1, spec=spec)
    return vault


def test_the_last_batch_is_an_update_batch_and_every_new_note_is_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _run(tmp_path, monkeypatch, "12")

    assert _order(vault)[-1] == "update"
    new = _written(vault)
    assert new, "the cycle wrote new notes"
    verdicts = _verified(vault)
    assert set(new) <= set(verdicts) and REL in verdicts
    assert {verdicts[n] for n in [*new, REL]} == {"verified"}


def test_the_last_batch_is_a_new_batch_and_every_updated_note_is_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _run(tmp_path, monkeypatch, "3")

    assert _order(vault)[-1] == "new"
    report = json.loads(
        (vault / "_pipeline/cycles/cycle-001-research.json").read_text()
    )
    assert report["notes_updated"] == [REL]  # the agent's last write had none
    verdicts = _verified(vault)
    assert verdicts[REL] == "verified"
    assert set(_written(vault)) <= set(verdicts)


def test_an_old_defect_is_recorded_not_rejected_when_the_last_batch_is_new(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real shape of defect 4: verifier on, an update to a note that carries
    an old deterministic violation, a new batch last."""
    from tests._helpers.vault_factory import commit_vault

    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    monkeypatch.setenv("FAKE_AGENT_VERIFIER_SCENARIO", "accept")
    monkeypatch.setenv(fake_agent.UPDATE_SCENARIO_ENV, "revised")
    monkeypatch.setenv(fake_agent.REPORT_REWRITE_ENV, "1")
    monkeypatch.setenv(fake_agent.SCOUT_NEW_ENV, "3")
    monkeypatch.setenv(
        fake_agent.SCOUT_UPDATES_ENV,
        json.dumps([{"note": "kafka-retries.md", "source_urls": ["https://e.org/x"]}]),
    )
    vault, spec, _ = _vault(tmp_path)
    settings = vault / "settings.yaml"
    settings.write_text(settings.read_text().replace("enabled: false", "enabled: true"))
    note = vault / REL
    note.write_text(
        note.read_text(encoding="utf-8").replace(
            "source_urls: [https://example.org/original]",
            "source_urls: [{url: https://example.org/original, credibility: bogus}]",
        ),
        encoding="utf-8",
    )
    commit_vault(vault)

    run_single_cycle(vault, cycle_num=1, budget_cap=10.0, max_cycles=1, spec=spec)

    assert _order(vault)[-1] == "new"
    assert _verified(vault)[REL] == "verified"
    sidecar = json.loads(
        (vault / "_pipeline/cycles/cycle-001-update-outcomes.json").read_text()
    )
    (row,) = sidecar["results"]
    assert row["status"] == "passed"
    assert [p["rule"] for p in row["pre_existing"]] == ["IX-credibility-malformed"]
    summary = (vault / "_pipeline/cycles/cycle-001-summary.md").read_text("utf-8")
    assert "1 note(s) carry older defects" in summary
