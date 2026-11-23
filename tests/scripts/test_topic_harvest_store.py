"""Spec 084 T004: the harvest records follow-ups in the backlog store."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from research_framework.pipeline import backlog
from research_framework.pipeline import state_layout as L

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "topic_harvest.py"
_SRC_DIR = str(Path(__file__).parent.parent.parent / "src")


def _run(vault: Path, cycle: int) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": _SRC_DIR}
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(vault), str(cycle)],
        capture_output=True,
        text=True,
        env=env,
    )


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "data_vault" / "concept").mkdir(parents=True)
    (vault / "_pipeline" / "cycles").mkdir(parents=True)
    backlog.create_empty(vault)
    return vault


def _note(vault: Path, name: str, body: str) -> None:
    (vault / "data_vault" / "concept" / name).write_text(body, encoding="utf-8")


def _research(vault: Path, cycle: int, created: list[str], **extra: Any) -> None:
    report = {
        "cycle": cycle,
        "phase": "research",
        "notes_created": created,
        "notes_updated": [],
        **extra,
    }
    (vault / "_pipeline" / "cycles" / f"cycle-{cycle:03d}-research.json").write_text(
        json.dumps(report), encoding="utf-8"
    )


def _entries(vault: Path) -> list[dict[str, Any]]:
    data = json.loads(L.research_backlog_path(vault).read_text(encoding="utf-8"))
    return data["entries"]


def test_two_orphans_and_a_flag_become_three_open_entries(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _note(vault, "A.md", "See [[Alpha]] and [[Beta]].\n")
    _note(vault, "B.md", "Also [[Alpha]].\n")
    _research(
        vault, 1, ["concept/A.md", "concept/B.md"], new_wikilinks_discovered=["Gamma"]
    )

    result = _run(vault, 1)
    assert result.returncode == 0, result.stderr

    by_title = {e["title"]: e for e in _entries(vault)}
    assert {t: (e["origin"], e["status"]) for t, e in by_title.items()} == {
        "Alpha": ("harvest", "open"),
        "Beta": ("harvest", "open"),
        "Gamma": ("researcher", "open"),
    }
    assert by_title["Alpha"]["citation_count"] == 2
    assert by_title["Alpha"]["first_seen_cycle"] == 1
    view = backlog.view_path(vault).read_text(encoding="utf-8")
    for title in ("Alpha", "Beta", "Gamma"):
        assert f"**{title}**" in view


def test_a_written_note_resolves_its_entry(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _note(vault, "A.md", "See [[Ghost]].\n")
    _research(vault, 1, ["concept/A.md"])
    assert _run(vault, 1).returncode == 0
    assert [e["status"] for e in _entries(vault)] == ["open"]

    _note(vault, "Ghost.md", "# Ghost\n\nNow written.\n")
    _note(vault, "C.md", "Nothing to cite.\n")
    _research(vault, 2, ["concept/C.md"])
    assert _run(vault, 2).returncode == 0

    (entry,) = _entries(vault)
    assert entry["title"] == "Ghost"
    assert entry["status"] == "resolved"
    assert entry["status_by"] == "harvest"


def test_coverage_gaps_are_not_stored(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    L.coverage_targets_path(vault).write_text(
        json.dumps(
            {
                "categories": [
                    {
                        "name": "architecture",
                        "note_type": "concept",
                        "target_count": 5,
                        "met_count": 2,
                        "required": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    _note(vault, "N.md", "See [[Ghost]].\n")
    _research(vault, 1, ["concept/N.md"])

    assert _run(vault, 1).returncode == 0

    manifest = json.loads(
        (vault / "_pipeline" / "cycles" / "cycle-001-harvest.json").read_text("utf-8")
    )
    assert [g["name"] for g in manifest["coverage_gaps"]] == ["architecture"]
    assert [e["title"] for e in _entries(vault)] == ["Ghost"]
    assert "architecture" not in L.research_backlog_path(vault).read_text("utf-8")
    # ...yet the view still lists the gap, rendered live from the targets.
    assert "`architecture`" in backlog.view_path(vault).read_text("utf-8")


def test_a_malformed_store_is_left_alone_and_the_harvest_still_succeeds(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    store = L.research_backlog_path(vault)
    store.write_text("{not json", encoding="utf-8")
    _note(vault, "A.md", "See [[Ghost]].\n")
    _research(vault, 1, ["concept/A.md"])

    result = _run(vault, 1)

    assert result.returncode == 0
    assert store.read_text(encoding="utf-8") == "{not json"
    manifest = vault / "_pipeline" / "cycles" / "cycle-001-harvest.json"
    assert manifest.is_file()
