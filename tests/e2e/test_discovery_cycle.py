"""Tier-5: the outside-in discovery pass inside a cycle (spec 088 User Stories
1, 2 and 3, SC-001, SC-004; T004)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from research_framework.pipeline import backlog, discovery
from research_framework.pipeline.orchestrator import run_single_cycle
from research_framework.spec.schema import NoteTypeConfig, ScopeConfig, SpecConfig
from tests._helpers import fake_agent
from tests._helpers.vault_factory import build_minimal_vault, commit_vault

pytestmark = pytest.mark.e2e

AREAS = ["Event-driven ingestion at scale", "Operating retry storms"]
NOTE = (
    "---\n"
    "type: concept\n"
    "summary: How retries behave\n"
    "coverage_category: {category}\n"
    "source_urls: [https://example.org/original]\n"
    "as_of: 2020-01-01\n"
    "currency: current\n"
    "---\n\n"
    "# Retry notes\n\nThe original body, unchanged since 2020.\n"
)
REL = "data_vault/01 - Concepts/retry-notes.md"
PROBE = "Zanzibar Quokka Handshake"  # shares no term with any note, label or area


def _vault(tmp_path: Path, *, split: str = "") -> tuple[Path, SpecConfig]:
    vault = build_minimal_vault(
        tmp_path,
        num_categories=1,
        num_targets_per_category=20,
        max_cycles=1,
        spec_overrides={
            "scope": ScopeConfig(
                domain="test-domain",
                organization="test-org",
                out_of_scope=["crypto"],
                boundaries=AREAS,
            ),
            "note_types": [
                NoteTypeConfig(
                    name="concept",
                    description="d",
                    folder="01 - Concepts",
                    min_word_count=30,
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
    if split:
        settings = vault / "settings.yaml"
        settings.write_text(
            settings.read_text(encoding="utf-8").replace(
                "pipeline:\n", f"pipeline:\n  cycle_split: {split}\n", 1
            ),
            encoding="utf-8",
        )
    commit_vault(vault)
    return vault, spec


def _scout(vault: Path) -> dict[str, Any]:
    path = vault / "_pipeline" / "cycles" / "cycle-001-scout.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _ledger(vault: Path) -> dict[str, Any]:
    return discovery.load_ledger(vault)


def _notes(vault: Path) -> list[str]:
    return sorted(p.stem for p in (vault / "data_vault").rglob("*.md"))


def test_a_topic_with_no_shared_term_is_dispatched_and_attributed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scout reports a topic no title, label or area shares a term with; it
    is planned with provenance ``discovery``, dispatched, written, and the
    cycle's record names the scope area that produced it (US1, SC-001)."""
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    monkeypatch.setenv(
        fake_agent.DISCOVERY_ENV, json.dumps({"new": [PROBE], "unassigned": True})
    )
    vault, spec = _vault(tmp_path)

    run_single_cycle(vault, cycle_num=1, budget_cap=10.0, max_cycles=1, spec=spec)

    # the scout was asked about the spec's areas, in the prompt it was given
    prompt = (
        vault / "_pipeline" / "cycles" / "cycle-001-scout-prompt.rendered.md"
    ).read_text(encoding="utf-8")
    assert "## Discovery pass" in prompt
    assert all(f"- {a}" in prompt for a in AREAS)
    assert _scout(vault)["topics_found"]["discovery"], "the fake reported rows"

    # planned with provenance discovery, ahead of the scout's own topics
    plan = (vault / "_pipeline" / "cycles" / "cycle-001-research-plan.md").read_text(
        encoding="utf-8"
    )
    queue = plan.split("## Priority queue")[1].split("## Exclusions")[0]
    first = next(line for line in queue.splitlines() if line.startswith("1."))
    assert PROBE in first and "· discovery ·" in first

    # dispatched: the note exists, and the backlog entry is resolved
    assert any("zanzibar" in stem.lower() for stem in _notes(vault))
    entry = next(
        e
        for e in json.loads(backlog.store_path(vault).read_text("utf-8"))["entries"]
        if e["title"] == PROBE
    )
    assert entry["origin"] == "discovery" and entry["scope_area"] == AREAS[0]

    # the ledger names the area, the kept row, and the dropped unassigned row
    ledger = _ledger(vault)
    (record,) = ledger["cycles"]
    assert record["assigned"] == AREAS
    assert record["topics"] == [{"title": PROBE, "area": AREAS[0]}]
    assert record["kept"] == 1 and record["rerouted"] == 0
    assert [d["title"] for d in record["dropped"]] == ["Unassigned Probe"]
    assert "not assigned" in record["dropped"][0]["reason"]
    assert ledger["areas"][AREAS[0]]["last_checked_cycle"] == 1
    assert ledger["areas"][AREAS[0]]["found_total"] == 1  # the scout's own count
    # ... and DG-001 recorded its warning with the scout's other gates
    gates = json.loads(
        (vault / "_pipeline" / "cycles" / "cycle-001-step-gates.json").read_text(
            "utf-8"
        )
    )
    assert {g["gate_id"]: g["status"] for g in gates}["DG-001"] == "WARN"


def test_a_finding_about_an_existing_note_becomes_one_update_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A row about a topic that already has a note never yields a second note:
    it becomes one ``new_material`` update entry carrying its source (US2,
    SC-004)."""
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    monkeypatch.setenv(fake_agent.UPDATE_SCENARIO_ENV, "revised")
    monkeypatch.setenv(
        fake_agent.DISCOVERY_ENV,
        json.dumps({"new": [], "existing": ["retry-notes"], "stale": True}),
    )
    vault, spec = _vault(tmp_path)

    run_single_cycle(vault, cycle_num=1, budget_cap=10.0, max_cycles=1, spec=spec)

    entries = {
        e["id"]: e
        for e in json.loads(backlog.store_path(vault).read_text("utf-8"))["entries"]
    }
    update = entries["update:retry-notes"]
    assert update["reason"] == "new_material"
    assert update["prompted_by"] == ["https://example.org/discovery/retry-notes"]
    assert not [e for e in entries.values() if e["origin"] == "discovery"]
    assert [s for s in _notes(vault) if "retry" in s] == ["retry-notes"]
    (record,) = _ledger(vault)["cycles"]
    assert record["rerouted"] == 1 and record["kept"] == 0
    assert [d["title"] for d in record["dropped"]] == ["Stale Probe"]
    assert "before the window" in record["dropped"][0]["reason"]


def test_a_report_with_no_discovery_keys_records_the_areas_as_not_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing reported: the areas are 'assigned, not reported', never advanced,
    and the cycle is not failed (FR-009)."""
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    monkeypatch.delenv(fake_agent.DISCOVERY_ENV, raising=False)
    vault, spec = _vault(tmp_path)

    code = run_single_cycle(
        vault, cycle_num=1, budget_cap=10.0, max_cycles=1, spec=spec
    )

    assert code in (0, 1)
    ledger = _ledger(vault)
    assert [ledger["areas"][a]["times_assigned_not_reported"] for a in AREAS] == [1, 1]
    assert all(ledger["areas"][a]["last_checked_cycle"] is None for a in AREAS)


def test_checked_with_nothing_found_is_recorded_as_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    monkeypatch.setenv(fake_agent.DISCOVERY_ENV, json.dumps({"new": []}))
    vault, spec = _vault(tmp_path)

    run_single_cycle(vault, cycle_num=1, budget_cap=10.0, max_cycles=1, spec=spec)

    ledger = _ledger(vault)
    for area in AREAS:
        row = ledger["areas"][area]
        assert (
            row["last_checked_cycle"],
            row["times_checked"],
            row["found_total"],
        ) == (
            1,
            1,
            0,
        )
    (record,) = ledger["cycles"]
    assert [r["found"] for r in record["reported"]] == [0, 0]
    assert all(r["queries"] for r in record["reported"])


def test_share_zero_runs_no_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    monkeypatch.setenv(fake_agent.DISCOVERY_ENV, json.dumps({"new": [PROBE]}))
    vault, spec = _vault(tmp_path, split="{new: 70, updates: 30, discovery: 0}")

    run_single_cycle(vault, cycle_num=1, budget_cap=10.0, max_cycles=1, spec=spec)

    prompt = (vault / "_pipeline" / "prompts" / "scout-prompt.md").read_text("utf-8")
    assert "Discovery pass" not in prompt
    assert not discovery.assignment_path(vault, 1).exists()
    assert not (vault / "_pipeline" / "state" / "discovery-ledger.json").exists()
    assert not [
        e
        for e in json.loads(backlog.store_path(vault).read_text("utf-8"))["entries"]
        if e["origin"] == "discovery"
    ]
