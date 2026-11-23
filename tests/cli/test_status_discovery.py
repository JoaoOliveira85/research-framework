"""Tier 4: ``./vault status`` and the cycle summary say which scope areas the
last cycle checked and what became of the rows (spec 088 FR-010; T005)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.cli import main
from research_framework.cli.status import build_status_json
from research_framework.pipeline import discovery
from research_framework.pipeline.cycle_summary import write_summary


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)
    for n in (1, 2):
        (cycles / f"cycle-{n:03d}-summary.md").write_text(
            f"cycle {n}: PASS\n", encoding="utf-8"
        )
    discovery.record_cycle(
        vault,
        cycle=1,
        assigned=["old area"],
        reported=[{"area": "old area", "queries": ["q"], "found": 5}],
        kept=5,
        rerouted=0,
        dropped=[],
    )
    discovery.record_cycle(
        vault,
        cycle=2,
        assigned=["Streaming ingestion", "Retry storms", "Schema drift"],
        reported=[
            {"area": "Streaming ingestion", "queries": ["q1"], "found": 3},
            {"area": "Retry storms", "queries": ["q2"], "found": 0},
        ],
        kept=1,
        rerouted=2,
        dropped=[{"title": "T", "reason": "no source"}],
    )
    return vault


def test_status_names_the_areas_checked_and_the_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path)

    assert build_status_json(vault)["discovery"] == {
        "cycle": 2,
        "checked": ["Streaming ingestion", "Retry storms"],
        "not_reported": ["Schema drift"],
        "kept": 1,
        "rerouted": 2,
        "dropped": 1,
    }

    assert main(["status", "--vault", str(vault)]) == 0
    text = capsys.readouterr().out
    assert (
        "discovery (cycle 2): checked 2 scope area(s) "
        "[Streaming ingestion; Retry storms], kept 1, re-routed to updates 2, "
        "dropped 1; not reported: Schema drift"
    ) in text

    assert main(["status", "--vault", str(vault), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["discovery"]["rerouted"] == 2


def test_a_cycle_with_no_pass_shows_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path)
    (vault / "_pipeline" / "cycles" / "cycle-003-summary.md").write_text(
        "cycle 3: PASS\n", encoding="utf-8"
    )
    assert build_status_json(vault)["discovery"] is None
    assert main(["status", "--vault", str(vault)]) == 0
    assert "discovery (" not in capsys.readouterr().out


def test_an_unreadable_ledger_never_fails_status(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    from research_framework.pipeline import state_layout

    state_layout.discovery_ledger_path(vault).write_text("{broken", encoding="utf-8")
    assert build_status_json(vault)["discovery"] is None


def test_the_cycle_summary_carries_the_same_line(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    path = write_summary(vault, 2, exit_code=0)
    text = path.read_text(encoding="utf-8")
    assert "- discovery (cycle 2): checked 2 scope area(s)" in text
    assert "not reported: Schema drift" in text
    assert "discovery (" not in write_summary(vault, 3, exit_code=0).read_text(
        encoding="utf-8"
    )
