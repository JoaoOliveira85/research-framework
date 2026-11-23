"""A cycle whose scout reports NO new topics still works its updates (spec 087
US4, FR-017). The fake agent used to report new topics every time, which hid
that a real ``refresh`` scout (correctly) reports none and SG-001 then aborted
the cycle before a single update batch ran."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from research_framework.cli._budget_resolve import BudgetResolution
from research_framework.pipeline import backlog
from research_framework.pipeline.orchestrator import run_cycles, run_single_cycle
from tests._helpers import fake_agent
from tests.e2e.test_update_cycle import REL, _vault

pytestmark = pytest.mark.e2e


def _git(vault: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(vault), *args], check=True, capture_output=True, text=True
    ).stdout


def _gates(vault: Path) -> dict[str, str]:
    from research_framework.pipeline.step_gate_log import read_step_gates

    return {
        g.gate_id: g.status for g in read_step_gates(vault / "_pipeline" / "cycles", 1)
    }


def _healthy(vault: Path) -> None:
    """Make the fixture note a whole note (not a stub, template version set), so
    the loop's other fuel does not mask what these tests are about."""
    note = vault / REL
    text = note.read_text(encoding="utf-8")
    text = text.replace(
        "currency: current\n",
        'currency: current\ntemplate_version: "1.0.0"\nverifier_status: verified\n',
    )
    note.write_text(
        text + "\n" + "This note has a body of reasonable length. " * 12 + "\n"
    )


def _entry(vault: Path) -> dict[str, Any]:
    store = json.loads(
        (vault / "_pipeline/state/research-backlog.json").read_text("utf-8")
    )
    return next(e for e in store["entries"] if e["id"] == "update:kafka-retries")


def _prompts(vault: Path) -> list[str]:
    return [
        p.read_text(encoding="utf-8")
        for p in sorted((vault / "_pipeline/cycles").glob("cycle-001-batch-*-dfs.md"))
    ]


def test_a_refresh_cycle_with_a_scout_that_reports_no_new_topics_works_its_updates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    monkeypatch.setenv(fake_agent.SCOUT_NEW_ENV, "0")  # the scout finds nothing new
    monkeypatch.setenv(fake_agent.UPDATE_SCENARIO_ENV, "confirmed")
    vault, spec, _ = _vault(tmp_path, mode="refresh")
    _healthy(vault)
    _git(vault, "add", "-A", "-f")
    _git(
        vault,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@e.invalid",
        "commit",
        "-qm",
        "base",
    )
    before = int(_git(vault, "rev-list", "--all", "--count"))

    rc = run_cycles(
        spec,
        vault,
        budget=BudgetResolution(
            max_cycles=3,
            max_cycles_source="settings",
            max_usd=10.0,
            max_usd_source="settings",
        ),
    )

    assert rc == 0, "the cycle ran to a clean finish, not an SG-001 abort"
    assert _gates(vault)["SG-001"] == "PASS"  # no new topics were asked for
    prompts = _prompts(vault)
    assert prompts and all("\n## Update topics (JSON)\n" in p for p in prompts)
    assert not any("\n## Batch topics (JSON)\n" in p for p in prompts)
    entry = _entry(vault)
    assert (entry["status"], entry["outcome"]) == ("resolved", "confirmed")
    assert backlog.update_topics(vault) == []
    # and it was committed: the cycle's work is in history, the tree is clean
    assert int(_git(vault, "rev-list", "--all", "--count")) > before
    assert _git(vault, "log", "--all", "--format=%H", "--", REL).count("\n") >= 2
    assert _git(vault, "status", "--porcelain", "data_vault").strip() == ""


def test_an_expand_cycle_with_no_new_topics_still_works_its_updates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    monkeypatch.setenv(fake_agent.SCOUT_NEW_ENV, "0")
    monkeypatch.setenv("FAKE_AGENT_VERIFIER_SCENARIO", "accept")
    monkeypatch.setenv(fake_agent.UPDATE_SCENARIO_ENV, "revised")
    vault, spec, _ = _vault(tmp_path, mode="expand")
    _healthy(vault)
    _git(vault, "add", "-A", "-f")
    _git(
        vault, "-c", "user.name=t", "-c", "user.email=t@e.invalid", "commit", "-qm", "h"
    )

    rc = run_single_cycle(vault, cycle_num=1, budget_cap=10.0, max_cycles=1, spec=spec)

    assert rc != 2, "SG-001 must not abort a cycle that has update work"
    assert _gates(vault)["SG-001"] == "WARN"  # new topics were wanted, none came
    prompts = _prompts(vault)
    assert prompts and all("\n## Update topics (JSON)\n" in p for p in prompts)
    entry = _entry(vault)
    assert (entry["status"], entry["outcome"]) == ("resolved", "revised")
    report = json.loads(
        (vault / "_pipeline/cycles/cycle-001-research.json").read_text("utf-8")
    )
    assert report["notes_updated"] == [REL]
    assert report["update_work"]["worked"] == 1


def test_a_cycle_with_no_new_topics_and_nothing_to_update_still_aborts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate is not switched off: nothing to do is still a failure."""
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    monkeypatch.setenv(fake_agent.SCOUT_NEW_ENV, "0")
    vault, spec, _ = _vault(tmp_path, mode="expand")
    assert backlog.update(  # the note is not due and nothing is queued
        vault, "review", lambda tx: None
    )
    note = vault / REL
    note.write_text(note.read_text().replace("as_of: 2020-01-01", "as_of: 2099-01-01"))
    _git(vault, "add", "-A", "-f")
    _git(
        vault, "-c", "user.name=t", "-c", "user.email=t@e.invalid", "commit", "-qm", "x"
    )

    rc = run_single_cycle(vault, cycle_num=1, budget_cap=10.0, max_cycles=1, spec=spec)

    # nothing to do is still a failure: here the validator's trunk-seed check
    # (and, were that skipped, SG-001) stops the cycle before any batch
    assert rc == 2
    assert not _prompts(vault)


def test_update_only_cycles_stop_when_no_update_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What bounds a run of update-only cycles: a cycle that worked nothing that
    held is not fuel for another, so a note the writer cannot settle does not
    loop (and its attempts are counted toward being set aside)."""
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    monkeypatch.setenv(fake_agent.SCOUT_NEW_ENV, "0")
    monkeypatch.setenv(fake_agent.UPDATE_SCENARIO_ENV, "no_outcome")
    vault, spec, _ = _vault(tmp_path, mode="refresh")
    _healthy(vault)
    _git(vault, "add", "-A", "-f")
    _git(
        vault, "-c", "user.name=t", "-c", "user.email=t@e.invalid", "commit", "-qm", "b"
    )

    rc = run_cycles(
        spec,
        vault,
        budget=BudgetResolution(
            max_cycles=5,
            max_cycles_source="settings",
            max_usd=10.0,
            max_usd_source="settings",
        ),
    )

    assert rc != 2
    cycles = sorted((vault / "_pipeline/cycles").glob("cycle-00?-research.json"))
    assert len(cycles) == 1, "no second cycle on entries that could not be settled"
    entry = _entry(vault)
    assert entry["status"] == "open" and entry["attempts"] == 1


def test_an_update_to_a_note_with_an_old_defect_stands_and_counts_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The committed note already carries a citation with an invalid
    credibility level. The update adds no flaw, so it stands:
    the run exits 0, the entry resolves and the summary counts the older defect
    (spec 087, defect 4)."""
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "happy")
    monkeypatch.setenv(fake_agent.SCOUT_NEW_ENV, "0")
    monkeypatch.setenv("FAKE_AGENT_VERIFIER_SCENARIO", "accept")
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
    vault, spec, _ = _vault(tmp_path, mode="refresh")
    settings = vault / "settings.yaml"  # the verifier judges the update
    settings.write_text(settings.read_text().replace("enabled: false", "enabled: true"))
    _healthy(vault)
    note = vault / REL
    note.write_text(
        note.read_text(encoding="utf-8").replace(
            "source_urls: [https://example.org/original]",
            "source_urls: [{url: https://example.org/original, credibility: bogus}]",
        ),
        encoding="utf-8",
    )
    _git(vault, "add", "-A", "-f")
    _git(
        vault,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@e.invalid",
        "commit",
        "-qm",
        "base",
    )

    rc = run_cycles(
        spec,
        vault,
        budget=BudgetResolution(
            max_cycles=3,
            max_cycles_source="settings",
            max_usd=10.0,
            max_usd_source="settings",
        ),
    )

    assert rc == 0
    entry = _entry(vault)
    assert (entry["status"], entry["outcome"]) == ("resolved", "revised")
    report = json.loads(
        (vault / "_pipeline/cycles/cycle-001-research.json").read_text()
    )
    (row,) = report["update_outcome_results"]
    assert row["status"] == "passed"
    assert [p["rule"] for p in row["pre_existing"]] == ["IX-credibility-malformed"]
    summary = (vault / "_pipeline/cycles/cycle-001-summary.md").read_text("utf-8")
    assert "1 note(s) carry older defects" in summary
