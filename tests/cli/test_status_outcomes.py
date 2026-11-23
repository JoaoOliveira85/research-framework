"""Tier 4: ``./vault status`` shows the last cycle's update outcomes by kind
(spec 087 FR-019; T010)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_framework.cli import main
from research_framework.cli.status import build_status_json


def _vault(tmp_path: Path, results: list[dict]) -> Path:
    vault = tmp_path / "vault"
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)
    (cycles / "cycle-001-summary.md").write_text("cycle 1: PASS\n", encoding="utf-8")
    (cycles / "cycle-002-summary.md").write_text("cycle 2: PASS\n", encoding="utf-8")
    (cycles / "cycle-001-update-outcomes.json").write_text(
        json.dumps(
            {
                "cycle": 1,
                "results": [{"note": "old", "status": "passed", "outcome": "revised"}],
            }
        )
    )
    (cycles / "cycle-002-update-outcomes.json").write_text(
        json.dumps({"cycle": 2, "results": results})
    )
    return vault


RESULTS = [
    {"note": "a", "status": "passed", "outcome": "confirmed"},
    {"note": "b", "status": "passed", "outcome": "confirmed"},
    {"note": "c", "status": "passed", "outcome": "revised"},
    {"note": "d", "status": "passed", "outcome": "superseded"},
    {"note": "e", "status": "failed", "outcome": "retracted", "reason": "no reason"},
]


def test_status_shows_the_last_cycles_outcomes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = _vault(tmp_path, RESULTS)

    doc = build_status_json(vault)
    assert doc["update_outcomes"] == {
        "cycle": 2,
        "confirmed": 2,
        "revised": 1,
        "superseded": 1,
        "retracted": 0,
        "failed": 1,
    }

    assert main(["status", "--vault", str(vault)]) == 0
    text = capsys.readouterr().out
    assert (
        "update outcomes (cycle 2): confirmed 2, revised 1, superseded 1, "
        "retracted 0, failed 1"
    ) in text

    assert main(["status", "--vault", str(vault), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["update_outcomes"]["failed"] == 1


def test_status_has_no_outcomes_line_for_a_cycle_without_updates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = tmp_path / "vault"
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)
    (cycles / "cycle-001-summary.md").write_text("cycle 1: PASS\n", encoding="utf-8")

    assert build_status_json(vault)["update_outcomes"] is None
    main(["status", "--vault", str(vault)])
    assert "update outcomes" not in capsys.readouterr().out
