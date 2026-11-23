"""Spec 084 T006: the quarantine sweep keeps its pointers in the backlog store."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_framework.pipeline import state_layout as L
from research_framework.pipeline.orchestrator import _quarantine_rejected_notes

from .test_rejected_note_handling import _git_vault_with_committed_note, _note


def _entries(vault: Path) -> list[dict[str, Any]]:
    data = json.loads(L.research_backlog_path(vault).read_text(encoding="utf-8"))
    return data["entries"]


def test_sweep_upserts_one_entry_per_stem_with_its_kind(tmp_path: Path) -> None:
    vault = _git_vault_with_committed_note(
        tmp_path,
        "Refreshed",
        "---\ntitle: Refreshed\ntype: concept\nverifier_status: accepted\n---\nOld.\n",
    )
    _note(vault, "Fresh", "rejected", notes="no source")
    (vault / "data_vault" / "Refreshed.md").write_text(
        "---\ntitle: Refreshed\ntype: concept\nverifier_status: rejected\n"
        "verifier_notes: fabricated\n---\nDraft.\n",
        encoding="utf-8",
    )

    assert _quarantine_rejected_notes(vault) == 2
    assert _quarantine_rejected_notes(vault) == 0

    by_stem = {e["stem"]: e for e in _entries(vault)}
    assert set(by_stem) == {"Fresh", "Refreshed"}
    assert by_stem["Fresh"]["kind"] == "rewrite"
    assert by_stem["Fresh"]["detail"] == "no source"
    assert by_stem["Refreshed"]["kind"] == "retry"
    assert {e["status"] for e in by_stem.values()} == {"open"}
    assert {e["origin"] for e in by_stem.values()} == {"quarantine"}


def test_operator_entries_survive_every_sweep(tmp_path: Path) -> None:
    vault = tmp_path / "v"
    store = L.research_backlog_path(vault)
    store.parent.mkdir(parents=True)
    mine = {
        "id": "topic:my own topic",
        "title": "My own topic",
        "origin": "operator",
        "status": "open",
        "status_by": "operator",
        "status_written": "open",
        "detail": "Do not rewrite quarantined note: foo until Q3",
        "owner": "me",
    }
    closed = {
        "id": "quarantine:bad-one",
        "title": "bad-one",
        "origin": "quarantine",
        "status": "dropped",
        "status_by": "operator",
        "status_written": "dropped",
        "stem": "bad-one",
        "kind": "rewrite",
        "reviewer": "me",
    }
    store.write_text(
        json.dumps({"schema_version": "1.0", "entries": [mine, closed]}),
        encoding="utf-8",
    )
    _note(vault, "bad-one", "rejected", notes="again")

    _quarantine_rejected_notes(vault)
    _quarantine_rejected_notes(vault)

    by_id = {e["id"]: e for e in _entries(vault)}
    for original in (mine, closed):
        kept = by_id[original["id"]]
        for key, value in original.items():
            assert kept[key] == value, (original["id"], key)
    assert by_id["quarantine:bad-one"]["status"] == "dropped"
