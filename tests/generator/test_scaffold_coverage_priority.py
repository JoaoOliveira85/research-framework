"""Scaffold must carry spec priorities into coverage-targets.json and must not
destroy live state on re-scaffold (#54)."""

from __future__ import annotations

import json
from pathlib import Path

from research_framework.generator.scaffold import scaffold
from research_framework.pipeline import state_layout
from research_framework.pipeline.coverage import load_targets
from research_framework.pipeline.research_plan import _build_coverage_state
from research_framework.spec.parser import parse
from research_framework.spec.schema import SpecConfig


def _spec(sample_spec_path: Path, **priorities: int) -> SpecConfig:
    spec = parse(sample_spec_path)
    for cat in spec.coverage_targets.categories:
        cat.priority = priorities.get(cat.name, 0)
    return spec


def _targets_file(vault: Path) -> Path:
    return state_layout.coverage_targets_path(vault)


def _write_note(vault: Path, name: str) -> None:
    folder = vault / "data_vault" / "01 - Concepts"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.md").write_text(
        "---\ntype: concept\ncoverage_category: concepts\n---\n\nBody.\n",
        encoding="utf-8",
    )


def test_scaffold_carries_spec_priority_to_planner(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    scaffold(_spec(sample_spec_path, concepts=90), vault)

    state = {s.name: s for s in _build_coverage_state(load_targets(vault), vault)}
    assert state["concepts"].priority == 90
    assert state["secondary-concepts"].priority == 0
    entry = json.loads(_targets_file(vault).read_text())["categories"][0]
    assert entry["display_name"] == ""
    assert "expected_filenames" in entry


def test_rescaffold_recomputes_met_count_and_keeps_cycle_number(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    spec = _spec(sample_spec_path)
    scaffold(spec, vault)
    for i in range(3):
        _write_note(vault, f"Concept {i}")
    data = json.loads(_targets_file(vault).read_text())
    data["cycle_number"] = 7
    _targets_file(vault).write_text(json.dumps(data), encoding="utf-8")

    scaffold(spec, vault)

    again = json.loads(_targets_file(vault).read_text())
    met = {c["name"]: c["met_count"] for c in again["categories"]}
    assert met["concepts"] == 3
    assert met["secondary-concepts"] == 0
    assert again["cycle_number"] == 7


def test_rescaffold_keeps_hand_set_priority_when_spec_priority_unset(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    scaffold(_spec(sample_spec_path), vault)
    data = json.loads(_targets_file(vault).read_text())
    for c in data["categories"]:
        c["priority"] = 75
    _targets_file(vault).write_text(json.dumps(data), encoding="utf-8")

    scaffold(_spec(sample_spec_path), vault)

    prios = {c.name: c.priority for c in load_targets(vault).categories}
    assert prios == {"concepts": 75, "secondary-concepts": 75}


def test_rescaffold_nonzero_spec_priority_beats_existing_json(
    sample_spec_path: Path, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    scaffold(_spec(sample_spec_path), vault)
    data = json.loads(_targets_file(vault).read_text())
    for c in data["categories"]:
        c["priority"] = 75
    _targets_file(vault).write_text(json.dumps(data), encoding="utf-8")

    scaffold(_spec(sample_spec_path, concepts=90), vault)

    prios = {c.name: c.priority for c in load_targets(vault).categories}
    assert prios == {"concepts": 90, "secondary-concepts": 75}
