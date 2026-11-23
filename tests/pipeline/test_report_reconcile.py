"""The pipeline's own record of a cycle's notes (spec 087, defect 6)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from research_framework.pipeline import verifier
from research_framework.pipeline.report_reconcile import CycleRecord, normalise_notes
from research_framework.pipeline.verifier import VerifierVerdict

REL = "data_vault/01 - Concepts/Offset vs Keyset Pagination.md"


def _vault(tmp_path: Path, *names: str) -> Path:
    for rel in names:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("---\ntype: concept\n---\n\nBody.\n", encoding="utf-8")
    return tmp_path


def test_a_bare_filename_and_its_full_path_are_one_note(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    vault = _vault(tmp_path, REL)

    with caplog.at_level(logging.WARNING):
        out = normalise_notes(
            vault,
            ["Offset vs Keyset Pagination.md", REL, "Ghost.md", "", 7, REL],
        )

    assert out == [REL]
    assert "Ghost.md" in caplog.text  # dropped, and said so


def test_a_bare_filename_matching_two_notes_is_dropped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    vault = _vault(tmp_path, "data_vault/a/Same.md", "data_vault/b/Same.md")
    with caplog.at_level(logging.WARNING):
        assert normalise_notes(vault, ["Same.md"]) == []
    assert "several notes" in caplog.text


def test_the_record_restores_what_a_later_agent_write_dropped(tmp_path: Path) -> None:
    vault = _vault(tmp_path, REL, "data_vault/01 - Concepts/Updated.md")
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)
    report = cycles / "cycle-001-research.json"
    record = CycleRecord(vault)
    # batch 1 (new): its agent lists a failure and a link; the pipeline sees the file
    report.write_text(
        json.dumps(
            {
                "notes_created": ["Offset vs Keyset Pagination.md"],
                "capture_failures": [{"url": "u1"}],
                "new_wikilinks_discovered": ["A"],
            }
        )
    )
    record.absorb(report, [REL])
    # batch 2 (update) rewrites the report whole: no created notes, other lists
    report.write_text(
        json.dumps({"notes_created": [], "capture_failures": [{"url": "u2"}]})
    )
    record.absorb(report, [])
    (cycles / "cycle-001-update-outcomes.json").write_text(
        json.dumps(
            {
                "cycle": 1,
                "results": [
                    {
                        "path": "data_vault/01 - Concepts/Updated.md",
                        "outcome": "revised",
                        "status": "passed",
                        "row": {"n": 1},
                    },
                    {
                        "path": "data_vault/x.md",
                        "outcome": "confirmed",
                        "status": "passed",
                        "row": {"n": 2},
                    },
                    {
                        "path": "data_vault/y.md",
                        "outcome": "revised",
                        "status": "failed",
                        "row": {"n": 3},
                    },
                ],
            }
        )
    )

    record.apply(cycles, report, 1)

    doc: dict[str, Any] = json.loads(report.read_text())
    assert doc["notes_created"] == [REL]
    assert doc["notes_updated"] == ["data_vault/01 - Concepts/Updated.md"]
    assert len(doc["update_outcome_results"]) == 3
    assert len(doc["update_outcomes"]) == 3
    assert doc["capture_failures"] == [{"url": "u1"}, {"url": "u2"}]
    assert doc["new_wikilinks_discovered"] == ["A"]


def test_the_verifier_verifies_a_passed_outcome_the_report_lost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    vault = _vault(tmp_path, "data_vault/01 - Concepts/Updated.md")
    cycles = vault / "_pipeline" / "cycles"
    cycles.mkdir(parents=True)
    rel = "data_vault/01 - Concepts/Updated.md"
    (cycles / "cycle-001-update-outcomes.json").write_text(
        json.dumps(
            {
                "cycle": 1,
                "results": [
                    {"path": rel, "outcome": "revised", "status": "passed"},
                    {
                        "path": "data_vault/c.md",
                        "outcome": "confirmed",
                        "status": "passed",
                    },
                    {
                        "path": "data_vault/f.md",
                        "outcome": "revised",
                        "status": "failed",
                    },
                ],
            }
        )
    )
    seen: list[str] = []

    def fake(**kw: Any) -> VerifierVerdict:
        seen.append(kw["note_rel"])
        return VerifierVerdict(note_path=kw["note_rel"], status="verified")

    monkeypatch.setattr(verifier, "_call_verifier", fake)

    with caplog.at_level(logging.ERROR):
        summary = verifier.run_verifier_stage(
            vault,
            1,
            {"notes_created": [], "notes_updated": []},  # what the last agent left
            settings={"stages": {"verifier": {"enabled": True}}},
        )

    assert seen == [rel]  # the confirmed and the failed outcome are not owed it
    assert [v.status for v in summary.verdicts] == ["verified"]
    assert "does not list the note" in caplog.text  # the mismatch is an ERROR


def test_a_note_listed_twice_is_verified_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _vault(tmp_path, REL)
    seen: list[str] = []

    def fake(**kw: Any) -> VerifierVerdict:
        seen.append(kw["note_rel"])
        return VerifierVerdict(note_path=kw["note_rel"], status="verified")

    monkeypatch.setattr(verifier, "_call_verifier", fake)
    verifier.run_verifier_stage(
        vault,
        1,
        {"notes_created": [REL], "notes_updated": [REL]},
        settings={"stages": {"verifier": {"enabled": True}}},
    )
    assert seen == [REL]
